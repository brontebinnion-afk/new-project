"""Single-household, read-only feed to iCloud mirror. Run behind HTTPS for remote access."""
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import caldav
import requests
from flask import Flask, jsonify, request, send_file
from icalendar import Calendar

app = Flask(__name__)
ROOT = Path(__file__).parent
DATA = Path(os.environ.get('SYNC_DATA_DIR', ROOT / '.data'))
DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
LOCK = threading.Lock()
STATE = {'running': False, 'last_run': None, 'message': 'Connect your calendars to begin.', 'copied': 0}


def config():
    path = DATA / 'config.json'
    return json.loads(path.read_text()) if path.exists() else {}


def save(value):
    path = DATA / 'config.tmp'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream)
    path.replace(DATA / 'config.json')


def destination(cfg):
    client = caldav.DAVClient(url='https://caldav.icloud.com/', username=cfg['apple_id'], password=cfg['password'])
    calendars = client.principal().calendars()
    matches = [c for c in calendars if str(c.url) == cfg.get('destination')]
    if len(matches) != 1:
        raise ValueError('Select your destination calendar again.')
    return matches[0]


def mirror_items(raw, source_id, label):
    original = Calendar.from_ical(raw)
    groups = {}
    zones = [c for c in original.subcomponents if c.name == 'VTIMEZONE']
    for component in original.subcomponents:
        if component.name != 'VEVENT':
            continue
        uid = str(component.get('UID', ''))
        if not uid:
            raise ValueError('An event has no ID; this feed cannot be safely synced.')
        groups.setdefault(uid, []).append(component)
    result = {}
    for uid, components in groups.items():
        masters = [c for c in components if 'RECURRENCE-ID' not in c]
        if masters and str(masters[0].get('STATUS', '')).upper() == 'CANCELLED':
            continue
        new_uid = 'family-sync-' + hashlib.sha256((source_id + '\0' + uid).encode()).hexdigest()
        output = Calendar()
        output.add('prodid', '-//Family Sync//EN')
        output.add('version', '2.0')
        for zone in zones:
            output.add_component(zone)
        for event in components:
            for prop in ('UID', 'ORGANIZER', 'ATTENDEE', 'METHOD', 'URL'):
                event.pop(prop, None)
            event.add('uid', new_uid)
            event['SUMMARY'] = f"{label} · {event.get('SUMMARY', 'Appointment')}"
            event.subcomponents = [c for c in event.subcomponents if c.name != 'VALARM']
            output.add_component(event)
        result[new_uid] = output.to_ical()
    return result


def read_feed(url):
    url = url.replace('webcal://', 'https://', 1)
    parsed = urlparse(url)
    # Only provider-hosted HTTPS feeds; never fetch arbitrary local or private addresses.
    host = (parsed.hostname or '').lower()
    allowed = host.endswith('.icloud.com') or host in ('outlook.live.com', 'outlook.office365.com', 'outlook.office.com')
    if parsed.scheme != 'https' or not allowed or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Use an iCloud or Outlook HTTPS calendar publishing link.')
    response = requests.get(url, timeout=45, allow_redirects=False)
    response.raise_for_status()
    if len(response.content) > 15_000_000:
        raise ValueError('Calendar feed is too large.')
    if b'BEGIN:VCALENDAR' not in response.content:
        raise ValueError('The link did not return a calendar feed.')
    return response.content


def sync():
    if not LOCK.acquire(blocking=False):
        return
    STATE['running'] = True
    try:
        cfg = config()
        if not cfg.get('enabled'):
            return
        target = destination(cfg)
        # Read every source successfully before making any destination changes.
        desired = {}
        for source in cfg['sources']:
            desired.update(mirror_items(read_feed(source['url']), source['id'], source['label']))
        existing = {}
        for event in target.events():
            uid = str(Calendar.from_ical(event.data).walk('VEVENT')[0].get('UID', ''))
            if uid.startswith('family-sync-'):
                existing[uid] = event
        for uid, payload in desired.items():
            if uid in existing:
                event = existing[uid]
                if Calendar.from_ical(event.data).to_ical() != payload:
                    event.data = payload.decode()
                    event.save()
            else:
                target.save_event(payload.decode())
        # Delete only objects in our own namespace, never manually created events.
        for uid, event in existing.items():
            if uid not in desired:
                event.delete()
        STATE.update(last_run=time.time(), message='Sync completed. Your family calendar is up to date with the available feeds.', copied=len(desired))
    except Exception:
        # Provider exceptions can contain private URLs and credentials. Never expose them.
        STATE['message'] = 'Sync could not finish. Check your feed links, Apple app password, and calendar access. It will retry automatically.'
    finally:
        STATE['running'] = False
        LOCK.release()


@app.before_request
def same_origin():
    if request.method == 'POST':
        origin = request.headers.get('Origin')
        if origin and origin != request.host_url.rstrip('/'):
            return jsonify(error='Open setup directly in this browser.'), 403
        if not request.is_json:
            return jsonify(error='JSON required.'), 415


@app.get('/')
def index():
    return send_file(ROOT / 'index.html')


@app.get('/api/status')
def status():
    cfg = config()
    return jsonify(**STATE, connected=bool(cfg.get('destination')), enabled=cfg.get('enabled', False), sources=[{'label': s['label'], 'id': s['id']} for s in cfg.get('sources', [])])


@app.post('/api/calendars')
def calendars():
    body = request.get_json()
    try:
        client = caldav.DAVClient(url='https://caldav.icloud.com/', username=body['apple_id'], password=body['password'])
        available = client.principal().calendars()
        choices = [{'id': str(c.url), 'name': c.name or 'Unnamed calendar'} for c in available]
        with LOCK:
            cfg = config()
            cfg.update(apple_id=body['apple_id'], password=body['password'], enabled=False)
            save(cfg)
        return jsonify(calendars=choices)
    except Exception:
        return jsonify(error='Could not connect. Check your Apple Account email and app-specific password.'), 400


@app.post('/api/setup')
def setup():
    body = request.get_json()
    sources = body.get('sources', [])
    if not sources or len(sources) > 20 or not body.get('destination') or not body.get('confirmed'):
        return jsonify(error='Choose a destination, add a source, and confirm it is separate from the sources.'), 400
    try:
        checked = []
        for s in sources:
            label = str(s['label']).strip()[:60]
            if not label:
                raise ValueError()
            url = s['url'].strip()
            source_id = hashlib.sha256(url.encode()).hexdigest()
            mirror_items(read_feed(url), source_id, label)
            checked.append({'label': label, 'url': url, 'id': source_id})
        with LOCK:
            cfg = config()
            cfg.update(sources=checked, destination=body['destination'], enabled=True)
            destination(cfg)
            save(cfg)
        threading.Thread(target=sync, daemon=True).start()
        return jsonify(ok=True)
    except Exception:
        return jsonify(error='Setup could not be verified. Check each calendar feed and the selected destination.'), 400


@app.post('/api/sync')
def manual_sync():
    threading.Thread(target=sync, daemon=True).start()
    return jsonify(ok=True)


@app.post('/api/pause')
def pause():
    with LOCK:
        cfg = config()
        cfg['enabled'] = False
        save(cfg)
    return jsonify(ok=True)


def worker():
    while True:
        sync()
        time.sleep(900)


if __name__ == '__main__':
    threading.Thread(target=worker, daemon=True).start()
    app.run(host=os.environ.get('SYNC_BIND', '127.0.0.1'), port=8000, debug=False)

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from icalendar import Calendar

FEED = b'''BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:original\r\nDTSTART:20261101T100000Z\r\nDTEND:20261101T110000Z\r\nSUMMARY:Lunch\r\nRRULE:FREQ=WEEKLY;COUNT=3\r\nATTENDEE:mailto:test@example.com\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n'''

class Event:
    def __init__(self, data):
        self.data = data
        self.deleted = False
        self.saved = False
    def delete(self):
        self.deleted = True
    def save(self):
        self.saved = True

class Target:
    def __init__(self, events=()):
        self.items = list(events)
    def events(self):
        return self.items
    def save_event(self, data):
        self.items.append(Event(data))


def prepare(monkeypatch, target, feed=FEED):
    monkeypatch.setattr(app, 'config', lambda: {'enabled': True, 'sources': [{'id': 'a', 'url': 'unused', 'label': 'Alex'}]})
    monkeypatch.setattr(app, 'destination', lambda cfg: target)
    monkeypatch.setattr(app, 'read_feed', lambda url: feed)


def test_identity_recurrence_and_no_invitations():
    a = app.mirror_items(FEED, 'a', 'Alex')
    assert a.keys() == app.mirror_items(FEED, 'a', 'Alex').keys()
    assert a.keys() != app.mirror_items(FEED, 'b', 'Alex').keys()
    event = Calendar.from_ical(next(iter(a.values()))).walk('VEVENT')[0]
    assert str(event['SUMMARY']) == 'Alex · Lunch'
    assert 'RRULE' in event and 'ATTENDEE' not in event


def test_create_update_delete_preserves_family_events(monkeypatch):
    manual = Event(FEED)
    target = Target([manual])
    prepare(monkeypatch, target)
    app.sync()
    assert len(target.items) == 2
    app.sync()
    assert len(target.items) == 2
    prepare(monkeypatch, target, FEED.replace(b'Lunch', b'Dinner'))
    app.sync()
    assert target.items[1].saved
    assert 'Dinner' in target.items[1].data
    prepare(monkeypatch, target, b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n')
    app.sync()
    assert target.items[1].deleted
    assert not manual.deleted and not manual.saved


def test_failed_feed_never_deletes(monkeypatch):
    owned = Event(next(iter(app.mirror_items(FEED, 'a', 'Alex').values())))
    target = Target([owned])
    prepare(monkeypatch, target)
    def failure(url):
        raise RuntimeError('private URL')
    monkeypatch.setattr(app, 'read_feed', failure)
    app.sync()
    assert not owned.deleted
    assert 'private URL' not in app.STATE['message']


def test_cancelled_series_removed():
    assert not app.mirror_items(FEED.replace(b'SUMMARY:Lunch', b'STATUS:CANCELLED\r\nSUMMARY:Lunch'), 'a', 'Alex')


def test_page_and_csrf():
    client = app.app.test_client()
    assert client.get('/').status_code == 200
    assert client.post('/api/pause', json={}, headers={'Origin': 'https://evil.example'}).status_code == 403

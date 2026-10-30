"""Stateless scheduled entry point. Credentials stay in an Actions secret."""
import json
import os
import sys
import tempfile

os.environ['SYNC_DATA_DIR'] = tempfile.mkdtemp(prefix='family-sync-')
from app import STATE, caldav, save, sync


def main():
    try:
        cfg = json.loads(os.environ['FAMILY_SYNC_CONFIG'])
        client = caldav.DAVClient(url='https://caldav.icloud.com/', username=cfg['apple_id'], password=cfg['password'])
        choices = client.principal().calendars()
        target = [c for c in choices if c.name == cfg.get('calendar_name', 'Family')]
        if len(target) != 1:
            print('Destination calendar name must match exactly one calendar visible to this Apple Account.')
            return 1
        import hashlib
        sources = cfg['sources']
        if not sources:
            raise ValueError()
        for source in sources:
            source['id'] = hashlib.sha256(source['url'].encode()).hexdigest()
        cfg.update(destination=str(target[0].url), enabled=True)
        save(cfg)
        sync()
        print(STATE['message'])
        return 0 if STATE['last_run'] else 1
    except Exception:
        print('Setup failed. Check FAMILY_SYNC_CONFIG. Private error details are hidden.')
        return 1


if __name__ == '__main__':
    sys.exit(main())

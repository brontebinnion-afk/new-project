# Gather — Family calendar sync

A mobile-friendly setup guide and an hourly, one-way iCloud/Outlook feed mirror into an existing shared iCloud Family calendar. Originals are read-only. This is implemented software; it has not been connected to your accounts or deployed.

## Set up from your iPhone

Open the project's setup page and follow the three steps. It generates your configuration locally in your browser. No credentials are sent by the setup page. The repository must first be uploaded to a **private GitHub repository**, including `.github/workflows/sync.yml`. Anyone administering that repository or modifying its workflows could access its secrets; use only trusted collaborators.

1. For each source iCloud calendar: Calendar → Calendars → ⓘ → Public Calendar → Share Link. Both partners must agree to publishing. Anyone with this link can read the published details.
2. For each Outlook/Hotmail calendar: Outlook on the web → Settings → Calendar → Shared calendars → Publish a calendar. Copy the ICS link. Safari's Request Desktop Website may be needed. Managed accounts may prohibit publishing.
3. Verify you can write to the destination Family calendar. Never include it as a source, even through a different feed URL. Use one installation per destination.
4. At account.apple.com, create an app-specific password with two-factor authentication enabled. Use the Apple Account that can write to Family. The service never needs your normal Apple password.
5. In the setup page, enter source labels and links, your Apple email, app-specific password, and exact destination name. Generate and copy the JSON.
6. GitHub repository → Settings → Secrets and variables → Actions → New repository secret. Name: `FAMILY_SYNC_CONFIG`. Value: the generated JSON. Keep it out of repository files and chat. Clear the page and clipboard after saving.
7. Actions → Family calendar sync → Run workflow. Inspect the result. Check for a copied appointment in Family, then test a source time change and deletion after the feed refreshes. Your original events must remain untouched by the service.
8. Keep Actions enabled. The workflow runs hourly at minute 17. GitHub schedules can be delayed, and feed providers control refresh timing. This is not instant sync. Monitor failed runs in Actions.

For reference, the secret's structure is:

```json
{
  "apple_id": "you@example.com",
  "password": "YOUR-APP-SPECIFIC-PASSWORD",
  "calendar_name": "Family",
  "sources": [
    {"label": "Alex · Personal", "url": "webcal://YOUR-ICLOUD-FEED"},
    {"label": "Sam · Outlook", "url": "https://outlook.live.com/YOUR-ICS-FEED"}
  ]
}
```

## Free hosting and limitations

Uses standard GitHub-hosted Linux Actions runners. A typical personal free account includes a limited private-repository Actions allowance; confirm your account's current allowance. About 720 scheduled runs/month may fit if runs are short, but runtime and other repositories affect usage. Keep paid usage disabled for a strict zero-cost limit. Syncing stops if allowance runs out. This is not a free-hosting guarantee or a deployed service. A GitHub account, secret entry, and initial verification are required.

Published feeds are necessary for this version. If either partner cannot publish a source calendar or does not consent, do not use this approach. A private-authentication adapter is not implemented. The destination is accessed through Apple's authenticated CalDAV service; special account restrictions or Family calendar visibility may prevent access. The first run checks the exact destination name and refuses ambiguous matches.

Recurring series, recurrence exceptions, time zones, and all-day dates are copied as iCalendar data. Guest invitations, organizers, URLs, and reminders are stripped. Source labels are added to titles. Destination edits to copies will be overwritten by later runs. Appointments outside a provider's published feed window are not mirrored; copies disappear when absent from a successful feed response. Feed failures stop that run before destination writes. A provider returning a valid but incomplete feed can still remove copies. Writes are not transactional; a later run retries partial changes.

Only `family-sync-` UID objects are updated/deleted. Manual Family events are left alone. Do not reuse that UID prefix for other software. A changed source feed URL changes its identity: copies are replaced on the next successful run. Removing a source from configuration removes its copies after the next successful run. Review source lists before saving changes.

To stop: disable the workflow in Actions and revoke the Apple app-specific password. Existing copies remain. Unpublish source feeds if desired. To remove copies manually, identify events by their source label; do not delete originals.

## Development / optional local service

Python 3.12+. From this checkout:

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

The setup page is served on port 8000. The cloud workflow uses `python cloud_sync.py`, not the local web process. The optional local API stores its configuration in `.data/config.json` with owner-only permissions and polls every 15 minutes. It binds loopback by default; it has no account login. Do not expose this API to the Internet or an untrusted network. The static setup page can instead be hosted without the API; it needs no server secrets.

Tests: install pytest, then `python -m pytest -q`. Tests use fake calendar servers; live Apple/Outlook behavior requires the account checks above. Future cloud tasks already have an isolated checkout; do not create Git worktrees unless explicitly requested.

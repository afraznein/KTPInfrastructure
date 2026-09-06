# support-poller

Polls all 24 fleet instances over A2S and pushes a public status document to
`ktpleague.gg`. This is the surviving remnant of the `support.ktpdod.com` web app,
adopted here when that vhost was decommissioned (2026-09-02/03).

## Why only these files

The old app was 26 files. `support-web.service` is stopped and its nginx vhost is out
of `sites-enabled`, so the web half is gone. What still runs is the poller timer, whose
import closure is exactly:

    tools/run_poller.py -> app.poller -> app.a2s, app.hostname

`app/__init__.py` is empty but required — `run_poller.py` does `from app import poller`,
and `poller.py` uses relative imports.

## Layout mirrors production deliberately

Paths here match `/opt/support-web` one-for-one, so `md5sum` compares directly between
this tree and the box. Flattening the package would break both the relative imports and
that comparison.

## Deploy

Not automated. The unit runs `/opt/support-web/venv/bin/python tools/run_poller.py` as
`supportweb`, on a timer, reading `/etc/ktp/support-web.env` (which holds the push
secret — never commit it).

⚠️ `support-poller.service` still lists `/var/www/support.ktpdod.com/status` in
`ReadWritePaths=`. That docroot is being removed; the local status write is now vestigial
and the unit should drop that path once the docroot goes.

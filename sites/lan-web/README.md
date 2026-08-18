# WSDoD LAN 2026 — web service

Dedicated FastAPI service for the LAN site: Discord login, a captain-only
seeding poll, result reporting, an auto-fed bracket, awards, uploads and the
public dossier site. Separate from the AC API, which keeps that service's
surface narrow. Voice on all player-facing copy is WSDoD **we/us/our**.

⚠️ **It serves `dodworldseries.com` at the ROOT, not `/lan/`.** *(Corrected
2026-08-14 — this said "runs behind nginx at `/lan/`", and `/lan/admin` 404s.)*
nginx has a single `location /` proxying to `127.0.0.1:8099`,
`LAN_WEB_ROOT_PATH` is empty, and the app mounts the built static site itself
(`LAN_SITE_DIR`, `LAN_SITE_AT_ROOT=1`) **after** every router — `Mount("/")`
matches every path, so a router registered later would never be reached.
🔑 That mount is why Discord OAuth, uploads and the awards API are same-origin
with the site: one host, one cookie, one redirect URI. Do not "tidy" it into a
separate vhost without re-solving all three.

⚠️ **This is no longer "Phase 0".** *(Corrected 2026-08-14 — it claimed the
poll, schedule and bracket UIs were still to come. They shipped, along with
awards, veto, stations, check-in, photos and feedback.)*

## Layout

```
app/
  main.py        FastAPI entry (+ SessionMiddleware, root_path)
  config.py      env-backed settings
  db.py          thin PyMySQL helpers (query_one/query_all/execute)
  auth.py        Discord OAuth + session_user / current_identity / require_captain
  routes/        16 routers — public, auth, admin, api, poll, mappoll, schedule,
                 bracket, veto, stations, placements, checkin, demo, extras,
                 match. Registered BEFORE the static mount, which claims "/".
  site_gate.py   serves the built site's HTML and strips the stats payload when
                 stats_published is 0 — the flag cannot hide data baked into a
                 static file, so the withholding happens on the way out
  stat_awards.py generated awards: candidates, staff nomination, master select
  admin_audit.py lan_admin_audit writer + reader
  match_stats.py per-match scoreboard, gated on stats_published
  templates/     field-manual base + per-feature pages
migrations/      0001 … 0018. Awards framework is 0015-0018.
migrate.py       idempotent migration runner (tracks applied files)
tools/lan_admin.py   CLI to seed teams/players + link Discord IDs
tools/load_match_scoreboard.py  loads the generated per-match scoreboard
deploy/          systemd unit + nginx snippet
```

## Identity model (the linchpin)

`lan_players.discord_id` is what ties a Discord login to a roster. Two states,
kept distinct in `auth.py`:

- **signed in** (`session_user`) — authenticated via Discord, snowflake known
- **linked** (`current_identity`) — that snowflake matches a `lan_players` row

A user can be signed in without being linked (logged in, not yet drafted).
`is_captain` gates the poll and result reporting.

## Local dev

```bash
python -m venv venv && . venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                            # fill LAN_WEB_SECRET_KEY + DB creds

# create the DB + user (see .env.example header), then:
python migrate.py
uvicorn app.main:app --reload --port 8099
```

`/health` works with no Discord app configured. To exercise the OAuth →
identity path before real rosters exist, register a dev Discord app (redirect
`http://127.0.0.1:8099/auth/callback`), then link your own Discord ID:

```bash
python tools/lan_admin.py add-team   --name "Test Team" --tag TT
python tools/lan_admin.py add-player  --team "Test Team" --display you \
      --discord <your-discord-id> --discord-name you --captain
```

## Deploy (prod)

1. Point the LAN domain at the box (A-record) + Let's Encrypt cert.
2. Register the Discord app; redirect `https://YOUR_DOMAIN/lan/auth/callback`.
3. `/opt/lan-web` ← this dir + a venv; secrets in `/etc/ktp/lan-web.env`
   (`LAN_WEB_ENV=prod`, `LAN_WEB_ROOT_PATH=/lan`, Discord creds, DB creds).
4. `python migrate.py`
5. Install `deploy/lan-web.service`; add `deploy/nginx-lan.conf.example` to the
   TLS server block; reload nginx.

## Blocked on (external prerequisites)

- **Domain + TLS** — Discord OAuth needs an HTTPS redirect; no bare-IP http.
- **Discord application** — client id/secret/redirect.
- **Drafted rosters** — populate `lan_players` (the poll can't open until then).

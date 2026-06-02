# WSDoD LAN 2026 — web service

Dedicated FastAPI service for the LAN site: Discord login, a captain-only
seeding poll, Saturday result reporting, and an auto-fed Sunday bracket. Runs
behind nginx at `/lan/`, separate from the AC API (keeps that service's
surface narrow). Voice on all player-facing copy is WSDoD **we/us/our**.

This directory is **Phase 0**: the identity foundation — schema, migrations,
and the full Discord OAuth + session + captain-gating wiring. The poll,
schedule, and bracket UIs land in later phases; their tables already exist.

## Layout

```
app/
  main.py        FastAPI entry (+ SessionMiddleware, root_path)
  config.py      env-backed settings
  db.py          thin PyMySQL helpers (query_one/query_all/execute)
  auth.py        Discord OAuth + session_user / current_identity / require_captain
  routes/        public.py (/, /health), auth_routes.py (/login /auth/callback /logout /me)
  templates/     field-manual base + index + me
migrations/      0001_init.sql  (lan_teams, lan_players, lan_seed_ballots, lan_schedule, lan_bracket)
migrate.py       idempotent migration runner (tracks applied files)
tools/lan_admin.py   CLI to seed teams/players + link Discord IDs (Phase-0 stand-in for the admin UI)
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

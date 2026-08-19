# ktpdod.com landing page — design & architecture

Companion to `prototype.html` (self-contained, open in any browser; the dashed amber
box bottom-right is a mockup-only tier switcher, not a real control).

Style source of record: `KTPAntiCheat/docs/bundles-web/styles.css`. The prototype
copies its tokens, type scale, panel/pill/field shapes verbatim. Deviations are
listed at the end — there are three, all deliberate.

---

## 1. Recommendations up front

1. **One page, tier-triaged — not two.** Public landing at `/`; the admin area is a
   section of the same page, rendered server-side only for qualifying sessions.
2. **Auth: reuse lan-web's Discord OAuth (`identify` scope) + an allowlist**, not
   guild roles. Two role values in one table. Do **not** invent a third auth system.
3. **`users.ini` is never touched by the web app — read or write.** Privilege
   requests are queued tickets a human applies over SSH. (§5, and loudly: the file
   holds **plaintext passwords** next to SteamIDs and flag strings.)
4. **Status = one server-side poller writing one public JSON** on the data server;
   the page fetches that file. No client ever queries a game server, `:8087`, or
   systemd. Admin-only detail comes from a separate authed endpoint.
5. **Report-a-problem posts to Discord via the existing relay**, new private
   channels, per-IP rate limit, honeypot, never echoed to any public surface.
6. **Ship standalone now** (per the TODO's own recommendation) — new nginx vhost +
   cert on the data server; don't gate on the league-site consolidation.

---

## 2. Information architecture

```
ktpdod.com  (new vhost on the data server — ktpdod.com is in NO server_name today)
│
├── Header (STATIC — not sticky, not animated; operator requirement)
│     brand · Status · Report · Sites · Admin · sign-in/who pill
│
├── Hero — one sentence of identity, no carousel, no motion
│
├── § Server status                          [public]
│     5 region panels (24 instances) — name + player count only
│     5 service tiles — HLTV relays / Match recording / Demo pipeline /
│                       Broadcast HUD / HUD web (separate; they fail independently)
│     └── Operational detail panel           [KTP admin only, server-rendered]
│           unit names, timestamps, failure detail
│
├── § Report a problem                       [public, unauthenticated write]
│     category · server (public labels) · description · optional Discord handle
│
├── § Everything KTP                         [public]
│     10 subdomain cards (list is already public) + Sponsors card
│     → https://github.com/sponsors/afraznein
│
└── § Admin                                  [tier-rendered]
      logged out : what access exists + "Sign in with Discord"
      1.3 admin  : request 1.3 moderator (.kick) + "your requests" list
      KTP admin  : all of the above, plus:
                     privilege request (KTP admin / seasonal captain / 1.3 mod)
                     approval queue (approve → checklist item, not a server change)
                     bot command hub (/ops, /ac, /ktp — copy-paste friendly)
```

Backend: one small FastAPI app (clone of the lan-web skeleton) on the data server,
nginx in front. Routes: `GET /` (tier-rendered page), `GET /status/public.json`
(static file written by the poller, nginx-served), `GET /api/status/detail`
(authed), `POST /api/report`, `POST /api/requests`, `POST /api/requests/{id}/…`
(authed), plus the lan-web OAuth trio (`/login`, `/auth/callback`, `/logout`).

## 3. One page or two? — one page

**Decision: one page, sections rendered by tier.** Reasoning:

- **The admin surface is small.** Two forms, a ticket list, and a command
  reference. That doesn't justify a second nav, a second URL, and a second place
  for the design to drift. The public content (status, hub) is the bulk, and
  admins want it too — a separate admin page would duplicate it or lack it.
- **The property already sprawls.** Ten subdomains, and `admin.ktpdod.com`
  already exists for the AC console. The landing page exists to *reduce* the
  number of places; adding an eleventh works against its own purpose.
- **The disclosure argument for two pages is void if rendering is server-side.**
  The only real risk of one page is shipping admin markup to logged-out clients.
  Don't: the Jinja template emits the admin section only when the session
  qualifies, and the ops-detail/approval data only comes from authed endpoints.
  A logged-out `view-source` shows nothing an anonymous visitor can't have.
- The 1.3-vs-KTP distinction is conditional rendering *within* the section, with
  the same enforcement server-side on every POST (never trust the rendering).

Mechanically the form POSTs live under `/api/...` routes of the same app — that is
plumbing, not a second page. The prototype's tier switcher demonstrates the three
renderings; in production there is no switcher and no hidden markup.

## 4. Auth — reuse lan-web, allowlist, two roles

**Existing, working pattern** (`KTPInfrastructure/sites/lan-web/app/auth.py`):
Discord OAuth with scope `identify` only; "admin" = env bootstrap IDs
(`LAN_ADMIN_DISCORD_IDS`) plus a DB table (`lan_admins`) granted from a staff page.

**Option A — allowlist (recommended).** Same code, one table:

```sql
CREATE TABLE ktpdod_admins (
  discord_id BIGINT PRIMARY KEY,
  role       ENUM('ktp','one3') NOT NULL,
  label      VARCHAR(64),
  added_by   BIGINT, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

`is_ktp_admin()` / `is_one3_admin()` mirror lan-web's `is_admin()`. KTP admins can
add/remove rows from the page (bootstrap set stays in env). Why A:

- Already built and battle-tested at the LAN; the delta is one column.
- No bot token in the web app, no extra OAuth scope, no per-login Discord API
  round-trip, no failure mode when the bot is missing from a guild.
- The population is small and slow-changing (a handful of KTP staff; 1.3 admin
  orgs are stable). Allowlist churn is a few rows a season.

**Option B — guild roles (`guilds.members.read` + bot token).** Auto-follows
Discord permission changes: someone de-modded in the 1.3 Discord loses site access
without anyone touching a table. Costs: an extra consent screen, a bot token held
by the web app (a new credential on an internet-facing service), membership
lookups against **two** guilds (KTP and 1.3) at login and on re-validation,
role-ID configuration per guild, and silent breakage when the bot is kicked or
the role renamed. For maybe a dozen people, that is machinery without a payoff —
and the failure mode of A (a stale allowlist row) is *visible and auditable*,
while B's (a bot permission problem) presents as "the site is broken."

Pick **A**. Revisit only if 1.3 moderator delegation grows to the point where KTP
staff are rubber-stamping allowlist edits weekly — that volume is B's use case.

**⚠️ The third-auth-system flag.** This property already runs two identity
systems: SteamID + password (bundles/profiles, tied to AC accounts) and Discord
OAuth (lan-web). That is one more than ideal. This design deliberately does **not
add a third** — it reuses the Discord OAuth implementation as-is, so the count
stays at two and the OAuth code stays one codebase. Long-term, whether AC pages
should also accept Discord login (SteamID-linked) is an operator decision — noted
in §9, not designed here.

## 5. `users.ini` — the request/approval flow (never a write path)

**⛔ The load-bearing fact: `users.ini` contains PLAINTEXT PASSWORDS on the same
lines as SteamIDs and access-flag strings.** Any web component that can read it
can leak every admin credential on the fleet; any component that can write it can
grant itself anything. Therefore the web app has **no code path that opens the
file, in either direction** — not "restricted", *absent*. The site's role stops
at a ticket in a database and a Discord ping. A human with SSH does the rest,
exactly as they do today; the site adds a paper trail, not a capability.

Consequences worth stating:

- The form **never collects a password.** The applying admin sets one and
  delivers it by Discord DM, out-of-band. The site never sees, stores, or
  displays a game-admin password — so a compromise of the site cannot leak one.
- The site also never *reads* users.ini to show "current grants." A ticket's
  `applied` state is set by the human who applied it. If tickets and reality
  drift, reality wins and the ticket log is the audit trail for finding out why.
- Grants go live at the **next nightly restart** (plugins/config load per
  process). The UI says so ("active after nightly restart") so nobody expects
  instant effect — and nobody is tempted to build the "just reload it live"
  write path this design exists to prevent.

**State machine** (`privilege_requests` table; every transition timestamped with
actor):

```
                 requester (1.3 or KTP admin, signed in)
                                │  POST /api/requests
                                ▼
                          ┌───────────┐
                          │ SUBMITTED │──── relay embed → private admin channel
                          └─────┬─────┘
              KTP admin reviews │ in the approval queue
             ┌──────────────────┴──────────────────┐
             ▼                                     ▼
       ┌──────────┐                          ┌──────────┐
       │ APPROVED │                          │ REJECTED │ (reason required,
       └────┬─────┘                          └──────────┘  shown to requester)
            │ a human edits users.ini over SSH,
            │ sets the password, DMs it to the grantee,
            │ then marks the ticket:
            ▼
       ┌─────────┐   nightly restart      ┌────────┐
       │ APPLIED │ ─────────────────────▶ │ ACTIVE │ (display state, not a row
       └─────────┘  (config loads)        └────────┘  transition — shown once the
                                                      restart after `applied_at`
                                                      has passed)
Terminal: REJECTED, plus REVOKED (a later removal, same human-applied path;
seasonal-captain grants are expected to end in REVOKED at the postseason sweep).
```

Rules: only KTP admins transition SUBMITTED→APPROVED/REJECTED; only KTP admins
mark APPLIED (self-approval of one's own request is blocked; the approver and
applier may be the same person, that's fine — it's one team). 1.3 admins may
request only the `one3_moderator` role. Every transition emits a relay embed to
the private admin channel, so the Discord log and the DB agree.

## 6. Status — data contracts

One poller (`ktpdod-status-poller`, systemd timer on the data server, every 60s)
produces **one public JSON** and **one gated JSON**. The page never talks to a
game server, `:8087`, or systemd; nginx serves the public file like any static
asset — one poll per minute serves every viewer.

**⚠️ `:8087` (hltv-api) is ufw source-scoped to the 5 game hosts.** The poller
runs on the data server where the service lives, so it reaches it over
**localhost**. That rule is never widened, and no admin-key-bearing endpoint is
ever fetched client-side. Same posture for anything gated: server-side only.

| Indicator | Source (poller-side) | Cadence | Public JSON gets | Gated JSON adds |
|---|---|---|---|---|
| 24 game instances | A2S info query per instance (public protocol; players connect to these ports anyway — but the page still doesn't print them) | 60s; 2s timeout, 3 consecutive misses = down (one lost UDP reply ≠ outage) | region, display name ("Atlanta #1"), up/down, players/max, region rollups | host:port, map, last-seen time, miss count |
| HLTV relays (24) | `systemctl is-active 'hltv@*'` — local | 60s | single rollup: n/24 up | per-unit state + since |
| Match recording (hltv-api) | `GET http://127.0.0.1:8087/…` health, **localhost only, no key in the page** | 60s | ok / degraded / down | HTTP status, latency, error text |
| Demo pipeline (hltv-demo-renamer) | unit active **and** a freshness probe (newest renamed demo age vs. recent match activity — "active but wedged" is this unit's real failure mode) | 60s | ok / degraded / down | unit state, queue depth, oldest pending |
| Broadcast HUD | `hud-observer.service` — local | 60s | ok / down | unit state + since |
| HUD web | `hud-observer-web.service` — local | 60s | ok / down | unit state + since |

Contract details:

- `public.json`: `{ "generated_at": …, "regions": [ { "name": "Atlanta", "up": 5,
  "total": 5, "players": 37, "instances": [ { "name": "Atlanta #1", "up": true,
  "players": 14, "max": 32 } ] } ], "services": [ { "id": "hltv-relays",
  "label": "HLTV relays", "state": "ok", "detail": "24/24" }, … ] }` — and that
  is the *whole* schema. **No IPs, no ports, no unit names, no maps, no error
  text** in the public file, ever; the poller writes only whitelisted fields, so
  a poller bug can't leak detail by accident (allowlist, not redaction).
- Staleness is a first-class state: the page compares `generated_at` to now and
  shows "status unavailable" past 3× the poll interval, rather than forever
  displaying the last good snapshot as if it were current. A dead poller must
  look dead.
- The page refreshes the JSON every 60s with jitter via `fetch`; no
  auto-animating counters (static header rule extends to temperament: the page
  updates, it doesn't *move*).
- `detail.json` sits outside the web root and is served only through the
  authed `GET /api/status/detail` route (KTP admins).
- Map names are deliberately withheld from the public page (they are technically
  public via A2S, but printing them adds nothing for the visitor and invites
  "why is my scrim on the front page" complaints — operator may overrule, §9).
- TODO.md suggests reusing `ktp-fleet-health.sh` judgement. That script runs
  per-host and drives alerting; the poller here is a *presentation* prober on the
  data server. Keep them separate processes but **align the thresholds** (3-miss
  rule) so the page and the alerts never disagree about whether something is
  down. If fleet-health later publishes its verdicts centrally, the poller can
  switch to consuming those — the JSON contract to the page doesn't change.

## 7. Report-a-problem — anti-abuse

It's a public unauthenticated write; treat it as hostile by default.

- **Transport:** `POST /api/report` → app validates → Discord Relay (existing
  pattern, secret held server-side in the app's env, exactly like
  `discord.ini`/`discord-relay.conf` consumers) → **new private ops channels**
  (one for general reports, one for player-behavior reports so cheating
  accusations don't sit in a broadly-visible ops room). Additionally an
  `intake_reports` DB row (timestamp, category, server label, body, IP hash)
  for audit and dedupe. Relay is primary; the row means a relay outage doesn't
  eat reports (poster retries from the row).
- **Rate limit, two layers:** nginx `limit_req` on the route (burst control) +
  app-level per-IP token bucket, 3 reports/hour, keyed on a salted hash of the
  IP (we need dedupe, not a stored IP register). 429 with a plain message.
- **Honeypot** hidden field (bots fill it → silent 200, dropped) + minimum
  fill time check. No CAPTCHA at launch — this community is small; add one only
  if abuse actually happens.
- **Size/shape:** category from a fixed enum, server from the fixed public
  label list, body ≤ 2000 chars, optional Discord handle ≤ 64. Everything is
  treated as untrusted text: relay embeds are built with plain fields (no
  markdown passthrough of user input into mentions — the relay's
  `allowed_mentions` passthrough is load-bearing elsewhere, so the report path
  sends `allowed_mentions: none`).
- **Never echoed:** no "recent reports" surface, no ticket-status page, no
  public IDs. The submitter sees only "sent". (A reply, if any, happens on
  Discord via the handle they chose to give.)

## 8. Deviations from the style source (all deliberate)

1. **Static header.** `nav { position: static }` vs. the siblings' sticky —
   operator requirement, explicitly not sticky, not animated.
2. **`--amber` (#e8a13c)** added for the *degraded* status state. The sibling
   palette has ok=blue and alert=red but no middle; a status page needs one.
   Used only for status pills/dots, never as a brand accent. Status is never
   conveyed by color alone (dot + text label everywhere).
3. **Fonts:** production self-hosts JetBrains Mono woff2 same-origin exactly as
   bundles-web does; the prototype is self-contained so it rides the fallback
   mono stack.

Also note: the brand is a **committed dark treatment** ("no light variant" per
the styles.css header). The page declares `color-scheme: dark` so light-mode UAs
render form controls correctly; there is intentionally no light theme, matching
every sibling site.

## 9. Open questions for the operator

*Reconciled 2026-08-05 against the operator answers in the ADDENDUM below. Resolved items are kept,
struck, so a stale answer cannot be picked up from this list later.*

**STILL OPEN — blocks build:**

1. **Channel role gating** — IDs received 2026-08-05, roles still owed. ✅ Guild
   **`579024206931689482`** · `#server-reports` **`1534624929729740890`** · `#player-reports`
   **`1534624984469737583`**. Report-a-problem is unblocked. What remains is **which role can read
   each** — the design assumes and recommends `#player-reports` be **narrower than ops**, and that is
   a Discord permission change, not a code change.
   📝 Put all three in **env** (`SUPPORT_DISCORD_GUILD_ID`, `..._CHANNEL_SERVER_REPORTS`,
   `..._CHANNEL_PLAYER_REPORTS`), matching how lan-web already handles
   `LAN_DISCORD_ANNOUNCE_ROLE_ID`. Not secrets, but they differ per environment and must not be
   hardcoded — a test post landing in a live ops room is the failure mode.

**STILL OPEN — does not block build:**

8. **Theme toggle — a property-wide decision, not a `support.` one.** *(reframed after reviewing
   `1911-ktp-beta.vercel.app/ktp`)* The root site has a **light/dark toggle**. Neither `support.` nor
   the AC pages have one: `bundles-web/styles.css` contains **zero** `prefers-color-scheme` /
   `data-theme` rules. So this prototype is *correct against its brief* — the gap is between **the AC
   pages and the new root**, not between this page and its style source. Adding a toggle here alone
   would make `support.` the odd one out in the other direction. **Decide once, for the property.**

9. **Does the root site link to `support.`?** *(still open)* Observed nav is
   *KTP · Season 10 · Admin · 1911 · WSDoD · Features* — **no support/status entry.** One nav line,
   cheaper to agree now than to retrofit.

10. **Two "Admin" surfaces** *(new)*. The root site's nav already has an **Admin** section, and
    `support.` has a KTP-admin tier — plus `admin.ktpdod.com` exists as the AC review console. That is
    three things called "admin" to the same small group of people. Not a conflict to resolve today,
    but worth naming what each is for before all three are live and someone has to guess.

**RESOLVED — do not re-answer from this list:**

2. ~~Show current map on the public status page?~~ ✅ **YES**, plus parsed match-state badges from the
   MatchHandler-rewritten hostname. ADDENDUM §D — including the 🔴 right-to-left parsing trap.
3. ~~Seasonal-captain expiry: manual sweep or nag?~~ ✅ **NAG.** Calendar is fully derivable from the
   published seasonal framework; S10 = Fall 2026, first match Sunday **2026-09-13**. ADDENDUM §C —
   including the Super-Bowl-anchor override and why season *end* is deliberately not computed.
5. ~~`www.ktpdod.com` — include in the new vhost + cert (assumed yes).~~ ⛔ **NO — the assumption was
   WRONG and is now a hazard.** `ktpdod.com` and `www.ktpdod.com` belong to **Sears' in-progress root
   site**. `support.`'s `server_name` and cert must cover **`support.ktpdod.com` only**; including the
   apex or `www` would shadow their site on deploy. ADDENDUM §A.
6. ~~Sponsors placement.~~ ✅ **Promoted to a persistent header slot** (static, per the no-moving-header
   requirement). Hub card removed. ADDENDUM §E.
7. ~~`api` / `admin` on the public hub grid.~~ ✅ **No.** `api` removed outright; `admin` relocated into
   the KTP-admin tier.

## 10. Build notes (when this goes real)

- New nginx vhost `ktpdod.com www.ktpdod.com` + certbot cert on the data server
  (verified 2026-08-03: no existing `server_name` carries the apex).
- App: clone lan-web skeleton (FastAPI + Authlib + session middleware), new DB
  schema (`ktpdod_admins`, `privilege_requests`, `intake_reports`) with its own
  MySQL user and **per-table GRANTs** (the AC deploys have twice proven a missed
  grant fails silently or blocks startup).
- Poller: one Python script + systemd timer, writes `public.json` atomically
  (tmp + rename) into the web root and `detail.json` outside it.
- The prototype's tier switcher and sample data are throwaway; the templates
  render per-session and the JSON contract in §6 replaces the hardcoded numbers.


### RESOLVED 2026-08-05 (operator) — `api` and `admin` are off the public grid

`api.ktpdod.com` is **removed entirely**: it is a backend for tooling, not a human destination, so it
has no place on a front door at any tier.

`admin.ktpdod.com` is **removed from the public hub and relocated into the KTP-admin block.** It is not
hidden — the hostname is already public and this is not a security control. The point is narrower: a
landing page should not advertise the admin entrance to logged-out visitors, and the people who need
the console are exactly the ones who will be signed in.

---

# ADDENDUM 2026-08-05 — operator answers

## A. Domain: `support.ktpdod.com` — and the root belongs to someone else

This site ships at **`support.ktpdod.com`**: new vhost, new cert.

✅ **RESOLVED 2026-08-05 — do NOT touch `ktpdod.com`.** A full website for the root is **already in
progress, built by Sears**. An earlier draft of this document recommended 301-ing the bare root at
`support.` as a placeholder. **That recommendation is withdrawn** — it would have collided with work
already underway.

🔴 **Concrete deployment trap, and it is easy to hit:** `support.`'s nginx `server_name` must list
**`support.ktpdod.com` and nothing else.** Do not add `ktpdod.com` or `www.ktpdod.com` "for
convenience". nginx resolves by `server_name` match, so a stray entry here would **shadow Sears' site
the moment it deploys**, and the symptom — the wrong site answering on the main domain — looks like
their bug, not ours. Same for TLS: issue a cert for `support.` alone, **not a SAN cert covering the
apex**, so certificate renewal for the two properties never contends.

**Coordination worth doing before build, not after:**
- Sears' site is the natural front door; **it should link to `support.`** (report a problem / server
  status). One line in their nav, cheaper to agree now than to retrofit.
- **Visual relationship is a real decision.** This design deliberately matches the AC pages
  (`bundles-web`) because those are the existing property. If the new root establishes a different
  look, `support.` becomes the odd one out — or the AC pages do. Worth asking what they are building
  toward before this is locked, rather than discovering the mismatch at launch.
- The subdomain hub grid on `support.` may be **partly redundant** once a real root site exists. Not a
  problem now — but the hub is the section most likely to be trimmed later, so do not over-invest in it.

## B. The two new Discord channels — concrete spec

Both **private**, both in the **KTP guild** (they carry player-identifying complaints; the 1.3 guild
has a different admin population). Reports arrive as relay embeds.

| | `#server-reports` | `#player-reports` |
|---|---|---|
| **Takes** | Server faults: crashes, lag/choke, wrong config, HLTV/demo problems, "server is down" | Conduct + cheating accusations against a named player |
| **Who reads** | Ops / infra admins | KTP admins (+ AC reviewers) |
| **Visibility** | Private, ops role | Private, **narrower than ops** — an accusation should not be visible to everyone who can restart a server |
| **Ping** | None by default | None by default |
| **Retention** | Normal | Treat as sensitive; do not forward screenshots out of channel |

**Why two and not one — this is the load-bearing reason:** an accusation of cheating is a *reputational
allegation about a named person*, made by an anonymous submitter with no evidence gate in front of it.
Mixing that into a general ops room means every "server feels laggy" reader also sees every unproven
accusation. That is how an unverified claim becomes a rumour before anyone reviews it.

**Embed shape** (same fields both channels): category · server label · body (≤2000) · optional Discord
handle · timestamp · short intake ID for referencing the DB row. **`allowed_mentions: none`** on this
path — the relay's mention passthrough is load-bearing elsewhere, so it must be explicitly suppressed
here, not assumed off.

🔻 **Route on category, not on a checkbox.** If the submitter picks the destination, mistakes and
deliberate misrouting both land in the wrong room. The category enum decides.

📝 **Operator still owes:** the two channel IDs, and which role gates each. Everything else above
is buildable now.

## C. Seasonal-captain expiry — the site nags, and the calendar is derivable

Operator: **the site should nag when the season flips.** Good news — the published framework is
computable, so this needs **no season-date table to maintain**:

| Rule | Derivation | 2026 | 2027 |
|---|---|---|---|
| **Spring start** | Sunday after Super Bowl Sunday | 2026-02-15 | 2027-02-21 |
| **Fall start** | Sunday after Labor Day (1st Mon Sep) | **2026-09-13** | 2027-09-12 |
| **Spring BYE** | Easter Sunday (computus) | 2026-04-05 | 2027-03-28 |
| **Fall BYE** | Sunday of Thanksgiving week | 2026-11-22 | 2027-11-21 |
| **Window** | ≤ 12 match Sundays from start, BYE excluded | S10: **2026-09-13 → 2026-12-06** | — |

**S10 = Fall 2026, first match Sunday 2026-09-13.**

⚠️ **One anchor is not algorithmic: Super Bowl Sunday.** "Second Sunday in February" has held
2022–2026, but the NFL sets that date, not a rule — an 18-game season would move it. Every other
anchor (Labor Day, Easter, Thanksgiving) is defined by law or computus and safe to compute forever.
**So: compute by default, but keep a per-season override column.** A silent one-week drift in the
Spring start would expire captain grants a week early, which is exactly the failure a nag is meant to
prevent.

⚠️ **Season *end* is deliberately not derivable.** The framework commits to a window, explicitly not
to a fixed number of regular-season weeks. So the nag anchors on the **next season's start**, not on a
computed end — and the copy should say "S10 grants expire when S11 begins (2027-02-21)", never invent
a finish date the league has not set.

**Nag behaviour:** at 14 days before the next season start, every `ACTIVE` captain grant surfaces a
banner in the KTP-admin tier listing them with one-click **Revoke** ticket creation. It does **not**
auto-revoke — same principle as everywhere else here: the site proposes, a human applies. Grants also
carry the season they were issued for, so a stale one is visible even if a nag is missed.

## D. Public status shows current map **and** parsed match state

Operator: yes to map, and yes to hostname — because **KTPMatchHandler rewrites the hostname with live
match state** (`update_server_hostname()`), which A2S returns for free. Format:

`{base} - {TYPE} - {STATE}` — TYPE ∈ KTP · SCRIM · 12MAN · DRAFT · KTP OT · DRAFT OT · MATCH;
STATE ∈ PENDING · PAUSED · LIVE · LIVE - 1ST HALF · LIVE - 2ND HALF · LIVE - OT{n}

**Render TYPE and STATE as separate badges**, not as a raw hostname string — a scoreboard-style
"12MAN · LIVE - 2ND HALF" is the actual value here.

🔴 **Parsing trap — do not split on `" - "` left-to-right.** The *base* hostname already contains
that separator (`"KTP - Atlanta 1"`), so a naive split mangles every server name on the fleet. **Match
known TYPE/STATE tokens from the right**, and when nothing matches, show the hostname verbatim and no
badges. A server that has never hosted a match must not render as a parse error.

Map name is A2S-public, so no disclosure change. State is public the moment anyone opens the server
browser — this is surfacing what is already visible, more legibly.

## E. Sponsors — promoted to the header

Moved from a hub card + footer link into a **persistent header slot**, per operator. It stays a link,
not a banner: the header is static by requirement, so nothing about this animates or follows scroll.

## F. Auth — ✅ DECIDED 2026-08-05: websites use Discord, the AC client keeps SteamID

Left open, and the hesitation is well-placed. Recording the distinction that matters:

- **The website** adopting Discord login is low-risk and already the direction here.
- **The AC client** is a different question entirely. It identifies by **SteamID**, which is the thing
  VAC, the game server and every ban list key on. Adding Discord as a client-side identity introduces a
  second identifier that can be unlinked, transferred, or lost, for an account system whose whole value
  is that it maps to the Steam account actually playing.

✅ **Operator decision 2026-08-05, matching the recommendation: websites authenticate with Discord;
the AC client stays on SteamID for now.** Original reasoning kept below.

**Recommendation: do not tie the AC client to Discord.** Link them *server-side* if desired (a
`discord_id` column on the player row, populated by an opt-in "link your Discord" flow on the website)
— that gets the convenience without making Discord load-bearing for identity. **Not a decision needed
for this build.**

---

## G. Sears is on Supabase (Postgres) — does our side need a redesign? **No.**

**Recommendation: change nothing structural. Do not migrate, do not share a database.**

**Why a "big integration pass" is the wrong move:**

- The data server runs **MySQL only** — verified 2026-08-05: `mysql active`, `postgresql
  not-installed`, databases `hlstatsx` + `ktp_lan`. The AC API is MySQL (`ktp_ac_api` user), HLStatsX
  is MySQL, `ktp_lan` is MySQL. Moving any of that to Postgres to match a *different site's* backend
  would be a large, risky migration whose only payoff is aesthetic symmetry.
- **Supabase is hosted; our data lives beside the game servers.** That is not a flaw to reconcile — it
  reflects that the two systems have different jobs.
- 🔴 **Especially do not put `support.`'s data in Supabase.** This site's job is to work *when
  things are broken*. Putting its report intake and ticket state behind an external hosted DB means a
  network or provider problem takes down **the tool people use to report that problem**. Reports and
  privilege tickets stay in local MySQL on the data server, which is already inside `/opt/ktp-backup.sh`.

**The correct integration boundary is HTTP, not a shared schema.** Two independently-deployed systems
sharing database tables couple at the worst possible layer — either side's migration breaks the other,
silently. We already have the pattern: the AC API (`api.ktpdod.com`), the HLTV API on `:8087`, the
Discord Relay. If Sears' site needs live server status, it should call a **read-only JSON endpoint**
— which this design already produces (`public.json`, §6). That is one URL to agree on, versus a schema
to keep in sync forever.

### The two things actually worth aligning now — both cheap, both expensive later

1. **🔴 One Discord OAuth application, or two?** Supabase ships Discord auth, and this site reuses
   lan-web's. If each property registers its **own** Discord app, a user signing in to both gets
   **two consent prompts** and appears as two different OAuth grants — confusing, and it makes "is this
   the same person?" harder than it should be. A single Discord application supports **multiple
   redirect URIs**, so sharing one app across `ktpdod.com`, `support.` and lan-web is possible — but
   only if agreed **before** either side ships, because changing it later invalidates existing sessions.
   **Ask Sears which Discord app his Supabase auth points at.**

2. **🟠 Who owns league data?** Season 10 schedule, standings, rosters and captains currently live in
   **Google Sheets** (`/ktp` in KTPAdminBot reads them). If his site puts the same data in Supabase,
   that is a second source of truth for facts players act on. Decide the direction of flow — sheet →
   Supabase, or Supabase becomes canonical and the bot reads it — rather than letting both drift.
   ⚠️ This matters to `support.` in exactly one place: **seasonal-captain expiry**. That nag is safe
   either way because the season calendar is **computed, not looked up** (§C) — which is now a second
   reason to keep it that way.

**Nothing above blocks building `support.`.** Both are conversations to have with Sears, not
prerequisites.

---

## H. Deployment reality — measured on the data server 2026-08-05

`support.ktpdod.com` was added to Wix routing. Verified what that actually produced:

| Host | Resolves to | Serves today |
|---|---|---|
| `support.ktpdod.com` | **`<DATA_SERVER_IP>`** (data server) ✅ | **404** — no vhost yet, as expected |
| `ac` / `admin` / `api` / `bundles` / `fastdl` / `hud` / `netcode` / `profiles` / `watch` | `<DATA_SERVER_IP>` | own vhost each, own LE cert each |
| **`ktpdod.com` (apex)** | **`<DATA_SERVER_IP>` — OUR box** | ⚠️ **404** |
| **`www.ktpdod.com`** | **34.149.87.45 — external** | Sears' host |

DNS for `support.` is correct and nothing more is needed there.

### 🔴 The apex and `www` are split, and the apex points at us

`ktpdod.com` resolves to the data server while `www.ktpdod.com` resolves elsewhere. No vhost claims
the apex (confirmed: `server_name` across all of `/etc/nginx/` has no `ktpdod.com` / `www.ktpdod.com`
entry), so it falls to the `_` catch-all in `sites-available/default` and **returns 404**.

**So today, typing `ktpdod.com` gets a 404 from our infrastructure** — while `www.` reaches Sears'
site. That is a live split-brain on the main domain, and it is not ours to fix unilaterally: the apex
A record should almost certainly follow `www` to Sears' host, not sit on our box. **Flag it to whoever
holds the Wix DNS.**

🔴 This also sharpens §A's warning from theoretical to immediate: **the apex already resolves
here.** A stray `ktpdod.com` in `support.`'s `server_name` would capture it the instant nginx reloads
— no DNS change required, no warning. Keep `server_name support.ktpdod.com;` and nothing else.

### Reusable, already on the box

- **Rate limiting:** `/etc/nginx/conf.d/ktp-ratelimit.conf` already defines zones in the http context
  (`zone=ghsponsors:1m rate=30r/m`). Add a `support_report` zone there rather than inventing a second
  place for zones to live.
- **Certs:** Let's Encrypt per-subdomain, one `live/` dir each — nine already. `support.` follows the
  same pattern: **its own cert, never a SAN including the apex** (§A).
- **Vhost convention:** one file per subdomain in `sites-available` → symlinked. `support.` matches.

---

# Visual refinement pass — 2026-08-05

Operator brief: *"in terms of a prototype this is pretty good as a first pass; just needs to be
overall cleaned up, made to look cleaner, less cluttered."* This pass is refinement **within** the
bundles-web house style — no new palette, no new typefaces, no layout paradigm change. Components
copied verbatim from `bundles-web/styles.css` (eyebrow, panel/head/body, pill, field, btn, footer,
nav) stay verbatim; everything page-specific was rebuilt onto the scales below.

## The scales the page is now built to

**Spacing (px): 4 · 8 · 12 · 16 · 24 · 32 · 48.** Sections sit on a uniform 48px top rhythm (was
26px, which read as one undifferentiated column); admin sub-sections at 32; panels stack at 16 via
the house's own `.panel + .panel` rule (restored — its absence was why the first pass carried ~10
inline `margin-top` styles); captions sit 12 under their content. Grid containers space with `gap`
and explicitly zero the panel-stacking margin (`.fleet/.cmdcols/.cmdgrid > .panel`), because grid
items don't collapse margins — without that reset the restored rule shifts every non-first grid panel.

**Type (rem): 0.68 · 0.72 · 0.78 · 0.82 · 0.86 · 0.92 · 1.05 · 1.3 · clamp() h1** (+ the house's
0.7 pill, untouched). Roles: 0.68 uppercase micro-labels, 0.72 meta/hints/captions, 0.78
tables/card body/fineprint, 0.82 rows/nav/tickets, 0.86 prose panels, 0.92 lede/inputs/buttons,
1.05 sub-heads/brand, 1.3 section h2. This retired ten one-off sizes (0.62, 0.64, 0.74, 0.76, 0.8,
0.84, 0.9, 1.02, 1.1rem, 11px).

**Colour discipline:** colour now only carries information — red = accent word, brand K, live/down,
note-box rail, sponsor; blue = ok, info, every command `code`; amber = degraded, and the mockup
switcher (deliberately loud, it isn't part of the design). Everything else is the grey ramp.
A page-local `--rule: rgba(33,72,149,0.38)` token replaced five separately-declared interior row
borders, and interior rules (table rows, fineprint tops) are now consistently lighter than panel
borders, so tables read by alignment instead of chrome.

## Fixed outright (bugs, not taste)

- **`.badge` referenced `--line`, `--green`, `--accent` — none exist in this palette** (rules were
  pasted from a different site). Badges now use the real tokens: `type` = blue (info), `live` = red
  (a live match is the one thing worth a hot colour on a status board). They also moved onto their
  own line inside service tiles instead of being nested mid-sentence in a 0.72rem span.
- `.sponsor-slot` used `float:right` inside a flex row (a no-op) and a 4px-radius rectangle
  matching nothing on the property → `margin-left:auto` and the house pill geometry.
- `p.hint` outside `.field` matched no selector (AC-console panel) — `.hint` is now a standalone
  class.
- `<summary>` had no `:focus-visible` outline; added.

## Removed

- **`.score` — operator call ("rarely used by anyone").** Gone from the Ready group (renamed
  "Ready & status") and from match-flow steps 4/6, which now show `.status` (it reports the score
  while live, so the strip loses nothing). Recorded in COMMANDS.md §5 so it is never re-added.
- ~20 inline `style=""` attributes (all but the data-driven bar widths) → the scales above plus
  three sanctioned utilities (`.mt8`, `.mt16`, `.measure`) and two content classes (`.prose`,
  `.rolelist`). Inline styles were the main specificity hazard this file had.
- Dead rules: `.hcard.sponsor` (no such card exists since the §E header move), duplicated panel
  gradient declarations (now one `--panel-grad` token — same output, one source).

## Signature element

**The house eyebrow's 26px × 2px blue dash, reused as the marker above each top-level section
`h2`.** One sentence of justification: it gives a long single page wayfinding using the one
decorative mark the property already owns, so section starts here read exactly like every sibling
page's hero. Sub-heads inside the admin tier deliberately do *not* get it — the dash means
"section", and diluting it would cost the meaning. Nothing else was added; the hover red rail on
hub cards (already house behaviour from `.bcard`) remains the only other flourish.

## Still needs work (out of scope for this pass)

- **Real-browser QA across widths.** This pass was built to plan and statically checked; the fleet
  grid at ~700–900px (five panels, awkward 2/2/1 wrap) is the spot most likely to want a tweak.
- **Copy-button density in the bot hub** — 15 `/ops` rows each with a copy pill is still the
  busiest area of the page. They're quieter now (faint until hover) but a "copy on row hover only"
  treatment was rejected for touch/keyboard reasons; if the operator still finds it noisy, the next
  lever is dropping copy buttons from the admin tables entirely (admins can select text).
- **Production font**: the prototype rides the fallback mono stack; metrics will shift slightly
  when self-hosted JetBrains Mono lands. Re-check the matchflow strip wrapping then.
- The `.mock` tier switcher ignores the type scale on purpose (throwaway device); don't "fix" it.

---

# Palette change — WSDoD olive (2026-08-05)

Operator brief: re-palette the live template to the WSDoD olive-drab scheme, values extracted from
`1911-ktp-beta.vercel.app/wsdod` (resolved from `lab()` to hex — real values, not guesses). Applied
to **`app/templates/index.html` only**; `design/prototype.html` still carries the navy palette and
is now visually stale as a color reference (its layout/markup reference value is unchanged).

## Token mapping (names deliberately kept — the stylesheet references them everywhere)

| Token | Was (navy) | Now (olive) | Source |
|---|---|---|---|
| `--bg` | `#001e62` | `#171c0a` | WSDoD `--background` |
| `--panel` | `#0a2f77` | `#252a14` | WSDoD `--card` |
| `--panel-2` | `#13367c` | `#323920` | WSDoD `--secondary` (still unused, kept defined) |
| `--inset` | `#001a54` | `#101407` | derived — recessed tone darker than `--bg`; WSDoD has no inset role |
| `--border` | `#214895` | `#3d432b` | WSDoD `--border` |
| `--rule` | `rgba(33,72,149,.38)` | `rgba(61,67,43,.5)` | `--border` at reduced alpha; olive border is lower-contrast so alpha raised .38→.5 |
| `--text` | `#f3fbff` | `#eae7d4` | WSDoD `--foreground` |
| `--dim` | `#adc8e0` | `#b6b299` | WSDoD `--muted-foreground` |
| `--faint` | `#8aa6cf` | `#98947c` | derived — `--dim` stepped down; chosen at ≈4.8:1 on panels (matching the navy faint's ~5:1, not the 4.2:1 a naive darken produced) |
| `--red` | `#f52735` | `#d0513b` | WSDoD `--destructive` (rust) |
| `--red-soft` | — (new) | `#e07a63` | derived; see contrast notes |
| `--blue` | `#0072d5` | `#819746` | WSDoD `--primary` (moss) — **name kept, color is now green** |
| `--blue-soft` | `#4ea3e6` | `#9fb45c` | derived — moss lifted for text-on-panel, mirroring the old blue/blue-soft split |
| `--amber` | `#e8a13c` | `#c08b5c` | WSDoD `--accent` `#ad794b` **lifted** — see contrast notes |
| `--panel-grad` | panel→`#082a6b` | panel→`#1e230f` | same darken-toward-bottom treatment |

Hardcoded hexes swept in the same pass: theme-color meta, body radial gradient, nav backdrop
(`rgba(16,20,7,.72)`), `::selection` ink, sponsor-slot hover ink, `.hcard` hover border
(`#565e3b`), `.btn` ink + hover (`#93aa55`), ghost/copy hover ink (`#e6e3cf`), `.mock` pressed
tint. A regex sweep confirms zero navy-era hexes remain. Font stack untouched — JetBrains Mono
already led `--mono` and WSDoD uses the same face, so no change and no external request.

## Status-colour semantics (re-derived, not just re-hexed)

| State | Was | Now | Where |
|---|---|---|---|
| ok / info / commands / links / actions | blue | **moss** (`--blue`/`--blue-soft`) | dots, ok pills, bars, badges.type, links, buttons, code, focus rings, eyebrow/section dash, mstep.live |
| down / live / alert / accent | red | **rust** (`--red`, `--red-soft` for small text) | down dots/pills, badge.live, offline counts, note-box rail, brand K, hero accent, hcard rail, sponsor |
| degraded | amber | **tan** (`--amber`) | warn pills/dots only — still never a brand color |

Moss = ok is the natural reading in an olive scheme; rust keeps "down/live" hot; tan slots into
"degraded/attention". The `red`/`blue`/`amber` token names now lie about their hue — accepted
trade (renaming was churn across the whole stylesheet); the `:root` block comments say so inline.

**Ok-green vs background-green:** the flagged risk. Mitigations: `.dot.ok` and all ok *text* use
`--blue-soft` `#9fb45c` (6.4:1 on panels — unmistakably lighter than any surface); fills/borders
use `--blue` `#819746`, which is 4.5:1 on panels and 5.3:1 on `--inset` (the `.bar` track), both
past the 3:1 UI-component floor. And per the existing rule, status is never colour-alone — every
dot/pill has a text label, which is what actually protects the moss-on-olive case.

## Contrast problems found and how they were solved

- **White-on-moss buttons failed (3.3:1).** The navy `.btn` was white-on-blue (4.8:1); the same
  treatment on moss fails. Fix: dark ink `#0b0f04` — WSDoD's own `--primary-foreground` — giving
  6.0:1. Same treatment for `::selection` and the sponsor-slot hover (rust bg + `#150b04` ink,
  WSDoD's `--accent-foreground`; white ink there was 4.3:1).
- **Rust is mid-luminance; small rust text fails.** `#d0513b` on panels is 3.4:1 — same ratio the
  navy red had, but that was already marginal and the new small-text sites (0.68–0.72rem
  `badge.live`, `pill.down`, `.inst.off .ct`, the sponsor pill) deserve better. Fix: new
  `--red-soft` `#e07a63`
  (5.0:1) for small rust *text*, mirroring the existing blue/blue-soft precedent; borders, dots
  and large accents stay `--red` (borders need only 3:1 — 3.4 passes).
- **WSDoD tan `#ad794b` fails as text (3.9:1).** `--amber` ships lifted to `#c08b5c` (4.9:1) since
  its only jobs here are small warn-pill text and a dot. The raw WSDoD value is recorded above if
  a fill-weight tan is ever needed.
- **`--faint` and `--rule` re-tuned rather than transliterated** — a straight luminance-match of
  the navy values read too weak against olive (see table).

## Admin layout — small panels no longer weigh like forms

Operator: the AC console link / privileges form / approval queue / admin commands each spanned the
full page, so a one-line link had the same visual weight as a six-field form. Changes (all inside
the existing Jinja guards — no content moved across a `{% if %}` boundary, no gating change):

- **KTP tier**: the top of the block is now a `.twocol` (existing 3fr/2fr grid). Wide column:
  **Request game server privileges** (the real form). Narrow column, stacked: **AC review
  console** (one link), **Approval queue** (empty-state + lifecycle strip; tickets are
  flex-wrapping rows, so the ~440px column holds them when populated), **Booking a server** (two
  short paragraphs, moved up from below the commands table — it's guidance, not reference, and it
  pairs with the booking-adjacent queue). **In-game admin commands** and the **Bot command hub**
  keep full width — they are wide tables in `.scrollbox`, width is load-bearing there.
- **1.3/shared tier**: the moderator-request form + "Your requests" pair became the same
  `.twocol` (form wide, status panel narrow) instead of two full-width stacked panels.
- Under 860px `.twocol` collapses to one column (existing rule), so mobile reads top-to-bottom:
  form, console link, queue, booking.
- Incidental fix: the shared-tier block carried a **stray unbalanced `</div>`**; removed. All
  three tier renders now emit balanced markup (verified by rendering the template with mock
  context: public 61/61, 1.3 66/66, KTP 110/110 open/close divs).

Verified: CSS braces balance (179/179), every `var()` reference resolves (`--panel-2` remains the
one defined-but-unused token, as before), Jinja tags pair to depth 0, and the backend-read form
names (`steam_id`, `display_name`, `level`, `group`, `note`) all survive.

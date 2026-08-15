# Awards framework — the contract between generator, API and page

Frozen 2026-08-14. The generator writes rows, the API shapes them, the page renders them.
Change this file before changing any of the three, or they drift silently.

## Gates

Three independent flags. Two are new rows in `lan_settings` and join `PUBLISH_FLAGS`
in `app/seeding.py`; the third already exists and is NOT touched by this work.

| Flag | Where | Meaning |
|---|---|---|
| `stats_published` | `lan_settings` (new) | the stats board is public |
| `awards_published` | `lan_settings` (new) | ticked awards are public |
| `lan_awards.is_open` | existing table | a vote category is open; results hidden until closed |

⛔ **`is_open` is live with real votes cast. Do not read, write or "tidy" it.**

Unpublished must emit **no data**, not hidden data — `DESIGN.md:51-55`: *"an unpublished
dataset should not be one view-source away."* A public request while `awards_published`
is 0 returns `{"published": false, "awards": []}` and nothing else.

## `GET /api/awards/candidates`

Query: `?edition=philly-2026` (required), `&match=<match_key>` (optional; omit for
weekend scope, which also covers `day` and `team` scopes).

Staff (`is_admin`) always see everything.

**The gate depends on the scope, and so does whether selection applies:**

| Request | Gate flag | Selection |
|---|---|---|
| weekend board (no `match`) | `awards_published` | public sees **only ticked** awards |
| per-match strip (`?match=`) | **`stats_published`** | **none — every candidate publishes** |

*(Amended 2026-08-14. 56 matches × ~18 award types is over a thousand tick
decisions nobody will make, so a selection-gated match strip is permanently
empty. And the strip sits directly under the scoreboard on the same page, so
gating both on `stats_published` means the two can never disagree about being
visible.)*

⚠️ At match scope `selected` is **informational, not a gate**. It still reports
truthfully whether a master ticked that record — the table is read for reporting
and never for filtering — so a ticked box stays ticked on reload. Do not read it
as "this is why the card is showing".

⚠️ `can_select` and `my_vote` ride along unchanged at both scopes: they describe
capability and personal state, not consequence, and `POST /api/awards/select`
still accepts a match-scoped tick. The checkbox on a match card means **featured
/ staff pick**, not published.

⚠️ **A match-scoped tick must send the mount's `match_key`.** Posting `""` from a
match page writes a *weekend* selection for that slug, which now silently
publishes an unrelated card on the weekend board. Empty string is the legitimate
weekend value — the schema uses `''` rather than NULL so those rows can sit in
the primary key — so this fails as a wrong value, never as an error.

```json
{
  "published": true,
  "is_staff": false,
  "edition": "philly-2026",
  "awards": [
    {
      "slug": "weekend-kills-high",
      "title": "The Fragger",
      "sting": "Most kills across the weekend.",
      "is_renamed": false,
      "scope": "weekend",
      "kind": "player",
      "selected": true,
      "tie_width": 1,
      "decisiveness": 0.148,
      "winners": [
        {"who": "hildebrand", "alias": null, "value": "305", "where": null}
      ],
      "runners": [
        {"rank": 2, "who": "piff", "value": "298", "where": null}
      ]
    }
  ]
}
```

- `winners` is every row at `rank_pos = 1`. Always an array — a single winner is an
  array of one, so the page never branches on cardinality to find the name.
- `tie_width` = `len(winners)`. Drives the render tier: 1 normal, 2-4 all in gold,
  5+ collapsed to "Shared by N" in the muted treatment.
- `decisiveness` = `abs(v1 - v_next_distinct) / abs(v1)`, 0.0 when there is no next
  distinct value and when `v1` is 0. Direction-independent: rows arrive already
  ordered so rank 1 is the winner, and a fastest-time award scores the same way a
  most-kills one does. *(Amended 2026-08-14: the signed form written here first
  returned a negative margin for every low-is-better award, which the staff sort
  reads as "least decisive" and the page would print with a minus sign.)*
- `is_renamed` is true when `lan_award_types.title` is set, so staff can see at a
  glance which cards carry an operator title.
- Public responses omit `is_staff`-only fields? **No** — they carry the same shape.
  ⚠️ *(Corrected 2026-08-14: this said `selected` is "always true, because every award
  the public sees is a selected one". True of the weekend board only. A public
  match strip returns unselected candidates, and reports `selected` truthfully.)*

Staff sort: `(tie_width ASC, decisiveness DESC)`. Public sort: `sort_order ASC`.

### `group` and `render` — restoring the page's three sections

*(Added 2026-08-14. Their absence cost the live "Best six by position" panel and
flattened three sections into one list; the first contract simply had no field a
renderer could group on.)*

Every award carries `group`, one of:

| `group` | Section on the page | Contents |
|---|---|---|
| `weekend` | Weekend totals | `scope: weekend`, `kind: player` |
| `positions` | Best six by position | the role panel, see below |
| `single-match` | Single-match records | `scope: match` — the best single match ANYONE had |
| `team` | Club records | `scope: weekend`, `kind: team` |

The page renders one section per group, in that order, and preserves the API's
order **within** each group. Grouping is presentation; sort within a group is
still the server's call.

⚠️ `single-match` is one card per award naming the best single match of the
weekend — **not** one card per match. A per-match view is `?match=<key>`, which
narrows every group to that match and is not what the awards page requests.

Awards also carry `render`, either `card` (default) or `positions`.

`render: "positions"` is a single award — one card, one checkbox, one publish
decision — whose `winners` array is the six role slots rather than tied
co-winners. Each entry adds `role` (`Rifle`, `Heavy`, `3rd`, `Sniper`) and
`slot` (1-based within that role). `tie_width` is meaningless here and the tie
tiers must not be applied; branch on `render`, never on `len(winners)`.

```json
{
  "slug": "weekend-positions",
  "group": "positions",
  "render": "positions",
  "title": "Best six by position",
  "sting": "Top KTPR at each position, the way a roster is built.",
  "winners": [
    {"who": "hildebrand", "role": "Sniper", "slot": 1, "value": "1.388", "where": "Sat"}
  ]
}
```

*(Implementation notes, added 2026-08-14 — the first draft of this section left
three things unstated that the API cannot guess.)*

- **`render` is derived from the data, not from the slug.** An award whose rows
  carry a `role` is the panel. `weekend-positions` stays the canonical slug but
  is not a magic string the API branches on, so a second role panel would work
  without a code change — and a generator that forgets `role` degrades to a
  one-winner card rather than to a wrong-looking panel.
- **`tie_width` and `decisiveness` are `null`** on a `render: positions` award,
  not 0 and not 6. Both are undefined for it — the six margins compare KTPR
  across different positions — and a number there is a plausible-looking lie
  that any page branching on `len(winners)` would act on. `runners` is `[]`.
- **Staff sort places the role panel first**, ahead of every card. Neither half
  of `(tie_width ASC, decisiveness DESC)` applies to it, and a width of six
  would file the one award staff most need to review as the least decisive on
  the board.

## Two tiers: staff nominate, master admins decide

*(Added 2026-08-14, replacing "any admin ticks the checkbox".)*

**Staff** — anyone `is_admin()` — cast a **vote** for the awards they think should
make the cut. A voted card lights up for that voter exactly the way a selected
card used to. A vote publishes nothing.

**Master admins** are staff too — they **vote as well**, and their vote counts in
the tally like anyone's. On top of that they see the **vote count** on each card
and hold the real checkbox. Only they can write `lan_award_selections`, and only
a selected award is ever published.

So a master admin's card carries three things at once: their own vote state
(lit the same way it is for staff), the tally, and the checkbox. Voting and
checking are independent — a master may tick an award they did not vote for, and
`vote_count` must never be derived from or confused with `selected`.

Master admins come from `LAN_MASTER_ADMIN_DISCORD_IDS` (env, comma-separated),
falling back to the three resolved 2026-08-14 — nein `218890328273321984`,
seanality `143944554440163328`, goddamnitchi `749415733393621101`. Env-driven so
a wrong id is one config change, never a redeploy.

⛔ **`lan_award_staff_votes` IS NOT `lan_award_votes`.** The latter holds the
players' ballots on the four vote categories — 35 real votes, live, gated by
`lan_awards.is_open`. The names are one word apart and the wrong one is
destructive. Nothing in this feature reads or writes it.

Presence of a row **is** the vote; un-voting is a DELETE, so there is no stale
`false` to reconcile against.

### Field additions to `GET /api/awards/candidates`

| Field | Who sees it | Meaning |
|---|---|---|
| `my_vote` | staff | this caller has voted for it |
| `vote_count` | **master only** | how many staff voted; `null` for everyone else |
| `can_select` | staff | whether this caller may tick — master only |

⚠️ `vote_count` is withheld the same way award data is withheld from the public:
**not sent**, not sent-and-hidden. A staff member must not be able to read the
tally out of the response. Test it the way the publish gate is tested.

### `POST /api/awards/staff-vote` — any staff

```json
{"edition": "philly-2026", "slug": "weekend-kills-high", "match_key": "", "voted": true}
```

Upserts or deletes in `lan_award_staff_votes`, audit action `award_staff_vote`.
403 for non-staff. ⚠️ **Not** `/api/awards/vote` — *(resolved 2026-08-14: that path
is live and is the players' ballot, so this one is prefixed rather than
overloading it)*.

`vote_count` ships as `null` to staff who are not master, and the three fields
are absent entirely from a public response — no audience is ever sent a number
it may not read.

## `POST /api/awards/select` — MASTER ADMINS ONLY

```json
{"edition": "philly-2026", "slug": "weekend-kills-high", "match_key": "", "selected": true}
```

Upserts `lan_award_selections`, writes `lan_admin_audit` with action `award_select`.
403 for non-admins. Returns `{"ok": true, "selected": true}`.

## `POST /api/awards/rename` — staff only

```json
{"slug": "weekend-kills-high", "title": "The Fragger", "sting": "Most kills."}
```

Writes `lan_award_types.title`/`.sting`. **Global to the award type** — it is inherited
by every future edition, which is the whole point. A null or empty string clears the
override and restores the generated default. Audit action `award_rename`, carrying the
old and new value.

## Staff grant / revoke — audited in place

The existing `POST /admin/staff/add` and `POST /admin/staff/remove` keep their
form-post shape and their auth; they now also write `lan_admin_audit` (actions
`staff_add`, `staff_remove`). *(Amended 2026-08-14: this section was headed
`POST /api/admin/staff`, which reads as a third endpoint — there isn't one, and a
second way in would be a second thing to get the lockout guard right in.)*
🔑 Bootstrap admins from `LAN_ADMIN_DISCORD_IDS` remain unrevocable — that is the
lockout guard, not a bug. *(Amended 2026-08-15: revoking one now returns 400 instead
of running a DELETE that could never match. It used to write a `staff_remove` row for
the attempt, so the log asserted a revocation that never happened — and a log that
records changes it did not make is worse than one that records none. Revoking an id
that was never granted likewise writes nothing.)*

## What else writes `lan_admin_audit`

`publish_flag` — `POST /admin/publish`, target = the flag name, old/new = `"0"`/`"1"`.
Only on a real change, so a double-click is one decision rather than two. Every
individual award tick was logged while "made the whole board public" was not.

`award_close` — `POST /api/awards/{award_id}/close`, target = the award slug. Owner
only, one-way, and it publishes the tally; a repeat close short-circuits and writes
nothing.

Not audited, deliberately: `POST /admin/audit/undo` writes the *result* log, which has
its own record and an undo of its own.

## `GET /admin/audit-log` — staff only

Paginated HTML read of `lan_admin_audit`, newest first, 50 to a page via `?page=`.
Separate from `/admin/audit`, which is the match-result log and carries an undo;
nothing in this one is reversible.

## Generator output contract

The generator owns `lan_award_types` (upsert defaults, never touch `title`/`sting`)
and `lan_award_candidates` (delete-then-insert per edition). It must **never** write
`lan_award_selections`.

Ranking is competition rank: 1, 2, 2, 4. Rows are emitted already ordered so
`rank_pos = 1` is the winner regardless of the award's direction.

### What the API needs the generator to emit

*(Added 2026-08-14 with `group`/`render`. Each of these is a place where the API
cannot tell a missing row from an empty one.)*

- **A match-scope award's weekend card lives at `match_key = ''`.** `scope: match`
  means "the best single match anyone had", so the generator writes that one
  result under the empty match key, with `where_text` naming the match it
  happened in. Per-match rows are written under their real `match_key` and are
  only ever read by `?match=<key>`. A generator that writes *only* per-match rows
  leaves the awards page with no single-match section at all, and the API cannot
  tell that apart from an award nobody won.
- **The role panel needs `role` and `slot`** (migration `0016`, both NULL for
  every ordinary award). `slot` is 1-based within a role, so the two Rifles are
  1 and 2.
- **`rank_pos` carries DISPLAY order for panel rows** — 1..6 over Rifle #1,
  Heavy #1, 3rd, Rifle #2, Heavy #2, Sniper. That is not the same as ordering by
  `(role, slot)`, and it is the only column that can hold it: six rows all at
  `rank_pos = 1` fall back to the query's alphabetical tiebreak on `who` and the
  panel silently reorders itself.
- **A `day`-scope player award groups as `weekend`.** There is no `day` section;
  MVP renormalises per day, so it can only exist as a day award, and grouping
  falls through rather than inventing a fifth section for it.
  ⚠️ `lan_award_types.scope` is `ENUM('weekend','match')` and the catalogue also
  yields `day`, which that column cannot store. Resolving that is the generator's
  call — the API groups on whatever it finds.

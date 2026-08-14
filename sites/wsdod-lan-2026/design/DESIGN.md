# dodworldseries.com — full rework, in the KTP visual language

Companion to `prototype.html` (self-contained, open in any browser; the dashed tan box
bottom-right is a **mockup-only** publication switcher demonstrating the stats gate — it is
not part of the design). The prototype was rendered and interaction-tested in Chrome at
desktop width: day switch, position + map filters, column sorting, KTPR tooltip, row
detail, show-all, demo-stub flip, and the published/unpublished gate all verified working;
zero console errors; no horizontal body scroll.

**Revised 2026-08-06 (operator feedback round)** — see §9 for what changed: position
filters, sortable columns, top-20 + medal colouring, the KTPR tooltip, demo-link stubs,
the real WSDoD patch, the placements scaffold, the casting correction, and the
counting-basis note.

**Revised 2026-08-06, third pass** — see §10: the podium is filled (1–10 verified
standings), the Sunday bracket renders as a bracket (structure from lan-web's
`bracket.html`, data from `lan-stats/bracket.json`), and the demo-link bug (two
scripts fighting over the same spans) is found and fixed.

**Revised 2026-08-06, fourth pass** — see §11: the multi-edition structure (Philly
2026 / Philly 2025 / Coming Soon, editions as data), veto maps on the bracket, the
stats-board column rework + team filter, the detail-expansion bug (data-shape
mismatch) found and fixed, the complete ruleset ported, the staff remote group,
and the Discord-attributed feedback form (two states, deployment prerequisites
recorded).

Style source of record: `KTPInfrastructure/sites/support-web/app/templates/index.html`
(the live KTP look — itself derived from `KTPAntiCheat/docs/bundles-web/styles.css`, then
re-paletted to the WSDoD olive scheme; see support-web `design/DESIGN.md` § "Palette change
— WSDoD olive"). Tokens, type scale, spacing scale, panel/pill/table/details components are
**copied, not reinterpreted**. There is a pleasing circularity here: support.ktpdod.com took
its palette *from* WSDoD, so WSDoD adopting the property style is mostly a homecoming.

---

## 1. Recommendations up front

1. **This is a replacement, not a restyle.** The cream-paper field-manual dossier and the
   olive-drab property style are opposite treatments; blending them produces neither. The
   dossier's *voice* survives in small doses (section meta lines like "the order of battle",
   the crest); its *costume* — paper grain, stamps, binding holes, fold creases, Google
   Fonts — does not.
2. **The site is now post-event.** The LAN ran 31 Jul – 2 Aug; the prototype is designed
   around what the site must do *now*: carry the record (teams, results, stats, demos) and
   stay useful as an archive. The pre-event lifecycle (registration CTAs, "TRANSMISSION
   PENDING" stubs) is a next-LAN concern — see §8 open questions.
3. **Stats are the centerpiece and the per-day split is structural.** Two boards, one per
   day, each carrying its own field baseline. There is no DOM state in which Saturday and
   Sunday rows share a table — the incomparability of KTPR across days is enforced by the
   page's shape, not by a footnote (the footnote exists too).
4. **The publication gate must leave no scar.** With `lan_settings.stats_published=0`,
   the Stats section and its nav link are absent and the page reads complete: Results still
   carries the match log, the hero still carries the event facts. In production this is
   server-side (unpublished stats ship **no markup**); the prototype's toggle demonstrates
   both states client-side.
5. **Publish nothing you cannot attribute.** Match *scores* exist in the engine record but
   are not attributed to teams anywhere in the dataset — so the Results section ships the
   verifiable match log (map, time, length, halves, demos) and holds bracket placements
   behind a "being compiled by staff" note rather than guessing. Same discipline as the rest
   of the property: identity is the verified record, never the banner.

---

## 2. Information architecture

```
dodworldseries.com
│
├── Header (STATIC — property requirement)
│     brand "WSDoD — World Series of DoD" · Event · Teams · Results · Stats* · Rules ·
│     Archive · Feedback · "part of KTP" pill → ktpdod.com
│     (*absent when stats unpublished; all but Feedback are 2026-edition links)
├── Edition bar (§11)    — Philly 2026 (default) · Philly 2025 · Coming soon;
│                          chips render from the #editions data block
│
├── Hero — identity + the crest (the page's one pictorial element)
│     eyebrow: Philadelphia · dates · venue · Discord pill
│     event fact tiles: 12-cap/10 registered · 61 players · 100 matches ·
│                       58 tournament · 242 HLTV demos
│     (2026's masthead is markup; other editions render theirs into #ed-hero)
│
├── § Edition summary    — [non-2026 only] data-rendered record; see §11
├── § The weekend        — three day cards (draft / groups / playoffs+finals),
│                          venue panel (condensed travel), "how it ran" (KTP stack)
├── § Teams              — 10 registered companies, captain marked, placement border;
│                          honest caption: rosters are as-registered, day-of shifted
├── § Results            — podium + 1–10 + bracket (with maps played) + per-day match
│                          logs (31 + 27 rows, from the engine's own match index)
├── § Player stats       — [gated] two day boards; see §5 and §11
├── § Rules              — two <details> panels: Rules of engagement, Code of conduct —
│                          both COMPLETE text since §11 (reusable template property)
├── § LAN command        — 8 on-site staff cards + a "(remote)" group of 2
├── § Archive            — Demos panel (242 HLTV + POV filing) · Broadcast panel (casters)
├── § Feedback           — Discord-attributed feedback form (§11); site-level,
│                          shown for every edition
└── Footer               — what this is · Discord · KTP link
```

No JS is required for anything except the stats boards (render, day/map switch, row
detail), which degrade to an empty table without JS — acceptable for a prototype; the
production build should render the default board server-side (see §7).

## 3. Token mapping

All tokens verbatim from `support-web/app/templates/index.html` — **zero new tokens, zero
changed values**: `--bg #171c0a`, `--panel #252a14`, `--panel-2 #323920`, `--inset #101407`,
`--border #3d432b`, `--rule rgba(61,67,43,.5)`, `--text #eae7d4`, `--dim #b6b299`,
`--faint #98947c`, `--red #d0513b` / `--red-soft #e07a63`, `--blue #819746` /
`--blue-soft #9fb45c` (moss — the token name keeps its blue-era spelling, same as the
source), `--amber #c08b5c`, radius 14px, the same panel gradient, the same mono stack
(JetBrains Mono → system mono fallback; the prototype makes no external requests).

Spacing (4/8/12/16/24/32/48, sections on the 48px rhythm) and the type scale
(0.68/0.72/0.78/0.82/0.86/0.92/1.05/1.3 + clamp h1) are the support site's scales.

**Colour discipline carried over:** rust = accent word, brand mark, captain tag, top-3
rank, note-box rail; moss = links, actions, ok, the eyebrow/section dash, KTPR bars, active
tab/chip; tan = the mockup switcher only (deliberately loud, not part of the design);
everything else is the warm-grey ramp. The four position pills are deliberately **neutral**
(border + dim text): Rifle/Heavy/3rd/Sniper are categories, not statuses, and giving them
status colours would spend the semantic palette on decoration.

Components reused verbatim: `.eyebrow` (+ its dash as the section marker — the property's
signature), `.panel/.head/.body`, `.pill`, `.note-box`, `.hint/.prose/.fineprint`,
`details.panel` disclosure, `.scrollbox`, table treatment (th/td rules from `.opstable`),
`.btn/.btn.ghost`, footer, and the `.mock` switcher pattern from the support prototype.

Page-specific components (documented in the stylesheet header): `.crest`, `.statstrip`,
`.daytab`, `.baseline`, `.mapchips/.chip`, `.leader` (+ `.ktprbar`, `.rolepill`,
`.detailbtn`, `.detailgrid`), `.teamgrid/.roster`, `.logtable`, `.staffgrid`. All are built
from the existing scales; none introduce a colour or size outside them.

**The one aesthetic risk:** the dossier's divisional patch, redrawn as an inline SVG in the
property palette (moss crossed rifle-and-bat, bone rim text, rust "★ LAN ★"). It is the
only pictorial element on the page and the only survivor of the field-manual costume —
kept because it is the event's *brand*, not the old page's *treatment*. It hides below
760px rather than compressing.

## 4. Kept / dropped from the current page

**Kept (re-dressed):** event identity and dates; venue + condensed transit facts; the full
team registry with captains and registration dates; rules of engagement (abridged, with the
"original wording governs" fineprint — that caveat is load-bearing and survives); code of
conduct (condensed); staff roster with the recusal note; casters; Discord link; the
POV-demo/HLTV recording facts (now stated as record, not instruction).

**Dropped, with reasons:**
- *Paper costume* — grain, stamps, folds, binding holes, typewriter/serif/stencil Google
  Fonts, load animations. Opposite treatment; also violates the zero-external-requests rule.
- *Registration CTAs + vacancy banner* (player/team Google Forms) — the event is over.
  The form URLs are preserved here for the next cycle:
  players `https://forms.gle/v7iHjA9fV1V6vpTW6`, teams `https://forms.gle/er1VPETNHiXmAHWZ7`.
- *Fee/payment lines* ($160/$50, "deposit fronted by las1k64") — transacted; las1k64's
  fronting is acknowledged nowhere now, which may be worth a thank-you line somewhere if the
  operator cares (flagged, not decided).
- *The schematic venue map (SVG "FIG. 1")* — decorative; the address + transit lines carry
  the same information.
- *"TRANSMISSION PENDING" schedule stub* — replaced by the real match log.
- *Demo submission instructions* (§X filing rules, flash-drive handoff) — instructions to
  attendees during the event; the archive section states what was recorded instead.
- *Masthead doc-ids* ("WSDoD/LAN-26/OPORD-1", "Compiled at hq.dodworldseries", stamp
  numbers) — dossier props. **One flagged unknown:** if "hq.dodworldseries" refers to a real
  build host naming convention someone depends on, it should live in ops docs, not page
  chrome; I could not determine a real purpose, so it was dropped rather than carried.
- *"FILED 14 MAY 2026" chapter stamps and revision line* — replaced by nothing; the builder
  can stamp a "last updated" into the footer if wanted (open question).

## 5. The stats section

### Per-day incomparability — structural, three ways

1. **Two boards, one per day.** The day switch swaps the *entire* board: baseline strip,
   map chips (Saturday has 6 maps, Sunday 7 — the chip row itself changes), and table. No
   view merges days; no control sorts across them, because no such DOM state exists.
2. **The baseline travels with the board.** Each day's field averages (avg K/D,
   kills/half, flags/half, pool) render in a strip *above the table it governs*, captioned
   "KTPR normalizes every player below against these numbers — and only these." The
   normalization basis is visible, not implied.
3. **The day tab faces say it**: "rated against Saturday's field" / "rated against
   Sunday's field" — on the control itself, before the note-box is even read.

The note-box states the rule in words ("A Saturday 1.20 and a Sunday 1.20 are not the same
number") — but it is the *fourth* line of defense, not the first.

Per-map tables reuse **that day's** averages (as the dataset does), so map views stay
comparable within a day and the same three defenses apply unchanged.

### What leads, what is disclosure (~27 fields → 10 columns)

**Leads** (the leaderboard): rank · player · position pill · KTPR (number + bar scaled to
the day's leader) · K–D · K/D · kills/half · flags/half · assists · damage. These are the
three KTPR terms, the two most-asked raw numbers, and the two headline HUD stats. Top 20
rows by default; "Show all 61 players" expands (and collapses back).

**Filtering and sorting (added in the 08-06 pass):** a Position chip row (All · Rifle ·
Heavy · 3rd · Sniper, with live counts) composes with the existing map chips; every column
header sorts (click to sort, click again to reverse, ▲/▼ + `aria-sort` mark the active
one). Rank and the medal colours are computed against the **last numeric column sorted**
(KTPR by default) within the current filter — sort by assists and the assists leader is
rank 1 and gold; reverse the sort and the medals stay with the leaders at the bottom,
because rank belongs to the player, not the row position. Sorting by name or position
reorders the rows but leaves the ranking metric alone (there is no "alphabetical
champion"). The K–D column sorts by total kills (the ratio and the rates have their own
columns; total kills is otherwise unsortable). Switching to a view that lacks the active
sort column (map boards drop kills/half) resets to KTPR descending. The board head names
the active view ("Saturday · Sniper only — ranked within this view") so a filtered board
can never pass for the full field.

**Progressive disclosure** (per-row "detail" expander, three columns):
- *Where the hits landed* — hitbox distribution as labeled bars (hits + damage each).
- *Class spawns* — the league-vernacular class names (Scharf, Unter, Tommy…) with counts,
  plus the position provenance line.
- *The rest of the ledger* — headshot kills, hits landed, headshot hits, HUD flag caps,
  cap denials, objective score, best streak, grenade/gun kills, prone transitions.

**Deliberately not shown anywhere:** `damage_hlstatsx` (two damage numbers with an ~11%
definitional gap invite the wrong question; the HUD number is shown because it pairs with
hits/hitboxes from the same source), `steam_id` (an identity key, not a stat), `halves`
(implied by matches; kept in the data for tooltips if ever wanted).

**Positions:** the four league positions render as pills — **solid border = named by
staff, dashed = read from class play** (unchallenged in the operator's final pass), with a
title tooltip explaining which. As of the 2026-08-06 dataset the distribution is
operator-settled: Rifle 23 / Heavy 18 / 3rd 10 / Sniper 10 on both days, with 17 explicit
staff overrides in `roster_roles.json`; the inference caveat from `lookups.py` (class
cannot determine position — the p12/epyon/monday cases proved it) is exactly why
provenance is still drawn, not footnoted.

### Publication gate

`body[data-stats="off"]` hides the section (prototype). Production does this server-side:
when `lan_settings.stats_published=0` and the caller is not staff, the route in front of
the static mount strips the JSON blocks outright — an unpublished dataset should not be one
view-source away.

⚠️ The gate must also rewrite `statsPublished` inside `#editions`, because `applyGate()`
sets `body.dataset.stats` **from** that value on load and would otherwise overwrite a
server-set attribute — stripping the data without it yields an empty board that reads as
"nobody scored". The section now keeps its heading and shows a placeholder rather than
vanishing; the nav link no longer hides with it.

*(Corrected 2026-08-14: this named `lan_stats_publication.published`, which is a table in
`hlstatsx_lan` that nothing has ever read and that lan-web has no privilege to reach.)*

Everything else on the page is written to stand without it: Results
carries the match log, the hero tiles are event facts (match/demo counts), and no copy
elsewhere references "the stats below".

## 6. Real data in the prototype (sources)

- **Players/maps/averages:** `lan-stats/lan-stats.json`, embedded trimmed+minified
  (~146 KB) in a `<script type="application/json">` block. All 61 players × 2 days, all 13
  day-map tables, real names, real KTPR, plus the KTPR coefficients (0.25 / 2.25) for the
  tooltip — nothing invented. The embedded copy is the **2026-08-06 18:04** build (the
  operator's final position pass — `roster_roles.json` at 17 overrides). If
  `build_stats.py` runs again, the embedded blob is stale until re-injected — production
  should template it in at render time, not hand-paste.
- **Match logs:** `KTPAntiCheat/docs/reviews/lan-match_index-2026-08-06.csv`, `.ktp` rows
  only — 31 Saturday + 27 Sunday, with start time, map, length, halves, demo counts.
- **Event facts:** same CSV — 100 matches total (58 ktp / 21 scrim / 16 draft / 5 12man),
  242 demo files, Friday = 16 draft + 15 scrims, ~40h of tournament server time.
- **Teams:** `sample.csv` (the registration sheet snapshot the current page renders from),
  all 11 rows, captains = player 1.
- **Rules/conduct/staff/casters/venue:** the current `index.html`.

## 7. Production notes (when this goes real)

- `builder.py` grows three inputs: the registration CSV it already fetches, the match
  index (or a query against `hlstatsx_lan`), and `lan-stats.json` + the publication flag.
  Render server-side with Jinja like today; the stats JSON should be templated into the
  page (or fetched from a same-origin static file) so a dataset rebuild republises without
  hand-editing.
- Self-host JetBrains Mono woff2 same-origin, exactly as bundles-web does — the prototype
  rides the fallback stack by design. Re-check the leaderboard column widths when the real
  face lands.
- The leaderboard's default board should be server-rendered so the page is not
  JS-dependent for its centerpiece; the day/map switching can stay client-side.
- Wide tables already sit in `.scrollbox`; body never scrolls horizontally (verified at
  desktop; **narrow-width QA is pending** — the browser used for verification refused
  window resize, so the 640/760/860px breakpoints are code-reviewed but not eyeballed.
  They are the support site's own patterns).

## 8. Open questions for the operator

1. **Final placements & bracket.** Team-attributed results exist nowhere in the data (the
   match index has scores but not team identities). Who compiles the bracket/placements,
   and in what form? A tiny JSON (`results.json`: round, teams, score, match_ids) would
   slot straight into the pending panel.
2. **Played rosters.** Registration rosters are visibly stale — tags in the stats data
   ([bb], ßℓυ†н, JTM…) don't all match the sheet, and roughly ten tags actually played
   against eleven registered teams. Publish as-registered (current design, with the honest
   caption), or supply a played-roster pass? If the latter: same override-file pattern as
   `team_overrides.json`.
3. **Do player names link anywhere?** profiles.ktpdod.com exists; linking stats rows to
   profiles would knit the property together, but LAN aliases ≠ profile identities and the
   join key would be SteamID — which this design deliberately doesn't render. Decide
   whether the production JSON should carry an opt-in profile URL per player instead.
4. **Demo archive URL.** 242 demos exist; where do they publish for the public? The
   archive panel currently points only at the league archive.
5. ~~**KTPR column sorting.**~~ **Resolved 08-06** — every column sorts, within a single
   day's board only (the day boundary stays structural, so sorting can't cross it).
   See §5 and §9.
6. **The pre-event lifecycle.** Should this template also serve LAN 2027 pre-event
   (registration open, schedule pending)? The section skeleton supports it (Results and
   Stats absent, a registration panel returns), but the copy in the prototype is written
   post-event. Decide before reusing.
7. **las1k64's deposit acknowledgment** — dropped with the fee lines; restore a thanks
   line somewhere if wanted.
8. **A "last updated" stamp** — the dossier's revision line was dropped; the builder can
   stamp the footer if freshness matters post-event.
9. ~~**Crest artwork.**~~ **Resolved 08-06** — the real WSDoD patch was found at
   `sites/lan-web/app/static/wsdod-lan-2026.png` and now replaces the redrawn SVG,
   inlined as a data URI. See §9.

---

## 9. Refinement pass — 2026-08-06 (operator feedback)

### What changed

1. **Position filters.** A Position chip row (All · Rifle 23 · Heavy 18 · 3rd 10 ·
   Sniper 10 — counts are live per view) composes with the map chips on both day boards.
   Rankings recompute within the filtered view: the #1 Sniper is #1 among snipers. The
   board head names the active filter.
2. **Sortable columns** — every column, both directions, `aria-sort` + ▲/▼ indicator,
   default KTPR descending. Full semantics in §5 ("Filtering and sorting").
3. **Top-20 default with medal colouring.** 20 rows by default, "Show all 61 players"
   toggle. Medals track the current sort *and* filter (spec'd behaviour; see §5).
4. **KTPR tooltip on the column header** — hover *and* keyboard focus (`aria-describedby`,
   Escape closes, scroll dismisses). Shows the formula
   `KTPR = [ (K/D ÷ avg K/D) + (kills per half ÷ avg) + 0.25 × (flags per half ÷ avg) ] ÷ 2.25`
   with the coefficients read from the data, plus **that day's** actual baselines, and
   states that 1.00 is exactly average for the day and the two days are not comparable.
   Positioned `fixed` so the scrollbox can't clip it.
5. **Demo-link stubs in the match log.** Every match-log row carries its engine match id
   (`data-match="1785604799-KTP3"`, from the match index CSV — real identifiers, no
   invented URLs) and renders a dashed "N · pending" pill. An empty
   `<script id="demo-urls" type="application/json">{}</script>` map sits beside the data
   blob; **filling it (match id → URL) is the only step needed to flip stubs to live
   links** — verified in-page. No markup changes when the archive pass lands.
6. **Casting credit corrected** to Corey Marko and Dyelife; the VOD slot line stays.
   ⚠️ The **old** `index.html` (the live dossier page) still credits Corey Marko (lead) +
   Alopex in its §Broadcast — if the old page stays up much longer, that credit is wrong
   on the public site today.
7. **Schedule + bracket scaffolding.** The schedule survives as record: the three day
   cards (Friday draft / Saturday groups / Sunday playoffs+finals, past tense) plus the
   two per-day match logs, which are the realized schedule. The old page never had a
   bracket *structure* — only a "bracket to follow" stub — so the scaffold added here is
   a **Final placements** panel (Champion / Runner-up / Third slots, medal-coloured,
   rendered pending) with a stated slot for the full bracket tree. It fills from staff's
   verified results (open question 1 still governs the data shape) and is the template
   shape next year's event reuses.
8. **The real WSDoD patch** (see below) replaces the redrawn SVG in the hero.
9. **Counting-basis note** added under the boards: HUD-derived columns (assists, damage,
   grenade kills, caps, streaks, prone) run 11–19% under a full event count because the
   HUD's final periodic save lands before a half ends — stated plainly as deliberate
   ("undersold beats oversold"), while kills/deaths/K/D/flags are called out as exact and
   match-scoped. Raw-event counting would be *less* accurate (HUD events include warmup,
   and only 95 `half_end` events exist for 189 `half_start`, so live-window filtering is
   impossible) — that reasoning lives here, not on the page.
10. **Copy fix:** the stats note-box claimed Sunday's field was "thinned by eliminations" —
   the data says 61 players appear in `.ktp` matches on *both* days (consolation play).
   Now it just says the days ran at different baselines.
11. **Data re-embedded** from the 2026-08-06 18:04 `lan-stats.json` (operator-final
   positions), including the KTPR coefficients; map rows carry each player's
   position/provenance so the filters work on map boards too.

### Medal palette derivation

All four from the existing olive ramp, applied to the rank + player cells only (the rank
*number* carries the information; colour reinforces it — no colour-only signal):

| Medal | Token | Value | Derivation |
|---|---|---|---|
| 1st | `--gold` | `#d2b356` | `--amber #c08b5c` rotated toward yellow at the same value range — brass, not canary; ~8.4:1 on `--panel` |
| 2nd | `--silver` | `#c9cdbb` | the warm-grey ramp (`--dim #b6b299`) lifted a step and cooled toward the moss side — reads silver against the warm text `#eae7d4`; ~9.4:1 |
| 3rd | `--bronze` | `#c08b5c` | `--amber` verbatim, per the brief — tan *is* the bronze; ~5.6:1 |
| 4th–5th | `--medal45` | `#9fb45c` | `--blue-soft` (moss) shared — palette-native, clearly not a metal; ~6.9:1 |

The podium slots in Results reuse the same three metals, so "gold" means the same thing
in both sections. Risk accepted: moss for 4th–5th is also the link colour; inside a table
row it can't be mistaken for a link (nothing there is clickable but "detail", which is a
button), and it keeps the page to the property's five hues.

### The logo (change 8 finding)

**A real asset exists** — `sites/lan-web/app/static/wsdod-lan-2026.png` (937×768 RGBA,
825 KB), the patch lan-web's HUD pages have used all season ("Day of Defeat 1.3 /
Philadelphia / TAP Esports / July 31–August 2, 2026"). It replaces the SVG redraw
one-for-one in the hero, downscaled to 360 px and palette-quantized (256 colours,
Floyd–Steinberg) → 32 KB, inlined as a data URI (~43 KB of markup) — zero external
requests, sharp at the 180 px display size. The source PNG is untouched. Two caveats:
the artwork is **year-stamped**, so next year's template needs next year's patch; and its
khaki/red palette sits a shade warmer than the page's olive, which is correct — it is
their patch, not a costume.

### Verification (this pass)

Chrome, desktop width: position filter recomputes ranks (Sniper → 10 rows, new #1);
assists sort makes the 77-assist leader gold and reversing keeps the medals with the
leaders; alphabetical sort leaves the ranking metric alone; map switch while sorted on a
day-only column resets to KTPR; tooltip appears on keyboard focus and hover with
Saturday's real baselines, hides on blur/Escape/scroll; show-all toggles 20 ⇄ 61; 58 demo
stubs carry real match ids and a test entry in `#demo-urls` flipped its stub to a link;
the gate still removes the section + nav link; no horizontal body scroll; zero console
errors. **Narrow-width QA is still pending** — the test browser again refused window
resize (same as §7), so the breakpoints remain code-reviewed only.

### Still open after this pass

- ~~Demo archive URL scheme~~ **Resolved — see §10.** `#demo-urls` is filled (58 matches /
  134 files at `fastdl.ktpdod.com/demos/LAN-PHILLY2026/ktp/`).
- VOD links — the Broadcast panel holds the slot.
- ~~Bracket/placements data shape~~ **Resolved — see §10.** `lan-stats/bracket.json`
  arrived; the podium is filled and the bracket renders.
- The old `index.html` still carries the Alopex casting credit and the pre-event copy;
  decide when the rework replaces it.

---

## 10. Third pass — 2026-08-06 (operator feedback: podium, bracket, demo links)

### Fix 1 — the podium is filled

`lan-stats/bracket.json` (exported from `ktp_lan.lan_bracket`, all 15 rows `final`)
plus the operator's verified standings closed open question 1. The "pending staff
verification" scaffold is gone: the podium carries NATO / icyHOT / dicE in the
existing gold/silver/bronze (same treatment as the team cards — border + name carry
the metal), and a full **1–10 placement list** sits under it in two columns (one
below 640px), the lan-web "Final standings" pattern. The Results note-box now states
the record is complete instead of promising compilation. The 1–10 list was checked
against the match rows: every placement is consistent with F/P34/P56/P78/P910.

### Fix 2 — the bracket renders as a bracket

**Structure carried from the old site** — `lan-web/app/templates/bracket.html`, the
page the bracket actually ran on during the event (the dossier `index.html` only ever
had a "bracket to follow" stub). Its geometry translates verbatim: flex round columns
whose equal-share cells produce the merge-tree spacing; elbow connectors drawn with
pseudo-elements (`odd` child elbows down, `even` elbows up, next round takes a straight
stub); the play-in column's cells sit **in the rows of the QFs they feed** (`.has` /
`.fed` straight lines); placement matches as a second, connector-less column tree.
Re-dressed in the olive tokens (`--border` 2px lines, `--inset` cards, `--panel-2`
seed boxes); winner = moss bold on name + score, champion = gold + "★ Champion" under
the final card. Losers stay `--faint` — winners are legible at a glance from colour,
weight and score together.

**Data shape** (`lan-stats/bracket.json`, one object per match):
- `bracket`: `upper` (PI1-2, QF1-4, SF1-2, F) or `placement` (LS1-2, P34, P56, P78, P910)
- `mkey`/`stage`/`slot`: match identity — mkey is the join key everything else uses
- `source_a`/`source_b`: **the progression encoding** — `seed:N`, `W:QF2` (winner of),
  `L:SF1` (loser of). The prototype's connections and pairings were built from these,
  never from team names (two teams meeting twice — e.g. NoSoul/dicE in QF4 then never —
  would break name-inference; sources cannot).
- `team_a/b`, `score_a/b`, `winner`, `status` (`final` throughout), `station`, `map`
  (the played BO3 picks, `NULL` on four matches — carried as a `title` tooltip on each
  card, since the match log owns map data).

Seeds shown in the cards are derived from the `seed:N` sources (1 icyHOT, 2 dicE,
3 NATO, 4 AD, 5 [bb], 6 FJTM, 7 NoSoul, 8 [$], 9 b., 10 uR[TM]).

The prototype's bracket is **static HTML** (each card carries `data-mkey`; verified
15/15 against the JSON — teams, scores and win flags all machine-checked). Production
renders the same shape from `ktp_lan.lan_bracket` with Jinja, exactly as lan-web did.
Placement cards carry "3rd–4th · semi-final losers"-style tags and no connectors, so
they read as deciders, not as part of the title tree. `.bkt-round` min-width (244px)
is set from a measured worst case: "North Atlantic Treaty Org" bold needs 182.8px at
the fallback mono — below that the champion's own name ellipsizes.

### Fix 3 — the demo-link bug (root cause)

**Two scripts were competing for the same `.demo-pend` spans.** The §9 pass's
single-link flipper (inside the main IIFE) was never removed when the per-file
renderer (second `<script>`) was added. Load order did the rest:

1. The old flipper ran first, replaced each span with **one** `<a>` whose `href` was
   the URL *array* coerced to a comma-joined string (`urls[id]` used to be a single
   URL when the map was empty-by-design; once the archive pass filled it with arrays,
   `if (!url)` stayed truthy and `a.href = url` silently stringified).
2. The per-file renderer then found **zero** `.demo-pend[data-match]` spans — so no
   per-file links — but still appended its "Teams" `<th>` to both headers, leaving a
   7-column head over 6-column rows.

So the symptom "one link where there should be two" was the old script's output, with
a broken href and a misaligned table besides. **Fix: the old flipper and its dead
`a.demo-link` CSS are deleted**; the per-file renderer is now the only consumer.
Verified in-page: 58/58 rows render `.demo-links`, distribution 41×2 / 16×3 / 1×4 =
134 links total, head and body both 7 columns, two rows show "not recorded" teams
(the two matches an older rename pass stripped of team names — expected).

**Labels stay filename-true on purpose.** `H1 / H1 pt2` where the second file is
really the second half reflects the archive's known mislabelling (36 of 58 matches);
the operator is fixing the renames separately and the page must keep the error
visible, so labels parse `_h(\d)` / `_part(\d)` from the filename and nothing else.

### Also in this pass

- The no-JS state of the demo cells was still "N · pending" with a "being renamed"
  tooltip — false since the archive published. Now "N demos" + a JS-required note.
- Teams section meta said "rosters as fielded" while its own footnote said
  "as registered" — meta corrected to "as registered".
- Archive §Demos no longer claims the location is unpublished; it links
  `fastdl.ktpdod.com/demos/LAN-PHILLY2026/`.
- **Nav overflow fixed** (found doing the narrow QA §7/§9 left pending): the static
  nav row never wrapped, so the brand + the two pills forced ~228px of body-level
  horizontal scroll at 400px. Below 640px the row now wraps. With that, a 400px
  smoke test shows zero body overflow; bracket, placement tree and match logs all
  scroll inside their own `.scrollbox`; `.placings` collapses to one column; the
  crest hides as before.

### Verification (this pass)

Machine-checked: CSS braces balanced, no undefined `var(--…)`, all HTML tags paired,
15/15 bracket cards match `bracket.json` (teams, scores, winner flags), 58/58 match
rows carry the right link count (41×2 / 16×3 / 1×4). Chrome, desktop width: podium +
1–10 list render; bracket connectors correct (play-in feeds QF1/QF4, QF→SF→F elbows);
no name truncation; champion gold; stats gate still removes the section + nav link
while Results (podium, bracket, logs) stays; day switch / chips / show-all regress
clean; zero console messages on a fresh load; no body horizontal scroll at desktop or
in a 400px-viewport iframe smoke test. True narrow-*window* QA (real resize, not an
iframe) remains the one thing this environment cannot do.

### Still open after this pass

- VOD links — the Broadcast panel holds the slot.
- The two team-attribution gaps in the demo archive (`1785613505-KTP4`,
  `1785689132-KTP4` — renamed by an older pass without team names); their rows show
  "not recorded" until the operator's rename fix lands.
- The h1/h2 mislabelling itself — display is filename-true by design; when the
  archive renames land, `#demo-urls` is the only thing to regenerate.
- The old `index.html` still carries the Alopex casting credit and the pre-event copy.

---

## 11. Fourth pass — 2026-08-06 (operator feedback: corrections, veto maps, stats rework, full ruleset, multi-edition structure, feedback form)

### Small corrections

1. **"11 registered" → 10** in the hero fact tile (the field was ten companies;
   the teams meta and lede already said so).
2. **Comms were self-hosted TeamSpeak, not Mumble** — fixed in "How it ran".
   ⚠️ Note the tension this leaves: CoC rule 3.5 *as issued* names Mumble as the
   sole authorized tool. The ruleset is ported verbatim (see below), so the rule
   still says Mumble; a fineprint note under the CoC states the historical fact.
   If next year's ruleset should say TeamSpeak, that is a rules edit for staff,
   not a website edit.
3. The Teams caption's "played-roster pass is pending from staff" clause is
   deleted — resolved.
8. **Staff split:** 8 on-site cards, then a "(remote)" group (shmaltz, chi) under
   a small uppercase sublabel (`.staffsub`). Spelling kept as "shmaltz" — that is
   what the original page's roster says.

### Veto maps on the bracket (change 4)

`veto.json`'s `played` map (keyed by `mkey`) renders as a **footer row inside
each bracket card** (`.bkt-maps`, border-top hairline, faint 0.62rem, wraps
rather than truncates). Inside the card rather than under it so the connector
geometry — which centres on the `.bkt-m` cell — is untouched. 14 of 15 matches
have maps; P910 has none in the data and gets **no row** (absent, not dashed).
The old per-card `title` tooltips (from bracket.json's `map` field) are removed
as redundant. The full ban/pick `sequences` are deliberately not shown — the
operator asked for maps played only, and the veto dance belongs in the data,
not on the card.

**Splice bug caught in verification:** the first automated insert matched
`class="bkt-c` — which also matches `bkt-card` — and put the maps row between
the two team rows on every card. Screenshot review caught it; the corrected
pass verifies every maps row sits after both team rows and matches veto.json
14/14.

### Demo links (change 5) — verified against the regenerated archive

`#demo-urls` now carries **58 matches / 119 files** (56×2, 1×3, 1×4), labels
`H1`/`H2` (+`ptN`) parsed from filenames: 64 h1 / 55 h2, zero unparsable. The
15 match-log rows whose static no-JS text still said "3 demos" from the
pre-rename archive were re-synced to the real per-match file counts (all 58 now
agree). In-page: 58/58 rows render `.demo-links`, 119 links total, 7-column
head over 7-column rows.

### Stats board rework (change 6)

**Columns (day boards):** # · Player · Pos · KTPR · **K/D** (moved to sit
directly after KTPR) · **Kills · Deaths** (the old K–D column split — each
sorts independently now, no "sorts by kills" special case) · **Flags** (the
per-player total, new) · Assists · Damage · **Streak · Breaks** (promoted from
the detail panel) · detail. Map boards carry the same core minus
Streak/Breaks/detail (the per-map data doesn't have them).

**The 6f judgement call — prone was cut.** Best streak and cap breaks are
promoted (compact one/two-digit values, competitively meaningful). Prone count
stays in the detail panel: it is telemetry trivia rather than a performance
stat, its values are the widest of the three, and thirteen columns is the
board's readable ceiling — at fourteen the table starts horizontal-scrolling at
desktop width, which hides the detail button. "Breaks" carries a header tooltip
("enemy captures broken up").

**Kills/half and flags/half moved INTO the detail panel** (top of "the rest of
the ledger"), streak/breaks moved out of it — nothing is shown twice.

**The detail-expansion bug (6d) — root cause.** Not a script collision this
time: the §9 pass re-embedded `lan-stats.json` with hitboxes in their source
shape — `{"hits": N, "damage": N}` objects — while `detailRow()` still indexed
them as `[hits, damage]` arrays from the first embed. `row.hb[k][1]` is
`undefined` on an object, `fmt(undefined)` threw `TypeError` mid-build, and the
click handler died before inserting the row — so the button flipped its
aria-expanded state and nothing appeared. Fix: the renderer reads
`.hits`/`.damage`; the embed keeps the object shape; a comment at the site
pins renderer and embed together. Lesson repeated from §10: the data blob and
its consumers version together — re-embedding is an interface change.

**Team filter (6g).** A Team chip row sits between Position and Map: all 10
teams in final-standings order, short labels (NATO, icyHOT, dicE, BLUTH, FJTM,
[bb], NoSoul, [$], b Team, uR[TM] — full name on the chip's title), live
counts. Composes with position and map; rank and medals recompute within the
filtered view (already structural — rank is computed on the filtered row set).
Each chip row's counts respect the *other* filter, so a chip's number is always
what clicking it would show. Data side: every embedded player row (day and map)
now carries `tm`, joined `steam_id → player_teams.json` (61/61 matched, both
days, all map tables — verified at embed time). The diagnostic fields
(votes/margin/…) are not embedded.

**Data re-embed:** `#lan-data` is regenerated from the 2026-08-06 18:36
`lan-stats.json` + `player_teams.json` by script (no hand-pasting). ~156 KB.

### Full ruleset port (change 7)

The complete Rules of Engagement (§VI) and Code of Conduct (§VII) from the
original `index.html` now live in the two collapsed `<details>` panels —
every section, every reg, original wording preserved (including the RoE
footer's own "abridged transcription pending verification" caveat, which is
part of the document). Only the dressing changed: `.reglist` grid rows, the
CoC penalties list flattened into the reg body (the original's inline-styled
`<ul>` used the dossier's `--serif` token, which doesn't exist here). The page
is the reusable template for next year, so the rules carry in full.

### Multi-edition structure (change 9)

**The shape: one markup edition, N data editions.** The page now carries three
editions — Philly 2026 (default), Philly 2025, Coming Soon — switched by a chip
row under the nav (`.edbar`). Everything 2026-specific (its seven sections, its
nav links, its hero internals) is tagged `data-ed="philly-2026"`; the edition
module shows/hides by tag. Non-markup editions render **entirely from data**
into two containers: `#ed-hero` (eyebrow · name · lede · fact tiles) and
`#edition` (the record: facts panel, purse, standings-or-note, teams grid).
Adding 2027 = adding an entry to the `#editions` JSON block. In production each
edition is a server-rendered route and the switcher is real navigation; the
client-side switch is the prototype's stand-in.

**Edition data shape** (`#editions`):

```
{ default, order: [ids],
  editions: {
    id: {
      label, status,                  — chip text · status note
      markup: true,                   — 2026 only: content is the page markup
      statsPublished: bool,           — the publication gate, now per-edition
      city, dates, venue,             — eyebrow line (all optional)
      venue_full, entry_fee, format,  — "The event" kv panel (rows render only
      tournament_director,              for fields present)
      sponsor_note,
      prize_pool: [{place, amount}],  — "The purse" kv panel
      standings: [{place,team}]|null, — null = "Results not yet recorded" note;
                                        an array renders the placings list with
                                        the medal treatment. NEVER an empty
                                        podium with dashes.
      teams: [{seed, name, captain,   — teamgrid; count comes from the data
               players: [names]}],      (12 in 2025, 10 in 2026 — nothing
                                        hardcoded to ten)
      lede, roster_note, coming,      — copy fields
      discord
    } } }
```

**Degradation is absence.** For 2025: no Stats, no Results, no Archive, no
Rules sections exist in the rendered view — not empty ones. Its standings are
`null` (the 2025 sheet has no bracket/standings/match-log tab), so the record
shows teams, venue, purse and format plus a "Results not yet recorded"
note-box; when the operator supplies placements it is a data edit
(`standings: [{place, team}…]`) and the medal list renders. Coming Soon shows
the masthead and a single "What publishes here" panel. Verified: switching
editions leaves zero dashes, zero empty podiums, zero empty bands.

**Philly 2025 content** comes from `lan-stats/philly-2025.json` (the 2025
registration sheet): 12 teams / 71 registered players, captains, seeds, entry
fee, $3,000/$1,800/$600 purse, TD cK, Shmaltz's venue backing.
⚠️ **The rosters were transcribed from the rendered sheet grid** (view-only;
export 403s), not exported from a database — proof-read before publishing.
The page carries that caveat in the 2025 view's roster footnote too.

**The gate is per-edition.** `statsPublished` lives on the edition; the mock
switcher now flips the *active* edition's flag (and disables itself on
editions with no stats markup). 2026's gate behaviour is unchanged.

### Feedback form (change 10)

A site-level §Feedback (last section, every edition — it should not compete
with results/stats, but stays reachable; nav link included). Modelled on
support-web's report form (same `.field` treatment, honeypot off-screen text
input, hidden fill-time field, maxlength 2000, inline `role="status"` result
line, "never public" fineprint) with one deliberate difference: **attribution
is the point, so there is no anonymous path.** Two states, both rendered via
the mockup switcher:

- **Signed out:** a prompt panel explaining attribution + "Sign in with
  Discord" (production: lan-web's OAuth flow, `identify` scope only).
- **Signed in:** the form, headed by a "Sending as *name* · Discord" pill so
  the sender sees exactly what will be attached.

Side panels: "Why sign in?" (so staff can answer) and a "Never public"
note-box — no feedback list, no ticket tracker, no status page; the submitter
gets the confirmation line and nothing else. Categories: event / site & stats /
next year / other.

**Deployment prerequisites, not assumptions** (for whoever wires the backend):

- Feedback posts to Discord guild **1203444168106705007** — a *different*
  server from the KTP guild the support site posts to (579024206931689482).
- **The channel ID within that guild is unknown** — the operator has not
  supplied one, and `#server-reports`/`#player-reports` belong to the support
  site. Open question below.
- **A redirect URI must be registered on the Discord application** for this
  site's OAuth callback (same as support.ktpdod.com/auth/callback was).
- **The relay bot must be a member of that guild with channel access.** The
  relay authenticates as "KTP Score Bot", which lives in the KTP guild; its
  membership of 1203444168106705007 is unverified. When support-web's channels
  were first wired, the bot was in the guild but lacked channel access and
  every post failed with Discord error **50001 "Missing Access"** — it looks
  like an auth failure and is not. Check membership + channel permission
  before debugging anything else.

### Verification (this pass)

Machine-checked: CSS braces 272/272, no undefined `var(--…)`, all tags paired,
15/15 bracket cards, 14/14 veto map rows matching veto.json, 58/58 demo rows ×
119 links with correct static counts, 61/61 players per day with `tm`/`st`/`cb`
and object-shaped hitboxes, editions JSON parses (12 teams / 71 players in
2025, standings null). Chrome (served over localhost — the extension refuses
file://): zero console messages on load; detail expansion opens/closes with
kills-per-half + flags-per-half in the ledger and no `undefined` anywhere;
team filter → 6 rows, composes with position (NATO+Sniper → 1) and map, head
names the view; 2025 edition hides all seven 2026 sections + their nav links,
renders 12 team cards / 71 roster rows / purse / "Results not yet recorded",
zero podium scaffolding; Coming Soon renders masthead + one panel; gate mock
flips 2026's stats off/on and is disabled on 2025; feedback states flip, submit
shows the confirmation line and stamps the fill-time field; no body horizontal
scroll in any edition.

### Still open after this pass

- **Feedback channel ID** in guild 1203444168106705007 — operator to supply.
- **Relay bot membership** of that guild (see the 50001 note above) — verify at
  deploy time.
- **OAuth redirect URI** registration on the Discord application — deploy
  prerequisite.
- **Philly 2025 standings** — `standings` stays null until the operator hands
  over placements; then it is a one-line data edit.
- **Philly 2025 roster proof-read** — names were transcribed from the rendered
  sheet, not exported.
- VOD links — the Broadcast panel still holds the slot.
- The two team-attribution gaps in the demo archive (`1785613505-KTP4`,
  `1785689132-KTP4`) still show "not recorded" pending the operator's rename fix.
- The old `index.html` still carries the Alopex casting credit and the
  pre-event copy.

## 12. Fifth pass — 2026-08-09 (one grid, three views)

### The stats rework

The two-tab day board and the separate weekend leaderboard merged into **one
grid with three views** — Saturday / Sunday / Full weekend as three `.daytab`s
(the existing component, extended to three columns via `.daytabs.three`) on a
single generated section that now carries `id="stats"`, so the nav link and
the publication gate keep working unchanged. The whole section — notes, tabs,
filters, table, renderer — is generated by `lan-stats/inject_season_board.py`
between the season-board markers; the old static section was removed, and
2026 no longer invokes `buildStatsBoard` (2025 still does, untouched).

**Every view now runs the same KTPR** — the current team formula from
`docs/ktpr_mcp/ktpr_engine.py` (`[profiles.new]`, `team_placement_weight`
forced to 0), computed per view by `lan-stats/build_season_board.py`:
per-day views against that day's own per-role medians (Sunday's field is 45
regulars vs Saturday's 61; every role clears `class_min_size` on both days),
the weekend view against combined totals. **This supersedes §5's "Per-day
incomparability — structural, three ways" and the "the two boards never
merge" note-box**: the boards do merge now, and the incomparability claim
survives in its true form — same formula everywhere, *different baseline
populations per view* — stated in the note-box, the baseline strip (which now
shows the regulars-per-position counts that actually set the medians), the
tab faces, and the KTPR tooltip.

Mechanics worth recording:

- **Columns are uniform across the three views** (# · Player · Pos · KTPR ·
  Style · K/D · Kills · Deaths · Flags · HS · Assists · Damage · Streak ·
  Breaks · Prone · detail), so the grid never reshapes on a view switch. The
  weekend row is aggregated in the renderer from the two day rows of
  `#lan-data`: sums for counts, max for the streak (its story travels with
  it), rates recomputed from summed totals — never an average of two days'
  rates. The join is by name per day and 18 of 61 players re-tagged between
  days, so the payload carries both day names per player and the injector
  hard-fails unless the name join is total in both directions.
- **Filters carried across all views**: position, team, and the weekend
  board's style chips (tier/archetype are computed per view). The **map
  filter is disabled — not hidden — on the weekend view** (`.chip[disabled]`
  + inline hint): map splits are per-day and there is no cross-day map
  aggregation.
- **Map boards** are scored against the day's baselines with `tw_break=0`
  (weights renormalize exactly): no per-map break counts exist, and scoring
  invented zeros would penalize unevenly. Said in the status-foot and the
  KTPR tooltip when a map view is active. Map views still drop
  Streak/Breaks/detail, which are day-level.
- **HUD badges** stay on assists and capture breaks (the two HUD-sourced
  rating inputs) and on the Prone column, which is genuinely HUD-sourced;
  damage lost its badge when it moved to HLStatsX. `.srcbadge` gained a
  static-position variant for prose (`.note-box`/`.status-foot`) — the
  absolute placement is for column headers, and in a note-box it silently
  rendered off-flow.
- The renderer initializes on DOMContentLoaded because it reads `#lan-data`,
  which sits later in the document than the generated section.

⚠️ The new per-day KTPR moves the figures quoted by three proposed awards
(MVP · Saturday, MVP · Sunday, Best six by position) and changes their
shortlists (Sunday's leader flips vertex → bR0M). Deliberately **not**
applied to `awards.json` — a shortlist change is a nomination change, which
is the operator's call. The recomputed lists are in the session report.

### Verification (this pass)

All four generators `--check`-clean and idempotent; `season-board.json`'s
weekend view byte-identical to the pre-rework board (the weekend formula did
not change); injector verified the name join 61/61 per day and per map.
Chrome over localhost, prototype and built `dist/` both: zero console errors;
weekend default view renders 61 players / 48-regular baseline; Saturday top
matches the generator (hildebrand? 1.440); map chip → 13-column view with the
day-baseline note in the tooltip; style filter composes; sort-by-assists
moves gold to the assists leader and reversing the sort leaves the medals
with the leaders; weekend detail panel shows merged class spawns, summed
matches/halves and Saturday's 13-kill streak story; 2025's board renders
exactly as before with the unified section absent.

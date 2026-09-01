# Telemetry causal links v1

## Purpose

This extension defines only direct, producer-observed links. It forbids a
consumer from manufacturing a relationship by nearest timestamp, common player
pair, or a configurable time window.

## Exact death-group links

At one DODX death hook, the producer can observe all of the following before
the victim's damage matrix is cleared:

1. the victim's authoritative life-end boundary;
2. the non-teamkill frag context, when the stock frag row exists; and
3. each explicit assist awarded from that same victim/death calculation.

The schema extension will carry the life-end source-event key on a frag and on
every assist emitted by this hook. An assist may additionally carry the emitted
frag source-event key when a non-teamkill frag marker was successfully queued.
Those fields mean "observed in the same death hook", not merely "nearby".

## Explicit non-links

- A damage hit is not automatically linked to a later frag. It is a fact about
  that hit; a later kill does not prove the hit was causal.
- A teamkill, world death, suicide, disconnected player, missing life marker,
  or dropped frag marker has no frag parent. The corresponding nullable link
  remains absent.
- The generic HLStatsX action row remains compatible evidence but is not a
  canonical parent relation.

## Persistence and replay

The private link key is `(match_id, half, producer_sequence)`. It is valid
only within the same server producer context. Replays must retain the original
link values; a conflicting replay is rejected. The link fields must be nullable
for legacy capture rows and for honest no-parent cases.

## Analytics handling

`death_group` is available only when the referenced life-end event, and any
referenced frag, resolve in the same validated producer context. A missing link
is `unavailable`, never a negative contribution. Public packets may publish
only aggregate, privacy-suppressed counts of link availability.

## Acceptance tests

- A non-teamkill death produces one life-end key; its frag and all qualifying
  assists reference that key.
- A dropped frag marker leaves assist frag-parent keys null without changing
  their life-end key.
- Teamkills, suicides, and world deaths produce no frag-parent key.
- Replayed markers are idempotent; mismatched parent keys are rejected.
- A bot match exercises a normal non-teamkill death and validates that the
  persisted keys resolve within one match half.

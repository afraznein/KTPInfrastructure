### `scripts/mmr`: `import-mmr` inspects identifier keys and values, not only row field names (2026-10-01)

`mmr_payload.validate_for_import` only checked `f in row` for four exact field
names over the rows of a list-shaped `players`. Three things got past it:

- a `players` **object** keyed by player was refused as "payload carries no
  players", so the identifier leg never ran and the refusal never said that
  the keys were raw ids;
- anything outside `players` was not inspected, though the importer writes the
  whole document;
- a SteamID-shaped alias, or a field spelled `steamId`, passed.

The guard now walks the whole payload and refuses forbidden or id-shaped keys at
any depth (field names after case and separator folding, SteamID2/3/64 shapes,
digit-only keys) and SteamID-shaped string values. It runs before the shape
checks, so a shape refusal still names a leak. An object-shaped `players` is
refused by name, because the consumer reads a list of alias rows. Pseudonymous
keys pass. The live published payload on `mmr-ratings` still validates clean.

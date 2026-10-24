### `scripts`: say why the geometry emitter targets the site's table and not the report payload (2026-10-24)

`emit_site_map_geometry.py` enforced that rule and never recorded the reason for it. Report rows
are immutable, so geometry delivered inside a report freezes at the moment that report was
written and can never be corrected afterwards -- and shipped descriptors have already needed
correcting once. A rule with no reason beside it is the kind a later pass simplifies away.

Docstring only; no behaviour change.

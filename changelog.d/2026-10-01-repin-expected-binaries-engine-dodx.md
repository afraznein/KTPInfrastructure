### `provision`: re-pin `expected-binaries.conf` to the live engine and dodx (2026-10-01)

The engine pin still named 3.22.0.1016-dev (`cbb0a71d…`) and the dodx pin
2.7.33.5934 (`b0d1fb1c…`), so `audit-fleet-drift.py` reported both as drift on
every host while the fleet was uniform. Re-pinned to engine 3.22.0.1030-dev
(`39efd9da…`, live since the 2026-10-01 03:00 ET swap) and dodx 2.7.33.5943
(`a15e9875…`, live since the 2026-09-28 swap), measured on all 24 instances.
The other five entries were measured unchanged.

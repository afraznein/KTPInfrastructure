### `docs`: ban-list renderer states the measured distributor fan-out (2026-11-25)

The header comment of `scripts/ktp-render-banlist.sh` said a file placed in `distribute/` reaches all
24 instances "within ~15s". The watcher debounces for 5 s and then takes 18-21 s to reach all 24 for a
small file, so the comment now says about half a minute. Comment only; no behaviour change.
`docs/LIVE_SCRIPT_INVENTORY.md` re-pins the script's row to the new blob (`de416342` @ `6fb2f5214a`), which is
what made the comment-only edit in #891 fail its pin check; the data-server install follows the merge.

### `scripts`: the post-restart soak reports why the gate produced no report (2026-11-10)

`suite_post_restart` ran `ktp-verify-deploy ... 2>&1` and, when no `--out` JSON
appeared, attached only the captured stderr as the check's detail. The redirect
had already moved stderr into stdout, and stdout was discarded, so the detail was
always empty. From 2026-10-25 to 2026-11-07 the gate refused every night because
its installed copy was stale, printed that refusal in full, and the soak reported
"failed to read verify-deploy output" fourteen times without once naming it.

The gate now runs without the redirect, the soak keeps both streams, and the
failure check carries the gate's exit status in its summary and its own output in
the detail that goes to Discord.

Three cases run the real `sh()` through a real shell against a fake gate, because
the defect lived in the shell redirect and a stubbed `sh()` would pass against the
broken code: a refusal on stderr and output on stdout each reach the detail, and a
gate that fails silently still reports RED with no detail. Restoring the old
stream handling fails the first two; the third passes either way, as a control.

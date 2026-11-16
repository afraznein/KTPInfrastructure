### ktp-nettest: the stall test no longer reports one stall per second from a throttled browser (2026-11-16)

- Every real run reported exactly 60 stalls over 250 ms in a 60 s test, on a wired line with 0%
  loss. The sender was paced by a 10 ms page timer, and Chrome clamps page timers to one wake-up a
  second in a hidden tab and in a `display:none` cross-origin frame, which is how the site embeds
  `/frame`. Each wake-up then sent 100 packets at once and the echoes came back in bursts, so the
  gap between bursts read as a stall. Reproduced locally against the real node with a wall-clock
  aligned 1 Hz timer: 60 stalls, worst 944 ms, 0% loss; with the timer unclamped, 0 stalls.
- Sending is now driven by a dedicated worker's 10 ms tick (`GET /tick.js`, same origin, allowed by
  the frame's existing CSP) with the page timer kept as a backup clock.
- A gap is charged to the line only for the part the sender was not itself paused, using the
  recorded send time of every packet. The result also carries `stall_recv_gaps_250` /
  `stall_recv_worst_gap_ms` (the old raw measure) and `stall_send_gaps_250` /
  `stall_send_worst_gap_ms` (pauses in the browser's own sending). A run with send gaps was paced
  by the browser, not the line. `client_version` is now `ktp-nettest-client/2`, so earlier rows can
  be told apart; their `stall_gaps_250` should not be trusted.
- The site's save schema strips unknown keys, so the new fields are dropped until the site stores
  them; nothing breaks meanwhile.

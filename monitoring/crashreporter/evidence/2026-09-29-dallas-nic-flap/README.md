# 2026-09-29 Dallas NIC flap — five retained backtraces

Five `hlds_linux` cores from `neindallas`, all within two seconds of each other
(13:08:53–13:08:55 EDT). The `.bt` and `.reported` sidecars are verbatim as the
daemon wrote them on the day.

## Why these are kept in the repo

They are the only symbol-matched backtraces that exist for this event, and they
could not be regenerated after `engine_i486.so` was replaced on 2026-10-20. See
the regenerate-in-place note in the parent README: re-running the daemon over
these cores today produces a *different and wrong* top frame, because gdb
resolves the same address against the newer binary.

The cores themselves are not here — about 116 MB each, and useless without the
matching engine. The `.bt` is the durable artifact.

## What happened

A four-minute link flap (`igb enp1s0f0` down 13:06:53, up 13:11:08) took the
interface out from under all five instances. The LinuxGSM monitor cannot
distinguish *my network is down* from *the server hung*, so it restarted all
five into the dead link at 13:08:35. Each new process reached map load, called
`NET_Config`, failed to bind, and fatal-exited.

The stack is the same in all five:

```
#0  Sys_Error(char const*, ...)
#1  NET_Config(int)
#2  Host_InitializeGameDLL()
#3  Host_Map_f()
#4  Cmd_ExecuteString_internal(char const*, cmd_source_s, IGameClient*)
```

So these are fatal exits, not engine faults — the signal is SIGSEGV but the top
frame is the engine's own error path. Do not read them as five crashes.

## Delivery

All five failed to post on the day: the daemon held its own copy of the relay
secret and a rotation had left it behind, so all 25 attempts (5 cores × the
5-attempt cap) failed inside twenty minutes. The secret-precedence fix landed
2026-10-13.

One core's sidecar was re-armed on 2026-10-22 to test that fix. It posted on the
first attempt, which is the only end-to-end proof that this host's reporter can
deliver at all. That re-arm is also what overwrote the live `.bt` and produced
the regeneration finding above.

`core.hlds_linux.502465.1790701733.reported` therefore reads
`discord_posted: true, post_attempts: 1`; the other four still read
`post_attempts: 5`, which is what give-up looks like.

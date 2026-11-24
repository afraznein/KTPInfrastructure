### publish-base-image: build on ubuntu-24.04 again (2026-11-14)

- The nightly test-base publish has failed since 2026-10-26, when `ubuntu-latest` moved to the
  26.04 image. That image ships docker 29.4.2, whose default seccomp profile blocks the i386
  `socketcall(2)` syscall. steamcmd is 32-bit, so inside the image build it cannot open a socket
  and stops with "Steamcmd needs to be online to update".
- The job now runs on `ubuntu-24.04` (docker 28.0.4), which is where the last green run built.
- A new step checks the runner's docker version before the image build and fails with the real
  cause if it is 29.4.2.

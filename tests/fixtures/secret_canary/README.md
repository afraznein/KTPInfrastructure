# Secret-scan canary fixtures

Every file here plants the same fake value in a different format. `ktp_secret_scan
selftest` must find it in **all** of them; a format that stops matching is reported
by name and fails the build.

The value authenticates nothing and is public on purpose — it is the positive
control that proves the matcher can still fire. **Never remove a format** to make
a scan pass, and never rotate the canary: KTPCANARY-Zm9vYmFy-DO-NOT-ROTATE

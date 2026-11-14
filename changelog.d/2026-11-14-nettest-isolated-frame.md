### ktp-nettest: the website runs the test in a sandboxed frame on the node (2026-11-14)

- New `GET /frame` and `GET /frame.js`. The website embeds `/frame` in a sandboxed iframe and
  drives the run by `postMessage`, so `client.js` executes in the node's origin instead of being
  loaded as a `<script>` into the site's. A wrong or compromised node URL can no longer run code
  with the site's privileges.
- `/frame` sends its own CSP: this node's scripts only, requests to this node only, and
  `frame-ancestors` limited to `KTP_NETTEST_ORIGIN`. Both sides check each other's exact origin.
- Nothing is deployed yet; no region is live. The site half is in keep-the-prac.

# `sites/` — tracked static pages and web apps

Where each thing under this directory is actually served from, because the URL
does not tell you and a wrong guess becomes a write in the wrong place.

## Nothing here deploys itself

Only `lan-web` has deploy tooling (`provision/deploy-lan-web.sh`). Every other
page in this directory reaches production by a manual copy to the data server.
Merging a change to `sites/` does not publish it, and no workflow or script in
this repo will. Judge a page by fetching its public URL — not by the PR merging,
and not over `http://127.0.0.1`, which cannot reach these vhosts.

## `sites/netcode/index.html` — the netcode advice page

Public URL `https://fastdl.ktpdod.com/netcode/`. **It is not served from the
FastDL docroot.** The `fastdl.ktpdod.com` vhost has `root /var/www/fastdl`, but
`/netcode` is an nginx `alias`:

```nginx
location /netcode {
    alias /var/www/netcode; index index.html; autoindex off;
    ...
}
```

So the file lives at `/var/www/netcode/index.html`, and `/var/www/fastdl/netcode`
does not exist. One useful consequence: being outside `/var/www/fastdl/` means
this page is not FTP-reachable, unlike anything under that docroot.

Deploying a change:

- Back up the live file to `/root/netcode-backups/` first. That directory is
  deliberately outside every docroot — a backup left beside a live page is a
  served page, and `sites-enabled/` is included as `*`, so one left there is
  loaded.
- Capture owner and mode from the live file and restore them rather than
  assuming; it is `www-data:www-data`, mode 644.
- `/var/www/netcode/` also holds the page's icons and logo. They are not tracked
  at that path here, so copy `index.html` alone unless an asset really changed.

## Locating a page's real path

Match the **outgoing md5** across candidate paths instead of trusting a path you
reasoned your way to. That is how the netcode page was found at all: the obvious
candidate under the FastDL docroot came back absent, and the md5 sweep is what
kept a wrong guess from becoming a write somewhere else. It applies to
`sites/fastdl`, `sites/support-web` and `sites/wsdod-lan-2026` too, whose serving
paths are not recorded here.

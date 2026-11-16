### ktp-nettest: a stall offer can no longer crash the node (2026-11-16)

- The first real end-to-end run on a node crashed the whole process on `POST /stall/offer`:
  `uv_interface_addresses returned Unknown system error 97`. The unit's
  `RestrictAddressFamilies` blocked `AF_NETLINK`, which `os.networkInterfaces()` needs, and the
  throw came from werift's mDNS responder in a socket callback, outside any request. The unit now
  allows `AF_NETLINK`.
- The node drops a browser's mDNS `.local` candidates (and the offer's `a=end-of-candidates`)
  before werift sees them, so werift never starts its multicast-dns responder. Those names
  resolve only on the player's LAN; the browser is still reached as a peer-reflexive candidate.
- The wait for host-candidate gathering is bounded at 5 s. werift swallows a gathering failure
  and never reports `complete`, so that request used to hang; it now answers 400.
- README § Deploy: the netlink requirement, which `systemd-analyze verify` cannot catch, and a
  certbot deploy hook to reload nginx, since a webroot renewal does not.

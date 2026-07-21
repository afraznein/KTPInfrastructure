#!/bin/bash
# KTP LAN — show this box's IP address(es).
#
# Run at the venue once the box is on the network. Take the primary IP, put it
# into LAN_IP= in lan-deploy.conf (shortcut: ~/lan-deploy.conf), then re-apply
# the IP-dependent config.

echo "=== Primary LAN IP (use this for LAN_IP) ==="
hostname -I | awk '{print $1}'
echo
echo "=== Gateway-facing IP (use this if the box has more than one NIC) ==="
ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K\S+' || echo "(no default route / box is offline)"
echo
echo "=== All interfaces (interface  subnet) ==="
ip -4 -o addr show scope global | awk '{print $2, $4}'
echo
echo "Next: set LAN_IP in lan-deploy.conf, then re-apply the IP-dependent config."

#!/bin/bash
# Ensure all hlds_linux processes run at nice -5
# Deployed to: /home/dodserver/ensure-priority.sh
# Cron: */5 * * * * /home/dodserver/ensure-priority.sh

for pid in $(pgrep hlds_linux 2>/dev/null); do
  current=$(ps -o ni= -p $pid 2>/dev/null | tr -d ' ')
  if [ "$current" != "-5" ]; then
    sudo renice -n -5 -p $pid >/dev/null 2>&1
  fi
done

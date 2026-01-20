#!/bin/bash
  BACKUP_DIR="/opt/backups"
  TIMESTAMP=$(date +%Y%m%d_%H%M%S)
  MYSQL_PASS="KTPStats2025"
  mkdir -p "$BACKUP_DIR"
  mysqldump -u hlstatsx -p"$MYSQL_PASS" hlstatsx > "$BACKUP_DIR/hlstatsx_$TIMESTAMP.sql"
  tar -czf "$BACKUP_DIR/configs_$TIMESTAMP.tar.gz" /opt/ktp-file-distributor/*.json /opt/hlstatsx/scripts/*.conf /home/dod/distribute/addons/ktpamx/configs/ /etc/systemd/system/ktp-*.service /etc/systemd/system/hlstatsx.service 2>/dev/null
  find "$BACKUP_DIR" -name "*.sql" -mtime +28 -delete
  find "$BACKUP_DIR" -name "*.tar.gz" -mtime +28 -delete
  echo "Backup complete: $TIMESTAMP"


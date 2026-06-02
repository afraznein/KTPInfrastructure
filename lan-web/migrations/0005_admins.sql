-- Web-managed staff access. Bootstrap admins still come from LAN_ADMIN_DISCORD_IDS
-- (env) and can never be revoked here — that's the lockout guard.
CREATE TABLE IF NOT EXISTS lan_admins (
  discord_id  BIGINT UNSIGNED NOT NULL,
  label       VARCHAR(64) NULL,          -- friendly name/note (auto-filled from roster if blank)
  added_by    BIGINT UNSIGNED NULL,      -- discord id of the granting admin
  added_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (discord_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

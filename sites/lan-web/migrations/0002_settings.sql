-- Key/value settings for runtime toggles (poll open/closed, etc.).
CREATE TABLE IF NOT EXISTS lan_settings (
  k VARCHAR(64) NOT NULL PRIMARY KEY,
  v VARCHAR(255) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO lan_settings (k, v) VALUES ('poll_open', '0');

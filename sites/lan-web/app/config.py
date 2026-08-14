"""Environment-backed settings for the LAN web service."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    env: str
    secret_key: str
    base_url: str
    bind_host: str
    bind_port: int
    root_path: str
    discord_client_id: str
    discord_client_secret: str
    discord_redirect_uri: str
    discord_bot_token: str
    discord_webhook_url: str
    discord_announce_role_id: str
    discord_relay_url: str
    discord_relay_auth: str
    photo_report_channel_id: str
    photo_report_ping_user_id: str
    feedback_channel_id: str
    site_dir: str
    site_mount: str
    site_at_root: bool
    match_slugs_path: str
    owner_discord_id: str
    photo_thumb_px: int
    admin_discord_ids: frozenset
    master_admin_discord_ids: frozenset
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    demo_dir: str
    demo_max_bytes: int
    photo_dir: str
    photo_max_bytes: int

    @property
    def is_prod(self) -> bool:
        return self.env.lower() == "prod"


def _parse_ids(raw: str) -> frozenset:
    return frozenset(int(x) for x in raw.replace(",", " ").split() if x.strip().isdigit())


# Env-driven so a wrong id is a config change rather than a redeploy. An unset
# variable falls back rather than emptying: no masters means nobody can publish
# an award at all.
MASTER_ADMINS = "218890328273321984,143944554440163328,749415733393621101"


def load() -> Settings:
    return Settings(
        env=os.getenv("LAN_WEB_ENV", "dev"),
        secret_key=os.getenv("LAN_WEB_SECRET_KEY", "dev-insecure-change-me"),
        base_url=os.getenv("LAN_WEB_BASE_URL", "http://127.0.0.1:8099"),
        bind_host=os.getenv("LAN_WEB_BIND_HOST", "127.0.0.1"),
        bind_port=int(os.getenv("LAN_WEB_BIND_PORT", "8099")),
        root_path=os.getenv("LAN_WEB_ROOT_PATH", ""),
        discord_client_id=os.getenv("DISCORD_CLIENT_ID", ""),
        discord_client_secret=os.getenv("DISCORD_CLIENT_SECRET", ""),
        discord_redirect_uri=os.getenv("DISCORD_REDIRECT_URI", ""),
        discord_bot_token=os.getenv("LAN_DISCORD_BOT_TOKEN", ""),
        discord_webhook_url=os.getenv("LAN_DISCORD_WEBHOOK_URL", ""),
        discord_announce_role_id=os.getenv("LAN_DISCORD_ANNOUNCE_ROLE_ID", "1343215543175352392"),
        # The relay URL already carries its /reply path — appending it again 404s.
        discord_relay_url=os.getenv("LAN_DISCORD_RELAY_URL", ""),
        discord_relay_auth=os.getenv("LAN_DISCORD_RELAY_AUTH", ""),
        photo_report_channel_id=os.getenv("LAN_PHOTO_REPORT_CHANNEL_ID", "1535106233877663744"),
        photo_report_ping_user_id=os.getenv("LAN_PHOTO_REPORT_PING_USER_ID", "218890328273321984"),
        feedback_channel_id=os.getenv("LAN_FEEDBACK_CHANNEL_ID", "1535106233877663744"),
        site_dir=os.getenv("LAN_SITE_DIR", ""),
        site_mount=os.getenv("LAN_SITE_MOUNT", "/2026"),
        # Serve the WSDoD site at "/" as well, and move the LAN briefing to
        # /lan. Off by default so deploying this is a no-op and the switch is
        # an env change plus a restart — which is also the rollback.
        site_at_root=os.getenv("LAN_SITE_AT_ROOT", "").lower() in ("1", "true", "yes"),
        # The build's frozen key → slug map, read at runtime. Defaults to the
        # repo layout; a standalone deploy sets the path. Absent is survivable —
        # the raw-key redirect 404s and every slug URL is unaffected.
        match_slugs_path=os.getenv(
            "LAN_MATCH_SLUGS",
            str(Path(__file__).resolve().parents[2] / "wsdod-lan-2026" /
                "lan-stats" / "match-slugs.json"),
        ),
        # Deliberately one id, not the admin list: closing a vote ends it for
        # everyone, so it does not widen when staff are added.
        owner_discord_id=os.getenv("LAN_OWNER_DISCORD_ID", "218890328273321984"),
        photo_thumb_px=int(os.getenv("LAN_PHOTO_THUMB_PX", "480")),
        admin_discord_ids=_parse_ids(os.getenv("LAN_ADMIN_DISCORD_IDS", "")),
        master_admin_discord_ids=_parse_ids(
            os.getenv("LAN_MASTER_ADMIN_DISCORD_IDS", "") or MASTER_ADMINS),
        db_host=os.getenv("LAN_DB_HOST", "127.0.0.1"),
        db_port=int(os.getenv("LAN_DB_PORT", "3306")),
        db_user=os.getenv("LAN_DB_USER", "ktp_lan"),
        db_password=os.getenv("LAN_DB_PASSWORD", ""),
        db_name=os.getenv("LAN_DB_NAME", "ktp_lan"),
        demo_dir=os.getenv(
            "LAN_DEMO_DIR",
            str(Path(__file__).resolve().parent.parent / "data" / "demos"),
        ),
        demo_max_bytes=int(os.getenv("LAN_DEMO_MAX_MB", "250")) * 1024 * 1024,
        photo_dir=os.getenv(
            "LAN_PHOTO_DIR",
            str(Path(__file__).resolve().parent.parent / "data" / "photos"),
        ),
        photo_max_bytes=int(os.getenv("LAN_PHOTO_MAX_MB", "15")) * 1024 * 1024,
    )


settings = load()

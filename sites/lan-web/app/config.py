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
    admin_discord_ids: frozenset
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
        admin_discord_ids=_parse_ids(os.getenv("LAN_ADMIN_DISCORD_IDS", "")),
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

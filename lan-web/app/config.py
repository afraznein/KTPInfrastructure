"""Environment-backed settings for the LAN web service."""
from __future__ import annotations

import os
from dataclasses import dataclass


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
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str

    @property
    def is_prod(self) -> bool:
        return self.env.lower() == "prod"


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
        db_host=os.getenv("LAN_DB_HOST", "127.0.0.1"),
        db_port=int(os.getenv("LAN_DB_PORT", "3306")),
        db_user=os.getenv("LAN_DB_USER", "ktp_lan"),
        db_password=os.getenv("LAN_DB_PASSWORD", ""),
        db_name=os.getenv("LAN_DB_NAME", "ktp_lan"),
    )


settings = load()

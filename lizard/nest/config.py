from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class NestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LIZARD_", env_file=".env", extra="ignore")

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "lizard"
    mqtt_username: str | None = None
    mqtt_password: SecretStr | None = None
    mqtt_tls: bool = False

    listen_host: str = "0.0.0.0"
    listen_port: int = 8000
    data_dir: Path = Field(default=Path("./data"))

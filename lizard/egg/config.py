from __future__ import annotations

import socket
from typing import Any

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from lizard.common.models import AlertThreshold


class EggSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LIZARD_", env_file=".env", extra="ignore")

    host_id: str = Field(default_factory=socket.gethostname)
    hostname: str = Field(default_factory=socket.gethostname)
    interval_seconds: int = Field(default=15, ge=1)

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "lizard"
    mqtt_username: str | None = None
    mqtt_password: SecretStr | None = None
    mqtt_tls: bool = False
    remote_config_enabled: bool = True

    cpu_percent_thresholds: list[AlertThreshold] = Field(
        default_factory=lambda: [
            AlertThreshold(level="warning", value=10.0),
            AlertThreshold(level="critical", value=90.0),
        ]
    )
    memory_percent_thresholds: list[AlertThreshold] = Field(
        default_factory=lambda: [AlertThreshold(level="warning", value=90.0)]
    )
    disk_percent_thresholds: list[AlertThreshold] = Field(
        default_factory=lambda: [AlertThreshold(level="warning", value=90.0)]
    )
    gpu_percent_thresholds: list[AlertThreshold] = Field(
        default_factory=lambda: [AlertThreshold(level="warning", value=95.0)]
    )
    temperature_celsius_thresholds: list[AlertThreshold] = Field(
        default_factory=lambda: [AlertThreshold(level="warning", value=85.0)]
    )

    def with_remote_update(self, payload: dict[str, Any]) -> EggSettings:
        allowed_keys = {
            "interval_seconds",
            "cpu_percent_thresholds",
            "memory_percent_thresholds",
            "disk_percent_thresholds",
            "gpu_percent_thresholds",
            "temperature_celsius_thresholds",
        }
        updates = {key: value for key, value in payload.items() if key in allowed_keys}
        current = self.model_dump()
        current.update(updates)
        return type(self).model_validate(current)

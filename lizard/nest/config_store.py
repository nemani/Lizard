from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from lizard.common.models import AlertConfig, ConfigAck, ConfigEnvelope


class ConfigStore:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "configs.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._configs: dict[str, ConfigEnvelope] = {}
        self._acks: dict[str, ConfigAck] = {}
        self.load()

    def load(self) -> None:
        if not self._path.exists():
            return
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        with self._lock:
            self._configs = {
                key: ConfigEnvelope.model_validate(value)
                for key, value in raw.get("configs", {}).items()
                if isinstance(value, dict)
            }
            self._acks = {
                key: ConfigAck.model_validate(value)
                for key, value in raw.get("acks", {}).items()
                if isinstance(value, dict)
            }

    def next_envelope(self, scope: str, config: AlertConfig) -> ConfigEnvelope:
        with self._lock:
            current = self._configs.get(scope)
            version = (current.version + 1) if current is not None else 1
            envelope = ConfigEnvelope(
                scope=scope,
                version=version,
                updated_at=datetime.now(timezone.utc),
                config=config,
            )
            self._configs[scope] = envelope
            self._flush()
            return envelope

    def get(self, scope: str) -> ConfigEnvelope | None:
        with self._lock:
            return self._configs.get(scope)

    def all(self) -> dict[str, ConfigEnvelope]:
        with self._lock:
            return dict(self._configs)

    def put_ack(self, ack: ConfigAck) -> None:
        with self._lock:
            self._acks[ack.host_id] = ack
            self._flush()

    def acks(self) -> dict[str, ConfigAck]:
        with self._lock:
            return dict(self._acks)

    def _flush(self) -> None:
        encoded = {
            "configs": {
                scope: config.model_dump(exclude_none=True, mode="json")
                for scope, config in self._configs.items()
            },
            "acks": {
                host_id: ack.model_dump(mode="json") for host_id, ack in self._acks.items()
            },
        }
        self._path.write_text(json.dumps(encoded, indent=2, sort_keys=True), encoding="utf-8")

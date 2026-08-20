from __future__ import annotations

import json
import threading
from pathlib import Path

from lizard.common.models import AlertConfig


class ConfigStore:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "configs.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._configs: dict[str, AlertConfig] = {}
        self.load()

    def load(self) -> None:
        if not self._path.exists():
            return
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        with self._lock:
            self._configs = {
                key: AlertConfig.model_validate(value)
                for key, value in raw.items()
                if isinstance(value, dict)
            }

    def put(self, scope: str, config: AlertConfig) -> None:
        with self._lock:
            self._configs[scope] = config
            self._flush()

    def get(self, scope: str) -> AlertConfig | None:
        with self._lock:
            return self._configs.get(scope)

    def all(self) -> dict[str, AlertConfig]:
        with self._lock:
            return dict(self._configs)

    def _flush(self) -> None:
        encoded = {
            scope: config.model_dump(exclude_none=True, mode="json")
            for scope, config in self._configs.items()
        }
        self._path.write_text(json.dumps(encoded, indent=2, sort_keys=True), encoding="utf-8")

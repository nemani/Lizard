from __future__ import annotations

import threading
from pathlib import Path

from lizard.common.models import MetricsEnvelope


class MetricsStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._latest: dict[str, MetricsEnvelope] = {}

    def put(self, envelope: MetricsEnvelope) -> None:
        with self._lock:
            self._latest[envelope.host_id] = envelope
            path = self._data_dir / f"{envelope.host_id}.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(envelope.model_dump_json() + "\n")

    def latest(self) -> list[MetricsEnvelope]:
        with self._lock:
            return sorted(self._latest.values(), key=lambda item: item.host_id)

    def get(self, host_id: str) -> MetricsEnvelope | None:
        with self._lock:
            return self._latest.get(host_id)

    def history(self, host_id: str, limit: int = 240) -> list[MetricsEnvelope]:
        path = self._data_dir / f"{host_id}.jsonl"
        if not path.exists():
            return []

        lines = _read_tail_lines(path, limit)
        return [MetricsEnvelope.model_validate_json(line) for line in lines if line]

    def load_existing_latest(self) -> None:
        for path in self._data_dir.glob("*.jsonl"):
            last_line = _read_last_line(path)
            if not last_line:
                continue
            envelope = MetricsEnvelope.model_validate_json(last_line)
            self._latest[envelope.host_id] = envelope


def _read_last_line(path: Path) -> str | None:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        if position == 0:
            return None
        buffer = bytearray()
        position -= 1
        while position >= 0:
            handle.seek(position)
            char = handle.read(1)
            if char == b"\n" and buffer:
                break
            buffer.extend(char)
            position -= 1
        return bytes(reversed(buffer)).decode("utf-8").strip()


def _read_tail_lines(path: Path, limit: int) -> list[str]:
    if limit <= 0:
        return []

    with path.open("r", encoding="utf-8") as handle:
        lines = handle.readlines()
    return [line.strip() for line in lines[-limit:]]

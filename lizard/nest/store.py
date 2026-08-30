from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from lizard.common.models import HostInventory, HostStatus, MetricsEnvelope

LOGGER = logging.getLogger(__name__)


class MetricsStore:
    def __init__(self, data_dir: Path, max_jsonl_lines: int = 100_000) -> None:
        self._data_dir = data_dir.resolve()
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._latest: dict[str, MetricsEnvelope] = {}
        self._inventory: dict[str, HostInventory] = {}
        self._max_jsonl_lines = max_jsonl_lines

    def put(self, envelope: MetricsEnvelope) -> None:
        with self._lock:
            self._latest[envelope.host_id] = envelope
            path = self._host_path(envelope.host_id, ".jsonl")
            with path.open("a", encoding="utf-8") as handle:
                handle.write(envelope.model_dump_json() + "\n")
            self._rotate_if_needed(path)

    def latest(self) -> list[MetricsEnvelope]:
        with self._lock:
            return sorted(self._latest.values(), key=lambda item: item.host_id)

    def statuses(
        self,
        stale_after_seconds: int,
        offline_after_seconds: int,
        now: datetime | None = None,
    ) -> list[HostStatus]:
        observed_at = now or datetime.now(timezone.utc)
        with self._lock:
            latest = list(self._latest.values())
        return sorted(
            [
                _status_for_envelope(
                    envelope,
                    observed_at,
                    stale_after_seconds,
                    offline_after_seconds,
                )
                for envelope in latest
            ],
            key=lambda item: item.host_id,
        )

    def get(self, host_id: str) -> MetricsEnvelope | None:
        with self._lock:
            return self._latest.get(host_id)

    def put_inventory(self, inventory: HostInventory) -> None:
        with self._lock:
            self._inventory[inventory.host_id] = inventory
            path = self._host_path(inventory.host_id, ".inventory.json")
            path.write_text(inventory.model_dump_json(indent=2), encoding="utf-8")

    def inventory(self, host_id: str) -> HostInventory | None:
        with self._lock:
            return self._inventory.get(host_id)

    def inventories(self) -> list[HostInventory]:
        with self._lock:
            return sorted(self._inventory.values(), key=lambda item: item.host_id)

    def history(self, host_id: str, limit: int = 240) -> list[MetricsEnvelope]:
        path = self._host_path(host_id, ".jsonl")
        if not path.exists():
            return []

        with self._lock:
            lines = _read_tail_lines(path, limit)
        return _parse_metric_lines(path, lines)

    def load_existing_latest(self) -> None:
        for path in self._data_dir.glob("*.jsonl"):
            envelope = _read_latest_valid_envelope(path)
            if envelope is not None:
                self._latest[envelope.host_id] = envelope
        for path in self._data_dir.glob("*.inventory.json"):
            try:
                inventory = HostInventory.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError, ValueError):
                LOGGER.warning("skipping invalid inventory file: %s", path)
            else:
                self._inventory[inventory.host_id] = inventory

    def _host_path(self, host_id: str, suffix: str) -> Path:
        path = (self._data_dir / f"{host_id}{suffix}").resolve()
        if path.parent != self._data_dir:
            raise ValueError(f"host_id escapes data directory: {host_id!r}")
        return path

    def _rotate_if_needed(self, path: Path) -> None:
        """Truncate the JSONL file to the most recent max_jsonl_lines if it exceeds the limit."""
        if self._max_jsonl_lines <= 0:
            return
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size == 0:
            return
        tail = _read_tail_lines(path, self._max_jsonl_lines)
        line_count = sum(1 for _ in path.open("r", encoding="utf-8"))
        if line_count <= self._max_jsonl_lines:
            return
        LOGGER.info(
            "rotating %s: %d lines exceeds max %d, keeping last %d lines",
            path.name,
            line_count,
            self._max_jsonl_lines,
            self._max_jsonl_lines,
        )
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(tail) + "\n" if tail else "", encoding="utf-8")
        os.replace(tmp, path)


def _read_latest_valid_envelope(path: Path) -> MetricsEnvelope | None:
    for line in reversed(_read_tail_lines(path, 1000)):
        if not line:
            continue
        try:
            return MetricsEnvelope.model_validate_json(line)
        except (ValidationError, ValueError):
            LOGGER.warning("skipping invalid metrics line in %s", path)
    return None


def _parse_metric_lines(path: Path, lines: list[str]) -> list[MetricsEnvelope]:
    envelopes: list[MetricsEnvelope] = []
    for line in lines:
        if not line:
            continue
        try:
            envelopes.append(MetricsEnvelope.model_validate_json(line))
        except (ValidationError, ValueError):
            LOGGER.warning("skipping invalid metrics line in %s", path)
    return envelopes


def _read_tail_lines(path: Path, limit: int) -> list[str]:
    if limit <= 0:
        return []

    chunk_size = 8192
    chunks: list[bytes] = []
    lines_seen = 0
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        while position > 0 and lines_seen <= limit:
            read_size = min(chunk_size, position)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size)
            chunks.append(chunk)
            lines_seen += chunk.count(b"\n")

    data = b"".join(reversed(chunks))
    return [line.decode("utf-8").strip() for line in data.splitlines()[-limit:]]


def _status_for_envelope(
    envelope: MetricsEnvelope,
    now: datetime,
    stale_after_seconds: int,
    offline_after_seconds: int,
) -> HostStatus:
    age_seconds = max(0.0, (now - envelope.timestamp).total_seconds())
    if age_seconds >= offline_after_seconds:
        state = "offline"
    elif age_seconds >= stale_after_seconds:
        state = "stale"
    else:
        state = "online"

    return HostStatus(
        host_id=envelope.host_id,
        hostname=envelope.hostname,
        last_seen=envelope.timestamp,
        age_seconds=age_seconds,
        state=state,
        uptime_seconds=envelope.uptime_seconds,
        alert_count=len(envelope.alerts),
        critical_alert_count=sum(1 for alert in envelope.alerts if alert.level == "critical"),
    )

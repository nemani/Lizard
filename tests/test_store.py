from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from lizard.common.models import CpuMetrics, HostInventory, MemoryMetrics, MetricsEnvelope
from lizard.nest.store import MetricsStore, _read_tail_lines


def _envelope(host_id: str, cpu_percent: float) -> MetricsEnvelope:
    return MetricsEnvelope(
        host_id=host_id,
        hostname=host_id,
        uptime_seconds=123,
        cpu=CpuMetrics(overall_percent=cpu_percent, per_core_percent=[cpu_percent]),
        memory=MemoryMetrics(total_bytes=10, used_bytes=1, available_bytes=9, percent=10),
        disks=[],
        temperatures=[],
        gpus=[],
    )


def test_store_keeps_latest_and_reloads_jsonl(tmp_path) -> None:
    store = MetricsStore(tmp_path)
    store.put(_envelope("gpu-01", 10))
    store.put(_envelope("gpu-01", 20))

    reloaded = MetricsStore(tmp_path)
    reloaded.load_existing_latest()

    latest = reloaded.get("gpu-01")
    assert latest is not None
    assert latest.cpu.overall_percent == 20


def test_store_returns_host_history_in_order(tmp_path) -> None:
    store = MetricsStore(tmp_path)
    store.put(_envelope("gpu-01", 10))
    store.put(_envelope("gpu-01", 20))
    store.put(_envelope("gpu-01", 30))

    history = store.history("gpu-01", limit=2)

    assert [item.cpu.overall_percent for item in history] == [20, 30]


def test_store_history_skips_malformed_jsonl_lines(tmp_path) -> None:
    store = MetricsStore(tmp_path)
    store.put(_envelope("gpu-01", 10))
    (tmp_path / "gpu-01.jsonl").write_text(
        f"{_envelope('gpu-01', 10).model_dump_json()}\n{{not-json\n{_envelope('gpu-01', 20).model_dump_json()}\n",
        encoding="utf-8",
    )

    history = store.history("gpu-01", limit=10)

    assert [item.cpu.overall_percent for item in history] == [10, 20]


def test_store_reload_uses_latest_valid_jsonl_line(tmp_path) -> None:
    (tmp_path / "gpu-01.jsonl").write_text(
        f"{_envelope('gpu-01', 10).model_dump_json()}\n{{truncated\n",
        encoding="utf-8",
    )

    store = MetricsStore(tmp_path)
    store.load_existing_latest()

    latest = store.get("gpu-01")
    assert latest is not None
    assert latest.cpu.overall_percent == 10


def test_read_tail_lines_returns_only_requested_suffix(tmp_path) -> None:
    path = tmp_path / "large.jsonl"
    path.write_text("\n".join(str(index) for index in range(3000)) + "\n", encoding="utf-8")

    assert _read_tail_lines(path, 3) == ["2997", "2998", "2999"]


def test_store_reports_host_status_from_latest_heartbeat(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    store = MetricsStore(tmp_path)
    online = _envelope("gpu-01", 10)
    stale = _envelope("gpu-02", 20)
    offline = _envelope("gpu-03", 30)
    online.timestamp = now - timedelta(seconds=10)
    stale.timestamp = now - timedelta(seconds=70)
    offline.timestamp = now - timedelta(seconds=400)
    store.put(online)
    store.put(stale)
    store.put(offline)

    statuses = store.statuses(stale_after_seconds=60, offline_after_seconds=300, now=now)

    assert [(item.host_id, item.state, item.uptime_seconds) for item in statuses] == [
        ("gpu-01", "online", 123),
        ("gpu-02", "stale", 123),
        ("gpu-03", "offline", 123),
    ]


def test_store_persists_host_inventory(tmp_path) -> None:
    store = MetricsStore(tmp_path)
    store.put_inventory(
        HostInventory(
            host_id="gpu-01",
            hostname="gpu-01",
            os="Linux",
            os_version="Ubuntu 22.04",
            kernel="6.8.0",
            architecture="x86_64",
            python_version="3.12",
            cpu_logical_count=16,
            memory_total_bytes=100,
            disks=[],
            gpus=[],
        )
    )

    reloaded = MetricsStore(tmp_path)
    reloaded.load_existing_latest()

    assert reloaded.inventory("gpu-01") is not None
    assert reloaded.inventory("gpu-01").cpu_logical_count == 16


def test_metrics_envelope_rejects_host_id_path_traversal() -> None:
    with pytest.raises(ValidationError):
        _envelope("../config/authorized_keys", 10)


def test_store_host_path_stays_inside_data_dir(tmp_path) -> None:
    store = MetricsStore(tmp_path)

    with pytest.raises(ValueError):
        store._host_path("../config/authorized_keys", ".jsonl")


def test_store_rotates_jsonl_when_exceeding_max_lines(tmp_path) -> None:
    store = MetricsStore(tmp_path, max_jsonl_lines=5)
    for i in range(10):
        store.put(_envelope("gpu-01", float(i)))

    path = tmp_path / "gpu-01.jsonl"
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 5
    # Should keep the most recent entries (indices 5-9)
    values = [
        MetricsEnvelope.model_validate_json(line).cpu.overall_percent
        for line in lines
    ]
    assert values == [5.0, 6.0, 7.0, 8.0, 9.0]


def test_store_no_rotation_when_below_max(tmp_path) -> None:
    store = MetricsStore(tmp_path, max_jsonl_lines=100)
    for i in range(5):
        store.put(_envelope("gpu-01", float(i)))

    path = tmp_path / "gpu-01.jsonl"
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 5


def test_store_rotation_disabled_with_zero(tmp_path) -> None:
    store = MetricsStore(tmp_path, max_jsonl_lines=0)
    for i in range(10):
        store.put(_envelope("gpu-01", float(i)))

    path = tmp_path / "gpu-01.jsonl"
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 10

from datetime import datetime, timedelta, timezone

from lizard.common.models import CpuMetrics, HostInventory, MemoryMetrics, MetricsEnvelope
from lizard.nest.store import MetricsStore


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

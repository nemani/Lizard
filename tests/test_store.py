from lizard.common.models import CpuMetrics, MemoryMetrics, MetricsEnvelope
from lizard.nest.store import MetricsStore


def _envelope(host_id: str, cpu_percent: float) -> MetricsEnvelope:
    return MetricsEnvelope(
        host_id=host_id,
        hostname=host_id,
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

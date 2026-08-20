from datetime import datetime, timezone

from lizard.common.models import CpuMetrics, HostStatus, MemoryMetrics, MetricsEnvelope
from lizard.nest.prometheus import render_prometheus_metrics


def test_render_prometheus_metrics_includes_core_metrics_and_status() -> None:
    envelope = MetricsEnvelope(
        host_id='gpu-"01',
        hostname="gpu-01",
        uptime_seconds=42,
        cpu=CpuMetrics(overall_percent=12.5, per_core_percent=[12.5]),
        memory=MemoryMetrics(total_bytes=100, used_bytes=50, available_bytes=50, percent=50),
        disks=[],
        temperatures=[],
        gpus=[],
    )
    status = HostStatus(
        host_id='gpu-"01',
        hostname="gpu-01",
        last_seen=datetime.now(timezone.utc),
        age_seconds=3,
        state="online",
        uptime_seconds=42,
        alert_count=0,
        critical_alert_count=0,
    )

    rendered = render_prometheus_metrics([envelope], [status])

    assert 'lizard_cpu_percent{host_id="gpu-\\"01",hostname="gpu-01"} 12.5' in rendered
    assert 'lizard_agent_uptime_seconds{host_id="gpu-\\"01",hostname="gpu-01"} 42' in rendered
    assert 'lizard_host_status{host_id="gpu-\\"01",hostname="gpu-01",state="online"} 1' in rendered

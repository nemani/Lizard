from __future__ import annotations

from collections.abc import Iterable

from lizard.common.models import HostStatus, MetricsEnvelope


def render_prometheus_metrics(
    envelopes: Iterable[MetricsEnvelope],
    statuses: Iterable[HostStatus],
) -> str:
    lines: list[str] = [
        "# HELP lizard_cpu_percent Overall CPU usage percent.",
        "# TYPE lizard_cpu_percent gauge",
    ]
    for envelope in envelopes:
        labels = _host_labels(envelope)
        lines.append(f"lizard_cpu_percent{labels} {envelope.cpu.overall_percent}")
        for core_index, core_percent in enumerate(envelope.cpu.per_core_percent):
            lines.append(
                f'lizard_cpu_core_percent{_labels(host_id=envelope.host_id, hostname=envelope.hostname, core=str(core_index))} '
                f"{core_percent}"
            )
        lines.append(f"lizard_memory_percent{labels} {envelope.memory.percent}")
        lines.append(f"lizard_memory_total_bytes{labels} {envelope.memory.total_bytes}")
        lines.append(f"lizard_memory_used_bytes{labels} {envelope.memory.used_bytes}")
        lines.append(f"lizard_memory_available_bytes{labels} {envelope.memory.available_bytes}")
        if envelope.uptime_seconds is not None:
            lines.append(f"lizard_agent_uptime_seconds{labels} {envelope.uptime_seconds}")

        alerts_by_level: dict[str, int] = {}
        for alert in envelope.alerts:
            alerts_by_level[alert.level] = alerts_by_level.get(alert.level, 0) + 1
        for level, count in alerts_by_level.items():
            lines.append(
                f'lizard_alerts_total{_labels(host_id=envelope.host_id, hostname=envelope.hostname, level=level)} {count}'
            )

        for disk in envelope.disks:
            disk_labels = _labels(
                host_id=envelope.host_id,
                hostname=envelope.hostname,
                mountpoint=disk.mountpoint,
                device=disk.device,
            )
            lines.append(
                f"lizard_disk_percent{disk_labels} {disk.percent}"
            )
            lines.append(f"lizard_disk_total_bytes{disk_labels} {disk.total_bytes}")
            lines.append(f"lizard_disk_used_bytes{disk_labels} {disk.used_bytes}")
            lines.append(f"lizard_disk_free_bytes{disk_labels} {disk.free_bytes}")
        for gpu in envelope.gpus:
            gpu_labels = _labels(
                host_id=envelope.host_id,
                hostname=envelope.hostname,
                gpu_index=str(gpu.index),
                gpu_name=gpu.name,
            )
            if gpu.utilization_percent is not None:
                lines.append(f"lizard_gpu_utilization_percent{gpu_labels} {gpu.utilization_percent}")
            if gpu.utilization_percent is not None:
                lines.append(f"lizard_gpu_utilization_percent{gpu_labels} {gpu.utilization_percent}")
            if gpu.memory_total_bytes is not None:
                lines.append(f"lizard_gpu_memory_total_bytes{gpu_labels} {gpu.memory_total_bytes}")
            if gpu.memory_used_bytes is not None:
                lines.append(f"lizard_gpu_memory_used_bytes{gpu_labels} {gpu.memory_used_bytes}")
            if gpu.memory_percent is not None:
                lines.append(f"lizard_gpu_memory_percent{gpu_labels} {gpu.memory_percent}")
            if gpu.temperature_celsius is not None:
                lines.append(f"lizard_gpu_temperature_celsius{gpu_labels} {gpu.temperature_celsius}")
            if gpu.power_watts is not None:
                lines.append(f"lizard_gpu_power_watts{gpu_labels} {gpu.power_watts}")
        for entry_index, temperature in enumerate(envelope.temperatures):
            temp_labels = _labels(
                host_id=envelope.host_id,
                hostname=envelope.hostname,
                sensor=temperature.sensor,
                label=temperature.label,
                entry=str(entry_index),
            )
            lines.append(f"lizard_temperature_celsius{temp_labels} {temperature.current_celsius}")
            if temperature.high_celsius is not None:
                lines.append(f"lizard_temperature_high_celsius{temp_labels} {temperature.high_celsius}")
            if temperature.critical_celsius is not None:
                lines.append(f"lizard_temperature_critical_celsius{temp_labels} {temperature.critical_celsius}")

    lines.extend(
        [
            "# HELP lizard_host_status Host heartbeat status. 1 for current state.",
            "# TYPE lizard_host_status gauge",
        ]
    )
    for status in statuses:
        for state in ("online", "stale", "offline"):
            value = 1 if status.state == state else 0
            lines.append(
                f'lizard_host_status{_labels(host_id=status.host_id, hostname=status.hostname, state=state)} {value}'
            )
        lines.append(
            f"lizard_host_last_seen_age_seconds{_labels(host_id=status.host_id, hostname=status.hostname)} "
            f"{status.age_seconds}"
        )
    return "\n".join(lines) + "\n"


def _host_labels(envelope: MetricsEnvelope) -> str:
    return _labels(host_id=envelope.host_id, hostname=envelope.hostname)


def _labels(**labels: str) -> str:
    encoded = ",".join(f'{key}="{_escape_label(value)}"' for key, value in labels.items())
    return "{" + encoded + "}"


def _escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')

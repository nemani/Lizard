from __future__ import annotations

import logging
import platform
import socket
import subprocess
from datetime import datetime, timezone

import psutil

from lizard.common.models import (
    Alert,
    AlertThreshold,
    CpuMetrics,
    DiskMetrics,
    GpuMetrics,
    MemoryMetrics,
    MetricsEnvelope,
    TemperatureMetrics,
)
from lizard.egg.config import EggSettings

LOGGER = logging.getLogger(__name__)


def collect_metrics(settings: EggSettings) -> MetricsEnvelope:
    cpu = _collect_cpu()
    memory = _collect_memory()
    disks = _collect_disks()
    temperatures = _collect_temperatures()
    gpus = _collect_gpus()
    alerts = _evaluate_alerts(settings, cpu, memory, disks, temperatures, gpus)

    return MetricsEnvelope(
        host_id=settings.host_id,
        hostname=settings.hostname,
        timestamp=datetime.now(timezone.utc),
        cpu=cpu,
        memory=memory,
        disks=disks,
        temperatures=temperatures,
        gpus=gpus,
        alerts=alerts,
        metadata={
            "platform": platform.platform(),
            "fqdn": socket.getfqdn(),
            "agent": "lizard-egg",
        },
    )


def _collect_cpu() -> CpuMetrics:
    return CpuMetrics(
        overall_percent=psutil.cpu_percent(interval=1),
        per_core_percent=psutil.cpu_percent(interval=None, percpu=True),
    )


def _collect_memory() -> MemoryMetrics:
    mem = psutil.virtual_memory()
    return MemoryMetrics(
        total_bytes=mem.total,
        used_bytes=mem.used,
        available_bytes=mem.available,
        percent=mem.percent,
    )


def _collect_disks() -> list[DiskMetrics]:
    disks: list[DiskMetrics] = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except PermissionError:
            LOGGER.debug("skipping disk mount without permission: %s", part.mountpoint)
            continue
        disks.append(
            DiskMetrics(
                mountpoint=part.mountpoint,
                device=part.device,
                fstype=part.fstype,
                total_bytes=usage.total,
                used_bytes=usage.used,
                free_bytes=usage.free,
                percent=usage.percent,
            )
        )
    return disks


def _collect_temperatures() -> list[TemperatureMetrics]:
    temps: list[TemperatureMetrics] = []
    if not hasattr(psutil, "sensors_temperatures"):
        return temps

    for sensor, entries in psutil.sensors_temperatures(fahrenheit=False).items():
        for entry in entries:
            temps.append(
                TemperatureMetrics(
                    sensor=sensor,
                    label=entry.label or sensor,
                    current_celsius=entry.current,
                    high_celsius=entry.high,
                    critical_celsius=entry.critical,
                )
            )
    return temps


def _collect_gpus() -> list[GpuMetrics]:
    gpus = _collect_gpus_with_nvml()
    if gpus:
        return gpus
    return _collect_gpus_with_nvidia_smi()


def _collect_gpus_with_nvml() -> list[GpuMetrics]:
    try:
        import pynvml  # type: ignore[import-not-found]
    except ImportError:
        return []

    try:
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        metrics: list[GpuMetrics] = []
        for index in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            name = pynvml.nvmlDeviceGetName(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            temperature = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            try:
                power_watts = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000
            except pynvml.NVMLError:
                power_watts = None
            metrics.append(
                GpuMetrics(
                    index=index,
                    name=name.decode() if isinstance(name, bytes) else name,
                    utilization_percent=float(util.gpu),
                    memory_total_bytes=int(mem.total),
                    memory_used_bytes=int(mem.used),
                    memory_percent=(mem.used / mem.total * 100) if mem.total else None,
                    temperature_celsius=float(temperature),
                    power_watts=power_watts,
                )
            )
        return metrics
    except (pynvml.NVMLError, AttributeError) as exc:
        LOGGER.debug("NVML GPU collection failed: %s", exc)
        return []
    finally:
        try:
            pynvml.nvmlShutdown()
        except pynvml.NVMLError as exc:
            LOGGER.debug("NVML shutdown failed: %s", exc)


def _collect_gpus_with_nvidia_smi() -> list[GpuMetrics]:
    query = "index,name,utilization.gpu,memory.total,memory.used,temperature.gpu,power.draw"
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={query}",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    metrics: list[GpuMetrics] = []
    for line in completed.stdout.splitlines():
        fields = [item.strip() for item in line.split(",")]
        if len(fields) != 7:
            continue
        index, name, util, mem_total_mib, mem_used_mib, temp, power = fields
        total_bytes = _mib_to_bytes(mem_total_mib)
        used_bytes = _mib_to_bytes(mem_used_mib)
        metrics.append(
            GpuMetrics(
                index=int(index),
                name=name,
                utilization_percent=_float_or_none(util),
                memory_total_bytes=total_bytes,
                memory_used_bytes=used_bytes,
                memory_percent=(used_bytes / total_bytes * 100) if total_bytes else None,
                temperature_celsius=_float_or_none(temp),
                power_watts=_float_or_none(power),
            )
        )
    return metrics


def _mib_to_bytes(value: str) -> int | None:
    numeric = _float_or_none(value)
    if numeric is None:
        return None
    return int(numeric * 1024 * 1024)


def _float_or_none(value: str) -> float | None:
    if value.lower() in {"n/a", "na", ""}:
        return None
    return float(value)


def _evaluate_alerts(
    settings: EggSettings,
    cpu: CpuMetrics,
    memory: MemoryMetrics,
    disks: list[DiskMetrics],
    temperatures: list[TemperatureMetrics],
    gpus: list[GpuMetrics],
) -> list[Alert]:
    alerts: list[Alert] = []
    _append_threshold_alerts(
        alerts,
        "cpu.overall_percent",
        cpu.overall_percent,
        settings.cpu_percent_thresholds,
    )
    _append_threshold_alerts(
        alerts,
        "memory.percent",
        memory.percent,
        settings.memory_percent_thresholds,
    )

    for disk in disks:
        _append_threshold_alerts(
            alerts,
            f"disk.percent:{disk.mountpoint}",
            disk.percent,
            settings.disk_percent_thresholds,
        )
    for temp in temperatures:
        _append_threshold_alerts(
            alerts,
            f"temperature.current_celsius:{temp.sensor}/{temp.label}",
            temp.current_celsius,
            settings.temperature_celsius_thresholds,
        )
    for gpu in gpus:
        if gpu.utilization_percent is not None:
            _append_threshold_alerts(
                alerts,
                f"gpu.utilization_percent:{gpu.index}",
                gpu.utilization_percent,
                settings.gpu_percent_thresholds,
            )
    return alerts


def _append_threshold_alerts(
    alerts: list[Alert],
    metric: str,
    value: float,
    thresholds: list[AlertThreshold],
) -> None:
    crossed = [threshold for threshold in thresholds if value > threshold.value]
    if not crossed:
        return
    _append_alert(alerts, metric, value, max(crossed, key=lambda item: item.value))


def _append_alert(alerts: list[Alert], metric: str, value: float, threshold: AlertThreshold) -> None:
    message = f"{metric} is {value:.1f}, above {threshold.level} threshold {threshold.value:.1f}"
    LOGGER.warning(message)
    alerts.append(
        Alert(
            level=threshold.level,
            metric=metric,
            message=message,
            value=value,
            threshold=threshold.value,
        )
    )

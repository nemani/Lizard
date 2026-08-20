from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from lizard.common.models import CpuMetrics, DiskMetrics, GpuMetrics, MemoryMetrics
from lizard.egg import collector
from lizard.egg.collector import _evaluate_alerts
from lizard.egg.config import AlertThreshold, EggSettings


def test_cpu_emits_highest_crossed_threshold_only() -> None:
    settings = EggSettings(
        mqtt_host="broker",
        cpu_percent_thresholds=[
            AlertThreshold(level="warning", value=50),
            AlertThreshold(level="critical", value=90),
        ],
    )
    alerts = _evaluate_alerts(
        settings,
        CpuMetrics(overall_percent=95.0, per_core_percent=[95.0]),
        MemoryMetrics(total_bytes=10, used_bytes=5, available_bytes=5, percent=50),
        [],
        [],
        [],
    )

    assert [(alert.level, alert.metric, alert.threshold) for alert in alerts] == [
        ("critical", "cpu.overall_percent", 90),
    ]


def test_alert_selection_prefers_severity_over_threshold_value() -> None:
    settings = EggSettings(
        mqtt_host="broker",
        cpu_percent_thresholds=[
            AlertThreshold(level="warning", value=95),
            AlertThreshold(level="critical", value=90),
        ],
    )
    alerts = _evaluate_alerts(
        settings,
        CpuMetrics(overall_percent=96.0, per_core_percent=[96.0]),
        MemoryMetrics(total_bytes=10, used_bytes=5, available_bytes=5, percent=50),
        [],
        [],
        [],
    )

    assert [(alert.level, alert.threshold) for alert in alerts] == [("critical", 90)]


def test_alerts_include_disk_and_gpu_thresholds() -> None:
    settings = EggSettings(
        mqtt_host="broker",
        disk_percent_thresholds=[AlertThreshold(level="warning", value=80)],
        gpu_percent_thresholds=[AlertThreshold(level="warning", value=70)],
    )
    alerts = _evaluate_alerts(
        settings,
        CpuMetrics(overall_percent=1.0, per_core_percent=[1.0]),
        MemoryMetrics(total_bytes=10, used_bytes=5, available_bytes=5, percent=50),
        [
            DiskMetrics(
                mountpoint="/data",
                device="/dev/sdb1",
                fstype="ext4",
                total_bytes=100,
                used_bytes=90,
                free_bytes=10,
                percent=90,
            )
        ],
        [],
        [GpuMetrics(index=0, name="A100", utilization_percent=75)],
    )

    assert {alert.metric for alert in alerts} == {
        "disk.percent:/dev/sdb1",
        "gpu.utilization_percent:0",
    }


def test_disk_collection_dedupes_by_device(monkeypatch) -> None:
    monkeypatch.setattr(
        collector.psutil,
        "disk_partitions",
        lambda all=False: [
            SimpleNamespace(device="/dev/sda1", mountpoint="/", fstype="ext4"),
            SimpleNamespace(device="/dev/sda1", mountpoint="/host", fstype="ext4"),
            SimpleNamespace(device="/dev/sdb1", mountpoint="/data", fstype="ext4"),
        ],
    )
    monkeypatch.setattr(
        collector.psutil,
        "disk_usage",
        lambda mountpoint: SimpleNamespace(
            total=100,
            used=40 if mountpoint == "/" else 50,
            free=60,
            percent=40.0,
        ),
    )

    disks = collector._collect_disks()

    assert [(disk.device, disk.mountpoint) for disk in disks] == [
        ("/dev/sda1", "/"),
        ("/dev/sdb1", "/data"),
    ]


def test_cpu_collection_reads_overall_and_per_core_after_one_sleep(monkeypatch) -> None:
    calls = []

    def fake_cpu_percent(interval=None, percpu=False):
        calls.append((interval, percpu))
        return [10.0, 20.0] if percpu else 15.0

    monkeypatch.setattr(collector.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))
    monkeypatch.setattr(collector.psutil, "cpu_percent", fake_cpu_percent)

    cpu = collector._collect_cpu()

    assert cpu.overall_percent == 15.0
    assert cpu.per_core_percent == [10.0, 20.0]
    assert calls == [
        ("sleep", 1),
        (None, False),
        (None, True),
    ]


def test_nvidia_smi_fallback_treats_bracketed_na_as_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        collector.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="0, NVIDIA A4000, 50, 16376, 2048, 62, [N/A]\n",
        ),
    )

    gpus = collector._collect_gpus_with_nvidia_smi()

    assert len(gpus) == 1
    assert gpus[0].power_watts is None
    assert gpus[0].utilization_percent == 50


def test_remote_config_updates_runtime_thresholds() -> None:
    settings = EggSettings(mqtt_host="broker")
    updated = settings.with_remote_update(
        {
            "interval_seconds": 5,
            "cpu_percent_thresholds": [
                {"level": "warning", "value": 50},
                {"level": "critical", "value": 90},
            ],
            "mqtt_host": "ignored-at-runtime",
        }
    )

    assert updated.interval_seconds == 5
    assert updated.mqtt_host == "broker"
    assert [(item.level, item.value) for item in updated.cpu_percent_thresholds] == [
        ("warning", 50),
        ("critical", 90),
    ]


def test_config_rejects_invalid_interval_and_thresholds() -> None:
    with pytest.raises(ValidationError):
        EggSettings(interval_seconds=0)

    with pytest.raises(ValidationError):
        EggSettings(cpu_percent_thresholds=[{"level": "warning", "value": -1}])

import pytest
from pydantic import ValidationError

from lizard.common.models import CpuMetrics, DiskMetrics, GpuMetrics, MemoryMetrics
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
        "disk.percent:/data",
        "gpu.utilization_percent:0",
    }


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

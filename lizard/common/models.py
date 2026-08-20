from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class AlertThreshold(BaseModel):
    level: str = "warning"
    value: float = Field(ge=0)


class AlertConfig(BaseModel):
    interval_seconds: int | None = Field(default=None, ge=1)
    cpu_percent_thresholds: list[AlertThreshold] | None = None
    memory_percent_thresholds: list[AlertThreshold] | None = None
    disk_percent_thresholds: list[AlertThreshold] | None = None
    gpu_percent_thresholds: list[AlertThreshold] | None = None
    temperature_celsius_thresholds: list[AlertThreshold] | None = None


class ConfigEnvelope(BaseModel):
    scope: str
    version: int = Field(ge=1)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    config: AlertConfig


class ConfigAck(BaseModel):
    host_id: str
    hostname: str
    scope: str
    version: int
    active_scope: str
    active_version: int
    status: str
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DiskInventory(BaseModel):
    device: str
    mountpoint: str
    fstype: str


class GpuInventory(BaseModel):
    index: int
    name: str
    memory_total_bytes: int | None = None


class HostInventory(BaseModel):
    host_id: str
    hostname: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    os: str
    os_version: str
    kernel: str
    architecture: str
    python_version: str
    cpu_logical_count: int
    cpu_physical_count: int | None = None
    memory_total_bytes: int
    disks: list[DiskInventory]
    gpus: list[GpuInventory]
    metadata: dict[str, Any] = Field(default_factory=dict)


class CpuMetrics(BaseModel):
    overall_percent: float
    per_core_percent: list[float]


class MemoryMetrics(BaseModel):
    total_bytes: int
    used_bytes: int
    available_bytes: int
    percent: float


class DiskMetrics(BaseModel):
    mountpoint: str
    device: str
    fstype: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


class TemperatureMetrics(BaseModel):
    sensor: str
    label: str
    current_celsius: float
    high_celsius: float | None = None
    critical_celsius: float | None = None


class GpuMetrics(BaseModel):
    index: int
    name: str
    utilization_percent: float | None = None
    memory_total_bytes: int | None = None
    memory_used_bytes: int | None = None
    memory_percent: float | None = None
    temperature_celsius: float | None = None
    power_watts: float | None = None


class Alert(BaseModel):
    level: str = "warning"
    metric: str
    message: str
    value: float
    threshold: float


class MetricsEnvelope(BaseModel):
    host_id: str
    hostname: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    uptime_seconds: float | None = None
    cpu: CpuMetrics
    memory: MemoryMetrics
    disks: list[DiskMetrics]
    temperatures: list[TemperatureMetrics]
    gpus: list[GpuMetrics]
    alerts: list[Alert] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HostStatus(BaseModel):
    host_id: str
    hostname: str
    last_seen: datetime
    age_seconds: float = Field(ge=0)
    state: str
    uptime_seconds: float | None = None
    alert_count: int
    critical_alert_count: int

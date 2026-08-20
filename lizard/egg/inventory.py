from __future__ import annotations

import platform
import socket
import sys

import psutil

from lizard.common.models import DiskInventory, GpuInventory, HostInventory
from lizard.egg.collector import _collect_gpus
from lizard.egg.config import EggSettings


def collect_inventory(settings: EggSettings) -> HostInventory:
    return HostInventory(
        host_id=settings.host_id,
        hostname=settings.hostname,
        os=platform.system(),
        os_version=platform.version(),
        kernel=platform.release(),
        architecture=platform.machine(),
        python_version=sys.version.split()[0],
        cpu_logical_count=psutil.cpu_count(logical=True) or 0,
        cpu_physical_count=psutil.cpu_count(logical=False),
        memory_total_bytes=psutil.virtual_memory().total,
        disks=[
            DiskInventory(device=part.device, mountpoint=part.mountpoint, fstype=part.fstype)
            for part in psutil.disk_partitions(all=False)
        ],
        gpus=[
            GpuInventory(index=gpu.index, name=gpu.name, memory_total_bytes=gpu.memory_total_bytes)
            for gpu in _collect_gpus()
        ],
        metadata={
            "fqdn": socket.getfqdn(),
            "agent": "lizard-egg",
        },
    )

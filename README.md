# 🦎 Lizard

🦎 Lizard monitors Ubuntu 22.04 Linux servers with GPUs. Each monitored server runs a **🥚 egg** agent that samples CPU, per-core CPU, RAM, per-device disk usage, temperatures, and NVIDIA GPU usage, then publishes metrics over MQTT. A central **nest** service subscribes to those messages, stores JSONL history, exports Prometheus metrics, and exposes the latest status over HTTP.

## Components

- `lizard-egg`: 🥚 local monitoring agent for each GPU server.
- `lizard-nest`: 🦎 central receiver, UI, and HTTP API.
- `mqtt`: Eclipse Mosquitto broker used for transport.
- `scripts/lay-egg.sh`: installer that lays an egg by installing `lizard-egg` as a systemd service.

## Run the Nest

```bash
docker compose up --build mqtt nest prometheus grafana
```

The Nest UI and API listen on `http://localhost:8000`. Prometheus listens on `http://localhost:9090`, and Grafana listens on `http://localhost:3000` with `admin` / `lizard` for local demo use.

```bash
open http://localhost:8000
curl http://localhost:8000/health
curl http://localhost:8000/servers
curl http://localhost:8000/servers/status
curl http://localhost:8000/servers/inventory
curl http://localhost:8000/servers/<host_id>
curl http://localhost:8000/servers/<host_id>/series?limit=240
curl http://localhost:8000/servers/<host_id>/inventory
curl http://localhost:8000/metrics
```

Grafana includes:

- `Lizard Overview` for fleet-level charts.
- `Lizard Host Detail` for per-host CPU core, disk, GPU, and heartbeat charts.

## Run an Egg Locally

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[gpu]"
LIZARD_MQTT_HOST=localhost lizard-egg
```

For Docker-based agent testing on a GPU host with NVIDIA Container Toolkit:

```bash
docker compose --profile egg up --build egg
```

## Lay an Egg on a Server

Copy this repository or a release archive to the Ubuntu 22.04 GPU server, then run:

```bash
sudo MQTT_HOST=<nest-or-broker-host> INTERVAL_SECONDS=15 scripts/lay-egg.sh
```

This lays a 🥚 and creates:

- `/opt/lizard/venv` with the Python package installed.
- `/etc/lizard/egg.env` for runtime configuration.
- `/etc/systemd/system/lizard-egg.service`.

Useful operations:

```bash
sudo systemctl status lizard-egg
sudo journalctl -u lizard-egg -f
sudo systemctl restart lizard-egg
```

## Configuration

All settings use the `LIZARD_` environment prefix.

| Setting | Default | Description |
| --- | --- | --- |
| `LIZARD_INTERVAL_SECONDS` | `15` | Sample/publish interval. |
| `LIZARD_MQTT_HOST` | `localhost` | MQTT broker host. |
| `LIZARD_MQTT_PORT` | `1883` | MQTT broker port. |
| `LIZARD_MQTT_TOPIC_PREFIX` | `lizard` | MQTT topic namespace. |
| `LIZARD_REMOTE_CONFIG_ENABLED` | `true` | Subscribe to MQTT config topics. |
| `LIZARD_CPU_PERCENT_THRESHOLDS` | warning `10`, critical `90` | JSON list of CPU thresholds. |
| `LIZARD_MEMORY_PERCENT_THRESHOLDS` | warning `90` | JSON list of RAM thresholds. |
| `LIZARD_DISK_PERCENT_THRESHOLDS` | warning `90` | JSON list of disk thresholds. |
| `LIZARD_GPU_PERCENT_THRESHOLDS` | warning `95` | JSON list of GPU utilization thresholds. |
| `LIZARD_TEMPERATURE_CELSIUS_THRESHOLDS` | warning `85` | JSON list of temperature thresholds. |

Alerts are logged locally by the egg and included in the MQTT payload.

Thresholds are ordered lists, so one metric can emit multiple alerts. For example:

```bash
LIZARD_CPU_PERCENT_THRESHOLDS='[{"level":"warning","value":50},{"level":"critical","value":90}]'
```

If CPU is `95%`, the egg emits both the `warning` and `critical` CPU alerts.

## Pushing Config Changes

🥚 Eggs subscribe to two retained MQTT config topics:

- `lizard/config/global`
- `lizard/servers/<host_id>/config`

Use retained messages so config survives egg restarts. Nest owns config versions, timestamps, and publishing. Host-specific config takes precedence over global config as a full replacement: if a host config exists, the egg applies that host config instead of the global config.

Global MQTT envelope example:

```bash
mosquitto_pub -h <broker-host> -r -t lizard/config/global -m '{
  "scope": "global",
  "version": 1,
  "updated_at": "2026-08-20T18:00:00Z",
  "config": {
    "interval_seconds": 10,
    "cpu_percent_thresholds": [
      {"level": "warning", "value": 50},
      {"level": "critical", "value": 90}
    ]
  }
}'
```

Host-specific MQTT envelope example:

```bash
mosquitto_pub -h <broker-host> -r -t lizard/servers/gpu-01/config -m '{
  "scope": "host:gpu-01",
  "version": 1,
  "updated_at": "2026-08-20T18:00:00Z",
  "config": {
    "interval_seconds": 5,
    "gpu_percent_thresholds": [
      {"level": "warning", "value": 80},
      {"level": "critical", "value": 95}
    ]
  }
}'
```

Remote updates are applied in memory. On restart, the 🥚 reads local `/etc/lizard/egg.env`, then receives the broker's retained config again. Keep broker connection settings local because changing MQTT host/credentials over the same MQTT connection is intentionally not supported. Eggs publish ack/status to `lizard/servers/<host_id>/config/status`.

Nest also exposes this as an API and publishes retained MQTT messages for you.

Global config:

```bash
curl -X POST http://localhost:8000/config/global \
  -H 'content-type: application/json' \
  -d '{
    "interval_seconds": 10,
    "cpu_percent_thresholds": [
      {"level": "warning", "value": 50},
      {"level": "critical", "value": 90}
    ]
  }'
```

Host config:

```bash
curl -X POST http://localhost:8000/servers/gpu-01/config \
  -H 'content-type: application/json' \
  -d '{
    "gpu_percent_thresholds": [
      {"level": "warning", "value": 80},
      {"level": "critical", "value": 95}
    ]
  }'
```

The dashboard at `/` uses the same endpoints. It separates monitoring and config into tabs, shows latest 🥚 status, heartbeat state, uptime, last seen age, CPU/RAM/GPU/disk time-series charts, per-core CPU, per-device disk usage, latest alerts, and a form for publishing global or per-host local alert config.

Disk usage is reported once per backing device. The 🥚 enumerates mounted filesystems, deduplicates by `device`, and samples usage from the first accessible mountpoint for that device. This is intended for host-level Linux installs; Docker bind/overlay mounts may look different.

## Host Inventory

🥚 Eggs publish permanent-ish host inventory on startup, after config changes, and when Nest requests a refresh. Inventory includes OS/kernel, architecture, CPU counts, memory size, disks, and GPUs.

```bash
curl http://localhost:8000/servers/<host_id>/inventory
curl -X POST http://localhost:8000/servers/<host_id>/inventory/refresh
```

## Deployment Strategy

1. Run `docker compose up -d --build mqtt nest prometheus grafana` on the Nest host.
2. Restrict broker access at the network layer. MQTT auth/TLS is omitted from the prototype, but production should use username/password or mTLS plus topic ACLs before exposing it outside a trusted LAN/VPN.
3. Build a release archive from the repo, or clone it on each GPU server.
4. Install on each Ubuntu 22.04 server with `scripts/lay-egg.sh`, passing the Nest/broker host and desired interval.
5. Validate each egg with `systemctl status lizard-egg` and confirm it appears in `GET /servers`.
6. Roll out threshold and interval changes with retained MQTT config messages. Roll out broker/credential changes by editing `/etc/lizard/egg.env` and restarting `lizard-egg`.

For fleet automation, wrap `scripts/lay-egg.sh` with Ansible, cloud-init, or your provisioning system. The installer is intentionally environment-variable driven so a single artifact can be reused across servers.

## Scaling

This design scales in layers:

- MQTT handles fan-in well because eggs publish small periodic JSON messages and Nest subscribes by topic wildcard.
- Increase `LIZARD_INTERVAL_SECONDS` for larger fleets, or shard by topic prefix such as `lizard/prod-a` and `lizard/prod-b`.
- Run Mosquitto on the same private network/VPN as the GPU hosts; use auth/TLS before crossing untrusted networks.
- Prometheus scrapes Nest's `/metrics` endpoint for long-term querying and Grafana dashboards. For very large fleets or long retention, pair Prometheus with Mimir, Thanos, VictoriaMetrics, or another remote-write backend.
- The current Nest JSONL store is simple and good for the product UI prototype. For larger fleets, treat it as a cache or replace it with a database-backed API.
- Run more than one Nest subscriber if you need separate consumers, such as API storage, alert routing, and dashboards. MQTT lets those consumers subscribe independently without changing the eggs.

## Test Hosts

On a non-GPU development machine, run simulated CPU-only eggs:

```bash
docker compose --profile test-hosts up -d --build --scale egg-test=3 egg-test
```

These publish to the same MQTT/Nest path and are useful for end-to-end UI, config, heartbeat, and Prometheus testing.

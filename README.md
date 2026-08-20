# Lizard

Lizard monitors Ubuntu 22.04 Linux servers with GPUs. Each monitored server runs an **egg** agent that samples CPU, RAM, mounted disks, temperatures, and NVIDIA GPU usage, then publishes metrics over MQTT. A central **nest** service subscribes to those messages, stores JSONL history, and exposes the latest status over HTTP.

## Components

- `lizard-egg`: local monitoring agent for each GPU server.
- `lizard-nest`: central receiver and HTTP API.
- `mqtt`: Eclipse Mosquitto broker used for transport.
- `scripts/lay-egg.sh`: installer that lays an egg by installing `lizard-egg` as a systemd service.

## Run the Nest

```bash
docker compose up --build mqtt nest
```

The Nest UI and API listen on `http://localhost:8000`.

```bash
open http://localhost:8000
curl http://localhost:8000/health
curl http://localhost:8000/servers
curl http://localhost:8000/servers/<host_id>
curl http://localhost:8000/servers/<host_id>/series?limit=240
```

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

This creates:

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

Eggs subscribe to two retained MQTT config topics:

- `lizard/config/global`
- `lizard/servers/<host_id>/config`

Use retained messages so config survives egg restarts. Global config applies to every egg; host-specific config applies only to one server.

Global example:

```bash
mosquitto_pub -h <broker-host> -r -t lizard/config/global -m '{
  "interval_seconds": 10,
  "cpu_percent_thresholds": [
    {"level": "warning", "value": 50},
    {"level": "critical", "value": 90}
  ],
  "memory_percent_thresholds": [
    {"level": "warning", "value": 90},
    {"level": "critical", "value": 98}
  ]
}'
```

Host-specific override:

```bash
mosquitto_pub -h <broker-host> -r -t lizard/servers/gpu-01/config -m '{
  "interval_seconds": 5,
  "gpu_percent_thresholds": [
    {"level": "warning", "value": 80},
    {"level": "critical", "value": 95}
  ]
}'
```

Remote updates are applied in memory. On restart, the egg reads local `/etc/lizard/egg.env`, then receives the broker's retained config again. Keep broker connection settings local because changing MQTT host/credentials over the same MQTT connection is intentionally not supported.

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

The dashboard at `/` uses the same endpoints. It shows latest egg status, CPU/RAM/GPU/disk time-series charts, latest alerts, and a form for publishing global or per-host local alert config.

## Deployment Strategy

1. Run `docker compose up -d --build mqtt nest` on the Nest host.
2. Restrict broker access at the network layer or replace the example anonymous Mosquitto config with username/password or TLS before exposing it outside a trusted LAN/VPN.
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
- The current Nest JSONL store is simple and good for early operation. For larger fleets or long retention, replace `MetricsStore` with TimescaleDB, ClickHouse, VictoriaMetrics, or Prometheus remote-write style storage.
- Run more than one Nest subscriber if you need separate consumers, such as API storage, alert routing, and dashboards. MQTT lets those consumers subscribe independently without changing the eggs.

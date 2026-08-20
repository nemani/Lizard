# 🦎 Lizard 5-Minute Loom Demo Script

This is a spoken walkthrough script, not an automation script. The demo assumes nothing is running when recording starts.

## 0:00-0:30 - Set the context

Screen: repo root in terminal, README open beside it.

Say:

"This is Lizard, a prototype hardware monitoring system for Ubuntu 22.04 edge devices with NVIDIA GPUs. Each monitored server runs a lightweight egg agent. The egg samples CPU, per-core CPU, RAM, per-device disk usage, temperature, and GPU usage, then pushes metrics over MQTT. The central Nest receives those messages, exposes a UI and API, and exports Prometheus metrics for Grafana."

"I chose MQTT because these edge devices are often deployed on client networks where inbound scraping is awkward. A push model lets devices report out to a broker, while Nest and Prometheus stay central."

## 0:30-1:05 - Bring up the central services

Screen: terminal.

Run:

```bash
docker compose up -d --build mqtt nest prometheus grafana
```

If local port `1883` is busy, use:

```bash
LIZARD_MQTT_PUBLISHED_PORT=1884 docker compose up -d --build mqtt nest prometheus grafana
```

Say:

"First I am starting the central side: Mosquitto for MQTT transport, Nest for ingestion and the product UI, Prometheus for metrics scraping, and Grafana for longer-term dashboards. In production I would run these with proper auth, TLS, and durable storage; for this prototype they are local Docker services."

Run:

```bash
docker compose ps
```

Say:

"At this point the Nest is up, but no eggs have reported yet."

## 1:05-1:45 - Show empty Nest, then start eggs

Screen: browser at `http://localhost:8000`.

Say:

"This is the Nest UI. It separates monitoring from configuration. Right now, with no eggs reporting, there is no host selected."

Screen: terminal.

Run:

```bash
docker compose --profile test-hosts up -d --build --scale egg-test=3 egg-test
```

If using the MQTT port override for the whole stack, run:

```bash
LIZARD_MQTT_PUBLISHED_PORT=1884 docker compose --profile test-hosts up -d --build --scale egg-test=3 egg-test
```

Say:

"For the demo, I am starting three test eggs in Docker. On real Ubuntu GPU hosts, the egg is installed with the lay-egg installer as a systemd service. That gives boot startup, crash restart, journald logs, and direct access to host-level Linux and GPU metrics."

## 1:45-2:35 - Show live metrics in Nest

Screen: refresh `http://localhost:8000`.

Say:

"The eggs are now reporting. The list is sorted by state so online hosts appear first, and I can hide offline hosts if I want a clean operations view."

Click an egg.

Say:

"For a selected host, the top cards show the latest CPU, RAM, GPU, disk, uptime, and last-seen age. Below that, the UI shows time-series charts from Nest's stored samples. Overall CPU is separate from the per-core CPU chart so we can see whether load is spread across the machine or concentrated on a few cores."

Scroll to details.

Say:

"Disk is reported per backing device rather than per mount. The egg deduplicates mounted filesystems by device and samples usage from an accessible mountpoint. Inventory is separate from metrics because it changes slowly: OS version, kernel, architecture, CPU count, memory, disks, and GPUs are sent on startup, after config changes, or when Nest requests a refresh."

## 2:35-3:20 - Show API and Prometheus

Screen: terminal.

Run:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/servers/status
curl http://localhost:8000/metrics | head
```

Say:

"Nest also exposes a simple HTTP API. The `/servers/status` endpoint gives heartbeat state, uptime, and last seen. The `/metrics` endpoint is Prometheus format, so Prometheus scrapes Nest instead of scraping every device directly."

Screen: browser at `http://localhost:9090`, query `lizard_host_status` or `lizard_cpu_percent`.

Say:

"Here Prometheus can query the metrics exported by Nest. For a larger deployment I would remote-write this data to a scalable backend such as Mimir, Thanos, or VictoriaMetrics."

## 3:20-4:10 - Show Grafana dashboards

Screen: browser at `http://localhost:3000`, login `admin` / `lizard`.

Say:

"Grafana is included for the advanced charting path. The product UI is useful for fleet status and config workflows, while Grafana is better for deeper metric analysis."

Open dashboards:

- `Lizard Overview`
- `Lizard Host Detail`

Say:

"The overview dashboard is fleet-focused. The host detail dashboard breaks out per-host CPU cores, disk devices, GPU metrics when available, and heartbeat state."

## 4:10-4:45 - Push config from Nest

Screen: Nest UI, Config tab.

Say:

"Configuration is pushed back to eggs over retained MQTT messages. Nest owns the version number and timestamp. Eggs subscribe to global config and host-specific config; host config takes precedence as a full replacement."

Set:

- Scope: `Global`
- CPU thresholds: `warning:1,critical:90`
- Interval seconds: `5`

Click `Build JSON`, then `Publish retained config`.

Say:

"This config supports multiple severity thresholds, but the egg reports only the highest crossed threshold per metric to avoid alert noise. After applying config, eggs publish an ack/status message showing the active version."

Screen: Monitor tab.

Say:

"Because the demo threshold is low, CPU warnings may appear in the latest alerts section once the next samples arrive."

## 4:45-5:00 - Close with production notes

Screen: `DESIGN.md` or README limitations.

Say:

"The prototype intentionally keeps a few things simple. Production should add MQTT auth or mTLS with topic ACLs, authentication and audit logs for the Nest config API, explicit reconnect/backoff behavior, and a durable control-plane database. The JSONL history is transparent for the demo, while Prometheus and Grafana are the long-term metric path."

"The main design choices are: lightweight headless eggs on devices, MQTT push for edge network friendliness, Nest as the central control and API point, and Prometheus/Grafana for scalable observability."

## Backup Commands

Use these only if you need to recover during the recording.

```bash
docker compose ps
docker compose logs --tail=50 nest
docker compose logs --tail=50 egg-test
curl http://localhost:8000/health
curl http://localhost:8000/servers/status
```

# 🦎 Lizard Design

🦎 Lizard is a push-based edge monitoring prototype for Ubuntu 22.04 NVIDIA GPU devices. Each device runs a lightweight `lizard-egg` 🥚 agent that samples CPU, per-core CPU, RAM, per-device disk usage, temperature, and GPU metrics, evaluates local alert thresholds, and publishes metrics to MQTT. A central `lizard-nest` service consumes MQTT, exposes a fleet/config UI and API, exports Prometheus metrics, and publishes retained versioned config back to eggs.

## Architecture

```text
🥚 Egg agent -> MQTT broker -> 🦎 Nest API/UI -> Prometheus -> Grafana
             ^              |
             |              v
             +-- retained config + egg ack/status
```

MQTT is used because edge devices are often behind client firewalls/NAT and push telemetry is simpler than scraping each device. Nest owns config versions and publishes retained config envelopes. 🥚 Eggs subscribe to global and host-specific config topics, apply host config over global config as full-replacement precedence, and publish config ack/status with the active version.

Prometheus scrapes Nest's `/metrics` endpoint for long-term metric querying and Grafana dashboards. Grafana includes fleet-level and per-host dashboards. Nest still stores JSONL samples and host inventory for the prototype UI and API; in production this JSONL path would be removed or treated as short-lived local cache.

🥚 Eggs publish host inventory on startup, after config changes, and when Nest requests a refresh. Inventory captures OS/kernel, architecture, CPU counts, memory size, disks, and GPUs without resending it on every metrics sample.

Disk metrics are device-oriented: the egg deduplicates mounted filesystems by backing `device` and samples usage from the first accessible mountpoint for that device. This keeps host reporting stable for normal Linux installs, while acknowledging that container overlay/bind mounts can present a different view.

## Tradeoffs

- MQTT push works well for edge networks and config fan-out, but broker security and operations become important.
- Local alerting gives autonomous device behavior, but central alert lifecycle belongs in Prometheus Alertmanager or an equivalent service.
- JSONL storage is transparent and easy to demo, but not suitable for long retention or large fleets.
- The built-in UI is useful for product workflow and config control; Grafana is better for advanced charts.
- Mosquitto auth/TLS is intentionally omitted from the prototype. Production should enable per-device credentials, TLS, topic ACLs, and credential rotation so devices can only publish/read their own topics.

## Scaling

For thousands of devices, shard MQTT topics by environment or fleet, run brokers close to device networks, and scrape Nest with Prometheus or remote-write to a scalable backend such as Mimir, Thanos, or VictoriaMetrics. Device samples are small and label-based metrics keep Prometheus queries natural. Nest should eventually move config/audit state to a database and publish config changes through a durable control-plane workflow.

## Security

Secrets should live outside source control and be injected via systemd environment files or secret managers. The Nest config API should require authentication, authorization, CSRF protection for browser use, and audit logging. MQTT auth was excluded for this prototype, but adding username/password or mTLS plus ACLs would protect metric ingestion, retained config topics, and per-device status acks.

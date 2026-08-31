# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Quick commands

- Install: `pip install -e ".[dev]"`  (add `gpu` extra for NVML on GPU hosts)
- Tests: `python -m pytest tests/ -v`
- Lint: `ruff check .`
- Run Nest: `LIZARD_MQTT_HOST=localhost lizard-nest`
- Run Egg (once): `LIZARD_MQTT_HOST=localhost lizard-egg --once`
- Full stack with Docker: `docker compose up --build mqtt nest prometheus grafana`
- Test hosts (Docker, CPU-only): `docker compose --profile test-hosts up -d --build --scale egg-test=3 egg-test`

## Architecture

- Egg agents push metrics over MQTT (paho-mqtt) → Nest subscribes via wildcard topics
- Nest stores JSONL in `data_dir`, exposes FastAPI + Prometheus `/metrics` + dashboard UI
- Prometheus scrapes Nest `/metrics`, Grafana dashboards provisioned in `deploy/grafana/`
- Config flows: Nest publishes retained MQTT config → Eggs subscribe, apply host > global precedence, ack back
- Host IDs constrained to `[A-Za-z0-9._-]{1,64}` via Pydantic model validation
- Inventory published at startup, on config change, and on refresh request

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.

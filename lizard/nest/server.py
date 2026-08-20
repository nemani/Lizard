from __future__ import annotations

import json
import logging
import sys
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import paho.mqtt.client as mqtt
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse

from lizard.common.models import (
    AlertConfig,
    ConfigAck,
    ConfigEnvelope,
    HostInventory,
    HostStatus,
    MetricsEnvelope,
)
from lizard.common.mqtt import (
    MqttSettings,
    build_client,
    publish_text,
    track_connection,
    wait_for_mqtt_connection,
)
from lizard.nest.config import NestSettings
from lizard.nest.config_store import ConfigStore
from lizard.nest.prometheus import render_prometheus_metrics
from lizard.nest.store import MetricsStore
from lizard.nest.ui import index_html

LOGGER = logging.getLogger(__name__)
settings = NestSettings()
store = MetricsStore(settings.data_dir)
config_store = ConfigStore(settings.data_dir)
client: mqtt.Client | None = None
mqtt_connected: threading.Event | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    startup()
    try:
        yield
    finally:
        shutdown()


app = FastAPI(title="Lizard Nest", version="0.1.0", lifespan=lifespan)


def startup() -> None:
    global client, mqtt_connected
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    store.load_existing_latest()
    mqtt_settings = MqttSettings(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        topic_prefix=settings.mqtt_topic_prefix,
        username=settings.mqtt_username,
        password=settings.mqtt_password,
        tls=settings.mqtt_tls,
    )
    client = build_client("lizard-nest", mqtt_settings)
    mqtt_connected = track_connection(client, _on_connect)
    client.on_message = _on_message
    client.connect_async(mqtt_settings.host, mqtt_settings.port, keepalive=60)
    client.loop_start()
    LOGGER.info("started lizard nest mqtt=%s:%s", settings.mqtt_host, settings.mqtt_port)


def shutdown() -> None:
    if client is not None:
        client.loop_stop()
        client.disconnect()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return index_html()


@app.get("/servers")
def servers() -> list[MetricsEnvelope]:
    return store.latest()


@app.get("/servers/status")
def server_statuses() -> list[HostStatus]:
    return store.statuses(settings.host_stale_seconds, settings.host_offline_seconds)


@app.get("/servers/inventory")
def server_inventories() -> list[HostInventory]:
    return store.inventories()


@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics() -> str:
    statuses = store.statuses(settings.host_stale_seconds, settings.host_offline_seconds)
    return render_prometheus_metrics(store.latest(), statuses)


@app.get("/servers/{host_id}")
def server(host_id: str) -> MetricsEnvelope:
    envelope = store.get(host_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail="unknown host_id")
    return envelope


@app.get("/servers/{host_id}/series")
def server_series(host_id: str, limit: int = 240) -> list[MetricsEnvelope]:
    if store.get(host_id) is None:
        raise HTTPException(status_code=404, detail="unknown host_id")
    return store.history(host_id, limit=min(limit, 2000))


@app.get("/servers/{host_id}/inventory")
def server_inventory(host_id: str) -> HostInventory:
    inventory = store.inventory(host_id)
    if inventory is None:
        raise HTTPException(status_code=404, detail="unknown host inventory")
    return inventory


@app.post("/servers/{host_id}/inventory/refresh")
def refresh_server_inventory(host_id: str) -> dict[str, str]:
    mqtt_client = _require_mqtt_client()
    if store.get(host_id) is None:
        raise HTTPException(status_code=404, detail="unknown host_id")

    topic = f"{settings.mqtt_topic_prefix}/servers/{host_id}/inventory/refresh"
    try:
        publish_text(mqtt_client, topic, "{}", qos=1)
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "ok", "host_id": host_id}


@app.get("/config")
def configs() -> dict[str, ConfigEnvelope]:
    return config_store.all()


@app.get("/config/global")
def global_config() -> ConfigEnvelope | None:
    return config_store.get("global")


@app.post("/config/global")
def set_global_config(config: AlertConfig) -> ConfigEnvelope:
    return _publish_config("global", f"{settings.mqtt_topic_prefix}/config/global", config)


@app.get("/servers/{host_id}/config")
def host_config(host_id: str) -> ConfigEnvelope | None:
    return config_store.get(f"host:{host_id}")


@app.post("/servers/{host_id}/config")
def set_host_config(host_id: str, config: AlertConfig) -> ConfigEnvelope:
    if store.get(host_id) is None:
        raise HTTPException(status_code=404, detail="unknown host_id")
    topic = f"{settings.mqtt_topic_prefix}/servers/{host_id}/config"
    return _publish_config(f"host:{host_id}", topic, config)


@app.delete("/servers/{host_id}/config")
def delete_host_config(host_id: str) -> dict[str, str | bool]:
    mqtt_client = _require_mqtt_client()
    if store.get(host_id) is None:
        raise HTTPException(status_code=404, detail="unknown host_id")

    topic = f"{settings.mqtt_topic_prefix}/servers/{host_id}/config"
    try:
        publish_text(mqtt_client, topic, "", qos=1, retain=True)
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    deleted = config_store.delete(f"host:{host_id}")
    LOGGER.info("deleted retained config host_id=%s topic=%s existed=%s", host_id, topic, deleted)
    return {"status": "ok", "host_id": host_id, "deleted": deleted}


@app.get("/config/acks")
def config_acks() -> dict[str, ConfigAck]:
    return config_store.acks()


def _on_connect(
    mqtt_client: mqtt.Client,
    _userdata: object,
    _flags: mqtt.ConnectFlags,
    reason_code: mqtt.ReasonCode,
    _properties: mqtt.Properties | None,
) -> None:
    if reason_code.is_failure:
        LOGGER.error("MQTT connection failed: %s", reason_code)
        return
    topics = [
        (f"{settings.mqtt_topic_prefix}/servers/+/metrics", 1),
        (f"{settings.mqtt_topic_prefix}/servers/+/config/status", 1),
        (f"{settings.mqtt_topic_prefix}/servers/+/inventory", 1),
    ]
    mqtt_client.subscribe(topics)
    LOGGER.info("subscribed to nest topics")


def _on_message(_mqtt_client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
    if message.topic.endswith("/config/status"):
        _on_config_status(message)
        return
    if message.topic.endswith("/inventory"):
        _on_inventory(message)
        return

    try:
        payload = json.loads(message.payload.decode("utf-8"))
        envelope = MetricsEnvelope.model_validate(payload)
    except Exception:
        LOGGER.exception("discarding invalid metrics message from %s", message.topic)
        return

    store.put(envelope)
    LOGGER.info(
        "stored metrics host_id=%s alerts=%s topic=%s",
        envelope.host_id,
        len(envelope.alerts),
        message.topic,
    )


def _on_inventory(message: mqtt.MQTTMessage) -> None:
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        inventory = HostInventory.model_validate(payload)
    except Exception:
        LOGGER.exception("discarding invalid inventory from %s", message.topic)
        return

    store.put_inventory(inventory)
    LOGGER.info(
        "stored inventory host_id=%s disks=%s gpus=%s",
        inventory.host_id,
        len(inventory.disks),
        len(inventory.gpus),
    )


def _on_config_status(message: mqtt.MQTTMessage) -> None:
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        ack = ConfigAck.model_validate(payload)
    except Exception:
        LOGGER.exception("discarding invalid config status from %s", message.topic)
        return

    config_store.put_ack(ack)
    LOGGER.info(
        "stored config ack host_id=%s status=%s active=%s:%s",
        ack.host_id,
        ack.status,
        ack.active_scope,
        ack.active_version,
    )


def _publish_config(scope: str, topic: str, config: AlertConfig) -> ConfigEnvelope:
    mqtt_client = _require_mqtt_client()

    envelope = config_store.next_envelope(scope, config)
    payload = envelope.model_dump_json(exclude_none=True)
    try:
        publish_text(mqtt_client, topic, payload, qos=1, retain=True)
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    LOGGER.info("published retained config scope=%s version=%s topic=%s", scope, envelope.version, topic)
    return envelope


def _require_mqtt_client() -> mqtt.Client:
    if client is None or mqtt_connected is None:
        raise HTTPException(status_code=503, detail="MQTT client is not connected")
    try:
        wait_for_mqtt_connection(mqtt_connected, f"{settings.mqtt_host}:{settings.mqtt_port}")
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return client


def main() -> int:
    uvicorn.run(app, host=settings.listen_host, port=settings.listen_port)
    return 0


if __name__ == "__main__":
    sys.exit(main())

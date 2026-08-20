from __future__ import annotations

import json
import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import paho.mqtt.client as mqtt
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from lizard.common.models import AlertConfig, MetricsEnvelope
from lizard.common.mqtt import MqttSettings, build_client
from lizard.nest.config import NestSettings
from lizard.nest.config_store import ConfigStore
from lizard.nest.store import MetricsStore
from lizard.nest.ui import INDEX_HTML

LOGGER = logging.getLogger(__name__)
settings = NestSettings()
store = MetricsStore(settings.data_dir)
config_store = ConfigStore(settings.data_dir)
client: mqtt.Client | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    startup()
    try:
        yield
    finally:
        shutdown()


app = FastAPI(title="Lizard Nest", version="0.1.0", lifespan=lifespan)


def startup() -> None:
    global client
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
    client.on_connect = _on_connect
    client.on_message = _on_message
    client.connect(mqtt_settings.host, mqtt_settings.port, keepalive=60)
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
    return INDEX_HTML


@app.get("/servers")
def servers() -> list[MetricsEnvelope]:
    return store.latest()


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


@app.get("/config")
def configs() -> dict[str, AlertConfig]:
    return config_store.all()


@app.get("/config/global")
def global_config() -> AlertConfig:
    return config_store.get("global") or AlertConfig()


@app.post("/config/global")
def set_global_config(config: AlertConfig) -> dict[str, str]:
    _publish_config("global", f"{settings.mqtt_topic_prefix}/config/global", config)
    return {"status": "ok", "scope": "global"}


@app.get("/servers/{host_id}/config")
def host_config(host_id: str) -> AlertConfig:
    return config_store.get(f"host:{host_id}") or AlertConfig()


@app.post("/servers/{host_id}/config")
def set_host_config(host_id: str, config: AlertConfig) -> dict[str, str]:
    if store.get(host_id) is None:
        raise HTTPException(status_code=404, detail="unknown host_id")
    topic = f"{settings.mqtt_topic_prefix}/servers/{host_id}/config"
    _publish_config(f"host:{host_id}", topic, config)
    return {"status": "ok", "scope": f"host:{host_id}"}


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
    topic = f"{settings.mqtt_topic_prefix}/servers/+/metrics"
    mqtt_client.subscribe(topic, qos=1)
    LOGGER.info("subscribed to %s", topic)


def _on_message(_mqtt_client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
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


def _publish_config(scope: str, topic: str, config: AlertConfig) -> None:
    if client is None:
        raise HTTPException(status_code=503, detail="MQTT client is not connected")

    config_store.put(scope, config)
    payload = config.model_dump_json(exclude_none=True)
    result = client.publish(topic, payload, qos=1, retain=True)
    result.wait_for_publish(timeout=10)
    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        raise HTTPException(status_code=502, detail=f"failed to publish MQTT config: rc={result.rc}")
    LOGGER.info("published retained config scope=%s topic=%s", scope, topic)


def main() -> int:
    uvicorn.run(app, host=settings.listen_host, port=settings.listen_port)
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from lizard.common.models import ConfigAck, ConfigEnvelope
from lizard.common.mqtt import MqttSettings, build_client, publish_json, publish_text
from lizard.egg.collector import collect_metrics
from lizard.egg.config import EggSettings
from lizard.egg.inventory import collect_inventory

LOGGER = logging.getLogger(__name__)
SHUTDOWN = False


class RuntimeState:
    def __init__(self, settings: EggSettings) -> None:
        self._lock = threading.Lock()
        self._base_settings = settings
        self._settings = settings
        self._global_config: ConfigEnvelope | None = None
        self._host_config: ConfigEnvelope | None = None

    def get_settings(self) -> EggSettings:
        with self._lock:
            return self._settings

    def apply_remote_config(self, topic: str, payload: bytes) -> ConfigAck:
        try:
            decoded = json.loads(payload.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise TypeError("config payload must be a JSON object")
            envelope = ConfigEnvelope.model_validate(decoded)
            with self._lock:
                if envelope.scope == "global":
                    self._global_config = envelope
                elif envelope.scope == f"host:{self._base_settings.host_id}":
                    self._host_config = envelope
                else:
                    raise ValueError(f"config scope {envelope.scope!r} does not match this egg")
                active = self._active_config()
                self._settings = (
                    self._base_settings.with_alert_config(active.config)
                    if active is not None
                    else self._base_settings
                )
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError, ValidationError):
            LOGGER.exception("discarding invalid remote config from %s", topic)
            return self._config_ack("unknown", 0, "rejected", "invalid config payload")
        except ValueError as exc:
            LOGGER.warning("discarding remote config from %s: %s", topic, exc)
            return self._config_ack("unknown", 0, "rejected", str(exc))

        with self._lock:
            active = self._active_config()
            status = "applied" if active == envelope else "stored"
            ack = self._config_ack(envelope.scope, envelope.version, status, "config received")
        LOGGER.info(
            "%s remote config from %s scope=%s version=%s active=%s:%s",
            status,
            topic,
            envelope.scope,
            envelope.version,
            ack.active_scope,
            ack.active_version,
        )
        return ack

    def _active_config(self) -> ConfigEnvelope | None:
        return self._host_config or self._global_config

    def _config_ack(self, scope: str, version: int, status: str, message: str) -> ConfigAck:
        active = self._active_config()
        return ConfigAck(
            host_id=self._base_settings.host_id,
            hostname=self._base_settings.hostname,
            scope=scope,
            version=version,
            active_scope=active.scope if active is not None else "local",
            active_version=active.version if active is not None else 0,
            status=status,
            message=message,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Lizard egg monitoring agent.")
    parser.add_argument("--once", action="store_true", help="Collect and publish one sample, then exit.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    settings = EggSettings()
    agent_started_at = datetime.now(timezone.utc)
    state = RuntimeState(settings)
    mqtt_settings = MqttSettings(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        topic_prefix=settings.mqtt_topic_prefix,
        username=settings.mqtt_username,
        password=settings.mqtt_password,
        tls=settings.mqtt_tls,
    )
    client = build_client(f"lizard-egg-{settings.host_id}", mqtt_settings)
    if settings.remote_config_enabled:
        client.on_connect = _build_on_connect(settings)
        client.on_message = _build_on_message(state, settings)
    client.connect(mqtt_settings.host, mqtt_settings.port, keepalive=60)
    client.loop_start()
    _publish_inventory(client, settings)

    LOGGER.info(
        "started lizard egg host_id=%s mqtt=%s:%s interval=%ss",
        settings.host_id,
        settings.mqtt_host,
        settings.mqtt_port,
        settings.interval_seconds,
    )
    try:
        while not SHUTDOWN:
            settings = state.get_settings()
            try:
                envelope = collect_metrics(settings, agent_started_at=agent_started_at)
                topic = f"{settings.mqtt_topic_prefix}/servers/{settings.host_id}/metrics"
                publish_json(client, topic, envelope.model_dump(mode="json"))
                LOGGER.info("published metrics to %s alerts=%s", topic, len(envelope.alerts))
            except (RuntimeError, TimeoutError):
                LOGGER.exception("failed to publish metrics; will retry next interval")
            if args.once:
                break
            time.sleep(settings.interval_seconds)
    finally:
        client.loop_stop()
        client.disconnect()
    return 0


def _handle_shutdown(signum: int, _frame: object) -> None:
    global SHUTDOWN
    LOGGER.info("received signal %s; shutting down", signum)
    SHUTDOWN = True


def _build_on_connect(settings: EggSettings):
    def on_connect(
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
            (f"{settings.mqtt_topic_prefix}/config/global", 1),
            (f"{settings.mqtt_topic_prefix}/servers/{settings.host_id}/config", 1),
            (f"{settings.mqtt_topic_prefix}/servers/{settings.host_id}/inventory/refresh", 1),
        ]
        mqtt_client.subscribe(topics)
        LOGGER.info("subscribed to remote config and inventory topics")

    return on_connect


def _build_on_message(state: RuntimeState, settings: EggSettings):
    def on_message(mqtt_client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
        if message.topic.endswith("/inventory/refresh"):
            _publish_inventory(mqtt_client, settings, wait=False)
            return

        ack = state.apply_remote_config(message.topic, message.payload)
        topic = f"{settings.mqtt_topic_prefix}/servers/{settings.host_id}/config/status"
        payload = ack.model_dump_json()
        publish_text(mqtt_client, topic, payload, qos=1, retain=True, wait=False)
        _publish_inventory(mqtt_client, state.get_settings(), wait=False)

    return on_message


def _publish_inventory(mqtt_client: mqtt.Client, settings: EggSettings, wait: bool = True) -> None:
    inventory = collect_inventory(settings)
    topic = f"{settings.mqtt_topic_prefix}/servers/{settings.host_id}/inventory"
    try:
        publish_text(mqtt_client, topic, inventory.model_dump_json(), qos=1, retain=True, wait=wait)
        if wait:
            LOGGER.info("published inventory to %s", topic)
        else:
            LOGGER.info("queued inventory publish to %s", topic)
    except (RuntimeError, TimeoutError) as exc:
        LOGGER.warning("failed to publish inventory to %s: %s", topic, exc)


if __name__ == "__main__":
    sys.exit(main())

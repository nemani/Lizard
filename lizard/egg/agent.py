from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from lizard.common.mqtt import MqttSettings, build_client, publish_json
from lizard.egg.collector import collect_metrics
from lizard.egg.config import EggSettings

LOGGER = logging.getLogger(__name__)
SHUTDOWN = False


class RuntimeState:
    def __init__(self, settings: EggSettings) -> None:
        self._lock = threading.Lock()
        self._settings = settings

    def get_settings(self) -> EggSettings:
        with self._lock:
            return self._settings

    def apply_remote_config(self, topic: str, payload: bytes) -> None:
        try:
            decoded = json.loads(payload.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise TypeError("config payload must be a JSON object")
            with self._lock:
                updated = self._settings.with_remote_update(decoded)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError, ValidationError):
            LOGGER.exception("discarding invalid remote config from %s", topic)
            return

        with self._lock:
            self._settings = updated
        LOGGER.info("applied remote config from %s", topic)


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
        client.on_message = _build_on_message(state)
    client.connect(mqtt_settings.host, mqtt_settings.port, keepalive=60)
    client.loop_start()

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
            envelope = collect_metrics(settings)
            topic = f"{settings.mqtt_topic_prefix}/servers/{settings.host_id}/metrics"
            publish_json(client, topic, envelope.model_dump(mode="json"))
            LOGGER.info("published metrics to %s alerts=%s", topic, len(envelope.alerts))
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
        ]
        mqtt_client.subscribe(topics)
        LOGGER.info("subscribed to remote config topics")

    return on_connect


def _build_on_message(state: RuntimeState):
    def on_message(_mqtt_client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
        state.apply_remote_config(message.topic, message.payload)

    return on_message


if __name__ == "__main__":
    sys.exit(main())

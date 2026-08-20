from __future__ import annotations

import json
import logging
import ssl
from dataclasses import dataclass

import paho.mqtt.client as mqtt
from pydantic import SecretStr

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MqttSettings:
    host: str
    port: int
    topic_prefix: str
    username: str | None = None
    password: SecretStr | None = None
    tls: bool = False


def build_client(client_id: str, settings: MqttSettings) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    if settings.username:
        client.username_pw_set(
            settings.username,
            settings.password.get_secret_value() if settings.password else None,
        )
    if settings.tls:
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    return client


def publish_json(client: mqtt.Client, topic: str, payload: dict, qos: int = 1) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), default=str)
    result = client.publish(topic, encoded, qos=qos)
    result.wait_for_publish(timeout=10)
    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"failed to publish MQTT message to {topic}: rc={result.rc}")

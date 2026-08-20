from __future__ import annotations

import json
import logging
import ssl
import threading
from collections.abc import Callable
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


def track_connection(
    client: mqtt.Client,
    on_connect: Callable[..., None] | None = None,
    on_disconnect: Callable[..., None] | None = None,
) -> threading.Event:
    connected = threading.Event()

    def tracked_on_connect(
        mqtt_client: mqtt.Client,
        userdata: object,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            connected.clear()
        else:
            connected.set()
        if on_connect is not None:
            on_connect(mqtt_client, userdata, flags, reason_code, properties)

    def tracked_on_disconnect(mqtt_client: mqtt.Client, userdata: object, *args: object) -> None:
        connected.clear()
        if on_disconnect is not None:
            on_disconnect(mqtt_client, userdata, *args)

    client.on_connect = tracked_on_connect
    client.on_disconnect = tracked_on_disconnect
    return connected


def wait_for_mqtt_connection(connected: threading.Event, target: str, timeout: float = 10) -> None:
    if not connected.wait(timeout):
        raise TimeoutError(f"timed out waiting for MQTT connection to {target}")


def publish_json(client: mqtt.Client, topic: str, payload: dict, qos: int = 1) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), default=str)
    publish_text(client, topic, encoded, qos=qos)


def publish_text(
    client: mqtt.Client,
    topic: str,
    payload: str,
    qos: int = 1,
    retain: bool = False,
    wait: bool = True,
) -> None:
    result = client.publish(topic, payload, qos=qos, retain=retain)
    if wait:
        wait_for_publish_success(result, topic)


def wait_for_publish_success(
    result: mqtt.MQTTMessageInfo,
    topic: str,
    timeout: float = 10,
) -> None:
    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"failed to publish MQTT message to {topic}: rc={result.rc}")
    result.wait_for_publish(timeout=timeout)
    if not result.is_published():
        raise TimeoutError(f"timed out publishing MQTT message to {topic}")

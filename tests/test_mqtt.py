import pytest
from paho.mqtt import client as mqtt

from lizard.common.mqtt import track_connection, wait_for_mqtt_connection, wait_for_publish_success


class FakePublishResult:
    def __init__(self, rc: int, published: bool) -> None:
        self.rc = rc
        self._published = published
        self.timeout: float | None = None

    def wait_for_publish(self, timeout: float) -> None:
        self.timeout = timeout

    def is_published(self) -> bool:
        return self._published


class FakeReasonCode:
    def __init__(self, is_failure: bool = False) -> None:
        self.is_failure = is_failure


class FakeClient:
    def __init__(self) -> None:
        self.on_connect = None
        self.on_disconnect = None


def test_wait_for_publish_success_accepts_published_result() -> None:
    result = FakePublishResult(mqtt.MQTT_ERR_SUCCESS, True)

    wait_for_publish_success(result, "lizard/test", timeout=3)

    assert result.timeout == 3


def test_wait_for_publish_success_rejects_immediate_publish_error() -> None:
    result = FakePublishResult(mqtt.MQTT_ERR_NO_CONN, False)

    with pytest.raises(RuntimeError):
        wait_for_publish_success(result, "lizard/test")


def test_wait_for_publish_success_rejects_timeout_without_publish() -> None:
    result = FakePublishResult(mqtt.MQTT_ERR_SUCCESS, False)

    with pytest.raises(TimeoutError):
        wait_for_publish_success(result, "lizard/test", timeout=0.01)


def test_track_connection_sets_clears_and_delegates_callbacks() -> None:
    client = FakeClient()
    calls: list[str] = []

    connected = track_connection(
        client,
        on_connect=lambda *_args: calls.append("connect"),
        on_disconnect=lambda *_args: calls.append("disconnect"),
    )

    client.on_connect(client, None, None, FakeReasonCode(), None)
    assert connected.is_set()
    assert calls == ["connect"]

    client.on_disconnect(client, None, None, FakeReasonCode())
    assert not connected.is_set()
    assert calls == ["connect", "disconnect"]

    client.on_connect(client, None, None, FakeReasonCode(is_failure=True), None)
    assert not connected.is_set()
    assert calls == ["connect", "disconnect", "connect"]


def test_wait_for_mqtt_connection_rejects_timeout() -> None:
    connected = track_connection(FakeClient())

    with pytest.raises(TimeoutError):
        wait_for_mqtt_connection(connected, "mqtt:1883", timeout=0.01)

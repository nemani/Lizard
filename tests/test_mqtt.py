import pytest
from paho.mqtt import client as mqtt

from lizard.common.mqtt import wait_for_publish_success


class FakePublishResult:
    def __init__(self, rc: int, published: bool) -> None:
        self.rc = rc
        self._published = published
        self.timeout: float | None = None

    def wait_for_publish(self, timeout: float) -> None:
        self.timeout = timeout

    def is_published(self) -> bool:
        return self._published


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

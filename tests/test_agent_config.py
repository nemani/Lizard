import pytest
from pydantic import ValidationError

from lizard.common.models import AlertConfig, ConfigEnvelope
from lizard.egg.agent import RuntimeState
from lizard.egg.config import EggSettings


def test_host_config_replaces_global_config_precedence() -> None:
    settings = EggSettings(host_id="gpu-01", hostname="gpu-01")
    state = RuntimeState(settings)

    global_ack = state.apply_remote_config(
        "lizard/config/global",
        ConfigEnvelope(
            scope="global",
            version=1,
            config=AlertConfig(interval_seconds=20),
        ).model_dump_json().encode(),
    )
    host_ack = state.apply_remote_config(
        "lizard/servers/gpu-01/config",
        ConfigEnvelope(
            scope="host:gpu-01",
            version=1,
            config=AlertConfig(interval_seconds=5),
        ).model_dump_json().encode(),
    )

    assert global_ack.status == "applied"
    assert host_ack.status == "applied"
    assert host_ack.active_scope == "host:gpu-01"
    assert host_ack.active_version == 1
    assert state.get_settings().interval_seconds == 5


def test_global_config_is_stored_but_not_applied_when_host_config_exists() -> None:
    settings = EggSettings(host_id="gpu-01", hostname="gpu-01")
    state = RuntimeState(settings)
    state.apply_remote_config(
        "lizard/servers/gpu-01/config",
        ConfigEnvelope(
            scope="host:gpu-01",
            version=1,
            config=AlertConfig(interval_seconds=5),
        ).model_dump_json().encode(),
    )

    ack = state.apply_remote_config(
        "lizard/config/global",
        ConfigEnvelope(
            scope="global",
            version=2,
            config=AlertConfig(interval_seconds=20),
        ).model_dump_json().encode(),
    )

    assert ack.status == "stored"
    assert ack.active_scope == "host:gpu-01"
    assert state.get_settings().interval_seconds == 5


def test_egg_settings_rejects_invalid_host_id_at_startup() -> None:
    with pytest.raises(ValidationError):
        EggSettings(host_id="../gpu-01", hostname="gpu-01")


def test_inventory_publish_request_is_consumed_once() -> None:
    state = RuntimeState(EggSettings(host_id="gpu-01", hostname="gpu-01"))

    assert state.consume_inventory_publish_request() is False

    state.request_inventory_publish()

    assert state.consume_inventory_publish_request() is True
    assert state.consume_inventory_publish_request() is False

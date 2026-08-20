from lizard.common.models import AlertConfig, AlertThreshold, ConfigAck
from lizard.nest.config_store import ConfigStore


def test_config_store_versions_and_persists_scoped_configs(tmp_path) -> None:
    store = ConfigStore(tmp_path)
    first = store.next_envelope(
        "global",
        AlertConfig(
            interval_seconds=10,
            cpu_percent_thresholds=[
                AlertThreshold(level="warning", value=50),
                AlertThreshold(level="critical", value=90),
            ],
        ),
    )
    second = store.next_envelope("global", AlertConfig(interval_seconds=20))

    reloaded = ConfigStore(tmp_path)
    envelope = reloaded.get("global")

    assert first.version == 1
    assert second.version == 2
    assert envelope is not None
    assert envelope.version == 2
    assert envelope.config.interval_seconds == 20


def test_config_store_persists_acks(tmp_path) -> None:
    store = ConfigStore(tmp_path)
    store.put_ack(
        ConfigAck(
            host_id="gpu-01",
            hostname="gpu-01",
            scope="global",
            version=1,
            active_scope="global",
            active_version=1,
            status="applied",
            message="ok",
        )
    )

    reloaded = ConfigStore(tmp_path)

    assert reloaded.acks()["gpu-01"].active_version == 1

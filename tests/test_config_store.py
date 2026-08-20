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


def test_config_store_deletes_scoped_config(tmp_path) -> None:
    store = ConfigStore(tmp_path)
    store.next_envelope("host:gpu-01", AlertConfig(interval_seconds=5))

    assert store.delete("host:gpu-01") is True
    assert store.delete("host:gpu-01") is False

    reloaded = ConfigStore(tmp_path)
    assert reloaded.get("host:gpu-01") is None


def test_config_store_skips_corrupt_persisted_state(tmp_path) -> None:
    (tmp_path / "configs.json").write_text("{not-json", encoding="utf-8")

    store = ConfigStore(tmp_path)

    assert store.all() == {}
    assert store.acks() == {}


def test_config_store_skips_invalid_entries(tmp_path) -> None:
    (tmp_path / "configs.json").write_text(
        """
        {
          "configs": {
            "global": {"scope": "global", "version": 1, "config": {"interval_seconds": 10}},
            "bad": {"scope": "bad", "version": 0, "config": {}}
          },
          "acks": {
            "gpu-01": {
              "host_id": "gpu-01",
              "hostname": "gpu-01",
              "scope": "global",
              "version": 1,
              "active_scope": "global",
              "active_version": 1,
              "status": "applied",
              "message": "ok"
            },
            "bad": {"host_id": "../bad"}
          }
        }
        """,
        encoding="utf-8",
    )

    store = ConfigStore(tmp_path)

    assert set(store.all()) == {"global"}
    assert set(store.acks()) == {"gpu-01"}

from lizard.common.models import AlertConfig, AlertThreshold
from lizard.nest.config_store import ConfigStore


def test_config_store_persists_scoped_configs(tmp_path) -> None:
    store = ConfigStore(tmp_path)
    store.put(
        "global",
        AlertConfig(
            interval_seconds=10,
            cpu_percent_thresholds=[
                AlertThreshold(level="warning", value=50),
                AlertThreshold(level="critical", value=90),
            ],
        ),
    )

    reloaded = ConfigStore(tmp_path)
    config = reloaded.get("global")

    assert config is not None
    assert config.interval_seconds == 10
    assert [(item.level, item.value) for item in config.cpu_percent_thresholds or []] == [
        ("warning", 50),
        ("critical", 90),
    ]

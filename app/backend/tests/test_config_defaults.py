from src.services.config_defaults import ConfigDefaultsResolver


def test_task_override_recovers_section_when_existing_payload_value_is_scalar():
    resolver = ConfigDefaultsResolver()
    task = {
        "id": 4,
        "name": "single save",
        "payload": {
            "logistics": "legacy bad scalar",
            "template_overrides": {
                "logistics": {
                    "weight": "0.08",
                    "length": "12",
                },
            },
        },
    }

    result = resolver.resolve([], task, None)

    assert result.defaults["logistics"] == {
        "weight": "0.08",
        "length": "12",
    }
    assert result.sources["logistics"] == {
        "weight": "任务覆盖",
        "length": "任务覆盖",
    }

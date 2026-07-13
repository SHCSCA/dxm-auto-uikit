from src.services.config_defaults import ConfigDefaultsResolver


def test_template_values_take_priority_over_task_overrides():
    resolver = ConfigDefaultsResolver()
    templates = [
        {
            "id": 1,
            "template_type": "logistics",
            "template_name": "Dang Kang 包装物流模板",
            "is_enabled": True,
            "payload": {
                "logistics": {
                    "weight": "0.03",
                    "length": "10",
                    "width": "10",
                }
            },
        }
    ]
    task = {
        "id": 4,
        "name": "single save",
        "payload": {
            "template_overrides": {
                "logistics": {
                    "weight": "0.08",
                    "length": "12",
                    "height": "2",
                },
            },
        },
    }

    result = resolver.resolve(templates, task, None)

    assert result.defaults["logistics"] == {
        "weight": "0.03",
        "length": "10",
        "width": "10",
        "height": "2",
    }
    assert result.sources["logistics"] == {
        "weight": "模板：Dang Kang 包装物流模板",
        "length": "模板：Dang Kang 包装物流模板",
        "width": "模板：Dang Kang 包装物流模板",
        "height": "高级：本次任务临时覆盖",
    }


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
        "weight": "高级：本次任务临时覆盖",
        "length": "高级：本次任务临时覆盖",
    }

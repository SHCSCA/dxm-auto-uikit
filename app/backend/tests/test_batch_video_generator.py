"""旧视频兼容入口必须零访问、零派发且明确拒绝。"""

import asyncio

import pytest

from src.batch_edit.path_a_section_templates import VideoGenerationConfig
from src.batch_edit.video_generator import (
    LEGACY_VIDEO_EXECUTOR_NOT_BOUND,
    BatchVideoGenerator,
    VideoGenerationError,
    VideoGenerationResult,
)


class Untouchable:
    def __init__(self, touches):
        object.__setattr__(self, "touches", touches)

    def __getattribute__(self, name):
        object.__getattribute__(self, "touches").append(name)
        raise AssertionError("旧视频入口不得访问调用方对象")

    def __repr__(self):
        raise AssertionError("旧视频入口不得格式化调用方对象")

    __str__ = __repr__


def assert_not_bound(result):
    assert result.success is False
    assert result.error_type == VideoGenerationError.EXECUTOR_NOT_BOUND
    assert result.error_message == LEGACY_VIDEO_EXECUTOR_NOT_BOUND
    assert result.execution_state == "blocked"
    assert result.completion_state == "not_bound"
    assert result.request_recorded is False
    assert result.video_id is None and result.media_identity is None
    assert result.quota_remaining is None
    assert result.evidence == {"reason_code": LEGACY_VIDEO_EXECUTOR_NOT_BOUND,
                              "write_attempted": False, "execution_allowed": False}


def test_default_config_import_remains_compatible():
    config = VideoGenerationConfig()
    assert config.enabled is False
    assert config.failure_strategy == "pause"
    assert config.max_wait_seconds == 300 and config.poll_interval_seconds == 5


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("strategy", ["pause", "ignore"])
def test_every_enabled_and_failure_strategy_refuses_without_touching_page_or_client(enabled, strategy, caplog):
    touches = []
    forbidden = Untouchable(touches)
    generator = BatchVideoGenerator(dxm_client=forbidden)
    config = VideoGenerationConfig(enabled=enabled, failure_strategy=strategy)
    result = asyncio.run(generator.execute(forbidden, config, forbidden))
    assert_not_bound(result)
    assert touches == []
    events = [record for record in caplog.records if record.message == "legacy_video_execution_rejected"]
    assert len(events) == 1 and events[0].name == "dxm.legacy_video_generator"
    assert events[0].event_fields == {"reason_code": LEGACY_VIDEO_EXECUTOR_NOT_BOUND, "write_attempted": False}


@pytest.mark.parametrize("kind", ["none", "unknown", "hostile"])
def test_refusal_does_not_need_configuration_or_context_inspection(kind):
    touches = []
    forbidden = Untouchable(touches)
    config = {"none": None, "unknown": object(), "hostile": forbidden}[kind]
    result = asyncio.run(BatchVideoGenerator(forbidden).execute(forbidden, config, forbidden))
    assert_not_bound(result)
    assert touches == []


def test_refusal_logs_only_fixed_facts_and_repeated_calls_stay_blocked(caplog):
    generator = BatchVideoGenerator()
    context = {"token": "private-video-token", "product_id": "private-product"}
    config = {"enabled": True, "failure_strategy": "ignore", "secret": "private-config"}
    first = asyncio.run(generator.execute(None, config, context))
    first.evidence["execution_allowed"] = True
    second = asyncio.run(generator.execute(None, config, context))
    assert_not_bound(second)
    assert context == {"token": "private-video-token", "product_id": "private-product"}
    assert config == {"enabled": True, "failure_strategy": "ignore", "secret": "private-config"}
    assert "private-" not in caplog.text


@pytest.mark.parametrize("entry", ["_check_quota", "_trigger_generation", "_poll_completion",
                                   "_capture_media_identity", "_place_video_to_product"])
def test_untrusted_private_execution_entry_points_are_removed(entry):
    assert not hasattr(BatchVideoGenerator(), entry)


def test_result_container_and_existing_error_values_remain_import_compatible():
    result = VideoGenerationResult(success=False, error_type=VideoGenerationError.QUOTA_EXHAUSTED,
                                   quota_remaining=0, error_message="额度不足，未执行")
    assert result.success is False and result.error_type == "quota_exhausted"
    assert result.quota_remaining == 0 and result.request_recorded is False
    assert VideoGenerationError.PROGRAM_ERROR == "program_error"
    assert VideoGenerationError.TIMEOUT == "timeout"
    assert VideoGenerationError.PAGE_ERROR == "page_error"
    assert VideoGenerationError.DISPATCH_UNCERTAIN == "dispatch_uncertain"


def test_native_input_helpers_still_reexport_the_shared_validation_functions():
    from src.batch_edit import native_video_inputs, video_generator

    assert video_generator.VideoGenerationConfig is VideoGenerationConfig
    assert video_generator.resolve_native_video_inputs is native_video_inputs.resolve_native_video_inputs
    assert video_generator.validate_native_video_generation_rule is native_video_inputs.validate_native_video_generation_rule
    assert video_generator.NATIVE_VIDEO_TRANSITIONS is native_video_inputs.NATIVE_VIDEO_TRANSITIONS

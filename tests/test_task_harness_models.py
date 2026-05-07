from __future__ import annotations

from ainrf.task_harness.models import TaskConfigurationMode


def test_task_configuration_mode_has_all_variants() -> None:
    assert TaskConfigurationMode.RAW_PROMPT.value == "raw_prompt"
    assert TaskConfigurationMode.STRUCTURED_RESEARCH.value == "structured_research"
    assert TaskConfigurationMode.REPRODUCE_BASELINE.value == "reproduce_baseline"
    assert TaskConfigurationMode.DISCOVER_IDEAS.value == "discover_ideas"
    assert TaskConfigurationMode.VALIDATE_IDEAS.value == "validate_ideas"

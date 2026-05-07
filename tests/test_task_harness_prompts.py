from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.task_harness.models import TaskConfigurationMode
from ainrf.task_harness.service import (
    _check_aris_skills,
    _render_task_prompt,
    TaskHarnessError,
)


def test_render_reproduce_baseline_prompt() -> None:
    result = _render_task_prompt(
        "",
        TaskConfigurationMode.REPRODUCE_BASELINE,
        {
            "paper_path": "papers/target.pdf",
            "scope": "core-only",
            "target_table": "Table3",
            "budget_hours": 8,
        },
    )
    assert "/research-pipeline" in result
    assert "papers/target.pdf" in result
    assert "core-only" in result
    assert "Table3" in result


def test_render_reproduce_baseline_prompt_minimal() -> None:
    result = _render_task_prompt(
        "",
        TaskConfigurationMode.REPRODUCE_BASELINE,
        {"paper_path": "papers/target.pdf"},
    )
    assert "/research-pipeline" in result
    assert "papers/target.pdf" in result
    assert "core-only" in result
    assert "Table3" not in result


def test_render_discover_ideas_prompt() -> None:
    result = _render_task_prompt(
        "",
        TaskConfigurationMode.DISCOVER_IDEAS,
        {
            "topic": "graph neural networks for drug discovery",
            "seed_paper_path": "papers/seed.pdf",
            "depth": 5,
            "budget_hours": 6,
        },
    )
    assert "/research-lit" in result
    assert "graph neural networks for drug discovery" in result
    assert "papers/seed.pdf" in result


def test_render_discover_ideas_prompt_minimal() -> None:
    result = _render_task_prompt(
        "",
        TaskConfigurationMode.DISCOVER_IDEAS,
        {"topic": "vision transformers"},
    )
    assert "/research-lit" in result
    assert "vision transformers" in result
    assert "--seed" not in result


def test_render_validate_ideas_prompt() -> None:
    result = _render_task_prompt(
        "",
        TaskConfigurationMode.VALIDATE_IDEAS,
        {
            "idea_source": "workspace/ideas/novel-gnn.md",
            "validation_scope": "full",
            "budget_hours": 4,
        },
    )
    assert "/research-refine-pipeline" in result
    assert "workspace/ideas/novel-gnn.md" in result


def test_render_validate_ideas_prompt_minimal() -> None:
    result = _render_task_prompt(
        "",
        TaskConfigurationMode.VALIDATE_IDEAS,
        {"idea_source": "A hybrid GNN approach"},
    )
    assert "/research-refine-pipeline" in result
    assert "A hybrid GNN approach" in result
    assert "full" in result  # default scope


def test_check_aris_skills_passes_when_skills_present(tmp_path: Path) -> None:
    (tmp_path / "research-pipeline").mkdir()
    _check_aris_skills(TaskConfigurationMode.REPRODUCE_BASELINE, tmp_path)


def test_check_aris_skills_fails_when_skills_missing(tmp_path: Path) -> None:
    with pytest.raises(TaskHarnessError, match="ARIS skill.*not installed"):
        _check_aris_skills(TaskConfigurationMode.REPRODUCE_BASELINE, tmp_path)


def test_check_aris_skills_ignores_non_aris_modes(tmp_path: Path) -> None:
    _check_aris_skills(TaskConfigurationMode.RAW_PROMPT, tmp_path)
    _check_aris_skills(TaskConfigurationMode.STRUCTURED_RESEARCH, tmp_path)


def test_as_int_handles_float() -> None:
    from ainrf.task_harness.service import _as_int

    assert _as_int(3.7, default=4) == 3
    assert _as_int(3.0, default=4) == 3


def test_as_int_rejects_bool() -> None:
    from ainrf.task_harness.service import _as_int

    assert _as_int(True, default=4) == 4
    assert _as_int(False, default=4) == 4


def test_normalize_task_configuration_rejects_invalid_mode() -> None:
    from ainrf.task_harness.service import _normalize_task_configuration

    with pytest.raises(TaskHarnessError, match="Unsupported task configuration mode"):
        _normalize_task_configuration(
            "legacy",
            {"mode": "invalid_mode", "template_vars": {}},
        )

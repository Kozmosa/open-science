from __future__ import annotations

from typing import Any, Callable

from ainrf.agentic_researcher.models import AgenticResearcher, HarnessEngineType

ARIS_SYSTEM_PROMPT = """You are an ARIS (AI Research Intelligence System) researcher.
Your goal is to conduct systematic research following the ARIS methodology.
"""


def vanilla(engine: HarnessEngineType, user_skills: list[str] | None = None) -> AgenticResearcher:
    """创建 vanilla researcher - 无预置 skill，允许用户外挂"""
    return AgenticResearcher.vanilla(engine=engine, user_skills=user_skills)


def aris(engine: HarnessEngineType) -> AgenticResearcher:
    """创建 ARIS researcher - 默认挂载 ARIS skills"""
    return AgenticResearcher.aris(engine=engine, system_prompt=ARIS_SYSTEM_PROMPT)


_PRESETS: dict[str, Callable[..., AgenticResearcher]] = {
    "vanilla": vanilla,
    "aris-researcher": aris,
}


def get_preset(name: str, engine: HarnessEngineType, **kwargs: Any) -> AgenticResearcher:
    preset = _PRESETS.get(name)
    if preset is None:
        raise ValueError(f"Unknown researcher preset: {name}")
    return preset(engine=engine, **kwargs)

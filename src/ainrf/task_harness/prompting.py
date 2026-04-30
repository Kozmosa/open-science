from __future__ import annotations

from dataclasses import dataclass

from ainrf.environments.models import EnvironmentRegistryEntry
from ainrf.task_harness.models import ResearchAgentProfileSnapshot, TaskPromptLayer
from ainrf.workspaces.models import WorkspaceRecord

GLOBAL_HARNESS_PROMPT = (
    "You are running inside AINRF Task Harness v1.\n"
    "Follow the task request directly, keep your output concise, and prefer concrete changes over discussion."
)

TASK_PROFILE_PROMPTS: dict[str, str] = {
    "claude-code": (
        "Use Claude Code style execution.\n"
        "Inspect the repository before editing, apply changes directly, and summarize the concrete outcome."
    )
}


class PromptCompositionError(ValueError):
    pass


@dataclass(slots=True)
class PromptComposition:
    rendered_prompt: str
    layers: list[TaskPromptLayer]

    @property
    def layer_order(self) -> list[str]:
        return [layer.name for layer in self.layers]


def compose_task_prompt(
    *,
    workspace: WorkspaceRecord,
    environment: EnvironmentRegistryEntry,
    task_profile: str,
    task_input: str,
    research_agent_profile: ResearchAgentProfileSnapshot | None = None,
) -> PromptComposition:
    task_profile_prompt = TASK_PROFILE_PROMPTS.get(task_profile)
    if task_profile_prompt is None:
        raise PromptCompositionError(f"Unsupported task profile: {task_profile}")
    if not workspace.workspace_prompt.strip():
        raise PromptCompositionError("Workspace prompt is empty")
    environment_prompt = (environment.task_harness_profile or "").strip()
    if not environment_prompt:
        raise PromptCompositionError("Environment task harness profile is empty")

    raw_layers = [
        ("global_harness_system", "Global harness/system", GLOBAL_HARNESS_PROMPT.strip()),
        ("workspace", "Workspace", workspace.workspace_prompt.strip()),
        ("environment", "Environment", environment_prompt),
        ("task_profile", "Task profile", task_profile_prompt.strip()),
    ]
    if research_agent_profile is not None:
        if research_agent_profile.system_prompt and research_agent_profile.system_prompt.strip():
            raw_layers.append(
                (
                    "research_agent_system",
                    "Research agent system prompt",
                    research_agent_profile.system_prompt.strip(),
                )
            )
        skills_lines: list[str] = []
        if research_agent_profile.skills:
            skills_lines.append("Enabled skills: " + ", ".join(research_agent_profile.skills))
        if research_agent_profile.skills_prompt and research_agent_profile.skills_prompt.strip():
            skills_lines.append(research_agent_profile.skills_prompt.strip())
        if skills_lines:
            raw_layers.append(
                (
                    "research_agent_skills",
                    "Research agent skills/config notes",
                    "\n\n".join(skills_lines),
                )
            )
    raw_layers.append(("task_input", "Task input", task_input.strip()))
    layers = [
        TaskPromptLayer(
            position=index,
            name=name,
            label=label,
            content=content,
            char_count=len(content),
        )
        for index, (name, label, content) in enumerate(raw_layers, start=1)
    ]
    rendered_prompt = "\n\n".join(
        f"[{layer.label}]\n{layer.content}" for layer in layers if layer.content
    )
    return PromptComposition(rendered_prompt=rendered_prompt, layers=layers)


def derive_task_title(task_input: str) -> str:
    for line in task_input.splitlines():
        candidate = line.strip()
        if candidate:
            return candidate[:80]
    return "Untitled task"

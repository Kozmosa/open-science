"""Lazy skill runtime exports."""

from typing import Any
from ainrf._lazy_exports import resolve_export

_EXPORTS = {
    "SkillsDiscoveryService": ("ainrf.skills.discovery", "SkillsDiscoveryService"),
    "SkillLoader": ("ainrf.skills.loader", "SkillLoader"),
}
_EXPORTS.update(
    {
        name: ("ainrf.skills.models", name)
        for name in ("InjectMode", "SkillDefinition", "SkillItem", "SkillManifest")
    }
)
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())

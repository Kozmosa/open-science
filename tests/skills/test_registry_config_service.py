from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.skills.registry_config_service import (
    SkillRegistryConfigService,
    SkillRegistryNotFoundError,
)
from ainrf.skills.registry_models import DEFAULT_REGISTRIES, SkillRegistryConfig

pytestmark = [pytest.mark.unit]


def _default_registry_ids() -> set[str]:
    return {r.registry_id for r in DEFAULT_REGISTRIES}


def test_service_loads_defaults_when_no_file(tmp_path: Path) -> None:
    """Initialize creates the registry file and seeds default registries."""
    service = SkillRegistryConfigService(state_root=tmp_path)
    service.initialize()

    assert (tmp_path / "runtime" / "skill_registries.json").exists()
    registries = service.list_registries()
    assert {r.registry_id for r in registries} == _default_registry_ids()


def test_service_persists_custom_registries(tmp_path: Path) -> None:
    """Custom registries survive re-initialization."""
    service = SkillRegistryConfigService(state_root=tmp_path)
    service.initialize()

    custom = SkillRegistryConfig(
        registry_id="custom",
        display_name="Custom Registry",
        git_url="https://github.com/example/custom-skills.git",
        git_ref="develop",
        source_skills_path="skills",
        core_skill_ids=["custom-core"],
        install_mode="copy",
        enabled=True,
    )
    service.add_registry(custom)

    # Re-create service to force reload from disk.
    new_service = SkillRegistryConfigService(state_root=tmp_path)
    new_service.initialize()

    ids = {r.registry_id for r in new_service.list_registries()}
    assert ids == _default_registry_ids() | {"custom"}
    assert new_service.get_registry("custom").git_ref == "develop"


def test_service_merges_new_defaults(tmp_path: Path) -> None:
    """If a new default registry is added to code, it is merged on init."""
    service = SkillRegistryConfigService(state_root=tmp_path)
    service.initialize()

    # Simulate persisting only a subset by editing the file directly.
    registry_path = tmp_path / "runtime" / "skill_registries.json"
    registry_path.write_text('{"items": [], "updated_at": "2026-01-01T00:00:00"}')

    new_service = SkillRegistryConfigService(state_root=tmp_path)
    new_service.initialize()

    assert {r.registry_id for r in new_service.list_registries()} == _default_registry_ids()


def test_get_registry_not_found(tmp_path: Path) -> None:
    service = SkillRegistryConfigService(state_root=tmp_path)
    service.initialize()

    with pytest.raises(SkillRegistryNotFoundError):
        service.get_registry("missing")


def test_update_registry(tmp_path: Path) -> None:
    service = SkillRegistryConfigService(state_root=tmp_path)
    service.initialize()

    service.update_registry("aris", git_ref="stable")
    updated = service.get_registry("aris")
    assert updated.git_ref == "stable"
    assert updated.display_name == "ARIS"  # unchanged


def test_update_registry_not_found(tmp_path: Path) -> None:
    service = SkillRegistryConfigService(state_root=tmp_path)
    service.initialize()

    with pytest.raises(SkillRegistryNotFoundError):
        service.update_registry("missing", git_ref="stable")


def test_delete_custom_registry(tmp_path: Path) -> None:
    service = SkillRegistryConfigService(state_root=tmp_path)
    service.initialize()

    custom = SkillRegistryConfig(
        registry_id="custom",
        display_name="Custom",
        git_url="https://github.com/example/custom.git",
    )
    service.add_registry(custom)
    service.delete_registry("custom")

    with pytest.raises(SkillRegistryNotFoundError):
        service.get_registry("custom")


def test_delete_builtin_registry_fails(tmp_path: Path) -> None:
    service = SkillRegistryConfigService(state_root=tmp_path)
    service.initialize()

    for registry_id in _default_registry_ids():
        with pytest.raises(ValueError, match="Built-in registry"):
            service.delete_registry(registry_id)


def test_add_duplicate_registry_fails(tmp_path: Path) -> None:
    service = SkillRegistryConfigService(state_root=tmp_path)
    service.initialize()

    custom = SkillRegistryConfig(
        registry_id="custom",
        display_name="Custom",
        git_url="https://github.com/example/custom.git",
    )
    service.add_registry(custom)

    with pytest.raises(ValueError, match="already exists"):
        service.add_registry(custom)


def test_reset_to_defaults(tmp_path: Path) -> None:
    service = SkillRegistryConfigService(state_root=tmp_path)
    service.initialize()

    custom = SkillRegistryConfig(
        registry_id="custom",
        display_name="Custom",
        git_url="https://github.com/example/custom.git",
    )
    service.add_registry(custom)
    service.update_registry("aris", git_ref="stable")

    service.reset_to_defaults()

    assert {r.registry_id for r in service.list_registries()} == _default_registry_ids()
    assert service.get_registry("aris").git_ref == "main"

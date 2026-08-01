"""Lazy local development exports."""

from typing import Any

from ainrf._lazy_exports import resolve_export

_EXPORTS: dict[str, tuple[str, str]] = {}


def _exports(module: str, names: tuple[str, ...]) -> None:
    _EXPORTS.update({name: (module, name) for name in names})


_exports(
    "ainrf.development.browser",
    (
        "BrowserCdpProbe",
        "DevelopmentDoctorCheck",
        "DevelopmentDoctorResult",
        "chrome_devtools_config_locations",
        "configured_chrome_devtools_servers",
        "discover_chrome",
        "discover_chrome_devtools_mcp",
        "probe_chrome_cdp",
        "run_development_doctor",
    ),
)
_exports(
    "ainrf.development.frontend_fixture",
    (
        "DEFAULT_FRONTEND_DEV_API_KEY",
        "DEFAULT_FRONTEND_DEV_ARTIFACT_SHA",
        "FrontendDevFixture",
        "prepare_frontend_dev_fixture",
    ),
)
_exports(
    "ainrf.development.frontend_faults",
    (
        "FrontendDevFaultProfile",
        "build_frontend_dev_fault_middleware",
        "configured_frontend_dev_fault_profile",
        "normalize_frontend_dev_fault_profile",
    ),
)
_exports(
    "ainrf.development.frontend_profiles",
    (
        "FRONTEND_DEV_FIXTURE_VERSION",
        "FrontendDevProfile",
        "FrontendDevSeedResult",
        "FrontendDevUsers",
        "normalize_frontend_dev_profile",
        "seed_frontend_dev_profile",
    ),
)
_exports(
    "ainrf.development.frontend_worker",
    ("FrontendFixtureEngine", "FrontendFixtureWorker", "FrontendFixtureWorkerRunResult"),
)
_exports(
    "ainrf.development.instance",
    (
        "DEFAULT_DEVELOPMENT_ROOT",
        "INSTANCE_SCHEMA_VERSION",
        "FrontendDevInstance",
        "FrontendDevPorts",
        "ensure_frontend_dev_instance",
        "resolve_frontend_dev_instance",
    ),
)
_exports(
    "ainrf.development.stack",
    (
        "STACK_MANIFEST_SCHEMA_VERSION",
        "DevelopmentProcessRecord",
        "DevelopmentStack",
        "DevelopmentStackError",
        "DevelopmentStackMode",
        "DevelopmentStackStatus",
    ),
)
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    return resolve_export(name, _EXPORTS, globals())

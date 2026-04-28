from __future__ import annotations

from ainrf.environments.models import EnvironmentRegistryEntry

LOCAL_ENVIRONMENT_HOSTS = {"127.0.0.1", "localhost"}


def is_localhost_environment(environment: EnvironmentRegistryEntry) -> bool:
    return (
        environment.host in LOCAL_ENVIRONMENT_HOSTS
        and environment.proxy_jump is None
        and environment.proxy_command is None
    )


__all__ = ["LOCAL_ENVIRONMENT_HOSTS", "is_localhost_environment"]

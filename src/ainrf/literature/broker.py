"""Dramatiq broker configuration isolated from the Litefuse stack."""

from __future__ import annotations

import os
from dataclasses import dataclass

import dramatiq
from dramatiq.brokers.redis import RedisBroker


@dataclass(frozen=True, slots=True)
class LiteratureRuntimeConfig:
    redis_url: str
    redis_namespace: str
    state_root: str
    request_interval_seconds: int
    daily_source_budget: int
    daily_search_budget: int

    @classmethod
    def from_env(cls) -> "LiteratureRuntimeConfig":
        return cls(
            redis_url=os.getenv("OPENSCIENCE_LITERATURE_REDIS_URL", "redis://127.0.0.1:16379/0"),
            redis_namespace=os.getenv(
                "OPENSCIENCE_LITERATURE_REDIS_NAMESPACE", "openscience:literature"
            ),
            state_root=os.getenv("AINRF_STATE_ROOT", os.getenv("OPENSCIENCE_STATE_ROOT", ".ainrf")),
            request_interval_seconds=int(
                os.getenv("OPENSCIENCE_LITERATURE_REQUEST_INTERVAL_SECONDS", "3")
            ),
            daily_source_budget=int(os.getenv("OPENSCIENCE_LITERATURE_DAILY_SOURCE_BUDGET", "24")),
            daily_search_budget=int(os.getenv("OPENSCIENCE_LITERATURE_DAILY_SEARCH_BUDGET", "8")),
        )


def configure_broker(config: LiteratureRuntimeConfig | None = None) -> RedisBroker:
    runtime = config or LiteratureRuntimeConfig.from_env()
    broker = RedisBroker(url=runtime.redis_url, namespace=runtime.redis_namespace)
    dramatiq.set_broker(broker)
    return broker

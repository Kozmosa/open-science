from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ainrf.monitor.collectors import LocalCollector, RemoteCollector
from ainrf.monitor.models import ResourceSnapshot

if TYPE_CHECKING:
    from ainrf.environments.service import InMemoryEnvironmentService

logger = logging.getLogger(__name__)


class ResourceMonitorService:
    def __init__(self, environment_service: InMemoryEnvironmentService) -> None:
        self._environment_service = environment_service
        self._snapshots: dict[str, ResourceSnapshot] = {}
        self._task: asyncio.Task[None] | None = None
        self._local_collector = LocalCollector()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self._collect_all()
            except Exception:
                logger.exception("Resource collection failed")
            await asyncio.sleep(2)

    async def _collect_all(self) -> None:
        from ainrf.environments.probing import _ssh_container_for
        from ainrf.execution.ssh import SSHExecutor

        environments = self._environment_service.list_environments()

        for env in environments:
            try:
                if env.id == "env-localhost":
                    snapshot = await self._local_collector.collect()
                else:
                    container = _ssh_container_for(env)
                    executor = SSHExecutor(container)
                    try:
                        collector = RemoteCollector(executor, env.id, env.display_name)
                        snapshot = await collector.collect()
                    finally:
                        await executor.close()

                self._snapshots[env.id] = snapshot
            except Exception as exc:
                logger.warning("Failed to collect resources for %s: %s", env.id, exc)
                if env.id in self._snapshots:
                    old = self._snapshots[env.id]
                    self._snapshots[env.id] = ResourceSnapshot(
                        environment_id=env.id,
                        environment_name=env.display_name,
                        timestamp=datetime.now(tz=timezone.utc),
                        status="degraded",
                        gpus=old.gpus,
                        cpu=old.cpu,
                        memory=old.memory,
                        ainrf_processes=old.ainrf_processes,
                    )

    def get_snapshots(self) -> dict[str, ResourceSnapshot]:
        return self._snapshots.copy()

from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ainrf.monitor.models import CpuInfo, GpuInfo, MemoryInfo, ResourceSnapshot
from ainrf.monitor.process_tree import ProcessTreeFilter, RawProcess

if TYPE_CHECKING:
    from ainrf.execution.ssh import SSHExecutor


def parse_nvidia_smi_csv(stdout: str) -> list[GpuInfo]:
    lines = [line.strip() for line in stdout.strip().split("\n") if line.strip()]
    if not lines:
        return []

    if "name" in lines[0].lower() or "index" in lines[0].lower():
        lines = lines[1:]

    gpus: list[GpuInfo] = []
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            gpus.append(
                GpuInfo(
                    index=int(parts[0]),
                    name=parts[1],
                    utilization_percent=float(parts[2].replace("%", "").strip()),
                    memory_used_mb=int(parts[3].replace("MiB", "").strip()),
                    memory_total_mb=int(parts[4].replace("MiB", "").strip()),
                )
            )
        except (ValueError, IndexError):
            continue
    return gpus


def parse_ps_output(stdout: str) -> list[RawProcess]:
    """Parse ``ps -eo pid,ppid,pcpu,rss,etime,comm`` output.

    ``comm`` is placed last because it may contain spaces. We parse the first
    five fixed columns and join the remainder as the command name. The ``rss``
    column is resident set size in **KB**; it is converted to MB here.
    """
    lines = [line.strip() for line in stdout.strip().split("\n") if line.strip()]
    if not lines:
        return []

    if "PID" in lines[0].upper():
        lines = lines[1:]

    processes: list[RawProcess] = []
    for line in lines:
        parts = line.split()
        if len(parts) < 6:
            continue
        try:
            processes.append(
                RawProcess(
                    pid=int(parts[0]),
                    ppid=int(parts[1]),
                    cpu_percent=float(parts[2]),
                    memory_mb=int(parts[3]) // 1024,  # rss is in KB → convert to MB
                    runtime_seconds=_parse_elapsed(parts[4]),
                    name=" ".join(parts[5:]),
                )
            )
        except (ValueError, IndexError):
            continue
    return processes


def _parse_elapsed(elapsed: str) -> int:
    parts = elapsed.split("-")
    if len(parts) == 2:
        days = int(parts[0])
        time_part = parts[1]
    else:
        days = 0
        time_part = parts[0]

    time_parts = time_part.split(":")
    if len(time_parts) == 3:
        hours, minutes, seconds = int(time_parts[0]), int(time_parts[1]), int(time_parts[2])
    elif len(time_parts) == 2:
        hours, minutes, seconds = 0, int(time_parts[0]), int(time_parts[1])
    else:
        hours, minutes, seconds = 0, 0, int(time_parts[0])

    return days * 86400 + hours * 3600 + minutes * 60 + seconds


class LocalCollector:
    def __init__(self) -> None:
        self._own_pid = os.getpid()

    async def collect(self) -> ResourceSnapshot:
        gpus = await self._collect_gpu()
        processes = await self._collect_processes()
        cpu, memory = self._extract_system_stats(processes)

        filter_ = ProcessTreeFilter(root_pid=self._own_pid)
        ainrf_processes = filter_.collect_ainrf_processes(processes)

        return ResourceSnapshot(
            environment_id="env-localhost",
            environment_name="Localhost",
            timestamp=datetime.now(tz=timezone.utc),
            status="ok",
            gpus=gpus,
            cpu=cpu,
            memory=memory,
            ainrf_processes=ainrf_processes,
        )

    async def _collect_gpu(self) -> list[GpuInfo]:
        if not shutil.which("nvidia-smi"):
            return []

        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=index,name,utilization.gpu,memory.used,memory.total",
            "--format=csv",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
        return parse_nvidia_smi_csv(stdout.decode())

    async def _collect_processes(self) -> list[RawProcess]:
        proc = await asyncio.create_subprocess_exec(
            "ps", "-eo", "pid,ppid,pcpu,rss,etime,comm",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
        return parse_ps_output(stdout.decode())

    def _extract_system_stats(self, processes: list[RawProcess]) -> tuple[CpuInfo, MemoryInfo]:
        core_count = os.cpu_count() or 1
        total_cpu = sum(p.cpu_percent for p in processes)
        # pcpu is percent of one CPU; dividing by core_count normalises to 0–100 % system load.
        system_percent = round(total_cpu / core_count, 1)
        memory = self._read_meminfo()
        return CpuInfo(percent=system_percent, core_count=core_count), memory

    def _read_meminfo(self) -> MemoryInfo:
        try:
            with open("/proc/meminfo") as f:
                content = f.read()
            total_kb = 0
            available_kb = 0
            for line in content.split("\n"):
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    available_kb = int(line.split()[1])
            used_kb = total_kb - available_kb
            total_mb = total_kb // 1024
            used_mb = used_kb // 1024
            percent = round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0.0
            return MemoryInfo(used_mb=used_mb, total_mb=total_mb, percent=percent)
        except Exception:
            return MemoryInfo(used_mb=0, total_mb=0, percent=0.0)


class RemoteCollector:
    def __init__(self, executor: SSHExecutor, environment_id: str, environment_name: str) -> None:
        self._executor = executor
        self._environment_id = environment_id
        self._environment_name = environment_name

    async def collect(self) -> ResourceSnapshot:
        gpus: list[GpuInfo] = []
        processes: list[RawProcess] = []
        status = "ok"

        try:
            gpu_result = await self._executor.run_command(
                "nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv",
                timeout=3,
            )
            if gpu_result.exit_code == 0:
                gpus = parse_nvidia_smi_csv(gpu_result.stdout)
        except Exception:
            pass

        try:
            ps_result = await self._executor.run_command(
                "ps -eo pid,ppid,pcpu,rss,etime,comm",
                timeout=3,
            )
            if ps_result.exit_code == 0:
                processes = parse_ps_output(ps_result.stdout)
        except Exception:
            status = "unavailable"

        ainrf_processes = [p for p in processes if p.name in ProcessTreeFilter.WHITELIST]
        ainrf_processes.sort(key=lambda p: p.cpu_percent, reverse=True)

        core_count = await self._collect_core_count()
        total_cpu = sum(p.cpu_percent for p in processes)
        system_percent = round(total_cpu / core_count, 1)
        memory = await self._collect_memory()

        return ResourceSnapshot(
            environment_id=self._environment_id,
            environment_name=self._environment_name,
            timestamp=datetime.now(tz=timezone.utc),
            status=status,
            gpus=gpus,
            cpu=CpuInfo(percent=system_percent, core_count=core_count),
            memory=memory,
            ainrf_processes=ainrf_processes,
        )

    async def _collect_core_count(self) -> int:
        try:
            result = await self._executor.run_command(
                "nproc",
                timeout=3,
            )
            if result.exit_code == 0:
                return int(result.stdout.strip())
        except Exception:
            pass
        return 1

    async def _collect_memory(self) -> MemoryInfo:
        try:
            result = await self._executor.run_command(
                "free -m | awk 'NR==2{print $3,$2}'",
                timeout=3,
            )
            if result.exit_code == 0:
                parts = result.stdout.strip().split()
                if len(parts) == 2:
                    used_mb = int(parts[0])
                    total_mb = int(parts[1])
                    percent = round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0.0
                    return MemoryInfo(used_mb=used_mb, total_mb=total_mb, percent=percent)
        except Exception:
            pass
        return MemoryInfo(used_mb=0, total_mb=0, percent=0.0)

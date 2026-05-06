from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GpuInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    name: str
    utilization_percent: float
    memory_used_mb: int
    memory_total_mb: int


class CpuInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    percent: float
    core_count: int = 1


class MemoryInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    used_mb: int
    total_mb: int
    percent: float


class ProcessInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pid: int
    name: str
    cpu_percent: float
    memory_mb: int
    runtime_seconds: int


class ResourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment_id: str
    environment_name: str
    timestamp: datetime
    status: Literal["ok", "degraded", "unavailable"] = "ok"
    gpus: list[GpuInfo] = Field(default_factory=list)
    cpu: CpuInfo
    memory: MemoryInfo
    ainrf_processes: list[ProcessInfo] = Field(default_factory=list)


class ResourcesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ResourceSnapshot] = Field(default_factory=list)

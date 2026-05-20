from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawProcess:
    pid: int
    ppid: int
    name: str
    cpu_percent: float
    memory_mb: int
    runtime_seconds: int


class ProcessTreeFilter:
    def __init__(self, root_pid: int) -> None:
        self.root_pid = root_pid

    @staticmethod
    def find_ainrf_roots(processes: list[RawProcess]) -> list[int]:
        """Return PIDs of processes whose command line contains 'ainrf'."""
        return [p.pid for p in processes if "ainrf" in p.name]

    def collect_descendants(self, all_processes: list[RawProcess]) -> list[RawProcess]:
        pid_to_ppid = {p.pid: p.ppid for p in all_processes}
        descendant_pids = self._collect_descendants(pid_to_ppid, self.root_pid)

        return sorted(
            (p for p in all_processes if p.pid in descendant_pids),
            key=lambda p: p.cpu_percent,
            reverse=True,
        )

    def _collect_descendants(self, pid_to_ppid: dict[int, int], root: int) -> set[int]:
        descendants: set[int] = {root}
        changed = True
        while changed:
            changed = False
            for pid, ppid in pid_to_ppid.items():
                if ppid in descendants and pid not in descendants:
                    descendants.add(pid)
                    changed = True
        return descendants

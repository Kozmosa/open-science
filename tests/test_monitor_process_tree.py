from ainrf.monitor.process_tree import ProcessTreeFilter, RawProcess


class TestProcessTreeFilter:
    def test_collect_descendants(self):
        processes = [
            RawProcess(
                pid=1, ppid=0, name="systemd", cpu_percent=0.1, memory_mb=10, runtime_seconds=100
            ),
            RawProcess(
                pid=100, ppid=1, name="ainrf", cpu_percent=5.0, memory_mb=100, runtime_seconds=50
            ),
            RawProcess(
                pid=101, ppid=100, name="python", cpu_percent=3.0, memory_mb=80, runtime_seconds=40
            ),
            RawProcess(
                pid=102, ppid=100, name="node", cpu_percent=2.0, memory_mb=60, runtime_seconds=30
            ),
            RawProcess(
                pid=103, ppid=101, name="uv", cpu_percent=1.0, memory_mb=20, runtime_seconds=20
            ),
            RawProcess(
                pid=200, ppid=1, name="sshd", cpu_percent=0.5, memory_mb=15, runtime_seconds=60
            ),
        ]
        filter_ = ProcessTreeFilter(root_pid=100)
        result = filter_.collect_descendants(processes)
        pids = {p.pid for p in result}
        assert pids == {100, 101, 102, 103}

    def test_excludes_non_descendants(self):
        processes = [
            RawProcess(
                pid=1, ppid=0, name="systemd", cpu_percent=0.1, memory_mb=10, runtime_seconds=100
            ),
            RawProcess(
                pid=100, ppid=1, name="ainrf", cpu_percent=5.0, memory_mb=100, runtime_seconds=50
            ),
            RawProcess(
                pid=500, ppid=1, name="node", cpu_percent=0.5, memory_mb=20, runtime_seconds=60
            ),
            RawProcess(
                pid=501, ppid=500, name="code-server", cpu_percent=1.0, memory_mb=50, runtime_seconds=30
            ),
        ]
        filter_ = ProcessTreeFilter(root_pid=100)
        result = filter_.collect_descendants(processes)
        pids = {p.pid for p in result}
        assert pids == {100}

    def test_find_ainrf_roots_by_args(self):
        processes = [
            RawProcess(
                pid=1, ppid=0, name="/sbin/init", cpu_percent=0.1, memory_mb=10, runtime_seconds=100
            ),
            RawProcess(
                pid=100, ppid=1, name="uv run ainrf monitor", cpu_percent=5.0, memory_mb=100, runtime_seconds=50
            ),
            RawProcess(
                pid=101, ppid=100, name="python -m ainrf", cpu_percent=3.0, memory_mb=80, runtime_seconds=40
            ),
            RawProcess(
                pid=200, ppid=1, name="/usr/bin/node /path/to/some-server.js", cpu_percent=2.0, memory_mb=60, runtime_seconds=30
            ),
        ]
        roots = ProcessTreeFilter.find_ainrf_roots(processes)
        assert roots == [100, 101]

    def test_collect_descendants_from_multiple_roots(self):
        processes = [
            RawProcess(
                pid=100, ppid=1, name="uv run ainrf monitor", cpu_percent=5.0, memory_mb=100, runtime_seconds=50
            ),
            RawProcess(
                pid=101, ppid=100, name="python", cpu_percent=3.0, memory_mb=80, runtime_seconds=40
            ),
            RawProcess(
                pid=200, ppid=1, name="python -m ainrf.worker", cpu_percent=2.0, memory_mb=60, runtime_seconds=30
            ),
            RawProcess(
                pid=201, ppid=200, name="node worker.js", cpu_percent=1.0, memory_mb=40, runtime_seconds=20
            ),
            RawProcess(
                pid=300, ppid=1, name="code-server", cpu_percent=10.0, memory_mb=500, runtime_seconds=120
            ),
        ]
        ainrf_roots = ProcessTreeFilter.find_ainrf_roots(processes)
        descendant_pids: set[int] = set()
        for root_pid in ainrf_roots:
            tree = ProcessTreeFilter(root_pid=root_pid)
            pid_to_ppid = {p.pid: p.ppid for p in processes}
            descendant_pids.update(tree._collect_descendants(pid_to_ppid, root_pid))

        # 100,101 from first tree; 200,201 from second tree; 300 excluded
        assert descendant_pids == {100, 101, 200, 201}

    def test_empty_processes(self):
        filter_ = ProcessTreeFilter(root_pid=100)
        result = filter_.collect_descendants([])
        assert result == []

    def test_find_ainrf_roots_empty(self):
        processes = [
            RawProcess(
                pid=1, ppid=0, name="/sbin/init", cpu_percent=0.1, memory_mb=10, runtime_seconds=100
            ),
        ]
        assert ProcessTreeFilter.find_ainrf_roots(processes) == []

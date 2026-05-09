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
        result = filter_.collect_ainrf_processes(processes)
        pids = {p.pid for p in result}
        assert pids == {100, 101, 102, 103}

    def test_whitelist_includes_non_descendants(self):
        processes = [
            RawProcess(
                pid=1, ppid=0, name="systemd", cpu_percent=0.1, memory_mb=10, runtime_seconds=100
            ),
            RawProcess(
                pid=100, ppid=1, name="ainrf", cpu_percent=5.0, memory_mb=100, runtime_seconds=50
            ),
            RawProcess(
                pid=500, ppid=1, name="tmux", cpu_percent=0.5, memory_mb=20, runtime_seconds=60
            ),
            RawProcess(
                pid=501,
                ppid=500,
                name="code-server",
                cpu_percent=1.0,
                memory_mb=50,
                runtime_seconds=30,
            ),
        ]
        filter_ = ProcessTreeFilter(root_pid=100)
        result = filter_.collect_ainrf_processes(processes)
        pids = {p.pid for p in result}
        assert pids == {100, 500, 501}

    def test_empty_processes(self):
        filter_ = ProcessTreeFilter(root_pid=100)
        result = filter_.collect_ainrf_processes([])
        assert result == []

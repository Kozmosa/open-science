from ainrf.monitor.collectors import parse_nvidia_smi_csv, parse_ps_output


class TestParseNvidiaSmi:
    def test_parse_valid_output(self):
        stdout = "0, NVIDIA GeForce RTX 4090, 45 %, 8192 MiB, 24576 MiB\n"
        result = parse_nvidia_smi_csv(stdout)
        assert len(result) == 1
        assert result[0].index == 0
        assert result[0].name == "NVIDIA GeForce RTX 4090"
        assert result[0].utilization_percent == 45.0
        assert result[0].memory_used_mb == 8192
        assert result[0].memory_total_mb == 24576

    def test_parse_empty_output(self):
        result = parse_nvidia_smi_csv("")
        assert result == []

    def test_parse_header_only(self):
        stdout = "index, name, utilization.gpu [%], memory.used [MiB], memory.total [MiB]\n"
        result = parse_nvidia_smi_csv(stdout)
        assert result == []


class TestParsePsOutput:
    def test_parse_valid_output(self):
        # Format: pid,ppid,pcpu,rss,etime,comm  (comm last, may contain spaces)
        stdout = (
            "PID PPID %CPU RSS ELAPSED COMM\n"
            "1 0 0.1 10240 01:23:45 systemd\n"
            "100 1 5.0 524288 00:10:30 ainrf\n"
        )
        result = parse_ps_output(stdout)
        assert len(result) == 2
        assert result[0].pid == 1
        assert result[0].name == "systemd"
        assert result[0].memory_mb == 10
        assert result[1].pid == 100
        assert result[1].cpu_percent == 5.0
        assert result[1].memory_mb == 512

    def test_parse_comm_with_spaces(self):
        # comm is the last column and may contain spaces
        stdout = (
            "PID PPID %CPU RSS ELAPSED COMM\n"
            "1 0 0.1 10240 01:23:45 systemd\n"
            "200 1 2.5 20480 00:05:00 code server\n"
        )
        result = parse_ps_output(stdout)
        assert len(result) == 2
        assert result[1].pid == 200
        assert result[1].name == "code server"
        assert result[1].cpu_percent == 2.5
        assert result[1].memory_mb == 20

    def test_parse_empty_output(self):
        result = parse_ps_output("")
        assert result == []

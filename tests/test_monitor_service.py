from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from ainrf.monitor.models import CpuInfo, MemoryInfo, ResourceSnapshot
from ainrf.monitor.service import ResourceMonitorService


class TestResourceMonitorService:
    @pytest.fixture
    def mock_env_service(self):
        service = MagicMock()
        service.list_environments.return_value = []
        return service

    def test_get_snapshots_empty(self, mock_env_service):
        service = ResourceMonitorService(mock_env_service)
        assert service.get_snapshots() == {}

    def test_get_snapshots_returns_copy(self, mock_env_service):
        service = ResourceMonitorService(mock_env_service)
        snapshot = ResourceSnapshot(
            environment_id="test",
            environment_name="Test",
            timestamp=datetime.now(tz=timezone.utc),
            cpu=CpuInfo(percent=10.0, core_count=4),
            memory=MemoryInfo(used_mb=1000, total_mb=8000, percent=12.5),
        )
        service._snapshots = {"test": snapshot}
        result = service.get_snapshots()
        assert "test" in result
        assert result["test"].environment_id == "test"

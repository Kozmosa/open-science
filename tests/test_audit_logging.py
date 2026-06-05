"""Tests for ainrf.security.audit and ainrf.security.sensitive_paths."""

from __future__ import annotations

import structlog

from ainrf.security.audit import audit_event
from ainrf.security.sensitive_paths import check_path_access, is_sensitive_path


class TestAuditEvent:
    """Tests for audit_event()."""

    def test_emits_structured_event(self) -> None:
        with structlog.testing.capture_logs() as logs:
            audit_event("test.event", severity="info", user_id="alice")
        assert len(logs) == 1
        entry = logs[0]
        assert entry["event"] == "test.event"
        assert entry["severity"] == "info"
        assert entry["user_id"] == "alice"
        assert entry["component"] == "audit"

    def test_default_severity_is_info(self) -> None:
        with structlog.testing.capture_logs() as logs:
            audit_event("test.default")
        assert logs[0]["severity"] == "info"

    def test_custom_severity_critical(self) -> None:
        with structlog.testing.capture_logs() as logs:
            audit_event("test.critical", severity="critical")
        assert logs[0]["severity"] == "critical"

    def test_extra_kwargs_propagated(self) -> None:
        with structlog.testing.capture_logs() as logs:
            audit_event("test.extra", client_ip="10.0.0.1", role="admin")
        assert logs[0]["client_ip"] == "10.0.0.1"
        assert logs[0]["role"] == "admin"


class TestIsSensitivePath:
    """Tests for is_sensitive_path()."""

    def test_env_file(self) -> None:
        ok, name = is_sensitive_path("/home/user/project/.env")
        assert ok is True
        assert name is not None

    def test_pem_file(self) -> None:
        ok, name = is_sensitive_path("/etc/ssl/cert.pem")
        assert ok is True

    def test_id_rsa(self) -> None:
        ok, name = is_sensitive_path("/home/user/.ssh/id_rsa")
        assert ok is True

    def test_sqlite(self) -> None:
        ok, name = is_sensitive_path("/data/app.sqlite")
        assert ok is True

    def test_etc_passwd(self) -> None:
        ok, name = is_sensitive_path("/etc/passwd")
        assert ok is True

    def test_normal_file_not_sensitive(self) -> None:
        ok, name = is_sensitive_path("/home/user/project/main.py")
        assert ok is False
        assert name is None

    def test_normal_directory_not_sensitive(self) -> None:
        ok, name = is_sensitive_path("/workspace/src/index.ts")
        assert ok is False

    def test_db_extension(self) -> None:
        ok, name = is_sensitive_path("/var/data/config.db")
        assert ok is True


class TestCheckPathAccess:
    """Tests for check_path_access()."""

    def test_sensitive_path_emits_audit(self) -> None:
        with structlog.testing.capture_logs() as logs:
            check_path_access("/home/user/.env", user_id="alice")
        assert len(logs) == 1
        assert logs[0]["event"] == "files.sensitive_path_access"
        assert logs[0]["severity"] == "high"
        assert logs[0]["user_id"] == "alice"
        # Only basename logged, not full path
        assert logs[0]["path"] == ".env"

    def test_normal_path_no_audit(self) -> None:
        with structlog.testing.capture_logs() as logs:
            check_path_access("/home/user/src/main.py")
        assert len(logs) == 0

    def test_includes_environment_id(self) -> None:
        with structlog.testing.capture_logs() as logs:
            check_path_access("/etc/shadow", environment_id="env-prod")
        assert logs[0]["environment_id"] == "env-prod"

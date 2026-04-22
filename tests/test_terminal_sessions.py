from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from ainrf.environments.service import InMemoryEnvironmentService
from ainrf.terminal.attachments import (
    TerminalAttachmentAuthorizationError,
    TerminalAttachmentBroker,
    TerminalAttachmentExpiredError,
)
from ainrf.terminal.models import (
    TerminalAttachmentTarget,
    TerminalMuxKind,
    TerminalSessionStatus,
    UserEnvironmentBinding,
    utc_now,
)
from ainrf.terminal.pty import TERMINAL_LOCAL_TARGET_KIND
from ainrf.terminal.sessions import SessionManager
from ainrf.terminal.tmux import TmuxAdapter


def make_manager(
    tmp_path: Path, *, user_id: str = "daemon-user"
) -> tuple[SessionManager, InMemoryEnvironmentService]:
    environment_service = InMemoryEnvironmentService()
    manager = SessionManager(
        state_root=tmp_path,
        environment_service=environment_service,
        tmux_adapter=TmuxAdapter(tmp_path),
        default_shell="/bin/bash",
        user_id=user_id,
    )
    return manager, environment_service


def test_binding_upsert_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager, environment_service = make_manager(tmp_path)
    environment = environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
        default_workdir="/workspace/project",
    )
    adapter = manager._tmux_adapter
    monkeypatch.setattr(adapter, "ensure_personal_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        adapter, "build_attach_command", lambda *args, **kwargs: ("tmux", "attach-session")
    )

    manager.ensure_personal_session(environment, "/workspace/project")
    first_binding = manager._load_binding(environment.id)
    assert first_binding is not None

    manager.ensure_personal_session(environment, "/workspace/project")
    second_binding = manager._load_binding(environment.id)
    assert second_binding is not None

    assert first_binding.binding_id == second_binding.binding_id
    assert first_binding.mux_kind.value == "tmux"


def test_session_name_generation_is_stable(tmp_path: Path) -> None:
    manager, environment_service = make_manager(tmp_path)
    environment = environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )

    expected = f"ainrf:u:{manager.user_id}:e:{environment.id}:personal"
    assert manager.session_name_for(environment.id) == expected
    assert manager.session_name_for(environment.id) == expected


def test_agent_session_name_generation_is_stable(tmp_path: Path) -> None:
    manager, environment_service = make_manager(tmp_path)
    environment = environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )

    expected = f"ainrf:u:{manager.user_id}:e:{environment.id}:agent"
    assert manager.agent_session_name_for(environment.id) == expected
    assert manager.agent_session_name_for(environment.id) == expected


def test_tmux_adapter_builds_local_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = TmuxAdapter(tmp_path)
    environment = InMemoryEnvironmentService().create_environment(
        alias="localhost-2",
        display_name="Localhost 2",
        host="127.0.0.1",
    )
    binding = manager_binding(environment.id)
    captured: list[tuple[str, ...]] = []

    monkeypatch.setattr(adapter, "has_session", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        adapter,
        "_run_local_command",
        lambda command: (
            captured.append(command) or SimpleNamespace(returncode=0, stdout="", stderr="")
        ),
    )

    adapter.ensure_personal_session(binding, environment, "session-1")

    assert captured == [
        (
            "tmux",
            "new-session",
            "-d",
            "-s",
            "session-1",
            "-c",
            "/workspace/project",
            "/bin/bash",
            "-l",
        )
    ]
    assert adapter.build_attach_command(binding, environment, "session-1") == (
        "tmux",
        "attach-session",
        "-t",
        "session-1",
    )


def test_tmux_adapter_builds_remote_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = TmuxAdapter(tmp_path)
    environment = InMemoryEnvironmentService().create_environment(
        alias="remote-lab",
        display_name="Remote Lab",
        host="gpu.example.com",
        port=2222,
        user="researcher",
        identity_file="/keys/id_ed25519",
        proxy_jump="bastion",
        proxy_command="ssh -W %h:%p bastion",
        ssh_options={"StrictHostKeyChecking": "no", "ServerAliveInterval": "30"},
    )
    binding = manager_binding(environment.id, remote_login_user="researcher")
    captured: list[tuple[str, str]] = []
    home_dir = tmp_path / "home"
    (home_dir / ".ssh").mkdir(parents=True)
    (home_dir / ".ssh" / "config").write_text("Host *\n", encoding="utf-8")

    monkeypatch.setattr(adapter, "has_session", lambda *args, **kwargs: False)
    monkeypatch.setattr("ainrf.terminal.tmux.Path.home", lambda: home_dir)
    monkeypatch.setattr(
        adapter,
        "_run_remote_command",
        lambda env, user, remote_command: (
            captured.append((user, remote_command))
            or SimpleNamespace(returncode=0, stdout="", stderr="")
        ),
    )

    adapter.ensure_personal_session(binding, environment, "session-1")

    assert captured == [
        (
            "researcher",
            "command -v tmux >/dev/null 2>&1 || { echo __AINRF_REMOTE_TMUX_MISSING__; exit 127; }; "
            "tmux new-session -d -s session-1 -c /workspace/project /bin/bash -l",
        )
    ]
    assert adapter.build_attach_command(binding, environment, "session-1") == (
        "ssh",
        "-tt",
        "-F",
        str(home_dir / ".ssh" / "config"),
        "-p",
        "2222",
        "-i",
        "/keys/id_ed25519",
        "-o",
        "ProxyJump=bastion",
        "-o",
        "ProxyCommand=ssh -W %h:%p bastion",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "StrictHostKeyChecking=no",
        "researcher@gpu.example.com",
        "exec tmux attach-session -t session-1",
    )


def test_tmux_adapter_builds_local_task_window_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = TmuxAdapter(tmp_path)
    environment = InMemoryEnvironmentService().create_environment(
        alias="localhost-2",
        display_name="Localhost 2",
        host="127.0.0.1",
    )
    binding = manager_binding(environment.id)
    captured: list[tuple[str, ...]] = []

    def fake_run_local(command: tuple[str, ...]) -> SimpleNamespace:
        captured.append(command)
        if command[:3] == ("tmux", "new-window", "-P"):
            return SimpleNamespace(returncode=0, stdout="@3\ttrain-task\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(adapter, "_run_local_command", fake_run_local)
    monkeypatch.setattr(adapter, "has_session", lambda *args, **kwargs: False)

    adapter.ensure_agent_session(binding, environment, "agent-1")
    window = adapter.create_window(
        binding,
        environment,
        "agent-1",
        window_name="train-task",
        working_directory="/workspace/project",
        command="python train.py",
    )

    assert captured == [
        (
            "tmux",
            "new-session",
            "-d",
            "-s",
            "agent-1",
            "-c",
            "/workspace/project",
            "/bin/bash",
            "-l",
        ),
        ("tmux", "set-option", "-t", "agent-1", "remain-on-exit", "on"),
        (
            "tmux",
            "new-window",
            "-P",
            "-F",
            "#{window_id}\t#{window_name}",
            "-t",
            "agent-1",
            "-n",
            "train-task",
            "-c",
            "/workspace/project",
            "exec /bin/bash -lc 'python train.py'",
        ),
    ]
    assert window.window_id == "@3"
    assert window.window_name == "train-task"
    assert adapter.build_window_attach_command(binding, environment, "agent-1", "@3") == (
        "tmux",
        "attach-session",
        "-t",
        "agent-1",
        ";",
        "select-window",
        "-t",
        "@3",
    )


def test_tmux_adapter_builds_remote_task_window_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = TmuxAdapter(tmp_path)
    home_dir = tmp_path / "home"
    monkeypatch.setattr("ainrf.terminal.tmux.Path.home", lambda: home_dir)
    environment = InMemoryEnvironmentService().create_environment(
        alias="remote-lab",
        display_name="Remote Lab",
        host="gpu.example.com",
        port=2222,
        user="researcher",
        identity_file="/keys/id_ed25519",
        ssh_options={"StrictHostKeyChecking": "no"},
    )
    binding = manager_binding(environment.id, remote_login_user="researcher")
    captured: list[tuple[str, str]] = []

    def fake_remote_command(
        env: object, remote_login_user: str, remote_command: str
    ) -> SimpleNamespace:
        _ = env
        captured.append((remote_login_user, remote_command))
        if "new-window" in remote_command:
            return SimpleNamespace(returncode=0, stdout="@7\ttrain-task\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(adapter, "has_session", lambda *args, **kwargs: False)
    monkeypatch.setattr(adapter, "_run_remote_command", fake_remote_command)

    adapter.ensure_agent_session(binding, environment, "agent-1")
    adapter.create_window(
        binding,
        environment,
        "agent-1",
        window_name="train-task",
        working_directory="/workspace/project",
        command="python train.py",
    )
    adapter.send_window_interrupt(binding, environment, "@7")

    assert captured == [
        (
            "researcher",
            "command -v tmux >/dev/null 2>&1 || { echo __AINRF_REMOTE_TMUX_MISSING__; exit 127; }; "
            "tmux new-session -d -s agent-1 -c /workspace/project /bin/bash -l",
        ),
        (
            "researcher",
            "command -v tmux >/dev/null 2>&1 || { echo __AINRF_REMOTE_TMUX_MISSING__; exit 127; }; "
            "tmux set-option -t agent-1 remain-on-exit on",
        ),
        (
            "researcher",
            "command -v tmux >/dev/null 2>&1 || { echo __AINRF_REMOTE_TMUX_MISSING__; exit 127; }; "
            "tmux new-window -P -F '#{window_id}\t#{window_name}' -t agent-1 -n train-task -c "
            "/workspace/project 'exec /bin/bash -lc '\"'\"'python train.py'\"'\"''",
        ),
        (
            "researcher",
            "command -v tmux >/dev/null 2>&1 || { echo __AINRF_REMOTE_TMUX_MISSING__; exit 127; }; "
            "tmux send-keys -t @7 C-c",
        ),
    ]
    assert adapter.build_window_attach_command(binding, environment, "agent-1", "@7") == (
        "ssh",
        "-tt",
        "-p",
        "2222",
        "-i",
        "/keys/id_ed25519",
        "-o",
        "StrictHostKeyChecking=no",
        "researcher@gpu.example.com",
        "exec tmux attach-session -t agent-1 ';' select-window -t @7",
    )


def test_terminal_attachment_broker_validates_token_and_expiry(tmp_path: Path) -> None:
    broker = TerminalAttachmentBroker()
    attachment = broker.create_attachment("http://testserver/", attachment_target(tmp_path))

    with pytest.raises(TerminalAttachmentAuthorizationError):
        broker.open_runtime(attachment.attachment_id, "wrong-token")

    broker._attachments[attachment.attachment_id].expires_at = attachment.expires_at - timedelta(
        minutes=10
    )
    with pytest.raises(TerminalAttachmentExpiredError):
        broker.open_runtime(attachment.attachment_id, attachment.token)


def test_detach_only_closes_bridge_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    broker = TerminalAttachmentBroker()
    attachment = broker.create_attachment("http://testserver/", attachment_target(tmp_path))
    stopped: list[object] = []
    runtime = object()
    broker._runtimes[attachment.attachment_id] = runtime  # type: ignore[assignment]
    monkeypatch.setattr(
        "ainrf.terminal.attachments.stop_terminal_bridge",
        lambda current_runtime: stopped.append(current_runtime),
    )

    detached = broker.detach_attachment(attachment.attachment_id)

    assert detached is not None
    assert stopped == [runtime]


def test_reset_kills_and_recreates_personal_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = TmuxAdapter(tmp_path)
    environment = InMemoryEnvironmentService().create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )
    binding = manager_binding(environment.id)
    calls: list[str] = []

    monkeypatch.setattr(adapter, "has_session", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        adapter,
        "kill_session",
        lambda *args, **kwargs: calls.append("kill"),
    )
    monkeypatch.setattr(
        adapter,
        "ensure_personal_session",
        lambda *args, **kwargs: calls.append("ensure"),
    )

    adapter.reset_personal_session(binding, environment, "session-1")

    assert calls == ["kill", "ensure"]


def test_reconcile_restores_running_state_from_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, environment_service = make_manager(tmp_path)
    environment = environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
        default_workdir="/workspace/project",
    )
    adapter = manager._tmux_adapter
    monkeypatch.setattr(adapter, "ensure_personal_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        adapter, "build_attach_command", lambda *args, **kwargs: ("tmux", "attach-session")
    )

    manager.ensure_personal_session(environment, "/workspace/project")

    restored_manager = SessionManager(
        state_root=tmp_path,
        environment_service=environment_service,
        tmux_adapter=TmuxAdapter(tmp_path),
        default_shell="/bin/bash",
        user_id=manager.user_id,
    )
    monkeypatch.setattr(restored_manager._tmux_adapter, "has_session", lambda *args, **kwargs: True)

    restored_manager.reconcile()
    record = restored_manager.get_session_record(environment, "/workspace/project")

    assert record.status is TerminalSessionStatus.RUNNING
    assert record.binding_id is not None
    assert record.session_name == manager.session_name_for(environment.id)


def test_session_names_include_app_user_namespace(tmp_path: Path) -> None:
    manager, environment_service = make_manager(tmp_path)
    environment = environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
    )

    assert manager.session_name_for("browser-a", environment.id) != manager.session_name_for(
        "browser-b",
        environment.id,
    )
    assert manager.agent_session_name_for(
        "browser-a", environment.id
    ) != manager.agent_session_name_for(
        "browser-b",
        environment.id,
    )


def test_first_real_app_user_claims_legacy_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, environment_service = make_manager(tmp_path)
    environment = environment_service.create_environment(
        alias="gpu-lab",
        display_name="GPU Lab",
        host="gpu.example.com",
        default_workdir="/workspace/project",
    )
    adapter = manager._tmux_adapter
    monkeypatch.setattr(adapter, "ensure_personal_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        adapter, "build_attach_command", lambda *args, **kwargs: ("tmux", "attach-session")
    )

    manager.ensure_personal_session(environment, "/workspace/project")
    legacy_binding = manager._load_binding(environment.id)
    assert legacy_binding is not None

    record, _ = manager.ensure_personal_session("browser-user", environment, "/workspace/project")
    claimed_binding = manager._load_binding("browser-user", environment.id)

    assert claimed_binding is not None
    assert claimed_binding.binding_id == legacy_binding.binding_id
    assert claimed_binding.user_id == "browser-user"
    assert record.binding_id == legacy_binding.binding_id
    assert record.session_name == f"ainrf:u:browser-user:e:{environment.id}:personal"


def manager_binding(
    environment_id: str, *, remote_login_user: str = "root"
) -> UserEnvironmentBinding:
    timestamp = utc_now()
    return UserEnvironmentBinding(
        binding_id="binding-1",
        user_id="daemon-user",
        environment_id=environment_id,
        remote_login_user=remote_login_user,
        default_shell="/bin/bash",
        default_workdir="/workspace/project",
        mux_kind=TerminalMuxKind.TMUX,
        created_at=timestamp,
        updated_at=timestamp,
    )


def attachment_target(tmp_path: Path) -> TerminalAttachmentTarget:
    return TerminalAttachmentTarget(
        binding_id="binding-1",
        session_id="ainrf:u:daemon-user:e:env-1:personal",
        session_name="ainrf:u:daemon-user:e:env-1:personal",
        user_id="daemon-user",
        environment_id="env-1",
        environment_alias="gpu-lab",
        target_kind=TERMINAL_LOCAL_TARGET_KIND,
        working_directory="/workspace/project",
        attach_command=("tmux", "attach-session", "-t", "ainrf:u:daemon-user:e:env-1:personal"),
        spawn_working_directory=tmp_path,
    )

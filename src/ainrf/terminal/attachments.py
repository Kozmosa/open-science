from __future__ import annotations

from dataclasses import replace
from secrets import token_urlsafe
from uuid import uuid4

from ainrf.terminal.models import (
    TerminalAttachment,
    TerminalAttachmentTarget,
    TerminalSessionRecord,
    utc_now,
)
from ainrf.terminal.pty import (
    TERMINAL_ATTACHMENT_TOKEN_TTL,
    TerminalBridgeRuntime,
    build_attachment_ws_url,
    start_terminal_bridge,
    stop_terminal_bridge,
)


class TerminalAttachmentError(RuntimeError):
    pass


class TerminalAttachmentNotFoundError(TerminalAttachmentError):
    pass


class TerminalAttachmentAuthorizationError(TerminalAttachmentError):
    pass


class TerminalAttachmentExpiredError(TerminalAttachmentError):
    pass


class TerminalAttachmentConflictError(TerminalAttachmentError):
    pass


class TerminalAttachmentBroker:
    def __init__(self) -> None:
        self._attachments: dict[str, TerminalAttachment] = {}
        self._runtimes: dict[str, TerminalBridgeRuntime] = {}

    def create_attachment(
        self,
        api_base_url: str,
        target: TerminalAttachmentTarget,
    ) -> TerminalAttachment:
        self._purge_expired()
        now = utc_now()
        attachment_id = str(uuid4())
        token = token_urlsafe(24)
        attachment = TerminalAttachment(
            attachment_id=attachment_id,
            token=token,
            session_id=target.session_id,
            binding_id=target.binding_id,
            session_name=target.session_name,
            user_id=target.user_id,
            environment_id=target.environment_id,
            environment_alias=target.environment_alias,
            target_kind=target.target_kind,
            working_directory=target.working_directory,
            created_at=now,
            expires_at=now + TERMINAL_ATTACHMENT_TOKEN_TTL,
            attach_command=target.attach_command,
            spawn_working_directory=target.spawn_working_directory,
            readonly=target.readonly,
            mode=target.mode,
            window_id=target.window_id,
            window_name=target.window_name,
            owner_user_id=target.owner_user_id,
            task_id=target.task_id,
            binding_status=target.binding_status,
        )
        self._attachments[attachment_id] = attachment
        return attachment

    def attach_record(
        self,
        session: TerminalSessionRecord,
        attachment: TerminalAttachment,
        api_base_url: str,
    ) -> TerminalSessionRecord:
        return replace(
            session,
            terminal_ws_url=build_attachment_ws_url(
                api_base_url,
                attachment.attachment_id,
                attachment.token,
            ),
            attachment_id=attachment.attachment_id,
            attachment_expires_at=attachment.expires_at,
        )

    def open_runtime(
        self, attachment_id: str, token: str
    ) -> tuple[TerminalAttachment, TerminalBridgeRuntime]:
        attachment = self._validate_attachment(attachment_id, token)
        if attachment_id in self._runtimes:
            raise TerminalAttachmentConflictError("terminal attachment is already connected")
        runtime = start_terminal_bridge(
            attachment.attach_command,
            attachment.spawn_working_directory,
        )
        self._runtimes[attachment_id] = runtime
        return attachment, runtime

    def detach_attachment(self, attachment_id: str | None) -> TerminalAttachment | None:
        if attachment_id is None:
            return None
        attachment = self._attachments.pop(attachment_id, None)
        runtime = self._runtimes.pop(attachment_id, None)
        stop_terminal_bridge(runtime)
        return attachment

    def close_runtime(self, attachment_id: str) -> None:
        runtime = self._runtimes.pop(attachment_id, None)
        stop_terminal_bridge(runtime)
        self._attachments.pop(attachment_id, None)

    def shutdown(self) -> None:
        attachment_ids = list(self._attachments.keys())
        for attachment_id in attachment_ids:
            self.detach_attachment(attachment_id)

    def _validate_attachment(self, attachment_id: str, token: str) -> TerminalAttachment:
        attachment = self._attachments.get(attachment_id)
        if attachment is None:
            raise TerminalAttachmentNotFoundError("terminal attachment not found")
        if attachment.token != token:
            raise TerminalAttachmentAuthorizationError("invalid terminal attachment token")
        if attachment.expires_at <= utc_now():
            self.detach_attachment(attachment_id)
            raise TerminalAttachmentExpiredError("terminal attachment expired")
        return attachment

    def _purge_expired(self) -> None:
        now = utc_now()
        expired_ids = [
            attachment_id
            for attachment_id, attachment in self._attachments.items()
            if attachment.expires_at <= now
        ]
        for attachment_id in expired_ids:
            self.detach_attachment(attachment_id)

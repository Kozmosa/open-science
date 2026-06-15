"""Token usage and streaming output edge cases."""

from __future__ import annotations

import asyncio
import json

import pytest

from ainrf.agentic_researcher.models import (
    TaskOutputEvent,
    TaskStatus,
)
from tests.testutil import make_researcher

pytestmark = [pytest.mark.unit, pytest.mark.token]


class TestTokenUsageEdgeCases:
    def test_token_usage_null_cost_defaults_to_zero(self, agentic_service):
        task = agentic_service.create_task(
            project_id="project-1",
            workspace_id="workspace-1",
            environment_id="env-1",
            researcher=make_researcher(),
            prompt="hello",
            owner_user_id="user-1",
        )
        usage = {
            "source": "agent-sdk",
            "total": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "cost_usd": None,
            },
        }
        agentic_service._record_token_usage_sync(task.task_id, usage, replace=True)

        final = agentic_service.get_task(task.task_id)
        parsed = json.loads(final.token_usage_json)
        assert parsed["total"]["cost_usd"] == 0.0

    def test_token_usage_merge_conflicting_by_model(self, agentic_service):
        task = agentic_service.create_task(
            project_id="project-1",
            workspace_id="workspace-1",
            environment_id="env-1",
            researcher=make_researcher(),
            prompt="hello",
            owner_user_id="user-1",
        )
        first = {
            "source": "agent-sdk",
            "total": {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.01},
            "by_model": {
                "claude-sonnet": {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.01}
            },
        }
        second = {
            "source": "agent-sdk",
            "total": {"input_tokens": 20, "output_tokens": 8, "cost_usd": 0.02},
            "by_model": {
                "claude-sonnet": {"input_tokens": 20, "output_tokens": 8, "cost_usd": 0.02}
            },
        }
        agentic_service._record_token_usage_sync(task.task_id, first, replace=True)
        agentic_service._record_token_usage_sync(task.task_id, second, replace=False)

        final = agentic_service.get_task(task.task_id)
        parsed = json.loads(final.token_usage_json)
        assert parsed["total"]["input_tokens"] == 30
        assert parsed["total"]["cost_usd"] == pytest.approx(0.03)
        model = parsed["by_model"]["claude-sonnet"]
        assert model["input_tokens"] == 30
        assert model["cost_usd"] == pytest.approx(0.03)

    def test_streaming_buffer_cleared_on_final_event(self, agentic_service):
        task = agentic_service.create_task(
            project_id="project-1",
            workspace_id="workspace-1",
            environment_id="env-1",
            researcher=make_researcher(),
            prompt="hello",
            owner_user_id="user-1",
        )

        deltas = [
            TaskOutputEvent(
                task_id=task.task_id,
                seq=1,
                kind="message",
                content=json.dumps(
                    {"role": "assistant", "content": "a", "is_delta": True, "block_id": "b1"}
                ),
                created_at=None,
            ),
            TaskOutputEvent(
                task_id=task.task_id,
                seq=2,
                kind="message",
                content=json.dumps(
                    {"role": "assistant", "content": "b", "is_delta": True, "block_id": "b1"}
                ),
                created_at=None,
            ),
        ]
        for d in deltas:
            agentic_service._buffer_streaming_delta(task.task_id, d.kind, d.content)

        assert len(agentic_service._stream_buffers[task.task_id]) == 2

        # Final event clears the buffer.
        final_content = json.dumps(
            {"role": "assistant", "content": "ab", "is_partial": False, "block_id": "b1"}
        )
        asyncio.run(agentic_service.append_output(task.task_id, "message", final_content))
        agentic_service._clear_stream_buffer(task.task_id, "b1")

        assert task.task_id not in agentic_service._stream_buffers

    def test_streaming_buffer_isolated_per_task(self, agentic_service):
        t1 = agentic_service.create_task(
            project_id="p1",
            workspace_id="w1",
            environment_id="e1",
            researcher=make_researcher(),
            prompt="one",
            owner_user_id="user-1",
        )
        t2 = agentic_service.create_task(
            project_id="p2",
            workspace_id="w2",
            environment_id="e2",
            researcher=make_researcher(),
            prompt="two",
            owner_user_id="user-1",
        )

        agentic_service._buffer_streaming_delta(t1.task_id, "message", "delta-1")
        agentic_service._buffer_streaming_delta(t2.task_id, "message", "delta-2")

        assert len(agentic_service._stream_buffers[t1.task_id]) == 1
        assert len(agentic_service._stream_buffers[t2.task_id]) == 1
        assert agentic_service._stream_buffers[t1.task_id][0].content == "delta-1"
        assert agentic_service._stream_buffers[t2.task_id][0].content == "delta-2"

    @pytest.mark.anyio
    async def test_append_output_increments_latest_output_seq(self, agentic_service):
        task = agentic_service.create_task(
            project_id="project-1",
            workspace_id="workspace-1",
            environment_id="env-1",
            researcher=make_researcher(),
            prompt="hello",
            owner_user_id="user-1",
        )
        event = await agentic_service.append_output(task.task_id, "message", "hello")
        assert event.seq == 1

        latest = agentic_service.get_task(task.task_id)
        assert latest.latest_output_seq == 1
        assert latest.status == TaskStatus.QUEUED

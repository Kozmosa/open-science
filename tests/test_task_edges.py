from datetime import datetime

from ainrf.task_harness.models import TaskEdge


def test_task_edge_model():
    edge = TaskEdge(
        edge_id="edge-123",
        project_id="project-456",
        source_task_id="task-a",
        target_task_id="task-b",
        created_at=datetime.now(),
    )
    assert edge.edge_id == "edge-123"
    assert edge.source_task_id == "task-a"
    assert edge.target_task_id == "task-b"

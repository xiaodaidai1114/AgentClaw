import asyncio
import time

import pytest


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_sync_workflow_function_node_does_not_block_event_loop():
    from agentclaw.graph.context import WorkflowContext
    from agentclaw.graph.workflow import Workflow

    workflow = Workflow(id="sync_node_event_loop_guard", name="Sync Node Event Loop Guard")

    @workflow.node(id="slow_sync", output_to_user=False)
    def slow_sync_node(state):
        time.sleep(0.2)
        return {"done": True}

    run_task = asyncio.create_task(
        workflow.get_node("slow_sync").execute({}, WorkflowContext(thread_id="sync-node-guard"))
    )
    started = time.perf_counter()
    await asyncio.sleep(0.03)
    heartbeat_elapsed = time.perf_counter() - started

    result = await run_task

    assert heartbeat_elapsed < 0.12
    assert result["done"] is True


@pytest.mark.asyncio
async def test_sync_custom_node_process_does_not_block_event_loop():
    from agentclaw.graph.context import WorkflowContext
    from agentclaw.node.custom import CustomNode

    class SlowSyncCustomNode(CustomNode):
        def process(self):
            time.sleep(0.2)
            return {"done": True}

    node = SlowSyncCustomNode(id="slow_custom", output_to_user=False)
    run_task = asyncio.create_task(
        node.execute({}, WorkflowContext(thread_id="custom-node-guard"))
    )
    started = time.perf_counter()
    await asyncio.sleep(0.03)
    heartbeat_elapsed = time.perf_counter() - started

    result = await run_task

    assert heartbeat_elapsed < 0.12
    assert result["done"] is True

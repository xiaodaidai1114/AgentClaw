from agentclaw.memory.workflow_memory import MEMORY_CHAR_LIMIT, write_workflow_memory


def test_workflow_memory_default_limit_is_40000_chars(tmp_path):
    assert MEMORY_CHAR_LIMIT == 40000

    at_limit = write_workflow_memory(tmp_path, "wf", "x" * MEMORY_CHAR_LIMIT)
    over_limit = write_workflow_memory(tmp_path, "wf", "x" * (MEMORY_CHAR_LIMIT + 1))

    assert at_limit["over_limit"] is False
    assert over_limit["over_limit"] is True

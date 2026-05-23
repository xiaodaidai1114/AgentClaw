def test_state_path_reads_writes_and_merges_nested_values():
    from agentclaw.graph.state_path import get_path, merge_path, set_path

    state = {}

    set_path(state, "actors.p7.memory", {"trust": [3]})
    assert get_path(state, "actors.p7.memory.trust") == [3]
    assert get_path(state, "actors.p8.memory", default={}) == {}

    merge_path(state, "actors.p7.memory", {"pressure": [9]}, strategy="shallow_merge")
    assert state["actors"]["p7"]["memory"] == {"trust": [3], "pressure": [9]}

    merge_path(state, "actors.p7.memory", {"nested": {"a": 1}}, strategy="deep_merge")
    merge_path(state, "actors.p7.memory", {"nested": {"b": 2}}, strategy="deep_merge")
    assert state["actors"]["p7"]["memory"]["nested"] == {"a": 1, "b": 2}

    merge_path(state, "actor_outputs.p7.events", {"type": "speech"}, strategy="append")
    assert state["actor_outputs"]["p7"]["events"] == [{"type": "speech"}]


def test_state_path_renders_path_templates():
    from agentclaw.graph.state_path import render_path_template

    assert (
        render_path_template("{actor_root}.memory", {"actor_root": "actors.p7"})
        == "actors.p7.memory"
    )

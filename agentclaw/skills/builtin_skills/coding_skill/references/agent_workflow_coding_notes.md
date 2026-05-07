# Coding Skill x Agent Creator Integration Notes

This reference is not an `agent_creator` playbook.
It defines how `coding_skill` should collaborate with `agent_creator` when a task includes both workflow design and code editing.

## 1) Responsibility Split

- `agent_creator` owns:
  - workflow architecture and node graph decisions
  - registration/runtime acceptance decisions
  - delivery status (`completed` / `partial` / `blocked`)
- `coding_skill` owns:
  - deterministic code edits
  - path-accurate file operations
  - syntax-level validation evidence

Rule:
- Do not duplicate architecture decisions inside `coding_skill`.
- Do not move low-level edit mechanics into `agent_creator`.

## 2) Shared Contract for Mixed Tasks

When a task says "build agent/workflow and modify code", collaboration should follow:

1. `agent_creator` defines target design + required files.
2. `coding_skill` executes edits with coding-tools.
3. `coding_skill` returns concrete edit/validation results.
4. `agent_creator` decides readiness and user-facing completion status.

`coding_skill` should report facts, not design verdicts.

## 3) Coding-Side Requirements in Agent Tasks

For workflow-related edits, `coding_skill` should verify only code facts:

- constructor and node calls are syntactically valid
- edited files exist at expected paths
- bootstrap imports/registration-related lines are actually present after edit
- syntax checks pass (`syntax_check`, `py_compile`)

Do not claim "workflow is ready" from code edits alone.

## 4) Tool Usage Pattern for Integration

Preferred sequence for coding execution under an agent task:

1. `search_code` locate workflow/entry files
2. `read_code` confirm exact anchors
3. edit via `replace_in_file` or `update_code`
4. if needed, `write_file` for full file creation/overwrite
5. `syntax_check` + `py_compile`
6. return machine-checkable evidence to `agent_creator`

If the same edit call fails twice, switch tool strategy and report the switch.

## 5) Common Integration Failure Modes

- `agent_creator` plan says file A, but coding edits file B (entry mismatch)
- workflow file changed but bootstrap import not applied
- path drift between write and follow-up syntax check
- repeated parameter-shape errors in `update_code` / `replace_in_file`

`coding_skill` should surface these as execution facts for `agent_creator` to resolve.

## 6) Non-Goals in This Reference

- no full workflow design templates
- no runtime acceptance gate policy
- no external API behavior specification

Those belong to `agent_creator` docs.

# NL2SQL / SQL Agent Patterns

Use this reference when the user asks to create or modify an NL2SQL, SQL query, database Q&A, reporting, analytics, or log-audit workflow.

A strong SQL agent starts from live schema evidence, validates generated SQL before execution, and makes blockers explicit instead of filling unknown tables or columns from model memory.

## 1) Map the Evidence First

Before coding, identify how the workflow will know:

1. Database type: PostgreSQL, MySQL, SQLite, etc.
2. Connection source: environment variables, config file, MCP server, or user-provided values.
3. Allowed scope: schemas, databases, tables, read-only vs. write access.
4. Schema source: live introspection, supplied DDL, docs, or a curated metadata file.
5. Execution policy: generate SQL only, validate only, or execute read-only SQL.
6. Output contract: SQL text, explanation, tabular results, report, files, or API response.

When schema is not already available, shape the agent around runtime schema introspection or ask the user for the schema source. This keeps the workflow grounded without making it feel brittle or over-prescribed.

## 2) Choose One Design

There are two useful NL2SQL designs. Pick the one that matches the reliability needs of the user request.

### Design A: Tool-Based Agent

Use when:
- The user wants a conversational, exploratory database assistant.
- The agent must decide which tables to inspect dynamically.
- The database schema changes often.
- Flexible exploration is more important than a fixed production path.

Tradeoff:
- Strength: high flexibility and fast implementation; the agent can inspect schema and choose tools as needed.
- Cost: higher tool dependency, latency, and token usage than the process-based workflow.

Shape:

```text
agentic LLMNode
  tools:
    get_database_schema
    validate_sql
    execute_readonly_sql
```

Operating protocol:
1. The agent should obtain fresh schema with `get_database_schema` before generating SQL unless a fresh schema is already visible in state/context.
2. The agent should call `validate_sql` before any execution.
3. `execute_readonly_sql` should accept only SQL that passed validation.
4. Tool docstrings should state the intended order clearly because agentic mode learns the workflow from tool descriptions.
5. The final answer should include SQL, field evidence, validation status, and result or blocker.

Template:

```python
import os
from agentclaw import Workflow, LLMNode, ToolKit

workflow = Workflow(
    id="nl2sql_agent",
    name="NL2SQL Agent",
    inputs={"user_query": str, "execute_query": bool},
    user_input="user_query",
)

toolkit = ToolKit()


@toolkit.tool
def get_database_schema() -> dict:
    """Read the live database schema before SQL generation.

    Returns:
        A dict containing tables, columns, types, primary keys, and foreign keys.
    """
    # Connect using environment variables and introspect information_schema / PRAGMA.
    # Return structured JSON-serializable metadata.
    ...


@toolkit.tool
def validate_sql(sql: str) -> dict:
    """Validate read-only SQL against the live schema before execution.

    Args:
        sql: Candidate SQL generated from the known schema.

    Returns:
        {valid, safe_sql, errors, missing_tables, missing_columns}
    """
    # Enforce SELECT-only, table/column existence, LIMIT, and dry-run / EXPLAIN.
    ...


@toolkit.tool
def execute_readonly_sql(safe_sql: str) -> dict:
    """Execute SQL after validate_sql returned valid=true.

    Args:
        safe_sql: The validated SQL returned by validate_sql.
    """
    # Execute with timeout and row limits.
    ...


workflow.register_toolkit(toolkit)

workflow.add_node(LLMNode(
    id="agent",
    agent_style="agentic",
    tools=["get_database_schema", "validate_sql", "execute_readonly_sql"],
    system_prompt="""You are a schema-grounded SQL assistant.

Operating protocol:
1. Obtain the live schema with get_database_schema unless a fresh schema is already visible in context.
2. Use only tables and columns present in the schema.
3. Base joins, metrics, and filters on schema evidence or user-provided business rules.
4. Before executing, call validate_sql and use only safe_sql returned by validation.
5. If validation fails, explain the validation errors and ask for clarification instead of executing.
6. If execute_query is false, return the validated SQL and explanation without executing it.

Answer with:
- SQL
- field evidence: table.column entries used
- validation status
- results or blocker
""",
    user_prompt="Question: {user_query}\nExecute query: {execute_query}",
    output_to_user=True,
    stream=True,
))

workflow.publish()
```

Use this design when the model genuinely needs flexible multi-step exploration. For production reporting, scheduled jobs, or high reliability, prefer Design B.

### Design B: Process-Based Workflow

Use when:
- The workflow should be reliable and repeatable.
- The agent is used for production reports, scheduled tasks, dashboards, or customer-visible answers.
- Deterministic failure handling matters.
- SQL execution should happen only after validation passes.

Shape:

```text
load_schema
  -> generate_sql
  -> validate_sql
  -> generate_sql      if invalid and no regeneration has been attempted
  -> validate_sql      after regeneration
  -> execute_sql?      if valid and execute_query=true
  -> format_answer
```

The important loop is: read schema, generate SQL, validate SQL, regenerate once if invalid, validate again, then execute only valid SQL. One schema-aware `generate_sql` node can handle the initial draft and the single regeneration by reading `sql_validation` and `sql_regeneration_count` from state.

For SQL-backed reports or scheduled audit reports, extend the successful execution path:

```text
... -> execute_sql -> generate_report -> write_report? -> format_response
```

`generate_report` should be an `LLMNode` that writes the narrative summary, risk explanation, recommendations, and Markdown content from structured query results and validation evidence. `write_report` should only persist the LLM-produced Markdown.

Construction guidance:
1. `load_schema` is deterministic and writes `schema_json` / `schema_text` into state.
2. `generate_sql` receives schema in the prompt and has no SQL execution tool.
3. `validate_sql` is deterministic and writes `valid`, `safe_sql`, and structured errors.
4. If validation fails, route back to `generate_sql` exactly once with validation errors and `sql_regeneration_count=1`.
5. If SQL is still invalid after one regeneration, skip execution and report the validation blocker.
6. `execute_sql` executes only `safe_sql`, never raw LLM output.
7. `format_answer` reports SQL, evidence, validation, results, or the blocker.
8. For report files, use deterministic code for collection, validation, metrics, and file writing; use an `LLMNode` for the human-facing narrative/report content.

Template:

```python
import json
from agentclaw import Workflow, LLMNode

workflow = Workflow(
    id="nl2sql_flow",
    name="NL2SQL Flow",
    inputs={"user_query": str, "execute_query": bool},
    user_input="user_query",
)


@workflow.node("load_schema")
def load_schema(state):
    """Load live database schema into workflow state."""
    schema = ...  # Introspect real database metadata.
    return {
        "schema_json": schema,
        "schema_text": json.dumps(schema, ensure_ascii=False, indent=2),
        "sql_regeneration_count": 0,
        "sql_validation": {},
    }


workflow.add_node(LLMNode(
    id="generate_sql",
    system_prompt="""Generate SQL from the provided schema and optional validation feedback.

<SCHEMA>
{schema_text}
</SCHEMA>

Previous validation, if any:
{sql_validation}

Regeneration count:
{sql_regeneration_count}

Use only tables and columns in <SCHEMA>. If the question cannot be mapped to schema, output status=clarification_needed.
When validation feedback is present, regenerate once by correcting only the reported issues.

Output JSON only:
{
  "status": "ok | clarification_needed",
  "sql": "...",
  "field_evidence": [{"field": "table.column", "reason": "..."}],
  "questions": []
}
""",
    user_prompt="{user_query}",
    output_key="sql_draft",
    output_format="json",
    output_to_user=False,
))


@workflow.node("validate_sql")
def validate_sql(state):
    """Validate generated SQL against schema and database dry-run."""
    draft = state.get("sql_draft") or {}
    sql = draft.get("sql") if isinstance(draft, dict) else ""
    schema = state.get("schema_json") or {}
    validation = ...  # SELECT-only, schema check, LIMIT, EXPLAIN/PREPARE.
    return {"sql_validation": validation}


@workflow.node("mark_regeneration_attempt")
def mark_regeneration_attempt(state):
    """Count the single allowed SQL regeneration attempt."""
    return {"sql_regeneration_count": int(state.get("sql_regeneration_count") or 0) + 1}


@workflow.node("execute_sql")
def execute_sql(state):
    """Execute only validated safe_sql when requested."""
    if not state.get("execute_query"):
        return {"query_result": {"executed": False}}
    validation = state.get("sql_validation") or {}
    if not validation.get("valid"):
        return {"query_result": {"executed": False, "error": "SQL validation failed"}}
    safe_sql = validation["safe_sql"]
    result = ...  # Execute read-only safe_sql with timeout and row limit.
    return {"query_result": result}


workflow.add_node(LLMNode(
    id="format_answer",
    system_prompt="""Present the NL2SQL result.

User question: {user_query}
SQL draft: {sql_draft}
Validation: {sql_validation}
Query result: {query_result}

Explain whether SQL was generated, validated, executed, or blocked. Include validation blockers when present.
""",
    output_to_user=True,
    stream=True,
))

workflow.add_edge("__start__", "load_schema")
workflow.add_edge("load_schema", "generate_sql")
workflow.add_edge("generate_sql", "validate_sql")
workflow.add_router(
    after="validate_sql",
    routes={
        "valid": "execute_sql",
        "regenerate": "mark_regeneration_attempt",
        "blocked": "format_answer",
    },
    condition=lambda state: (
        "valid"
        if (state.get("sql_validation") or {}).get("valid")
        else "regenerate"
        if int(state.get("sql_regeneration_count") or 0) < 1
        else "blocked"
    ),
)
workflow.add_edge("mark_regeneration_attempt", "generate_sql")
workflow.add_edge("execute_sql", "format_answer")
workflow.publish()
```

Prefer this design for most NL2SQL agents created by `agent_creator`.

## 3) Prompt Requirements

Every NL2SQL prompt should communicate these ideas:

```text
Use only the provided schema.
If a table or column is missing, ask for clarification or return clarification_needed.
If a user request cannot be mapped to schema, ask for clarification or return clarification_needed.
Before execution, SQL must pass validation.
```

Avoid prompts that encourage shortcutting evidence, for example:

```text
Please directly output SQL and do not ask questions.
Use common database fields.
Assume typical user/order/product columns.
```

Only include `{schema}`, `{schema_text}`, or similar placeholders when an upstream node actually writes those state fields.

## 4) SQL Tool Requirements

SQL execution tools should:

1. Allow read-only SQL only.
2. Reject multiple statements.
3. Accept validated `safe_sql` rather than raw model SQL.
4. Validate table and column names against schema when feasible.
5. Add or enforce LIMIT.
6. Use timeout and row caps.
7. Return structured errors:
   - `invalid_sql`
   - `missing_table`
   - `missing_column`
   - `ambiguous_column`
   - `unsafe_statement`
   - `dry_run_failed`

## 5) Validation Checklist

Before reporting completion for an NL2SQL agent:

1. Import validation passes.
2. Registration passes.
3. Schema discovery succeeds or returns a clear blocker.
4. A known valid question generates SQL using only real fields.
5. An impossible/missing-field question returns a blocker or clarification path.
6. Invalid SQL is blocked before execution.
7. If execution is enabled, only validated `safe_sql` is executed.

Report `partial` if schema discovery, validation, or runtime smoke testing is incomplete.

## 6) Common Failure Shapes

Watch for these during creation and validation:

- A single LLMNode directly writes and executes SQL with no schema gate.
- A prompt has `{schema}` but no upstream state field provides schema.
- A tool named `query_db(sql)` executes arbitrary model SQL after only checking `SELECT`.
- The workflow treats SQL database errors as the first validation layer instead of validating before execution.
- A report-generation workflow writes the full human-facing analysis in Python string templates instead of using an `LLMNode` after evidence collection.
- The final response claims completion without schema discovery, SQL validation, and runtime evidence.

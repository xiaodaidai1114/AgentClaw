"""StateExtractNode - extract structured fields from text into workflow state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, TYPE_CHECKING, Union
import json

from agentclaw.graph.state_path import get_path, set_path
from agentclaw.node.base import BaseNode
from agentclaw.node.llm import LLMNode

if TYPE_CHECKING:
    from agentclaw.graph.context import WorkflowContext


@dataclass
class StateExtractNode(BaseNode):
    """Use an LLM to extract structured data from text and write it to state."""

    source_key: str = ""
    target_key: str = ""
    instruction: str = ""
    schema: Dict[str, Any] = field(default_factory=dict)
    fields: Dict[str, Any] = field(default_factory=dict)
    requirements: str = ""
    examples: Union[str, list, Dict[str, Any]] = field(default_factory=list)
    write_to: Dict[str, str] = field(default_factory=dict)
    model_id: Optional[str] = None
    use_fast_model: bool = False
    model_params: Optional[Dict[str, Any]] = None
    output_to_user: bool = False
    save_to_context: bool = False

    async def _do_execute(self, state: dict, context: "WorkflowContext") -> dict:
        source_key = self._resolve_source_key(context)
        source_value = get_path(state, source_key)
        raw_text = "" if source_value is None else str(source_value)

        llm = LLMNode(
            id=f"{self.id}__llm",
            system_prompt=self._build_system_prompt(),
            user_prompt="{__state_extract_source__}",
            output_format="json",
            output_key=f"__{self.id}_raw_extract__",
            output_to_user=False,
            save_to_context=False,
            model_id=self.model_id,
            use_fast_model=self.use_fast_model,
            model_params=self.model_params,
            auto_fallback=False,
            fallback_threshold=0,
        )

        working_state = dict(state)
        working_state["__state_extract_source__"] = raw_text
        result_state = await llm.execute(working_state, context)
        raw_result = result_state.get(f"__{self.id}_raw_extract__")

        extracted = self._normalize_result(raw_result)
        state[self.get_output_key()] = extracted

        for state_path, result_path in self._effective_write_to().items():
            value = self._extract_result_path(extracted, result_path)
            set_path(state, state_path, value)

        return state

    def _build_system_prompt(self) -> str:
        schema = self._normalized_schema()
        fields_json = json.dumps(schema, ensure_ascii=False, indent=2)
        fields_json = fields_json.replace("{", "{{").replace("}", "}}")
        parts = [
            "You extract structured state from text for an AgentClaw workflow.\n"
            "Return JSON only. Do not include markdown or explanations.\n"
            "Return a single JSON object with exactly the requested business fields.\n"
            "When a field cannot be determined, use its default value.\n"
        ]
        if self.instruction:
            parts.append(f"\nInstruction:\n{self.instruction}\n")
        if self.requirements:
            parts.append(f"\nBusiness requirements:\n{self.requirements}\n")
        if self.examples:
            if isinstance(self.examples, str):
                examples = self.examples
            else:
                examples = json.dumps(self.examples, ensure_ascii=False, indent=2, default=str)
            examples = examples.replace("{", "{{").replace("}", "}}")
            parts.append(f"\nExamples:\n{examples}\n")
        parts.append(f"\nSchema:\n{fields_json}")
        return "".join(parts)

    def _resolve_source_key(self, context: "WorkflowContext") -> str:
        if self.source_key:
            return self.source_key
        if context and context.user_input_field:
            return context.user_input_field
        return "user_input"

    def _normalized_schema(self) -> Dict[str, dict]:
        raw_schema = self.schema or self.fields
        normalized: Dict[str, dict] = {}
        for name, config in raw_schema.items():
            if isinstance(config, dict):
                normalized[name] = {
                    "description": config.get("description", ""),
                    "default": config.get("default"),
                }
            else:
                normalized[name] = {
                    "description": str(config),
                    "default": None,
                }
        return normalized

    def _effective_write_to(self) -> Dict[str, str]:
        effective = dict(self.write_to)
        if self.target_key and self.target_key not in effective:
            effective[self.target_key] = "$"
        return effective

    def get_state_output_keys(self) -> list[str]:
        """Return all top-level state fields this node may write."""
        keys = [self.get_output_key()]
        for state_path in self._effective_write_to():
            top_level_key = state_path.split(".", 1)[0]
            if top_level_key and top_level_key not in keys:
                keys.append(top_level_key)
        return keys

    def _normalize_result(self, raw_result: Any) -> dict:
        schema = self._normalized_schema()
        if not isinstance(raw_result, dict) or "__error__" in raw_result:
            raw_result = {}

        if isinstance(raw_result.get("data"), dict):
            raw_result = raw_result["data"]

        if not schema:
            return dict(raw_result)

        normalized = {}
        for name, config in schema.items():
            normalized[name] = raw_result.get(name, config.get("default"))
        return normalized

    @staticmethod
    def _extract_result_path(result: dict, result_path: str) -> Any:
        if result_path == "$":
            return result
        if result_path.startswith("$."):
            return get_path(result, result_path[2:])
        return get_path(result, result_path)

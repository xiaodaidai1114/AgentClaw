"""Workflow templates that instantiate to regular AgentClaw workflows."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
import string

from agentclaw.graph.workflow import Workflow
from agentclaw.node.base import BaseNode


class _StrictFormatDict(dict):
    def __missing__(self, key: str) -> str:
        raise KeyError(key)


class _PreserveMissingFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass
class WorkflowTemplate:
    """A parameterized workflow definition that expands to a normal Workflow."""

    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    variables: Dict[str, Any] = field(default_factory=dict)

    _nodes: Dict[str, BaseNode] = field(default_factory=dict, init=False, repr=False)
    _node_order: List[str] = field(default_factory=list, init=False, repr=False)
    _edges: List[tuple[str, Union[str, List[str]]]] = field(default_factory=list, init=False, repr=False)
    _state_fields: Dict[str, type] = field(default_factory=dict, init=False, repr=False)
    _required_variables: set[str] = field(default_factory=set, init=False, repr=False)

    def add_node(self, node: BaseNode) -> "WorkflowTemplate":
        if node.id in self._nodes:
            raise ValueError(f"Node ID '{node.id}' already exists in workflow template '{self.id}'.")
        self._nodes[node.id] = node
        self._node_order.append(node.id)
        self._collect_node_variables(node)
        return self

    def add_edge(self, from_node: str, to_node: Union[str, List[str]]) -> "WorkflowTemplate":
        self._edges.append((from_node, to_node))
        self._required_variables.update(self._extract_format_fields(from_node))
        if isinstance(to_node, list):
            for target in to_node:
                self._required_variables.update(self._extract_format_fields(target))
        else:
            self._required_variables.update(self._extract_format_fields(to_node))
        return self

    def register_state_field(self, name: str, field_type: type = str) -> "WorkflowTemplate":
        self._state_fields[name] = field_type
        self._required_variables.update(self._extract_format_fields(name))
        return self

    def instantiate(
        self,
        id: str,
        name: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
        **workflow_kwargs,
    ) -> Workflow:
        merged_vars = {**self.variables, **(variables or {})}
        self._validate_required_variables(merged_vars)
        workflow = Workflow(
            id=id,
            name=name or self.name,
            version=self.version,
            description=self._render(self.description, merged_vars),
            **workflow_kwargs,
        )

        for field_name, field_type in self._state_fields.items():
            workflow.register_state_field(self._render(field_name, merged_vars), field_type)

        rendered_id_by_template_id: dict[str, str] = {}
        for template_node_id in self._node_order:
            node = self._render_value(deepcopy(self._nodes[template_node_id]), merged_vars, strict=False)
            rendered_id_by_template_id[template_node_id] = node.id
            workflow.add_node(node)

        for from_node, to_node in self._edges:
            workflow.add_edge(
                self._render_edge_endpoint(from_node, merged_vars, rendered_id_by_template_id),
                self._render_edge_targets(to_node, merged_vars, rendered_id_by_template_id),
            )

        return workflow

    def _render_edge_targets(
        self,
        to_node: Union[str, List[str]],
        variables: Dict[str, Any],
        id_map: Dict[str, str],
    ) -> Union[str, List[str]]:
        if isinstance(to_node, list):
            return [self._render_edge_endpoint(target, variables, id_map) for target in to_node]
        return self._render_edge_endpoint(to_node, variables, id_map)

    def _render_edge_endpoint(self, value: str, variables: Dict[str, Any], id_map: Dict[str, str]) -> str:
        if value in ("__start__", "__end__", "START", "END"):
            return value
        if value in id_map:
            return id_map[value]
        return self._render(value, variables)

    def _render_value(self, value: Any, variables: Dict[str, Any], *, strict: bool) -> Any:
        if isinstance(value, str):
            return self._render(value, variables, strict=strict)
        if isinstance(value, list):
            return [self._render_value(item, variables, strict=strict) for item in value]
        if isinstance(value, tuple):
            return tuple(self._render_value(item, variables, strict=strict) for item in value)
        if isinstance(value, dict):
            return {
                self._render_value(key, variables, strict=strict): self._render_value(item, variables, strict=strict)
                for key, item in value.items()
            }
        if isinstance(value, BaseNode):
            for attr, attr_value in vars(value).items():
                if attr.startswith("_"):
                    continue
                setattr(value, attr, self._render_value(attr_value, variables, strict=strict))
            return value
        return value

    @staticmethod
    def _render(template: str, variables: Dict[str, Any], *, strict: bool = True) -> str:
        formatter = string.Formatter()
        values = _StrictFormatDict(variables) if strict else _PreserveMissingFormatDict(variables)
        return formatter.vformat(template, (), values)

    def _collect_node_variables(self, node: BaseNode) -> None:
        self._required_variables.update(self._extract_format_fields(node.id))
        for attr, attr_value in vars(node).items():
            if attr.startswith("_"):
                continue
            if attr == "user_prompt":
                continue
            self._required_variables.update(self._extract_value_fields(attr_value))

    def _extract_value_fields(self, value: Any) -> set[str]:
        if isinstance(value, str):
            return self._extract_format_fields(value)
        if isinstance(value, dict):
            fields: set[str] = set()
            for key, item in value.items():
                fields.update(self._extract_value_fields(key))
                fields.update(self._extract_value_fields(item))
            return fields
        if isinstance(value, (list, tuple)):
            fields: set[str] = set()
            for item in value:
                fields.update(self._extract_value_fields(item))
            return fields
        return set()

    @staticmethod
    def _extract_format_fields(template: str) -> set[str]:
        if not isinstance(template, str):
            return set()
        fields: set[str] = set()
        formatter = string.Formatter()
        for _, field_name, _, _ in formatter.parse(template):
            if field_name:
                fields.add(field_name.split(".", 1)[0].split("[", 1)[0])
        return fields

    def _validate_required_variables(self, variables: Dict[str, Any]) -> None:
        missing = sorted(name for name in self._required_variables if name not in variables)
        if missing:
            raise KeyError(missing[0])

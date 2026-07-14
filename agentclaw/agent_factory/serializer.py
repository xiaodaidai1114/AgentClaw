"""
AgentBlueprint 序列化器 - 支持 JSON 与 YAML

- JSON: Pydantic 原生（无额外依赖）
- YAML: 优先使用 pyyaml（AgentClaw 未将其列为直接依赖，但通常作为
  langchain/openai 等的间接依赖可用）；不可用时调用 YAML 方法会抛出
  明确错误，JSON 路径不受影响。

datetime 字段以 ISO 字符串序列化，加载时由 Pydantic 自动还原。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Union

from .blueprint import AgentBlueprint


# 延迟探测 pyyaml，避免在不可用时影响 JSON 路径与包导入
_YAML_AVAILABLE = False
try:
    import yaml as _yaml  # type: ignore

    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover - 依赖环境决定
    _yaml = None


YAML_EXTS = {".yaml", ".yml"}
JSON_EXTS = {".json"}


def yaml_available() -> bool:
    """是否可用 YAML 序列化（即 pyyaml 已安装）"""
    return _YAML_AVAILABLE


def _require_yaml() -> None:
    if not _YAML_AVAILABLE:
        raise RuntimeError(
            "YAML 序列化需要 pyyaml，当前环境未安装。"
            "请执行：pip install pyyaml"
        )


# ------------------------------------------------------------------
# dict
# ------------------------------------------------------------------

def to_dict(blueprint: AgentBlueprint) -> Dict[str, Any]:
    """转换为纯 Python 字典（datetime → ISO 字符串）"""
    return blueprint.model_dump(mode="json")


def from_dict(data: Dict[str, Any]) -> AgentBlueprint:
    """从字典构造 Blueprint"""
    return AgentBlueprint.model_validate(data)


# ------------------------------------------------------------------
# JSON
# ------------------------------------------------------------------

def to_json(blueprint: AgentBlueprint, *, indent: int = 2, ensure_ascii: bool = False) -> str:
    """序列化为 JSON 字符串（默认中文不转义）"""
    return json.dumps(to_dict(blueprint), ensure_ascii=ensure_ascii, indent=indent)


def from_json(text: str) -> AgentBlueprint:
    """从 JSON 字符串加载"""
    return AgentBlueprint.model_validate(json.loads(text))


# ------------------------------------------------------------------
# YAML
# ------------------------------------------------------------------

def to_yaml(blueprint: AgentBlueprint) -> str:
    """序列化为 YAML 字符串"""
    _require_yaml()
    return _yaml.safe_dump(
        to_dict(blueprint),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def from_yaml(text: str) -> AgentBlueprint:
    """从 YAML 字符串加载"""
    _require_yaml()
    data = _yaml.safe_load(text)
    if data is None:
        raise ValueError("YAML 内容为空")
    return AgentBlueprint.model_validate(data)


# ------------------------------------------------------------------
# 文件（按扩展名自动选择格式）
# ------------------------------------------------------------------

def save(blueprint: AgentBlueprint, path: Union[str, Path]) -> Path:
    """
    保存 Blueprint 到文件，根据扩展名自动选择格式：
    .yaml / .yml → YAML；.json → JSON。

    会自动创建父目录。
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext in YAML_EXTS:
        text = to_yaml(blueprint)
    elif ext in JSON_EXTS:
        text = to_json(blueprint)
    else:
        raise ValueError(
            f"不支持的文件扩展名: {ext!r}（支持 .yaml / .yml / .json）"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def load(path: Union[str, Path]) -> AgentBlueprint:
    """从文件加载 Blueprint，根据扩展名自动选择格式"""
    path = Path(path)
    ext = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if ext in YAML_EXTS:
        return from_yaml(text)
    if ext in JSON_EXTS:
        return from_json(text)
    raise ValueError(
        f"不支持的文件扩展名: {ext!r}（支持 .yaml / .yml / .json）"
    )

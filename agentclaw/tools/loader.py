"""
ToolSpec 加载器：从 tools/specs/*.yaml 批量加载工具定义。

约定：每个 YAML 文件一个 ToolSpec（顶层 name/description/input_schema/handler）。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Union

from .spec import ToolSpec


def load_specs(specs_dir: Union[str, Path]) -> List[ToolSpec]:
    """
    从目录加载所有 *.y*ml 工具定义。

    Args:
        specs_dir: 工具定义目录（如项目根的 tools/specs/）

    Returns:
        ToolSpec 列表（按文件名排序）
    """
    specs_dir = Path(specs_dir)
    if not specs_dir.exists():
        return []

    try:
        import yaml  # type: ignore
    except ImportError:
        return []

    specs: List[ToolSpec] = []
    for f in sorted(specs_dir.glob("*.y*ml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and data.get("name"):
            try:
                specs.append(ToolSpec.model_validate(data))
            except Exception:
                # 跳过单个坏定义，不影响其他工具
                continue
    return specs


def load_spec(specs_dir: Union[str, Path], name: str):
    """加载单个工具定义（按 name）"""
    for s in load_specs(specs_dir):
        if s.name == name:
            return s
    return None

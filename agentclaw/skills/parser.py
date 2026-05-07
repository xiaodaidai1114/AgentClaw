"""
SKILL.md 解析器
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .schema import Skill


class SkillParser:
    """解析 SKILL.md 文件"""

    @staticmethod
    def parse(skill_dir: Path) -> Skill:
        """解析技能目录

        Args:
            skill_dir: 技能目录路径

        Returns:
            Skill 对象

        Raises:
            FileNotFoundError: SKILL.md 不存在
            ValueError: SKILL.md 格式无效
        """
        skill_dir = Path(skill_dir)
        skill_md = skill_dir / "SKILL.md"

        if not skill_md.exists():
            raise FileNotFoundError(f"SKILL.md not found in {skill_dir}")

        content = skill_md.read_text(encoding="utf-8")

        # 解析 YAML frontmatter
        frontmatter, markdown_body = SkillParser._parse_frontmatter(content)

        if not frontmatter:
            raise ValueError(f"SKILL.md must have YAML frontmatter in {skill_dir}")

        # 收集脚本文件
        scripts = SkillParser._collect_scripts(skill_dir)

        # 收集参考文档
        references = SkillParser._collect_references(skill_dir)

        # 收集资源文件
        resources = SkillParser._collect_resources(skill_dir)

        # 提取 metadata（可能是 dict 或 JSON 字符串）
        metadata = frontmatter.get("metadata")
        if isinstance(metadata, str) and metadata:
            try:
                import json
                # 清理尾随逗号（某些 YAML 中的 JSON 不严格）
                cleaned = re.sub(r",\s*([}\]])", r"\1", metadata)
                metadata = json.loads(cleaned)
            except (json.JSONDecodeError, ValueError):
                metadata = None

        return Skill(
            name=frontmatter.get("name", skill_dir.name),
            description=frontmatter.get("description", ""),
            path=skill_dir,
            content=markdown_body,
            license=frontmatter.get("license"),
            metadata=metadata if isinstance(metadata, dict) else None,
            scripts=scripts,
            references=references,
            resources=resources,
        )

    @staticmethod
    def _parse_frontmatter(content: str) -> Tuple[Optional[Dict], str]:
        """解析 YAML frontmatter

        Args:
            content: SKILL.md 文件内容

        Returns:
            (frontmatter_dict, markdown_body)
        """
        if not content.startswith("---"):
            return None, content

        # 使用正则匹配 frontmatter
        pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(pattern, content, re.DOTALL)

        if not match:
            return None, content

        yaml_content = match.group(1)
        markdown_body = match.group(2).strip()

        # 简单解析 YAML（避免依赖 pyyaml）
        frontmatter = SkillParser._simple_yaml_parse(yaml_content)

        return frontmatter, markdown_body

    @staticmethod
    def _simple_yaml_parse(yaml_content: str) -> Dict:
        """简单的 YAML 解析（支持简单键值对和多行 JSON/缩进值）

        Args:
            yaml_content: YAML 内容

        Returns:
            解析后的字典
        """
        import json

        result = {}
        lines = yaml_content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if not stripped or stripped.startswith("#"):
                i += 1
                continue

            # 顶层 key 必须不以空格开头（非缩进行）
            if line[0] in (" ", "\t") and not line.lstrip().startswith("-"):
                i += 1
                continue

            if ":" not in stripped:
                i += 1
                continue

            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()

            # 值在同一行且以 { 或 [ 开头 → 收集多行 JSON
            if value and value[0] in ("{", "["):
                collected = value
                open_count = collected.count("{") + collected.count("[")
                close_count = collected.count("}") + collected.count("]")

                while open_count > close_count and i + 1 < len(lines):
                    i += 1
                    collected += "\n" + lines[i]
                    open_count = collected.count("{") + collected.count("[")
                    close_count = collected.count("}") + collected.count("]")

                try:
                    result[key] = json.loads(collected)
                except json.JSONDecodeError:
                    result[key] = collected

            # 值为空 → 可能是多行缩进块（JSON 或 YAML 子结构）
            elif not value:
                # 收集后续缩进行
                collected_lines = []
                while i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # 缩进行或空行属于这个值
                    if next_line and next_line[0] in (" ", "\t"):
                        collected_lines.append(next_line)
                        i += 1
                    elif not next_line.strip():
                        collected_lines.append(next_line)
                        i += 1
                    else:
                        break

                if collected_lines:
                    block = "\n".join(collected_lines).strip()
                    # 尝试解析为 JSON
                    try:
                        result[key] = json.loads(block)
                    except (json.JSONDecodeError, ValueError):
                        result[key] = block
                else:
                    result[key] = ""

            else:
                # 简单的 key: value
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]

                result[key] = value

            i += 1

        return result

    @staticmethod
    def _collect_scripts(skill_dir: Path) -> List[Path]:
        """收集脚本文件"""
        scripts_dir = skill_dir / "scripts"
        if not scripts_dir.exists():
            return []

        scripts = []
        for f in scripts_dir.glob("*.py"):
            # 跳过私有文件和 __init__.py
            if f.name.startswith("_"):
                continue
            scripts.append(f)

        return sorted(scripts, key=lambda x: x.name)

    @staticmethod
    def _collect_references(skill_dir: Path) -> List[Path]:
        """收集参考文档"""
        ref_dir = skill_dir / "references"
        if not ref_dir.exists():
            return []

        refs = list(ref_dir.glob("*.md"))
        return sorted(refs, key=lambda x: x.name)

    @staticmethod
    def _collect_resources(skill_dir: Path) -> List[Path]:
        """收集资源文件"""
        res_dir = skill_dir / "resources"
        if not res_dir.exists():
            return []

        resources = [f for f in res_dir.iterdir() if f.is_file()]
        return sorted(resources, key=lambda x: x.name)

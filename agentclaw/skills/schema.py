"""
Skill 数据结构定义
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Skill:
    """Skill 数据结构"""

    name: str  # 技能名称
    description: str  # 技能描述（用于触发判断）
    path: Path  # 技能目录路径
    content: str  # SKILL.md 的 Markdown 内容
    license: Optional[str] = None  # 许可证说明
    metadata: Optional[Dict[str, Any]] = None  # 扩展元数据
    scripts: List[Path] = field(default_factory=list)  # 脚本文件列表
    references: List[Path] = field(default_factory=list)  # 参考文档列表
    resources: List[Path] = field(default_factory=list)  # 资源文件列表

    @property
    def has_scripts(self) -> bool:
        """是否有可执行脚本"""
        return len(self.scripts) > 0

    @property
    def requirements_file(self) -> Optional[Path]:
        """获取 requirements.txt 路径
        
        查找顺序：
        1. scripts/requirements.txt
        2. requirements.txt (根目录)
        """
        # 优先查找 scripts 目录
        req_file = self.path / "scripts" / "requirements.txt"
        if req_file.exists():
            return req_file
        
        # 其次查找根目录
        req_file = self.path / "requirements.txt"
        if req_file.exists():
            return req_file
        
        return None

    def to_prompt(self, include_content: bool = False) -> str:
        """转换为 system_prompt 追加内容

        Args:
            include_content: 是否包含完整内容，默认 False（只包含摘要）

        Returns:
            prompt 字符串
        """
        if include_content:
            # 完整模式：直接返回内容
            return f"## Skill: {self.name}\n\n{self.content}"
        else:
            # 摘要模式：名称 + 描述
            return f"## Skill: {self.name}\n{self.description}"
    
    def to_full_prompt(self) -> str:
        """转换为完整 prompt（包含 SKILL.md 全部内容）"""
        return self.to_prompt(include_content=True)

    def get_reference(self, name: str) -> Optional[str]:
        """获取参考文档内容

        Args:
            name: 文档名称（可带或不带 .md 后缀）

        Returns:
            文档内容，不存在返回 None
        """
        for ref in self.references:
            if ref.name == name or ref.stem == name:
                return ref.read_text(encoding="utf-8")
        return None

    def list_references(self) -> List[str]:
        """列出所有参考文档名称"""
        return [ref.name for ref in self.references]

    def __repr__(self) -> str:
        scripts_count = len(self.scripts)
        refs_count = len(self.references)
        return f"Skill(name={self.name!r}, scripts={scripts_count}, refs={refs_count})"

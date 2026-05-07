"""
DocumentNode - 文档解析节点

基于 markitdown 将各种文档格式转换为 Markdown。

支持格式：
- PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx)
- HTML, 图片 (OCR), 音频 (转录) 等

Example:
    workflow.add_node(DocumentNode(
        id="parse_doc",
        input_key="document",
        output_key="doc_content",
    ))

依赖安装：
    pip install markitdown[all]
"""

from __future__ import annotations
from typing import Any, Dict, Optional, List, TYPE_CHECKING
from pathlib import Path

from agentclaw.node.custom import CustomNode
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# markitdown 实例缓存
_markitdown_instance = None


def _get_markitdown():
    """获取或创建 markitdown 实例"""
    global _markitdown_instance
    if _markitdown_instance is None:
        try:
            from markitdown import MarkItDown
            _markitdown_instance = MarkItDown()
        except ImportError:
            raise ImportError(
                "DocumentNode 需要 markitdown 库，请安装: pip install markitdown[all]"
            )
    return _markitdown_instance


class DocumentNode(CustomNode):
    """
    文档解析节点
    
    将文档文件转换为 Markdown 格式的文本。
    
    Args:
        id: 节点 ID
        input_key: state 中文档路径的 key，默认 "document"
        output_key: 解析结果存储的 key
        include_metadata: 是否包含文档元数据
        max_length: 最大输出长度（0 表示不限制）
    """
    
    def __init__(
        self,
        id: str,
        input_key: str = "document",
        include_metadata: bool = False,
        max_length: int = 0,
        **kwargs
    ):
        super().__init__(id, **kwargs)
        self.input_key = input_key
        self.include_metadata = include_metadata
        self.max_length = max_length
    
    def process(self, **state) -> Dict[str, Any]:
        """解析文档，支持单个路径、路径列表或文件 meta 列表"""
        doc_input = state.get(self.input_key)
        if not doc_input:
            logger.warning(f"DocumentNode: 未找到文档路径 (key={self.input_key})")
            return {self.get_output_key(): ""}

        # 支持多种输入格式:
        #   str          — 单个文件路径 (File 类型)
        #   list[str]    — 文件路径列表
        #   list[dict]   — 文件 meta 列表 (Files 类型: [{file_path, original_name, ...}])
        if isinstance(doc_input, list):
            paths = []
            for item in doc_input:
                if isinstance(item, dict):
                    paths.append(item.get("file_path") or item.get("path", ""))
                elif isinstance(item, str):
                    paths.append(item)
            results = [self._parse_file(p) for p in paths if p]
            combined = "\n\n---\n\n".join(r for r in results if r)
            return {self.get_output_key(): combined}
        else:
            content = self._parse_file(doc_input)
            return {self.get_output_key(): content}
    
    def _parse_file(self, file_path: str) -> str:
        """解析单个文件"""
        path = Path(file_path)
        
        if not path.exists():
            logger.warning(f"DocumentNode: 文件不存在: {file_path}")
            return ""
        
        try:
            md = _get_markitdown()
            result = md.convert(str(path))
            
            content = result.text_content if hasattr(result, 'text_content') else str(result)
            
            # 添加元数据
            if self.include_metadata:
                metadata = [
                    f"**文件名**: {path.name}",
                    f"**大小**: {path.stat().st_size} bytes",
                ]
                if hasattr(result, 'title') and result.title:
                    metadata.append(f"**标题**: {result.title}")
                content = "\n".join(metadata) + "\n\n" + content
            
            # 限制长度
            if self.max_length > 0 and len(content) > self.max_length:
                content = content[:self.max_length] + "\n\n... [内容已截断]"
            
            logger.info(f"DocumentNode: 解析完成 {path.name} ({len(content)} 字符)")
            return content
            
        except Exception as e:
            logger.error(f"DocumentNode: 解析失败 {file_path}: {e}")
            return f"[解析失败: {e}]"


class DocumentExtractNode(DocumentNode):
    """
    文档提取节点（带结构化提取）
    
    解析文档并提取特定信息。
    """
    
    def __init__(
        self,
        id: str,
        input_key: str = "document",
        extract_sections: Optional[List[str]] = None,
        extract_tables: bool = False,
        **kwargs
    ):
        super().__init__(id, input_key=input_key, **kwargs)
        self.extract_sections = extract_sections
        self.extract_tables = extract_tables
    
    def process(self, **state) -> Dict[str, Any]:
        """解析并提取"""
        result = super().process(**state)
        content = result.get(self.get_output_key(), "")
        
        extracted = {"full_content": content}
        
        if self.extract_sections:
            extracted["sections"] = self._extract_sections(content, self.extract_sections)
        
        if self.extract_tables:
            extracted["tables"] = self._extract_tables(content)
        
        return {self.get_output_key(): extracted}
    
    def _extract_sections(self, content: str, section_titles: List[str]) -> Dict[str, str]:
        """提取指定章节"""
        import re
        sections = {}
        for title in section_titles:
            pattern = rf'#+\s*{re.escape(title)}[^\n]*\n(.*?)(?=\n#+\s|\Z)'
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            sections[title] = match.group(1).strip() if match else ""
        return sections
    
    def _extract_tables(self, content: str) -> List[str]:
        """提取 Markdown 表格"""
        import re
        pattern = r'\|[^\n]+\|\n\|[-:\s|]+\|\n(?:\|[^\n]+\|\n?)+'
        return [m.strip() for m in re.findall(pattern, content)]

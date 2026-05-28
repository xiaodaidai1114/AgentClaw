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

from agentclaw.database import get_file_storage
from agentclaw.node.custom import CustomNode
from agentclaw.logger.config import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# markitdown 实例缓存
_markitdown_instance = None
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".amr"}


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
        asr_model_id: Optional[str] = None,
        audio_service: Optional[Any] = None,
        **kwargs
    ):
        super().__init__(id, **kwargs)
        self.input_key = input_key
        self.include_metadata = include_metadata
        self.max_length = max_length
        self.asr_model_id = asr_model_id
        self._audio_service = audio_service
    
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
            file_infos = self._normalize_file_inputs(doc_input)
            results = [self._parse_file(info["file_path"]) for info in file_infos if info.get("file_path")]
            combined = "\n\n---\n\n".join(r for r in results if r)
            return {self.get_output_key(): combined}
        else:
            file_info = self._normalize_file_input(doc_input)
            content = self._parse_file(file_info["file_path"]) if file_info.get("file_path") else ""
            return {self.get_output_key(): content}

    async def async_execute(self, state: dict, context) -> Dict[str, Any]:
        """解析文档；配置 ASR 时音频文件走异步转写。"""
        doc_input = state.get(self.input_key)
        if not doc_input:
            logger.warning(f"DocumentNode: 未找到文档路径 (key={self.input_key})")
            return {self.get_output_key(): ""}

        if isinstance(doc_input, list):
            file_infos = self._normalize_file_inputs(doc_input)
            results = [await self._parse_file_async(info, context) for info in file_infos if info.get("file_path")]
            combined = "\n\n---\n\n".join(r for r in results if r)
            return {self.get_output_key(): combined}

        file_info = self._normalize_file_input(doc_input)
        content = await self._parse_file_async(file_info, context) if file_info.get("file_path") else ""
        return {self.get_output_key(): content}

    def _normalize_file_inputs(self, items: list) -> List[Dict[str, Any]]:
        return [self._normalize_file_input(item) for item in items]

    def _normalize_file_input(self, item: Any) -> Dict[str, Any]:
        if isinstance(item, dict):
            path = item.get("file_path") or item.get("path") or ""
            return {
                "file_path": path,
                "original_name": item.get("original_name") or item.get("filename") or Path(path).name,
                "mime_type": item.get("mime_type") or item.get("content_type"),
                "size": item.get("size"),
            }
        if isinstance(item, str):
            return {
                "file_path": item,
                "original_name": Path(item).name,
                "mime_type": None,
                "size": None,
            }
        return {"file_path": "", "original_name": "", "mime_type": None, "size": None}

    async def _parse_file_async(self, file_info: Dict[str, Any], context) -> str:
        file_path = await self._resolve_file_path(file_info.get("file_path") or "")
        if file_path:
            file_info = {**file_info, "file_path": file_path}
        if self.asr_model_id and self._is_audio_file(file_info):
            return await self._transcribe_file(file_info, context)
        return self._parse_file(file_path)

    async def _resolve_file_path(self, file_path: str) -> str:
        if not file_path or Path(file_path).is_absolute():
            return file_path
        try:
            storage = get_file_storage()
            if storage:
                local_path = await storage.get_local_path_by_key(file_path)
                if local_path:
                    return local_path
        except Exception as e:
            logger.warning(f"DocumentNode: 解析存储文件路径失败 {file_path}: {e}")
        return file_path

    def _is_audio_file(self, file_info: Dict[str, Any]) -> bool:
        mime_type = str(file_info.get("mime_type") or "").strip().lower()
        if mime_type.startswith("audio/"):
            return True
        path = Path(str(file_info.get("file_path") or file_info.get("original_name") or ""))
        return path.suffix.lower() in _AUDIO_EXTENSIONS

    def _get_audio_service(self, context):
        if self._audio_service is not None:
            return self._audio_service
        llm_manager = getattr(context, "llm_manager", None)
        if not llm_manager:
            raise RuntimeError("DocumentNode ASR requires WorkflowContext.llm_manager")
        from agentclaw.audio import AudioService

        return AudioService(llm_manager)

    async def _transcribe_file(self, file_info: Dict[str, Any], context) -> str:
        file_path = file_info.get("file_path") or ""
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"DocumentNode: 文件不存在: {file_path}")
            return ""

        try:
            from agentclaw.audio import AudioArtifact

            artifact = AudioArtifact(
                data=path.read_bytes(),
                mime_type=file_info.get("mime_type"),
                filename=file_info.get("original_name") or path.name,
                ext=path.suffix.lower(),
            )
            service = self._get_audio_service(context)
            content = await service.transcribe(artifact, model_id=self.asr_model_id)
            if self.max_length > 0 and len(content) > self.max_length:
                content = content[:self.max_length] + "\n\n... [内容已截断]"
            logger.info(f"DocumentNode: ASR 解析完成 {path.name} ({len(content)} 字符)")
            return content
        except Exception as e:
            logger.error(f"DocumentNode: ASR 解析失败 {file_path}: {e}")
            return f"[解析失败: {e}]"
    
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

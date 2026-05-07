"""
知识库文档解析
"""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path
from typing import Optional

from agentclaw.knowledgebase.models import ParsedDocument


class DocumentParseError(RuntimeError):
    """Raised when a user-provided document cannot be parsed into text."""


_TEXT_SUFFIXES = {".txt", ".md", ".json", ".csv", ".py", ".yaml", ".yml"}
_OOXML_SUFFIXES = {
    ".docx": "Word",
    ".pptx": "PowerPoint",
    ".xlsx": "Excel",
}
_LEGACY_OFFICE_SUFFIXES = {
    ".doc": ".docx 或 PDF",
    ".ppt": ".pptx 或 PDF",
    ".xls": ".xlsx 或 CSV",
}


class MarkItDownParser:
    """基于 markitdown 的统一文档解析器。"""

    async def parse(self, file_path: str, display_name: Optional[str] = None) -> ParsedDocument:
        return await asyncio.to_thread(self._parse_sync, file_path, display_name)

    def _parse_sync(self, file_path: str, display_name: Optional[str] = None) -> ParsedDocument:
        path = Path(file_path)
        display_name = display_name or path.name
        suffix = path.suffix.lower()
        self._validate_file_container(path, suffix, display_name)

        try:
            from markitdown import MarkItDown  # type: ignore

            result = MarkItDown().convert(str(path))
            text = (getattr(result, "text_content", None) or "").strip()
            if not text:
                raise ValueError("markitdown returned empty content")
            return ParsedDocument(
                text=text,
                markdown=text,
                title=str(getattr(result, "title", "") or path.stem),
                metadata={
                    "source_path": str(path),
                    "suffix": suffix,
                },
                parser_name="markitdown",
            )
        except ImportError:
            if suffix in _TEXT_SUFFIXES:
                return self._parse_plain_text(path, suffix, display_name)
            raise RuntimeError(
                "markitdown 未安装，无法解析该文件。请安装知识库依赖：pip install 'agentclaw[knowledgebase]'"
            )
        except DocumentParseError:
            raise
        except Exception as exc:
            if suffix in _TEXT_SUFFIXES:
                return self._parse_plain_text(path, suffix, display_name)
            raise DocumentParseError(self._format_conversion_error(display_name, suffix, exc)) from exc

    def _validate_file_container(self, path: Path, suffix: str, display_name: str) -> None:
        if suffix in _OOXML_SUFFIXES and not zipfile.is_zipfile(path):
            raise DocumentParseError(
                f"无法解析文档 {display_name}：文件扩展名是 {suffix}，但内容不是有效的 Office Open XML 压缩包。"
                f"请确认文件未损坏，或使用 {_OOXML_SUFFIXES[suffix]} 重新另存为 {suffix} 后再上传。"
            )

    def _parse_plain_text(self, path: Path, suffix: str, display_name: str) -> ParsedDocument:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            raise DocumentParseError(f"无法解析文档 {display_name}：文本内容为空。")
        return ParsedDocument(
            text=text,
            markdown=text,
            title=path.stem,
            metadata={"source_path": str(path), "suffix": suffix},
            parser_name="plain_text",
        )

    def _format_conversion_error(self, display_name: str, suffix: str, exc: Exception) -> str:
        if suffix in _LEGACY_OFFICE_SUFFIXES:
            return (
                f"无法解析文档 {display_name}：该文件看起来是旧版 Office 二进制格式 {suffix}，"
                f"请另存为 {_LEGACY_OFFICE_SUFFIXES[suffix]} 后重新上传。"
            )
        detail = str(exc).strip() or exc.__class__.__name__
        if "BadZipFile" in detail or "File is not a zip file" in detail:
            return (
                f"无法解析文档 {display_name}：文件扩展名是 {suffix or '未知'}，但内容不是有效的 Office Open XML 压缩包。"
                "请确认文件未损坏，或将文件另存为正确格式后重新上传。"
            )
        return f"无法解析文档 {display_name}：MarkItDown 无法转换该文件。原因：{detail}"

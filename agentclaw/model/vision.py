"""
Vision - 图像处理模块

支持：
- Base64 图像编码
- URL 图像引用
- 自动格式检测
- 多图像输入

使用方式:
    from agentclaw.model.vision import ImageInput, encode_image
    
    # URL 图像
    image = ImageInput.from_url("https://example.com/image.jpg")
    
    # 本地文件
    image = ImageInput.from_file("./image.png")
    
    # Base64
    image = ImageInput.from_base64(base64_str, media_type="image/png")
    
    # 在 LLM 调用中使用
    response = await llm.invoke(
        prompt="描述这张图片",
        images=[image],
    )
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Literal, Optional, Union
import base64
import mimetypes
from pathlib import Path

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)

# 支持的图像格式
SUPPORTED_FORMATS = {
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png": [".png"],
    "image/gif": [".gif"],
    "image/webp": [".webp"],
}

# 反向映射：扩展名 -> MIME 类型
EXT_TO_MIME = {}
for mime, exts in SUPPORTED_FORMATS.items():
    for ext in exts:
        EXT_TO_MIME[ext.lower()] = mime


@dataclass
class ImageInput:
    """
    图像输入
    
    支持两种格式：
    1. URL 引用：{"type": "image_url", "image_url": {"url": "https://..."}}
    2. Base64 内嵌：{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    """
    
    type: Literal["url", "base64"] = "url"
    url: Optional[str] = None
    base64_data: Optional[str] = None
    media_type: str = "image/jpeg"
    detail: Literal["auto", "low", "high"] = "auto"  # OpenAI 特有
    
    @classmethod
    def from_url(cls, url: str, detail: str = "auto") -> "ImageInput":
        """
        从 URL 创建图像输入
        
        Args:
            url: 图像 URL
            detail: 详细程度（auto/low/high）
        
        Example:
            image = ImageInput.from_url("https://example.com/cat.jpg")
        """
        return cls(type="url", url=url, detail=detail)
    
    @classmethod
    def from_file(cls, path: Union[str, Path], detail: str = "auto") -> "ImageInput":
        """
        从本地文件创建图像输入（自动 Base64 编码）
        
        Args:
            path: 本地文件路径
            detail: 详细程度
        
        Example:
            image = ImageInput.from_file("./screenshot.png")
        """
        file_path = Path(path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"图像文件不存在: {path}")
        
        # 检测 MIME 类型
        ext = file_path.suffix.lower()
        media_type = EXT_TO_MIME.get(ext)
        if not media_type:
            raise ValueError(f"不支持的图像格式: {ext}，支持: {list(EXT_TO_MIME.keys())}")
        
        # 读取并编码
        with open(file_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        
        logger.debug(f"编码图像: {path} ({media_type}, {len(data)} bytes)")
        
        return cls(
            type="base64",
            base64_data=data,
            media_type=media_type,
            detail=detail,
        )
    
    @classmethod
    def from_base64(
        cls,
        data: str,
        media_type: str = "image/jpeg",
        detail: str = "auto",
    ) -> "ImageInput":
        """
        从 Base64 字符串创建图像输入
        
        Args:
            data: Base64 编码的图像数据
            media_type: MIME 类型
            detail: 详细程度
        
        Example:
            image = ImageInput.from_base64(b64_str, "image/png")
        """
        # 移除可能的 data URL 前缀
        if data.startswith("data:"):
            # data:image/png;base64,xxxx
            parts = data.split(",", 1)
            if len(parts) == 2:
                header, data = parts
                if ";" in header:
                    media_type = header.split(":")[1].split(";")[0]
        
        return cls(
            type="base64",
            base64_data=data,
            media_type=media_type,
            detail=detail,
        )
    
    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        media_type: str = "image/jpeg",
        detail: str = "auto",
    ) -> "ImageInput":
        """
        从字节数据创建图像输入
        
        Args:
            data: 图像字节数据
            media_type: MIME 类型
            detail: 详细程度
        """
        b64_data = base64.b64encode(data).decode("utf-8")
        return cls(
            type="base64",
            base64_data=b64_data,
            media_type=media_type,
            detail=detail,
        )
    
    def to_openai_format(self) -> dict:
        """
        转换为 OpenAI API 格式
        
        Returns:
            OpenAI vision message content item
        """
        if self.type == "url":
            return {
                "type": "image_url",
                "image_url": {
                    "url": self.url,
                    "detail": self.detail,
                },
            }
        else:
            data_url = f"data:{self.media_type};base64,{self.base64_data}"
            return {
                "type": "image_url",
                "image_url": {
                    "url": data_url,
                    "detail": self.detail,
                },
            }
    
    def to_anthropic_format(self) -> dict:
        """
        转换为 Anthropic API 格式
        
        Returns:
            Anthropic vision message content item
        """
        if self.type == "url":
            # Anthropic 不直接支持 URL，需要下载
            raise ValueError("Anthropic 不支持 URL 图像，请使用 from_file 或 from_base64")
        
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": self.media_type,
                "data": self.base64_data,
            },
        }


def build_vision_messages(
    prompt: str,
    images: List[ImageInput],
    system_prompt: Optional[str] = None,
    provider: str = "openai",
) -> List[dict]:
    """
    构建包含图像的消息列表
    
    Args:
        prompt: 用户文本提示
        images: 图像列表
        system_prompt: 系统提示
        provider: LLM 提供商（openai/anthropic）
    
    Returns:
        消息列表
    
    Example:
        messages = build_vision_messages(
            prompt="这张图片里有什么？",
            images=[ImageInput.from_file("cat.jpg")],
        )
    """
    messages = []
    
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    
    if provider == "anthropic":
        # Anthropic 格式
        content = []
        for img in images:
            content.append(img.to_anthropic_format())
        content.append({"type": "text", "text": prompt})
        messages.append({"role": "user", "content": content})
    else:
        # OpenAI 格式（默认）
        content = []
        for img in images:
            content.append(img.to_openai_format())
        content.append({"type": "text", "text": prompt})
        messages.append({"role": "user", "content": content})
    
    return messages


# 便捷函数
def encode_image(path: Union[str, Path]) -> str:
    """
    编码本地图像为 Base64 data URL
    
    Args:
        path: 图像文件路径
    
    Returns:
        data URL 格式的字符串
    
    Example:
        data_url = encode_image("./image.png")
        # "data:image/png;base64,iVBORw0KGgo..."
    """
    img = ImageInput.from_file(path)
    return f"data:{img.media_type};base64,{img.base64_data}"


def image_from_url(url: str) -> ImageInput:
    """快捷函数：从 URL 创建图像"""
    return ImageInput.from_url(url)


def image_from_file(path: str) -> ImageInput:
    """快捷函数：从文件创建图像"""
    return ImageInput.from_file(path)

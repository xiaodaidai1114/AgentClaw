# -*- coding: utf-8 -*-
"""
伪流式工具

将普通文本转换为 async iterator，模拟流式输出效果。
"""

import asyncio
import random
from typing import AsyncIterator


async def fake_stream(
    text: str,
    delay: float = 0.02,
    chunk_size: int = 1,
    randomize: bool = True,
    min_chunk: int = 1,
    max_chunk: int = 4,
    delay_variance: float = 0.5,
) -> AsyncIterator[str]:
    """
    将文本转换为伪流式输出，模拟 LLM 生成效果
    
    Args:
        text: 要输出的文本
        delay: 基础延迟（秒），默认 0.02 秒
        chunk_size: 固定每次输出的字符数（randomize=False 时使用）
        randomize: 是否启用随机模式（默认 True）
        min_chunk: 随机模式下最小 chunk 大小
        max_chunk: 随机模式下最大 chunk 大小
        delay_variance: 延迟随机波动比例（0-1），默认 0.5 表示 ±50%
    
    Yields:
        str: 文本片段
    
    Example:
        # 默认随机模式（更像真实 LLM）
        await output(fake_stream("你好，我是助手！"), save_to_context=True)
        
        # 固定模式
        await output(fake_stream("Hello!", randomize=False, chunk_size=2))
        
        # 自定义随机参数
        await output(fake_stream("内容", min_chunk=2, max_chunk=6, delay=0.03))
    """
    i = 0
    text_len = len(text)
    
    while i < text_len:
        if randomize:
            # 随机 chunk 大小
            size = random.randint(min_chunk, max_chunk)
            # 随机延迟（基础延迟 ± variance）
            actual_delay = delay * (1 + random.uniform(-delay_variance, delay_variance))
        else:
            size = chunk_size
            actual_delay = delay
        
        chunk = text[i:i + size]
        yield chunk
        i += size
        
        if i < text_len and actual_delay > 0:
            await asyncio.sleep(actual_delay)

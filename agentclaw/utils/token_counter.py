"""
Token 计数工具

使用 tiktoken 库计算消息的 token 数量
"""

from typing import List, Optional
import tiktoken

from agentclaw.logger.config import get_logger

logger = get_logger(__name__)


def count_messages_tokens(
    messages: List[dict],
    model: str = "gpt-4",
    exclude_system: bool = True
) -> int:
    """
    计算消息列表的 token 数

    Args:
        messages: 消息列表，格式为 [{"role": "user", "content": "..."}, ...]
        model: 模型名称，用于选择对应的 tokenizer
        exclude_system: 是否排除系统消息（默认 True）

    Returns:
        token 数量

    Note:
        这是一个估算值，实际 token 数可能因模型而异
    """
    try:
        # 获取对应模型的 encoding
        # 对于不支持的模型，使用 cl100k_base（GPT-4/GPT-3.5-turbo 的编码）
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            logger.debug(f"Model {model} not found in tiktoken, using cl100k_base")
            encoding = tiktoken.get_encoding("cl100k_base")

        num_tokens = 0

        for message in messages:
            if not isinstance(message, dict):
                continue

            role = message.get("role", "")

            # 如果需要排除系统消息
            if exclude_system and role == "system":
                continue

            # 每条消息的格式开销
            # 参考：https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb
            num_tokens += 4  # 每条消息约 4 tokens 的格式开销

            # 计算内容的 token 数
            content = message.get("content", "")
            if isinstance(content, str):
                num_tokens += len(encoding.encode(content))

            # 计算 role 的 token 数
            if role:
                num_tokens += len(encoding.encode(role))

        # 每次对话的额外开销
        num_tokens += 2

        return num_tokens

    except Exception as e:
        logger.error(f"Failed to count tokens: {e}")
        # 降级到简单估算：1 token ≈ 4 个字符
        total_chars = sum(
            len(msg.get("content", ""))
            for msg in messages
            if isinstance(msg, dict) and (not exclude_system or msg.get("role") != "system")
        )
        return total_chars // 4

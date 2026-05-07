"""
上下文压缩器 - Context Compressor

当上下文 token 数超过阈值时，自动压缩历史消息为摘要。
使用大模型进行智能摘要生成，保留关键信息。

压缩后上下文结构：
1. 系统提示词（保留）
2. 开场白（可选，保留）
3. 压缩摘要（一条消息，包含之前所有对话要点，由 LLM 生成）
"""

from typing import List, Dict, Any, Optional, Tuple
import json
import re

from agentclaw.logger.config import get_logger
from agentclaw.utils.token_counter import count_messages_tokens

logger = get_logger(__name__)

# 压缩提示词 - 用于让 LLM 生成摘要
COMPRESSION_PROMPT = """You are a professional conversation summarization assistant. Your task is to compress the following conversation history into a comprehensive summary that preserves all critical information.

## Summary Requirements

1. **Preserve User Requests**: Capture all key user requests, requirements, questions, and intentions
2. **Preserve Assistant Responses**: Keep important replies, conclusions, solutions, and decisions
3. **Preserve Tool Results**: Record critical tool outputs (file paths, execution results, errors, status codes)
4. **Preserve Context**: Maintain file contents, code snippets, configurations, and relevant background
5. **Remove Redundancy**: Eliminate greetings, repetitive phrases, and conversational filler
6. **Maintain Chronology**: Preserve the sequence of events and dependencies

## Output Format

Produce a structured summary with the following sections:

### Overview
Brief description of the conversation purpose and current state.

### Key Points
- Bullet list of critical facts, decisions, and outcomes
- Include file paths, variable names, and specific values
- Note any errors or exceptions encountered

### Conversation Flow
For each significant turn:
- User intent/request
- Actions taken (tools invoked, files modified)
- Results and outcomes

### Current State
- Active files being worked on
- Pending tasks or incomplete items
- Environment/context that may affect next steps

## Conversation History

{conversation_history}

## Generate Summary
"""


MEMORY_EXTRACTION_PROMPT = """You are maintaining a workflow-level memory.md file used as long-term memory for future conversations.

Extract ONLY general, stable, long-term memory from the context summary below.

Default to EMPTY. Do not write memory unless the summary contains facts that should remain useful across unrelated future conversations.

Keep:
- Stable user preferences, identities, communication style, standing constraints, and durable domain facts
- Stable project/workflow facts, file paths, APIs, schemas, conventions, and configuration details that are not tied to one task
- Explicitly stated long-term preferences or durable facts the user wants remembered

Discard:
- Temporary execution logs, token counts, greetings, transient status, one-off tool outputs, search workflow details, and redundant chatter
- Product search results, recommendation lists, prices, model comparisons, shopping candidates, ranking tables, and price-trend follow-ups unless the user explicitly says to remember them long term
- Details that are only useful inside the current compressed conversation
- "Possible future needs" inferred by the assistant
- Pending work, unfinished tasks, next steps, TODOs, commitments, and current-session plans

Output concise markdown bullets. If there is nothing worth long-term memory, output exactly: EMPTY

<context_summary>
{summary}
</context_summary>
"""


class ContextCompressor:
    """
    上下文压缩器

    压缩策略：
    1. 保留系统提示词（第一条消息，如果 role=system）
    2. 保留开场白（第二条消息，如果是 assistant 的欢迎消息，可选）
    3. 其余所有消息使用 LLM 压缩成一条摘要消息
    """

    def __init__(
        self,
        threshold: int = 100000,
        llm_manager: Optional[Any] = None,
        compression_model: Optional[str] = None,
    ):
        self.threshold = threshold
        self.llm_manager = llm_manager
        self.compression_model = compression_model  # 可选：指定用于压缩的模型

    def should_compress(self, messages: List[Dict[str, Any]], estimated_tokens: int = 0) -> bool:
        """判断是否需要压缩"""
        if estimated_tokens > 0:
            return estimated_tokens > self.threshold
        # 使用 token_counter 进行更准确的估算
        try:
            token_count = count_messages_tokens(messages, exclude_system=False)
            return token_count > self.threshold
        except Exception:
            # 降级到简单估算：平均每个 token 3-4 个字符（中文）
            total_chars = sum(len(str(m.get("content", ""))) for m in messages)
            estimated = total_chars // 3
            return estimated > self.threshold

    async def compress(
        self,
        messages: List[Dict[str, Any]],
        llm_manager: Optional[Any] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        压缩上下文

        Args:
            messages: 消息列表
            llm_manager: LLM 管理器实例（如果初始化时未提供）

        Returns:
            (compressed_messages, compression_info)
        """
        if len(messages) <= 2:
            return messages, {"compressed": False, "reason": "too_few_messages"}

        # 分离系统提示词
        system_msg = None
        idx = 0
        if messages and messages[0].get("role") == "system":
            system_msg = messages[0]
            idx = 1

        # 分离开场白（assistant 的第一条消息，通常是欢迎语）
        welcome_msg = None
        if idx < len(messages) and messages[idx].get("role") == "assistant":
            content = str(messages[idx].get("content", ""))
            # 判断是否是开场白（较短且没有工具调用）
            if len(content) < 500 and not messages[idx].get("tool_calls"):
                welcome_msg = messages[idx]
                idx += 1

        # 需要压缩的消息
        messages_to_compress = messages[idx:]
        if not messages_to_compress:
            return messages, {"compressed": False, "reason": "no_messages_to_compress"}

        # 使用 LLM 生成摘要
        manager = llm_manager or self.llm_manager
        if manager:
            summary = await self._generate_summary_with_llm(messages_to_compress, manager)
        else:
            # 降级到规则化摘要
            logger.warning("未提供 LLM 管理器，使用规则化摘要")
            summary = self._generate_summary_rules(messages_to_compress)

        # 构建压缩后的消息列表
        compressed = []
        if system_msg:
            compressed.append(system_msg)
        if welcome_msg:
            compressed.append(welcome_msg)

        # 添加压缩摘要消息
        compressed.append({
            "role": "assistant",
            "content": f"[Context Summary] Previous conversation summary:\n\n{summary}",
            "is_summary": True,
            "original_message_count": len(messages_to_compress),
        })

        compression_info = {
            "compressed": True,
            "original_count": len(messages),
            "compressed_count": len(compressed),
            "compressed_message_count": len(messages_to_compress),
            "summary_length": len(summary),
            "context_tokens": count_messages_tokens(compressed, exclude_system=True),
            "has_system": system_msg is not None,
            "has_welcome": welcome_msg is not None,
            "used_llm": manager is not None,
        }

        return compressed, compression_info

    async def generate_memory_update(
        self,
        summary: str,
        llm_manager: Optional[Any] = None,
    ) -> str:
        """Generate long-term memory markdown from a compression summary."""
        text = str(summary or "").strip()
        if not text:
            return ""

        manager = llm_manager or self.llm_manager
        if manager:
            try:
                response = await manager.invoke(
                    messages=[{"role": "user", "content": MEMORY_EXTRACTION_PROMPT.format(summary=text)}],
                    model_id=self.compression_model,
                )
                memory = response.content if hasattr(response, "content") else str(response)
                memory = memory.strip()
                if memory.upper() == "EMPTY":
                    return ""
                return self._normalize_memory_markdown(memory)
            except Exception as e:
                logger.warning(f"长期记忆提取失败，跳过写入 memory.md: {e}")
                return ""

        logger.warning("未提供 LLM 管理器，跳过长期记忆提取")
        return ""

    def _generate_memory_rules(self, summary: str) -> str:
        """No rule-based long-term memory extraction; use LLM judgement only."""
        return ""

    def _normalize_memory_markdown(self, text: str) -> str:
        """Normalize model output without making content decisions."""
        lines = []
        for line in str(text or "").splitlines():
            item = line.strip()
            if not item:
                continue
            lines.append(item)
        return "\n".join(lines)

    async def _generate_summary_with_llm(
        self,
        messages: List[Dict[str, Any]],
        llm_manager: Any,
    ) -> str:
        """使用 LLM 生成摘要"""
        # 构建对话历史文本
        conversation_text = self._format_messages_for_llm(messages)

        # 构建提示词
        prompt = COMPRESSION_PROMPT.format(
            conversation_history=conversation_text,
        )

        # 调用 LLM
        try:
            response = await llm_manager.invoke(
                messages=[{"role": "user", "content": prompt}],
                model_id=self.compression_model,  # 可能为 None，使用默认模型
            )

            # 提取响应内容
            if hasattr(response, "content"):
                summary = response.content
            elif isinstance(response, str):
                summary = response
            else:
                summary = str(response)

            # 清理摘要
            summary = summary.strip()
            return summary

        except Exception as e:
            logger.error(f"LLM 摘要生成失败: {e}")
            # 降级到规则化摘要
            return self._generate_summary_rules(messages)

    def _format_messages_for_llm(self, messages: List[Dict[str, Any]]) -> str:
        """将消息格式化为 LLM 可读的文本"""
        lines = []
        turn = 0

        for msg in messages:
            role = msg.get("role", "")
            content = str(msg.get("content", "")).strip()
            tool_calls = msg.get("tool_calls", [])

            if not content and not tool_calls:
                continue

            if role == "user":
                turn += 1
                lines.append(f"\n=== Turn {turn} ===")
                lines.append(f"[User] {content}")
            elif role == "assistant":
                if "[上下文摘要]" in content or "[Context Summary]" in content:
                    # 跳过之前的摘要
                    continue
                if tool_calls:
                    tool_info = []
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            func = tc.get("function", {})
                            name = func.get("name", "unknown")
                            args = func.get("arguments", "")
                            tool_info.append(f"{name}({args})")
                    if tool_info:
                        lines.append(f"[Assistant-Tool Calls] {', '.join(tool_info)}")
                if content:
                    lines.append(f"[Assistant] {content}")
            elif role == "tool":
                tool_name = msg.get("name", "tool")
                lines.append(f"[Tool-{tool_name} Result] {content[:500]}")

        return "\n".join(lines)

    def _generate_summary_rules(self, messages: List[Dict[str, Any]]) -> str:
        """
        使用规则化方法生成摘要（LLM 失败时的降级方案）
        """
        summary_parts = []
        turns = []
        current_turn = {"user": None, "assistant": None, "tools": []}

        for msg in messages:
            role = msg.get("role", "")
            content = str(msg.get("content", "")).strip()
            tool_calls = msg.get("tool_calls", [])

            if role == "user":
                if current_turn["user"] or current_turn["assistant"]:
                    turns.append(current_turn)
                    current_turn = {"user": None, "assistant": None, "tools": []}
                current_turn["user"] = content
            elif role == "assistant":
                current_turn["assistant"] = content
                if tool_calls:
                    current_turn["tools"] = tool_calls
            elif role == "tool":
                current_turn["tools"].append(content)

        if current_turn["user"] or current_turn["assistant"]:
            turns.append(current_turn)

        for i, turn in enumerate(turns, 1):
            user_input = turn.get("user", "")
            assistant_response = turn.get("assistant", "")
            tools = turn.get("tools", [])

            turn_summary = []

            if user_input:
                user_summary = self._extract_key_points(user_input, max_length=100)
                if user_summary:
                    turn_summary.append(f"User: {user_summary}")

            if tools:
                if isinstance(tools, list) and len(tools) > 0:
                    if isinstance(tools[0], dict):
                        tool_names = [tc.get("function", {}).get("name", "unknown") for tc in tools if isinstance(tc, dict)]
                        if tool_names:
                            turn_summary.append(f"Tools: {', '.join(tool_names)}")
                    else:
                        tool_results = [str(t)[:50] for t in tools if t]
                        if tool_results:
                            turn_summary.append(f"Results: {'; '.join(tool_results)}")

            if assistant_response:
                if "[上下文摘要]" in assistant_response or "[Context Summary]" in assistant_response:
                    continue
                assistant_summary = self._extract_key_points(assistant_response, max_length=150)
                if assistant_summary:
                    turn_summary.append(f"Assistant: {assistant_summary}")

            if turn_summary:
                summary_parts.append(f"[Turn {i}] " + " | ".join(turn_summary))

        full_summary = "\n".join(summary_parts)
        return full_summary

    def _extract_key_points(self, text: str, max_length: int = 100) -> str:
        """提取文本的关键点"""
        if not text:
            return ""

        text = text.strip()
        if len(text) <= max_length:
            return text

        sentences = re.split(r'[。！？\n]', text)
        result = ""
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if len(result) + len(sent) < max_length:
                result += sent + "；"
            else:
                break

        if not result:
            result = text[:max_length]

        return result.rstrip("；")


async def compress_context(
    messages: List[Dict[str, Any]],
    conversation_id: str,
    workflow_id: str,
    threshold: int = 100000,
    checkpointer: Optional[Any] = None,
    llm_manager: Optional[Any] = None,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    压缩上下文并更新数据库

    Args:
        messages: 当前消息列表
        conversation_id: 会话 ID
        workflow_id: 工作流 ID
        threshold: 压缩阈值（token 数）
        checkpointer: 可选的 checkpointer 实例
        llm_manager: LLM 管理器实例（用于生成摘要）

    Returns:
        (messages, compression_info) - 如果未压缩，compression_info 为 None
    """
    compressor = ContextCompressor(threshold=threshold)

    if not compressor.should_compress(messages):
        return messages, None

    logger.info(f"触发上下文压缩: conversation={conversation_id}, messages={len(messages)}")

    # 执行压缩
    compressed_msgs, info = await compressor.compress(messages, llm_manager=llm_manager)

    if not info.get("compressed"):
        return messages, None

    # 更新数据库
    if checkpointer and conversation_id:
        try:
            # 转换为 LangChain 消息格式存储
            lc_messages = []
            for m in compressed_msgs:
                msg_type = m.get("role", "user")
                content = m.get("content", "")
                if msg_type == "system":
                    lc_messages.append(("system", content))
                elif msg_type == "user":
                    lc_messages.append(("human", content))
                elif msg_type == "assistant":
                    lc_messages.append(("ai", content))
                elif msg_type == "tool":
                    lc_messages.append(("tool", content))

            # 保存到 checkpointer
            await checkpointer.aput(
                (conversation_id,),
                {"messages": lc_messages, "compressed": True, "compression_info": info},
            )

            logger.info(f"上下文已压缩并保存: {info}")

        except Exception as e:
            logger.error(f"保存压缩上下文失败: {e}")
            # 即使保存失败，也返回压缩后的消息

    return compressed_msgs, info

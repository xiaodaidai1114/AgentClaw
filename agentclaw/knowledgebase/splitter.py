"""
知识库文本切分
"""

from __future__ import annotations

from typing import List

from agentclaw.knowledgebase.models import ChunkPayload


class TextChunker:
    """简单但稳定的段落级切分器。"""

    def __init__(self, chunk_size: int = 1200, chunk_overlap: int = 200):
        self.chunk_size = max(200, int(chunk_size))
        self.chunk_overlap = max(0, int(chunk_overlap))
        self._encoding = None

    def split(self, text: str) -> List[ChunkPayload]:
        cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not cleaned:
            return []

        paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [cleaned]

        chunks: List[ChunkPayload] = []
        current = ""

        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if not current or self._count_tokens(candidate) <= self.chunk_size:
                current = candidate
                continue

            chunks.append(self._build_chunk(len(chunks), current))
            overlap_text = self._tail_by_tokens(current, self.chunk_overlap)
            current = f"{overlap_text}\n\n{paragraph}".strip() if overlap_text else paragraph

            # 极长段落兜底：继续按 token 窗口切
            while self._count_tokens(current) > self.chunk_size:
                head = self._head_by_tokens(current, self.chunk_size)
                chunks.append(self._build_chunk(len(chunks), head))
                tail = self._tail_after_head(current, head)
                overlap_text = self._tail_by_tokens(head, self.chunk_overlap)
                current = f"{overlap_text}\n\n{tail}".strip() if tail else overlap_text.strip()
                if not current:
                    break

        if current.strip():
            chunks.append(self._build_chunk(len(chunks), current))

        return chunks

    def _build_chunk(self, chunk_index: int, content: str) -> ChunkPayload:
        return ChunkPayload(
            chunk_index=chunk_index,
            content=content.strip(),
            token_count=self._count_tokens(content),
            metadata={"length": len(content)},
        )

    def _get_encoding(self):
        if self._encoding is not None:
            return self._encoding
        try:
            import tiktoken

            self._encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoding = False
        return self._encoding

    def _count_tokens(self, text: str) -> int:
        encoding = self._get_encoding()
        if not encoding:
            return max(1, len(text) // 4)
        return len(encoding.encode(text))

    def _tail_by_tokens(self, text: str, token_limit: int) -> str:
        if token_limit <= 0 or not text:
            return ""
        encoding = self._get_encoding()
        if not encoding:
            approx_chars = token_limit * 4
            return text[-approx_chars:]
        tokens = encoding.encode(text)
        return encoding.decode(tokens[-token_limit:])

    def _head_by_tokens(self, text: str, token_limit: int) -> str:
        encoding = self._get_encoding()
        if not encoding:
            return text[: token_limit * 4]
        tokens = encoding.encode(text)
        return encoding.decode(tokens[:token_limit])

    def _tail_after_head(self, full_text: str, head: str) -> str:
        if not head:
            return full_text
        if full_text.startswith(head):
            return full_text[len(head):].strip()
        return full_text.replace(head, "", 1).strip()

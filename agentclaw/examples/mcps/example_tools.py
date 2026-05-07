"""Service-published MCP tools for the examples project.

This file demonstrates the lightweight AgentClaw MCP publishing path:

1. Build a normal ``ToolKit`` with Python functions.
2. Publish the toolkit into AgentClaw's built-in MCP service routes.
3. Reuse the same tools from workflows or remote MCP clients.

The tools are intentionally deterministic and dependency-free so the example can
run in a fresh project without extra services.
"""

from __future__ import annotations

import re
from collections import Counter

from agentclaw import ToolKit, publish_mcp_toolkit


toolkit = ToolKit()


def _split_terms(text: str) -> list[str]:
    return re.findall(r"[\w\u4e00-\u9fff]+", text.lower())


@toolkit.tool
async def analyze_text(text: str, focus: str = "") -> dict:
    """Analyze plain text and return deterministic metrics, keywords, and simple risk signals.

    Args:
        text: Text to analyze.
        focus: Optional analysis focus.
    """
    normalized = text or ""
    terms = _split_terms(normalized)
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "for",
        "in",
        "is",
        "of",
        "the",
        "to",
        "with",
        "一个",
        "以及",
        "这个",
        "我们",
        "需要",
    }
    keyword_counts = Counter(term for term in terms if len(term) > 1 and term not in stop_words)

    risk_terms = {
        "error",
        "failed",
        "failure",
        "warning",
        "denied",
        "timeout",
        "exception",
        "错误",
        "失败",
        "告警",
        "拒绝",
        "超时",
        "异常",
        "风险",
    }
    matched_risk_terms = sorted({term for term in terms if term in risk_terms})
    risk_level = "high" if len(matched_risk_terms) >= 3 else "medium" if matched_risk_terms else "low"

    return {
        "focus": focus or "general",
        "characters": len(normalized),
        "lines": len(normalized.splitlines()) or 1,
        "terms": len(terms),
        "sentences": len(re.findall(r"[。！？.!?]+", normalized)) or 1,
        "top_keywords": [
            {"term": term, "count": count}
            for term, count in keyword_counts.most_common(8)
        ],
        "risk_level": risk_level,
        "risk_terms": matched_risk_terms,
    }


@toolkit.tool
async def build_markdown_report(
    title: str,
    summary: str,
    findings: str = "",
    recommendations: str = "",
) -> str:
    """Build a concise Markdown report from a title, summary, findings, and recommendations.

    Args:
        title: Markdown report title.
        summary: Short report summary.
        findings: Findings separated by newlines or semicolons.
        recommendations: Recommendations separated by newlines or semicolons.
    """
    def split_items(value: str) -> list[str]:
        return [
            item.strip(" -\t")
            for item in re.split(r"[\n；;]+", value or "")
            if item.strip(" -\t")
        ]

    lines = [
        f"# {title.strip() or 'MCP Analysis Report'}",
        "",
        "## Summary",
        summary.strip() or "No summary provided.",
    ]

    finding_items = split_items(findings)
    if finding_items:
        lines.extend(["", "## Findings"])
        lines.extend(f"- {item}" for item in finding_items)

    recommendation_items = split_items(recommendations)
    if recommendation_items:
        lines.extend(["", "## Recommendations"])
        lines.extend(f"- {item}" for item in recommendation_items)

    return "\n".join(lines).rstrip() + "\n"


publish_mcp_toolkit(toolkit, server="examples-tools", overwrite=True)

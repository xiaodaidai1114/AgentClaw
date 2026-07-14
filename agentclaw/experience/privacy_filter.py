"""
隐私脱敏 - 默认对敏感信息脱敏

覆盖 8 类敏感信息：
- 正则精确匹配：email / 手机号 / 身份证号 / 银行卡号
- key=value 密钥：api_key / token / password / secret 等
- 字典敏感 key：address / phone / id_card 等字段名

脱敏默认开启（EventLogger 写入前过滤）。宁可多打码，保护企业数据安全。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple


# 正则可精确匹配的敏感信息（编译一次复用）
_TEXT_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # email
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "email"),
    # 中国手机号
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "phone"),
    # 身份证号（18 位）
    (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "id_card"),
    # 银行卡号（16-19 位连续数字）
    (re.compile(r"(?<!\d)\d{16,19}(?!\d)"), "bank_card"),
]

# key=value 形式的密钥：api_key / token / password / secret / bearer 等
_SECRET_PATTERN = re.compile(
    r"(?i)((?:api[_-]?key|apikey|access_token|token|password|passwd|pwd|secret[_-]?key|secret|bearer)\s*[:=]\s*)"
    r"['\"]?([^\s'\",;]+)"
)

# 字典中的敏感 key（含 address / phone 等字段名）
SENSITIVE_KEYS: Set[str] = {
    "password", "passwd", "pwd", "secret", "secret_key",
    "api_key", "apikey", "token", "access_token", "authorization",
    "address", "addr", "phone", "mobile", "id_card", "id_number",
    "bank_card", "card_number",
}


def mask_value(text: str, keep_start: int = 2, keep_end: int = 2, max_stars: int = 8) -> str:
    """打码：保留首尾字符，中间替换为 *（最多 max_stars 个）"""
    if not text:
        return text
    n = len(text)
    if n <= keep_start + keep_end:
        return "*" * n
    stars = min(n - keep_start - keep_end, max_stars)
    return text[:keep_start] + "*" * stars + text[-keep_end:]


def sanitize_text(text: str) -> str:
    """脱敏字符串：email / 手机号 / 身份证 / 银行卡 / 密钥"""
    if not isinstance(text, str) or not text:
        return text
    result = text
    for pat, _name in _TEXT_PATTERNS:
        result = pat.sub(lambda m: mask_value(m.group(0)), result)
    result = _SECRET_PATTERN.sub(lambda m: m.group(1) + mask_value(m.group(2)), result)
    return result


def sanitize_value(value: Any, sensitive_keys: Optional[Set[str]] = None) -> Any:
    """递归脱敏：str → sanitize_text；dict → sanitize_dict；list → 递归；其他原样"""
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return sanitize_dict(value, sensitive_keys)
    if isinstance(value, list):
        return [sanitize_value(v, sensitive_keys) for v in value]
    return value


def sanitize_dict(
    data: Dict[str, Any],
    sensitive_keys: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """脱敏字典：敏感 key 的值整值打码，其余字符串值做正则脱敏"""
    if not isinstance(data, dict):
        return data
    keys = SENSITIVE_KEYS if sensitive_keys is None else SENSITIVE_KEYS | set(sensitive_keys)
    result: Dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(k, str) and k.lower() in keys:
            # 敏感 key：整值打码，避免长度泄露更多信息
            result[k] = mask_value(str(v)) if v is not None else v
        else:
            result[k] = sanitize_value(v, sensitive_keys)
    return result


def has_sensitive_info(text: str) -> bool:
    """快速判断字符串是否含敏感信息（用于诊断/测试）"""
    if not isinstance(text, str) or not text:
        return False
    for pat, _name in _TEXT_PATTERNS:
        if pat.search(text):
            return True
    if _SECRET_PATTERN.search(text):
        return True
    return False

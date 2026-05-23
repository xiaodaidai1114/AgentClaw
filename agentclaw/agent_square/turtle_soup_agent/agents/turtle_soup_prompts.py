"""LLM protocol for the Turtle Soup example workflow.

This file intentionally keeps schemas and prompts together: they form the
contract between deterministic workflow code and model-driven nodes.
"""

from __future__ import annotations

import json
from typing import Any


PHASES = ("choose_type", "await_soup_confirmation", "playing", "solved")
INTENTS = (
    "type_choice",
    "soup_confirm",
    "soup_revision",
    "soup_regeneration",
    "question_judgement",
    "hint_request",
    "answer_attempt",
    "restart",
    "irrelevant_reply",
)
QUESTION_JUDGEMENT_ALLOWED = ("是", "否", "无关", "部分正确")
CLEARED_PHASE_RESULT = "__turtle_soup_cleared_phase_result__"
PHASE_RESULT_KEYS = (
    "solved_turn",
    "handle_irrelevant",
    "judge_answer",
    "generate_hint",
    "judge_question",
    "clarify_soup_confirmation",
    "regenerate_soup",
    "revise_soup",
    "confirm_soup_start",
    "soup_draft",
    "type_selection",
)

SESSION_STATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "phase",
        "soup_type",
        "difficulty",
        "soup_surface",
        "soup_solution",
        "truth_facts",
        "known_facts",
        "open_threads",
        "question_count",
        "hint_count",
        "answer_attempt_count",
        "last_feedback",
        "turn_history",
    ],
    "properties": {
        "phase": {"type": "string", "enum": list(PHASES)},
        "soup_type": {"type": "string"},
        "difficulty": {"type": "string", "enum": ["简单", "中等", "困难", ""]},
        "soup_surface": {"type": "string"},
        "soup_solution": {"type": "string"},
        "truth_facts": {"type": "array", "items": {"type": "string"}},
        "known_facts": {"type": "array", "items": {"type": "string"}},
        "open_threads": {"type": "array", "items": {"type": "string"}},
        "question_count": {"type": "integer", "minimum": 0},
        "hint_count": {"type": "integer", "minimum": 0},
        "answer_attempt_count": {"type": "integer", "minimum": 0},
        "last_feedback": {"type": "string"},
        "turn_history": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["user_input", "intent", "reply"],
                "properties": {
                    "user_input": {"type": "string"},
                    "intent": {"type": "string"},
                    "reply": {"type": "string"},
                    "verdict": {"type": ["string", "null"]},
                },
            },
            "description": "最近玩家输入与主持人回复，用于多轮指代消解和省略问题补全。",
        },
    },
}

PLAYER_TURN_CONTEXT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["user_input", "session", "reference_soups"],
    "properties": {
        "user_input": {"type": "string", "description": "玩家本轮输入原文"},
        "session": SESSION_STATE_SCHEMA,
        "reference_soups": {
            "type": "string",
            "description": "完整海龟汤参考题库，只能学习结构，不可直接照搬题目",
        },
    },
}

QUESTION_JUDGEMENT_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict"],
    "properties": {
        "verdict": {"type": "string", "enum": list(QUESTION_JUDGEMENT_ALLOWED)},
    },
}

OPENING_MESSAGE = """开场：欢迎来到海龟汤。

玩法很简单：我会先和你确认想玩的汤型，然后参考精品结构生成一个原创汤。你确认汤面后，游戏正式开始。

正式游戏中你可以：
- 向我提问，我只会回答：是 / 否 / 无关 / 部分正确
- 说“给我提示”，我会给一个不泄露汤底的方向提示
- 说“我猜答案是...”，我会判断是否完整命中

想玩什么类型？例如：悬疑、温情、反转、校园、科幻、职场、轻微诡异，或者你直接描述口味。"""

def _schema_for_prompt(schema: Any) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2, default=str).replace("{", "{{").replace("}", "}}")


TYPE_SELECTION_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "phase", "intent", "ready_to_draft", "soup_type", "tone", "session"],
    "properties": {
        "reply": {"type": "string"},
        "phase": {"type": "string", "enum": ["choose_type"]},
        "intent": {"type": "string", "enum": ["type_choice", "irrelevant_reply", "restart"]},
        "ready_to_draft": {"type": "boolean"},
        "soup_type": {"type": "string"},
        "tone": {"type": "string"},
        "session": SESSION_STATE_SCHEMA,
    },
}

SOUP_DRAFT_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "phase", "intent", "session"],
    "properties": {
        "reply": {"type": "string"},
        "phase": {"type": "string", "enum": ["await_soup_confirmation"]},
        "intent": {"type": "string", "enum": ["type_choice", "soup_regeneration"]},
        "session": SESSION_STATE_SCHEMA,
    },
}

SOUP_CONFIRMATION_INTENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "revision_request"],
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["confirm_start", "revise_soup", "regenerate_soup", "clarify_confirmation"],
        },
        "revision_request": {"type": "string"},
    },
}

CONFIRM_SOUP_START_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "phase", "intent", "session"],
    "properties": {
        "reply": {"type": "string"},
        "phase": {"type": "string", "enum": ["playing"]},
        "intent": {"type": "string", "enum": ["soup_confirm"]},
        "session": SESSION_STATE_SCHEMA,
    },
}

SOUP_REVISION_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "phase", "intent", "session"],
    "properties": {
        "reply": {"type": "string"},
        "phase": {"type": "string", "enum": ["await_soup_confirmation"]},
        "intent": {"type": "string", "enum": ["soup_revision", "soup_regeneration"]},
        "session": SESSION_STATE_SCHEMA,
    },
}

CLARIFY_CONFIRMATION_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "phase", "intent", "session"],
    "properties": {
        "reply": {"type": "string"},
        "phase": {"type": "string", "enum": ["await_soup_confirmation"]},
        "intent": {"type": "string", "enum": ["irrelevant_reply"]},
        "session": SESSION_STATE_SCHEMA,
    },
}

GAME_INTENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent"],
    "properties": {
        "intent": {"type": "string", "enum": ["question_judgement", "hint_request", "non_question"]},
    },
}

NON_QUESTION_INTENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent"],
    "properties": {
        "intent": {"type": "string", "enum": ["answer_attempt", "irrelevant_reply"]},
    },
}

HINT_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "phase", "intent", "session"],
    "properties": {
        "reply": {"type": "string"},
        "phase": {"type": "string", "enum": ["playing"]},
        "intent": {"type": "string", "enum": ["hint_request"]},
        "session": SESSION_STATE_SCHEMA,
    },
}

ANSWER_JUDGEMENT_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "phase", "intent", "is_correct", "session"],
    "properties": {
        "reply": {"type": "string"},
        "phase": {"type": "string", "enum": ["playing", "solved"]},
        "intent": {"type": "string", "enum": ["answer_attempt"]},
        "is_correct": {"type": "boolean"},
        "session": SESSION_STATE_SCHEMA,
    },
}

IRRELEVANT_REPLY_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "phase", "intent", "session"],
    "properties": {
        "reply": {"type": "string"},
        "phase": {"type": "string", "enum": ["playing"]},
        "intent": {"type": "string", "enum": ["irrelevant_reply"]},
        "session": SESSION_STATE_SCHEMA,
    },
}

SOLVED_TURN_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "phase", "intent", "session"],
    "properties": {
        "reply": {"type": "string"},
        "phase": {"type": "string", "enum": ["choose_type", "await_soup_confirmation", "solved"]},
        "intent": {"type": "string", "enum": ["restart", "type_choice", "irrelevant_reply"]},
        "session": SESSION_STATE_SCHEMA,
    },
}

INTENT_CLASSIFIER_SYSTEM_PROMPT = """你是海龟汤游戏主持人的意图识别器。每轮都要把玩家输入识别为 JSON 字段 intent，且只能取下列枚举：
- type_choice: 玩家在选择或描述想玩的海龟汤类型
- soup_confirm: 玩家确认使用当前汤面并开始游戏
- soup_revision: 玩家要求调整当前汤面，例如更悬疑、更短、更日常、更黑暗、更合理
- soup_regeneration: 玩家要求重新生成一题
- question_judgement: 玩家在正式游戏中提出一个可用“是/否/无关/部分正确”判定的问题
- hint_request: 玩家要求提示
- answer_attempt: 玩家尝试直接给出完整答案或解释汤底
- restart: 玩家想开启下一轮
- irrelevant_reply: 其他无关回复
"""

QUESTION_JUDGEMENT_SYSTEM_PROMPT = """正式游戏中，如果意图是 question_judgement，你必须根据完整汤底判断玩家问题。
回复仅能输出以下四个之一，不能添加任何解释、标点或额外文字：
是
否
无关
部分正确
"""

HINT_SYSTEM_PROMPT = """当玩家请求提示时，生成一个不要泄露汤底的提示。
提示必须能把玩家引向正确方向，但不能直接说出关键身份、关键动机、关键时间线或完整谜底。
"""

SOUP_GENERATION_SYSTEM_PROMPT = """生成原创海龟汤时必须：
- 参考 reference_soups 的完整题库结构、叙事节奏、信息隐藏方式和黑暗程度，但不能复用原题人物、场景、机关或谜底。
- 生成完整内部信息：soup_type、difficulty、soup_surface、soup_solution、truth_facts、open_threads。
- reply 只能展示 soup_surface、类型、难度和确认问题，绝不展示 soup_solution 或 truth_facts。
- 故事逻辑自检：关键线索必须有清楚的信息获取路径，不能让角色知道自己无法观察、听见、收到或合理推断的信息。
- 事件时序必须闭合：角色的发现、判断、行动和结局要按可成立的先后顺序发生，不能把后发生的证据当作前一行动的原因。
- 行动动机必须由当时已经获得的信息触发；汤面中的异常必须能被汤底解释，且玩家通过提问应能公平推理到核心反转。
- 不要把海龟汤强行改写得温情、友善或安全；如果玩家要求悬疑、惊悚、黑暗，可以保持海龟汤应有的压迫感。
- 避免现实可操作的犯罪教程、仇恨、色情内容；但允许虚构悬疑、死亡、欺骗、悔恨等海龟汤常见元素。
"""

ANSWER_JUDGEMENT_SYSTEM_PROMPT = """当玩家尝试直接作答时，判断是否完全命中汤底。
如果完全正确：给出正反馈，展示完整汤底，并总结玩家用了多少个问题、多少个提示，然后询问是否开启下一轮。
如果不完全正确：只说明还差哪些方向，例如身份、动机、时间线、因果关系；不能泄露答案事实。
"""

COMMON_CONTEXT_CONTRACT = f"""<CONTEXT_CONTRACT>
输入上下文必须视为 PLAYER_TURN_CONTEXT_SCHEMA：
PLAYER_TURN_CONTEXT_SCHEMA = {_schema_for_prompt(PLAYER_TURN_CONTEXT_SCHEMA)}

session 必须始终符合 SESSION_STATE_SCHEMA：
SESSION_STATE_SCHEMA = {_schema_for_prompt(SESSION_STATE_SCHEMA)}

session.turn_history 包含最近玩家输入和主持人回复。遇到“是三人吗”“那个人呢”“这个原因和钱有关吗”等省略或指代问题时，必须先参考 turn_history 补全问题主题，再基于汤底判定。
只能读取输入 JSON 中的 "user_input"、"session"、"reference_soups" 三个字段；不能假设其他隐式上下文。
</CONTEXT_CONTRACT>"""

TYPE_SELECTION_SYSTEM_PROMPT = f"""<ROLE>
你是海龟汤开局接待智能体，只负责判断玩家想玩什么类型。
</ROLE>

<TASK>
读取玩家输入。如果玩家已经给出类型、题材、风格或黑暗程度偏好，提取 soup_type 和 tone，并把 ready_to_draft 设为 true。
如果玩家没有给出足够偏好，reply 只询问玩家想玩哪类海龟汤，不要生成汤面。
</TASK>

{COMMON_CONTEXT_CONTRACT}

<OUTPUT_CONTRACT>
必须输出合法 JSON。不要输出 Markdown 代码块，不要输出前后解释。
TYPE_SELECTION_OUTPUT_SCHEMA = {_schema_for_prompt(TYPE_SELECTION_OUTPUT_SCHEMA)}
</OUTPUT_CONTRACT>
"""

SOUP_DRAFT_SYSTEM_PROMPT = f"""<ROLE>
你是海龟汤出题智能体，只负责生成一题原创海龟汤。
</ROLE>

<TASK>
根据 session 中的 soup_type/tone 和玩家偏好，参考 reference_soups 生成原创汤。
只输出一个候选汤：reply 展示类型、难度、完整汤面，并询问玩家是否使用；session 内保存完整 soup_solution 和 truth_facts。
</TASK>

{COMMON_CONTEXT_CONTRACT}

<SOUP_GENERATION>
{SOUP_GENERATION_SYSTEM_PROMPT}
生成时不要把海龟汤强行改得友善或柔和；黑暗悬疑题材可以保持原本张力。
</SOUP_GENERATION>

<HIDDEN_INFORMATION_POLICY>
不要在 reply 中泄露 soup_solution、truth_facts、known_facts 或内部推理。
玩家确认使用汤面之前，只能展示 soup_surface、类型、难度和确认问题。
</HIDDEN_INFORMATION_POLICY>

<OUTPUT_CONTRACT>
必须输出合法 JSON。不要输出 Markdown 代码块，不要输出前后解释。
SOUP_DRAFT_OUTPUT_SCHEMA = {_schema_for_prompt(SOUP_DRAFT_OUTPUT_SCHEMA)}
</OUTPUT_CONTRACT>
"""

SOUP_CONFIRMATION_INTENT_SYSTEM_PROMPT = f"""<ROLE>
你是海龟汤候选题确认意图分类器，只判断玩家对当前汤面的处理意图。
</ROLE>

<TASK>
读取 user_input，只输出以下四类之一：
- confirm_start: 玩家确认使用当前汤并开始游戏。
- revise_soup: 玩家想在当前汤基础上调整。
- regenerate_soup: 玩家想完全重新生成一题。
- clarify_confirmation: 玩家输入不清楚，或不是对候选汤的确认/调整/重生成。
</TASK>

{COMMON_CONTEXT_CONTRACT}

<OUTPUT_CONTRACT>
必须输出合法 JSON。不要输出 Markdown 代码块，不要输出前后解释。
SOUP_CONFIRMATION_INTENT_SCHEMA = {_schema_for_prompt(SOUP_CONFIRMATION_INTENT_SCHEMA)}
</OUTPUT_CONTRACT>
"""

CONFIRM_SOUP_START_SYSTEM_PROMPT = f"""<ROLE>
你是海龟汤开局确认节点，只负责把已确认的候选汤切换到正式游戏。
</ROLE>

<TASK>
将 session.phase 改为 playing。reply 重申汤面，并提示玩家可以开始通过问题推理。
不要修改 soup_solution、truth_facts、soup_surface。
</TASK>

{COMMON_CONTEXT_CONTRACT}

<HIDDEN_INFORMATION_POLICY>
不要在 reply 中泄露 soup_solution 或 truth_facts。
</HIDDEN_INFORMATION_POLICY>

<OUTPUT_CONTRACT>
必须输出合法 JSON。不要输出 Markdown 代码块，不要输出前后解释。
CONFIRM_SOUP_START_OUTPUT_SCHEMA = {_schema_for_prompt(CONFIRM_SOUP_START_OUTPUT_SCHEMA)}
</OUTPUT_CONTRACT>
"""

SOUP_REVISION_SYSTEM_PROMPT = f"""<ROLE>
你是海龟汤候选题修改/重生成节点，只负责产出新的候选汤。
</ROLE>

<TASK>
如果上游意图是 revise_soup，在当前汤基础上按玩家要求调整。
如果上游意图是 regenerate_soup，参考 reference_soups 完全重新生成一题。
reply 展示新汤面、类型、难度，并询问是否使用；session 内保存完整新汤底和 truth_facts。
</TASK>

{COMMON_CONTEXT_CONTRACT}

<SOUP_GENERATION>
{SOUP_GENERATION_SYSTEM_PROMPT}
</SOUP_GENERATION>

<HIDDEN_INFORMATION_POLICY>
不要在 reply 中泄露 soup_solution 或 truth_facts。
</HIDDEN_INFORMATION_POLICY>

<OUTPUT_CONTRACT>
必须输出合法 JSON。不要输出 Markdown 代码块，不要输出前后解释。
SOUP_REVISION_OUTPUT_SCHEMA = {_schema_for_prompt(SOUP_REVISION_OUTPUT_SCHEMA)}
</OUTPUT_CONTRACT>
"""

CLARIFY_CONFIRMATION_SYSTEM_PROMPT = f"""<ROLE>
你是海龟汤候选题确认澄清节点，只负责提示玩家如何继续。
</ROLE>

<TASK>
玩家没有明确确认、调整或重新生成。请简短说明可以回复“开始”“调整：...”或“重新生成”。
不要修改当前汤。
</TASK>

{COMMON_CONTEXT_CONTRACT}

<HIDDEN_INFORMATION_POLICY>
不要在 reply 中泄露 soup_solution 或 truth_facts。
</HIDDEN_INFORMATION_POLICY>

<OUTPUT_CONTRACT>
必须输出合法 JSON。不要输出 Markdown 代码块，不要输出前后解释。
IRRELEVANT_REPLY_OUTPUT_SCHEMA = {_schema_for_prompt(CLARIFY_CONFIRMATION_OUTPUT_SCHEMA)}
</OUTPUT_CONTRACT>
"""

GAME_INTENT_SYSTEM_PROMPT = f"""<ROLE>
你是海龟汤正式游戏意图分类器，只负责把玩家输入分成三类。
</ROLE>

<TASK>
根据 user_input 输出：
- question_judgement: 玩家提出可以用 是/否/无关/部分正确 回答的事实问题。
- hint_request: 玩家请求提示、线索或表示卡住了。
- non_question: 玩家不是在问事实问题，也不是请求提示；可能是在猜答案或闲聊。
如果 user_input 是承接上一轮的省略问题，例如“是三人吗”“那个人是他吗”“这个原因和钱有关吗”，必须结合 session.turn_history 识别为 question_judgement。
如果 user_input 是简短事实假设或确认句，只要能用 是/否/无关/部分正确 判定，也应识别为 question_judgement，即使没有问号或“吗”。
</TASK>

{COMMON_CONTEXT_CONTRACT}

<INTENT_ROUTING>
{INTENT_CLASSIFIER_SYSTEM_PROMPT}
优先级：直接猜完整经过的是 answer_attempt；请求线索的是 hint_request；可用事实判断推进谜底的封闭问题才是 question_judgement。
</INTENT_ROUTING>

<OUTPUT_CONTRACT>
必须输出合法 JSON。不要输出 Markdown 代码块，不要输出前后解释。
GAME_INTENT_SCHEMA = {_schema_for_prompt(GAME_INTENT_SCHEMA)}
</OUTPUT_CONTRACT>
"""

QUESTION_JUDGEMENT_SYSTEM_PROMPT = f"""<ROLE>
你是海龟汤问题判定节点，只处理玩家提出的事实问题。
</ROLE>

<TASK>
根据 session.soup_solution 和 truth_facts 判定玩家问题，结果只能是：是、否、无关、部分正确。
如果玩家问题承接上一轮，例如“是三人吗”，必须使用 session.turn_history 补全被省略的主题后再判定。
仅能输出这四个判定值之一到 verdict。
不要解释，不要补充，不要输出任何额外文本。
</TASK>

{COMMON_CONTEXT_CONTRACT}

<HIDDEN_INFORMATION_POLICY>
不要泄露汤底；不要解释判定理由。
</HIDDEN_INFORMATION_POLICY>

<OUTPUT_CONTRACT>
必须输出合法 JSON。不要输出 Markdown 代码块，不要输出前后解释。
QUESTION_JUDGEMENT_OUTPUT_SCHEMA = {_schema_for_prompt(QUESTION_JUDGEMENT_OUTPUT_SCHEMA)}
reply 必须只包含 verdict 本身，由渲染节点负责展示。
</OUTPUT_CONTRACT>
"""

HINT_SYSTEM_PROMPT = f"""<ROLE>
你是海龟汤提示生成节点，只处理玩家请求提示的情况。
</ROLE>

<TASK>
生成一个不揭示谜底、但能引导用户正确方向的提示。提示应根据 hint_count 逐步变得更具体。
必须参考 session.turn_history，避免重复玩家已经确认的事实；优先提示最近卡住的问题方向。
</TASK>

{COMMON_CONTEXT_CONTRACT}

<HIDDEN_INFORMATION_POLICY>
不要泄露汤底。不要泄露 soup_solution、truth_facts 的完整答案；不要直接说出关键身份、关键动机、关键时间线或完整谜底。
</HIDDEN_INFORMATION_POLICY>

<OUTPUT_CONTRACT>
必须输出合法 JSON。不要输出 Markdown 代码块，不要输出前后解释。
HINT_OUTPUT_SCHEMA = {_schema_for_prompt(HINT_OUTPUT_SCHEMA)}
</OUTPUT_CONTRACT>
"""

NON_QUESTION_CLASSIFIER_SYSTEM_PROMPT = f"""<ROLE>
你是海龟汤非问题分类器，只处理正式游戏中既不是问题判定、也不是提示请求的输入。
</ROLE>

<TASK>
判断玩家输入是：
- answer_attempt: 玩家正在尝试回答完整汤底或解释事件经过。
- irrelevant_reply: 玩家闲聊、偏离玩法、表达情绪、或输入无法作为答案。
如果玩家输入承接上一轮上下文但不是完整答案，例如“是三人吗”“那个人是他吗”，应避免误判为 answer_attempt，并结合 session.turn_history 判断是否属于上一轮问题延续。
</TASK>

{COMMON_CONTEXT_CONTRACT}

<OUTPUT_CONTRACT>
必须输出合法 JSON。不要输出 Markdown 代码块，不要输出前后解释。
NON_QUESTION_INTENT_SCHEMA = {_schema_for_prompt(NON_QUESTION_INTENT_SCHEMA)}
</OUTPUT_CONTRACT>
"""

ANSWER_JUDGEMENT_SYSTEM_PROMPT = f"""<ROLE>
你是海龟汤答案判定节点，只判断玩家是否完整回答了汤底。
</ROLE>

<TASK>
根据 session.soup_solution 和 truth_facts 判断玩家答案是否已经解释清楚汤面。truth_facts 是参考素材，不是逐条必答清单；不要求逐条命中 truth_facts。

判定正确的标准：
- 核心反转：玩家说清最主要的身份、角色、认知或事件反转。
- 关键证据：玩家说清导致真相暴露的关键线索或机制。
- 主要因果链：玩家能把汤面里的异常行为和后果连起来。
- 结局原因：玩家解释了为什么最后会出现汤面结局。

如果玩家答案覆盖以上核心要素，即使没有逐字复述 soup_solution，也应判为正确。动机、因果或风险如果能从玩家答案中合理推出或自然蕴含，不要重复列为缺失。已有关键证据可解释警方逮捕时，不要要求玩家逐步复述警方核查流程；不要仅因缺少主动报警的心理策略、辅助动机或自我包装细节而判错。不要要求题面或汤底未明确展开的旧案细节、幕后寄件人、精确时间线、人物姓名等附加背景。

如果正确：reply 给出正反馈，展示完整汤底，并总结用了多少问题和提示；phase 转为 solved，并问是否开启下一轮。
如果不完全正确：reply 只说明还差哪些核心类型的信息，例如身份反转、关键证据、主要因果链、结局原因；不要透露答案事实；phase 保持 playing。缺失反馈必须避免重复玩家已经答出的内容。
如果玩家连续作答，必须参考 session.turn_history 中最近的答案尝试和问题判定，判断本轮是否补足了之前缺失的信息。
</TASK>

{COMMON_CONTEXT_CONTRACT}

<HIDDEN_INFORMATION_POLICY>
答案不完全正确时，不要泄露 soup_solution 或 truth_facts 的具体事实。
</HIDDEN_INFORMATION_POLICY>

<OUTPUT_CONTRACT>
必须输出合法 JSON。不要输出 Markdown 代码块，不要输出前后解释。
ANSWER_JUDGEMENT_OUTPUT_SCHEMA = {_schema_for_prompt(ANSWER_JUDGEMENT_OUTPUT_SCHEMA)}
</OUTPUT_CONTRACT>
"""

IRRELEVANT_REPLY_SYSTEM_PROMPT = f"""<ROLE>
你是海龟汤无关回复处理节点，只负责把偏离玩法的输入拉回游戏。
</ROLE>

<TASK>
告诉用户可以：问问题、给出答案、或者寻求提示。不要推进游戏，不要泄露汤底。
必须参考 session.turn_history 中的最近对话，避免机械重复；如果用户是在延续上一轮但表达不清，应提示他可以把问题补完整。
</TASK>

{COMMON_CONTEXT_CONTRACT}

<OUTPUT_CONTRACT>
必须输出合法 JSON。不要输出 Markdown 代码块，不要输出前后解释。
IRRELEVANT_REPLY_OUTPUT_SCHEMA = {_schema_for_prompt(IRRELEVANT_REPLY_OUTPUT_SCHEMA)}
</OUTPUT_CONTRACT>
"""

SOLVED_TURN_SYSTEM_PROMPT = f"""<ROLE>
你是海龟汤结算后续智能体，只处理 solved 阶段。
</ROLE>

<TASK>
如果玩家想继续或选择新类型，清理旧汤并开启下一轮；如果玩家没有明确继续，询问是否开启下一轮。
不要继续用上一题汤底回答新问题。
</TASK>

{COMMON_CONTEXT_CONTRACT}

<OUTPUT_CONTRACT>
必须输出合法 JSON。不要输出 Markdown 代码块，不要输出前后解释。
SOLVED_TURN_OUTPUT_SCHEMA = {_schema_for_prompt(SOLVED_TURN_OUTPUT_SCHEMA)}
</OUTPUT_CONTRACT>
"""

PHASE_NODE_USER_PROMPT = """请处理以下玩家回合 JSON。严格读取 JSON 字段，不要把 JSON 当作玩家可见文本。
该 JSON 必须包含 "user_input"、"session"、"reference_soups" 三个字段。

{player_turn_context_json}
"""


LLM_NODE_SPECS = (
    ("type_selection", "识别玩家想玩的海龟汤类型", TYPE_SELECTION_SYSTEM_PROMPT, 0.2),
    ("soup_draft", "生成原创海龟汤候选题", SOUP_DRAFT_SYSTEM_PROMPT, 0.9),
    ("soup_confirmation_intent", "识别候选汤确认意图", SOUP_CONFIRMATION_INTENT_SYSTEM_PROMPT, 0.1),
    ("revise_soup", "按玩家反馈调整候选汤", SOUP_REVISION_SYSTEM_PROMPT, 0.7),
    ("regenerate_soup", "重新生成候选汤", SOUP_REVISION_SYSTEM_PROMPT, 0.9),
    ("clarify_soup_confirmation", "澄清候选汤确认输入", CLARIFY_CONFIRMATION_SYSTEM_PROMPT, 0.2),
    ("game_intent_classifier", "识别正式游戏输入意图", GAME_INTENT_SYSTEM_PROMPT, 0.1),
    ("judge_question", "判定玩家问题", QUESTION_JUDGEMENT_SYSTEM_PROMPT, 0.0),
    ("generate_hint", "生成不泄露谜底的提示", HINT_SYSTEM_PROMPT, 0.4),
    ("classify_non_question", "识别非问题是答案尝试还是无关回复", NON_QUESTION_CLASSIFIER_SYSTEM_PROMPT, 0.1),
    ("judge_answer", "判定玩家答案是否完整正确", ANSWER_JUDGEMENT_SYSTEM_PROMPT, 0.2),
    ("handle_irrelevant", "处理正式游戏中的无关回复", IRRELEVANT_REPLY_SYSTEM_PROMPT, 0.2),
    ("solved_turn", "已解答后的下一轮处理", SOLVED_TURN_SYSTEM_PROMPT, 0.3),
)

__all__ = [name for name in globals() if name.isupper()]

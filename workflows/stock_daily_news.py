"""
股市每日消息推送 Agent

功能:
- 每天早上获取实时股市数据
- 包含大盘指数、热门板块、涨跌幅榜、资金流向
- 用 LLM 整理成结构化日报
- 支持定时任务每日推送

数据来源:
- 使用新浪财经/东方财富等公开 API 获取 A 股行情
- 使用 akshare 库获取更丰富的金融数据

运行方式:
1. 注册工作流: 自动通过热注册完成
2. 手动测试: 通过 POST /api/workflow/run 调用
3. 定时任务: 通过 scheduler API 配置每日 9:00 执行
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

from agentclaw import Workflow, LLMNode, Input, CustomNode

# ============================================================
# Workflow 定义
# ============================================================
workflow = Workflow(
    id="stock_daily_news",
    name="股市每日消息推送",
    description="每天早上获取股市行情数据，自动生成结构化日报，包含大盘指数、热门板块、涨跌幅榜和市场分析。",
    welcome="📈 股市每日消息推送已启动！每天早上自动获取行情数据并生成日报。",
    timeout=240,
    recursion_limit=50,
    inputs=[
        Input("user_input", str, required=False, description="可选：指定关注的股票代码或板块，留空则获取全市场数据"),
    ],
    user_input="user_input",
)


# ============================================================
# 工具函数：获取股市数据
# ============================================================

@workflow.tool
def fetch_market_overview() -> str:
    """获取 A 股大盘指数行情（上证指数、深证成指、创业板指、科创50等）。

    Returns:
        JSON 字符串，包含各指数最新行情
    """
    import urllib.request
    import urllib.parse

    # 新浪财经指数行情 API
    codes = [
        "sh000001",  # 上证指数
        "sz399001",  # 深证成指
        "sz399006",  # 创业板指
        "sh000688",  # 科创50
        "sh000300",  # 沪深300
        "sh000016",  # 上证50
        "sz399005",  # 中小板指
        "sh000905",  # 中证500
    ]

    url = f"https://hq.sinajs.cn/list={','.join(codes)}"
    headers = {
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("gbk")
    except Exception as e:
        return json.dumps({"error": f"获取行情失败: {str(e)}"}, ensure_ascii=False)

    results = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        try:
            # 格式: var hq_str_sh000001="上证指数,3442.14,3428.83,3456.78,3468.10,3417.15,...";
            parts = line.split('="')
            if len(parts) < 2:
                continue
            code_name = parts[0].replace("var hq_str_", "").strip()
            data = parts[1].rstrip('";').split(",")
            if len(data) < 30:
                continue

            results.append({
                "code": code_name,
                "name": data[0],
                "current_price": float(data[1]) if data[1] else 0,
                "yesterday_close": float(data[2]) if data[2] else 0,
                "change": float(data[3]) if data[3] else 0,
                "change_pct": float(data[4]) if data[4] else 0,
                "high": float(data[5]) if data[5] else 0,
                "low": float(data[6]) if data[6] else 0,
                "volume": float(data[9]) if data[9] else 0,
                "amount": float(data[10]) if data[10] else 0,
            })
        except (ValueError, IndexError) as e:
            continue

    return json.dumps({"indices": results}, ensure_ascii=False)


@workflow.tool
def fetch_limit_up_stocks() -> str:
    """获取今日涨停/跌停股票列表。

    Returns:
        JSON 字符串，包含涨停和跌停股票
    """
    import urllib.request

    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = (
        "?pn=1&pz=30&po=1&np=1&fields=f12,f14,f2,f3,f4,f5,f6,f7,f15,f16,f17,f18"
        "&fid=f3&fs=m:90+t:3"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }

    req = urllib.request.Request(url + params, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return json.dumps({"error": f"获取涨跌停数据失败: {str(e)}"}, ensure_ascii=False)

    stocks = []
    items = data.get("data", {}).get("diff", [])
    for item in items[:20]:
        stocks.append({
            "code": item.get("f12", ""),
            "name": item.get("f14", ""),
            "price": item.get("f2", 0),
            "change_pct": item.get("f3", 0),
            "change_amount": item.get("f4", 0),
            "volume": item.get("f5", 0),
            "amount": item.get("f6", 0),
        })

    return json.dumps({"limit_up_stocks": stocks}, ensure_ascii=False)


@workflow.tool
def fetch_hot_sectors() -> str:
    """获取今日热门板块/行业板块涨跌幅排行。

    Returns:
        JSON 字符串，包含板块涨跌幅排行
    """
    import urllib.request

    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = (
        "?pn=1&pz=15&po=1&np=1&fields=f12,f14,f2,f3,f4,f5,f6,f7,f8,f9,f10,f20,f21"
        "&fid=f3&fs=m:90+t:2"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }

    req = urllib.request.Request(url + params, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return json.dumps({"error": f"获取板块数据失败: {str(e)}"}, ensure_ascii=False)

    sectors = []
    items = data.get("data", {}).get("diff", [])
    for item in items:
        sectors.append({
            "code": item.get("f12", ""),
            "name": item.get("f14", ""),
            "current_price": item.get("f2", 0),
            "change_pct": item.get("f3", 0),
            "change_amount": item.get("f4", 0),
            "volume": item.get("f5", 0),
            "amount": item.get("f6", 0),
            "up_count": item.get("f20", 0),
            "down_count": item.get("f21", 0),
        })

    return json.dumps({"hot_sectors": sectors}, ensure_ascii=False)


@workflow.tool
def fetch_money_flow() -> str:
    """获取今日主力资金流向（行业板块维度）。

    Returns:
        JSON 字符串，包含各行业资金流入流出排行
    """
    import urllib.request

    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = (
        "?pn=1&pz=10&po=1&np=1&fields=f12,f14,f62,f63,f64,f65,f66,f67,f68,f69,f70,f71,f72,f73,f78,f79"
        "&fid=f62&fs=m:90+t:2"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }

    req = urllib.request.Request(url + params, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return json.dumps({"error": f"获取资金流向数据失败: {str(e)}"}, ensure_ascii=False)

    flows = []
    items = data.get("data", {}).get("diff", [])
    for item in items:
        flows.append({
            "name": item.get("f14", ""),
            "main_net_inflow": item.get("f62", 0),
            "main_net_inflow_pct": item.get("f63", 0),
            "retail_net_inflow": item.get("f78", 0),
            "retail_net_inflow_pct": item.get("f79", 0),
        })

    return json.dumps({"money_flow": flows}, ensure_ascii=False)


@workflow.tool
def fetch_stock_news() -> str:
    """获取今日重要财经新闻和股市相关新闻。

    Returns:
        JSON 字符串，包含最新财经新闻列表
    """
    import urllib.request
    import urllib.parse

    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = (
        "?fltt=2&fields=f12,f14,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11"
        "&secids=1.000001,0.399001,0.399006,1.000688,1.000300"
        "&pos=0&count=5"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }

    try:
        # 尝试获取快讯新闻
        news_url = "https://np-anotice-stock.eastmoney.com/api/security/announcement/getannlist"
        news_params = (
            "?sr=-1&page_size=10&page_index=1&ann_type=SHA&stock_list="
        )
        news_req = urllib.request.Request(news_url + news_params, headers=headers)
        with urllib.request.urlopen(news_req, timeout=15) as resp:
            news_data = json.loads(resp.read().decode("utf-8"))
            news_items = news_data.get("data", {}).get("list", [])
            news_list = [{
                "title": n.get("title", ""),
                "date": n.get("notice_date", ""),
            } for n in news_items[:10]]
            return json.dumps({"news": news_list}, ensure_ascii=False)
    except Exception as e:
        # 备用：返回简单的市场快讯
        return json.dumps({"news": [], "note": f"新闻获取异常: {str(e)}"}, ensure_ascii=False)


@workflow.tool
def get_today_date() -> str:
    """获取当前日期和时间信息。

    Returns:
        当前日期字符串，包含年月日和星期
    """
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday = weekdays[now.weekday()]
    return json.dumps({
        "date": now.strftime("%Y-%m-%d"),
        "weekday": weekday,
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "is_trading_day": now.weekday() < 5,  # 周一到周五为交易日
    }, ensure_ascii=False)


# ============================================================
# 节点 1: 股市数据采集节点
# 并行获取所有数据源，汇总后传递给 LLM
# ============================================================

workflow.add_node(LLMNode(
    id="collect_data",
    description="采集股市数据",
    system_prompt="""你是一个股市数据采集助手。请使用以下工具获取今日股市数据：

1. fetch_market_overview - 获取大盘指数行情
2. fetch_limit_up_stocks - 获取涨跌停股票
3. fetch_hot_sectors - 获取热门板块排行
4. fetch_money_flow - 获取资金流向
5. fetch_stock_news - 获取财经新闻
6. get_today_date - 获取当前日期

请调用所有工具，获取完整数据。将获取到的所有数据以 JSON 格式汇总输出。""",
    user_prompt="请获取今日完整的股市数据。{user_input}",
    model_params={"temperature": 0.3, "max_tokens": 4096},
    save_to_context=False,
    tools=[
        "fetch_market_overview",
        "fetch_limit_up_stocks",
        "fetch_hot_sectors",
        "fetch_money_flow",
        "fetch_stock_news",
        "get_today_date",
    ],
    agent_style="agentic",
    enable_builtin_tools=False,
))


# ============================================================
# 节点 2: 生成股市日报
# 基于采集到的数据，用 LLM 生成结构化日报
# ============================================================

workflow.add_node(LLMNode(
    id="generate_report",
    description="生成股市日报",
    system_prompt="""你是一位专业的财经分析师。根据采集到的股市数据，生成一份结构清晰的**股市每日消息日报**。

## 日报格式要求

使用 Markdown 格式，包含以下章节：

### 📊 一、大盘回顾
- 列出主要指数（上证、深证、创业板、科创50、沪深300）的涨跌幅
- 用 📈 表示上涨，📉 表示下跌
- 简要总结今日大盘走势特征

### 🔥 二、热门板块
- 列出涨幅前 5 的板块
- 简要分析板块轮动情况

### ⭐ 三、涨停聚焦
- 列出部分涨停股票
- 分析涨停原因或所属热点概念

### 💰 四、资金流向
- 列出主力资金流入/流出前几的行业
- 分析资金偏好

### 📰 五、重要资讯
- 整理今日重要财经新闻
- 简要解读对市场的影响

### 💡 六、市场观点
- 综合以上数据，给出今日市场整体评价
- 提示风险或机会方向

## 写作风格
- 语言精炼、专业、客观
- 数据准确，用具体数字说话
- 适合快速阅读的日报风格
- 底部注明数据来源和免责声明

## 特殊情况
- 如果是非交易日，直接提示今日非交易日，并给出上一个交易日的简要回顾
- 如果数据获取失败，说明哪些数据不可用，基于已有数据生成日报""",
    user_prompt="""## 采集到的股市数据

{collect_data}

## 用户关注（如有）
{user_input}

请基于以上数据生成今日股市日报。""",
    model_params={"temperature": 0.5, "max_tokens": 4096},
    stream=True,
    output_to_user=True,
))


# ============================================================
# 边定义
# ============================================================

workflow.add_edge("__start__", "collect_data")
workflow.add_edge("collect_data", "generate_report")


# ============================================================
# 发布
# ============================================================

workflow.publish()


# ============================================================
# 手动测试入口
# ============================================================

if __name__ == "__main__":
    import asyncio

    async def main():
        print("=== 股市每日消息推送 - 手动测试 ===\n")
        result = await workflow.run({"user_input": ""})
        state = result["state"]
        print(f"\n--- 日报 ---\n{state.get('generate_report', '')}")

    asyncio.run(main())

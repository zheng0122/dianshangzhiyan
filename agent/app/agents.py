"""五个智能体 + 选题规划。
调用优先级：该智能体配置了 Coze Bot → 用 Coze；否则配置了 OpenAI 兼容模型 → 用模型；否则演示模式。
"""
import json
import re
from . import prompts, coze
from .llm import chat as llm_chat, extract_json, LLMError
from .config import settings
from .coze import CozeError

SYS_TAIL = "\n请使用简体中文。"


def backend(agent: str) -> str:
    if coze.configured(agent):
        return "coze"
    if not settings.llm_mock:
        return "llm"
    return "mock"


def providers() -> dict:
    return {a: backend(a) for a in ("wen", "chuang", "da", "fu", "xi")}


def _mock_flag(d: dict) -> dict:
    d["mock"] = True
    return d


def _text(agent: str, system: str, user: str, temperature=0.7, conv=None, plain=False, bot_key=None):
    """统一取文本回复。plain=True 时 Coze 直接发送用户原文（让 Bot 用自己的提示词）。返回 (text, meta)。"""
    be = backend(bot_key or agent)
    if be == "coze":
        msg = user if (plain or not settings.coze_structured or (bot_key or agent) in settings.coze_raw_agents) else f"{system}\n\n---\n{user}"
        r = coze.chat(settings.coze_bots[bot_key or agent], msg, conversation_id=conv)
        return r["answer"], {"suggestions": r["suggestions"], "conversation_id": r["conversation_id"]}
    return llm_chat(system, user, temperature), {}


def _json(agent: str, system: str, user: str, temperature=0.5, bot_key=None):
    """要求返回 JSON；解析失败返回 (None, 原文)。"""
    last = ""
    for i in range(2):
        txt, _ = _text(agent, system, user if i == 0 else user + "\n\n（只输出一个 JSON 对象，不要其他文字。）",
                       temperature, bot_key=bot_key)
        last = txt
        try:
            return extract_json(txt), txt
        except Exception:  # noqa
            continue
    return None, last


# ---------------- 云问 ----------------
def ask_wen(question: str, history=None, conversation_id=None) -> dict:
    be = backend("wen")
    if be == "mock":
        return _mock_flag({"answer": f"【依据】（演示模式）以下为示例回答。\n【操作步骤】1. 明确经营类目；2. 准备主体资质；3. 提交入驻申请。\n"
                                     f"【风险提醒】规则以平台官方最新公告为准。\n【下一步建议】先梳理资质清单。\n（你的问题：{question}）",
                           "suggestions": ["需要准备哪些资质？", "入驻要多久？", "有哪些费用？"]})
    if be == "coze":
        ctx = ""
        if not conversation_id:  # 没有会话 ID 时，把近几轮对话带上
            for h in (history or [])[-6:]:
                ctx += f"{h.get('role','user')}: {h.get('text','')}\n"
        txt, meta = _text("wen", prompts.WEN, (ctx + question).strip() if ctx else question, 0.4, conv=conversation_id, plain=True)
        return {"answer": txt, "suggestions": meta.get("suggestions", []), "conversation_id": meta.get("conversation_id")}
    ctx = "".join(f"{h.get('role','user')}: {h.get('text','')}\n" for h in (history or [])[-6:])
    txt, _ = _text("wen", prompts.WEN + SYS_TAIL, (ctx + f"用户问题：{question}").strip(), 0.4)
    return {"answer": txt, "suggestions": []}


# ---------------- 云创 ----------------
def _split_article(text: str) -> dict:
    """Bot 返回的是普通文案而非 JSON 时，尽量拆出标题/正文/话题。"""
    tags = re.findall(r"#([^\s#，,。]{1,20})", text)
    lines = [ln for ln in text.replace("\r", "").split("\n")]
    title = ""
    rest = []
    for ln in lines:
        clean = re.sub(r"^[#*\s>]+|[*\s]+$", "", ln)
        clean = re.sub(r"^(标题|题目)[:：]\s*", "", clean)
        if not title and clean:
            title = clean[:40]
            continue
        rest.append(ln)
    body = "\n".join(rest).strip()
    body = re.sub(r"(?m)^\s*(#\S+\s*)+$", "", body).strip()
    return {"title": title or "未命名", "digest": re.sub(r"\s+", "", body)[:50], "body": body or text, "hashtags": tags[:6]}


def create_content(platform: str, product: str, selling_points: str, audience: str, style: str) -> dict:
    be = backend("chuang")
    if be == "mock":
        return _mock_flag({"title": f"{product}｜值得一看的好物分享", "digest": f"{product}的真实使用分享",
                           "body": f"（演示模式）今天想和大家聊聊{product}。\n\n核心卖点：{selling_points}\n\n适合人群：{audience}",
                           "hashtags": [product, "好物分享", "种草"]})
    user = f"平台：{platform}\n商品名称：{product}\n核心卖点：{selling_points}\n目标人群：{audience}\n文案风格：{style}"
    d, raw = _json("chuang", prompts.CHUANG + SYS_TAIL, user, 0.8)
    if d is None:
        d = _split_article(raw)
        d["_fallback"] = True
    d["format"] = "text" if d.get("_fallback") else "json"
    d.pop("_fallback", None)
    d.setdefault("hashtags", [])
    d.setdefault("digest", "")
    return d


# ---------------- 云搭 ----------------
def _urls(text: str) -> list:
    """提取回复里的图片链接：Markdown 图片语法（不限后缀）+ 常见图片后缀的链接。"""
    t = text or ""
    md = re.findall(r"!\[[^\]]*\]\((https?://[^)\s]+)\)", t)
    ext = re.findall(r"https?://[^\s\"'\\)\]]+\.(?:png|jpg|jpeg|webp|gif)(?:\?[^\s\"'\\)\]]*)?", t, re.I)
    return list(dict.fromkeys(md + ext))[:6]


def outfit_plans(scene: str, category: str, budget: str, audience: str, style: str, bot: str = "1") -> dict:
    key = "da2" if (bot == "2" and settings.coze_bots.get("da2")) else "da"
    if backend(key) == "mock":
        return _mock_flag({"plans": [{"tag": "省钱", "name": "示例方案", "price_range": "¥200-300",
                                      "items": [{"name": "示例商品A", "price_range": "¥100-150", "role": "主体"}],
                                      "suitable": scene, "highlights": "（演示模式）", "sales_script": "（演示模式）"}]})
    user = f"使用场景：{scene}\n商品类型：{category}\n预算范围：{budget}\n目标人群：{audience}\n风格偏好：{style}"
    if backend(key) == "coze" and key in settings.coze_raw_agents:  # Bot 自带工作流：只调用一次，原样展示
        raw, _ = _text("da", prompts.DA, user, bot_key=key)
        return {"raw": raw, "images": _urls(raw), "format": "text"}
    d, raw = _json("da", prompts.DA + SYS_TAIL, user, 0.7, bot_key=key)
    if d and d.get("plans"):
        d["format"] = "json"
        return d
    return {"raw": raw, "images": _urls(raw), "format": "text"}


def da_image(text: str) -> dict:
    """调用云搭的 Coze 工作流生成「使用前后」效果图。参数模板见 COZE_WORKFLOW_DA_PARAMS。"""
    if not (settings.coze_token and settings.coze_workflow_da):
        raise ValueError("未配置 COZE_TOKEN / COZE_WORKFLOW_DA，无法生成效果图")
    try:
        tpl = json.loads(settings.coze_workflow_da_params)
    except Exception:  # noqa
        raise ValueError("COZE_WORKFLOW_DA_PARAMS 不是合法 JSON")
    params = {k: (v.replace("{text}", text) if isinstance(v, str) else v) for k, v in tpl.items()}
    return coze.run_workflow(settings.coze_workflow_da, params)


# ---------------- 云服 ----------------
def service_replies(conversation: list, shop: str = "1") -> dict:
    key = "fu2" if (shop == "2" and settings.coze_bots.get("fu2")) else "fu"
    if backend(key) == "mock":
        return _mock_flag({"category": "其他", "urgent": False,
                           "replies": [{"tone": t, "text": "（演示模式）示例回复"} for t in ["安抚语气", "问题判断", "解决方案", "补偿引导"]]})
    text = "\n".join(f"{c.get('role','客户')}: {c.get('text','')}" for c in conversation[-12:])
    d, raw = _json("fu", prompts.FU + SYS_TAIL, text, 0.5, bot_key=key)
    if d and d.get("replies"):
        d["format"] = "json"
        return d
    return {"raw": raw, "replies": [{"tone": "AI 回复", "text": raw}], "format": "text"}


# ---------------- 云析 ----------------
def analyze(range_label: str, metrics: dict) -> dict:
    if backend("xi") == "mock":
        return _mock_flag({"conclusion": "（演示模式）整体经营平稳。", "evidence": [f"输入数据：{json.dumps(metrics, ensure_ascii=False)[:80]}"],
                           "problems": ["（演示模式）"], "suggestions": [{"action": "（演示模式）示例建议", "priority": "中", "expected": "—"}]})
    user = f"统计周期：{range_label}\n指标数据(JSON)：{json.dumps(metrics, ensure_ascii=False)}"
    d, raw = _json("xi", prompts.XI + SYS_TAIL, user, 0.3)
    if d and d.get("conclusion"):
        d["format"] = "json"
        return d
    return {"raw": raw, "format": "text"}


# ---------------- 自动发布选题 ----------------
def plan_topic(profile: dict, history_titles: list) -> dict:
    products = profile.get("products") or [{"name": "主推商品", "selling_points": ["品质稳定"]}]
    key = "plan" if settings.coze_bots.get("plan") else "chuang"
    if backend(key) == "mock":
        p = products[len(history_titles) % len(products)]
        return _mock_flag({"topic": f"{p['name']}使用分享", "angle": "真实体验", "product": p["name"],
                           "selling_points": p.get("selling_points", []), "audience": profile.get("audience", "")})
    user = f"商家档案：{json.dumps(profile, ensure_ascii=False)}\n已发布标题：{json.dumps(history_titles[-30:], ensure_ascii=False)}"
    d, raw = _json("chuang", prompts.TOPIC + SYS_TAIL, user, 0.8, bot_key=key)
    if d and d.get("topic"):
        return d
    p = products[len(history_titles) % len(products)]  # Bot 没按 JSON 回复时，轮换主推商品兜底
    first = (raw or "").strip().split("\n")[0][:40] or f"{p['name']}使用分享"
    return {"topic": first, "angle": "", "product": p["name"], "selling_points": p.get("selling_points", []),
            "audience": profile.get("audience", "")}


# ---------------- 平台改写（小红书 / 抖音 辅助发布）----------------
def adapt_content(platform: str, title: str, body: str, tags=None) -> dict:
    if platform not in prompts.ADAPT:
        raise ValueError(f"不支持的平台：{platform}")
    if backend("chuang") == "mock":
        label = "小红书笔记" if platform == "xiaohongshu" else "抖音脚本"
        return _mock_flag({"title": title, "body": f"（演示模式·{label}）\n{body[:300]}", "hashtags": list(tags or [])[:5]})
    user = f"原标题：{title}\n原文：\n{body}"
    d, raw = _json("chuang", prompts.ADAPT[platform] + SYS_TAIL, user, 0.7)
    if d is None:
        d = _split_article(raw)
    d.setdefault("hashtags", [])
    return d

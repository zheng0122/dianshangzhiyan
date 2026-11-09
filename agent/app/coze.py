"""扣子（Coze）适配层：调用你在 Coze 上搭好的智能体 / 工作流。

对话：POST /v3/chat(stream=false) → 轮询 /v3/chat/retrieve → 读取 /v3/chat/message/list。
Bot 需要先在 Coze 里「发布」到 API 渠道，令牌用个人访问令牌（PAT）。
"""
import json
import re
import time
import requests
from .config import settings


class CozeError(Exception):
    pass


HINT = "（常见原因：令牌无效或过期；该 Bot 还没有发布到 API 渠道；Bot ID 填错）"


def configured(agent: str) -> bool:
    return bool(settings.coze_token and settings.coze_bots.get(agent))


def _headers():
    return {"Authorization": f"Bearer {settings.coze_token}", "Content-Type": "application/json"}


def _chk(resp, what):
    if not isinstance(resp, dict):
        raise CozeError(f"{what}失败：返回格式异常")
    if resp.get("code") not in (0, None):
        raise CozeError(f"{what}失败 code={resp.get('code')} msg={resp.get('msg')}{HINT}")
    return resp


def chat(bot_id: str, text: str, conversation_id=None, user_id: str = "dianshang-web",
         timeout: int = 120, poll: float = 0.8) -> dict:
    """返回 {answer, suggestions, conversation_id}。"""
    base = settings.coze_base_url
    params = {"conversation_id": conversation_id} if conversation_id else None
    body = {"bot_id": bot_id, "user_id": user_id, "stream": False, "auto_save_history": True,
            "additional_messages": [{"role": "user", "content": text, "content_type": "text"}]}
    try:
        r = requests.post(f"{base}/v3/chat", headers=_headers(), params=params, json=body, timeout=30).json()
    except requests.RequestException as e:
        raise CozeError(f"无法连接 Coze：{e}")
    d = _chk(r, "发起对话")["data"]
    chat_id, conv = d["id"], d["conversation_id"]
    q = {"conversation_id": conv, "chat_id": chat_id}
    deadline = time.time() + timeout
    status = d.get("status", "")
    while status not in ("completed",):
        if status in ("failed", "canceled", "requires_action"):
            err = (d.get("last_error") or {}).get("msg", "")
            raise CozeError(f"智能体运行{status}：{err}")
        if time.time() > deadline:
            raise CozeError("智能体响应超时")
        time.sleep(poll)
        rr = _chk(requests.get(f"{base}/v3/chat/retrieve", headers=_headers(), params=q, timeout=20).json(), "查询对话状态")
        d = rr["data"]
        status = d.get("status", "")
    ml = _chk(requests.get(f"{base}/v3/chat/message/list", headers=_headers(), params=q, timeout=20).json(), "读取回复")
    msgs = ml.get("data") or []
    answer = "\n".join(m.get("content", "") for m in msgs if m.get("type") == "answer").strip()
    sugg = [m.get("content", "").strip() for m in msgs if m.get("type") == "follow_up" and m.get("content")]
    if not answer:
        raise CozeError("智能体没有返回内容（请检查 Bot 是否正常、提示词是否会产生回复）")
    return {"answer": answer, "suggestions": sugg[:3], "conversation_id": conv}


def run_workflow(workflow_id: str, parameters: dict, timeout: int = 180) -> dict:
    """运行工作流，返回 {data, images}。images 为从结果中提取的图片链接。"""
    try:
        r = requests.post(f"{settings.coze_base_url}/v1/workflow/run", headers=_headers(),
                          json={"workflow_id": workflow_id, "parameters": parameters}, timeout=timeout).json()
    except requests.RequestException as e:
        raise CozeError(f"无法连接 Coze：{e}")
    _chk(r, "运行工作流")
    data = r.get("data")
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    imgs = re.findall(r"https?://[^\s\"'\\)\]]+\.(?:png|jpg|jpeg|webp|gif)(?:\?[^\s\"'\\)\]]*)?", text, re.I)
    if not imgs:  # 有些图片链接不带后缀，退而求其次取所有 http 链接
        imgs = re.findall(r"https?://[^\s\"'\\)\]]+", text)
    seen, uniq = set(), []
    for u in imgs:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return {"data": data, "images": uniq[:6]}

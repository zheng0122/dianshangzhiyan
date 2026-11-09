"""系统自检：逐个调用五个智能体并检查配置，帮助定位「页面和 Coze 搭建的 Bot 对不上」的问题。"""
import os
import sys
import time
from . import agents, workflow
from .config import settings
from .publisher import wechat


def _short(s, n=140):
    s = (s or "").replace("\n", " ").strip()
    return s[:n] + ("…" if len(s) > n else "")


def _sample(key, d):
    if key == "wen":
        return d.get("answer", "")
    if key == "chuang":
        return f"{d.get('title','')} | {d.get('body','')}"
    if key in ("da", "da2"):
        ps = d.get("plans") or []
        return (ps[0].get("name", "") + " " + ps[0].get("highlights", "")) if ps else d.get("raw", "")
    if key in ("fu", "fu2"):
        rs = d.get("replies") or []
        return rs[0].get("text", "") if rs else d.get("raw", "")
    return d.get("conclusion") or d.get("raw", "")


def run(check_wechat: bool = False) -> dict:
    tests = [
        ("wen", "云问", lambda: agents.ask_wen("请用一句话介绍你能帮商家做什么")),
        ("chuang", "云创", lambda: agents.create_content("小红书", "示例商品", "便携、轻巧", "上班族", "亲切自然")),
        ("da", "云搭", lambda: agents.outfit_plans("旅行", "行李箱", "¥500-1000", "上班族", "简约", "1")),
        ("fu", "云服", lambda: agents.service_replies([{"role": "客户", "text": "我的订单什么时候发货？"}], "1")),
        ("xi", "云析", lambda: agents.analyze("近7日", {"销售额": "¥10,000（环比+5%）", "订单数": "100（环比+3%）"})),
    ]
    if settings.coze_bots.get("da2"):
        tests.append(("da2", "云搭·Bot二", lambda: agents.outfit_plans("旅行", "行李箱", "¥500-1000", "上班族", "简约", "2")))
    if settings.coze_bots.get("fu2"):
        tests.append(("fu2", "云服·Bot二", lambda: agents.service_replies([{"role": "客户", "text": "我的订单什么时候发货？"}], "2")))
    out = []
    for key, name, fn in tests:
        be = agents.backend(key)
        item = {"key": key, "name": name, "backend": be, "ok": False, "ms": 0, "format": "", "sample": "", "error": ""}
        t0 = time.time()
        try:
            d = fn()
            item["ok"] = True
            item["format"] = "mock" if d.get("mock") else ("text" if key == "wen" else d.get("format", ""))
            item["sample"] = _short(_sample(key, d))
        except Exception as e:  # noqa
            item["error"] = str(e)[:300]
        item["ms"] = int((time.time() - t0) * 1000)
        out.append(item)
    cover_ok = bool(settings.wechat_thumb_media_id or (settings.wechat_cover_image and os.path.exists(settings.wechat_cover_image)))
    checks = [
        {"name": "Python 版本", "ok": sys.version_info >= (3, 8), "detail": sys.version.split()[0]},
        {"name": "Coze 令牌", "ok": bool(settings.coze_token), "detail": "已配置" if settings.coze_token else "未配置（功能将使用备用模型或演示模式）"},
        {"name": "管理口令 ADMIN_TOKEN", "ok": bool(settings.admin_token) and settings.admin_token != "换成一串随机字符", "detail": "已设置" if settings.admin_token else "未设置"},
        {"name": "公众号 AppID/AppSecret", "ok": bool(settings.wechat_appid and settings.wechat_secret),
         "detail": "已配置" if (settings.wechat_appid and settings.wechat_secret) else "未配置完整（缺 AppSecret 时无法写入草稿箱）"},
        {"name": "公众号封面图", "ok": cover_ok, "detail": "已配置" if cover_ok else "未找到封面图（WECHAT_COVER_IMAGE 路径或 WECHAT_THUMB_MEDIA_ID）"},
        {"name": "公众号发布方式", "ok": True, "detail": "默认直接提交发布" if settings.wechat_auto_publish else "默认只存草稿箱（计划里可单独选择直接发布）"},
        {"name": "飞书提醒", "ok": bool(settings.feishu_webhook), "detail": "已配置" if settings.feishu_webhook else "未配置（可选，仅影响推送提醒）"},
    ]
    if check_wechat:
        try:
            wechat.access_token()
            checks.append({"name": "公众号连通性", "ok": True, "detail": "已成功获取 access_token（AppID、AppSecret、IP 白名单均正常）"})
        except Exception as e:  # noqa
            checks.append({"name": "公众号连通性", "ok": False, "detail": str(e)[:300]})
    return {"agents": out, "checks": checks, "platforms": workflow.platforms_info()}

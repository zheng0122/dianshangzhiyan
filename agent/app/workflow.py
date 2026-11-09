"""自动发布流程：选题 → 生成 → 合规检查 → 待审核 → 审核通过 → 写入草稿箱/发布。"""
from __future__ import annotations

import json
import os
import datetime
import time
from . import agents, compliance, store
from .config import settings
from .publisher import wechat, notify


def load_profile() -> dict:
    try:
        with open(settings.profile_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa
        return {"shop_name": "示例店铺", "audience": "", "style": "亲切自然",
                "products": [{"name": "示例商品", "selling_points": ["品质稳定"]}], "banned_words": []}


def plan_and_generate() -> int:
    """生成 1 篇待审核内容，返回任务 id。"""
    store.init()
    profile = load_profile()
    titles = [t["title"] for t in store.list_tasks(limit=60)]
    topic = agents.plan_topic(profile, titles)
    content = agents.create_content("公众号", topic.get("product", ""), "、".join(topic.get("selling_points", [])),
                                    topic.get("audience") or profile.get("audience", ""), profile.get("style", ""))
    text = f"{content.get('title','')}\n{content.get('digest','')}\n{content.get('body','')}"
    issues = compliance.check(text, profile.get("banned_words"))
    tid = store.add_task(topic.get("topic", ""), content.get("title", "未命名"), content.get("digest", ""),
                         content.get("body", ""), content.get("hashtags", []), issues)
    store.add_event("review", f"新内容待审核：{content.get('title','')}", f"任务 #{tid}" + (f"，发现{len(issues)}处合规风险" if issues else ""), "publish")
    notify.feishu(f"【电商智研】新内容待审核 #{tid}：{content.get('title','')}"
                  + (f"（发现{len(issues)}处合规风险）" if issues else ""))
    if settings.skip_review and not issues:
        approve(tid)
        publish(tid)
    return tid


def approve(task_id: int, force: bool = False) -> dict:
    t = store.get(task_id)
    if not t:
        raise ValueError("任务不存在")
    if t["status"] not in ("pending_review", "failed"):
        raise ValueError(f"当前状态 {t['status']} 不能审核通过")
    if t["issues"] and not force:
        raise ValueError("内容存在合规风险，请先修改，或确认无误后使用 force=true")
    store.update(task_id, status="approved", error="")
    return store.get(task_id)


def reject(task_id: int) -> dict:
    store.update(task_id, status="rejected")
    return store.get(task_id)


def edit(task_id: int, title=None, digest=None, body=None) -> dict:
    t = store.get(task_id)
    if not t or t["status"] not in ("pending_review", "failed"):
        raise ValueError("只能编辑待审核或失败的任务")
    title = title if title is not None else t["title"]
    digest = digest if digest is not None else t["digest"]
    body = body if body is not None else t["body"]
    issues = compliance.check(f"{title}\n{digest}\n{body}", load_profile().get("banned_words"))
    store.update(task_id, title=title, digest=digest, body=body, issues=issues)
    return store.get(task_id)


def publish(task_id: int, direct=None) -> dict:
    """已审核通过的任务 → 公众号草稿箱；direct=True（或配置 WECHAT_AUTO_PUBLISH）时继续提交发布。
    直接发布失败（如账号没有发布权限）时内容仍保留在草稿箱，并在 error 里说明原因。"""
    t = store.get(task_id)
    if not t or t["status"] != "approved":
        raise ValueError("只有已审核通过的任务才能发布")
    direct = settings.wechat_auto_publish if direct is None else direct
    try:
        draft_id = wechat.add_draft(t["title"], t["digest"], t["body"])
        store.update(task_id, draft_id=draft_id, status="drafted", error="")
    except Exception as e:  # noqa
        store.update(task_id, status="failed", error=str(e)[:500])
        store.add_event("publish_failed", f"公众号写入草稿箱失败：{t['title']}", str(e)[:200], "publish")
        notify.feishu(f"【电商智研】发布失败 #{task_id}：{str(e)[:200]}")
        return store.get(task_id)
    if direct:
        return submit_draft(task_id)
    store.add_event("drafted", f"已写入公众号草稿箱：{t['title']}", "请到手机上确认发布", "publish")
    notify.feishu(f"【电商智研】已写入公众号草稿箱 #{task_id}：{t['title']}，请在手机上确认发布")
    return store.get(task_id)


def submit_draft(task_id: int) -> dict:
    """把草稿箱里的文章提交发布（需要公众号具备「发布能力」接口权限）。失败时保持草稿状态。"""
    t = store.get(task_id)
    if not t or t["status"] != "drafted" or not t.get("draft_id"):
        raise ValueError("只有已写入草稿箱的任务才能提交发布")
    try:
        pid = wechat.submit_publish(t["draft_id"])
        store.update(task_id, publish_id=pid, status="published", error="")
        store.add_event("published", f"已提交发布：{t['title']}", "可在「查询发布结果」里确认是否成功", "publish")
        notify.feishu(f"【电商智研】已提交发布 #{task_id}：{t['title']}")
    except Exception as e:  # noqa
        msg = f"已在草稿箱，但提交发布失败：{str(e)[:300]}"
        store.update(task_id, error=msg)
        store.add_event("publish_failed", f"提交发布失败（内容仍在草稿箱）：{t['title']}", str(e)[:200], "publish")
        notify.feishu(f"【电商智研】{msg}")
    return store.get(task_id)


def check_publish(task_id: int) -> dict:
    t = store.get(task_id)
    if not t or not t.get("publish_id"):
        raise ValueError("该任务还没有提交发布")
    return {"publish_id": t["publish_id"], **wechat.publish_status(t["publish_id"])}


def daily_tick(now: datetime.datetime | None = None) -> int | None:
    """调度心跳：到点且今天还没跑过就生成一篇。由后台循环每分钟调用。"""
    if not settings.auto_plan_enabled:
        return None
    now = now or datetime.datetime.now()
    hh, mm = (int(x) for x in settings.daily_plan_time.split(":"))
    today = now.strftime("%Y-%m-%d")
    if (now.hour, now.minute) >= (hh, mm) and store.kv_get("last_plan_date") != today:
        store.kv_set("last_plan_date", today)
        return plan_and_generate()
    return None


# ===================== 发布计划（选平台 + 选时间）=====================
PLATFORMS = {
    "wechat": {"name": "微信公众号"},
    "xiaohongshu": {"name": "小红书"},
    "douyin": {"name": "抖音"},
}


def platforms_info() -> list:
    out = []
    for k, v in PLATFORMS.items():
        if k == "wechat":
            ok = bool(settings.wechat_appid and settings.wechat_secret)
            mode = "自动发布" if settings.wechat_auto_publish else "写入草稿箱，手机上确认发布"
            hint = "" if ok else "（尚未配置公众号密钥）"
        else:
            ok = True
            mode = "到点改写内容并提醒你，手动发布"
            hint = "（暂无官方发帖接口，为辅助发布）"
        out.append({"key": k, "name": v["name"], "mode": mode + hint, "configured": ok})
    return out


def schedule(task_id: int, platforms: list, run_at=None, now=None, wechat_mode: str = "draft") -> list:
    """为一篇已审核通过的内容创建发布计划。run_at 为 Unix 秒；为空或已过期则立即执行。"""
    t = store.get(task_id)
    if not t:
        raise ValueError("任务不存在")
    if t["status"] not in ("approved", "drafted", "published"):
        raise ValueError("请先审核通过，再安排发布")
    if not platforms:
        raise ValueError("请选择至少一个发布平台")
    bad = [p for p in platforms if p not in PLATFORMS]
    if bad:
        raise ValueError(f"不支持的平台：{bad[0]}")
    now = now if now is not None else time.time()
    when = float(run_at) if run_at else now
    ids = []
    for p in dict.fromkeys(platforms):
        ids.append(store.add_schedule(task_id, p, when, wechat_mode if p == "wechat" else None))
    if when <= now:
        for sid in ids:
            run_schedule(sid)
    return [store.get_schedule(i) for i in ids]


def run_schedule(sid: int) -> dict:
    if not store.claim_schedule(sid):
        return store.get_schedule(sid)
    s = store.get_schedule(sid)
    t = store.get(s["task_id"])
    try:
        if s["platform"] == "wechat":
            direct = s.get("mode") == "publish"
            if t["status"] == "approved":
                r = publish(t["id"], direct=direct)
            elif t["status"] == "drafted" and direct:
                r = submit_draft(t["id"])
            else:
                r = None
            if r is None:
                msg = "这篇内容已在公众号草稿箱或已发布，无需重复提交"
            elif r["status"] == "failed":
                raise RuntimeError(r.get("error") or "公众号发布失败")
            elif r["status"] == "published":
                msg = "已提交发布（可在任务里查询发布结果）"
            else:
                msg = "已写入公众号草稿箱，请到手机上确认发布" + (f"。{r['error']}" if r.get("error") else "")
            store.update_schedule(sid, status="done", result={"mode": "wechat", "message": msg}, error="")
            store.add_event("schedule", f"公众号计划已执行：{t['title']}", msg, "publish")
        else:
            name = PLATFORMS[s["platform"]]["name"]
            content = agents.adapt_content(s["platform"], t["title"], t["body"], t["tags"])
            text = (f"【电商智研·{name}发布提醒】\n标题：{content.get('title','')}\n\n{content.get('body','')}\n\n"
                    + " ".join("#" + h for h in content.get("hashtags", [])))
            sent = notify.feishu(text[:1800])
            store.update_schedule(sid, status="done", error="", result={
                "mode": "remind", "content": content, "notified": sent,
                "message": f"已按{name}风格改写" + ("，并已推送提醒" if sent else "，请在此页复制内容后手动发布")})
            store.add_event("schedule", f"{name}发布提醒已生成：{t['title']}", "内容已改写好，点击查看并复制", "publish")
    except Exception as e:  # noqa
        store.update_schedule(sid, status="failed", error=str(e)[:500])
        store.add_event("schedule_failed", f"发布计划执行失败：{t['title']}", str(e)[:200], "publish")
        notify.feishu(f"【电商智研】发布计划执行失败 #{sid}：{str(e)[:200]}")
    return store.get_schedule(sid)


def cancel_schedule(sid: int) -> dict:
    s = store.get_schedule(sid)
    if not s or s["status"] != "scheduled":
        raise ValueError("只有待执行的计划可以取消")
    store.update_schedule(sid, status="cancelled")
    return store.get_schedule(sid)


def run_due(now=None) -> int:
    """调度心跳：执行所有到点的计划，返回执行数量。"""
    now = now if now is not None else time.time()
    n = 0
    for s in store.list_schedules(status="scheduled"):
        if s["run_at"] <= now:
            run_schedule(s["id"])
            n += 1
    return n

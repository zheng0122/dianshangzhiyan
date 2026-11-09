import asyncio
import hmac
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import os

from fastapi.staticfiles import StaticFiles

from . import agents, compliance, datasvc, diagnose, store, workflow
from .config import settings
from .llm import LLMError
from .coze import CozeError


async def _heartbeat():
    """心跳：每分钟检查一次是否该执行每日自动流程。"""
    while True:
        try:
            await asyncio.to_thread(workflow.daily_tick)
            await asyncio.to_thread(workflow.run_due)
        except Exception as e:  # noqa
            print("heartbeat error:", e)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init()
    task = asyncio.create_task(_heartbeat())
    yield
    task.cancel()


app = FastAPI(title="电商智研 Agent API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])


def admin(x_admin_token: str = Header(default="")):
    if not settings.admin_token or not hmac.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(401, "需要有效的 X-Admin-Token")


def run(fn, *a):
    try:
        return fn(*a)
    except (LLMError, CozeError) as e:
        raise HTTPException(502, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/health")
def health():
    return {"ok": True, "mock_mode": settings.mock_mode, "providers": agents.providers(),
            "fu_shops": 2 if settings.coze_bots.get("fu2") else 1, "fu_labels": settings.fu_labels,
            "da_bots": 2 if settings.coze_bots.get("da2") else 1, "da_labels": settings.da_labels,
            "da_image": bool(settings.coze_token and settings.coze_workflow_da),
            "wechat_configured": bool(settings.wechat_appid and settings.wechat_secret)}


# ---------- 五大智能体 ----------
class WenReq(BaseModel):
    question: str
    history: Optional[list[dict]] = None
    conversation_id: Optional[str] = None


class ChuangReq(BaseModel):
    platform: str = "小红书"
    product: str
    selling_points: str = ""
    audience: str = ""
    style: str = ""


class DaReq(BaseModel):
    bot: str = "1"
    scene: str
    category: str
    budget: str = ""
    audience: str = ""
    style: str = ""


class FuReq(BaseModel):
    conversation: list[dict]
    shop: str = "1"


class DaImageReq(BaseModel):
    text: str


class XiReq(BaseModel):
    range: str = "近7日"
    metrics: dict[str, Any]


@app.post("/api/wen")
def wen(r: WenReq):
    return run(agents.ask_wen, r.question, r.history, r.conversation_id)


@app.post("/api/chuang")
def chuang(r: ChuangReq):
    return run(agents.create_content, r.platform, r.product, r.selling_points, r.audience, r.style)


@app.post("/api/da")
def da(r: DaReq):
    return run(agents.outfit_plans, r.scene, r.category, r.budget, r.audience, r.style, r.bot)


@app.post("/api/da/image")
def da_image(r: DaImageReq):
    return run(agents.da_image, r.text)


@app.post("/api/fu/replies")
def fu(r: FuReq):
    return run(agents.service_replies, r.conversation, r.shop)


@app.post("/api/xi/report")
def xi(r: XiReq):
    return run(agents.analyze, r.range, r.metrics)


# ---------- 自动发布（需管理口令） ----------
class EditReq(BaseModel):
    title: Optional[str] = None
    digest: Optional[str] = None
    body: Optional[str] = None


class CreateTaskReq(BaseModel):
    title: str
    digest: str = ""
    body: str
    hashtags: list[str] = []
    topic: str = ""


@app.post("/api/publish/tasks", dependencies=[Depends(admin)])
def create_task(r: CreateTaskReq):
    """把前端（云创）生成的内容加入发布队列，自动做合规检查。"""
    issues = compliance.check(f"{r.title}\n{r.digest}\n{r.body}", workflow.load_profile().get("banned_words"))
    tid = store.add_task(r.topic, r.title, r.digest, r.body, r.hashtags, issues)
    return store.get(tid)


@app.get("/api/publish/tasks", dependencies=[Depends(admin)])
def tasks(status: Optional[str] = None):
    return store.list_tasks(status)


@app.post("/api/publish/plan", dependencies=[Depends(admin)])
def plan_now():
    tid = run(workflow.plan_and_generate)
    return store.get(tid)


@app.patch("/api/publish/tasks/{tid}", dependencies=[Depends(admin)])
def edit_task(tid: int, r: EditReq):
    return run(workflow.edit, tid, r.title, r.digest, r.body)


@app.post("/api/publish/tasks/{tid}/approve", dependencies=[Depends(admin)])
def approve(tid: int, force: bool = False):
    return run(workflow.approve, tid, force)


class ScheduleReq(BaseModel):
    platforms: list[str]
    run_at: Optional[float] = None  # Unix 秒；为空表示立即
    wechat_mode: str = "draft"  # draft=写入草稿箱；publish=提交发布


@app.post("/api/publish/tasks/{tid}/submit", dependencies=[Depends(admin)])
def submit(tid: int):
    return run(workflow.submit_draft, tid)


@app.get("/api/publish/tasks/{tid}/status", dependencies=[Depends(admin)])
def publish_status(tid: int):
    return run(workflow.check_publish, tid)


@app.get("/api/notifications", dependencies=[Depends(admin)])
def notifications(after: int = 0):
    return store.list_events(after)


@app.get("/api/diagnose", dependencies=[Depends(admin)])
def do_diagnose(wechat: int = 0):
    return diagnose.run(bool(wechat))


class ImportReq(BaseModel):
    csv: str
    replace: bool = False


@app.post("/api/data/import", dependencies=[Depends(admin)])
def data_import(r: ImportReq):
    return run(datasvc.import_csv, r.csv, r.replace)


@app.post("/api/data/clear", dependencies=[Depends(admin)])
def data_clear():
    store.clear_metrics()
    return {"ok": True}


@app.get("/api/data/summary")
def data_summary(days: int = 7):
    return datasvc.summary(max(1, min(days, 365)))


@app.get("/api/publish/platforms", dependencies=[Depends(admin)])
def platforms():
    return workflow.platforms_info()


@app.post("/api/publish/tasks/{tid}/schedule", dependencies=[Depends(admin)])
def schedule(tid: int, r: ScheduleReq):
    return run(workflow.schedule, tid, r.platforms, r.run_at, None, r.wechat_mode)


@app.get("/api/publish/schedules", dependencies=[Depends(admin)])
def schedules(task_id: Optional[int] = None):
    return store.list_schedules(task_id)


@app.post("/api/publish/schedules/{sid}/cancel", dependencies=[Depends(admin)])
def cancel_schedule(sid: int):
    return run(workflow.cancel_schedule, sid)


@app.post("/api/publish/tasks/{tid}/reject", dependencies=[Depends(admin)])
def reject(tid: int):
    return run(workflow.reject, tid)


@app.post("/api/publish/tasks/{tid}/publish", dependencies=[Depends(admin)])
def publish(tid: int, direct: Optional[bool] = None):
    return run(workflow.publish, tid, direct)


# 前端静态页面（放在所有 /api 路由之后）
_WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
if os.path.isdir(_WEB):
    app.mount("/", StaticFiles(directory=_WEB, html=True), name="web")

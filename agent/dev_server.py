"""无需安装 FastAPI 的本地预览服务（仅用标准库），接口与 app/main.py 保持一致。
用法：python dev_server.py  然后打开 http://localhost:8000
"""
import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import requests  # noqa: F401
except ImportError:
    sys.exit("缺少依赖，请先运行：pip install requests python-dotenv")
from app import agents, compliance, datasvc, diagnose, store, workflow  # noqa: E402
from app.config import settings  # noqa: E402
from app.llm import LLMError  # noqa: E402
from app.coze import CozeError  # noqa: E402

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
ADMIN_PATHS = ("/api/publish", "/api/notifications", "/api/diagnose", "/api/data/import", "/api/data/clear")


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj=None, raw=None, ctype="application/json; charset=utf-8"):
        body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, raw=b"")

    def _admin_ok(self):
        return settings.admin_token and self.headers.get("X-Admin-Token", "") == settings.admin_token

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _route(self, method):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        if not p.startswith("/api/"):
            if method != "GET":
                return self._send(405, {"detail": "method not allowed"})
            f = os.path.join(WEB, "index.html" if p == "/" else p.lstrip("/"))
            if not os.path.abspath(f).startswith(WEB) or not os.path.isfile(f):
                return self._send(404, {"detail": "not found"})
            return self._send(200, raw=open(f, "rb").read(), ctype=(mimetypes.guess_type(f)[0] or "text/plain") + "; charset=utf-8")
        if p.startswith(ADMIN_PATHS) and not self._admin_ok():
            return self._send(401, {"detail": "需要有效的 X-Admin-Token"})
        b = self._body() if method in ("POST", "PATCH") else {}
        try:
            if p == "/api/health":
                return self._send(200, {"ok": True, "mock_mode": settings.mock_mode, "providers": agents.providers(),
                                        "fu_shops": 2 if settings.coze_bots.get("fu2") else 1, "fu_labels": settings.fu_labels,
                                        "da_bots": 2 if settings.coze_bots.get("da2") else 1, "da_labels": settings.da_labels,
                                        "da_image": bool(settings.coze_token and settings.coze_workflow_da),
                                        "wechat_configured": bool(settings.wechat_appid and settings.wechat_secret)})
            if p == "/api/wen":
                return self._send(200, agents.ask_wen(b["question"], b.get("history"), b.get("conversation_id")))
            if p == "/api/chuang":
                return self._send(200, agents.create_content(b.get("platform", "小红书"), b["product"], b.get("selling_points", ""), b.get("audience", ""), b.get("style", "")))
            if p == "/api/da":
                return self._send(200, agents.outfit_plans(b["scene"], b["category"], b.get("budget", ""), b.get("audience", ""), b.get("style", ""), b.get("bot", "1")))
            if p == "/api/da/image":
                return self._send(200, agents.da_image(b["text"]))
            if p == "/api/fu/replies":
                return self._send(200, agents.service_replies(b["conversation"], b.get("shop", "1")))
            if p == "/api/xi/report":
                return self._send(200, agents.analyze(b.get("range", "近7日"), b["metrics"]))
            if p == "/api/publish/plan" and method == "POST":
                return self._send(200, store.get(workflow.plan_and_generate()))
            if p == "/api/publish/tasks" and method == "GET":
                return self._send(200, store.list_tasks((q.get("status") or [None])[0]))
            if p == "/api/publish/tasks" and method == "POST":
                issues = compliance.check(f"{b['title']}\n{b.get('digest','')}\n{b['body']}", workflow.load_profile().get("banned_words"))
                return self._send(200, store.get(store.add_task(b.get("topic", ""), b["title"], b.get("digest", ""), b["body"], b.get("hashtags", []), issues)))
            if p == "/api/notifications":
                return self._send(200, store.list_events(int((q.get("after") or ["0"])[0])))
            if p == "/api/diagnose":
                return self._send(200, diagnose.run((q.get("wechat") or ["0"])[0] == "1"))
            if p == "/api/data/import" and method == "POST":
                return self._send(200, datasvc.import_csv(b["csv"], bool(b.get("replace"))))
            if p == "/api/data/clear" and method == "POST":
                store.clear_metrics()
                return self._send(200, {"ok": True})
            if p == "/api/data/summary":
                return self._send(200, datasvc.summary(max(1, min(int((q.get("days") or ["7"])[0]), 365))))
            if p == "/api/publish/platforms":
                return self._send(200, workflow.platforms_info())
            if p == "/api/publish/schedules" and method == "GET":
                tid = (q.get("task_id") or [None])[0]
                return self._send(200, store.list_schedules(int(tid) if tid else None))
            parts = p.strip("/").split("/")
            if len(parts) == 5 and parts[:3] == ["api", "publish", "schedules"] and parts[4] == "cancel":
                return self._send(200, workflow.cancel_schedule(int(parts[3])))
            if len(parts) == 5 and parts[:3] == ["api", "publish", "tasks"] and parts[4] == "schedule":
                return self._send(200, workflow.schedule(int(parts[3]), b.get("platforms", []), b.get("run_at"), None, b.get("wechat_mode", "draft")))
            if len(parts) == 5 and parts[:3] == ["api", "publish", "tasks"] and parts[4] == "submit":
                return self._send(200, workflow.submit_draft(int(parts[3])))
            if len(parts) == 5 and parts[:3] == ["api", "publish", "tasks"] and parts[4] == "status":
                return self._send(200, workflow.check_publish(int(parts[3])))
            if len(parts) >= 4 and parts[:3] == ["api", "publish", "tasks"]:
                tid = int(parts[3])
                act = parts[4] if len(parts) > 4 else ""
                if method == "PATCH":
                    return self._send(200, workflow.edit(tid, b.get("title"), b.get("digest"), b.get("body")))
                if act == "approve":
                    return self._send(200, workflow.approve(tid, (q.get("force") or ["false"])[0] == "true"))
                if act == "reject":
                    return self._send(200, workflow.reject(tid))
                if act == "publish":
                    dv = (q.get("direct") or [None])[0]
                    return self._send(200, workflow.publish(tid, None if dv is None else dv in ("1", "true")))
            return self._send(404, {"detail": "not found"})
        except (LLMError, CozeError) as e:
            return self._send(502, {"detail": str(e)})
        except (ValueError, KeyError) as e:
            return self._send(400, {"detail": str(e)})

    def do_GET(self): self._route("GET")
    def do_POST(self): self._route("POST")
    def do_PATCH(self): self._route("PATCH")
    def log_message(self, *a): pass


def _heartbeat():
    import threading, time as _t

    def loop():
        while True:
            try:
                workflow.daily_tick()
                workflow.run_due()
            except Exception as e:  # noqa
                print("heartbeat error:", e)
            _t.sleep(30)
    threading.Thread(target=loop, daemon=True).start()


if __name__ == "__main__":
    store.init()
    _heartbeat()
    port = int(os.getenv("PORT", "8000"))
    print(f"预览服务已启动：http://localhost:{port}  （演示模式={settings.mock_mode}）")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()

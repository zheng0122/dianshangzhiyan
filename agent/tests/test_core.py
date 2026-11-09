import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["PROFILE_PATH"] = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "merchant_profile.json")
os.environ["LLM_API_KEY"] = ""
os.environ["WECHAT_APPID"] = "wx_test"
os.environ["WECHAT_SECRET"] = "secret"
os.environ["WECHAT_THUMB_MEDIA_ID"] = "thumb123"

from app import compliance, llm, store, workflow, agents  # noqa: E402
from app.config import settings  # noqa: E402
from app.publisher import wechat  # noqa: E402


class T(unittest.TestCase):
    def setUp(self):
        for name, val in [("wechat_appid", "wx_test"), ("wechat_secret", "secret"), ("wechat_thumb_media_id", "thumb123"),
                          ("llm_api_key", ""), ("coze_token", ""), ("wechat_auto_publish", False), ("skip_review", False)]:
            pp = mock.patch.object(settings, name, val)
            pp.start()
            self.addCleanup(pp.stop)
        store.init()

    def test_extract_json(self):
        self.assertEqual(llm.extract_json('好的：\n```json\n{"a": {"b": "}"}}\n```'), {"a": {"b": "}"}})
        self.assertEqual(llm.extract_json('前言 {"x":1} 后语'), {"x": 1})
        with self.assertRaises(ValueError):
            llm.extract_json("没有json")

    def test_compliance(self):
        iss = compliance.check("全网最低价，100%有效，绝对好用", ["竞品名"])
        words = {i["word"] for i in iss}
        self.assertTrue({"最低价", "100%", "绝对"} <= words)
        self.assertEqual(compliance.check("品质稳定，日常百搭"), [])
        self.assertNotIn("最好", compliance.soften("最好用"))

    def test_mock_agents(self):
        self.assertTrue(settings.mock_mode)
        self.assertIn("answer", agents.ask_wen("怎么开店"))
        self.assertIn("plans", agents.outfit_plans("旅行", "女装", "500", "", ""))
        self.assertEqual(len(agents.service_replies([{"role": "客户", "text": "发货了吗"}])["replies"]), 4)

    def test_to_html_escapes(self):
        h = wechat.to_html("小标题\n\n<script>alert(1)</script>这是一段正文。")
        self.assertNotIn("<script>", h)
        self.assertIn("<h3", h)

    def test_flow_draft_only(self):
        tid = workflow.plan_and_generate()
        t = store.get(tid)
        self.assertEqual(t["status"], "pending_review")
        with mock.patch.object(wechat, "access_token", return_value="tok"), \
             mock.patch("app.publisher.wechat.requests.post") as post:
            post.return_value.json.return_value = {"media_id": "draft_1"}
            workflow.approve(tid)
            r = workflow.publish(tid)
            self.assertEqual(r["status"], "drafted")
            self.assertEqual(r["draft_id"], "draft_1")
            args, kwargs = post.call_args
            self.assertIn("draft/add", args[0])
            self.assertIn(t["title"].encode("utf-8"), kwargs["data"])  # 中文未被转义

    def test_publish_permission_error(self):
        tid = workflow.plan_and_generate()
        workflow.approve(tid)
        with mock.patch.object(wechat, "access_token", return_value="tok"), \
             mock.patch("app.publisher.wechat.requests.post") as post:
            post.return_value.json.return_value = {"errcode": 48001, "errmsg": "api unauthorized"}
            r = workflow.publish(tid)
            self.assertEqual(r["status"], "failed")
            self.assertIn("没有此接口权限", r["error"])

    def test_approve_blocked_by_issues(self):
        tid = store.add_task("t", "全网最低价", "", "绝对有效", [], compliance.check("全网最低价 绝对有效"))
        with self.assertRaises(ValueError):
            workflow.approve(tid)
        fixed = workflow.edit(tid, title="价格实惠", body="品质稳定")
        self.assertEqual(fixed["issues"], [])
        self.assertEqual(workflow.approve(tid)["status"], "approved")

    def test_daily_tick_once_per_day(self):
        import datetime
        store.kv_set("last_plan_date", "")
        now = datetime.datetime(2026, 11, 2, 9, 5)
        self.assertIsNotNone(workflow.daily_tick(now))
        self.assertIsNone(workflow.daily_tick(now))
        self.assertIsNone(workflow.daily_tick(datetime.datetime(2026, 11, 3, 8, 0)))


if __name__ == "__main__":
    unittest.main()

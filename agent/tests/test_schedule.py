import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "s.db"))
os.environ.setdefault("PROFILE_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "merchant_profile.json"))

from app import store, workflow  # noqa: E402
from app.config import settings  # noqa: E402
from app.publisher import wechat  # noqa: E402


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        for name, val in [("wechat_appid", "wx"), ("wechat_secret", "s"), ("wechat_thumb_media_id", "t"),
                          ("llm_api_key", ""), ("coze_token", ""), ("wechat_auto_publish", False), ("feishu_webhook", "")]:
            p = mock.patch.object(settings, name, val)
            p.start()
            self.addCleanup(p.stop)
        store.init()

    def _approved(self, title="好文", body="第一段。\n\n第二段。"):
        tid = store.add_task("topic", title, "摘要", body, ["话题"], [])
        workflow.approve(tid)
        return tid

    def test_requires_approval_and_platform(self):
        tid = store.add_task("t", "x", "", "y", [], [])
        with self.assertRaises(ValueError):
            workflow.schedule(tid, ["wechat"])
        tid2 = self._approved()
        with self.assertRaises(ValueError):
            workflow.schedule(tid2, [])
        with self.assertRaises(ValueError):
            workflow.schedule(tid2, ["weibo"])

    def test_immediate_remind_platforms(self):
        tid = self._approved()
        rows = workflow.schedule(tid, ["xiaohongshu", "douyin"])
        self.assertEqual([r["status"] for r in rows], ["done", "done"])
        self.assertEqual(rows[0]["result"]["mode"], "remind")
        self.assertIn("title", rows[0]["result"]["content"])
        self.assertIn("手动发布", workflow.platforms_info()[1]["mode"])

    def test_future_schedule_runs_only_when_due(self):
        tid = self._approved()
        now = 1_000_000.0
        rows = workflow.schedule(tid, ["xiaohongshu"], run_at=now + 3600, now=now)
        self.assertEqual(rows[0]["status"], "scheduled")
        self.assertEqual(workflow.run_due(now + 100), 0)
        self.assertEqual(store.get_schedule(rows[0]["id"])["status"], "scheduled")
        self.assertEqual(workflow.run_due(now + 3601), 1)
        self.assertEqual(store.get_schedule(rows[0]["id"])["status"], "done")
        self.assertEqual(workflow.run_due(now + 7200), 0)  # 不会重复执行

    def test_cancel(self):
        tid = self._approved()
        now = 1_000_000.0
        s = workflow.schedule(tid, ["douyin"], run_at=now + 60, now=now)[0]
        self.assertEqual(workflow.cancel_schedule(s["id"])["status"], "cancelled")
        self.assertEqual(workflow.run_due(now + 120), 0)
        with self.assertRaises(ValueError):
            workflow.cancel_schedule(s["id"])

    def test_wechat_schedule_writes_draft_then_not_duplicated(self):
        tid = self._approved()
        with mock.patch.object(wechat, "access_token", return_value="tok"), \
             mock.patch("app.publisher.wechat.requests.post") as post:
            post.return_value.json.return_value = {"media_id": "draft9"}
            r = workflow.schedule(tid, ["wechat"])[0]
            self.assertEqual(r["status"], "done")
            self.assertIn("草稿箱", r["result"]["message"])
            self.assertEqual(store.get(tid)["status"], "drafted")
            r2 = workflow.schedule(tid, ["wechat"])[0]  # 再次安排：不重复提交
            self.assertEqual(post.call_count, 1)
            self.assertIn("无需重复", r2["result"]["message"])

    def test_wechat_failure_marks_failed(self):
        tid = self._approved()
        with mock.patch.object(wechat, "access_token", return_value="tok"), \
             mock.patch("app.publisher.wechat.requests.post") as post:
            post.return_value.json.return_value = {"errcode": 40164, "errmsg": "invalid ip"}
            r = workflow.schedule(tid, ["wechat"])[0]
        self.assertEqual(r["status"], "failed")
        self.assertIn("白名单", r["error"])

    def test_claim_is_atomic(self):
        tid = self._approved()
        s = workflow.schedule(tid, ["douyin"], run_at=time.time() + 999)[0]
        self.assertTrue(store.claim_schedule(s["id"]))
        self.assertFalse(store.claim_schedule(s["id"]))


if __name__ == "__main__":
    unittest.main()

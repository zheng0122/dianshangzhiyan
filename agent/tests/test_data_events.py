import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "d.db"))
os.environ.setdefault("PROFILE_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "merchant_profile.json"))

from app import datasvc, diagnose, store, workflow  # noqa: E402
from app.config import settings  # noqa: E402
from app.publisher import wechat  # noqa: E402

CSV = """日期,访客,订单,销售额,广告花费,复购订单
2026-10-20,100,5,"1,000",100,1
2026/10/21,120,6,¥1200,100,2
2026.10.22,0,0,0,0,0
2026-10-23,200,10,2000,200,3
2026-10-24,220,11,2310,200,4
2026年10月25日,240,12,2640,200,5
2026-10-26,260,13,2990,250,5
2026-10-27,280,14,3360,250,6
坏日期,1,1,1,1,1
"""


class DataTests(unittest.TestCase):
    def setUp(self):
        store.init()
        store.clear_metrics()

    def test_import_formats_and_errors(self):
        r = datasvc.import_csv(CSV, replace=True)
        self.assertEqual((r["imported"], r["skipped"]), (8, 1))
        self.assertIn("第10行", r["errors"][0])
        self.assertEqual(r["date_range"], ["2026-10-20", "2026-10-27"])
        self.assertEqual(len(store.list_metrics()), 8)

    def test_header_aliases_and_missing_columns(self):
        r = datasvc.import_csv("date,uv,orders,gmv\n2026-01-01,10,2,50\n", replace=True)
        self.assertEqual(r["columns"], ["访客", "订单", "销售额"])
        with self.assertRaises(ValueError):
            datasvc.import_csv("访客,订单\n1,2\n")
        with self.assertRaises(ValueError):
            datasvc.import_csv("日期\n2026-01-01\n")

    def test_summary_values_and_deltas(self):
        datasvc.import_csv(CSV, replace=True)
        s = datasvc.summary(3)  # 10-25..10-27 对比 10-22..10-24
        self.assertTrue(s["has_data"])
        self.assertEqual(s["latest_date"], "2026-10-27")
        self.assertEqual(s["latest"]["orders"], 14)
        m = {x["key"]: x for x in s["metrics"]}
        self.assertEqual(m["gmv"]["display"], "¥8,990")      # 2640+2990+3360
        self.assertEqual(m["orders"]["display"], "39")
        self.assertAlmostEqual(m["gmv"]["delta"], round((8990 - 4310) / 4310 * 100, 1), 1)
        self.assertEqual(m["cvr"]["unit"], "pp")
        self.assertEqual(len(s["series"]), 3)
        self.assertIn("roi", m)

    def test_summary_without_optional_columns(self):
        datasvc.import_csv("日期,销售额\n2026-01-01,100\n2026-01-02,200\n", replace=True)
        keys = [x["key"] for x in datasvc.summary(7)["metrics"]]
        self.assertEqual(keys, ["gmv"])

    def test_merge_vs_replace(self):
        datasvc.import_csv("日期,访客,订单,销售额\n2026-01-01,10,1,100\n", replace=True)
        datasvc.import_csv("日期,订单\n2026-01-01,5\n2026-01-02,3\n")  # 合并：只更新有值的列
        rows = {r["date"]: r for r in store.list_metrics()}
        self.assertEqual((rows["2026-01-01"]["visitors"], rows["2026-01-01"]["orders"]), (10, 5))
        datasvc.import_csv("日期,订单\n2026-02-01,9\n", replace=True)
        self.assertEqual(len(store.list_metrics()), 1)

    def test_no_data(self):
        self.assertEqual(datasvc.summary(7), {"has_data": False})


class PublishEventTests(unittest.TestCase):
    def setUp(self):
        for name, val in [("wechat_appid", "wx"), ("wechat_secret", "s"), ("wechat_thumb_media_id", "t"), ("llm_api_key", ""),
                          ("coze_token", ""), ("wechat_auto_publish", False), ("feishu_webhook", "")]:
            p = mock.patch.object(settings, name, val)
            p.start()
            self.addCleanup(p.stop)
        store.init()

    def _approved(self):
        tid = store.add_task("t", "标题", "摘要", "段一。\n\n段二。", [], [])
        workflow.approve(tid)
        return tid

    def test_plan_emits_review_event(self):
        before = max([e["id"] for e in store.list_events(0)] or [0])
        workflow.plan_and_generate()
        ev = store.list_events(before)
        self.assertTrue(any(e["kind"] == "review" for e in ev))

    def test_direct_publish_success(self):
        tid = self._approved()
        with mock.patch.object(wechat, "access_token", return_value="tok"), mock.patch("app.publisher.wechat.requests.post") as post:
            post.return_value.json.side_effect = [{"media_id": "d1"}, {"errcode": 0, "publish_id": "p1"}]
            t = workflow.publish(tid, direct=True)
        self.assertEqual((t["status"], t["publish_id"]), ("published", "p1"))

    def test_direct_publish_permission_denied_keeps_draft(self):
        tid = self._approved()
        with mock.patch.object(wechat, "access_token", return_value="tok"), mock.patch("app.publisher.wechat.requests.post") as post:
            post.return_value.json.side_effect = [{"media_id": "d1"}, {"errcode": 48001, "errmsg": "api unauthorized"}]
            t = workflow.publish(tid, direct=True)
        self.assertEqual(t["status"], "drafted")
        self.assertIn("没有此接口权限", t["error"])
        self.assertTrue(any(e["kind"] == "publish_failed" for e in store.list_events(0)))

    def test_submit_draft_later_and_check_status(self):
        tid = self._approved()
        with mock.patch.object(wechat, "access_token", return_value="tok"), mock.patch("app.publisher.wechat.requests.post") as post:
            post.return_value.json.side_effect = [{"media_id": "d1"}, {"errcode": 0, "publish_id": "p2"}, {"publish_status": 0, "article_id": "a"}]
            workflow.publish(tid, direct=False)
            self.assertEqual(store.get(tid)["status"], "drafted")
            self.assertEqual(workflow.submit_draft(tid)["status"], "published")
            self.assertEqual(workflow.check_publish(tid)["text"], "发布成功")

    def test_schedule_wechat_publish_mode(self):
        tid = self._approved()
        with mock.patch.object(wechat, "access_token", return_value="tok"), mock.patch("app.publisher.wechat.requests.post") as post:
            post.return_value.json.side_effect = [{"media_id": "d1"}, {"errcode": 0, "publish_id": "p3"}]
            s = workflow.schedule(tid, ["wechat"], wechat_mode="publish")[0]
        self.assertEqual(s["status"], "done")
        self.assertIn("已提交发布", s["result"]["message"])
        self.assertEqual(store.get(tid)["status"], "published")

    def test_diagnose_mock(self):
        d = diagnose.run()
        self.assertEqual([a["key"] for a in d["agents"]], ["wen", "chuang", "da", "fu", "xi"])
        self.assertTrue(all(a["ok"] and a["format"] == "mock" for a in d["agents"]))
        self.assertTrue(any(c["name"] == "Coze 令牌" and not c["ok"] for c in d["checks"]))


if __name__ == "__main__":
    unittest.main()

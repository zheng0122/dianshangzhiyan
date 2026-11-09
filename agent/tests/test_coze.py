import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "c.db"))
os.environ.setdefault("PROFILE_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "merchant_profile.json"))
os.environ["LLM_API_KEY"] = ""

from app import agents, coze, store, workflow  # noqa: E402
from app.config import settings  # noqa: E402


class Resp:
    def __init__(self, d): self._d = d
    def json(self): return self._d


def fake_coze(answer, follow=None, status_seq=("in_progress", "completed"), code=0):
    """构造 requests.post/get 的替身：模拟发起对话 → 轮询 → 读取消息。"""
    state = {"n": 0, "posts": []}

    def post(url, **kw):
        state["posts"].append((url, kw))
        if code:
            return Resp({"code": code, "msg": "bad token"})
        return Resp({"code": 0, "data": {"id": "chat1", "conversation_id": "conv1", "status": "in_progress"}})

    def get(url, **kw):
        if url.endswith("/v3/chat/retrieve"):
            st = status_seq[min(state["n"], len(status_seq) - 1)]
            state["n"] += 1
            return Resp({"code": 0, "data": {"status": st}})
        msgs = [{"type": "verbose", "content": "{}"}, {"type": "answer", "content": answer}]
        for f in (follow or []):
            msgs.append({"type": "follow_up", "content": f})
        return Resp({"code": 0, "data": msgs})
    return post, get, state


class CozeTests(unittest.TestCase):
    def setUp(self):
        store.init()
        self.p = [mock.patch.object(settings, "coze_token", "pat_x"),
                  mock.patch.object(settings, "coze_bots", {"wen": "b_wen", "chuang": "b_ch", "da": "b_da", "fu": "b_fu", "fu2": "b_fu2", "xi": "b_xi", "plan": ""}),
                  mock.patch("app.coze.time.sleep", lambda s: None)]
        for x in self.p: x.start()

    def tearDown(self):
        for x in self.p: x.stop()

    def run_with(self, post, get):
        with mock.patch("app.coze.requests.post", post), mock.patch("app.coze.requests.get", get):
            return None

    def test_chat_polls_and_parses(self):
        post, get, st = fake_coze("你好，欢迎", ["怎么入驻？", "要钱吗？"])
        with mock.patch("app.coze.requests.post", post), mock.patch("app.coze.requests.get", get):
            r = coze.chat("b1", "hi")
        self.assertEqual(r["answer"], "你好，欢迎")
        self.assertEqual(r["suggestions"], ["怎么入驻？", "要钱吗？"])
        self.assertEqual(r["conversation_id"], "conv1")
        body = st["posts"][0][1]["json"]
        self.assertEqual(body["bot_id"], "b1")
        self.assertFalse(body["stream"])
        self.assertEqual(st["posts"][0][1]["headers"]["Authorization"], "Bearer pat_x")

    def test_error_code_has_hint(self):
        post, get, _ = fake_coze("x", code=4100)
        with mock.patch("app.coze.requests.post", post), mock.patch("app.coze.requests.get", get):
            with self.assertRaises(coze.CozeError) as cm:
                coze.chat("b1", "hi")
        self.assertIn("API 渠道", str(cm.exception))

    def test_failed_status(self):
        post, get, _ = fake_coze("x", status_seq=("failed",))
        with mock.patch("app.coze.requests.post", post), mock.patch("app.coze.requests.get", get):
            with self.assertRaises(coze.CozeError):
                coze.chat("b1", "hi")

    def test_backend_routing(self):
        self.assertEqual(agents.backend("wen"), "coze")
        with mock.patch.object(settings, "coze_bots", {"wen": "", "chuang": "x"}):
            self.assertEqual(agents.backend("wen"), "mock")
            self.assertEqual(agents.backend("chuang"), "coze")

    def test_wen_returns_conversation_and_suggestions(self):
        post, get, st = fake_coze("【依据】x", ["下一步？"])
        with mock.patch("app.coze.requests.post", post), mock.patch("app.coze.requests.get", get):
            r = agents.ask_wen("怎么开店", None, "convA")
        self.assertEqual(r["suggestions"], ["下一步？"])
        self.assertEqual(r["conversation_id"], "conv1")
        self.assertEqual(st["posts"][0][1]["params"], {"conversation_id": "convA"})
        self.assertEqual(st["posts"][0][1]["json"]["additional_messages"][0]["content"], "怎么开店")  # 云问发原文

    def test_content_json_and_fallback(self):
        js = json.dumps({"title": "T", "digest": "D", "body": "B", "hashtags": ["a"]}, ensure_ascii=False)
        post, get, _ = fake_coze("好的\n```json\n" + js + "\n```")
        with mock.patch("app.coze.requests.post", post), mock.patch("app.coze.requests.get", get):
            d = agents.create_content("公众号", "戒指", "纯银", "", "")
        self.assertEqual((d["title"], d["body"], d["hashtags"]), ("T", "B", ["a"]))
        post, get, _ = fake_coze("## 标题：纯银戒指的日常\n\n这是第一段正文内容。\n\n第二段。\n\n#戒指 #好物")
        with mock.patch("app.coze.requests.post", post), mock.patch("app.coze.requests.get", get):
            d = agents.create_content("公众号", "戒指", "纯银", "", "")
        self.assertEqual(d["title"], "纯银戒指的日常")
        self.assertIn("第一段正文", d["body"])
        self.assertNotIn("#戒指", d["body"])
        self.assertEqual(d["hashtags"], ["戒指", "好物"])

    def test_fu_raw_fallback_and_shop2(self):
        post, get, st = fake_coze("亲，您好～")
        with mock.patch("app.coze.requests.post", post), mock.patch("app.coze.requests.get", get):
            d = agents.service_replies([{"role": "客户", "text": "发货了吗"}], "2")
        self.assertEqual(d["replies"][0]["text"], "亲，您好～")
        self.assertEqual(st["posts"][0][1]["json"]["bot_id"], "b_fu2")

    def test_da_and_xi_raw_fallback(self):
        post, get, _ = fake_coze("方案如下……")
        with mock.patch("app.coze.requests.post", post), mock.patch("app.coze.requests.get", get):
            self.assertEqual(agents.outfit_plans("旅行", "女装", "500", "", "")["raw"], "方案如下……")
            self.assertEqual(agents.analyze("近7日", {"销售额": 1})["raw"], "方案如下……")

    def test_workflow_images(self):
        r = {"code": 0, "data": json.dumps({"output": "效果图 https://x.com/a.png?x=1 和 https://x.com/b.jpg"})}
        with mock.patch.object(settings, "coze_workflow_da", "wf1"), \
             mock.patch("app.coze.requests.post", return_value=Resp(r)) as post:
            d = agents.da_image("轻奢旅行套装")
        self.assertEqual(d["images"], ["https://x.com/a.png?x=1", "https://x.com/b.jpg"])
        self.assertEqual(post.call_args[1]["json"]["parameters"], {"input": "轻奢旅行套装"})
        with mock.patch.object(settings, "coze_workflow_da", ""):
            with self.assertRaises(ValueError):
                agents.da_image("x")

    def test_publish_flow_uses_coze_content(self):
        js = json.dumps({"topic": "春季通勤穿搭", "product": "示例商品", "selling_points": ["百搭"], "audience": "上班族"}, ensure_ascii=False)
        calls = {"n": 0}
        art = json.dumps({"title": "春季通勤怎么穿", "digest": "d", "body": "段落一。\n\n段落二。", "hashtags": ["穿搭"]}, ensure_ascii=False)

        def post(url, **kw):
            return Resp({"code": 0, "data": {"id": "c", "conversation_id": "v", "status": "completed"}})

        def get(url, **kw):
            calls["n"] += 1
            ans = js if "春季" not in str(kw) and calls["n"] <= 1 else art
            return Resp({"code": 0, "data": [{"type": "answer", "content": ans}]})
        # 第一次 message/list 返回选题 JSON，第二次返回文章 JSON
        seq = iter([js, art])

        def get2(url, **kw):
            return Resp({"code": 0, "data": [{"type": "answer", "content": next(seq)}]})
        with mock.patch("app.coze.requests.post", post), mock.patch("app.coze.requests.get", get2):
            tid = workflow.plan_and_generate()
        t = store.get(tid)
        self.assertEqual(t["title"], "春季通勤怎么穿")
        self.assertEqual(t["topic"], "春季通勤穿搭")
        self.assertEqual(t["status"], "pending_review")


if __name__ == "__main__":
    unittest.main()


class DaSecondBot(unittest.TestCase):
    def test_da_bot2_routing_and_images(self):
        with mock.patch.object(settings, "coze_token", "pat_x"), \
             mock.patch.object(settings, "coze_bots", {"da": "b_da", "da2": "b_da2"}), \
             mock.patch("app.coze.time.sleep", lambda s: None):
            post, get, st = fake_coze("效果图 https://x.com/a.png 方案说明")
            with mock.patch("app.coze.requests.post", post), mock.patch("app.coze.requests.get", get):
                d = agents.outfit_plans("旅行", "女装", "500", "", "", "2")
            self.assertEqual(st["posts"][0][1]["json"]["bot_id"], "b_da2")
            self.assertEqual(d["images"], ["https://x.com/a.png"])
            post, get, st = fake_coze("x")
            with mock.patch("app.coze.requests.post", post), mock.patch("app.coze.requests.get", get):
                agents.outfit_plans("旅行", "女装", "500", "", "", "1")
            self.assertEqual(st["posts"][0][1]["json"]["bot_id"], "b_da")


class DaRawAgent(unittest.TestCase):
    def test_raw_agent_sends_plain_text_once_and_extracts_images(self):
        with mock.patch.object(settings, "coze_token", "pat_x"), \
             mock.patch.object(settings, "coze_bots", {"da": "b_da", "da2": "b_da2"}), \
             mock.patch.object(settings, "coze_raw_agents", {"da", "da2"}), \
             mock.patch("app.coze.time.sleep", lambda s: None):
            post, get, st = fake_coze("方案如下 ![效果图](https://cdn.x.com/abc123) 完毕")
            with mock.patch("app.coze.requests.post", post), mock.patch("app.coze.requests.get", get):
                d = agents.outfit_plans("通勤", "童装", "500", "宝妈", "简约", "1")
            self.assertEqual(len(st["posts"]), 1)  # 工作流只会被触发一次
            sent = st["posts"][0][1]["json"]["additional_messages"][0]["content"]
            self.assertTrue(sent.startswith("使用场景：通勤"))
            self.assertNotIn("JSON", sent)
            self.assertEqual(d["images"], ["https://cdn.x.com/abc123"])

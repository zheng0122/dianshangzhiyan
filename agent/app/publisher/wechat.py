"""微信公众号适配器：获取 access_token → 上传封面 → 新建草稿 →（可选）提交发布。

注意：调用接口的服务器出口 IP 必须加入公众号后台的 IP 白名单。
个人/未认证账号通常没有"发布"权限，只能写入草稿箱，由人在手机上点发布。
"""
import html
import json
import os
import time
import requests
from ..config import settings

API = "https://api.weixin.qq.com/cgi-bin"
_token = {"v": None, "exp": 0.0}


class WechatError(Exception):
    pass


def _check(resp: dict, what: str):
    if resp.get("errcode") not in (None, 0):
        hint = ""
        code = resp.get("errcode")
        if code == 40164:
            hint = "（服务器 IP 不在白名单，请把出口 IP 添加到公众号后台）"
        elif code in (48001, 48004):
            hint = "（该账号没有此接口权限，可能是未认证的订阅号）"
        raise WechatError(f"{what}失败 errcode={code} errmsg={resp.get('errmsg')}{hint}")
    return resp


def access_token() -> str:
    if not (settings.wechat_appid and settings.wechat_secret):
        raise WechatError("未配置 WECHAT_APPID / WECHAT_SECRET")
    if _token["v"] and time.time() < _token["exp"] - 120:
        return _token["v"]
    r = requests.get(f"{API}/token", params={"grant_type": "client_credential", "appid": settings.wechat_appid,
                                             "secret": settings.wechat_secret}, timeout=20).json()
    _check(r, "获取access_token")
    _token["v"] = r["access_token"]
    _token["exp"] = time.time() + int(r.get("expires_in", 7200))
    return _token["v"]


def thumb_media_id() -> str:
    if settings.wechat_thumb_media_id:
        return settings.wechat_thumb_media_id
    path = settings.wechat_cover_image
    if not (path and os.path.exists(path)):
        raise WechatError("未配置封面：请设置 WECHAT_THUMB_MEDIA_ID，或把封面图放到 WECHAT_COVER_IMAGE 指定的路径")
    with open(path, "rb") as f:
        r = requests.post(f"{API}/material/add_material", params={"access_token": access_token(), "type": "image"},
                          files={"media": (os.path.basename(path), f)}, timeout=60).json()
    _check(r, "上传封面")
    return r["media_id"]


def to_html(body: str) -> str:
    """纯文本正文 → 公众号可用的简单 HTML（段落、小标题）。"""
    parts = []
    for para in [p.strip() for p in body.replace("\r", "").split("\n\n") if p.strip()]:
        lines = html.escape(para).replace("\n", "<br/>")
        if len(para) <= 20 and not para.endswith(("。", "！", "？", "~")) and "\n" not in para:
            parts.append(f'<h3 style="margin:18px 0 8px;font-size:17px;font-weight:bold;">{lines}</h3>')
        else:
            parts.append(f'<p style="margin:0 0 14px;line-height:1.8;font-size:15px;color:#333;">{lines}</p>')
    return "".join(parts)


def _post_json(path: str, payload: dict) -> dict:
    # 必须 ensure_ascii=False，否则中文会被转义成 \uXXXX 显示异常
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return requests.post(f"{API}/{path}", params={"access_token": access_token()}, data=data,
                         headers={"Content-Type": "application/json; charset=utf-8"}, timeout=40).json()


def add_draft(title: str, digest: str, body: str) -> str:
    article = {"title": title[:64], "author": settings.wechat_author, "digest": (digest or "")[:120],
               "content": to_html(body), "content_source_url": "", "thumb_media_id": thumb_media_id(),
               "need_open_comment": 0, "only_fans_can_comment": 0}
    r = _check(_post_json("draft/add", {"articles": [article]}), "新建草稿")
    return r["media_id"]


def submit_publish(draft_media_id: str) -> str:
    r = _check(_post_json("freepublish/submit", {"media_id": draft_media_id}), "提交发布")
    return str(r.get("publish_id", ""))


PUBLISH_STATUS = {0: "发布成功", 1: "发布中，请稍后再查", 2: "原创审核不通过", 3: "发布失败（常规错误）", 4: "平台审核不通过",
                  5: "发布成功后文章被删除", 6: "发布成功后文章被系统封禁"}


def publish_status(publish_id: str) -> dict:
    r = _check(_post_json("freepublish/get", {"publish_id": publish_id}), "查询发布状态")
    st = int(r.get("publish_status", -1))
    return {"status": st, "text": PUBLISH_STATUS.get(st, f"未知状态 {st}"), "article_id": r.get("article_id", "")}

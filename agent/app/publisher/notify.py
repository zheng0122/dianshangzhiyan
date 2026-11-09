import requests
from ..config import settings


def feishu(text: str) -> bool:
    if not settings.feishu_webhook:
        return False
    try:
        r = requests.post(settings.feishu_webhook, json={"msg_type": "text", "content": {"text": text}}, timeout=10)
        return r.status_code == 200
    except Exception:  # noqa
        return False

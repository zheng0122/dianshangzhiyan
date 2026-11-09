"""OpenAI 兼容的大模型调用；未配置密钥时进入演示模式。"""
import json
import re
import requests
from .config import settings


class LLMError(Exception):
    pass


def chat(system: str, user: str, temperature: float = 0.7, timeout: int = 90) -> str:
    if settings.llm_mock:
        raise LLMError("未配置大模型")
    url = f"{settings.llm_base_url}/chat/completions"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"},
        json={
            "model": settings.llm_model,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        timeout=timeout,
    )
    if r.status_code != 200:
        raise LLMError(f"模型接口返回 {r.status_code}: {r.text[:300]}")
    try:
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:  # noqa
        raise LLMError(f"模型返回格式异常: {e}")


def extract_json(text: str):
    """从模型回复中取出第一个完整 JSON 对象（兼容 ```json 代码块与前后废话）。"""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("未找到 JSON")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("JSON 不完整")


def chat_json(system: str, user: str, temperature: float = 0.5, retries: int = 1):
    last = None
    for _ in range(retries + 1):
        out = chat(system, user, temperature)
        try:
            return extract_json(out)
        except Exception as e:  # noqa
            last = e
            user = user + "\n\n（上次输出不是合法 JSON，请只输出一个 JSON 对象，不要任何其他文字。）"
    raise LLMError(f"模型未返回合法 JSON: {last}")

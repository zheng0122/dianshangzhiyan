import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # 没装 python-dotenv 时，自己读取 .env
    def _load_env(path=".env"):
        try:
            with open(path, encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    v = v.strip()
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                        v = v[1:-1]
                    else:  # 未加引号的值：去掉行内注释（空白 + #）
                        v = v.split(" #", 1)[0].split("\t#", 1)[0].strip()
                    os.environ.setdefault(k.strip(), v)
        except FileNotFoundError:
            pass
    _load_env()


def _b(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Settings:
    llm_base_url = os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
    llm_api_key = os.getenv("LLM_API_KEY", "")
    llm_model = os.getenv("LLM_MODEL", "")
    admin_token = os.getenv("ADMIN_TOKEN", "")
    wechat_appid = os.getenv("WECHAT_APPID", "")
    wechat_secret = os.getenv("WECHAT_SECRET", "")
    wechat_author = os.getenv("WECHAT_AUTHOR", "电商智研")
    wechat_thumb_media_id = os.getenv("WECHAT_THUMB_MEDIA_ID", "")
    wechat_cover_image = os.getenv("WECHAT_COVER_IMAGE", "")
    wechat_auto_publish = _b("WECHAT_AUTO_PUBLISH", False)
    feishu_webhook = os.getenv("FEISHU_WEBHOOK", "")
    daily_plan_time = os.getenv("DAILY_PLAN_TIME", "09:00")
    auto_plan_enabled = _b("AUTO_PLAN_ENABLED", True)
    skip_review = _b("SKIP_REVIEW", False)
    db_path = os.getenv("DB_PATH", "data/agent.db")
    profile_path = os.getenv("PROFILE_PATH", "data/merchant_profile.json")
    cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

    # ---- Coze（扣子）----
    coze_base_url = os.getenv("COZE_BASE_URL", "https://api.coze.cn").rstrip("/")
    coze_token = os.getenv("COZE_TOKEN", "")
    coze_bots = {
        "wen": os.getenv("COZE_BOT_WEN", ""),
        "chuang": os.getenv("COZE_BOT_CHUANG", ""),
        "da": os.getenv("COZE_BOT_DA", ""),
        "da2": os.getenv("COZE_BOT_DA2", ""),
        "fu": os.getenv("COZE_BOT_FU", ""),
        "fu2": os.getenv("COZE_BOT_FU2", ""),
        "xi": os.getenv("COZE_BOT_XI", ""),
        "plan": os.getenv("COZE_BOT_PLAN", ""),  # 选题规划，不填则用云创 bot
    }
    fu_labels = [x.strip() for x in os.getenv("COZE_FU_LABELS", "店铺一,店铺二").split(",")]
    da_labels = [x.strip() for x in os.getenv("COZE_DA_LABELS", "搭配方案一,搭配方案二").split(",")]
    coze_workflow_da = os.getenv("COZE_WORKFLOW_DA", "")
    coze_workflow_da_params = os.getenv("COZE_WORKFLOW_DA_PARAMS", '{"input": "{text}"}')
    coze_structured = _b("COZE_STRUCTURED", True)
    # 这些功能对应的 Bot 原样接收用户需求（不附加 JSON 输出指令），完全用 Bot 自己的提示词和工作流，如 da,da2
    coze_raw_agents = {x.strip() for x in os.getenv("COZE_RAW_AGENTS", "").split(",") if x.strip()}

    @property
    def llm_mock(self) -> bool:
        return not (self.llm_api_key and self.llm_model)

    @property
    def mock_mode(self) -> bool:
        """既没配 Coze 也没配 OpenAI 兼容模型 → 全部演示模式。"""
        return self.llm_mock and not self.coze_token


settings = Settings()

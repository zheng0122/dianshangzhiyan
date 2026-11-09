"""内容合规检查：广告法极限词、绝对化用语、医疗/功效承诺等。仅为辅助，不能替代人工审核。"""
import re

BANNED = {
    "极限词": ["最好", "最佳", "最优", "最强", "最大", "最低价", "最便宜", "第一", "顶级", "极致", "唯一", "首选",
               "全网最", "史上最", "国家级", "世界级", "万能", "100%", "百分之百", "绝对", "永久", "秒杀全网"],
    "功效承诺": ["根治", "治愈", "包治", "无副作用", "立竿见影", "一周见效", "永不反弹", "祛除", "药到病除"],
    "诱导用语": ["点击领取红包", "加微信领", "私聊转账"],
}


def check(text: str, extra_banned=None):
    issues = []
    for cat, words in BANNED.items():
        for w in words:
            if w in text:
                issues.append({"type": cat, "word": w})
    for w in (extra_banned or []):
        if w and w in text:
            issues.append({"type": "商家禁用词", "word": w})
    seen = set()
    out = []
    for i in issues:
        k = (i["type"], i["word"])
        if k not in seen:
            seen.add(k)
            out.append(i)
    return out


def soften(text: str):
    """把明显的极限词替换为更稳妥的说法（仅用于提示性自动修正）。"""
    repl = {"最好": "很好", "最佳": "优选", "最优": "优质", "最强": "出色", "第一": "领先", "顶级": "高品质",
            "唯一": "独特", "首选": "推荐", "100%": "高比例", "百分之百": "高比例", "绝对": "非常"}
    for k, v in repl.items():
        text = text.replace(k, v)
    return re.sub(r"\s+\n", "\n", text)

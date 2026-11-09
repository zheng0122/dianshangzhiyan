"""店铺经营数据：导入每日 CSV（日期、访客、订单、销售额…），汇总为首页概览与云析指标。"""
import csv
import datetime as dt
import io
import re
from . import store

ALIASES = {
    "date": ["日期", "date", "day", "时间", "统计日期"],
    "visitors": ["访客", "访客数", "uv", "visitors", "visitor", "浏览人数", "访问人数"],
    "orders": ["订单", "订单数", "orders", "order", "成交订单", "订单量"],
    "gmv": ["销售额", "gmv", "成交额", "成交金额", "营业额", "sales", "revenue", "销售金额"],
    "ad_cost": ["广告花费", "广告费", "投放花费", "adcost", "cost", "推广费", "广告消耗"],
    "repeat_orders": ["复购订单", "复购订单数", "repeatorders", "repeat", "复购单数"],
}
LABELS = {"visitors": "访客", "orders": "订单", "gmv": "销售额", "ad_cost": "广告花费", "repeat_orders": "复购订单"}


def _norm(h):
    return re.sub(r"[\s_\-（）()]", "", str(h).strip().lstrip("\ufeff").lower())


def _date(s):
    s = str(s).strip()
    m = re.match(r"^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?:\s.*)?$", s)
    if not m:
        raise ValueError(f"日期格式无法识别：{s!r}")
    return dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()


def _num(s):
    s = str(s).strip().replace(",", "").replace("，", "").replace("¥", "").replace("￥", "").replace(" ", "")
    if s == "" or s in ("-", "--"):
        return None
    return float(s)


def parse_csv(text: str):
    """返回 (rows, errors, columns)。rows 为标准化后的字典列表。"""
    text = (text or "").lstrip("\ufeff")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValueError("文件内容为空，或缺少数据行")
    head = lines[0]
    delim = max([",", "\t", ";", "，"], key=lambda d: head.count(d))
    if head.count(delim) == 0:
        raise ValueError("无法识别分隔符，请使用逗号分隔的 CSV")
    rd = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))
    header = [_norm(h) for h in rd[0]]
    colmap = {}
    for key, al in ALIASES.items():
        for i, h in enumerate(header):
            if h in [_norm(a) for a in al]:
                colmap[key] = i
                break
    if "date" not in colmap:
        raise ValueError("缺少「日期」列。表头需包含：日期、访客、订单、销售额（广告花费、复购订单可选）")
    if not any(k in colmap for k in ("visitors", "orders", "gmv")):
        raise ValueError("至少需要「访客」「订单」「销售额」中的一列")
    rows, errors = [], []
    for ln, rec in enumerate(rd[1:], start=2):
        if not any(x.strip() for x in rec):
            continue
        try:
            r = {"date": _date(rec[colmap["date"]])}
            for k in store.METRIC_COLS:
                if k in colmap and colmap[k] < len(rec):
                    r[k] = _num(rec[colmap[k]])
            rows.append(r)
        except Exception as e:  # noqa
            errors.append(f"第{ln}行：{e}")
    return rows, errors, [LABELS[k] for k in LABELS if k in colmap]


def import_csv(text: str, replace: bool = False) -> dict:
    rows, errors, cols = parse_csv(text)
    if not rows:
        raise ValueError("没有可导入的有效数据行：" + ("；".join(errors[:3]) if errors else ""))
    store.upsert_metrics(rows, replace)
    ds = sorted(r["date"] for r in rows)
    return {"imported": len(rows), "skipped": len(errors), "errors": errors[:5], "columns": cols,
            "date_range": [ds[0], ds[-1]]}


def _sum(rs, k):
    vals = [r[k] for r in rs if r.get(k) is not None]
    return sum(vals) if vals else None


def _money(v):
    return f"¥{v:,.0f}" if v >= 100 else f"¥{v:,.1f}"


def _short_money(v):
    return f"¥{v/10000:.2f}万" if v >= 10000 else f"¥{v:,.0f}"


def _pct_change(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / prev * 100


def _agg(rs):
    v, o, g, a, rp = (_sum(rs, k) for k in store.METRIC_COLS)
    return {"visitors": v, "orders": o, "gmv": g, "ad_cost": a, "repeat_orders": rp,
            "cvr": (o / v * 100) if (v and o is not None) else None,
            "aov": (g / o) if (o and g is not None) else None,
            "repeat_rate": (rp / o * 100) if (o and rp is not None) else None,
            "roi": (g / a) if (a and g is not None) else None}


def summary(days: int = 7) -> dict:
    rows = store.list_metrics()
    if not rows:
        return {"has_data": False}
    last = dt.date.fromisoformat(rows[-1]["date"])
    start = last - dt.timedelta(days=days - 1)
    pend = start - dt.timedelta(days=1)
    pstart = pend - dt.timedelta(days=days - 1)
    inr = lambda r, a, b: a <= dt.date.fromisoformat(r["date"]) <= b  # noqa: E731
    cur = [r for r in rows if inr(r, start, last)]
    prev = [r for r in rows if inr(r, pstart, pend)]
    c, p = _agg(cur), _agg(prev)
    has_prev = bool(prev)

    def delta(key, pp=False):
        if not has_prev or c[key] is None or p[key] is None:
            return None
        return round(c[key] - p[key], 2) if pp else (None if p[key] == 0 else round(_pct_change(c[key], p[key]), 1))

    metrics = []
    if c["gmv"] is not None:
        metrics.append({"key": "gmv", "label": "销售额", "display": _money(c["gmv"]), "delta": delta("gmv"), "unit": "%"})
    if c["orders"] is not None:
        metrics.append({"key": "orders", "label": "订单数", "display": f"{c['orders']:,.0f}", "delta": delta("orders"), "unit": "%"})
    if c["visitors"] is not None:
        metrics.append({"key": "visitors", "label": "访客数", "display": f"{c['visitors']:,.0f}", "delta": delta("visitors"), "unit": "%"})
    if c["cvr"] is not None:
        metrics.append({"key": "cvr", "label": "转化率", "display": f"{c['cvr']:.2f}%", "delta": delta("cvr", True), "unit": "pp"})
    if c["aov"] is not None:
        metrics.append({"key": "aov", "label": "客单价", "display": _money(c["aov"]), "delta": delta("aov"), "unit": "%"})
    if c["repeat_rate"] is not None:
        metrics.append({"key": "repeat_rate", "label": "复购率", "display": f"{c['repeat_rate']:.1f}%", "delta": delta("repeat_rate", True), "unit": "pp"})
    if c["roi"] is not None:
        metrics.append({"key": "roi", "label": "ROI", "display": f"{c['roi']:.2f}x", "delta": delta("roi"), "unit": "%"})
    latest = rows[-1]
    return {"has_data": True, "rows": len(rows), "days": days, "days_covered": len(cur),
            "date_range": [rows[0]["date"], rows[-1]["date"]], "latest_date": latest["date"],
            "latest": {"visitors": latest.get("visitors"), "orders": latest.get("orders"), "gmv": latest.get("gmv"),
                       "gmv_display": _short_money(latest["gmv"]) if latest.get("gmv") is not None else None},
            "total_gmv_display": _short_money(c["gmv"]) if c["gmv"] is not None else None,
            "metrics": metrics, "has_prev": has_prev,
            "series": [{"date": r["date"], "gmv": r.get("gmv"), "orders": r.get("orders"), "visitors": r.get("visitors")} for r in cur]}

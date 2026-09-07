#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""多源财经新闻聚合与标准化。

这个模块只负责把不同接口返回的新闻统一成可追溯的结构化记录，
不直接生成交易信号，避免消息面噪音污染选股主逻辑。
"""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable, Iterable

import pandas as pd
import requests


from market_radar.freshness import classify_news_time


logger = logging.getLogger(__name__)


TITLE_COLUMNS = ("title", "标题", "新闻标题", "summary", "摘要")
TIME_COLUMNS = ("publish_time", "time", "date", "datetime", "发布时间", "日期", "时间")
SOURCE_COLUMNS = ("source", "来源", "媒体", "文章来源", "tag")
URL_COLUMNS = ("url", "链接", "新闻链接", "地址")
CONTENT_COLUMNS = ("content", "内容", "正文", "summary", "摘要")

SOURCE_WEIGHTS = {
    "cninfo_announcements": 22.0,
    "csrc_policy": 22.0,
    "ndrc_policy": 21.0,
    "miit_policy": 21.0,
    "pbc_policy": 22.0,
    "cls_key": 16.0,
    "cls_all": 13.0,
    "cctv": 12.0,
    "caixin": 12.0,
    "eastmoney": 10.0,
    "legacy_policy_news": 8.0,
}

EVENT_RULES = (
    ("政策/产业", 18.0, ("政策", "发改委", "工信部", "国务院", "项目清单", "设备更新", "补贴", "专项债", "规划", "试点")),
    ("供需/价格", 14.0, ("涨价", "降价", "库存", "供给", "需求", "订单", "产能", "限产", "出口", "进口", "交付")),
    ("科技突破", 13.0, ("算力", "AI", "人工智能", "芯片", "半导体", "服务器", "光模块", "机器人", "新能源", "储能")),
    ("业绩/订单", 12.0, ("业绩", "利润", "同比", "增长", "中标", "签约", "订单", "预增", "扭亏")),
    ("安全/地缘", 10.0, ("制裁", "关税", "出口管制", "安全", "军工", "稀土", "地缘", "贸易摩擦")),
)

INDUSTRY_KEYWORDS = {
    "机械设备": ("设备更新", "机械", "机床", "机器人", "工业母机", "工程机械"),
    "电力设备": ("电力设备", "电网", "储能", "光伏", "风电", "新能源", "充电桩"),
    "电子": ("芯片", "半导体", "消费电子", "PCB", "光模块", "封测", "算力硬件"),
    "计算机": ("AI", "人工智能", "算力", "服务器", "数据中心", "云计算", "软件"),
    "通信": ("通信", "光模块", "5G", "6G", "卫星互联网", "运营商"),
    "有色金属": ("铜", "铝", "锂", "钴", "镍", "稀土", "黄金", "小金属"),
    "化工": ("化工", "化肥", "农药", "氟化工", "磷化工", "材料"),
    "医药生物": ("创新药", "医药", "医疗器械", "疫苗", "CXO", "生物制药"),
    "汽车": ("汽车", "智能驾驶", "整车", "零部件", "无人驾驶", "固态电池"),
    "采掘": ("油价", "原油", "天然气", "煤炭", "矿山", "油田"),
    "银行": ("银行", "存量房贷", "息差", "资本补充", "转债"),
}

LOW_VALUE_KEYWORDS = (
    "抽检",
    "招生",
    "招聘",
    "旅游",
    "展会开幕",
    "提示风险",
    "辟谣",
    "股吧",
    "问答",
    "投资者关系",
)


def fetch_market_news(
    days: int = 3,
    limit: int = 30,
    providers: Iterable[tuple[str, Callable[[], pd.DataFrame]]] | None = None,
    provider_timeout: int = 20,
    provider_attempts: int = 1,
    include_unverified: bool = False,
) -> list[dict]:
    """拉取并合并多源新闻。

    Args:
        days: 预留给默认提供方使用，当前主要用于需要日期的接口。
        limit: 返回新闻数量上限。
        providers: 测试或扩展时注入的提供方列表。
        provider_timeout: 单个接口最长等待秒数，避免慢接口拖垮一键同步。
    """
    provider_list = list(providers) if providers is not None else _default_providers()
    merged: dict[str, dict] = {}

    provider_results: list[tuple[str, pd.DataFrame]] = []
    pending = provider_list
    for _attempt in range(max(1, int(provider_attempts))):
        if not pending:
            break
        retry: list[tuple[str, Callable[[], pd.DataFrame]]] = []
        with ThreadPoolExecutor(max_workers=max(1, len(pending))) as executor:
            futures = [
                (provider, fetcher, executor.submit(_call_provider, provider, fetcher, provider_timeout))
                for provider, fetcher in pending
            ]
            for provider, fetcher, future in futures:
                df = future.result()
                if df is None or df.empty:
                    retry.append((provider, fetcher))
                    continue
                provider_results.append((provider, df))
        pending = retry

    for provider, df in provider_results:
        for record in normalize_news_records(df, provider=provider):
            key = _normalize_title(record.get("title"))
            if not key:
                continue
            current = merged.get(key)
            if current is None:
                current = dict(record)
                current["providers"] = [record["provider"]]
                current["sources"] = [record["source"]] if record.get("source") else []
                current["source_count"] = 1
                merged[key] = current
            else:
                _merge_record(current, record)

    records = [_decorate_news_value(_normalize_news_timing(item)) for item in merged.values()]
    if providers is None:
        records = _filter_recent_records(records, days=days, include_unverified=include_unverified)
    records.sort(key=_news_sort_key, reverse=True)
    return _select_balanced_records(records, limit=limit)


def select_ai_news_records(records: list[dict], limit: int = 30) -> list[dict]:
    """为 AI 保留媒体、公告和政策三类证据，避免高频媒体挤掉官方来源。"""
    return _select_balanced_records(records, limit=limit, strict_ai_caps=True)


def normalize_news_records(df: pd.DataFrame, provider: str) -> list[dict]:
    """把单个新闻接口返回的 DataFrame 转为统一字段。"""
    if df is None or df.empty:
        return []

    title_col = _find_column(df, TITLE_COLUMNS)
    time_col = _find_column(df, TIME_COLUMNS)
    source_col = _find_column(df, SOURCE_COLUMNS)
    url_col = _find_column(df, URL_COLUMNS)
    content_col = _find_column(df, CONTENT_COLUMNS)

    records: list[dict] = []
    for _, row in df.iterrows():
        title = _clean_text(row.get(title_col)) if title_col else ""
        content = _clean_text(row.get(content_col)) if content_col else ""
        if not title and content:
            title = content[:80]
        if not title:
            continue
        source = _clean_text(row.get(source_col)) if source_col else ""
        publish_time = _clean_text(row.get(time_col)) if time_col else ""
        url = _clean_text(row.get(url_col)) if url_col else ""
        content_excerpt = _excerpt(content or title)
        records.append(
            {
                "title": title,
                "source": source or _provider_label(provider),
                "provider": provider,
                "publish_time": publish_time,
                "url": url,
                "content_excerpt": content_excerpt,
            }
        )
    return records


def score_news_record(record: dict) -> tuple[float, list[str]]:
    """给新闻打交易价值分，只决定进入AI解读的优先级。"""
    title = str(record.get("title") or "")
    excerpt = str(record.get("content_excerpt") or "")
    text = f"{title} {excerpt}"
    provider = str(record.get("provider") or "")
    score = SOURCE_WEIGHTS.get(provider, 8.0)
    reasons: list[str] = []

    source_count = int(record.get("source_count") or 1)
    if source_count > 1:
        score += min(12.0, (source_count - 1) * 4.0)
        reasons.append(f"多源确认{source_count}条")
    if record.get("url"):
        score += 3.0
        reasons.append("有原文链接")
    if excerpt and excerpt != title:
        score += 2.0

    for label, weight, keywords in EVENT_RULES:
        if any(keyword in text for keyword in keywords):
            score += weight
            reasons.append(label)

    industry_hits = _industry_hits(text)
    if industry_hits:
        score += min(18.0, 6.0 + len(industry_hits) * 3.0)
        reasons.append("映射行业:" + "、".join(industry_hits[:3]))

    recency = _recency_score(record.get("publish_time"))
    if recency:
        score += recency
        reasons.append("近期")

    noise_hits = [keyword for keyword in LOW_VALUE_KEYWORDS if keyword in text]
    if noise_hits:
        score -= min(24.0, 12.0 + 4.0 * len(noise_hits))
        reasons.append("低交易价值扣分:" + "、".join(noise_hits[:2]))

    if not reasons:
        reasons.append("普通新闻")
    return max(0.0, min(100.0, round(score, 1))), reasons


def _decorate_news_value(record: dict) -> dict:
    item = dict(record)
    score, reasons = score_news_record(item)
    item["news_value_score"] = score
    item["value_reasons"] = reasons
    item["value_reason_text"] = "；".join(reasons[:4])
    return item


def _industry_hits(text: str) -> list[str]:
    hits: list[str] = []
    for industry, keywords in INDUSTRY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            hits.append(industry)
    return hits


def _recency_score(value) -> float:
    publish_time = _parse_publish_time(value)
    if publish_time is None:
        return 0.0
    age_hours = max(0.0, (datetime.now() - publish_time).total_seconds() / 3600)
    if age_hours <= 12:
        return 8.0
    if age_hours <= 24:
        return 6.0
    if age_hours <= 48:
        return 4.0
    if age_hours <= 72:
        return 2.0
    return 0.0


def _filter_recent_records(records: list[dict], days: int, include_unverified: bool = False) -> list[dict]:
    if days <= 0:
        return records
    filtered = []
    for item in records:
        freshness = classify_news_time(item.get("publish_time"), record=item)
        item.update(freshness)
        if freshness["freshness_status"] == "unknown" and include_unverified:
            filtered.append(item)
            continue
        if freshness["decision_eligible"]:
            filtered.append(item)
    return filtered


def _news_sort_key(item: dict) -> tuple[float, float, int, str]:
    publish_time = _parse_publish_time(item.get("publish_time"))
    timestamp = publish_time.timestamp() if publish_time else 0.0
    return (
        timestamp,
        float(item.get("news_value_score") or 0.0),
        int(item.get("source_count") or 1),
        str(item.get("title") or ""),
    )


def _select_balanced_records(records: list[dict], limit: int, strict_ai_caps: bool = False) -> list[dict]:
    """按来源类型保留低频高可信信息，剩余名额仍按时效与价值回填。"""
    maximum = max(0, int(limit))
    if maximum == 0:
        return []
    ordered = sorted(records, key=_news_sort_key, reverse=True)
    quotas = {
        "media": min(16, maximum),
        "announcement": min(8, maximum),
        "policy": min(6, maximum),
    }
    buckets = {name: [] for name in quotas}
    for item in ordered:
        buckets[_news_bucket(item)].append(item)

    selected: list[dict] = []
    selected_ids: set[int] = set()
    for bucket in ("announcement", "policy", "media"):
        for item in buckets[bucket][: quotas[bucket]]:
            selected.append(item)
            selected_ids.add(id(item))

    if not strict_ai_caps or len(selected) < maximum:
        for item in ordered:
            if len(selected) >= maximum:
                break
            if id(item) in selected_ids:
                continue
            if strict_ai_caps and len(buckets[_news_bucket(item)]) > quotas[_news_bucket(item)]:
                # 仅在其他类型名额不足时回填，不突破总量上限。
                pass
            selected.append(item)
            selected_ids.add(id(item))

    selected.sort(key=_news_sort_key, reverse=True)
    return selected[:maximum]


def _news_bucket(item: dict) -> str:
    provider = str(item.get("provider") or "").strip()
    source = str(item.get("source") or "").strip()
    if provider == "cninfo_announcements" or source == "巨潮资讯":
        return "announcement"
    if provider in {"csrc_policy", "ndrc_policy", "miit_policy", "pbc_policy"} or source in {
        "中国证监会", "国家发改委", "工业和信息化部", "中国人民银行"
    }:
        return "policy"
    return "media"


def _normalize_news_timing(record: dict) -> dict:
    """统一发布时间；字段缺失时只信任 URL 中明确的年月日。"""
    item = dict(record)
    publish_time = _parse_publish_time(item.get("publish_time"))
    timing_source = "provider"
    if publish_time is None:
        publish_time = _publish_time_from_url(item.get("url"))
        timing_source = "url" if publish_time is not None else "unknown"
    timing = classify_news_time(publish_time, record=item)
    item.update(timing)
    item["publish_time"] = timing["as_of_time"]
    item["news_age_days"] = round(timing["age_hours"] / 24, 2) if timing["age_hours"] is not None else None
    item["freshness_bucket"] = timing["freshness_status"]
    item["publish_time_source"] = timing_source
    return item


def _publish_time_from_url(value) -> datetime | None:
    text = _clean_text(value)
    patterns = (
        r"/(20\d{2})-(\d{2})-(\d{2})/",
        r"/(20\d{2})/(\d{2})/(\d{2})/",
        r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            return datetime.strptime("-".join(match.groups()), "%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_publish_time(value) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[: len(datetime.now().strftime(fmt))], fmt)
        except ValueError:
            pass
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    try:
        return parsed.to_pydatetime().replace(tzinfo=None)
    except AttributeError:
        return None


def _default_providers() -> list[tuple[str, Callable[[], pd.DataFrame]]]:
    import akshare as ak
    from official_information_provider import (
        fetch_cninfo_announcements,
        fetch_csrc_policy,
        fetch_miit_policy,
        fetch_ndrc_policy,
        fetch_pbc_policy,
    )

    today = datetime.now().strftime("%Y%m%d")
    return [
        ("cninfo_announcements", fetch_cninfo_announcements),
        ("csrc_policy", fetch_csrc_policy),
        ("ndrc_policy", fetch_ndrc_policy),
        ("miit_policy", fetch_miit_policy),
        ("pbc_policy", fetch_pbc_policy),
        ("cls_key", lambda: _fetch_cls_news(important_only=True)),
        ("cls_all", lambda: _fetch_cls_news(important_only=False)),
        ("caixin", ak.stock_news_main_cx),
        ("eastmoney", lambda: _fetch_eastmoney_news(ak)),
        ("cctv", lambda: ak.news_cctv(date=today)),
    ]


def _fetch_cls_news(important_only: bool = False) -> pd.DataFrame:
    """读取财联社当前电报接口，替代已返回 404 的旧 AkShare 接口。"""
    url = "https://www.cls.cn/api/cache"
    params = {
        "rn": 20,
        "lastTime": int(datetime.now().timestamp()),
        "name": "telegraph",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.cls.cn/telegraph",
    }
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=8)
            response.raise_for_status()
            payload = response.json()
            rows = ((payload.get("data") or {}).get("roll_data") or [])
            if not isinstance(rows, list) or not rows:
                raise ValueError("财联社接口未返回电报数据")

            frame = pd.DataFrame(rows)
            for column in ("title", "content", "ctime", "level"):
                if column not in frame.columns:
                    frame[column] = ""
            frame = frame[["title", "content", "ctime", "level"]].copy()
            frame["ctime"] = pd.to_datetime(frame["ctime"], unit="s", utc=True).dt.tz_convert(
                "Asia/Shanghai"
            ).dt.tz_localize(None)
            frame.rename(
                columns={"title": "标题", "content": "内容", "ctime": "发布时间", "level": "等级"},
                inplace=True,
            )
            if important_only:
                frame = frame[frame["等级"].isin(("A", "B"))].copy()
            frame.reset_index(drop=True, inplace=True)
            return frame
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            last_error = exc
    raise RuntimeError(f"财联社新闻获取失败：{last_error}")


def _fetch_eastmoney_news(ak) -> pd.DataFrame:
    """东方财富个股新闻异常时切换到全球财经快讯接口。"""
    try:
        return ak.stock_news_em(symbol="全部")
    except Exception as primary_error:
        fallback = getattr(ak, "stock_info_global_em", None)
        if not callable(fallback):
            raise primary_error
        return fallback()


def _call_provider(provider: str, fetcher: Callable[[], pd.DataFrame], timeout: int) -> pd.DataFrame:
    holder: dict[str, object] = {}

    def _target() -> None:
        try:
            holder["df"] = fetcher()
        except Exception as exc:  # pragma: no cover - 外部接口容错
            holder["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        logger.warning("新闻源 %s 获取超时，已跳过。", provider)
        return pd.DataFrame()
    if "error" in holder:
        logger.warning("新闻源 %s 获取失败：%s", provider, holder["error"])
        return pd.DataFrame()
    df = holder.get("df")
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def _merge_record(current: dict, record: dict) -> None:
    provider = record.get("provider")
    if provider and provider not in current["providers"]:
        current["providers"].append(provider)
    source = record.get("source")
    if source and source not in current["sources"]:
        current["sources"].append(source)
    current["source_count"] = int(current.get("source_count") or 1) + 1
    for field in ("publish_time", "url", "content_excerpt"):
        if not current.get(field) and record.get(field):
            current[field] = record[field]


def _find_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    columns = list(df.columns)
    lower_map = {str(col).lower(): col for col in columns}
    for candidate in candidates:
        if candidate in columns:
            return candidate
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    for col in columns:
        text = str(col).lower()
        if any(str(candidate).lower() in text for candidate in candidates):
            return col
    return None


def _clean_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return re.sub(r"\s+", " ", str(value)).strip()


def _excerpt(text: str, limit: int = 180) -> str:
    text = _clean_text(text)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _normalize_title(title) -> str:
    return re.sub(r"\s+", "", str(title or "")).lower()


def _provider_label(provider: str) -> str:
    labels = {
        "cninfo_announcements": "巨潮资讯",
        "csrc_policy": "中国证监会",
        "ndrc_policy": "国家发改委",
        "miit_policy": "工业和信息化部",
        "pbc_policy": "中国人民银行",
        "cls_key": "财联社重点",
        "cls_all": "财联社",
        "caixin": "财新",
        "eastmoney": "东方财富",
        "cctv": "央视新闻",
    }
    return labels.get(str(provider), str(provider))

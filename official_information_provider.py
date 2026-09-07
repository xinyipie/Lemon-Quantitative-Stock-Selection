#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""公开公告与政府政策来源。

这些来源只补充市场雷达的消息证据，不参与量化评分。采集失败时返回空表，
避免单个官网临时改版或限流影响现有新闻与行情更新。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from html import unescape
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests


logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

OFFICIAL_COLUMNS = ["标题", "发布时间", "来源", "链接", "内容"]


def fetch_cninfo_announcements(days: int = 3, limit: int = 40) -> pd.DataFrame:
    """批量读取巨潮资讯近期沪深上市公司公告。"""
    endpoint = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    end = datetime.now()
    start = end - timedelta(days=max(1, int(days)))
    rows: list[dict] = []

    for column in ("szse", "sse"):
        payload = {
            "pageNum": 1,
            "pageSize": min(50, max(20, int(limit))),
            "column": column,
            "tabName": "fulltext",
            "plate": "",
            "stock": "",
            "searchkey": "",
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": f"{start:%Y-%m-%d}~{end:%Y-%m-%d}",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        try:
            response = requests.post(
                endpoint,
                data=payload,
                headers={**HEADERS, "Referer": "https://www.cninfo.com.cn/"},
                timeout=12,
            )
            response.raise_for_status()
            announcements = (response.json() or {}).get("announcements") or []
        except (requests.RequestException, ValueError, TypeError) as exc:
            logger.warning("巨潮公告源 %s 获取失败：%s", column, exc)
            continue

        for item in announcements:
            title = _clean_html(item.get("announcementTitle"))
            if not title:
                continue
            timestamp = item.get("announcementTime")
            try:
                publish_time = datetime.fromtimestamp(float(timestamp) / 1000).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except (TypeError, ValueError, OSError):
                publish_time = ""
            path = str(item.get("adjunctUrl") or "").lstrip("/")
            stock_name = _clean_html(item.get("secName"))
            rows.append(
                {
                    "标题": title,
                    "发布时间": publish_time,
                    "来源": "巨潮资讯",
                    "链接": urljoin("https://static.cninfo.com.cn/", path) if path else "",
                    "内容": f"{stock_name}：{title}" if stock_name else title,
                }
            )

    return _frame(rows, limit)


def fetch_csrc_policy(limit: int = 30) -> pd.DataFrame:
    """读取证监会政策解读与监管政策。"""
    return _fetch_official_pages(
        pages=(
            "https://www.csrc.gov.cn/csrc/c100039/common_list.shtml",
            "https://www.csrc.gov.cn/csrc/c100028/common_list.shtml",
        ),
        source="中国证监会",
        limit=limit,
        url_hints=("/content.shtml",),
    )


def fetch_ndrc_policy(limit: int = 30) -> pd.DataFrame:
    """读取国家发改委政策发布与政策解读。"""
    return _fetch_official_pages(
        pages=(
            "https://www.ndrc.gov.cn/xxgk/jd/jd/wap_index.html",
            "https://www.ndrc.gov.cn/xxgk/jd/zctj/wap_index.html",
            "https://www.ndrc.gov.cn/xxgk/zcfb/gg/wap_index.html",
        ),
        source="国家发改委",
        limit=limit,
        url_hints=("/t20", "/art/", ".html"),
    )


def fetch_miit_policy(limit: int = 30) -> pd.DataFrame:
    """通过工信部公开页面单元接口读取政策通知。"""
    page_url = "https://www.miit.gov.cn/zwgk/zcwj/wjfb/tz/index.html"
    endpoint = "https://www.miit.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit"
    params = {
        "parseType": "buildstatic",
        "webId": "8d828e408d90447786ddbe128d495e9e",
        "tplSetId": "209741b2109044b5b7695700b2bec37e",
        "pageType": "column",
        "tagId": "右侧内容",
        "editType": "null",
        "pageId": "3e3ad1a3bec74939890a0d3e54815141",
    }
    try:
        response = requests.get(
            endpoint,
            params=params,
            headers={**HEADERS, "Referer": page_url},
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json() or {}
        html = str((payload.get("data") or {}).get("html") or "")
        if not payload.get("success") or not html:
            raise ValueError("页面单元接口未返回有效内容")
        rows = _extract_dated_links(html, page_url, "工业和信息化部", ("/art/",))
        return _frame(rows, limit)
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning("官方来源 工业和信息化部 获取失败：%s", exc)
        return pd.DataFrame(columns=OFFICIAL_COLUMNS)


def fetch_pbc_policy(limit: int = 30) -> pd.DataFrame:
    """读取人民银行货币政策与政策发布。"""
    return _fetch_official_pages(
        pages=(
            "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/index.html",
            "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html",
        ),
        source="中国人民银行",
        limit=limit,
        url_hints=("/index.html",),
    )


def _fetch_official_pages(
    pages: tuple[str, ...],
    source: str,
    limit: int,
    url_hints: tuple[str, ...],
) -> pd.DataFrame:
    rows: list[dict] = []
    for page_url in pages:
        try:
            response = requests.get(page_url, headers=HEADERS, timeout=12)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or response.encoding
            rows.extend(_extract_dated_links(response.text, page_url, source, url_hints))
        except requests.RequestException as exc:
            logger.warning("官方来源 %s 获取失败（%s）：%s", source, page_url, exc)
    return _frame(rows, limit)


def _extract_dated_links(
    html: str,
    page_url: str,
    source: str,
    url_hints: tuple[str, ...],
) -> list[dict]:
    """从政府栏目页提取带明确日期的正文链接。"""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("缺少 beautifulsoup4，已跳过官方政策网页解析。")
        return []

    soup = BeautifulSoup(html, "html.parser")
    expected_domain = urlparse(page_url).netloc.replace("wap.", "")
    rows: list[dict] = []
    for anchor in soup.select("a[href]"):
        title = _clean_text(anchor.get_text(" ", strip=True))
        href = urljoin(page_url, str(anchor.get("href") or ""))
        if len(title) < 8 or href.startswith(("javascript:", "mailto:")):
            continue
        if expected_domain not in urlparse(href).netloc.replace("wap.", ""):
            continue
        if url_hints and not any(hint in href for hint in url_hints):
            continue

        container = anchor.find_parent(["li", "tr", "div", "p"]) or anchor.parent
        context = _clean_text(container.get_text(" ", strip=True) if container else title)
        publish_time = _extract_date(context) or _extract_date(href)
        if not publish_time:
            continue
        rows.append(
            {
                "标题": title,
                "发布时间": publish_time,
                "来源": source,
                "链接": href,
                "内容": context[:300],
            }
        )
    return rows


def _extract_date(text: str) -> str:
    patterns = (
        r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?",
        r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)",
    )
    for pattern in patterns:
        match = re.search(pattern, str(text or ""))
        if not match:
            continue
        try:
            return datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            ).strftime("%Y-%m-%d 00:00:00")
        except ValueError:
            continue
    return ""


def _frame(rows: list[dict], limit: int) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=OFFICIAL_COLUMNS)
    frame = pd.DataFrame(rows, columns=OFFICIAL_COLUMNS)
    frame.drop_duplicates(subset=["标题", "来源"], keep="first", inplace=True)
    frame.sort_values("发布时间", ascending=False, inplace=True)
    return frame.head(max(1, int(limit))).reset_index(drop=True)


def _clean_html(value) -> str:
    return _clean_text(re.sub(r"<[^>]+>", "", unescape(str(value or ""))))


def _clean_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()

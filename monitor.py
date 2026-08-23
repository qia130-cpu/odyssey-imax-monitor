#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V2 - strict Maoyan weekend IMAX monitor.

Important differences from V1:
1) Do NOT invent/query arbitrary future dates.
2) Only trust dates that Maoyan itself exposes in the current cinemaDetail payload.
3) Restrict parsing to The Odyssey movie node when the payload contains multiple movies.
4) Deduplicate by actual show fields, not by nested object IDs.
5) Do not print Maoyan's obfuscated stonefont price.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Asia/Shanghai")

CINEMA_ID = int(os.getenv("MAOYAN_CINEMA_ID", "42020"))
CITY_ID = int(os.getenv("MAOYAN_CITY_ID", "10"))
MOVIE_ID = int(os.getenv("MAOYAN_MOVIE_ID", "1545360"))
MOVIE_NAME = os.getenv("MOVIE_NAME", "奥德赛")
CINEMA_NAME = os.getenv("CINEMA_NAME", "正大乐影城（上海正大广场IMAX店）")

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
SERVERCHAN_SENDKEY = os.getenv("SERVERCHAN_SENDKEY", "").strip()
MAOYAN_COOKIE = os.getenv("MAOYAN_COOKIE", "").strip()
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))

API_URL = "https://m.maoyan.com/ajax/cinemaDetail"
CINEMA_URL = f"https://www.maoyan.com/cinema/{CINEMA_ID}?movieId={MOVIE_ID}"
MOBILE_URL = f"https://m.maoyan.com/shows/{CINEMA_ID}?movieId={MOVIE_ID}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": MOBILE_URL,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}

DATE_KEYS = ("date", "showDate", "showdate", "dt", "day")
NAME_KEYS = ("nm", "movieName", "name", "title")
MOVIE_ID_KEYS = ("movieId", "movieid", "id")


@dataclass(frozen=True)
class Showtime:
    date: str
    time: str
    language: str
    version: str
    hall: str

    @property
    def key(self) -> str:
        # Composite identity prevents duplicate notifications caused by repeated nested nodes.
        return "|".join([
            str(CINEMA_ID),
            str(MOVIE_ID),
            self.date,
            self.time,
            self.language,
            self.version,
            self.hall,
        ])


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    if MAOYAN_COOKIE:
        s.headers["Cookie"] = MAOYAN_COOKIE
    return s


def parse_date_value(value: Any) -> str | None:
    """Normalize common Maoyan date formats to YYYY-MM-DD."""
    if value is None:
        return None

    s = str(value).strip()

    # 2026-08-29 / 2026/08/29
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None

    # "8月29日" (infer current year; handle Dec -> Jan rollover)
    m = re.search(r"(\d{1,2})月(\d{1,2})日?", s)
    if m:
        mo, d = map(int, m.groups())
        today = datetime.now(TZ).date()
        y = today.year
        try:
            candidate = date(y, mo, d)
        except ValueError:
            return None
        if candidate < today - timedelta(days=30):
            try:
                candidate = date(y + 1, mo, d)
            except ValueError:
                return None
        return candidate.isoformat()

    return None


def dict_date(d: dict[str, Any]) -> str | None:
    for k in DATE_KEYS:
        if k in d:
            parsed = parse_date_value(d.get(k))
            if parsed:
                return parsed

    # Some payloads use labels like dateShow / showDateText.
    for k, value in d.items():
        kl = str(k).lower()
        if "date" in kl or "day" in kl:
            parsed = parse_date_value(value)
            if parsed:
                return parsed
    return None


def pick(d: dict[str, Any], *keys: str) -> str:
    for k in keys:
        value = d.get(k)
        if value not in (None, "", [], {}):
            return re.sub(r"<[^>]+>", "", str(value)).strip()
    return ""


def is_target_movie_node(d: dict[str, Any]) -> bool:
    ids = []
    for k in MOVIE_ID_KEYS:
        if k in d:
            try:
                ids.append(int(str(d.get(k)).strip()))
            except Exception:
                pass

    names = [str(d.get(k, "")) for k in NAME_KEYS if d.get(k)]
    name_match = any(MOVIE_NAME in n or "ODYSSEY" in n.upper() for n in names)
    id_match = MOVIE_ID in ids

    # A movie node normally has a name and/or child schedule data.
    has_schedule_children = any(k in d for k in ("shows", "showDates", "plist"))
    return (id_match and has_schedule_children) or (id_match and name_match)


def walk_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v)


def collect_plists(obj: Any, inherited_date: str | None = None) -> Iterable[tuple[str, list[Any]]]:
    """Yield only plist arrays that have a real date supplied by Maoyan."""
    if isinstance(obj, dict):
        current_date = dict_date(obj) or inherited_date

        plist = obj.get("plist")
        if isinstance(plist, list) and current_date:
            yield current_date, plist

        for k, v in obj.items():
            if k == "plist":
                continue
            yield from collect_plists(v, current_date)

    elif isinstance(obj, list):
        for v in obj:
            yield from collect_plists(v, inherited_date)


def target_schedule_roots(data: dict[str, Any]) -> list[Any]:
    """
    If the response contains explicit movie nodes, parse only The Odyssey.
    Otherwise fall back to top-level showDates (the selected movie schedule
    returned by many cinemaDetail variants).
    """
    movie_nodes = [d for d in walk_dicts(data) if is_target_movie_node(d)]
    if movie_nodes:
        return movie_nodes

    roots: list[Any] = []
    if isinstance(data.get("showDates"), list):
        roots.append(data["showDates"])

    show_data = data.get("showData")
    if isinstance(show_data, dict) and isinstance(show_data.get("showDates"), list):
        roots.append(show_data["showDates"])

    return roots


def is_future_weekend(ds: str) -> bool:
    try:
        d = date.fromisoformat(ds)
    except ValueError:
        return False
    today = datetime.now(TZ).date()
    return d > today and d.weekday() in (5, 6)


def is_imax_text(*parts: str) -> bool:
    return "IMAX" in " ".join(parts).upper()


def looks_purchasable(show: dict[str, Any]) -> bool:
    """
    Conservative filter:
    - Explicitly negative sale flags => reject.
    - Otherwise plist entries are treated as public schedule entries.
    We intentionally do not guess numeric seatStatus semantics.
    """
    negative_words = ("未开售", "不可购", "停售", "已停售", "sold out", "unavailable")
    fields = [
        pick(show, "status", "saleStatus", "ticketStatus", "buyStatus"),
        pick(show, "desc", "statusDesc", "buttonText", "buyBtn"),
    ]
    text = " ".join(fields).lower()
    return not any(w.lower() in text for w in negative_words)


def parse_available_shows(data: dict[str, Any]) -> tuple[list[Showtime], list[str]]:
    roots = target_schedule_roots(data)
    if not roots:
        raise RuntimeError(
            "猫眼返回了 JSON，但没有找到《奥德赛》的真实 showDates/plist 排片结构。"
            "为避免误报，本次不发送通知。"
        )

    detected_dates: set[str] = set()
    unique: dict[str, Showtime] = {}

    for root in roots:
        for ds, plist in collect_plists(root):
            detected_dates.add(ds)

            # Only actual future Saturdays/Sundays that Maoyan exposed.
            if not is_future_weekend(ds):
                continue

            for item in plist:
                if not isinstance(item, dict):
                    continue
                tm = pick(item, "tm", "time", "showTime", "startTime")
                if not re.fullmatch(r"\d{1,2}:\d{2}", tm):
                    continue

                language = pick(item, "lang", "language")
                version = pick(item, "tp", "version", "showType", "dim")
                hall = pick(item, "th", "hall", "hallName", "roomName")

                if not is_imax_text(language, version, hall):
                    continue
                if not looks_purchasable(item):
                    continue

                show = Showtime(ds, tm, language, version, hall)
                unique[show.key] = show

    return sorted(unique.values(), key=lambda x: (x.date, x.time, x.hall)), sorted(detected_dates)


def fetch_available_shows() -> tuple[list[Showtime], list[str]]:
    s = make_session()
    params = {
        "cinemaId": CINEMA_ID,
        "movieId": MOVIE_ID,
        "cityId": CITY_ID,
    }
    r = s.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

    content_type = r.headers.get("content-type", "")
    if "json" not in content_type.lower() and not r.text.lstrip().startswith(("{", "[")):
        raise RuntimeError(f"猫眼返回的不是 JSON（HTTP {r.status_code}）")

    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("猫眼 JSON 顶层结构异常。")

    return parse_available_shows(data)


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"known": {}}
    try:
        data = json.loads(STATE_FILE.read_text("utf-8"))
        if not isinstance(data, dict):
            return {"known": {}}
        data.setdefault("known", {})
        return data
    except Exception:
        return {"known": {}}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )


def push_wechat(new_shows: list[Showtime]) -> None:
    if not SERVERCHAN_SENDKEY:
        raise RuntimeError("缺少 GitHub Secret: SERVERCHAN_SENDKEY")

    title = f"🎬 奥德赛 IMAX 真正放票：新增 {len(new_shows)} 场"
    lines = [
        f"**影院：** {CINEMA_NAME}",
        f"**影片：** {MOVIE_NAME}",
        "",
        "### 猫眼当前公开可见的周末 IMAX 场次",
        "",
    ]

    by_date: dict[str, list[Showtime]] = {}
    for show in new_shows:
        by_date.setdefault(show.date, []).append(show)

    for ds in sorted(by_date):
        d = date.fromisoformat(ds)
        week = "周六" if d.weekday() == 5 else "周日"
        lines.append(f"**{ds} {week}**")
        for show in sorted(by_date[ds], key=lambda x: x.time):
            fmt = " / ".join(x for x in (show.language, show.version) if x)
            line = f"- **{show.time}** · {show.hall}"
            if fmt:
                line += f" · {fmt}"
            lines.append(line)
        lines.append("")

    lines += [
        "票价不在提醒中解析，避免猫眼 stonefont 动态字体造成乱码。",
        "",
        f"[👉 打开猫眼影院页确认并购票]({CINEMA_URL})",
        "",
        f"检测时间：{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}（上海时间）",
    ]

    url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
    resp = requests.post(
        url,
        data={"title": title, "desp": "\n".join(lines)},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("code") != 0:
        raise RuntimeError(f"Server酱推送失败: {result}")


def main() -> int:
    print(f"监控影院: {CINEMA_NAME} / cinemaId={CINEMA_ID}")
    print(f"监控影片: {MOVIE_NAME} / movieId={MOVIE_ID}")

    shows, detected_dates = fetch_available_shows()
    print("猫眼当前真实公开日期:", ", ".join(detected_dates) if detected_dates else "(未检测到)")
    print(f"其中未来周末 IMAX 场次: {len(shows)}")

    state = load_state()
    known: dict[str, Any] = state.get("known", {})

    current = {s.key: s for s in shows}
    new_shows = [current[k] for k in current if k not in known]
    new_shows.sort(key=lambda x: (x.date, x.time, x.hall))

    if new_shows:
        print(f"发现 {len(new_shows)} 个新的真实周末 IMAX 场次。")
        push_wechat(new_shows)
        for show in new_shows:
            known[show.key] = asdict(show)
        state["known"] = known
        save_state(state)
        print("微信推送成功，去重状态已保存。")
    else:
        print("没有新增真实周末 IMAX 场次，不推送。")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

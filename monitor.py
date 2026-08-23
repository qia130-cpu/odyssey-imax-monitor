#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor weekend IMAX showtimes for The Odyssey at
正大乐影城（上海正大广场IMAX店）, and push new showtimes to WeChat via Server酱 Turbo.

Designed for GitHub Actions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Asia/Shanghai")

# Fixed targets verified for this project.
CINEMA_ID = int(os.getenv("MAOYAN_CINEMA_ID", "42020"))
CITY_ID = int(os.getenv("MAOYAN_CITY_ID", "10"))  # Shanghai
MOVIE_ID = int(os.getenv("MAOYAN_MOVIE_ID", "1545360"))  # 奥德赛 / The Odyssey
MOVIE_NAME = os.getenv("MOVIE_NAME", "奥德赛")
CINEMA_NAME = os.getenv("CINEMA_NAME", "正大乐影城（上海正大广场IMAX店）")

CHECK_DAYS = int(os.getenv("CHECK_DAYS", "28"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
SERVERCHAN_SENDKEY = os.getenv("SERVERCHAN_SENDKEY", "").strip()
MAOYAN_COOKIE = os.getenv("MAOYAN_COOKIE", "").strip()
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))

CINEMA_URL = f"https://www.maoyan.com/cinema/{CINEMA_ID}?movieId={MOVIE_ID}"
MOBILE_CINEMA_URL = f"https://m.maoyan.com/shows/{CINEMA_ID}?movieId={MOVIE_ID}"
API_URL = "https://m.maoyan.com/ajax/cinemaDetail"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": f"https://m.maoyan.com/shows/{CINEMA_ID}",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}

@dataclass(frozen=True)
class Showtime:
    date: str
    time: str
    language: str
    version: str
    hall: str
    price: str
    seq_no: str

    @property
    def key(self) -> str:
        if self.seq_no:
            return f"seq:{self.seq_no}"
        raw = "|".join([
            str(CINEMA_ID), str(MOVIE_ID), self.date, self.time,
            self.language, self.version, self.hall
        ])
        return "sha1:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()

def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    if MAOYAN_COOKIE:
        s.headers["Cookie"] = MAOYAN_COOKIE
    return s

def upcoming_weekend_dates(today: date | None = None) -> list[date]:
    """Future Saturdays and Sundays only. Excludes today even if today is Sunday."""
    today = today or datetime.now(TZ).date()
    result = []
    for offset in range(1, CHECK_DAYS + 1):
        d = today + timedelta(days=offset)
        if d.weekday() in (5, 6):  # Saturday / Sunday
            result.append(d)
    return result

def walk_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk_dicts(value)

def pick(d: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = d.get(key)
        if value not in (None, "", [], {}):
            return str(value).strip()
    return ""

def looks_like_show(d: dict[str, Any]) -> bool:
    tm = pick(d, "tm", "time", "showTime", "startTime")
    hall = pick(d, "th", "hall", "hallName", "roomName")
    version = pick(d, "lang", "tp", "version", "showType")
    return bool(re.fullmatch(r"\d{1,2}:\d{2}", tm)) and bool(hall or version)

def normalize_show(d: dict[str, Any], target_date: str) -> Showtime:
    tm = pick(d, "tm", "time", "showTime", "startTime")
    lang = pick(d, "lang", "language")
    version = pick(d, "tp", "version", "showType", "dim")
    hall = pick(d, "th", "hall", "hallName", "roomName")
    price = pick(d, "sellPr", "price", "vipPrice", "marketPrice")
    seq_no = pick(d, "seqNo", "seqno", "showId", "id")

    # Some Maoyan payloads put "英语IMAX2D" entirely in lang/tp.
    if not version and "IMAX" in lang.upper():
        version = lang

    # API endpoint is queried for one exact date, so target_date is authoritative.
    return Showtime(
        date=target_date,
        time=tm,
        language=lang,
        version=version,
        hall=hall,
        price=price,
        seq_no=seq_no,
    )

def is_imax(show: Showtime) -> bool:
    haystack = " ".join([show.language, show.version, show.hall]).upper()
    return "IMAX" in haystack

def fetch_date(s: requests.Session, d: date) -> list[Showtime]:
    ds = d.isoformat()
    params_variants = [
        {
            "cinemaId": CINEMA_ID,
            "movieId": MOVIE_ID,
            "date": ds,
            "cityId": CITY_ID,
        },
        {
            "cinemaId": CINEMA_ID,
            "movieId": MOVIE_ID,
            "date": ds,
            "ci": CITY_ID,
        },
    ]

    last_error: Exception | None = None
    for params in params_variants:
        try:
            r = s.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            content_type = r.headers.get("content-type", "")
            if "json" not in content_type.lower() and not r.text.lstrip().startswith(("{", "[")):
                raise RuntimeError(f"猫眼返回的不是 JSON（HTTP {r.status_code}）")
            data = r.json()

            shows: dict[str, Showtime] = {}
            for item in walk_dicts(data):
                if not looks_like_show(item):
                    continue
                show = normalize_show(item, ds)
                if is_imax(show):
                    shows[show.key] = show
            return sorted(shows.values(), key=lambda x: (x.date, x.time, x.hall))
        except Exception as exc:
            last_error = exc
            time.sleep(1)

    raise RuntimeError(f"{ds} 排片获取失败: {last_error}")

def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"known": {}, "last_success": None}
    try:
        data = json.loads(STATE_FILE.read_text("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state is not an object")
        data.setdefault("known", {})
        return data
    except Exception:
        # Do not lose notifications because of a broken state file.
        return {"known": {}, "last_success": None}

def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )

def format_price(p: str) -> str:
    if not p:
        return "票价以购票页为准"
    try:
        value = float(p)
        return f"¥{value:g}"
    except Exception:
        return p

def serverchan_push(new_shows: list[Showtime]) -> None:
    if not SERVERCHAN_SENDKEY:
        raise RuntimeError(
            "缺少 GitHub Secret: SERVERCHAN_SENDKEY。"
            "请先在 Server酱 Turbo 获取 SCT 开头的 SendKey，再写入仓库 Secret。"
        )

    title = f"🎬 奥德赛 IMAX 放票：新增 {len(new_shows)} 场"
    lines = [
        f"**影院：** {CINEMA_NAME}",
        f"**影片：** {MOVIE_NAME}",
        "",
        "### 新增周末 IMAX 场次",
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
            fmt = " / ".join(x for x in [show.language, show.version] if x)
            details = f"- **{show.time}** · {show.hall}"
            if fmt:
                details += f" · {fmt}"
            details += f" · {format_price(show.price)}"
            lines.append(details)
        lines.append("")

    lines += [
        f"[👉 打开猫眼影院页购票]({CINEMA_URL})",
        "",
        f"检测时间：{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}（上海时间）",
    ]
    desp = "\n".join(lines)

    url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
    resp = requests.post(
        url,
        data={"title": title, "desp": desp},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    result = resp.json()
    # Server酱 Turbo success uses code=0 in current docs.
    if result.get("code") != 0:
        raise RuntimeError(f"Server酱推送失败: {result}")

def main() -> int:
    today = datetime.now(TZ).date()
    dates = upcoming_weekend_dates(today)
    print(f"监控影院: {CINEMA_NAME} / cinemaId={CINEMA_ID}")
    print(f"监控影片: {MOVIE_NAME} / movieId={MOVIE_ID}")
    print("目标周末日期:", ", ".join(d.isoformat() for d in dates))

    state = load_state()
    known: dict[str, Any] = state.get("known", {})
    s = session()

    all_shows: list[Showtime] = []
    errors: list[str] = []

    for d in dates:
        try:
            shows = fetch_date(s, d)
            print(f"{d.isoformat()}: 找到 {len(shows)} 个 IMAX 场次")
            all_shows.extend(shows)
        except Exception as exc:
            msg = str(exc)
            print("WARN:", msg, file=sys.stderr)
            errors.append(msg)

    # If every request failed, fail the workflow instead of silently treating it as "no showtimes".
    if errors and len(errors) == len(dates):
        raise RuntimeError("所有目标日期都获取失败；请查看 Actions 日志。" + " | ".join(errors[:2]))

    unique = {show.key: show for show in all_shows}
    new_keys = [k for k in unique if k not in known]
    new_shows = sorted(
        [unique[k] for k in new_keys],
        key=lambda x: (x.date, x.time, x.hall),
    )

    if new_shows:
        print(f"发现 {len(new_shows)} 个从未通知过的新周末 IMAX 场次。")
        # Push first; persist only after successful push so a transient Server酱 error will retry.
        serverchan_push(new_shows)
        for show in new_shows:
            known[show.key] = asdict(show)
        print("微信推送成功。")
    else:
        print("没有新增周末 IMAX 场次，不推送。")

    # Prune very old records, but keep future/current records indefinitely enough for de-duplication.
    cutoff = (today - timedelta(days=7)).isoformat()
    known = {
        k: v for k, v in known.items()
        if isinstance(v, dict) and str(v.get("date", "9999-12-31")) >= cutoff
    }

    old_known = state.get("known", {})
    if known != old_known:
        state["known"] = known
        save_state(state)
        print("去重状态已更新。")
    else:
        print("去重状态无变化，不写 state.json。")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

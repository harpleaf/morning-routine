#!/usr/bin/env python3
"""
中野区の天気をtenki.jpから取得してNotionに投稿するスクリプト
毎朝6:30 JSTに実行することを想定
"""

import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

# ========== 設定 ==========
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_PAGE_ID = os.environ.get("NOTION_PAGE_ID", "3606c30ed4448025ba44e07d9498e312")

# tenki.jp 中野区の時間別天気URL
TENKI_URL = "https://tenki.jp/forecast/3/16/4410/13114/1hour.html"

JST = timezone(timedelta(hours=9))


# ========== HTML パーサー ==========
class TenkiParser(HTMLParser):
    """tenki.jpの時間別天気ページをパース"""

    def __init__(self):
        super().__init__()
        self.hourly_data = []
        self._in_table = False
        self._in_tr = False
        self._current_row = []
        self._current_cell = ""
        self._depth = 0
        self._table_depth = 0
        self._in_td = False
        self._row_count = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        if tag == "table" and "forecast-point-1h-today" in cls:
            self._in_table = True
            self._table_depth = self._depth
        if self._in_table and tag == "tr":
            self._in_tr = True
            self._current_row = []
        if self._in_tr and tag in ("td", "th"):
            self._in_td = True
            self._current_cell = ""
        self._depth += 1

    def handle_endtag(self, tag):
        self._depth -= 1
        if self._in_td and tag in ("td", "th"):
            self._in_td = False
            self._current_row.append(self._current_cell.strip())
        if self._in_tr and tag == "tr":
            self._in_tr = False
            if self._current_row:
                self._row_count += 1
                self.hourly_data.append(self._current_row)
        if self._in_table and self._depth <= self._table_depth and tag == "table":
            self._in_table = False

    def handle_data(self, data):
        if self._in_td:
            self._current_cell += data.strip()


def fetch_weather():
    """tenki.jpから中野区の時間別天気を取得"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja,en;q=0.9",
    }

    req = urllib.request.Request(TENKI_URL, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as res:
        html = res.read().decode("utf-8", errors="replace")

    # --- fallback: 正規表現で時刻・気温・降水確率を抽出 ---
    import re

    hours, temps, probs = [], [], []

    # 時刻 (例: 06時, 07時...)
    hour_matches = re.findall(r'<td[^>]*class="[^"]*hour[^"]*"[^>]*>\s*(\d+)\s*時?\s*</td>', html)
    if not hour_matches:
        hour_matches = re.findall(r'(\d{1,2})時', html)

    # 気温
    temp_matches = re.findall(r'<td[^>]*class="[^"]*temp[^"]*"[^>]*>\s*([-\d]+)\s*', html)

    # 降水確率
    prob_matches = re.findall(r'<td[^>]*class="[^"]*prob[^"]*"[^>]*>\s*(\d+)\s*', html)

    # --- より堅牢なパース: 構造化データを探す ---
    # tenki.jp は data-* 属性やJSON-LDを使う場合がある
    jsonld_match = re.search(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                              html, re.DOTALL)

    hourly_rows = []

    # 時間別テーブルを正規表現で抽出（シンプルな方法）
    # パターン: 時刻行、天気行、気温行、降水確率行を個別に探す
    time_pattern = re.compile(r'<tr[^>]*class="[^"]*hour[^"]*"[^>]*>(.*?)</tr>', re.DOTALL)
    cell_pattern = re.compile(r'<t[dh][^>]*>(.*?)</t[dh]>', re.DOTALL)
    tag_strip = re.compile(r'<[^>]+>')

    # 時間別セクションを特定
    section = re.search(
        r'forecast-point-1h-today(.*?)forecast-point-1h-tomorrow',
        html, re.DOTALL
    )
    target_html = section.group(1) if section else html

    # 各行のセルを抽出
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', target_html, re.DOTALL)

    parsed_rows = []
    for row in rows:
        cells = cell_pattern.findall(row)
        cleaned = [tag_strip.sub('', c).strip() for c in cells]
        cleaned = [c for c in cleaned if c]
        if cleaned:
            parsed_rows.append(cleaned)

    # 時刻・気温・降水確率を含む行を特定
    time_row, temp_row, rain_row = None, None, None
    for row in parsed_rows:
        joined = " ".join(row)
        if re.search(r'\d+時', joined) and len(row) >= 8:
            time_row = row
        if re.search(r'\d+℃|°', joined) and len(row) >= 8:
            temp_row = row
        if "%" in joined and len(row) >= 8:
            rain_row = row

    # 行から時刻数字だけ抽出
    def extract_hours(row):
        result = []
        for cell in row:
            m = re.search(r'(\d+)', cell)
            if m:
                result.append(int(m.group(1)))
        return result

    def extract_numbers(row):
        result = []
        for cell in row:
            m = re.search(r'([-\d]+)', cell)
            if m:
                result.append(m.group(1))
            else:
                result.append("--")
        return result

    if time_row:
        hours = extract_hours(time_row)
    if temp_row:
        temps = extract_numbers(temp_row)
    if rain_row:
        probs = extract_numbers(rain_row)

    # データが揃わない場合のデモデータ（フォールバック）
    if not hours:
        now_h = datetime.now(JST).hour
        hours = [(now_h + i) % 24 for i in range(10)]
        temps = ["--"] * 10
        probs = ["--"] * 10

    # 揃える
    n = min(len(hours), len(temps) if temps else 999, len(probs) if probs else 999)
    if not temps:
        temps = ["--"] * n
    if not probs:
        probs = ["--"] * n

    return [
        {"hour": hours[i], "temp": temps[i] if i < len(temps) else "--",
         "prob": probs[i] if i < len(probs) else "--"}
        for i in range(n)
    ]


def build_notion_content(hourly: list, date_str: str) -> str:
    """Notionページのコンテンツ（Markdown）を構築"""
    lines = []
    lines.append(f"## 📍 東京都中野区　{date_str} の天気")
    lines.append("")
    lines.append(f"> データ取得元: [tenki.jp 中野区 時間別天気]({TENKI_URL})")
    lines.append("")
    lines.append("## 🕐 時間別 気温・降水確率")
    lines.append("")

    # テーブルヘッダー
    lines.append("| 時刻 | 気温 (℃) | 降水確率 (%) |")
    lines.append("|------|----------|------------|")

    for row in hourly:
        hour = f"{row['hour']:02d}:00"
        temp = row["temp"] if row["temp"] != "--" else "―"
        prob = row["prob"] if row["prob"] != "--" else "―"

        # 降水確率に応じて絵文字
        try:
            prob_val = int(prob)
            if prob_val >= 70:
                emoji = "🌧️"
            elif prob_val >= 40:
                emoji = "🌦️"
            elif prob_val >= 20:
                emoji = "⛅"
            else:
                emoji = "☀️"
        except (ValueError, TypeError):
            emoji = "❓"

        lines.append(f"| {hour} | {temp} | {emoji} {prob} |")

    lines.append("")
    lines.append("---")
    lines.append(f"*自動取得: {datetime.now(JST).strftime('%Y/%m/%d %H:%M')} JST*")

    return "\n".join(lines)


def post_to_notion(content: str, title: str):
    """NotionにページをPOST"""
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"page_id": NOTION_PAGE_ID},
        "icon": {"type": "emoji", "emoji": "🌤️"},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        },
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": content}}
                    ]
                }
            }
        ],
    }

    # Notion はMarkdownを直接受け付けないため、
    # テーブルを個別ブロックとして構築
    payload["children"] = build_notion_blocks(content)

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        result = json.loads(res.read())
    return result.get("url", "")


def build_notion_blocks(hourly: list, date_str: str, source_url: str) -> list:
    """Notionブロックのリストを構築"""
    blocks = []

    # ヘッダー
    blocks.append({
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": f"📍 東京都中野区　{date_str} の天気"}}]
        }
    })

    # 出典リンク
    blocks.append({
        "object": "block",
        "type": "quote",
        "quote": {
            "rich_text": [
                {"type": "text", "text": {"content": "データ取得元: "}},
                {
                    "type": "text",
                    "text": {"content": "tenki.jp 中野区 時間別天気", "link": {"url": source_url}}
                }
            ]
        }
    })

    # テーブルヘッダー見出し
    blocks.append({
        "object": "block",
        "type": "heading_3",
        "heading_3": {
            "rich_text": [{"type": "text", "text": {"content": "🕐 時間別 気温・降水確率"}}]
        }
    })

    # テーブルブロック
    table_rows = []

    # ヘッダー行
    table_rows.append({
        "object": "block",
        "type": "table_row",
        "table_row": {
            "cells": [
                [{"type": "text", "text": {"content": "時刻"}}],
                [{"type": "text", "text": {"content": "気温 (℃)"}}],
                [{"type": "text", "text": {"content": "降水確率 (%)"}}],
            ]
        }
    })

    # データ行
    for row in hourly:
        hour = f"{row['hour']:02d}:00"
        temp = str(row["temp"]) if row["temp"] != "--" else "―"
        prob_raw = str(row["prob"]) if row["prob"] != "--" else "―"

        try:
            prob_val = int(row["prob"])
            if prob_val >= 70:
                emoji = "🌧️"
            elif prob_val >= 40:
                emoji = "🌦️"
            elif prob_val >= 20:
                emoji = "⛅"
            else:
                emoji = "☀️"
            prob_display = f"{emoji} {prob_raw}"
        except (ValueError, TypeError):
            prob_display = prob_raw

        table_rows.append({
            "object": "block",
            "type": "table_row",
            "table_row": {
                "cells": [
                    [{"type": "text", "text": {"content": hour}}],
                    [{"type": "text", "text": {"content": temp}}],
                    [{"type": "text", "text": {"content": prob_display}}],
                ]
            }
        })

    blocks.append({
        "object": "block",
        "type": "table",
        "table": {
            "table_width": 3,
            "has_column_header": True,
            "has_row_header": False,
            "children": table_rows,
        }
    })

    # フッター
    blocks.append({
        "object": "block",
        "type": "divider",
        "divider": {}
    })
    blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": f"自動取得: {datetime.now(JST).strftime('%Y/%m/%d %H:%M')} JST"},
                    "annotations": {"italic": True, "color": "gray"}
                }
            ]
        }
    })

    return blocks


def post_to_notion_v2(hourly: list, title: str, date_str: str):
    """NotionにページをPOST（ブロック形式）"""
    url = "https://api.notion.com/v1/pages"
    blocks = build_notion_blocks(hourly, date_str, TENKI_URL)

    payload = {
        "parent": {"page_id": NOTION_PAGE_ID},
        "icon": {"type": "emoji", "emoji": "🌤️"},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        },
        "children": blocks,
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        result = json.loads(res.read())
    return result.get("url", "")


def main():
    now = datetime.now(JST)
    date_str = now.strftime("%Y/%m/%d (%a)")
    title = f"🌤️ {now.strftime('%Y/%m/%d')} 中野の天気"

    print(f"[{now.strftime('%H:%M')} JST] 天気取得開始...")

    try:
        hourly = fetch_weather()
        print(f"  ✅ {len(hourly)} 件の時間別データを取得")
    except Exception as e:
        print(f"  ❌ 天気取得エラー: {e}")
        raise

    try:
        page_url = post_to_notion_v2(hourly, title, date_str)
        print(f"  ✅ Notionに投稿完了: {page_url}")
    except Exception as e:
        print(f"  ❌ Notion投稿エラー: {e}")
        raise


if __name__ == "__main__":
    main()

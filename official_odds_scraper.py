# -*- coding: utf-8 -*-
"""
official_odds_scraper.py
ボートレース公式サイトから3連単全120通りのリアルタイムオッズを取得するスクレイパー
"""

import re
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

def parse_boatrace_odds3t(html: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.select('table')
    if len(tables) < 2:
        return {}
    table = tables[1]
    rows = table.select('tr')
    if len(rows) < 21:
        return {}

    all_odds = {}
    current_b2 = [None] * 7  # 1..6

    for r_idx in range(1, 21):
        tr = rows[r_idx]
        cells = tr.select('th, td')
        cell_idx = 0
        for b1 in range(1, 7):
            if cell_idx >= len(cells):
                break
            # もし2着セルが含まれる行（(r_idx - 1) % 4 == 0）なら3つのセル
            if (r_idx - 1) % 4 == 0:
                b2_str = cells[cell_idx].text.strip()
                cell_idx += 1
                try:
                    current_b2[b1] = int(b2_str)
                except:
                    pass
            
            if cell_idx >= len(cells):
                break
            b3_str = cells[cell_idx].text.strip()
            cell_idx += 1

            if cell_idx >= len(cells):
                break
            odd_str = cells[cell_idx].text.strip().replace(',', '')
            cell_idx += 1

            try:
                b2 = current_b2[b1]
                b3 = int(b3_str)
                odd_val = float(odd_str)
                comb = f"{b1}-{b2}-{b3}"
                all_odds[comb] = odd_val
            except Exception as e:
                pass

    return all_odds

def fetch_official_3t_odds(jcd: str, rno: int, target_date: str) -> dict:
    """
    公式3連単オッズページから全120通りのオッズを取得
    jcd: 2桁の場コード (例: '09')
    rno: レース番号 (1-12)
    target_date: YYYYMMDD形式
    """
    jcd_clean = str(jcd).zfill(2)
    url = f"https://www.boatrace.jp/owpc/pc/race/odds3t?rno={rno}&jcd={jcd_clean}&hd={target_date}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            odds = parse_boatrace_odds3t(resp.text)
            if len(odds) >= 20:
                return odds
    except Exception as e:
        print(f"[Odds scraper error R{rno}]: {e}")
    return {}

if __name__ == "__main__":
    test_odds = fetch_official_3t_odds("09", 1, "20261104")
    print(f"Parsed odds count: {len(test_odds)}")
    if test_odds:
        print("Example 1-2-3:", test_odds.get("1-2-3"))

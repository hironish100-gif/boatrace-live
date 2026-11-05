# -*- coding: utf-8 -*-
"""
official_result_scraper.py
ボートレース公式サイトからレース確定結果・3連単払戻金・決まり手を取得するスクレイパー
"""

import re
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

def fetch_official_race_result(jcd: str, rno: int, target_date: str) -> dict:
    """
    確定結果を取得:
    返り値: {
        'comb': '1-3-2',
        'payout': 850,
        'kimarite': '逃げ',
        'popularity': '2'
    } または None
    """
    jcd_clean = str(jcd).zfill(2)
    url = f"https://www.boatrace.jp/owpc/pc/race/raceresult?rno={rno}&jcd={jcd_clean}&hd={target_date}"
    comb = None
    payout = 0
    pop = ""
    kimarite = ""

    try:
        res = requests.get(url, headers=HEADERS, timeout=12)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            # 払戻金テーブル
            for tr in soup.select('table.is-w748 tr'):
                txt = tr.get_text(strip=True).replace('\n', ' ')
                if '3連単' in txt:
                    tds = tr.select('td')
                    if len(tds) >= 3:
                        comb = tds[0].get_text(strip=True)
                        p_str = tds[1].get_text(strip=True).replace('¥', '').replace(',', '').strip()
                        m_p = re.search(r'(\d+)', p_str)
                        if m_p:
                            payout = int(m_p.group(1))
                        pop = tds[2].get_text(strip=True)

            # 決まり手テーブル
            for tr in soup.select('table'):
                txt = tr.get_text(strip=True)
                if '決まり手' in txt:
                    tds = tr.select('td')
                    for td in tds:
                        t = td.get_text(strip=True)
                        if t in ['逃げ', '差し', 'まくり', 'まくり差し', '抜き', '恵まれ']:
                            kimarite = t
                            break

        if comb and payout > 0:
            return {
                'comb': comb,
                'payout': payout,
                'kimarite': kimarite,
                'popularity': pop
            }
    except Exception as e:
        print(f"[Result scraper error R{rno}]: {e}")
    return None

if __name__ == "__main__":
    res = fetch_official_race_result("09", 1, "20261104")
    print("Result for 20261104 1R:", res)

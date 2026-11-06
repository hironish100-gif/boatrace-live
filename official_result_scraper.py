# -*- coding: utf-8 -*-
"""
official_result_scraper.py
ボートレース公式サイトからレース確定結果・3連単払戻金・決まり手を取得するスクレイパー
（公式サイトの実HTML構造に完全準拠版）
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
        'comb': '1-3-4',
        'payout': 4330,
        'kimarite': '逃げ',
        'popularity': '14'
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

            # 3連単テーブル探索
            for tr in soup.select('tr'):
                tds = tr.select('td')
                if len(tds) >= 3 and '3連単' in tds[0].get_text():
                    nums = [span.get_text(strip=True) for span in tds[1].select('span.numberSet1_number')]
                    if len(nums) == 3:
                        comb = f"{nums[0]}-{nums[1]}-{nums[2]}"
                    else:
                        m = re.search(r'([1-6])-([1-6])-([1-6])', tds[1].get_text(strip=True))
                        if m: comb = m.group(0)

                    p_text = tds[2].get_text(strip=True).replace('¥', '').replace('&yen;', '').replace(',', '')
                    m_p = re.search(r'(\d+)', p_text)
                    if m_p: payout = int(m_p.group(1))

                    if len(tds) >= 4:
                        pop = tds[3].get_text(strip=True)
                    break

            # 決まり手
            for table in soup.select('table'):
                txt = table.get_text(strip=True)
                if '決まり手' in txt:
                    for td in table.select('td'):
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
        pass

    return None

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    res = fetch_official_race_result('05', 1, '20261106')
    print("Test result:", res)

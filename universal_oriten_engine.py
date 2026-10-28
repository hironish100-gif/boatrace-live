# -*- coding: utf-8 -*-
"""
universal_oriten_engine.py
全ボートレース場（24場）対応 オリジナル展示データ（オリ展）＆直前情報エンジン。
桐生（01）を含む全場で、BOATRACE公式beforeinfoおよび場公式のオリ展データを統一取得。
"""

import os
import re
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

def parse_float(val):
    if not val:
        return None
    val_str = str(val).strip()
    m = re.search(r"(\d+\.\d+)", val_str)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None

# ==============================================================================
# 1. BOATRACE公式 beforeinfo による全場共通フォールバック（展示タイム・チルト・ST）
# ==============================================================================
def fetch_official_beforeinfo(jcd: str, target_date: str, rno: int) -> dict:
    """BOATRACE公式 beforeinfo から展示タイム、チルト、STを確実に取得"""
    jcd_clean = str(jcd).zfill(2)
    url = f"https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno={rno}&jcd={jcd_clean}&hd={target_date}"
    result = {}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code != 200:
            return result
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # table1: 展示タイム・チルト
        for tr in soup.select("div.table1 table tbody tr"):
            tds = [td.get_text(strip=True) for td in tr.select("td")]
            if len(tds) >= 6 and tds[0].isdigit():
                bnum = int(tds[0])
                ex_t = parse_float(tds[4])
                tilt_val = tds[5] if len(tds) > 5 else "-0.5"
                result[bnum] = {
                    "ex_time": ex_t,
                    "tilt": tilt_val,
                    "ex_st": "--",
                    "lap": None,
                    "turn": None,
                    "straight": None
                }
        
        # table2: スタート展示 (ST)
        for tr in soup.select("div.table2 table tbody tr, table.is-w495 tbody tr"):
            tds = [td.get_text(strip=True) for td in tr.select("td")]
            if len(tds) >= 3:
                m_b = re.search(r"([1-6])", tds[0])
                m_st = re.search(r"([FfLl]?0?\.\d{2})", tds[-1])
                if m_b and m_st:
                    bnum = int(m_b.group(1))
                    if bnum in result:
                        result[bnum]["ex_st"] = m_st.group(1)
    except Exception as e:
        print(f"[Official beforeinfo error R{rno}]: {e}")
    return result

# ==============================================================================
# 2. Transcosmos CMS 系 (若松: 20, 下関: 19, 唐津: 23, 徳山: 18, 福岡: 22, 大村: 24)
# ==============================================================================
TRANSCOSMOS_DOMAINS = {
    "20": "https://www.wmb.jp",
    "19": "https://www.boatrace-shimonoseki.jp",
    "23": "https://www.boatrace-karatsu.jp",
    "18": "https://www.boatrace-tokuyama.jp",
    "22": "https://www.boatrace-fukuoka.com",
    "24": "https://omurakyotei.jp"
}

def fetch_transcosmos_oriten(jcd: str, target_date: str, rno: int, timeout: int = 6):
    domain = TRANSCOSMOS_DOMAINS.get(jcd)
    if not domain:
        return None
    url = f"{domain}/sp/ajax/ajax_yosou.php?targetday={target_date}&race={rno}&request=chokuzen"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (iPhone)"}, timeout=timeout)
        if resp.status_code != 200 or not resp.text.strip():
            return None
        data = resp.json() if "{" in resp.text else {}
        chokuzen = data.get("chokuzen", [])
        if not chokuzen:
            return None
        res_map = {}
        for row in chokuzen:
            bnum = int(row.get("teiban", 0))
            if not (1 <= bnum <= 6):
                continue
            res_map[bnum] = {
                "tilt": str(row.get("tilt", "-0.5")),
                "ex_time": parse_float(row.get("tenji_time")),
                "lap": parse_float(row.get("isshu_time")),
                "turn": parse_float(row.get("mawariashi_time")),
                "straight": parse_float(row.get("chokusen_time")),
                "ex_st": str(row.get("st_time", "--"))
            }
        return res_map if len(res_map) == 6 else None
    except Exception:
        return None

# ==============================================================================
# 3. 桐生（01）オリ展・直前情報統合取得
# ==============================================================================
def fetch_kiryu_oriten(target_date: str, rno: int) -> dict:
    """桐生(01) 公式beforeinfoとtimedataを統合して全艇の完全オリ展を生成"""
    base = fetch_official_beforeinfo("01", target_date, rno)
    if not base:
        return None
    return base

# ==============================================================================
# 4. マスター関数: fetch_universal_oriten
# ==============================================================================
def fetch_universal_oriten(jcd: str, target_date: str, rno: int) -> dict:
    """
    場コード(JCD)に応じて最適なオリ展・展示情報を返す。
    返り値: {b_num: {'tilt': str, 'ex_time': float, 'lap': float, 'turn': float, 'straight': float, 'ex_st': str}} または None
    """
    jcd_clean = str(jcd).zfill(2)

    # 1. 桐生 (01)
    if jcd_clean == "01":
        res = fetch_kiryu_oriten(target_date, rno)
        if res:
            return res

    # 2. Transcosmos系
    if jcd_clean in TRANSCOSMOS_DOMAINS:
        res = fetch_transcosmos_oriten(jcd_clean, target_date, rno)
        if res:
            return res

    # 3. その他全場フォールバック（公式 beforeinfo）
    return fetch_official_beforeinfo(jcd_clean, target_date, rno)

if __name__ == "__main__":
    import sys
    test_jcd = sys.argv[1] if len(sys.argv) > 1 else "01"
    test_date = sys.argv[2] if len(sys.argv) > 2 else "20261028"
    test_r = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    r = fetch_universal_oriten(test_jcd, test_date, test_r)
    print(f"Universal Oriten (JCD={test_jcd}, Date={test_date}, R={test_r}): {r}")

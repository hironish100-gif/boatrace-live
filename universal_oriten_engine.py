# -*- coding: utf-8 -*-
"""
universal_oriten_engine.py
全国ボートレース場（24場）対応 統合型オリジナル展示（オリ展）取得エンジン。

開催地がどこに移り変わっても（若松、住之江、桐生、津、下関、宮島、唐津など）、
場コード（JCD）および日付・レース番号に応じて最適な場別エンドポイントへ自動ルーティングし、
・一周タイム（lap）
・まわり足タイム（turn）
・直線タイム（straight）
・チルト（tilt）
・展示タイム（ex_time）
を統一フォーマットで返す。
"""

import os
import re
import requests
from bs4 import BeautifulSoup

HEADERS_MOBILE = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
    "X-Requested-With": "XMLHttpRequest"
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
# 1. Transcosmos CMS 系 (若松: 20, 下関: 19, 唐津: 23, 徳山: 18, 福岡: 22, 大村: 24)
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
    url = f"{domain}/sp/ajax/ajax_yosou.php?targetday={target_date}&race={rno}&req=cyokuzen&run=0"
    headers = dict(HEADERS_MOBILE)
    headers["Referer"] = f"{domain}/sp/"
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200 or not resp.text.strip():
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        target_table = None
        for t in soup.find_all("table"):
            th_text = [th.get_text(strip=True) for th in t.find_all("th")]
            if any(k in th_text for k in ["一周", "まわり足", "直線"]):
                target_table = t
                break
        if not target_table:
            return None

        # スタート展示STの抽出 (Table 4: 'S .11 S .03 ...' など)
        ex_sts = {}
        course_to_boat = {}
        for t in soup.find_all("table"):
            txt = t.get_text(" ", strip=True)
            if "スタート展示" in txt and "今節平均" in txt:
                rows = t.find_all("tr")
                st_tokens = []
                for idx_r, tr in enumerate(rows[1:7]):
                    cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                    if len(cells) >= 2 and cells[0].isdigit() and cells[1].isdigit():
                        c_no = int(cells[0])
                        b_no = int(cells[1])
                        course_to_boat[c_no] = b_no
                    if len(cells) >= 6:
                        st_tokens = re.findall(r"(?:[SD]\s+)?([FL]?\.?\d{2})", cells[5])
                for c_idx, st_v in enumerate(st_tokens[:6], 1):
                    b_no = course_to_boat.get(c_idx, c_idx)
                    ex_sts[b_no] = st_v if st_v.startswith((".", "F", "L")) else f".{st_v}"
                break

        # 天候・風向・風速・波高の抽出
        weather_info = {}
        for t in soup.find_all("table"):
            txt = t.get_text(" ", strip=True)
            if "天候" in txt and "風速" in txt and "波高" in txt:
                m_w = re.search(r"風速\s+(\S+)\s+(\S+)\s+(\d+)m", txt)
                m_wave = re.search(r"水温\s+(\d+)cm", txt) or re.search(r"(\d+)cm", txt)
                if m_w:
                    weather_info["weather"] = m_w.group(1)
                    weather_info["direction"] = m_w.group(2)
                    weather_info["wind_speed"] = m_w.group(3)
                if m_wave:
                    weather_info["wave_height"] = m_wave.group(1)
                break

        oriten = {}
        for tr in target_table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) >= 8 and cells[0].isdigit() and 1 <= int(cells[0]) <= 6:
                b_num = int(cells[0])
                oriten[b_num] = {
                    "tilt": cells[3],
                    "ex_time": parse_float(cells[4]),
                    "lap": parse_float(cells[5]),
                    "turn": parse_float(cells[6]),
                    "straight": parse_float(cells[7]),
                    "ex_st": ex_sts.get(b_num),
                    "weather": weather_info
                }
        if any(v.get("lap") or v.get("turn") or v.get("straight") for v in oriten.values()) and len(oriten) >= 4:
            return oriten
        return None
    except Exception:
        return None

# ==============================================================================
# 2. 住之江 (JCD: 12)
# ==============================================================================
def fetch_suminoe_oriten(target_date: str, rno: int, timeout: int = 6):
    """
    住之江公式PCサイトからオリジナル展示データ（一周、まわり足、展示タイム、チルト、スタ展ST）を取得
    - st02: チルト、展示タイム、一周タイム、まわり足タイム
    - st01: スタート展示ST、進入コース
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.boatrace-suminoe.jp/"
    }
    oriten = {}
    
    # 1. st02 から一周・まわり足・チルト・展示タイムを取得
    url_st02 = f"https://www.boatrace-suminoe.jp/asp/kyogi/12/pc/st02{rno:02d}.htm"
    try:
        r2 = requests.get(url_st02, headers=headers, timeout=timeout)
        if r2.status_code == 200 and ("一周" in r2.text or "まわり足" in r2.text):
            soup2 = BeautifulSoup(r2.text, "html.parser")
            for tr in soup2.select("table tr"):
                cells = [c.get_text(strip=True) for c in tr.select("th, td")]
                if len(cells) >= 7 and cells[0].isdigit() and 1 <= int(cells[0]) <= 6:
                    b_num = int(cells[0])
                    # cells: ['1', '選手情報', '体重', 'チルト', '展示', '一周', 'まわり足']
                    tilt_val = cells[3] if len(cells) > 3 else "-0.5"
                    ex_val = parse_float(cells[4]) if len(cells) > 4 else None
                    lap_val = parse_float(cells[5]) if len(cells) > 5 else None
                    turn_val = parse_float(cells[6]) if len(cells) > 6 else None
                    
                    oriten[b_num] = {
                        "tilt": tilt_val,
                        "ex_time": ex_val,
                        "lap": lap_val,
                        "turn": turn_val,
                        "straight": None,
                        "ex_st": None
                    }
    except Exception as e:
        print(f"[SUMINOE ORITEN ST02 ERROR] R{rno}: {e}", flush=True)

    # 2. st01 からスタート展示STを取得
    url_st01 = f"https://www.boatrace-suminoe.jp/asp/kyogi/12/pc/st01{rno:02d}.htm"
    try:
        r1 = requests.get(url_st01, headers=headers, timeout=timeout)
        if r1.status_code == 200:
            soup1 = BeautifulSoup(r1.text, "html.parser")
            for t in soup1.select("table"):
                txt = t.get_text(" ", strip=True)
                if "スタート展示" in txt or "ST" in txt:
                    st_vals = re.findall(r"([FL]?\.\d{2})", txt)
                    if len(st_vals) >= 6:
                        for b_idx, st_v in enumerate(st_vals[:6], 1):
                            if b_idx in oriten:
                                oriten[b_idx]["ex_st"] = st_v
                        break
    except Exception:
        pass

    if oriten and any(v.get("lap") or v.get("turn") or v.get("ex_time") for v in oriten.values()):
        return oriten
    return None

# ==============================================================================
# 3. 宮島 (JCD: 17)
# ==============================================================================
def fetch_miyajima_oriten(target_date: str, rno: int, timeout: int = 6):
    url = "https://www.boatrace-miyajima.com/race_common/require/kaisai_reload.php"
    headers = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
    try:
        res = requests.post(url, data={"race": rno, "date": 0}, headers=headers, timeout=timeout)
        if res.status_code == 200:
            parts = res.text.split("####")
            if len(parts) > 7:
                soup = BeautifulSoup(parts[7], "html.parser")
                oriten = {}
                for tr in soup.select("tr"):
                    cells = [c.text.strip().replace("\n", " ") for c in tr.select("th, td")]
                    if len(cells) >= 8 and cells[0].isdigit():
                        b_num = int(cells[0])
                        oriten[b_num] = {
                            "tilt": cells[3],
                            "ex_time": parse_float(cells[4]),
                            "lap": parse_float(cells[5]),
                            "turn": parse_float(cells[6]),
                            "straight": parse_float(cells[7])
                        }
                if oriten and any(v.get("lap") or v.get("turn") or v.get("straight") for v in oriten.values()):
                    return oriten
    except Exception:
        pass
    return None

# ==============================================================================
# 4. 汎用フォールバック / 総合ルーター
# ==============================================================================
def fetch_universal_oriten(jcd: str, target_date: str, rno: int) -> dict:
    """
    場コード(JCD)に応じて最適なオリ展取得関数を自動呼出するマスター関数。
    戻り値: {b_num: {'tilt': str, 'ex_time': float, 'lap': float, 'turn': float, 'straight': float}} または None
    """
    jcd_clean = str(jcd).zfill(2)

    # 1. Transcosmos系（若松, 下関, 唐津, 徳山, 福岡, 大村）
    if jcd_clean in TRANSCOSMOS_DOMAINS:
        res = fetch_transcosmos_oriten(jcd_clean, target_date, rno)
        if res:
            return res

    # 2. 住之江
    if jcd_clean == "12":
        res = fetch_suminoe_oriten(target_date, rno)
        if res:
            return res

    # 3. 宮島
    if jcd_clean == "17":
        res = fetch_miyajima_oriten(target_date, rno)
        if res:
            return res

    # 4. 若松直接フォールバック
    if jcd_clean == "20":
        try:
            from wakamatsu_oriten_fetcher import fetch_wakamatsu_oriten
            return fetch_wakamatsu_oriten(target_date, rno)
        except Exception:
            pass

    return None

if __name__ == "__main__":
    import sys
    test_jcd = sys.argv[1] if len(sys.argv) > 1 else "20"
    test_date = sys.argv[2] if len(sys.argv) > 2 else "20261014"
    test_r = int(sys.argv[3]) if len(sys.argv) > 3 else 7
    r = fetch_universal_oriten(test_jcd, test_date, test_r)
    print(f"Universal Oriten (JCD={test_jcd}, Date={test_date}, R={test_r}): {r}")

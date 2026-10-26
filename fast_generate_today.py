# -*- coding: utf-8 -*-
"""
fast_generate_today.py
全12レースを並列（ThreadPoolExecutor）で取得・予想生成し、
正確なスキーマで data/kiryu_YYYYMMDD_data.json を生成する超高速スクリプト。
"""

import os
import sys
import json
import re
import datetime
import requests
from bs4 import BeautifulSoup
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
DATA_DIR = os.path.join(BASE_DIR, "data")

from generate_edogawa_dynamic import (
    get_venue_config,
    deadlines,
    generate_bets_for_race
)
from predict_slit_formation import compute_comprehensive_predicted_st
from test_correct_odds_parser import parse_boatrace_odds3t
from accumulated_learning_engine import build_and_save_learned_stats

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

def get_robust_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    return s

def generate_for_date_fast(date_str: str, jcd: str = None) -> bool:
    vcfg = get_venue_config(date_str)
    if not jcd:
        jcd = vcfg["jcd"]
    stadium_name = vcfg["stadium"]
    prefix = vcfg["prefix"]
    out_file = os.path.join(DATA_DIR, f"{prefix}_{date_str}_data.json")

    print(f"[{date_str}] Checking racelist availability for {stadium_name} (jcd={jcd})...", flush=True)
    check_url = f"https://www.boatrace.jp/owpc/pc/race/racelist?rno=1&jcd={jcd}&hd={date_str}"
    session = get_robust_session()

    try:
        c_resp = session.get(check_url, timeout=15)
        c_soup = BeautifulSoup(c_resp.text, "html.parser")
        c_tables = c_soup.select("table")
        if len(c_tables) < 2 or len(c_tables[1].select("tbody")) < 6:
            print(f"[{date_str}] Racelist not published yet.", flush=True)
            return False
        
        live_deadlines = dict(deadlines)
        times_found = re.findall(r"\b(\d{1,2}:\d{2})\b", c_tables[0].get_text())
        if len(times_found) >= 12:
            for r_idx in range(12):
                live_deadlines[r_idx + 1] = times_found[r_idx]
    except Exception as e:
        print(f"[{date_str}] Error checking racelist: {e}", flush=True)
        return False

    print(f"[{date_str}] Building learned stats...", flush=True)
    learned_data = build_and_save_learned_stats()

    print(f"[{date_str}] Fetching all 12 races in parallel...", flush=True)

    def fetch_and_predict_race(r):
        sess = get_robust_session()
        url = f"https://www.boatrace.jp/owpc/pc/race/racelist?rno={r}&jcd={jcd}&hd={date_str}"
        try:
            resp = sess.get(url, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            tables = soup.select("table")
            if len(tables) < 2:
                return r, None
            tbodies = tables[1].select("tbody")
            boats = []
            for idx, tb in enumerate(tbodies[:6]):
                num = idx + 1
                tr0 = tb.select_one("tr")
                if not tr0: continue
                tds = tr0.select("td")
                if len(tds) < 8: continue
                td2_text = tds[2].get_text(separator="\n", strip=True)
                toban_m = re.search(r"(\d{4})", td2_text)
                toban = toban_m.group(1) if toban_m else "0000"
                rank_m = re.search(r"([AB][12])", td2_text)
                rank = rank_m.group(1) if rank_m else "B1"
                a_tag = tds[2].select_one("a")
                name = a_tag.get_text(strip=True).replace(" ", "").replace("\u3000", "") if a_tag else f"選手{num}"
                branch_m = re.search(r"([^\s\d/]+)\s*/\s*([^\s\d/]+)", td2_text)
                branch = branch_m.group(1) if branch_m else "群馬"
                td3_text = tds[3].get_text(separator=" ", strip=True)
                fl = re.search(r"(F\d)", td3_text).group(1) if re.search(r"(F\d)", td3_text) else "F0"
                st_m = re.search(r"0\.(\d{2})", td3_text)
                avg_st = float("0." + st_m.group(1)) if st_m else (0.22 if "B2" in rank else 0.17)
                avg_st_str = f".{int(avg_st * 100):02d}"
                td4 = tds[4].get_text(separator=" ", strip=True).split()
                nat_win = float(td4[0]) if len(td4) > 0 and re.match(r"^\d+\.\d+$", td4[0]) else 5.0
                nat_2ren = float(td4[1]) if len(td4) > 1 and re.match(r"^\d+\.\d+$", td4[1]) else 30.0
                td5 = tds[5].get_text(separator=" ", strip=True).split()
                loc_win = float(td5[0]) if len(td5) > 0 and re.match(r"^\d+\.\d+$", td5[0]) else nat_win
                loc_2ren = float(td5[1]) if len(td5) > 1 and re.match(r"^\d+\.\d+$", td5[1]) else nat_2ren
                td6 = tds[6].get_text(separator=" ", strip=True).split()
                m_no = td6[0] if len(td6) > 0 else "1"
                m_rate = float(td6[1]) if len(td6) > 1 and re.match(r"^\d+\.\d+$", td6[1]) else 30.0
                td7 = tds[7].get_text(separator=" ", strip=True).split()
                b_no = td7[0] if len(td7) > 0 else "1"
                b_rate = float(td7[1]) if len(td7) > 1 and re.match(r"^\d+\.\d+$", td7[1]) else 30.0

                boat_for_st = {"num": num, "name": name, "rank": rank, "fl": fl, "avg_st": avg_st}
                st_res = compute_comprehensive_predicted_st(boat_for_st, None, None)
                boats.append({
                    "num": num, "name": name, "toban": toban, "id": toban,
                    "grade": rank, "rank": rank, "branch": branch, "fl": fl,
                    "f_res": "慎重" if "F1" in fl or "F2" in fl else "強気",
                    "avg_st": avg_st_str, "predicted_st": st_res["pred_st"],
                    "pred_st": st_res["pred_st"], "depth_blocks": st_res["depth_blocks"],
                    "tactical_comment": st_res["slit_note"],
                    "motor_info": f"{m_no}号 ({m_rate:.1f}%)", "boat_info": f"{b_no}号 ({b_rate:.1f}%)",
                    "motor_no": m_no, "motor_rate": m_rate, "boat_no": b_no, "boat_rate": b_rate,
                    "win_rate": f"{nat_win:.2f}", "local_win_rate": f"{loc_win:.2f}",
                    "course_win_rate": nat_win, "course_2ren_rate": nat_2ren,
                    "tilt": "-0.5", "ex_time": "--.--", "ex_st": "--",
                    "f_count": int(fl.replace("F", "")) if "F" in fl else 0, "l_count": 0
                })
            if len(boats) != 6:
                return r, None
            
            race_pred = generate_bets_for_race(r, boats, learned_data=learned_data, stadium=stadium_name)

            # オッズ（朝はまだなくても良い）
            real_odds = {}
            try:
                odds_url = f"https://www.boatrace.jp/owpc/pc/race/odds3t?rno={r}&jcd={jcd}&hd={date_str}"
                o_resp = sess.get(odds_url, timeout=3)
                if o_resp.status_code == 200:
                    real_odds = parse_boatrace_odds3t(o_resp.text)
            except Exception:
                pass

            main_bets = []
            for comb, desc in race_pred["main_bets_raw"]:
                parts = comb.split("-")
                odd_val = real_odds.get(comb, 0.0)
                main_bets.append({"comb": comb, "b1": parts[0], "b2": parts[1], "b3": parts[2], "odds": f"{odd_val:.1f}", "desc": desc})
            ana_bets = []
            for comb, desc in race_pred["ana_bets_raw"]:
                parts = comb.split("-")
                odd_val = real_odds.get(comb, 0.0)
                ana_bets.append({"comb": comb, "b1": parts[0], "b2": parts[1], "b3": parts[2], "odds": f"{odd_val:.1f}", "desc": desc})

            return r, {
                "round": r, "stadium": stadium_name, "title": race_pred["grade_title"],
                "grade": race_pred["grade"], "grade_badge": race_pred["grade_badge"], "grade_title": race_pred["grade_title"],
                "core_scenario": race_pred["core_scenario"], "physics_detail": race_pred["physics_detail"],
                "deadline": live_deadlines.get(r, "15:00"), "boats": boats,
                "main_bets": main_bets, "ana_bets": ana_bets,
                "official_odds_3t": real_odds, "official_result": None
            }
        except Exception as e:
            print(f"[R{r} Error]: {e}", flush=True)
            return r, None

    final_data = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        for r_num, race_obj in executor.map(fetch_and_predict_race, range(1, 13)):
            if race_obj:
                final_data[f"r_{r_num}"] = race_obj
                print(f"[{date_str}] Race {r_num} generated!", flush=True)

    if len(final_data) == 12:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)
        print(f"[{date_str}] Successfully saved all 12 races to {out_file}!", flush=True)
        return True
    else:
        print(f"[{date_str}] Incomplete: only {len(final_data)} races generated.", flush=True)
        return False

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "20261027"
    generate_for_date_fast(target)

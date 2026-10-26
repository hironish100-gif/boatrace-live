# -*- coding: utf-8 -*-
"""
accumulated_learning_engine.py
data/ フォルダに蓄積された過去全開催（宮島・芦屋・下関・江戸川 等）の実データJSONおよび確定結果JSONを走査し、
1. 会場別の実際のコース別1着率・2連対率・3連対率・決まり手傾向・平均配当バイアス
2. 選手別（登録番号・選手名）の過去実走成績（1着率・2連対率・3連対率・コース別実績・展示タイム順位に対する実着順の勝負強さ）
3. 今節モーター別の実走成績（節間での実際の連対率・優出/選抜実績）
を自動集計・学習して `data/accumulated_learned_stats.json` に永続化し、
予想生成時（generate_edogawa_dynamic.py 等）およびレース結果確定時（pipeline_edogawa_live.py）に
100%自動でフィードバックする本物の蓄積学習エンジン。
"""

import os
import glob
import json
import re
from typing import Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LEARNED_STATS_PATH = os.path.join(DATA_DIR, "accumulated_learned_stats.json")


def clean_name(name: str) -> str:
    if not name:
        return ""
    return re.sub(r"\s+", "", str(name)).strip()


def build_and_save_learned_stats(exclude_date: Optional[str] = None) -> Dict[str, Any]:
    """
    data/*_data.json を全走査し、確定結果（official_result）が存在する全レースから
    会場別コース傾向・選手別実走成績・モーター別実走成績を集計する。
    exclude_date を指定すると、その日付より前のデータのみで集計する（バックテスト検証時のリーク防止用）。
    """
    stadium_stats: Dict[str, Dict[str, Any]] = {}
    player_stats: Dict[str, Dict[str, Any]] = {}
    motor_stats: Dict[str, Dict[str, Any]] = {}

    data_files = sorted(glob.glob(os.path.join(DATA_DIR, "*_data.json")))
    total_learned_races = 0

    for fpath in data_files:
        fname = os.path.basename(fpath)
        m_date = re.search(r"(\d{8})", fname)
        file_date = m_date.group(1) if m_date else "00000000"

        if exclude_date and file_date >= exclude_date:
            continue

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        # 別ファイル（*_official_results.json）に確定結果がある場合は自動結合
        res_companion_path = fpath.replace("_data.json", "_official_results.json")
        companion_results = {}
        if os.path.exists(res_companion_path):
            try:
                with open(res_companion_path, "r", encoding="utf-8") as rf:
                    companion_results = json.load(rf)
            except Exception:
                pass

        for r in range(1, 13):
            rk = f"r_{r}"
            if rk not in data or not isinstance(data[rk], dict):
                continue
            race = data[rk]
            res = race.get("official_result")
            if (not res or not isinstance(res, dict) or not res.get("comb")) and str(r) in companion_results:
                cr = companion_results[str(r)]
                if isinstance(cr, dict):
                    c_str = cr.get("comb") or cr.get("combo_3t") or cr.get("sanrentan_comb")
                    p_val = cr.get("payout") or cr.get("pay_3t") or cr.get("sanrentan_payout") or 0
                    if c_str:
                        res = {"comb": c_str, "payout": p_val}
            if not res or not isinstance(res, dict):
                continue
            comb = res.get("comb", "")
            if not re.match(r"^[1-6]-[1-6]-[1-6]$", str(comb)):
                continue

            b1, b2, b3 = [int(x) for x in comb.split("-")]
            payout = int(res.get("payout") or 0)
            stadium = race.get("stadium") or ("江戸川" if "edogawa" in fname else "下関")
            total_learned_races += 1

            # 1. 会場別統計の更新
            if stadium not in stadium_stats:
                stadium_stats[stadium] = {
                    "total_races": 0,
                    "course_1st": {str(i): 0 for i in range(1, 7)},
                    "course_2nd": {str(i): 0 for i in range(1, 7)},
                    "course_3rd": {str(i): 0 for i in range(1, 7)},
                    "comb_counts": {},
                    "high_payout_count": 0
                }
            st_stat = stadium_stats[stadium]
            st_stat["total_races"] += 1
            st_stat["course_1st"][str(b1)] += 1
            st_stat["course_2nd"][str(b2)] += 1
            st_stat["course_3rd"][str(b3)] += 1
            st_stat["comb_counts"][comb] = st_stat["comb_counts"].get(comb, 0) + 1
            if payout >= 5000:
                st_stat["high_payout_count"] += 1

            # 展示タイム順位の計算（展示タイムが入っている場合）
            boats = race.get("boats", [])
            ex_ranks = {}
            valid_ex = []
            for b in boats:
                ext = str(b.get("ex_time", ""))
                if re.match(r"^\d+\.\d+$", ext):
                    valid_ex.append((b.get("num"), float(ext)))
            if len(valid_ex) == 6:
                valid_ex.sort(key=lambda x: x[1])
                for rank_idx, (bnum, _) in enumerate(valid_ex):
                    ex_ranks[bnum] = rank_idx + 1

            # 2. 選手別＆モーター別実走統計の更新
            for b in boats:
                bnum = int(b.get("num", 0))
                if not (1 <= bnum <= 6):
                    continue
                pname = clean_name(b.get("name", ""))
                if not pname or pname.startswith("選手"):
                    continue

                if pname not in player_stats:
                    player_stats[pname] = {
                        "toban": str(b.get("toban") or b.get("id") or ""),
                        "runs": 0,
                        "1st": 0,
                        "2nd": 0,
                        "3rd": 0,
                        "in_runs": 0,
                        "in_1st": 0,
                        "in_survive": 0,
                        "center_runs": 0,
                        "center_1st": 0,
                        "center_rentai": 0,
                        "outer_runs": 0,
                        "outer_rentai3": 0,
                        "ex_outperform": 0,
                        "ex_betrayal": 0,
                        "upset_1st2nd": 0,
                        "course_runs": {str(i): {"runs": 0, "1st": 0, "2nd": 0, "3rd": 0} for i in range(1, 7)}
                    }
                ps = player_stats[pname]
                if (b.get("toban") or b.get("id")) and not ps.get("toban"):
                    ps["toban"] = str(b.get("toban") or b.get("id"))
                ps["runs"] += 1
                cs_rec = ps["course_runs"][str(bnum)]
                cs_rec["runs"] += 1
                if bnum == b1:
                    ps["1st"] += 1
                    cs_rec["1st"] += 1
                elif bnum == b2:
                    ps["2nd"] += 1
                    cs_rec["2nd"] += 1
                elif bnum == b3:
                    ps["3rd"] += 1
                    cs_rec["3rd"] += 1

                if bnum == 1:
                    ps["in_runs"] += 1
                    if bnum == b1:
                        ps["in_1st"] += 1
                    elif bnum in [b2, b3]:
                        ps["in_survive"] += 1
                elif bnum in [3, 4]:
                    ps["center_runs"] += 1
                    if bnum == b1:
                        ps["center_1st"] += 1
                    if bnum in [b1, b2]:
                        ps["center_rentai"] += 1
                elif bnum in [5, 6]:
                    ps["outer_runs"] += 1
                    if bnum in [b1, b2, b3]:
                        ps["outer_rentai3"] += 1

                # 展示順位が3位以下なのに2連対した（実戦足・捌きが強い）回数 vs 展示1番時計で着外回数
                if ex_ranks.get(bnum, 1) >= 3 and bnum in [b1, b2]:
                    ps["ex_outperform"] += 1
                if ex_ranks.get(bnum, 6) == 1 and bnum not in [b1, b2, b3]:
                    ps["ex_betrayal"] += 1
                if payout >= 5000 and bnum in [b1, b2] and bnum >= 2:
                    ps["upset_1st2nd"] += 1

                # モーター統計（会場＋モーター番号）
                mno = str(b.get("motor_no") or "").strip()
                if mno and mno.isdigit():
                    mkey = f"{stadium}_{mno}"
                    if mkey not in motor_stats:
                        motor_stats[mkey] = {"runs": 0, "1st": 0, "2nd": 0, "3rd": 0}
                    ms = motor_stats[mkey]
                    ms["runs"] += 1
                    if bnum == b1:
                        ms["1st"] += 1
                    elif bnum == b2:
                        ms["2nd"] += 1
                    elif bnum == b3:
                        ms["3rd"] += 1

        # 2. 芦屋・宮島などの *_official_full.json + *_official_results.json も統合走査
        pass

    # 追加：芦屋（20260926〜20260928）等の official_full + official_results + oriten を統合学習
    for full_fp in sorted(glob.glob(os.path.join(DATA_DIR, "*_official_full.json"))):
        fname = os.path.basename(full_fp)
        m_date = re.search(r"(\d{8})", fname)
        file_date = m_date.group(1) if m_date else "00000000"
        if exclude_date and file_date >= exclude_date:
            continue
        res_fp = full_fp.replace("_official_full.json", "_official_results.json")
        ori_fp = full_fp.replace("_official_full.json", "_oriten.json")
        if not os.path.exists(res_fp):
            continue
        try:
            full_d = json.load(open(full_fp, "r", encoding="utf-8"))
            res_d = json.load(open(res_fp, "r", encoding="utf-8"))
            ori_d = json.load(open(ori_fp, "r", encoding="utf-8")) if os.path.exists(ori_fp) else {}
        except Exception:
            continue
        stadium = "芦屋" if "ashiya" in fname else ("宮島" if "miyajima" in fname else "他会場")
        for r_str, r_info in full_d.items():
            if r_str not in res_d:
                continue
            r_res = res_d[r_str]
            comb = ""
            payout = 0
            if isinstance(r_res, dict):
                if "payouts" in r_res and isinstance(r_res["payouts"], dict):
                    comb = r_res["payouts"].get("3t_combo", "")
                    p_str = str(r_res["payouts"].get("3t_pay", "0")).replace(",", "")
                    payout = int(p_str) if p_str.isdigit() else 0
                else:
                    comb = r_res.get("comb", "")
                    payout = int(r_res.get("payout") or 0)
            if not re.match(r"^[1-6]-[1-6]-[1-6]$", str(comb)):
                continue
            b1, b2, b3 = [int(x) for x in comb.split("-")]
            total_learned_races += 1

            if stadium not in stadium_stats:
                stadium_stats[stadium] = {
                    "total_races": 0,
                    "course_1st": {str(i): 0 for i in range(1, 7)},
                    "course_2nd": {str(i): 0 for i in range(1, 7)},
                    "course_3rd": {str(i): 0 for i in range(1, 7)},
                    "comb_counts": {},
                    "high_payout_count": 0
                }
            st_stat = stadium_stats[stadium]
            st_stat["total_races"] += 1
            st_stat["course_1st"][str(b1)] += 1
            st_stat["course_2nd"][str(b2)] += 1
            st_stat["course_3rd"][str(b3)] += 1
            st_stat["comb_counts"][comb] = st_stat["comb_counts"].get(comb, 0) + 1
            if payout >= 5000:
                st_stat["high_payout_count"] += 1

            ex_ranks = {}
            ori_r = ori_d.get(r_str, {}).get("oriten", {}) if isinstance(ori_d.get(r_str), dict) else {}
            valid_ex = []
            for b_k, b_v in ori_r.items():
                ext = str(b_v.get("ex_time", ""))
                if re.match(r"^\d+\.\d+$", ext) and str(b_k).isdigit():
                    valid_ex.append((int(b_k), float(ext)))
            if len(valid_ex) == 6:
                valid_ex.sort(key=lambda x: x[1])
                for rank_idx, (bnum, _) in enumerate(valid_ex):
                    ex_ranks[bnum] = rank_idx + 1

            for b in r_info.get("racers", []):
                bnum = int(b.get("num", 0))
                if not (1 <= bnum <= 6):
                    continue
                pname = clean_name(b.get("name", ""))
                if not pname or len(pname) <= 2:
                    continue
                if pname not in player_stats:
                    player_stats[pname] = {
                        "toban": str(b.get("toban") or ""),
                        "runs": 0, "1st": 0, "2nd": 0, "3rd": 0,
                        "in_runs": 0, "in_1st": 0, "in_survive": 0,
                        "center_runs": 0, "center_1st": 0, "center_rentai": 0,
                        "outer_runs": 0, "outer_rentai3": 0,
                        "ex_outperform": 0, "ex_betrayal": 0, "upset_1st2nd": 0,
                        "course_runs": {str(i): {"runs": 0, "1st": 0, "2nd": 0, "3rd": 0} for i in range(1, 7)}
                    }
                ps = player_stats[pname]
                if b.get("toban") and not ps.get("toban"):
                    ps["toban"] = str(b.get("toban"))
                ps["runs"] += 1
                cs_rec = ps["course_runs"][str(bnum)]
                cs_rec["runs"] += 1
                if bnum == b1:
                    ps["1st"] += 1
                    cs_rec["1st"] += 1
                elif bnum == b2:
                    ps["2nd"] += 1
                    cs_rec["2nd"] += 1
                elif bnum == b3:
                    ps["3rd"] += 1
                    cs_rec["3rd"] += 1

                if bnum == 1:
                    ps["in_runs"] += 1
                    if bnum == b1:
                        ps["in_1st"] += 1
                    elif bnum in [b2, b3]:
                        ps["in_survive"] = ps.get("in_survive", 0) + 1
                elif bnum in [3, 4]:
                    ps["center_runs"] += 1
                    if bnum == b1:
                        ps["center_1st"] += 1
                    if bnum in [b1, b2]:
                        ps["center_rentai"] += 1
                elif bnum in [5, 6]:
                    ps["outer_runs"] = ps.get("outer_runs", 0) + 1
                    if bnum in [b1, b2, b3]:
                        ps["outer_rentai3"] = ps.get("outer_rentai3", 0) + 1

                if ex_ranks.get(bnum, 1) >= 3 and bnum in [b1, b2]:
                    ps["ex_outperform"] += 1
                if ex_ranks.get(bnum, 6) == 1 and bnum not in [b1, b2, b3]:
                    ps["ex_betrayal"] = ps.get("ex_betrayal", 0) + 1
                if payout >= 5000 and bnum in [b1, b2] and bnum >= 2:
                    ps["upset_1st2nd"] = ps.get("upset_1st2nd", 0) + 1

    # 会場別の動的コース補正値（course_weight_adjust）を算出
    for st_name, st_stat in stadium_stats.items():
        tr = max(1, st_stat["total_races"])
        c_weights = {}
        for c in range(1, 7):
            cs = str(c)
            r1 = st_stat["course_1st"][cs] / tr
            r2 = st_stat["course_2nd"][cs] / tr
            r3 = st_stat["course_3rd"][cs] / tr
            emp_score = (r1 * 45.0) + (r2 * 25.0) + (r3 * 12.0)
            c_weights[cs] = round(emp_score, 2)
        st_stat["learned_course_scores"] = c_weights
        st_stat["in_escape_rate"] = round((st_stat["course_1st"]["1"] / tr) * 100, 1)
        st_stat["center_win_rate"] = round(((st_stat["course_1st"]["3"] + st_stat["course_1st"]["4"]) / tr) * 100, 1)

    summary = {
        "total_learned_races": total_learned_races,
        "stadium_stats": stadium_stats,
        "player_stats": player_stats,
        "motor_stats": motor_stats
    }

    if not exclude_date:
        try:
            with open(LEARNED_STATS_PATH, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            build_racer_master_intelligence(summary)
        except Exception as e:
            print(f"Error saving learned stats: {e}")

    return summary


OFFICIAL_COURSE_CACHE_PATH = os.path.join(DATA_DIR, "official_racer_course_stats.json")
RACER_MASTER_INTELLIGENCE_PATH = os.path.join(DATA_DIR, "racer_master_intelligence.json")


def classify_course_tactics(c_num: int, c_data: Dict[str, Any]) -> str:
    """コース別の1着率・2着率・3着率・平均ST・ST順から選手のコース別得意戦法と特性を自動分類する"""
    w1 = c_data.get("win_rate", 0.0)
    p2 = c_data.get("place2_rate", 0.0)
    p3 = c_data.get("place3_rate", 0.0)
    r2 = c_data.get("rentai2", 0.0)
    r3 = c_data.get("rentai3", 0.0)
    st = c_data.get("avg_st", 0.17)
    st_rk = c_data.get("st_rank", 3.5)

    if c_num == 1:
        if w1 >= 68.0 and st <= 0.15:
            return "鉄壁イン速攻逃げ型"
        elif r3 >= 82.0:
            return "イン高信頼押し切り型"
        elif w1 < 48.0:
            return "イン波乱含み(被差し・被まくり警戒)"
        return "イン標準先マイ型"
    elif c_num == 2:
        if w1 >= 18.0 and r2 >= 45.0:
            return "2C鋭角差し・直まくり逆転巧者"
        elif p2 >= 26.0 or r3 >= 68.0:
            return "2C堅実差し追従・連下軸型"
        elif r3 < 40.0:
            return "2C苦戦傾向(差し遅れ注意)"
        return "2C標準差し型"
    elif c_num == 3:
        if w1 >= 16.0 and st_rk <= 3.2:
            return "3Cスリット強襲・ツケマイまくり型"
        elif r2 >= 35.0 or r3 >= 60.0:
            return "3C自在まくり差し・外マイ連対型"
        elif r3 < 40.0:
            return "3C谷間傾向(握りマイ空振り注意)"
        return "3C標準センター攻め型"
    elif c_num == 4:
        if w1 >= 18.0 or (w1 >= 14.0 and st_rk <= 3.1):
            return "4カド一撃まくり・まくり差し強襲型"
        elif r3 >= 55.0:
            return "4C二番差し・道中捌き連対巧者"
        elif r3 < 35.0:
            return "4C展開待ち傾向"
        return "4C標準カド戦型"
    elif c_num == 5:
        if w1 >= 10.0 or r2 >= 25.0:
            return "5Cまくり差し一撃・外強襲巧者"
        elif r3 >= 42.0:
            return "5C連動差し・3連対巧者"
        return "5C展開連動待ち型"
    else:
        if r3 >= 45.0 or r2 >= 20.0:
            return "6C最内差し・道中鬼捌き3連対巧者"
        elif p3 >= 20.0:
            return "6Cヒモ穴3着浮上型"
        return "6C大外展開待ち型"


def load_official_course_cache() -> Dict[str, Any]:
    if os.path.exists(OFFICIAL_COURSE_CACHE_PATH):
        try:
            with open(OFFICIAL_COURSE_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def fetch_and_cache_official_course_stats(tobans: list) -> Dict[str, Any]:
    """
    boatrace.jp公式のコース別成績(course?toban=XXXX)＋今期成績(season?toban=XXXX)から
    1〜6コース別の進入率・1着率・2着率・3着率・2連対率・3連対率・平均ST・ST順・自動戦法分類と
    今期勝率・能力指数・優出/優勝回数を取得して永続キャッシュする。
    """
    import requests
    from bs4 import BeautifulSoup
    from concurrent.futures import ThreadPoolExecutor

    cache = load_official_course_cache()
    missing = [
        str(t).strip() for t in set(tobans)
        if str(t).strip().isdigit() and len(str(t).strip()) == 4
        and (str(t).strip() not in cache or "season_summary" not in cache.get(str(t).strip(), {}))
    ]
    if not missing:
        return cache

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    def _fetch_one(t_id: str):
        url_c = f"https://www.boatrace.jp/owpc/pc/data/racersearch/course?toban={t_id}"
        url_s = f"https://www.boatrace.jp/owpc/pc/data/racersearch/season?toban={t_id}"
        try:
            r = requests.get(url_c, headers=headers, timeout=10)
            r.encoding = r.apparent_encoding or "utf-8"
            if r.status_code != 200:
                return t_id, None
            soup = BeautifulSoup(r.text, "html.parser")
            tbls = soup.find_all("table")
            if len(tbls) < 4:
                return t_id, None
            courses = {}
            rows_t0 = tbls[0].select("tbody tr")
            rows_t1 = tbls[1].select("tbody tr")
            rows_t2 = tbls[2].select("tbody tr")
            rows_t3 = tbls[3].select("tbody tr")
            for c_idx in range(min(6, len(rows_t1))):
                c_num = str(c_idx + 1)
                entry_rate = 16.7
                if c_idx < len(rows_t0):
                    tds0 = [td.get_text(strip=True).replace("%", "") for td in rows_t0[c_idx].select("th, td")]
                    if len(tds0) > 1 and re.match(r"^\d+(\.\d+)?$", tds0[1]):
                        entry_rate = float(tds0[1])
                tr1 = rows_t1[c_idx]
                tds1 = [td.get_text(strip=True) for td in tr1.select("th, td")]
                rentai3_str = tds1[1].replace("%", "") if len(tds1) > 1 else "0.0"
                rentai3_val = float(rentai3_str) if re.match(r"^\d+(\.\d+)?$", rentai3_str) else 0.0
                bars = []
                for sp in tr1.select("span.is-progress"):
                    st_attr = sp.get("style", "")
                    m_w = re.search(r"width:\s*([\d\.]+)%", st_attr)
                    bars.append(float(m_w.group(1)) if m_w else 0.0)
                r1 = bars[0] if len(bars) > 0 else 0.0
                r2 = bars[1] if len(bars) > 1 else 0.0
                r3 = bars[2] if len(bars) > 2 else 0.0
                rentai2_val = round(r1 + r2, 1)
                avg_st = 0.17
                if c_idx < len(rows_t2):
                    tds2 = [td.get_text(strip=True) for td in rows_t2[c_idx].select("th, td")]
                    if len(tds2) > 1 and re.match(r"^\d+\.\d+$", tds2[1]):
                        avg_st = float(tds2[1])
                st_rank = 3.5
                if c_idx < len(rows_t3):
                    tds3 = [td.get_text(strip=True) for td in rows_t3[c_idx].select("th, td")]
                    if len(tds3) > 1 and re.match(r"^\d+\.\d+$", tds3[1]):
                        st_rank = float(tds3[1])
                c_obj = {
                    "entry_rate": round(entry_rate, 1),
                    "win_rate": round(r1, 1),
                    "place2_rate": round(r2, 1),
                    "place3_rate": round(r3, 1),
                    "rentai2": rentai2_val,
                    "rentai3": round(rentai3_val, 1),
                    "avg_st": avg_st,
                    "st_rank": st_rank
                }
                c_obj["tactical_type"] = classify_course_tactics(c_idx + 1, c_obj)
                courses[c_num] = c_obj

            # 今期通算成績 (season?toban=XXXX) も取得
            season_summary = {}
            try:
                rs = requests.get(url_s, headers=headers, timeout=8)
                rs.encoding = rs.apparent_encoding or "utf-8"
                if rs.status_code == 200:
                    s_soup = BeautifulSoup(rs.text, "html.parser")
                    s_tbls = s_soup.find_all("table")
                    if s_tbls:
                        kv = {}
                        for tr in s_tbls[0].select("tr"):
                            cells = [c.get_text(strip=True) for c in tr.select("th, td")]
                            for i in range(0, len(cells) - 1, 2):
                                kv[cells[i]] = cells[i + 1]
                        season_summary = {
                            "season_win_rate": kv.get("勝率", ""),
                            "season_rentai2": kv.get("2連対率", ""),
                            "season_rentai3": kv.get("3連対率", ""),
                            "season_runs": kv.get("出走回数", ""),
                            "finals_count": kv.get("優出回数", ""),
                            "champion_count": kv.get("優勝回数", ""),
                            "ability_index": kv.get("能力指数", "")
                        }
            except Exception:
                pass
            courses["season_summary"] = season_summary
            return t_id, courses
        except Exception:
            return t_id, None

    with ThreadPoolExecutor(max_workers=8) as ex:
        for t_id, c_data in ex.map(_fetch_one, missing):
            if c_data:
                cache[t_id] = c_data

    try:
        with open(OFFICIAL_COURSE_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return cache


def build_racer_master_intelligence(learned_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    全情報源（①公式コース別・期別実測データ ②宮島・芦屋・下関・江戸川等の女子戦独自実走ログ
    ③展示タイム対実着順ギャップ ④イン残し率・穴演出実績 ⑤スタ展F対本番STアジャスト傾向 ⑥88名戦術プロファイル辞書）
    を統合し、公式データを凌駕する『全選手マスターインテリジェンスDB (data/racer_master_intelligence.json)』を生成する。
    """
    if learned_data is None:
        if os.path.exists(LEARNED_STATS_PATH):
            learned_data = json.load(open(LEARNED_STATS_PATH, "r", encoding="utf-8"))
        else:
            learned_data = {"player_stats": {}}

    st_f_bias_path = os.path.join(DATA_DIR, "racer_st_f_bias.json")
    st_f_bias = json.load(open(st_f_bias_path, "r", encoding="utf-8")) if os.path.exists(st_f_bias_path) else {}

    profiles_dict = {}
    try:
        from ladies_racer_profiles import ALL_RACER_PROFILES
        for k, v in ALL_RACER_PROFILES.items():
            profiles_dict[clean_name(v.get("name", ""))] = {"toban": str(k), **v}
    except Exception:
        pass

    # 全出走データから (toban, name) マッピングを収集
    toban_to_name = {}
    name_to_toban = {}
    for pname, pinfo in profiles_dict.items():
        tb = pinfo.get("toban", "")
        if tb:
            toban_to_name[tb] = pname
            name_to_toban[pname] = tb

    for fp in sorted(glob.glob(os.path.join(DATA_DIR, "*_data.json"))):
        try:
            d = json.load(open(fp, "r", encoding="utf-8"))
            for rk, rv in d.items():
                if not isinstance(rv, dict):
                    continue
                for b in rv.get("boats", []):
                    tb = str(b.get("toban") or b.get("id") or "").strip()
                    nm = clean_name(b.get("name", ""))
                    if tb and nm and not nm.startswith("選手"):
                        toban_to_name[tb] = nm
                        name_to_toban[nm] = tb
        except Exception:
            pass

    for fp in sorted(glob.glob(os.path.join(DATA_DIR, "*_official_full.json"))):
        try:
            d = json.load(open(fp, "r", encoding="utf-8"))
            for rk, rv in d.items():
                for b in rv.get("racers", []):
                    tb = str(b.get("toban") or "").strip()
                    nm = clean_name(b.get("name", ""))
                    if tb and nm and len(nm) > 2:
                        toban_to_name[tb] = nm
                        name_to_toban[nm] = tb
        except Exception:
            pass

    course_cache = fetch_and_cache_official_course_stats(list(toban_to_name.keys()))

    master_db = {}
    all_names = set(list(name_to_toban.keys()) + list(learned_data.get("player_stats", {}).keys()))

    for pname in sorted(all_names):
        tb = name_to_toban.get(pname, "")
        ps = learned_data.get("player_stats", {}).get(pname, {})
        if not tb and ps.get("toban"):
            tb = str(ps["toban"])
        off_c = course_cache.get(tb, {}) if tb else {}
        prof = profiles_dict.get(pname, {})
        st_bias = st_f_bias.get(pname, {})

        # 得意コース・注意コースの自動抽出とベイズ統合コース評価
        best_courses = []
        weak_courses = []
        integrated_courses = {}
        std_r3_map = {1: 78.0, 2: 52.0, 3: 48.0, 4: 44.0, 5: 30.0, 6: 20.0}

        for c_i in range(1, 7):
            cs = str(c_i)
            c_off = off_c.get(cs, {})
            c_act = ps.get("course_runs", {}).get(cs, {"runs": 0, "1st": 0, "2nd": 0, "3rd": 0})
            act_runs = c_act.get("runs", 0)
            off_r2 = c_off.get("rentai2", 0.0)
            off_r3 = c_off.get("rentai3", 0.0)
            if act_runs > 0:
                act_r2 = ((c_act["1st"] + c_act["2nd"]) / act_runs) * 100.0
                act_r3 = ((c_act["1st"] + c_act["2nd"] + c_act["3rd"]) / act_runs) * 100.0
                # ベイズ統合: 実走データが増えるほど女子戦実走データの比重を高める（事前重み N_prior=8走相当）
                w_act = act_runs / (act_runs + 8.0)
                eff_r2 = round((off_r2 * (1.0 - w_act)) + (act_r2 * w_act), 1) if c_off else round(act_r2, 1)
                eff_r3 = round((off_r3 * (1.0 - w_act)) + (act_r3 * w_act), 1) if c_off else round(act_r3, 1)
            else:
                eff_r2 = off_r2
                eff_r3 = off_r3

            t_type = c_off.get("tactical_type", "")
            integrated_courses[cs] = {
                "official_win_rate": c_off.get("win_rate", 0.0),
                "official_rentai2": off_r2,
                "official_rentai3": off_r3,
                "official_avg_st": c_off.get("avg_st", 0.17),
                "official_st_rank": c_off.get("st_rank", 3.5),
                "ladies_actual_runs": act_runs,
                "ladies_actual_1st": c_act.get("1st", 0),
                "ladies_actual_rentai3_count": c_act.get("1st", 0) + c_act.get("2nd", 0) + c_act.get("3rd", 0),
                "effective_rentai2": eff_r2,
                "effective_rentai3": eff_r3,
                "tactical_type": t_type
            }
            if eff_r3 >= std_r3_map[c_i] + 10.0:
                best_courses.append(f"{c_i}コース(実効3連対{eff_r3:.0f}%・{t_type})")
            elif c_off and eff_r3 <= std_r3_map[c_i] - 10.0:
                weak_courses.append(f"{c_i}コース(実効3連対{eff_r3:.0f}%)")

        # 独自実戦指標のサマリー
        runs = ps.get("runs", 0)
        in_runs = ps.get("in_runs", 0)
        in_1st = ps.get("in_1st", 0)
        in_survive = ps.get("in_survive", 0)
        in_lost = max(0, in_runs - in_1st)
        in_survive_rate = round((in_survive / in_lost) * 100.0, 1) if in_lost > 0 else None

        master_db[pname] = {
            "toban": tb,
            "name": pname,
            "style_label": prof.get("style_label", "実戦データ自動解析レーサー"),
            "scouting_desc": prof.get("desc", ""),
            "season_summary": off_c.get("season_summary", {}),
            "best_courses": best_courses,
            "weak_courses": weak_courses,
            "proprietary_metrics": {
                "accumulated_ladies_runs": runs,
                "accumulated_win_rate": round((ps.get("1st", 0) / runs) * 100.0, 1) if runs > 0 else 0.0,
                "accumulated_rentai2": round(((ps.get("1st", 0) + ps.get("2nd", 0)) / runs) * 100.0, 1) if runs > 0 else 0.0,
                "accumulated_rentai3": round(((ps.get("1st", 0) + ps.get("2nd", 0) + ps.get("3rd", 0)) / runs) * 100.0, 1) if runs > 0 else 0.0,
                "ex_outperform_count": ps.get("ex_outperform", 0),
                "ex_betrayal_count": ps.get("ex_betrayal", 0),
                "in_survive_rate_when_beaten": in_survive_rate,
                "upset_maker_count": ps.get("upset_1st2nd", 0),
                "st_f_tendency": st_bias.get("tendency", "標準アジャスト型"),
                "st_f_avg_adjust": st_bias.get("avg_f_adjust", 0.0)
            },
            "courses": integrated_courses
        }

    try:
        with open(RACER_MASTER_INTELLIGENCE_PATH, "w", encoding="utf-8") as f:
            json.dump(master_db, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return master_db


def compute_learned_adjustment(boat: Dict[str, Any], stadium: str, learned_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    蓄積学習データ（learned_data）＋公式コース別・期別実績＋独自実戦指標（ベイズ統合コース評価・展示対実着順ギャップ・イン残し率・穴演出度）から、
    当該艇のスコア補正値と学習根拠コメントを返す。
    """
    if not learned_data:
        return {"bonus": 0.0, "course_base": None, "note": ""}

    num = int(boat.get("num", 1))
    pname = clean_name(boat.get("name", ""))
    toban = str(boat.get("toban") or boat.get("id") or "").strip()
    mno = str(boat.get("motor_no") or "").strip()

    st_info = learned_data.get("stadium_stats", {}).get(stadium, {})
    course_base = st_info.get("learned_course_scores", {}).get(str(num))

    bonus = 0.0
    notes = []

    ps = learned_data.get("player_stats", {}).get(pname)

    # 0. 公式コース別成績 × 当システム女子戦コース別実走のベイズ統合評価
    course_cache = load_official_course_cache()
    if toban in course_cache and str(num) in course_cache[toban]:
        cs = course_cache[toban][str(num)]
        c_win = cs.get("win_rate", 0.0)
        c_r2 = cs.get("rentai2", 0.0)
        c_r3 = cs.get("rentai3", 0.0)
        c_st = cs.get("avg_st", 0.17)
        t_type = cs.get("tactical_type", "")

        # 当システムの該当コース実走データがあればベイズ統合（公式データを上書き強化）
        c_act = ps.get("course_runs", {}).get(str(num), {}) if ps else {}
        act_c_runs = c_act.get("runs", 0)
        if act_c_runs >= 1:
            act_c_r2 = ((c_act.get("1st", 0) + c_act.get("2nd", 0)) / act_c_runs) * 100.0
            act_c_r3 = ((c_act.get("1st", 0) + c_act.get("2nd", 0) + c_act.get("3rd", 0)) / act_c_runs) * 100.0
            w_act = act_c_runs / (act_c_runs + 8.0)
            eff_r2 = (c_r2 * (1.0 - w_act)) + (act_c_r2 * w_act)
            eff_r3 = (c_r3 * (1.0 - w_act)) + (act_c_r3 * w_act)
        else:
            eff_r2 = c_r2
            eff_r3 = c_r3

        std_r2 = {1: 68.0, 2: 34.0, 3: 30.0, 4: 26.0, 5: 16.0, 6: 9.0}.get(num, 25.0)
        std_r3 = {1: 78.0, 2: 52.0, 3: 48.0, 4: 44.0, 5: 30.0, 6: 20.0}.get(num, 40.0)
        diff_r2 = eff_r2 - std_r2
        diff_r3 = eff_r3 - std_r3
        c_adj = (diff_r2 * 0.14) + (diff_r3 * 0.08)
        if c_st <= 0.14:
            c_adj += 2.5
        elif c_st >= 0.20:
            c_adj -= 2.5
        c_adj = max(-9.0, min(11.0, c_adj))
        bonus += c_adj
        if abs(c_adj) >= 2.0 or t_type:
            short_t = t_type.replace("型", "").replace("巧者", "") if t_type else f"{num}C"
            notes.append(f"{short_t}:実効3連対{eff_r3:.0f}%(1着{c_win:.0f}%/ST.{int(c_st*100):02d})")

    # 1. 選手の蓄積実走実績ボーナス（独自実戦指標）
    if ps and ps["runs"] >= 2:
        runs = ps["runs"]
        rentai2_actual = (ps["1st"] + ps["2nd"]) / runs
        rentai3_actual = (ps["1st"] + ps["2nd"] + ps["3rd"]) / runs

        if rentai2_actual >= 0.45:
            b_val = min(14.0, (rentai2_actual - 0.30) * 35.0)
            bonus += b_val
            notes.append(f"蓄積実走2連対{int(rentai2_actual*100)}%({ps['1st']+ps['2nd']}/{runs}走)")
        elif rentai3_actual >= 0.60:
            b_val = min(9.0, (rentai3_actual - 0.45) * 25.0)
            bonus += b_val
            notes.append(f"蓄積実走3連対{int(rentai3_actual*100)}%({ps['1st']+ps['2nd']+ps['3rd']}/{runs}走)")
        elif rentai3_actual <= 0.15 and runs >= 3:
            bonus -= 7.0
            notes.append(f"近走着外苦戦({runs}走)")

        # イン実績＆イン残し粘り
        if num == 1 and ps["in_runs"] >= 2:
            if ps["in_1st"] == ps["in_runs"]:
                bonus += 6.0
                notes.append(f"蓄積イン全勝({ps['in_1st']}/{ps['in_runs']})")
            elif ps["in_1st"] == 0:
                bonus -= 8.0
                notes.append(f"蓄積イン未勝利(0/{ps['in_runs']})")

        # センター強襲実績
        if num in [3, 4] and ps["center_runs"] >= 2 and ps["center_1st"] >= 1:
            bonus += 5.5
            notes.append("センター1着実績有")

        # 展示以上の実戦足（道中捌き） vs 展示倒れ
        if ps.get("ex_outperform", 0) >= 1:
            bonus += min(6.0, ps["ex_outperform"] * 2.5)
            notes.append(f"道中実戦捌き強(+{ps['ex_outperform']}回)")
        if ps.get("ex_betrayal", 0) >= 2 and ps.get("ex_outperform", 0) == 0:
            bonus -= 3.5
            notes.append("展示過信禁物")

        # 穴演出（高配当貢献）
        if num >= 3 and ps.get("upset_1st2nd", 0) >= 1:
            bonus += min(4.0, ps["upset_1st2nd"] * 2.0)
            notes.append(f"高配当演出実績({ps['upset_1st2nd']}回)")

    # 2. モーターの節間実走実績ボーナス
    if mno and mno.isdigit():
        mkey = f"{stadium}_{mno}"
        ms = learned_data.get("motor_stats", {}).get(mkey)
        if ms and ms["runs"] >= 3:
            m_rentai2 = (ms["1st"] + ms["2nd"]) / ms["runs"]
            m_rentai3 = (ms["1st"] + ms["2nd"] + ms["3rd"]) / ms["runs"]
            if m_rentai2 >= 0.50:
                bonus += 6.0
                notes.append(f"節間好調機(実走2連対{int(m_rentai2*100)}%)")
            elif m_rentai3 >= 0.65:
                bonus += 3.5
                notes.append(f"節間安定機(実走3連対{int(m_rentai3*100)}%)")
            elif (ms["1st"] + ms["2nd"] + ms["3rd"]) == 0 and ms["runs"] >= 4:
                bonus -= 5.0

    return {
        "bonus": round(bonus, 2),
        "course_base": course_base,
        "note": " / ".join(notes)
    }


if __name__ == "__main__":
    stats = build_and_save_learned_stats()
    print(f"Learned from {stats['total_learned_races']} completed races.")
    for st, sdata in stats["stadium_stats"].items():
        print(f"Stadium [{st}]: {sdata['total_races']} races | In-Escape: {sdata['in_escape_rate']}% | Center-Win: {sdata['center_win_rate']}% | CourseScores: {sdata['learned_course_scores']}")
    print(f"Total tracked players: {len(stats['player_stats'])}, motors: {len(stats['motor_stats'])}")



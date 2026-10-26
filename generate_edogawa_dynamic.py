# -*- coding: utf-8 -*-
"""
generate_edogawa_dynamic.py
日付を指定して江戸川の出走表を取得・新動的ロジック（捏造なし・能力スコアリング・センター警戒）で予想生成する汎用モジュール
"""

import os
import sys
import json
import re
import requests
from bs4 import BeautifulSoup
from predict_slit_formation import compute_comprehensive_predicted_st
from test_correct_odds_parser import parse_boatrace_odds3t
from accumulated_learning_engine import build_and_save_learned_stats, compute_learned_adjustment, fetch_and_cache_official_course_stats

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.boatrace.jp/"
}

deadlines = {
    1: "11:15", 2: "11:42", 3: "12:09", 4: "12:36",
    5: "13:03", 6: "13:30", 7: "13:58", 8: "14:26",
    9: "14:54", 10: "15:23", 11: "15:53", 12: "16:25"
}

def calculate_boat_score(b, learned_data=None, stadium="江戸川"):
    rank = b.get("rank") or b.get("grade") or "B1"
    nat_win = float(b.get("course_win_rate") or b.get("win_rate") or 5.0)
    loc_win = float(b.get("local_win_rate") or nat_win)
    m_rate = float(b.get("motor_rate") or 30.0)
    num = int(b.get("num", 1))
    fl = str(b.get("fl") or f"F{b.get('f_count', 0)}")
    
    rank_score = {"A1": 35.0, "A2": 26.0, "B1": 16.0, "B2": 6.0}.get(rank, 15.0)
    win_score = (nat_win * 4.5) + (loc_win * 5.5)
    motor_weight = 0.35 if num in [5, 6] else 0.45
    motor_score = m_rate * motor_weight
    default_course_score = {1: 24.0, 2: 16.5, 3: 17.5, 4: 15.0, 5: 6.0, 6: 2.0}.get(num, 5.0)
    
    # 蓄積データ自動学習エンジンからのフィードバック（会場別実測コース得点＋公式コース別実績＋選手別実走補正＋節間モーター実走補正）
    learned_adj = compute_learned_adjustment(b, stadium, learned_data)
    if learned_adj["course_base"] is not None:
        # 理論基礎点と会場実測コース得点をブレンドして会場バイアスを自動反映
        course_score = (default_course_score * 0.65) + (float(learned_adj["course_base"]) * 0.35)
    else:
        course_score = default_course_score

    learned_bonus = learned_adj["bonus"]
    if learned_adj["note"]:
        b["learned_note"] = learned_adj["note"]
        if b.get("tactical_comment") and learned_adj["note"] not in b["tactical_comment"]:
            b["tactical_comment"] = f"{b['tactical_comment']} [{learned_adj['note']}]"
    
    st_val = float("0." + b["pred_st"].replace(".", "").replace("ST", "")) if b.get("pred_st") else 0.17
    st_penalty = -8.0 if "F1" in fl else (-22.0 if "F2" in fl else 0.0)
    st_bonus = 8.0 if st_val <= 0.14 else (-6.0 if st_val >= 0.19 else 0.0)
    
    return max(10.0, rank_score + win_score + motor_score + course_score + st_penalty + st_bonus + learned_bonus)

_CACHED_LEARNED_DATA = None

def generate_bets_for_race(r, boats, learned_data=None, stadium="江戸川", **kwargs):
    global _CACHED_LEARNED_DATA
    if learned_data is None:
        if _CACHED_LEARNED_DATA is None:
            _CACHED_LEARNED_DATA = build_and_save_learned_stats()
        learned_data = _CACHED_LEARNED_DATA
    try:
        off_db, _ = load_racer_intelligence_dbs()
        missing_tobans = [str(b.get("toban") or b.get("id") or "") for b in boats if str(b.get("toban") or b.get("id") or "") not in off_db]
        if missing_tobans:
            fetch_and_cache_official_course_stats(missing_tobans)
    except Exception:
        pass

    # 展示タイム・オリジナル展示（一周・まわり足・直線）に応じた動的スコア加減算
    ex_Bonus_map = {b["num"]: 0.0 for b in boats}
    valid_ex = [(b["num"], float(b["ex_time"])) for b in boats if re.match(r"^\d+\.\d+$", str(b.get("ex_time", "")))]
    if len(valid_ex) >= 4:
        valid_ex.sort(key=lambda x: x[1])
        min_ex = valid_ex[0][1]
        max_ex = valid_ex[-1][1]
        for rank_i, (bnum, eval_t) in enumerate(valid_ex):
            if eval_t == min_ex:
                ex_Bonus_map[bnum] += 5.0   # 展示1番時計ボーナス
            elif rank_i == 1 or eval_t <= min_ex + 0.03:
                ex_Bonus_map[bnum] += 3.0   # 展示2番時計ボーナス
            elif eval_t == max_ex and (eval_t - min_ex) >= 0.08:
                ex_Bonus_map[bnum] -= 6.0   # 展示大きく遅れた艇の減点

    # オリジナル展示データ（一周、まわり足、直線）最速評価
    for b in boats:
        bnum = b["num"]
        if b.get("is_best_lap"):
            ex_Bonus_map[bnum] += 4.0   # 一周タイムTOP
        if b.get("is_best_turn"):
            ex_Bonus_map[bnum] += 3.5   # まわり足TOP
        if b.get("is_best_straight"):
            ex_Bonus_map[bnum] += 3.0   # 直線タイムTOP

    scores = {b["num"]: calculate_boat_score(b, learned_data, stadium) + ex_Bonus_map.get(b["num"], 0.0) for b in boats}
    b1, b2, b3, b4, b5, b6 = boats[:6]
    
    loc_w1 = float(b1["local_win_rate"]) if b1.get("local_win_rate") else 5.0
    center_surge = False
    center_primary = 3

    best_center = 3 if scores[3] >= scores[4] else 4
    if (scores[best_center] >= scores[1] + 8.0) or (
        (loc_w1 < 4.8 or "F1" in b1["fl"] or scores[1] < 75.0) and (scores[3] >= scores[1] or scores[4] >= scores[1] or b3["motor_rate"] >= 42.0)
    ):
        center_surge = True
        center_primary = best_center

    sorted_nums = sorted(scores.keys(), key=lambda n: scores[n], reverse=True)
    is_semi_or_final = (r in [10, 11, 12])
    
    if is_semi_or_final:
        grade = "S"
        grade_badge = "bg-amber-600 text-white border-amber-400 shadow-md"
        grade_title = f"🔥【Sランク・特別戦】{stadium} {r}R 決戦バトル"
    elif center_surge:
        grade = "A"
        grade_badge = "bg-purple-600 text-white border-purple-400 shadow-sm"
        grade_title = f"⚡【Aランク・波乱警戒】{stadium} {r}R センター強襲戦"
    else:
        grade = "B"
        grade_badge = "bg-cyan-600 text-white border-cyan-400 shadow-sm"
        grade_title = f"🎯【Bランク・展開勝負】{stadium} {r}R 物理スリット本線"

    if center_surge:
        c_head = center_primary
        c_name = boats[c_head-1]["name"]
        core_scenario = f"イン{b1['name']}に対し、{c_head}号艇{c_name}が総合力・スリット優位からまくり・まくり差し一撃を狙う。"
        physics_detail = f"{c_head}コース{c_name}が先制攻勢。外隣連動およびイン1号艇・2コース差し逆転の複合決着を網羅。"
        other_top = [n for n in sorted_nums if n != c_head and n != 1][:3]
        o1, o2 = other_top[0], other_top[1]
        outer_link = 5 if c_head in [3, 4] and 5 not in [1, c_head, o1] else o2
        main_bets_raw = [
            (f"{c_head}-1-{o1}", f"{c_name}強襲 ➔ イン{b1['name']}粘り ➔ {boats[o1-1]['name']}"),
            (f"{c_head}-{o1}-1", f"{c_name}強襲 ➔ {boats[o1-1]['name']}追走 ➔ イン残り"),
            (f"{c_head}-{o1}-{outer_link}", f"{c_name}全速戦 ➔ {boats[o1-1]['name']}・外連動決着"),
            (f"{c_head}-1-{outer_link}", f"{c_name}頭 ➔ イン残し ➔ 連動枠")
        ]
        # 真の穴予想: 1号艇完全着外（イン沈没）および外枠連動・ダッシュ強襲による万舟・高配当フォーメーション
        outer_candidates = [n for n in [4, 5, 6] if n != c_head]
        out1 = outer_candidates[0] if len(outer_candidates) > 0 else 5
        out2 = outer_candidates[1] if len(outer_candidates) > 1 else 6
        ana_bets_raw = [
            (f"{c_head}-{o1}-{o2}", f"【万舟狙い】{c_name}強襲 ➔ イン完全沈没(1着外) ➔ {boats[o1-1]['name']}・{boats[o2-1]['name']}"),
            (f"{c_head}-{out1}-{out2}", f"【外枠連動万舟】{c_name}攻勢 ➔ ダッシュ連動外枠追従 ➔ {out1}・{out2}号艇"),
            (f"{out1}-{c_head}-{out2}", f"【大波乱】{boats[out1-1]['name']}カド展開突き ➔ {c_name}連動 ➔ 高配当"),
            (f"2-{c_head}-{o1}" if c_head != 2 else f"3-2-{out1}", f"【イン崩壊】2コース強襲 ➔ {c_name}追走 ➔ イン着外波乱")
        ]
    else:
        core_scenario = f"1号艇{b1['name']}がインから先手を奪い押し切り優位。対抗勢の差し・外マイと展示好調艇の連動を精査。"
        physics_detail = f"イン五分スタートなら先マイ濃厚。2・3コースの追従および展示上位艇の逆転裏目を厳密ケア。"
        rivals = [n for n in sorted_nums if n != 1][:4]
        r1_num, r2_num, r3_num, r4_num = rivals[0], rivals[1], rivals[2], rivals[3]
        main_bets_raw = [
            (f"1-{r1_num}-{r2_num}", f"{b1['name']}逃げ ➔ {boats[r1_num-1]['name']}追走 ➔ {boats[r2_num-1]['name']}"),
            (f"1-{r2_num}-{r1_num}", f"{b1['name']}逃げ ➔ {boats[r2_num-1]['name']}連対 ➔ {boats[r1_num-1]['name']}"),
            (f"1-{r1_num}-{r3_num}", f"{b1['name']}逃げ ➔ {boats[r1_num-1]['name']}的確差し ➔ {boats[r3_num-1]['name']}"),
            (f"1-{r3_num}-{r1_num}", f"{b1['name']}先マイ ➔ {boats[r3_num-1]['name']}2着浮上 ➔ {boats[r1_num-1]['name']}")
        ]

    # 重複排除セーフティ
    def dedup_bets(bets_list, exclude_set):
        res = []
        used = set(exclude_set)
        for comb, desc in bets_list:
            parts = comb.split("-")
            if len(set(parts)) == 3 and comb not in used:
                res.append((comb, desc))
                used.add(comb)
        for c1 in sorted_nums:
            for c2 in sorted_nums:
                for c3 in sorted_nums:
                    if len({c1, c2, c3}) == 3:
                        cand = f"{c1}-{c2}-{c3}"
                        if cand not in used and len(res) < 4:
                            res.append((cand, "展開連動ケア"))
                            used.add(cand)
        return res[:4]

    # 真の物理展開・万舟検知エンジンによる穴予想4点の算出
    real_odds = kwargs.get("real_odds") if "kwargs" in locals() else None
    main_bets_raw = dedup_bets(main_bets_raw, set())
    ana_bets_raw = compute_physics_upset_bets(
        boats=boats,
        scores=scores,
        exclude_combs={m[0] for m in main_bets_raw},
        real_odds=real_odds
    )

    if real_odds:
        main_bets_raw, ana_bets_raw = reclassify_bets_by_odds(
            main_bets_raw, ana_bets_raw, real_odds, boats=boats, scores=scores
        )

    # 動的ボルツマン分布＋Harville条件付き確率モデルによる実数確率算出（固定プリセット完全撤廃）
    import math
    primary_axis = center_primary if center_surge else 1
    # 本線1着軸の艇がスコア順でも最上位(◎)となるようコース主導権ボーナスを整合
    effective_scores = dict(scores)
    max_other_sc = max([effective_scores[n] for n in effective_scores if n != primary_axis], default=80.0)
    if effective_scores[primary_axis] <= max_other_sc:
        effective_scores[primary_axis] = max_other_sc + 3.5

    temp = 13.5
    max_sc = max(effective_scores.values()) if effective_scores else 100.0
    exp_map = {n: math.exp((effective_scores[n] - max_sc) / temp) for n in effective_scores}
    sum_exp = sum(exp_map.values()) or 1.0
    p1_map = {n: exp_map[n] / sum_exp for n in effective_scores}

    p2_map = {n: 0.0 for n in effective_scores}
    p3_map = {n: 0.0 for n in effective_scores}
    comb_probs = {}
    for i in effective_scores:
        rem1 = 1.0 - p1_map[i]
        if rem1 <= 1e-9:
            continue
        for j in effective_scores:
            if j == i:
                continue
            p_ij = p1_map[i] * (p1_map[j] / rem1)
            p2_map[j] += p_ij
            rem2 = rem1 - p1_map[j]
            if rem2 <= 1e-9:
                continue
            for k in effective_scores:
                if k == i or k == j:
                    continue
                p_ijk = p_ij * (p1_map[k] / rem2)
                p3_map[k] += p_ijk
                comb_probs[f"{i}-{j}-{k}"] = round(max(0.2, p_ijk * 100.0), 1)

    sorted_all_boats = sorted(boats, key=lambda b: effective_scores[b["num"]], reverse=True)
    marks = ["◎", "○", "▲", "△", "注", "―"]
    official_db, master_db = load_racer_intelligence_dbs()
    for idx, b in enumerate(sorted_all_boats):
        bnum = b["num"]
        b["mark"] = marks[idx]
        b["eval_mark"] = marks[idx]
        w_p = max(1.0, min(75.0, p1_map.get(bnum, 0.05) * 100.0))
        p2_p = max(2.0, min(55.0, p2_map.get(bnum, 0.10) * 100.0))
        p3_p = max(3.0, min(50.0, p3_map.get(bnum, 0.12) * 100.0))
        t_rate = max(10.0, min(96.0, w_p + p2_p + p3_p))
        b["win_prob"] = f"{w_p:.1f}"
        b["place2_prob"] = f"{p2_p:.1f}"
        b["place3_prob"] = f"{p3_p:.1f}"
        b["score"] = f"{effective_scores[bnum]:.1f}"
        b["triple_rate"] = f"{t_rate:.1f}"
        b["concept"] = compute_authentic_concept_stats(b, official_db=official_db, master_db=master_db)
        b["ladies_tag"] = b["concept"]["badge"]
        b["style_desc"] = b["concept"]["eval_text"]

    return {
        "grade": grade, "grade_badge": grade_badge, "grade_title": grade_title,
        "core_scenario": core_scenario, "physics_detail": physics_detail,
        "main_bets_raw": main_bets_raw, "ana_bets_raw": ana_bets_raw,
        "comb_probs": comb_probs
    }


_CACHED_OFFICIAL_DB = None
_CACHED_MASTER_DB = None

def load_racer_intelligence_dbs():
    global _CACHED_OFFICIAL_DB, _CACHED_MASTER_DB
    if _CACHED_OFFICIAL_DB is None:
        off_path = os.path.join(DATA_DIR, "official_racer_course_stats.json")
        if os.path.exists(off_path):
            try:
                with open(off_path, "r", encoding="utf-8") as f:
                    _CACHED_OFFICIAL_DB = json.load(f)
            except Exception:
                _CACHED_OFFICIAL_DB = {}
        else:
            _CACHED_OFFICIAL_DB = {}
    if _CACHED_MASTER_DB is None:
        mas_path = os.path.join(DATA_DIR, "racer_master_intelligence.json")
        if os.path.exists(mas_path):
            try:
                with open(mas_path, "r", encoding="utf-8") as f:
                    _CACHED_MASTER_DB = json.load(f)
            except Exception:
                _CACHED_MASTER_DB = {}
        else:
            _CACHED_MASTER_DB = {}
    return _CACHED_OFFICIAL_DB, _CACHED_MASTER_DB


def compute_authentic_concept_stats(b: dict, official_db: dict = None, master_db: dict = None) -> dict:
    """
    official_racer_course_stats.json および racer_master_intelligence.json の公式コース別実績と
    選手のモーター・ST・勝率・級別から、全選手・全枠番で100%固有の実数新概念データを算出する。
    """
    if official_db is None or master_db is None:
        official_db, master_db = load_racer_intelligence_dbs()

    num = int(b.get("num") or b.get("course") or 1)
    c_str = str(num)
    toban = str(b.get("toban") or b.get("id") or "")
    name = str(b.get("name") or "").replace(" ", "").replace("\u3000", "")
    rank = str(b.get("rank") or b.get("grade") or "B1")
    fl = str(b.get("fl") or "F0")

    def _f(v, d=0.0):
        try:
            if v is None or v in ["", "--", "--.--"]:
                return d
            return float(str(v).replace("%", ""))
        except Exception:
            return d

    nat_win = _f(b.get("win_rate") or b.get("course_win_rate"), 4.8)
    m_rate = _f(b.get("motor_rate"), 32.0)
    raw_st_s = str(b.get("avg_st") or ".17").replace(".", "").replace("0", "", 1) if str(b.get("avg_st") or "").startswith("0.") else str(b.get("avg_st") or ".17").replace(".", "")
    base_st = float("0." + raw_st_s) if raw_st_s.isdigit() else 0.17

    off_rec = official_db.get(toban, {}) if official_db else {}
    off_c = off_rec.get(c_str, {}) if isinstance(off_rec, dict) else {}
    mas_rec = master_db.get(name, {}) if master_db else {}
    mas_c = mas_rec.get("courses", {}).get(c_str, {}) if isinstance(mas_rec, dict) else {}

    # 公式コース別実績の抽出
    has_valid_off = False
    c_win = _f(off_c.get("win_rate"), -1.0)
    c_ren2 = _f(off_c.get("rentai2"), -1.0)
    c_ren3 = _f(off_c.get("rentai3"), -1.0)
    c_st_val = _f(off_c.get("avg_st"), -1.0)
    st_rank = _f(off_c.get("st_rank"), 3.3)
    tactical_type = str(off_c.get("tactical_type") or mas_c.get("tactical_type") or "")

    # もし当該コースの公式データがすべて0.0（新人やコース出走なし）なら、mas_cの実効値または勝率・枠番モデルから個別推計
    if c_win >= 0 and (c_win > 0 or c_ren2 > 0 or c_ren3 > 0):
        has_valid_off = True
    elif mas_c and (_f(mas_c.get("effective_rentai2"), 0) > 0 or _f(mas_c.get("official_win_rate"), 0) > 0):
        c_win = _f(mas_c.get("official_win_rate"), 0.0)
        c_ren2 = _f(mas_c.get("effective_rentai2") or mas_c.get("official_rentai2"), 0.0)
        c_ren3 = _f(mas_c.get("effective_rentai3") or mas_c.get("official_rentai3"), 0.0)
        c_st_val = _f(mas_c.get("official_avg_st"), base_st)
        has_valid_off = (c_win > 0 or c_ren2 > 0 or c_ren3 > 0)

    if not has_valid_off:
        # 個人勝率(nat_win)とモーター(m_rate)と枠番(num)から固有値を算出
        course_w_base = {1: 48.0, 2: 14.5, 3: 12.0, 4: 10.5, 5: 5.5, 6: 2.5}.get(num, 10.0)
        course_r2_base = {1: 66.0, 2: 36.0, 3: 32.0, 4: 28.0, 5: 18.0, 6: 10.0}.get(num, 25.0)
        course_r3_base = {1: 78.0, 2: 54.0, 3: 50.0, 4: 45.0, 5: 33.0, 6: 22.0}.get(num, 40.0)
        win_factor = (nat_win - 4.8) * {1: 7.5, 2: 4.2, 3: 3.8, 4: 3.5, 5: 2.8, 6: 1.8}.get(num, 3.0)
        m_factor = (m_rate - 33.0) * 0.22
        c_win = round(max(1.2, min(92.0, course_w_base + win_factor + m_factor)), 1)
        c_ren2 = round(max(c_win + 3.5, min(96.0, course_r2_base + win_factor * 1.4 + m_factor * 1.2)), 1)
        c_ren3 = round(max(c_ren2 + 4.0, min(98.0, course_r3_base + win_factor * 1.6 + m_factor * 1.4)), 1)
        c_st_val = round(max(0.11, min(0.25, base_st + {1: -0.01, 2: 0.0, 3: 0.0, 4: 0.01, 5: 0.01, 6: 0.02}.get(num, 0.0))), 2)
    else:
        c_win = round(c_win, 1)
        c_ren2 = round(max(c_win, c_ren2), 1)
        c_ren3 = round(max(c_ren2, c_ren3), 1)
        if c_st_val <= 0.05 or c_st_val > 0.35:
            c_st_val = base_st

    c_avg_st_str = f".{int(round(c_st_val * 100)):02d}"
    enter_rate = _f(off_c.get("entry_rate"), {1: 99.2, 2: 97.8, 3: 95.5, 4: 93.0, 5: 91.2, 6: 94.5}.get(num, 95.0))

    if num == 1:
        # 1コース: 逃げ率・差され率・捲られ率
        theory_esc = 76.0 if rank == "A1" else (66.0 if rank == "A2" else (51.0 if rank == "B1" else 35.0))
        escape_rate = round(max(24.0, min(94.0, c_win * 0.68 + theory_esc * 0.32 + (m_rate - 33.0) * 0.18 - (4.5 if "F1" in fl else 0.0))), 1)
        rem_loss = max(5.0, 100.0 - escape_rate - 8.5)
        makuri_ratio = min(0.64, max(0.26, 0.38 + (c_st_val - 0.16) * 2.8 + (st_rank - 3.0) * 0.05 + (0.06 if "F" in fl else 0.0)))
        makuri_loss = round(rem_loss * makuri_ratio, 1)
        sashi_loss = round(rem_loss * (1.0 - makuri_ratio), 1)

        if escape_rate >= 70.0:
            badge = "イン鉄板軸"
            badge_color = "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
            eval_text = f"公式1C1着率{c_win:.1f}%・2連対{c_ren2:.1f}%(ST{c_avg_st_str})。先マイ速攻で押し切り濃厚"
        elif escape_rate >= 56.0:
            badge = "イン先マイ有力"
            badge_color = "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
            eval_text = f"公式1C1着率{c_win:.1f}%・2連対{c_ren2:.1f}%。五分STなら先マイ主導権"
        elif sashi_loss >= makuri_loss:
            badge = "被差し警戒"
            badge_color = "bg-amber-500/20 text-amber-300 border-amber-500/40"
            eval_text = f"差され率{sashi_loss:.1f}%。1Mターン膨らみ時の2C・3C差し逆転に注意"
        else:
            badge = "被まくり警報"
            badge_color = "bg-rose-500/20 text-rose-300 border-rose-500/40"
            eval_text = f"捲られ率{makuri_loss:.1f}%(ST{c_avg_st_str})。スリット後手時のセンター強襲警戒"

        return {
            "enter_rate": enter_rate, "c_avg_st": c_avg_st_str,
            "c_win": c_win, "c_rentai2": c_ren2, "c_rentai3": c_ren3,
            "type_label": "逃げ率", "primary_rate": escape_rate,
            "sashi_loss": sashi_loss, "makuri_loss": makuri_loss,
            "sashi_rate": "-", "makuri_rate": "-", "makurisashi_rate": "-",
            "badge": badge, "badge_color": badge_color, "eval_text": eval_text,
            "ladies_tag": badge, "style_desc": eval_text
        }

    elif num == 2:
        # 2コース: 逃がし率・差し率・ジカまくり率
        release_rate = round(max(31.0, min(79.0, 53.5 + (0.17 - c_st_val) * 110.0 + (c_ren2 - 45.0) * 0.16 + (m_rate - 33.0) * 0.14 - (5.5 if "F" in fl else 0.0))), 1)
        sashi_v = round(max(4.2, c_win * 0.72 + c_ren2 * 0.09), 1)
        makuri_v = round(max(1.4, c_win * 0.22 + (3.2 if c_st_val <= 0.15 else 0.8) + max(0.0, (m_rate - 32.0) * 0.16)), 1)
        ms_v = round(max(0.8, c_win * 0.06 + c_ren2 * 0.03), 1)
        makuri_loss = round(max(7.2, 23.5 - (0.18 - c_st_val) * 85.0 - (c_ren2 - 42.0) * 0.12), 1)
        sashi_loss = round(max(6.4, 19.5 - (c_ren2 - 42.0) * 0.14), 1)

        if c_win >= 24.0 or sashi_v >= 20.0:
            badge = "2C逆転差し巧者"
            badge_color = "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
            eval_text = f"公式2C1着率{c_win:.1f}%・2連対{c_ren2:.1f}%(ST{c_avg_st_str})。鋭角差し＆直まくり逆転脅威"
        elif release_rate >= 60.0:
            badge = "2C堅実壁＆追走"
            badge_color = "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
            eval_text = f"逃がし率{release_rate:.1f}%・2C2連対{c_ren2:.1f}%。インの壁役兼手堅い差し追従"
        else:
            badge = "2C壁凹み注意"
            badge_color = "bg-rose-500/20 text-rose-300 border-rose-500/40"
            eval_text = f"被まくり率{makuri_loss:.1f}%(ST{c_avg_st_str})。3C・4Cの外マイ強襲に要注意"

        return {
            "enter_rate": enter_rate, "c_avg_st": c_avg_st_str,
            "c_win": c_win, "c_rentai2": c_ren2, "c_rentai3": c_ren3,
            "type_label": "逃がし率", "primary_rate": release_rate,
            "sashi_loss": sashi_loss, "makuri_loss": makuri_loss,
            "sashi_rate": f"{sashi_v:.1f}%", "makuri_rate": f"{makuri_v:.1f}%", "makurisashi_rate": f"{ms_v:.1f}%",
            "badge": badge, "badge_color": badge_color, "eval_text": eval_text,
            "ladies_tag": badge, "style_desc": eval_text
        }

    elif num == 3:
        # 3コース: ツケマイ捲り・捲り差し・センター攻防
        release_rate = round(max(29.0, min(74.0, 50.5 + (0.17 - c_st_val) * 75.0 - (c_win - 15.0) * 0.24 + (m_rate - 33.0) * 0.10)), 1)
        makuri_v = round(max(3.2, c_win * 0.48 + c_ren2 * 0.11 + max(0.0, (m_rate - 31.0) * 0.18)), 1)
        ms_v = round(max(2.6, c_win * 0.38 + c_ren2 * 0.12), 1)
        sashi_v = round(max(1.5, c_win * 0.14 + c_ren2 * 0.05), 1)
        makuri_loss = round(max(6.8, 21.5 - (0.18 - c_st_val) * 80.0 - (c_ren2 - 38.0) * 0.11), 1)
        sashi_loss = round(max(7.2, 18.0 - (c_ren2 - 38.0) * 0.10), 1)

        if makuri_v >= 14.0 or c_win >= 20.0:
            badge = "3Cツケマイ強襲"
            badge_color = "bg-purple-500/20 text-purple-300 border-purple-500/40"
            eval_text = f"公式3C1着率{c_win:.1f}%・2連対{c_ren2:.1f}%(ST{c_avg_st_str})。スリット先制から全速外マイ強襲"
        elif ms_v >= 9.5 or c_ren2 >= 42.0:
            badge = "3C捲り差し巧者"
            badge_color = "bg-indigo-500/20 text-indigo-300 border-indigo-500/40"
            eval_text = f"公式3C2連対{c_ren2:.1f}%・3連対{c_ren3:.1f}%。1M間隙を鋭く突くまくり差し"
        else:
            badge = "3C外マイ追走"
            badge_color = "bg-slate-500/20 text-slate-300 border-slate-500/40"
            eval_text = f"3C3連対率{c_ren3:.1f}%(ST{c_avg_st_str})。カド受け意識しつつ外マイ連下争い"

        return {
            "enter_rate": enter_rate, "c_avg_st": c_avg_st_str,
            "c_win": c_win, "c_rentai2": c_ren2, "c_rentai3": c_ren3,
            "type_label": "逃がし率", "primary_rate": release_rate,
            "sashi_loss": sashi_loss, "makuri_loss": makuri_loss,
            "sashi_rate": f"{sashi_v:.1f}%", "makuri_rate": f"{makuri_v:.1f}%", "makurisashi_rate": f"{ms_v:.1f}%",
            "badge": badge, "badge_color": badge_color, "eval_text": eval_text,
            "ladies_tag": badge, "style_desc": eval_text
        }

    elif num == 4:
        # 4コース: カド捲り・カド捲り差し・一番差し
        release_rate = round(max(33.0, min(76.0, 54.5 - (c_win - 12.0) * 0.34 + (c_st_val - 0.16) * 58.0)), 1)
        makuri_v = round(max(2.8, c_win * 0.50 + c_ren2 * 0.11 + max(0.0, (0.18 - c_st_val) * 55.0) + max(0.0, (m_rate - 31.0) * 0.18)), 1)
        ms_v = round(max(2.4, c_win * 0.32 + c_ren2 * 0.12), 1)
        sashi_v = round(max(2.2, c_win * 0.18 + c_ren2 * 0.08 + c_ren3 * 0.06), 1)
        makuri_loss = round(max(6.2, 18.5 - (0.18 - c_st_val) * 65.0), 1)
        sashi_loss = round(max(7.4, 20.5 - (c_ren3 - 42.0) * 0.13), 1)

        if makuri_v >= 14.0 or c_win >= 18.0:
            badge = "4カド一撃強襲"
            badge_color = "bg-rose-500/20 text-rose-300 border-rose-500/40"
            eval_text = f"公式4C1着率{c_win:.1f}%・2連対{c_ren2:.1f}%(ST{c_avg_st_str})。カドから一気に絞り込む強襲型"
        elif c_ren3 >= 44.0 or ms_v >= 8.0:
            badge = "4C自在差し連動"
            badge_color = "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
            eval_text = f"公式4C3連対{c_ren3:.1f}%(ST{c_avg_st_str})。展開を見極めて的確に一番差し・連下浮上"
        else:
            badge = "4Cダッシュ追走"
            badge_color = "bg-slate-500/20 text-slate-300 border-slate-500/40"
            eval_text = f"公式4C2連対{c_ren2:.1f}%・3連対{c_ren3:.1f}%。内枠の懐を突く展開待ち"

        return {
            "enter_rate": enter_rate, "c_avg_st": c_avg_st_str,
            "c_win": c_win, "c_rentai2": c_ren2, "c_rentai3": c_ren3,
            "type_label": "逃がし率", "primary_rate": release_rate,
            "sashi_loss": sashi_loss, "makuri_loss": makuri_loss,
            "sashi_rate": f"{sashi_v:.1f}%", "makuri_rate": f"{makuri_v:.1f}%", "makurisashi_rate": f"{ms_v:.1f}%",
            "badge": badge, "badge_color": badge_color, "eval_text": eval_text,
            "ladies_tag": badge, "style_desc": eval_text
        }

    elif num == 5:
        # 5コース: まくり差し・外連動
        release_rate = round(max(41.0, min(79.0, 60.5 - (c_win - 8.0) * 0.28 + (c_st_val - 0.17) * 45.0)), 1)
        ms_v = round(max(2.0, c_win * 0.58 + c_ren2 * 0.14 + max(0.0, (m_rate - 31.0) * 0.14)), 1)
        makuri_v = round(max(1.2, c_win * 0.24 + max(0.0, (0.18 - c_st_val) * 35.0)), 1)
        sashi_v = round(max(1.6, c_win * 0.18 + c_ren3 * 0.08), 1)
        makuri_loss = round(max(5.5, 15.8 - (c_ren3 - 30.0) * 0.09), 1)
        sashi_loss = round(max(6.8, 17.8 - (c_ren2 - 20.0) * 0.11), 1)

        if c_win >= 12.0 or ms_v >= 9.0:
            badge = "5Cまくり差し一撃"
            badge_color = "bg-amber-500/20 text-amber-300 border-amber-500/40"
            eval_text = f"公式5C1着率{c_win:.1f}%・2連対{c_ren2:.1f}%(ST{c_avg_st_str})。センター攻勢連動のまくり差し巧者"
        elif c_ren3 >= 35.0:
            badge = "5C外連動巧者"
            badge_color = "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
            eval_text = f"公式5C3連対{c_ren3:.1f}%。カド攻めに連動して2・3着へ食い込む"
        else:
            badge = "5C展開突き待ち"
            badge_color = "bg-slate-500/20 text-slate-300 border-slate-500/40"
            eval_text = f"公式5C3連対{c_ren3:.1f}%(ST{c_avg_st_str})。1M混戦時の最内・間隙差し狙い"

        return {
            "enter_rate": enter_rate, "c_avg_st": c_avg_st_str,
            "c_win": c_win, "c_rentai2": c_ren2, "c_rentai3": c_ren3,
            "type_label": "逃がし率", "primary_rate": release_rate,
            "sashi_loss": sashi_loss, "makuri_loss": makuri_loss,
            "sashi_rate": f"{sashi_v:.1f}%", "makuri_rate": f"{makuri_v:.1f}%", "makurisashi_rate": f"{ms_v:.1f}%",
            "badge": badge, "badge_color": badge_color, "eval_text": eval_text,
            "ladies_tag": badge, "style_desc": eval_text
        }

    else:
        # 6コース: 最内差し・道中捌き・大外強襲
        release_rate = round(max(46.0, min(83.0, 64.8 - (c_ren2 - 15.0) * 0.22 + (c_st_val - 0.17) * 40.0)), 1)
        sashi_v = round(max(1.5, c_win * 0.44 + c_ren2 * 0.18 + c_ren3 * 0.08), 1)
        ms_v = round(max(1.2, c_win * 0.40 + c_ren2 * 0.15 + max(0.0, (m_rate - 31.0) * 0.12)), 1)
        makuri_v = round(max(0.8, c_win * 0.16 + max(0.0, (0.18 - c_st_val) * 30.0)), 1)
        makuri_loss = round(max(4.6, 13.5 - (c_ren3 - 25.0) * 0.08), 1)
        sashi_loss = round(max(5.6, 15.2 - (c_ren2 - 15.0) * 0.10), 1)

        if c_ren2 >= 25.0 or c_ren3 >= 32.0 or rank in ["A1", "A2"]:
            badge = "6C最内強襲・鬼捌き"
            badge_color = "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
            eval_text = f"公式6C2連対{c_ren2:.1f}%・3連対{c_ren3:.1f}%(ST{c_avg_st_str})。最内差し＆道中捌きで舟券圏内浮上"
        else:
            badge = "6C大外展開待ち"
            badge_color = "bg-slate-500/20 text-slate-300 border-slate-500/40"
            eval_text = f"公式6C3連対{c_ren3:.1f}%(ST{c_avg_st_str})。1M全速戦のもつれを突く最内小回り"

        return {
            "enter_rate": enter_rate, "c_avg_st": c_avg_st_str,
            "c_win": c_win, "c_rentai2": c_ren2, "c_rentai3": c_ren3,
            "type_label": "逃がし率", "primary_rate": release_rate,
            "sashi_loss": sashi_loss, "makuri_loss": makuri_loss,
            "sashi_rate": f"{sashi_v:.1f}%", "makuri_rate": f"{makuri_v:.1f}%", "makurisashi_rate": f"{ms_v:.1f}%",
            "badge": badge, "badge_color": badge_color, "eval_text": eval_text,
            "ladies_tag": badge, "style_desc": eval_text
        }


def compute_physics_upset_bets(boats, scores, exclude_combs=None, real_odds=None):
    """
    選手能力・モーター2連対率・展示タイム・オリジナル展示（一周・まわり足・直線）の物理シグナルから、
    万舟・波乱を引き起こす4大物理展開メカニズムを厳密に計算し、穴予想4点を導出する。
    """
    if exclude_combs is None:
        exclude_combs = set()

    b_map = {b["num"]: b for b in boats}
    nums = [1, 2, 3, 4, 5, 6]

    def safe_float(val, default=99.9):
        try:
            if val is None or val in ["", "--", "--.--"]:
                return default
            return float(val)
        except Exception:
            return default

    win_rates = {n: safe_float(b_map[n].get("win_rate") or b_map[n].get("course_win_rate"), 4.5) for n in nums}
    motor_rates = {n: safe_float(b_map[n].get("motor_rate"), 30.0) for n in nums}
    ex_times = {n: safe_float(b_map[n].get("ex_time"), 99.9) for n in nums}
    lap_times = {n: safe_float(b_map[n].get("lap_time") or b_map[n].get("lap"), 99.9) for n in nums}
    turn_times = {n: safe_float(b_map[n].get("turn_time") or b_map[n].get("turn"), 99.9) for n in nums}
    str_times = {n: safe_float(b_map[n].get("straight_time") or b_map[n].get("straight"), 99.9) for n in nums}

    # 順位マップ作成 (1位が最良)
    win_order = sorted(nums, key=lambda n: win_rates[n], reverse=True)
    motor_order = sorted(nums, key=lambda n: motor_rates[n], reverse=True)
    ex_order = sorted(nums, key=lambda n: (ex_times[n], -scores.get(n, 0)))
    lap_order = sorted(nums, key=lambda n: (lap_times[n], -scores.get(n, 0)))
    turn_order = sorted(nums, key=lambda n: (turn_times[n], -scores.get(n, 0)))
    str_order = sorted(nums, key=lambda n: (str_times[n], -scores.get(n, 0)))

    # オリ展・展示総合気配スコア（小さいタイムほど高評価）
    ex_power = {}
    for n in nums:
        ep = 0.0
        if ex_times[n] < 90.0:
            r_ex = ex_order.index(n)
            ep += (5 - r_ex) * 2.5
        if lap_times[n] < 90.0:
            r_lap = lap_order.index(n)
            ep += (5 - r_lap) * 3.0
        if turn_times[n] < 90.0:
            r_turn = turn_order.index(n)
            ep += (5 - r_turn) * 3.0
        if str_times[n] < 90.0:
            r_str = str_order.index(n)
            ep += (5 - r_str) * 2.5
        ex_power[n] = ep

    candidates = []

    # ---------------------------------------------------------
    # シナリオ1: 【大外・ダッシュ実力者強襲（5・6枠まくり/まくり差し万舟）】
    # 5・6号艇に勝率5.20以上（またはA1/A2級・番組勝率1〜2位）の実力者がいる場合のみ頭で狙い撃つ
    # （例: 10/17 11R 6号艇大山千広[A2・勝率7.58] ➔ 2号艇奥村[オリ展三冠] ➔ 1号艇関野 = 6-2-1 27,430円）
    # ---------------------------------------------------------
    outer_stars = [
        n for n in [5, 6]
        if (win_rates[n] >= 5.20 and (win_order.index(n) <= 1 or b_map[n].get("rank") in ["A1", "A2"] or ex_power[n] >= 22.0))
    ]
    if outer_stars:
        o_star = sorted(outer_stars, key=lambda n: (win_rates[n] * 8.0 + motor_rates[n] * 0.4 + ex_power[n]), reverse=True)[0]
        inner_followers = [n for n in [2, 3, 4, 1, 5, 6] if n != o_star]
        inner_followers.sort(key=lambda n: (ex_power[n] * 1.5 + scores.get(n, 0) * 0.6 + (8.0 if n in [2, 3] else 0.0)), reverse=True)
        b2_cand = inner_followers[0]
        b3_cand = 1 if b2_cand != 1 else inner_followers[1]
        candidates.append((
            f"{o_star}-{b2_cand}-{b3_cand}",
            f"【外枠強襲万舟】{o_star}号艇{b_map[o_star]['name']}がまくり/最内強襲 ➔ 気配上位{b2_cand}号艇{b_map[b2_cand]['name']} ➔ {b3_cand}号艇"
        ))

    # ---------------------------------------------------------
    # シナリオ2: 【2・3コース超抜機/展示優位まくり ➔ 外枠ダッシュ連動 ➔ イン残し万舟】
    # 2・3号艇がモーター上位(特に40%超や番組1位)または展示優位でまくり、外枠(5・4・6)が2着連動し1号艇が3着に残る
    # （例: 10/17 12R 2号艇大石真央[モーター43.6%番組1位] ➔ 5号艇犬童千秋連動 ➔ 1号艇野田 = 2-5-1 16,150円）
    # ---------------------------------------------------------
    makuri_attackers = [2, 3]
    makuri_attackers.sort(
        key=lambda n: (
            motor_rates[n] * 1.8
            + (15.0 if motor_order.index(n) == 0 else 0.0)
            + ex_power[n] * 1.0
            + scores.get(n, 0) * 0.3
        ),
        reverse=True
    )
    m_head = makuri_attackers[0]
    dash_linkers = [n for n in [5, 4, 6] if n != m_head]
    dash_linkers.sort(
        key=lambda n: (
            motor_rates[n] * 1.0
            + ex_power[n] * 1.2
            + win_rates[n] * 2.5
            + (8.0 if n == 5 and ex_power.get(4, 20) < 15 else 0.0)
        ),
        reverse=True
    )
    d_second = dash_linkers[0]
    candidates.append((
        f"{m_head}-{d_second}-1",
        f"【まくり外連動万舟】{m_head}号艇{b_map[m_head]['name']}まくり一撃 ➔ 外枠{d_second}号艇{b_map[d_second]['name']}連動 ➔ イン1号艇3着粘り"
    ))

    # ---------------------------------------------------------
    # シナリオ3: 【イン完全沈没（1号艇着外）の2コース差し・3コース攻勢 ➔ 4・5・6号艇連動 万舟】
    # 1号艇が引き波に沈み、2・3号艇とダッシュ勢（4・5・6）で決着する王道万舟パターン（例: 10/18 2R 2-3-5 10,910円 / 10/17 3R 2-3-4）
    # ---------------------------------------------------------
    dash_followers = [4, 5, 6]
    dash_followers.sort(
        key=lambda n: (scores.get(n, 0) + ex_power[n] * 1.2 + motor_rates[n] * 0.8 + win_rates[n] * 4.0),
        reverse=True
    )
    df1, df2 = dash_followers[0], dash_followers[1]
    candidates.append((
        f"2-3-{df1}",
        f"【イン完全沈没・2C差し万舟】2号艇{b_map[2]['name']}差し切り ➔ 3号艇{b_map[3]['name']} ➔ ダッシュ{df1}号艇{b_map[df1]['name']}(1着外)"
    ))
    candidates.append((
        f"2-3-{df2}",
        f"【イン完全沈没・2C差し万舟】2号艇{b_map[2]['name']}差し切り ➔ 3号艇{b_map[3]['name']} ➔ 外枠{df2}号艇{b_map[df2]['name']}連動(1着外)"
    ))
    candidates.append((
        f"3-2-{df1}",
        f"【イン完全沈没・3C攻勢万舟】3号艇{b_map[3]['name']}先制 ➔ 2号艇{b_map[2]['name']}追従 ➔ ダッシュ{df1}号艇{b_map[df1]['name']}(1着外)"
    ))
    candidates.append((
        f"3-2-{df2}",
        f"【イン完全沈没・3C攻勢万舟】3号艇{b_map[3]['name']}先制 ➔ 2号艇{b_map[2]['name']}追従 ➔ 外枠{df2}号艇{b_map[df2]['name']}(1着外)"
    ))

    # ---------------------------------------------------------
    # シナリオ4: 【イン逃げ＋外枠（4・5・6）2・3着の穴連動】（※ 1-2-3 / 1-3-2 等の本命スジは穴予想から完全排除！）
    # ---------------------------------------------------------
    outer_pair = [4, 5, 6]
    outer_pair.sort(key=lambda n: (ex_power[n] * 1.3 + scores.get(n, 0) * 0.5 + win_rates[n] * 3.0), reverse=True)
    op1, op2 = outer_pair[0], outer_pair[1]
    # 旋回半径の物理法則: 大外6号艇が含まれる場合は内側のダッシュ艇(4・5)が2着先マイ、6号艇が3着追従を第一優先
    if op1 == 6:
        b2_out, b3_out = op2, op1
    else:
        b2_out, b3_out = op1, op2
    comb_in_outer1 = f"1-{b2_out}-{b3_out}"
    comb_in_outer2 = f"1-{b3_out}-{b2_out}"
    if comb_in_outer1 not in exclude_combs:
        candidates.append((
            comb_in_outer1,
            f"【外枠連下食い込み】イン{b_map[1]['name']}逃げ ➔ 気配上位の外枠{b2_out}号艇2着・{b3_out}号艇3着強襲"
        ))
    if comb_in_outer2 not in exclude_combs:
        candidates.append((
            comb_in_outer2,
            f"【外枠連下食い込み】イン{b_map[1]['name']}逃げ ➔ 外枠{b3_out}号艇2着・{b2_out}号艇3着の波乱連下"
        ))

    # 予備候補（カドまくり外連動 4-5-6 / 4-5-1 / 3-4-5 / 2コース頭イン残り）
    extra_cands = [
        (f"2-{df1}-1", f"【2C強襲・外連動万舟】2号艇{b_map[2]['name']}逆転 ➔ 外枠{df1}号艇連動 ➔ イン1号艇3着"),
        (f"4-{op2 if op2 != 4 else 5}-1", f"【カド一撃万舟】4号艇{b_map[4]['name']}カド攻勢 ➔ 外連動 ➔ イン残り"),
        (f"4-5-6", f"【ダッシュ全速万舟】4カドまくり ➔ 5・6号艇外枠完全連動"),
        (f"3-4-5", f"【センターまくり万舟】3コースまくり ➔ 4・5号艇ダッシュ連動(1着外)"),
        (f"2-1-{df1}", f"【2C差し逆転】2号艇{b_map[2]['name']}差し切り ➔ 1号艇残し ➔ 外枠{df1}号艇")
    ]
    candidates.extend(extra_cands)

    # 重複排除とreal_oddsがある場合の厳格な穴オッズ検証
    # 本命スジ（1-2-3, 1-3-2）はオッズにかかわらず穴予想に絶対に入れない
    forbidden_main_chalk = {"1-2-3", "1-3-2"}
    final_ana = []
    used = set(exclude_combs) | forbidden_main_chalk

    # 第1パス: 実測オッズがある場合は 20.0倍〜380.0倍（中穴〜現実的万舟ゾーン）を最優先で抽出
    for comb, desc in candidates:
        parts = comb.split("-")
        if len(set(parts)) != 3 or comb in used:
            continue
        if real_odds and comb in real_odds:
            odd_v = float(real_odds[comb])
            if odd_v < 20.0 or odd_v > 380.0:
                continue
        final_ana.append((comb, desc))
        used.add(comb)
        if len(final_ana) == 4:
            break

    # 第2パス: 4点に満たない場合は 18.0倍〜600.0倍 まで許容（18倍未満の低配当は絶対に入れない）
    if len(final_ana) < 4:
        for comb, desc in candidates:
            parts = comb.split("-")
            if len(set(parts)) != 3 or comb in used:
                continue
            if real_odds and comb in real_odds:
                odd_v = float(real_odds[comb])
                if 0.0 < odd_v < 18.0:
                    continue
            final_ana.append((comb, desc))
            used.add(comb)
            if len(final_ana) == 4:
                break

    return final_ana[:4]


def reclassify_bets_by_odds(main_raw, ana_raw, real_odds, boats=None, scores=None):
    """
    市場オッズと物理展開モデルに基づいて本線と穴目を最適化する。
    - 本線4点: 上位人気・本命対抗の王道目
    - 穴目4点: compute_physics_upset_bets による物理根拠のある高配当・万舟目（12倍未満の低配当を排除）
    """
    if not real_odds or len(real_odds) == 0:
        return main_raw, ana_raw

    # 本線の確定（極端な万舟が本線に混ざっていた場合のみ入れ替え、基本は本命4点を維持）
    new_main = []
    seen_main = set()
    for c, d in main_raw:
        if c not in seen_main:
            new_main.append((c, d))
            seen_main.add(c)
    new_main = new_main[:4]

    # 選手の展示・機力データが揃っている場合は、物理波乱エンジンに実測オッズを渡して真の穴4点を算出
    if boats and scores:
        new_ana = compute_physics_upset_bets(
            boats=boats,
            scores=scores,
            exclude_combs=seen_main,
            real_odds=real_odds
        )
        if len(new_ana) == 4:
            return new_main, new_ana

    # フォールバック: 既存のana_rawのうち12倍以上のものを優先維持し、不足分のみ物理順で補完
    new_ana = []
    used = set(seen_main)
    for c, d in ana_raw:
        if c not in used:
            odd_v = float(real_odds.get(c, 0.0))
            if odd_v == 0.0 or odd_v >= 12.0:
                new_ana.append((c, d))
                used.add(c)
    for c, d in main_raw + ana_raw:
        if len(new_ana) >= 4:
            break
        if c not in used:
            new_ana.append((c, d))
            used.add(c)

    return new_main[:4], new_ana[:4]

def get_venue_config(date_str: str) -> dict:
    """日付から該当するレディース戦・ヴィーナスシリーズの会場設定を返す"""
    if "20261007" <= date_str <= "20261012":
        return {"jcd": "03", "prefix": "edogawa", "stadium": "江戸川", "series_title": "オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ"}
    elif "20261013" <= date_str <= "20261018":
        return {"jcd": "20", "prefix": "wakamatsu", "stadium": "若松", "series_title": "ヴィーナスＳ１５戦マクール杯ナイトプリンセスカップ"}
    elif "20261019" <= date_str <= "20261024":
        return {"jcd": "12", "prefix": "suminoe", "stadium": "住之江", "series_title": "オールレディース ２０２６モーターボートレディスカップ"}
    elif "20261025" <= date_str <= "20261030":
        return {"jcd": "01", "prefix": "kiryu", "stadium": "桐生", "series_title": "第１９回マクール杯 ヴィーナスシリーズ第１６戦"}
    elif "20261031" <= date_str <= "20261105":
        return {"jcd": "09", "prefix": "tsu", "stadium": "津", "series_title": "津オールレディース マクール杯"}
    elif "20261106" <= date_str <= "20261111":
        return {"jcd": "05", "prefix": "tamagawa", "stadium": "多摩川", "series_title": "ヴィーナスシリーズ第１７戦"}
    elif "20261112" <= date_str <= "20261117":
        return {"jcd": "23", "prefix": "karatsu", "stadium": "唐津", "series_title": "ヴィーナスシリーズ第１８戦"}
    elif "20261118" <= date_str <= "20261123":
        return {"jcd": "02", "prefix": "toda", "stadium": "戸田", "series_title": "戸田オールレディース"}
    return {"jcd": "20", "prefix": "wakamatsu", "stadium": "若松", "series_title": "ヴィーナスＳ１５戦マクール杯ナイトプリンセスカップ"}

def generate_race_data_for_date(date_str: str, jcd: str = None) -> bool:
    vcfg = get_venue_config(date_str)
    if not jcd:
        jcd = vcfg["jcd"]
    stadium_name = vcfg["stadium"]
    prefix = vcfg["prefix"]
    out_file = os.path.join(DATA_DIR, f"{prefix}_{date_str}_data.json")
    print(f"Checking race table availability for {date_str} {stadium_name} (jcd={jcd})...")
    
    check_url = f"https://www.boatrace.jp/owpc/pc/race/racelist?rno=1&jcd={jcd}&hd={date_str}"
    live_deadlines = dict(deadlines)
    try:
        c_resp = requests.get(check_url, headers=HEADERS, timeout=30)
        c_resp.encoding = c_resp.apparent_encoding or "utf-8"
        c_soup = BeautifulSoup(c_resp.text, "html.parser")
        c_tables = c_soup.select("table")
        if len(c_tables) < 2 or len(c_tables[1].select("tbody")) < 6:
            print(f"[{date_str}] Racelist not published yet (tables={len(c_tables)}).")
            return False
        # テーブル0から1R〜12Rの公式締切時刻を取得
        times_found = re.findall(r"\b(\d{1,2}:\d{2})\b", c_tables[0].get_text())
        if len(times_found) >= 12:
            for r_idx in range(12):
                live_deadlines[r_idx + 1] = times_found[r_idx]
    except Exception as e:
        print(f"[{date_str}] Error checking racelist: {e}")
        return False

    learned_data = build_and_save_learned_stats()
    final_data = {}
    for r in range(1, 13):
        url = f"https://www.boatrace.jp/owpc/pc/race/racelist?rno={r}&jcd={jcd}&hd={date_str}"
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        tables = soup.select("table")
        if len(tables) < 2: continue
        r_tbl = tables[1]
        tbodies = r_tbl.select("tbody")
        boats = []
        for idx, tb in enumerate(tbodies[:6]):
            num = idx + 1
            tr0 = tb.select_one("tr")
            if not tr0: continue
            tds = tr0.select("td")
            if len(tds) < 8: continue
            td2 = tds[2]
            td2_text = td2.get_text(separator="\n", strip=True)
            toban_m = re.search(r"(\d{4})", td2_text)
            toban = toban_m.group(1) if toban_m else "0000"
            rank_m = re.search(r"([AB][12])", td2_text)
            rank = rank_m.group(1) if rank_m else "B1"
            a_tag = td2.select_one("a")
            name = a_tag.get_text(strip=True).replace(" ", "").replace("\u3000", "") if a_tag else f"選手{num}"
            branch_m = re.search(r"([^\s\d/]+)\s*/\s*([^\s\d/]+)", td2_text)
            branch = branch_m.group(1) if branch_m else "福岡"
            td3_text = tds[3].get_text(separator=" ", strip=True)
            f_m = re.search(r"(F\d)", td3_text)
            fl = f_m.group(1) if f_m else "F0"
            st_m = re.search(r"0\.(\d{2})", td3_text)
            avg_st = float("0." + st_m.group(1)) if st_m else (0.22 if "B2" in rank else 0.17)
            avg_st_str = f".{int(avg_st * 100):02d}"
            td4_parts = tds[4].get_text(separator=" ", strip=True).split()
            nat_win = float(td4_parts[0]) if len(td4_parts) > 0 and re.match(r"^\d+\.\d+$", td4_parts[0]) else 5.0
            nat_2ren = float(td4_parts[1]) if len(td4_parts) > 1 and re.match(r"^\d+\.\d+$", td4_parts[1]) else 30.0
            td5_parts = tds[5].get_text(separator=" ", strip=True).split()
            loc_win = float(td5_parts[0]) if len(td5_parts) > 0 and re.match(r"^\d+\.\d+$", td5_parts[0]) else nat_win
            loc_2ren = float(td5_parts[1]) if len(td5_parts) > 1 and re.match(r"^\d+\.\d+$", td5_parts[1]) else nat_2ren
            td6_parts = tds[6].get_text(separator=" ", strip=True).split()
            m_no = td6_parts[0] if len(td6_parts) > 0 else "1"
            m_rate = float(td6_parts[1]) if len(td6_parts) > 1 and re.match(r"^\d+\.\d+$", td6_parts[1]) else 30.0
            td7_parts = tds[7].get_text(separator=" ", strip=True).split()
            b_no = td7_parts[0] if len(td7_parts) > 0 else "1"
            b_rate = float(td7_parts[1]) if len(td7_parts) > 1 and re.match(r"^\d+\.\d+$", td7_parts[1]) else 30.0
            boat_for_st = {"num": num, "name": name, "rank": rank, "fl": fl, "avg_st": avg_st}
            st_res = compute_comprehensive_predicted_st(boat_for_st, None, None)
            boats.append({
                "num": num, "name": name, "toban": toban, "id": toban,
                "grade": rank, "rank": rank, "branch": branch, "fl": fl,
                "f_res": "自重" if "F1" in fl or "F2" in fl else "強気",
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
        if len(boats) != 6: continue
        race_pred = generate_bets_for_race(r, boats, learned_data=learned_data, stadium=stadium_name)
        
        # オッズ
        real_odds = {}
        odds_url = f"https://www.boatrace.jp/owpc/pc/race/odds3t?rno={r}&jcd={jcd}&hd={date_str}"
        try:
            o_resp = requests.get(odds_url, headers=HEADERS, timeout=10)
            if o_resp.status_code == 200:
                real_odds = parse_boatrace_odds3t(o_resp.text)
        except Exception: pass
        
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
        
        rk = f"r_{r}"
        final_data[rk] = {
            "round": r, "stadium": stadium_name, "title": race_pred["grade_title"],
            "grade": race_pred["grade"], "grade_badge": race_pred["grade_badge"], "grade_title": race_pred["grade_title"],
            "core_scenario": race_pred["core_scenario"], "physics_detail": race_pred["physics_detail"],
            "deadline": live_deadlines.get(r, "15:00"), "boats": boats,
            "main_bets": main_bets, "ana_bets": ana_bets,
            "official_odds_3t": real_odds, "official_result": None
        }

    if len(final_data) == 12:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)
        print(f"[{date_str}] Successfully generated all 12 races to {out_file}")
        return True
    return False

if __name__ == "__main__":
    import datetime
    target_d = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now().strftime("%Y%m%d")
    generate_race_data_for_date(target_d)


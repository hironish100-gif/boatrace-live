"""
lightgbm_prediction_service.py
3大LightGBM機械学習モデル統合エンジン：
1. lgb_win_model.txt (1着確率モデル)
2. lgb_rentai2_model.txt (2連対確率モデル)
3. lgb_rentai3_model.txt (3連対確率モデル)
SQLite公式ビッグデータ(16,153件)の特徴量を入力し、
3連単全120通りの客観出現確率 P(i,j,k) とオッズから
純粋な期待値(EV = P * Odds)を算出して買い目を選定する。
"""

import os
import sys
import json
import sqlite3
import numpy as np
import pandas as pd
import lightgbm as lgb

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "boatrace_master_bigdata.db")
MODEL_DIR = os.path.join(BASE_DIR, "models")

WIN_MODEL_PATH = os.path.join(MODEL_DIR, "lgb_win_model.txt")
RENTAI2_MODEL_PATH = os.path.join(MODEL_DIR, "lgb_rentai2_model.txt")
RENTAI3_MODEL_PATH = os.path.join(MODEL_DIR, "lgb_rentai3_model.txt")

_win_model = None
_rentai2_model = None
_rentai3_model = None
_racer_lookup = None

def get_models():
    global _win_model, _rentai2_model, _rentai3_model
    if _win_model is None and os.path.exists(WIN_MODEL_PATH):
        _win_model = lgb.Booster(model_file=WIN_MODEL_PATH)
    if _rentai2_model is None and os.path.exists(RENTAI2_MODEL_PATH):
        _rentai2_model = lgb.Booster(model_file=RENTAI2_MODEL_PATH)
    if _rentai3_model is None and os.path.exists(RENTAI3_MODEL_PATH):
        _rentai3_model = lgb.Booster(model_file=RENTAI3_MODEL_PATH)
    return _win_model, _rentai2_model, _rentai3_model

def get_racer_lookup():
    global _racer_lookup
    if _racer_lookup is None:
        conn = sqlite3.connect(DB_PATH)
        query = "SELECT * FROM racer_period_stats WHERE period = '2604'"
        df = pd.read_sql_query(query, conn)
        conn.close()
        _racer_lookup = {int(row['toban']): row.to_dict() for _, row in df.iterrows()}
    return _racer_lookup

def predict_race_with_lightgbm(boats, real_odds=None, stadium="津"):
    racer_lookup = get_racer_lookup()
    win_model, r2_model, r3_model = get_models()
    grade_map = {"A1": 4, "A2": 3, "B1": 2, "B2": 1}

    features = [
        "boat_num", "win_rate", "rentai2_rate", "grade_val", "avg_st",
        "c_enters", "c_rentai2", "c_st", "motor_rate", "boat_rate", "ex_time"
    ]

    rows = []
    b_map = {}
    for b in boats:
        num = int(b.get("num", 1))
        toban = int(b.get("toban", b.get("id", 0)))
        b_map[num] = b

        r_stats = racer_lookup.get(toban, {})
        w_rate = float(r_stats.get("win_rate", b.get("win_rate", 4.5)))
        r2_rate = float(r_stats.get("rentai2_rate", 30.0))
        avg_st = float(r_stats.get("avg_st", b.get("avg_st", 0.17)))
        g_val = grade_map.get(r_stats.get("grade", b.get("rank", "B1")), 2)

        c_enters = float(r_stats.get(f"c{num}_enters", 15.0))
        c_rentai2 = float(r_stats.get(f"c{num}_rentai2", 30.0))
        c_st = float(r_stats.get(f"c{num}_avg_st", avg_st))

        m_rate = float(b.get("motor_rate", 30.0))
        b_rate = float(b.get("boat_rate", 30.0))
        ex_t = float(b.get("ex_time", 6.80)) if b.get("ex_time") and b.get("ex_time") != "--.--" else 6.80

        rows.append({
            "boat_num": num,
            "win_rate": w_rate,
            "rentai2_rate": r2_rate,
            "grade_val": g_val,
            "avg_st": avg_st,
            "c_enters": c_enters,
            "c_rentai2": c_rentai2,
            "c_st": c_st,
            "motor_rate": m_rate,
            "boat_rate": b_rate,
            "ex_time": ex_t
        })

    df_race = pd.DataFrame(rows)
    X = df_race[features]

    # LightGBM 3大モデルによる推論
    p_win_raw = win_model.predict(X)
    p_r2_raw = r2_model.predict(X)
    p_r3_raw = r3_model.predict(X)

    # 1着確率 P(i) の正規化
    p_win_sum = sum(p_win_raw) or 1.0
    p_1st = {i+1: float(p_win_raw[i] / p_win_sum) for i in range(6)}

    # 2着能力スコア & 3着能力スコア
    s_2nd = {i+1: float(p_r2_raw[i]) for i in range(6)}
    s_3rd = {i+1: float(p_r3_raw[i]) for i in range(6)}

    # 3連単120通りの同時確率分布 P(i, j, k)
    prob_120 = {}
    for i in range(1, 7):
        p1 = p_1st[i]
        rem_j = [j for j in range(1, 7) if j != i]
        sum_2 = sum(s_2nd[j] for j in rem_j) or 1.0

        for j in rem_j:
            p2 = s_2nd[j] / sum_2
            rem_k = [k for k in rem_j if k != j]
            sum_3 = sum(s_3rd[k] for k in rem_k) or 1.0

            for k in rem_k:
                p3 = s_3rd[k] / sum_3
                comb = f"{i}-{j}-{k}"
                prob_120[comb] = p1 * p2 * p3

    # オッズテーブル構築
    odds_table = {}
    for comb, p in prob_120.items():
        if real_odds and comb in real_odds and float(real_odds[comb]) > 0:
            odds_table[comb] = float(real_odds[comb])
        else:
            fair = round(0.75 / max(0.0005, p), 1)
            odds_table[comb] = max(1.1, fair)

    # 期待値 EV = P * Odds
    ev_table = {c: prob_120[c] * odds_table[c] for c in prob_120}

    # 軸艇決定 (1着確率最上位)
    top_boat = max(p_1st.keys(), key=lambda n: p_1st[n])
    if p_1st[1] >= 0.28:
        top_boat = 1

    # 本線4点（軸艇からのAI確率最上位4点）
    axis_combs = [c for c in prob_120.keys() if c.startswith(f"{top_boat}-")]
    axis_combs.sort(key=lambda c: prob_120[c], reverse=True)
    main_combs = axis_combs[:4]

    # 穴4点（インヒモ荒れ2点 ＋ 逆転波乱2点、オッズ10倍以上、EV降順）
    anas_in = [c for c in prob_120 if c not in main_combs and c.startswith("1-") and odds_table[c] >= 10.0]
    anas_in.sort(key=lambda c: ev_table[c], reverse=True)

    anas_out = [c for c in prob_120 if c not in main_combs and not c.startswith("1-") and odds_table[c] >= 10.0]
    anas_out.sort(key=lambda c: ev_table[c], reverse=True)

    ana_combs = []
    ana_combs.extend(anas_in[:2])
    ana_combs.extend(anas_out[:2])
    if len(ana_combs) < 4:
        rem = [c for c in prob_120 if c not in main_combs and c not in ana_combs and odds_table[c] >= 8.0]
        rem.sort(key=lambda c: ev_table[c], reverse=True)
        ana_combs.extend(rem[:4 - len(ana_combs)])

    def build_desc(comb, is_ana=False):
        c1, c2, c3 = map(int, comb.split("-"))
        n1 = b_map[c1].get("name", f"{c1}号艇")
        n2 = b_map[c2].get("name", f"{c2}号艇")
        p_pct = prob_120[comb] * 100.0
        odds = odds_table[comb]
        ev = ev_table[comb]
        if not is_ana:
            return f"【ML本線】{c1}号艇{n1}軸 ➔ {c2}連対（AI確率{p_pct:.1f}%, EV{ev:.2f}倍）"
        else:
            return f"【ML高期待値穴】{c1}号艇{n1}展開突き ➔ {c2}連動（オッズ{odds:.1f}倍, EV{ev:.2f}）"

    main_bets_raw = [(c, build_desc(c, is_ana=False)) for c in main_combs]
    ana_bets_raw = [(c, build_desc(c, is_ana=True)) for c in ana_combs]

    return {
        "p_1st": p_1st,
        "prob_120": prob_120,
        "odds_table": odds_table,
        "ev_table": ev_table,
        "main_bets_raw": main_bets_raw,
        "ana_bets_raw": ana_bets_raw
    }

if __name__ == "__main__":
    m = get_models()
    print(f"Loaded 3 LightGBM models: win={bool(m[0])}, r2={bool(m[1])}, r3={bool(m[2])}")

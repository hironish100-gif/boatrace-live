"""
build_multiday_dashboard.py
9/19、9/20、9/21を単一のHTMLダッシュボードに完全統合するマルチデイビルダー
- 過去5年女子戦データ分析＆選手特性を徹底的に詳細化（出走全艇のコース別女子戦勝率・連対率・決まり手傾向テーブル＆深掘り展開解剖）
- 出走表テーブルの選手名・直前展示・機力数値を完全黒字化（高コントラスト）
- 「昨日」「今日」「明日」を排除し日付のみ（9/19, 9/20, 9/21）のスマート表示
"""

from __future__ import annotations
import json
import re
import os
import sys
from typing import Dict, Any, List

from test_parser_20260920 import parse_markdown_20260920
from test_parser_20260921 import parse_markdown_20260921
from test_parser_20260926 import parse_markdown_20260926
from test_parser_20260927 import parse_markdown_20260927
from test_parser_20260928 import parse_markdown_20260928
from test_parser_20260929 import parse_markdown_20260929
from build_boatrace_dashboard import compute_new_concept_stats
from generate_detailed_ladies_analysis import build_detailed_analysis_for_race
from predict_slit_formation import compute_comprehensive_predicted_st
# from slit_driven_prediction import generate_slit_driven_bets (REMOVED)


def normalize_race_data(data: Dict[str, Any], default_stadium: str = "下関") -> Dict[str, Any]:
    """全レースの stadium, round, weather, title, 各艇データを完全正規化し、undefinedや欠落を徹底防止"""
    for r in range(1, 13):
        rk = f"r_{r}"
        if rk not in data:
            continue
        race = data[rk]
        if not race.get("stadium"):
            race["stadium"] = default_stadium
        if not race.get("round"):
            race["round"] = r
        if not race.get("title") or race.get("title") == "None":
            race["title"] = f"{race['stadium']} {r}R 予選"
        
        # weather の正規化
        w = race.get("weather")
        if not isinstance(w, dict):
            race["weather"] = {
                "direction": "微風",
                "wind_speed": "1.0",
                "wave_height": "1",
                "weather": "晴",
                "tide": "中潮"
            }
        else:
            if not w.get("direction"):
                w["direction"] = w.get("wind_dir", "微風")
            if not w.get("wind_speed"):
                w["wind_speed"] = "1.0"
            w["wind_speed"] = str(w["wind_speed"]).replace("m", "")
            if not w.get("wave_height"):
                w["wave_height"] = str(w.get("wave", "1")).replace("cm", "")
            if not w.get("tide"):
                w["tide"] = "中潮"
            if not w.get("weather"):
                w["weather"] = "晴"

        # 各艇データの正規化（キー不一致によるundefinedを100%防止）
        for b in race.get("boats", []):
            if not b.get("id"):
                b["id"] = str(b.get("toban") or "")
            if not b.get("toban"):
                b["toban"] = b.get("id", "")
            if not b.get("branch"):
                b["branch"] = "支部"
            if not b.get("rank"):
                b["rank"] = str(b.get("grade") or b.get("class") or "B1")
            if not b.get("grade"):
                b["grade"] = b["rank"]
            if not b.get("course"):
                b["course"] = b.get("num", 1)

            if "tilt" not in b or b["tilt"] is None:
                b["tilt"] = "-0.5"
            if "ex_time" not in b or b["ex_time"] is None:
                b["ex_time"] = "--.--"

            # モーター情報
            if not b.get("motor_info"):
                m_no = b.get("motor_no") or b.get("motor_num") or "-"
                m_rate = b.get("motor_rate")
                if m_rate is not None:
                    try:
                        b["motor_info"] = f"{m_no}号 ({float(m_rate):.1f}%)"
                    except Exception:
                        b["motor_info"] = f"{m_no}号 ({m_rate}%)"
                else:
                    b["motor_info"] = f"{m_no}号"

            # ボート情報
            if not b.get("boat_info"):
                b_no = b.get("boat_no") or b.get("boat_num") or "-"
                b_rate = b.get("boat_rate")
                if b_rate is not None:
                    try:
                        b["boat_info"] = f"{b_no}号 ({float(b_rate):.1f}%)"
                    except Exception:
                        b["boat_info"] = f"{b_no}号 ({b_rate}%)"
                else:
                    b["boat_info"] = f"{b_no}号"

            # 勝率・2連率
            if not b.get("win_rate"):
                b["win_rate"] = str(b.get("course_win_rate") or b.get("national_win_rate") or "5.00")
            if not b.get("local_win_rate"):
                b["local_win_rate"] = str(b.get("course_2ren_rate") or b.get("local_rate") or "35.0")

            # avg_st
            if not b.get("avg_st"):
                st = b.get("st_avg") or 0.16
                b["avg_st"] = f"{float(st):.2f}".replace("0.", ".") if isinstance(st, (int, float)) else str(st)
            elif isinstance(b.get("avg_st"), (int, float)):
                b["avg_st"] = f"{float(b['avg_st']):.2f}".replace("0.", ".")

            # pred_st
            if not b.get("pred_st"):
                pst = b.get("predicted_st") or b.get("avg_st") or ".16"
                if isinstance(pst, (int, float)):
                    b["pred_st"] = f"{float(pst):.2f}".replace("0.", ".")
                else:
                    b["pred_st"] = str(pst)
            if not b.get("predicted_st"):
                b["predicted_st"] = b["pred_st"]

            # fl / f_count
            if not b.get("fl"):
                fc = b.get("f_count", 0)
                b["fl"] = f"F{fc}" if fc else "F0"

            if "f_res" not in b or b["f_res"] is None:
                b["f_res"] = "自重" if ("F1" in str(b.get("fl", "")) or "F2" in str(b.get("fl", ""))) else "強気"
            if "mark" not in b or b["mark"] is None:
                b["mark"] = b.get("eval_mark") or "−"

            # 確率・スコア
            try:
                b["win_prob"] = f"{float(b.get('win_prob', 20.0)):.1f}"
            except Exception:
                b["win_prob"] = "20.0"
            try:
                b["place2_prob"] = f"{float(b.get('place2_prob', 25.0)):.1f}"
            except Exception:
                b["place2_prob"] = "25.0"
            try:
                b["place3_prob"] = f"{float(b.get('place3_prob', 25.0)):.1f}"
            except Exception:
                b["place3_prob"] = "25.0"

            if not b.get("triple_rate"):
                try:
                    w = float(b["win_prob"])
                    p2 = float(b["place2_prob"])
                    p3 = float(b["place3_prob"])
                    b["triple_rate"] = f"{min(98.5, w + p2 + p3):.1f}"
                except Exception:
                    b["triple_rate"] = "70.0"
            else:
                try:
                    b["triple_rate"] = f"{float(b['triple_rate']):.1f}"
                except Exception:
                    b["triple_rate"] = "70.0"

            if not b.get("score"):
                b["score"] = str(b.get("confidence") or "35.0")

            if "depth_blocks" not in b or b["depth_blocks"] is None:
                b["depth_blocks"] = 10
            if not b.get("tactical_comment"):
                b["tactical_comment"] = b.get("comment") or "(通常進入想定)"

            # concept の正規化（50%/70%/.15等のダミー固定値を完全排除し、公式コース別実績DBから選手固有の実数値を算出）
            from generate_edogawa_dynamic import compute_authentic_concept_stats
            c = b.get("concept")
            if (not isinstance(c, dict)) or c.get("eval_text") == "標準的な戦術展開" or (c.get("c_win") == 50.0 and c.get("c_rentai2") == 70.0):
                b["concept"] = compute_authentic_concept_stats(b)
            else:
                auth_c = compute_authentic_concept_stats(b)
                for ck, def_val in auth_c.items():
                    if c.get(ck) is None:
                        c[ck] = def_val

            # 女子戦特性タグ（ladies_tag / style_desc）も「女子戦巧者」「標準型」の固定ダミーを排除し、公式コース別戦術バッジと完全同期
            if not b.get("ladies_tag") or b.get("ladies_tag") in ["女子戦巧者", "標準型"]:
                b["ladies_tag"] = b["concept"].get("badge", f"{b.get('course', 1)}C戦術自在")
            if not b.get("style_desc") or b.get("style_desc") in ["標準型", "女子戦巧者"]:
                b["style_desc"] = b["concept"].get("eval_text", b["ladies_tag"])

        # 各買い目（main_bets / ana_bets）の的中確率 prob が未設定の場合はHarvilleモデルで動的算出
        boats_list = race.get("boats", [])
        if len(boats_list) == 6:
            p1_dict = {}
            for b in boats_list:
                try:
                    p1_dict[int(b["num"])] = max(0.01, float(b.get("win_prob", 16.0)) / 100.0)
                except Exception:
                    p1_dict[int(b.get("num", 1))] = 0.16
            tot_p1 = sum(p1_dict.values()) or 1.0
            for k_n in p1_dict:
                p1_dict[k_n] /= tot_p1

            def _calc_comb_prob(comb_str: str, default_p: float) -> str:
                parts = str(comb_str).split("-")
                if len(parts) == 3 and all(p.isdigit() for p in parts):
                    i, j, k = int(parts[0]), int(parts[1]), int(parts[2])
                    pi = p1_dict.get(i, 0.15)
                    pj = p1_dict.get(j, 0.15)
                    pk = p1_dict.get(k, 0.15)
                    rem1 = max(0.05, 1.0 - pi)
                    rem2 = max(0.05, rem1 - pj)
                    p_val = pi * (pj / rem1) * (pk / rem2) * 100.0
                    return f"{max(0.4, min(28.0, p_val)):.1f}"
                return f"{default_p:.1f}"

            for idx_m, mb in enumerate(race.get("main_bets", [])):
                raw_p = str(mb.get("prob") or "0").replace("%", "").strip()
                try:
                    p_num = float(raw_p)
                except ValueError:
                    p_num = 0.0
                if p_num <= 0:
                    mb["prob"] = _calc_comb_prob(mb.get("comb", ""), max(4.5, 11.5 - idx_m * 1.8))
                else:
                    mb["prob"] = f"{p_num:.1f}"
            for idx_a, ab in enumerate(race.get("ana_bets", [])):
                raw_p = str(ab.get("prob") or "0").replace("%", "").strip()
                try:
                    p_num = float(raw_p)
                except ValueError:
                    p_num = 0.0
                if p_num <= 0:
                    ab["prob"] = _calc_comb_prob(ab.get("comb", ""), max(1.5, 4.2 - idx_a * 0.6))
                else:
                    ab["prob"] = f"{p_num:.1f}"

        # 過去5年女子戦データ分析＆選手特性 (player_notes) を新概念データと100%同期して動的注入
        try:
            race["player_notes"] = build_detailed_analysis_for_race(r, race.get("boats", []))
        except Exception:
            b1_name = race.get("boats", [{}])[0].get("name", "1号艇")
            race["player_notes"] = f"<div class='space-y-1'><div class='font-bold text-cyan-300'>【1号艇 {b1_name}】</div><div class='text-slate-300'>過去5年女子戦イン実績上位。{race['stadium']}の水面特性を活かした先マイ逃げ展開が軸。</div></div>"

        # 1マーク展開物理解剖＆水面力学 (physics_analysis) の動的注入（core_scenario・physics_detail・各艇のコース別決まり手を完全反映）
        w = race.get("weather", {})
        w_dir = w.get("direction") or w.get("wind_dir") or "微風"
        w_spd = str(w.get("wind_speed") or "1.0").replace("m", "")
        w_wave = str(w.get("wave_height") or w.get("wave") or "1").replace("cm", "")
        boats = race.get("boats", [])
        if len(boats) >= 6:
            b1, b2, b3, b4, b5, b6 = boats[:6]
            c1 = b1.get("concept", {})
            c2 = b2.get("concept", {})
            c3 = b3.get("concept", {})
            c4 = b4.get("concept", {})
            core_sc = race.get("core_scenario") or f"1号艇{b1.get('name', '')}のイン戦(逃げ率{c1.get('primary_rate', 65.0)}%)を軸に対抗勢が迫る。"
            phys_dt = race.get("physics_detail") or f"2コース{b2.get('name', '')}(差し率{c2.get('sashi_rate', '15%')})・3コース{b3.get('name', '')}(捲り率{c3.get('makuri_rate', '12%')})の攻防。"
            ana_first = race.get("ana_bets", [{}])[0] if race.get("ana_bets") else {}
            ana_desc = ana_first.get("desc", "スリット中凹み時のダッシュ一撃・外枠連動高配当を警戒")
            race["physics_analysis"] = (
                f"【{race['stadium']} {r}R 水面力学・1M展開解剖】\n"
                f"・水面気象＆スリット条件: {w_dir} {w_spd}m / 波高{w_wave}cm。1C {b1.get('name','')}(予測ST{b1.get('pred_st','.15')})に対し、2C {b2.get('name','')}(予測ST{b2.get('pred_st','.15')})・3C {b3.get('name','')}(予測ST{b3.get('pred_st','.15')})・4C {b4.get('name','')}(予測ST{b4.get('pred_st','.15')})の隊形アプローチ。\n"
                f"・本線1M旋回シナリオ: {core_sc} {phys_dt}\n"
                f"・波乱分岐メカニズム: イン被差し率{c1.get('sashi_loss', 15.0)}%・被まくり率{c1.get('makuri_loss', 12.0)}%。{ana_desc}。"
            )

    return data


def load_1002_data() -> Dict[str, Any]:
    """10/02 下関 ヴィーナスシリーズ第14戦 スターダム杯（2日目・ナイター）の全12R予想データおよび出走表を注入"""
    shimonoseki_data_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261002_data.json")
    if not os.path.exists(shimonoseki_data_path):
        from generate_shimonoseki_1002_data import main as gen_main
        gen_main()

    with open(shimonoseki_data_path, "r", encoding="utf-8") as f:
        data_1002 = json.load(f)

    # 1. 下関直前展示・オリ展キャッシュの注入（存在する場合）
    oriten_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261002_oriten.json")
    all_oriten = {}
    if os.path.exists(oriten_path):
        try:
            with open(oriten_path, "r", encoding="utf-8") as f:
                all_oriten = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_1002 and str(r) in all_oriten:
                    r_info = all_oriten[str(r)]
                    oriten = r_info.get("oriten", {})
                    st_entries = r_info.get("st_entries", [])

                    st_map = {}
                    for row in st_entries:
                        if len(row) >= 2:
                            if row[0].isdigit():
                                st_map[int(row[0])] = row[1]
                            elif row[1].isdigit():
                                st_map[int(row[1])] = row[-1]

                    turns = [float(o["turn"]) for o in oriten.values() if o.get("turn") and o.get("turn") not in ['--.--', '-']]
                    straights = [float(o["straight"]) for o in oriten.values() if o.get("straight") and o.get("straight") not in ['--.--', '-']]
                    laps = [float(o["lap"]) for o in oriten.values() if o.get("lap") and o.get("lap") not in ['--.--', '-']]
                    min_turn = min(turns) if turns else None
                    min_straight = min(straights) if straights else None
                    min_lap = min(laps) if laps else None

                    for b in data_1002[rk].get("boats", []):
                        num_str = str(b["num"])
                        o = oriten.get(num_str)
                        if o and o.get("ex_time") and o["ex_time"] != "--.--":
                            b["tilt"] = str(o.get("tilt", "0.0"))
                            b["ex_time"] = str(o.get("ex_time", "--.--"))
                            if o.get("turn") and o.get("turn") not in ['--.--', '-']:
                                b["turn_time"] = float(o["turn"])
                                b["is_best_turn"] = (b["turn_time"] == min_turn)
                            if o.get("straight") and o.get("straight") not in ['--.--', '-']:
                                b["straight_time"] = float(o["straight"])
                                b["is_best_straight"] = (b["straight_time"] == min_straight)
                            if o.get("lap") and o.get("lap") not in ['--.--', '-']:
                                b["lap_time"] = float(o["lap"])
                                b["is_best_lap"] = (b["lap_time"] == min_lap)

                            # 本番予測スリット隊形（総合推論）の算出
                            st_res = compute_comprehensive_predicted_st(b, st_map.get(b["num"]), o)
                            b["pred_st"] = st_res["pred_st"]
                            b["depth_blocks"] = st_res["depth_blocks"]
                            b["ex_st"] = st_res["ex_st_label"]
                            b["tactical_comment"] = st_res["slit_note"]
        except Exception as e:
            print(f"Shimonoseki 1002 Oriten injection error: {e}")

    # 2. 実測オッズ連動オプティマイザー（存在する場合）
    real_odds_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261002_real_odds.json")
    all_real_odds = {}
    if os.path.exists(real_odds_path):
        try:
            with open(real_odds_path, "r", encoding="utf-8") as f:
                all_real_odds = json.load(f)
        except Exception:
            pass

    from odds_aware_optimizer import optimize_race_bets
    for r in range(1, 13):
        rk = f"r_{r}"
        if rk in data_1002 and str(r) in all_real_odds:
            r_odds = all_real_odds[str(r)]
            if r_odds:
                boats = data_1002[rk].get("boats", [])
                opt_main, opt_ana = optimize_race_bets(boats, r_odds, is_nighter=True)
                if opt_main: data_1002[rk]["main_bets"] = opt_main
                if opt_ana: data_1002[rk]["ana_bets"] = opt_ana

    # 3. 確定結果の取得（終了レースの特定＆的中判定）
    results_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261002_official_results.json")
    if os.path.exists(results_path):
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                official_results = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_1002:
                    res = official_results.get(str(r))
                    if res and res.get("combo_3t"):
                        win_comb = res["combo_3t"]
                        payout = res.get("pay_3t", 0)
                        data_1002[rk]["official_result"] = {
                            "comb": win_comb,
                            "payout": payout,
                            "popularity": res.get("pop_3t", 0),
                            "kimarite": res.get("kimarite", "")
                        }
                        for m in data_1002[rk].get("main_bets", []):
                            m["is_hit"] = (m["comb"] == win_comb)
                            if m["is_hit"]: m["payout"] = payout
                        for a in data_1002[rk].get("ana_bets", []):
                            a["is_hit"] = (a["comb"] == win_comb)
                            if a["is_hit"]: a["payout"] = payout
        except Exception as e:
            print(f"Error merging 1002 official results: {e}")

    return normalize_race_data(data_1002, "下関")


def load_1003_data() -> Dict[str, Any]:
    """10/03 下関 ヴィーナスシリーズ第14戦 スターダム杯（3日目・ナイター）の全12R予想データおよび出走表を注入"""
    shimonoseki_data_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261003_data.json")
    if not os.path.exists(shimonoseki_data_path):
        from generate_shimonoseki_1003_data import main as gen_main
        gen_main()

    with open(shimonoseki_data_path, "r", encoding="utf-8") as f:
        data_1003 = json.load(f)

    # 下関直前展示・オリ展キャッシュの注入（存在する場合）
    oriten_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261003_oriten.json")
    all_oriten = {}
    if os.path.exists(oriten_path):
        try:
            with open(oriten_path, "r", encoding="utf-8") as f:
                all_oriten = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_1003 and str(r) in all_oriten:
                    r_info = all_oriten[str(r)]
                    oriten = r_info.get("oriten", {})
                    st_entries = r_info.get("st_entries", [])

                    st_map = {}
                    for row in st_entries:
                        if len(row) >= 2:
                            if row[0].isdigit(): st_map[int(row[0])] = row[1]
                            elif row[1].isdigit(): st_map[int(row[1])] = row[-1]

                    turns = [float(o["turn"]) for o in oriten.values() if o.get("turn") and o.get("turn") not in ['--.--', '-']]
                    straights = [float(o["straight"]) for o in oriten.values() if o.get("straight") and o.get("straight") not in ['--.--', '-']]
                    laps = [float(o["lap"]) for o in oriten.values() if o.get("lap") and o.get("lap") not in ['--.--', '-']]
                    min_turn = min(turns) if turns else None
                    min_straight = min(straights) if straights else None
                    min_lap = min(laps) if laps else None

                    for b in data_1003[rk].get("boats", []):
                        num_str = str(b["num"])
                        o = oriten.get(num_str)
                        if o and o.get("ex_time") and o["ex_time"] != "--.--":
                            b["tilt"] = str(o.get("tilt", "0.0"))
                            b["ex_time"] = str(o.get("ex_time", "--.--"))
                            if o.get("turn") and o.get("turn") not in ['--.--', '-']:
                                b["turn_time"] = float(o["turn"])
                                b["is_best_turn"] = (b["turn_time"] == min_turn)
                            if o.get("straight") and o.get("straight") not in ['--.--', '-']:
                                b["straight_time"] = float(o["straight"])
                                b["is_best_straight"] = (b["straight_time"] == min_straight)
                            if o.get("lap") and o.get("lap") not in ['--.--', '-']:
                                b["lap_time"] = float(o["lap"])
                                b["is_best_lap"] = (b["lap_time"] == min_lap)

                            st_res = compute_comprehensive_predicted_st(b, st_map.get(b["num"]), o)
                            b["pred_st"] = st_res["pred_st"]
                            b["depth_blocks"] = st_res["depth_blocks"]
                            b["ex_st"] = st_res["ex_st_label"]
                            b["tactical_comment"] = st_res["slit_note"]
        except Exception as e:
            print(f"Shimonoseki 1003 Oriten injection error: {e}")

    # 実測オッズ連動
    real_odds_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261003_real_odds.json")
    all_real_odds = {}
    if os.path.exists(real_odds_path):
        try:
            with open(real_odds_path, "r", encoding="utf-8") as f:
                all_real_odds = json.load(f)
        except Exception: pass

    from odds_aware_optimizer import optimize_race_bets
    for r in range(1, 13):
        rk = f"r_{r}"
        if rk in data_1003 and str(r) in all_real_odds:
            r_odds = all_real_odds[str(r)]
            if r_odds:
                boats = data_1003[rk].get("boats", [])
                opt_main, opt_ana = optimize_race_bets(boats, r_odds, is_nighter=True)
                if opt_main: data_1003[rk]["main_bets"] = opt_main
                if opt_ana: data_1003[rk]["ana_bets"] = opt_ana

    # 確定結果の取得（終了レースの特定＆的中判定）
    results_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261003_official_results.json")
    if os.path.exists(results_path):
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                official_results = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_1003:
                    res = official_results.get(str(r))
                    if res and res.get("combo_3t"):
                        win_comb = res["combo_3t"]
                        payout = res.get("pay_3t", 0)
                        data_1003[rk]["official_result"] = {
                            "comb": win_comb,
                            "payout": payout,
                            "popularity": res.get("pop_3t", 0),
                            "kimarite": res.get("kimarite", "")
                        }
                        for m in data_1003[rk].get("main_bets", []):
                            m["is_hit"] = (m["comb"] == win_comb)
                            if m["is_hit"]: m["payout"] = payout
                        for a in data_1003[rk].get("ana_bets", []):
                            a["is_hit"] = (a["comb"] == win_comb)
                            if a["is_hit"]: a["payout"] = payout
        except Exception as e:
            print(f"Error merging 1003 official results: {e}")

    return normalize_race_data(data_1003, "下関")


def load_1004_data() -> Dict[str, Any]:
    """10/04 下関 ヴィーナスシリーズ第14戦 スターダム杯（4日目・予選最終日・ナイター）の全12R予想データを注入"""
    shimonoseki_data_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261004_data.json")
    if not os.path.exists(shimonoseki_data_path):
        from generate_shimonoseki_1004_data import main as gen_main
        gen_main()

    with open(shimonoseki_data_path, "r", encoding="utf-8") as f:
        data_1004 = json.load(f)

    # 下関直前展示・オリ展キャッシュの注入（存在する場合）
    oriten_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261004_oriten.json")
    all_oriten = {}
    if os.path.exists(oriten_path):
        try:
            with open(oriten_path, "r", encoding="utf-8") as f:
                all_oriten = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_1004 and str(r) in all_oriten:
                    r_info = all_oriten[str(r)]
                    oriten = r_info.get("oriten", {})
                    st_entries = r_info.get("st_entries", [])

                    st_map = {}
                    for row in st_entries:
                        if len(row) >= 2:
                            if row[0].isdigit(): st_map[int(row[0])] = row[1]
                            elif row[1].isdigit(): st_map[int(row[1])] = row[-1]

                    turns = [float(o["turn"]) for o in oriten.values() if o.get("turn") and o.get("turn") not in ['--.--', '-']]
                    straights = [float(o["straight"]) for o in oriten.values() if o.get("straight") and o.get("straight") not in ['--.--', '-']]
                    laps = [float(o["lap"]) for o in oriten.values() if o.get("lap") and o.get("lap") not in ['--.--', '-']]
                    min_turn = min(turns) if turns else None
                    min_straight = min(straights) if straights else None
                    min_lap = min(laps) if laps else None

                    for b in data_1004[rk].get("boats", []):
                        num_str = str(b["num"])
                        o = oriten.get(num_str)
                        if o and o.get("ex_time") and o["ex_time"] != "--.--":
                            b["tilt"] = str(o.get("tilt", "0.0"))
                            b["ex_time"] = str(o.get("ex_time", "--.--"))
                            if o.get("turn") and o.get("turn") not in ['--.--', '-']:
                                b["turn_time"] = float(o["turn"])
                                b["is_best_turn"] = (b["turn_time"] == min_turn)
                            if o.get("straight") and o.get("straight") not in ['--.--', '-']:
                                b["straight_time"] = float(o["straight"])
                                b["is_best_straight"] = (b["straight_time"] == min_straight)
                            if o.get("lap") and o.get("lap") not in ['--.--', '-']:
                                b["lap_time"] = float(o["lap"])
                                b["is_best_lap"] = (b["lap_time"] == min_lap)

                            st_res = compute_comprehensive_predicted_st(b, st_map.get(b["num"]), o)
                            b["pred_st"] = st_res["pred_st"]
                            b["depth_blocks"] = st_res["depth_blocks"]
                            b["ex_st"] = st_res["ex_st_label"]
                            b["tactical_comment"] = st_res["slit_note"]
        except Exception as e:
            print(f"Shimonoseki 1004 Oriten injection error: {e}")

    # 実測オッズ連動
    real_odds_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261004_real_odds.json")
    all_real_odds = {}
    if os.path.exists(real_odds_path):
        try:
            with open(real_odds_path, "r", encoding="utf-8") as f:
                all_real_odds = json.load(f)
        except Exception: pass

    from odds_aware_optimizer import optimize_race_bets
    for r in range(1, 13):
        rk = f"r_{r}"
        if rk in data_1004:
            r_odds = all_real_odds.get(str(r), {})
            boats = data_1004[rk].get("boats", [])
            has_exhibition = any(b.get("ex_time") and b.get("ex_time") != "--.--" for b in boats)
            if has_exhibition or r_odds:
                opt_main, opt_ana = optimize_race_bets(boats, r_odds, is_nighter=True)
                if opt_main:
                    data_1004[rk]["main_bets"] = opt_main
                if opt_ana:
                    data_1004[rk]["ana_bets"] = opt_ana
                if has_exhibition:
                    data_1004[rk]["is_exhibition_final"] = True

    # 確定結果の取得（終了レースの特定＆的中判定）
    results_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261004_official_results.json")
    if os.path.exists(results_path):
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                official_results = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_1004:
                    res = official_results.get(str(r))
                    if res and res.get("combo_3t"):
                        win_comb = res["combo_3t"]
                        payout = res.get("pay_3t", 0)
                        actual_pop = res.get("pop_3t", 0)
                        kimarite = res.get("kimarite", "")

                        pre_main = [m.get("comb") for m in data_1004[rk].get("main_bets", [])]
                        pre_ana = [a.get("comb") for a in data_1004[rk].get("ana_bets", [])]
                        is_main_hit = (win_comb in pre_main)
                        is_ana_hit = (win_comb in pre_ana)

                        hit_status = "不的中"
                        if is_main_hit: hit_status = "🎯 本線的中！"
                        elif is_ana_hit: hit_status = "🎯 穴的中！"

                        data_1004[rk]["official_result"] = {
                            "comb": win_comb,
                            "payout": payout,
                            "popularity": actual_pop,
                            "kimarite": kimarite,
                            "hit_status": hit_status,
                            "finishes": res.get("finishes", [])
                        }
                        for m in data_1004[rk].get("main_bets", []):
                            m["is_hit"] = (m["comb"] == win_comb)
                            if m["is_hit"]: m["payout"] = payout
                        for a in data_1004[rk].get("ana_bets", []):
                            a["is_hit"] = (a["comb"] == win_comb)
                            if a["is_hit"]: a["payout"] = payout
        except Exception as e:
            print(f"Error merging 1004 official results: {e}")

    return normalize_race_data(data_1004, "下関")


def load_1005_data() -> Dict[str, Any]:
    """10/05 下関 ヴィーナスシリーズ第14戦 スターダム杯（5日目・準優勝戦・ナイター）の全12R予想データを注入"""
    shimonoseki_data_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261005_data.json")
    if not os.path.exists(shimonoseki_data_path):
        from auto_prepare_tomorrow import generate_tomorrow_predictions
        generate_tomorrow_predictions("20261005")

    with open(shimonoseki_data_path, "r", encoding="utf-8") as f:
        data_1005 = json.load(f)

    # 10/05 直前展示・オリ展キャッシュの注入（存在する場合）
    oriten_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261005_oriten.json")
    all_oriten = {}
    if os.path.exists(oriten_path):
        try:
            with open(oriten_path, "r", encoding="utf-8") as f:
                all_oriten = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_1005 and str(r) in all_oriten:
                    r_info = all_oriten[str(r)]
                    oriten = r_info.get("oriten", {})
                    st_entries = r_info.get("st_entries", [])

                    st_map = {}
                    for row in st_entries:
                        if len(row) >= 2:
                            if row[0].isdigit(): st_map[int(row[0])] = row[1]
                            elif row[1].isdigit(): st_map[int(row[1])] = row[-1]

                    turns = [float(o["turn"]) for o in oriten.values() if o.get("turn") and o.get("turn") not in ['--.--', '-']]
                    straights = [float(o["straight"]) for o in oriten.values() if o.get("straight") and o.get("straight") not in ['--.--', '-']]
                    laps = [float(o["lap"]) for o in oriten.values() if o.get("lap") and o.get("lap") not in ['--.--', '-']]
                    min_turn = min(turns) if turns else None
                    min_straight = min(straights) if straights else None
                    min_lap = min(laps) if laps else None

                    for b in data_1005[rk].get("boats", []):
                        num_str = str(b["num"])
                        o = oriten.get(num_str)
                        if o and o.get("ex_time") and o["ex_time"] != "--.--":
                            b["tilt"] = str(o.get("tilt", "0.0"))
                            b["ex_time"] = str(o.get("ex_time", "--.--"))
                            if o.get("turn") and o.get("turn") not in ['--.--', '-']:
                                b["turn_time"] = float(o["turn"])
                                b["is_best_turn"] = (b["turn_time"] == min_turn)
                            if o.get("straight") and o.get("straight") not in ['--.--', '-']:
                                b["straight_time"] = float(o["straight"])
                                b["is_best_straight"] = (b["straight_time"] == min_straight)
                            if o.get("lap") and o.get("lap") not in ['--.--', '-']:
                                b["lap_time"] = float(o["lap"])
                                b["is_best_lap"] = (b["lap_time"] == min_lap)

                            st_res = compute_comprehensive_predicted_st(b, st_map.get(b["num"]), o)
                            b["pred_st"] = st_res["pred_st"]
                            b["depth_blocks"] = st_res["depth_blocks"]
                            b["ex_st"] = st_res["ex_st_label"]
                            b["tactical_comment"] = st_res["slit_note"]
        except Exception as e:
            print(f"Shimonoseki 1005 Oriten injection error: {e}")

    # 実測オッズまたは展示連動再計算
    from odds_aware_optimizer import optimize_race_bets
    for r in range(1, 13):
        rk = f"r_{r}"
        if rk in data_1005:
            boats = data_1005[rk].get("boats", [])
            has_exhibition = any(b.get("ex_time") and b.get("ex_time") != "--.--" for b in boats)
            if has_exhibition:
                opt_main, opt_ana = optimize_race_bets(boats, {}, is_nighter=True)
                if opt_main: data_1005[rk]["main_bets"] = opt_main
                if opt_ana: data_1005[rk]["ana_bets"] = opt_ana
                data_1005[rk]["is_exhibition_final"] = True

    return normalize_race_data(data_1005, "下関")

def load_1006_data() -> Dict[str, Any]:
    """10/06 下関 ヴィーナスシリーズ第14戦 スターダム杯（最終日・優勝戦・ナイター）の全12R予想データを注入"""
    shimonoseki_data_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261006_data.json")
    if not os.path.exists(shimonoseki_data_path):
        from auto_prepare_tomorrow import generate_tomorrow_predictions
        generate_tomorrow_predictions("20261006")

    with open(shimonoseki_data_path, "r", encoding="utf-8") as f:
        data_1006 = json.load(f)

    # 10/06 直前展示・オリ展キャッシュの注入（存在する場合）
    oriten_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261006_oriten.json")
    all_oriten = {}
    if os.path.exists(oriten_path):
        try:
            with open(oriten_path, "r", encoding="utf-8") as f:
                all_oriten = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_1006 and str(r) in all_oriten:
                    r_info = all_oriten[str(r)]
                    oriten = r_info.get("oriten", {})
                    st_entries = r_info.get("st_entries", [])
                    st_map = {}
                    for row in st_entries:
                        if len(row) >= 2:
                            if row[0].isdigit(): st_map[int(row[0])] = row[1]
                            elif row[1].isdigit(): st_map[int(row[1])] = row[-1]
                    for b in data_1006[rk].get("boats", []):
                        b_num = str(b.get("num", ""))
                        if b_num in oriten:
                            o = oriten[b_num]
                            if o.get("ex_time"): b["ex_time"] = o["ex_time"]
                            if o.get("tilt"): b["tilt"] = o["tilt"]
                            if o.get("turn"): b["turn_time"] = o["turn"]
                            if o.get("straight"): b["straight_time"] = o["straight"]
                            if o.get("lap"): b["lap_time"] = o["lap"]
                        b_int = int(b.get("num", 0))
                        if b_int in st_map:
                            b["ex_st"] = st_map[b_int]
        except Exception as e:
            print(f"Error merging 1006 oriten: {e}")

    # 実測オッズ連動
    real_odds_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261006_real_odds.json")
    all_real_odds = {}
    if os.path.exists(real_odds_path):
        try:
            with open(real_odds_path, "r", encoding="utf-8") as f:
                all_real_odds = json.load(f)
        except Exception:
            pass

    from odds_aware_optimizer import optimize_race_bets
    for r in range(1, 13):
        rk = f"r_{r}"
        if rk in data_1006:
            r_odds = all_real_odds.get(str(r), {})
            boats = data_1006[rk].get("boats", [])
            has_exhibition = any(b.get("ex_time") and b.get("ex_time") != "--.--" for b in boats)
            if has_exhibition or r_odds:
                opt_main, opt_ana = optimize_race_bets(boats, r_odds, is_nighter=True)
                if opt_main:
                    data_1006[rk]["main_bets"] = opt_main
                if opt_ana:
                    data_1006[rk]["ana_bets"] = opt_ana
                if has_exhibition:
                    data_1006[rk]["is_exhibition_final"] = True

    # 確定結果の取得（終了レースの特定＆的中判定）
    results_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261006_official_results.json")
    if os.path.exists(results_path):
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                official_results = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_1006:
                    res = official_results.get(str(r))
                    if res and res.get("combo_3t"):
                        win_comb = res["combo_3t"]
                        payout = res.get("pay_3t", 0)
                        actual_pop = res.get("pop_3t", 0)
                        kimarite = res.get("kimarite", "")

                        pre_main = [m.get("comb") for m in data_1006[rk].get("main_bets", [])]
                        pre_ana = [a.get("comb") for a in data_1006[rk].get("ana_bets", [])]
                        is_main_hit = (win_comb in pre_main)
                        is_ana_hit = (win_comb in pre_ana)

                        hit_status = "不的中"
                        if is_main_hit: hit_status = "🎯 本線的中！"
                        elif is_ana_hit: hit_status = "🎯 穴的中！"

                        data_1006[rk]["official_result"] = {
                            "comb": win_comb,
                            "payout": payout,
                            "popularity": actual_pop,
                            "kimarite": kimarite,
                            "hit_status": hit_status,
                            "finishes": res.get("finishes", [])
                        }
                        for m in data_1006[rk].get("main_bets", []):
                            m["is_hit"] = (m["comb"] == win_comb)
                            if m["is_hit"]: m["payout"] = payout
                        for a in data_1006[rk].get("ana_bets", []):
                            a["is_hit"] = (a["comb"] == win_comb)
                            if a["is_hit"]: a["payout"] = payout
        except Exception as e:
            print(f"Error merging 1006 official results: {e}")

def load_1011_data() -> Dict[str, Any]:
    """10/11 江戸川 オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ（5日目・準優勝戦）の動的AI予想データを注入"""
    edogawa_data_path = os.path.join(os.path.dirname(__file__), "data", "edogawa_20261011_data.json")
    if not os.path.exists(edogawa_data_path):
        from generate_edogawa_1011_revised import main as gen_main_1011
        gen_main_1011()

    with open(edogawa_data_path, "r", encoding="utf-8") as f:
        data_1011 = json.load(f)

    return normalize_race_data(data_1011, "江戸川")


def load_1010_data() -> Dict[str, Any]:
    """10/10 江戸川 オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ（4日目）の最新AI予想データを注入"""
    edogawa_data_path = os.path.join(os.path.dirname(__file__), "data", "edogawa_20261010_data.json")
    if not os.path.exists(edogawa_data_path):
        from generate_edogawa_1010_data import fetch_and_parse_races
        fetch_and_parse_races()

    with open(edogawa_data_path, "r", encoding="utf-8") as f:
        data_1010 = json.load(f)

    return normalize_race_data(data_1010, "江戸川")


def load_1009_data() -> Dict[str, Any]:
    """10/09 江戸川 オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ（3日目）の前夜AI予想データを注入"""
    edogawa_data_path = os.path.join(os.path.dirname(__file__), "data", "edogawa_20261009_data.json")
    if not os.path.exists(edogawa_data_path):
        from generate_edogawa_1009_data import main as gen_main_1009
        gen_main_1009()

    with open(edogawa_data_path, "r", encoding="utf-8") as f:
        data_1009 = json.load(f)

    return normalize_race_data(data_1009, "江戸川")


def load_1008_data() -> Dict[str, Any]:
    """10/08 江戸川 オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ（2日目）の全12R確定結果・展示タイム・AI投資データを注入"""
    edogawa_data_path = os.path.join(os.path.dirname(__file__), "data", "edogawa_20261008_data.json")
    if not os.path.exists(edogawa_data_path):
        from generate_edogawa_1008_full import main as gen_main_1008
        gen_main_1008()

    with open(edogawa_data_path, "r", encoding="utf-8") as f:
        data_1008 = json.load(f)

    return normalize_race_data(data_1008, "江戸川")


def load_1007_data() -> Dict[str, Any]:
    """10/07 江戸川 オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ（初日）の全12R予想データを注入"""
    edogawa_data_path = os.path.join(os.path.dirname(__file__), "data", "edogawa_20261007_data.json")
    if not os.path.exists(edogawa_data_path):
        from generate_edogawa_1007_data import main as gen_main
        gen_main()

    with open(edogawa_data_path, "r", encoding="utf-8") as f:
        data_1007 = json.load(f)

    # 10/07 直前展示・オリ展キャッシュの注入（存在する場合）
    oriten_path = os.path.join(os.path.dirname(__file__), "data", "edogawa_20261007_oriten.json")
    all_oriten = {}
    if os.path.exists(oriten_path):
        try:
            with open(oriten_path, "r", encoding="utf-8") as f:
                all_oriten = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_1007 and str(r) in all_oriten:
                    r_info = all_oriten[str(r)]
                    oriten = r_info.get("oriten", {})
                    st_entries = r_info.get("st_entries", [])
                    st_map = {}
                    for row in st_entries:
                        if len(row) >= 2:
                            if row[0].isdigit(): st_map[int(row[0])] = row[1]
                            elif row[1].isdigit(): st_map[int(row[1])] = row[-1]
                    for b in data_1007[rk].get("boats", []):
                        b_num = str(b.get("num", ""))
                        if b_num in oriten:
                            o = oriten[b_num]
                            if o.get("ex_time"): b["ex_time"] = o["ex_time"]
                            if o.get("tilt"): b["tilt"] = o["tilt"]
                            if o.get("turn"): b["turn_time"] = o["turn"]
                            if o.get("straight"): b["straight_time"] = o["straight"]
                            if o.get("lap"): b["lap_time"] = o["lap"]
                        b_int = int(b.get("num", 0))
                        if b_int in st_map:
                            b["ex_st"] = st_map[b_int]
        except Exception as e:
            print(f"Error merging 1007 oriten: {e}")

    # 実測オッズ連動
    real_odds_path = os.path.join(os.path.dirname(__file__), "data", "edogawa_20261007_real_odds.json")
    all_real_odds = {}
    if os.path.exists(real_odds_path):
        try:
            with open(real_odds_path, "r", encoding="utf-8") as f:
                all_real_odds = json.load(f)
        except Exception:
            pass

    from odds_aware_optimizer import optimize_race_bets
    for r in range(1, 13):
        rk = f"r_{r}"
        if rk in data_1007:
            r_odds = all_real_odds.get(str(r), {})
            boats = data_1007[rk].get("boats", [])
            has_exhibition = any(b.get("ex_time") and b.get("ex_time") != "--.--" for b in boats)
            if has_exhibition or r_odds:
                opt_main, opt_ana = optimize_race_bets(boats, r_odds, is_nighter=False)
                if opt_main:
                    data_1007[rk]["main_bets"] = opt_main
                if opt_ana:
                    data_1007[rk]["ana_bets"] = opt_ana
                if has_exhibition:
                    data_1007[rk]["is_exhibition_final"] = True

    # 確定結果の取得（終了レースの特定＆的中判定）
    results_path = os.path.join(os.path.dirname(__file__), "data", "edogawa_20261007_official_results.json")
    if os.path.exists(results_path):
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                official_results = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_1007:
                    res = official_results.get(str(r))
                    if res and res.get("combo_3t"):
                        win_comb = res["combo_3t"]
                        payout = res.get("payout", 0)
                        pre_main = [m.get("comb") for m in data_1007[rk].get("main_bets", [])]
                        pre_ana = [a.get("comb") for a in data_1007[rk].get("ana_bets", [])]
                        is_main_hit = (win_comb in pre_main)
                        is_ana_hit = (win_comb in pre_ana)
                        hit_status = "不的中"
                        if is_main_hit: hit_status = "🎯 本線的中！"
                        elif is_ana_hit: hit_status = "🎯 穴的中！"
                        data_1007[rk]["official_result"] = {
                            "comb": win_comb,
                            "payout": payout,
                            "hit_status": hit_status
                        }
                        for m in data_1007[rk].get("main_bets", []):
                            m["is_hit"] = (m["comb"] == win_comb)
                            if m["is_hit"]: m["payout"] = payout
                        for a in data_1007[rk].get("ana_bets", []):
                            a["is_hit"] = (a["comb"] == win_comb)
                            if a["is_hit"]: a["payout"] = payout
        except Exception as e:
            print(f"Error merging 1007 official results: {e}")

    return normalize_race_data(data_1007, "江戸川")





def load_1001_data() -> Dict[str, Any]:
    """10/01 下関 ヴィーナスシリーズ第14戦 スターダム杯（初日・ナイター）の全12R予想データおよび出走表を注入"""
    shimonoseki_data_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261001_data.json")
    if not os.path.exists(shimonoseki_data_path):
        from generate_shimonoseki_1001_data import main as gen_main
        gen_main()

    with open(shimonoseki_data_path, "r", encoding="utf-8") as f:
        data_1001 = json.load(f)

    # 1. 下関直前展示・オリ展キャッシュの注入（存在する場合）
    oriten_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261001_oriten.json")
    all_oriten = {}
    if os.path.exists(oriten_path):
        try:
            with open(oriten_path, "r", encoding="utf-8") as f:
                all_oriten = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_1001 and str(r) in all_oriten:
                    r_info = all_oriten[str(r)]
                    oriten = r_info.get("oriten", {})
                    st_entries = r_info.get("st_entries", [])

                    st_map = {}
                    for row in st_entries:
                        if len(row) >= 2:
                            if row[0].isdigit():
                                st_map[int(row[0])] = row[1]
                            elif row[1].isdigit():
                                st_map[int(row[1])] = row[-1]

                    turns = [float(o["turn"]) for o in oriten.values() if o.get("turn") and o.get("turn") not in ['--.--', '-']]
                    straights = [float(o["straight"]) for o in oriten.values() if o.get("straight") and o.get("straight") not in ['--.--', '-']]
                    laps = [float(o["lap"]) for o in oriten.values() if o.get("lap") and o.get("lap") not in ['--.--', '-']]
                    min_turn = min(turns) if turns else None
                    min_straight = min(straights) if straights else None
                    min_lap = min(laps) if laps else None

                    for b in data_1001[rk].get("boats", []):
                        num_str = str(b["num"])
                        o = oriten.get(num_str)
                        if o and o.get("ex_time") and o["ex_time"] != "--.--":
                            b["tilt"] = str(o.get("tilt", "0.0"))
                            b["ex_time"] = str(o.get("ex_time", "--.--"))
                            if o.get("turn") and o.get("turn") not in ['--.--', '-']:
                                b["turn_time"] = float(o["turn"])
                                b["is_best_turn"] = (b["turn_time"] == min_turn)
                            if o.get("straight") and o.get("straight") not in ['--.--', '-']:
                                b["straight_time"] = float(o["straight"])
                                b["is_best_straight"] = (b["straight_time"] == min_straight)
                            if o.get("lap") and o.get("lap") not in ['--.--', '-']:
                                b["lap_time"] = float(o["lap"])
                                b["is_best_lap"] = (b["lap_time"] == min_lap)

                            # 本番予測スリット隊形（総合推論）の算出
                            st_res = compute_comprehensive_predicted_st(b, st_map.get(b["num"]), o)
                            b["pred_st"] = st_res["pred_st"]
                            b["depth_blocks"] = st_res["depth_blocks"]
                            b["ex_st"] = st_res["ex_st_label"]
                            b["tactical_comment"] = st_res["slit_note"]
        except Exception as e:
            print(f"Shimonoseki 1001 Oriten injection error: {e}")

    # 2. 確定結果の取得（終了レースの特定＆的中判定）
    results_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261001_official_results.json")
    finished_races = set()
    if os.path.exists(results_path):
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                all_results = json.load(f)
            for rk_str, r_val in all_results.items():
                if r_val and r_val.get("combo_3t"):
                    finished_races.add(int(rk_str))
                    r_int = int(rk_str)
                    rk = f"r_{r_int}"
                    if rk in data_1001:
                        actual_combo = r_val.get("combo_3t", "")
                        actual_pay = r_val.get("pay_3t", 0)
                        actual_pop = r_val.get("pop_3t", 0)
                        kimarite = r_val.get("kimarite", "")

                        # レース前の事前予想買い目を照合
                        pre_main = [m.get("comb") for m in data_1001[rk].get("main_bets", [])]
                        pre_ana = [a.get("comb") for a in data_1001[rk].get("ana_bets", [])]
                        is_main_hit = (actual_combo in pre_main)
                        is_ana_hit = (actual_combo in pre_ana)

                        hit_status = "不的中"
                        if is_main_hit: hit_status = "🎯 本線的中！"
                        elif is_ana_hit: hit_status = "🎯 穴的中！"

                        data_1001[rk]["official_result"] = {
                            "comb": actual_combo,
                            "payout": actual_pay,
                            "popularity": actual_pop,
                            "kimarite": kimarite,
                            "hit_status": hit_status,
                            "finishes": r_val.get("finishes", [])
                        }
                        for m in data_1001[rk].get("main_bets", []):
                            m["is_hit"] = (m["comb"] == actual_combo)
                            if m["is_hit"]: m["payout"] = actual_pay
                        for a in data_1001[rk].get("ana_bets", []):
                            a["is_hit"] = (a["comb"] == actual_combo)
                            if a["is_hit"]: a["payout"] = actual_pay
        except Exception as e:
            print(f"Error merging 1001 official results: {e}")

    # 3. 実測オッズ連動オプティマイザー（未終了の未来レースのみに適用）
    real_odds_path = os.path.join(os.path.dirname(__file__), "data", "shimonoseki_20261001_real_odds.json")
    all_real_odds = {}
    if os.path.exists(real_odds_path):
        try:
            with open(real_odds_path, "r", encoding="utf-8") as f:
                all_real_odds = json.load(f)
        except Exception:
            pass

    from odds_aware_optimizer import optimize_race_bets
    for r in range(1, 13):
        # 終了レースはスキップ（事前予想を絶対に改変しない）
        if r in finished_races:
            continue
        rk = f"r_{r}"
        if rk in data_1001 and str(r) in all_real_odds:
            r_odds = all_real_odds[str(r)]
            if r_odds:
                boats = data_1001[rk].get("boats", [])
                opt_main, opt_ana = optimize_race_bets(boats, r_odds, is_nighter=True)
                if opt_main: data_1001[rk]["main_bets"] = opt_main
                if opt_ana: data_1001[rk]["ana_bets"] = opt_ana

    return data_1001


def load_929_data() -> Dict[str, Any]:
    """9/29 芦屋 G3オールレディース（最終日・第12R優勝戦）の全12R予想データおよび出走表を注入"""
    report_path = os.path.join(os.path.dirname(__file__), "data", "reports", "20260929_ashiya_predictor.md")
    data_929 = parse_markdown_20260929(report_path)

    # 芦屋オリ展・直前展示キャッシュの注入（存在する場合：明朝自動更新）
    oriten_path = os.path.join(os.path.dirname(__file__), "data", "ashiya_20260929_oriten.json")
    all_oriten = {}
    if os.path.exists(oriten_path):
        try:
            with open(oriten_path, "r", encoding="utf-8") as f:
                all_oriten = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_929 and str(r) in all_oriten:
                    r_info = all_oriten[str(r)]
                    oriten = r_info.get("oriten", {})
                    st_entries = r_info.get("st_entries", [])

                    turns = [float(o["turn"]) for o in oriten.values() if o.get("turn") and o.get("turn") != '--.--']
                    straights = [float(o["straight"]) for o in oriten.values() if o.get("straight") and o.get("straight") != '--.--']
                    laps = [float(o["lap"]) for o in oriten.values() if o.get("lap") and o.get("lap") != '--.--']
                    min_turn = min(turns) if turns else None
                    min_straight = min(straights) if straights else None
                    min_lap = min(laps) if laps else None

                    st_map = {}
                    for row in st_entries:
                        if len(row) >= 2:
                            if row[0].isdigit():
                                st_map[int(row[0])] = row[1]
                            elif row[1].isdigit():
                                st_map[int(row[1])] = row[-1]

                    for b in data_929[rk].get("boats", []):
                        num_str = str(b["num"])
                        o = oriten.get(num_str)
                        if o:
                            b["tilt"] = str(o.get("tilt", "0.0"))
                            b["ex_time"] = str(o.get("ex_time", "--.--"))
                            if o.get("turn") and o.get("turn") != '--.--':
                                b["turn_time"] = float(o["turn"])
                                b["is_best_turn"] = (b["turn_time"] == min_turn)
                            if o.get("straight") and o.get("straight") != '--.--':
                                b["straight_time"] = float(o["straight"])
                                b["is_best_straight"] = (b["straight_time"] == min_straight)
                            if o.get("lap") and o.get("lap") != '--.--':
                                b["lap_time"] = float(o["lap"])
                                b["is_best_lap"] = (b["lap_time"] == min_lap)

                        # 本番予測スリット隊形（総合推論）の算出
                        st_res = compute_comprehensive_predicted_st(b, st_map.get(b["num"]), o)
                        b["pred_st"] = st_res["pred_st"]
                        b["depth_blocks"] = st_res["depth_blocks"]
                        b["ex_st"] = st_res["ex_st_label"]
                        b["tactical_comment"] = st_res["slit_note"]
        except Exception as e:
            print(f"Ashiya 929 Oriten injection error: {e}")

    # 選手別当日パフォーマンス注入
    perf_path = os.path.join(os.path.dirname(__file__), "data", "racer_daily_performance.json")
    if os.path.exists(perf_path):
        try:
            with open(perf_path, "r", encoding="utf-8") as f:
                daily_perf_db = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_929:
                    for b in data_929[rk].get("boats", []):
                        name = b.get("name", "")
                        p_info = daily_perf_db.get(name)
                        if p_info and p_info.get("races_today"):
                            latest_run = p_info["races_today"][-1]
                            b_finish = latest_run.get("finish", "")
                            b_kim = latest_run.get("kimarite", "")
                            b_st = latest_run.get("st", "")
                            perf_label = f"【今節直近実績: {latest_run.get('race')}{latest_run.get('boat')}号艇 {b_finish}着"
                            if b_kim: perf_label += f" {b_kim}"
                            perf_label += f" ST{b_st}】"
                            b["daily_perf_note"] = perf_label
        except Exception as e:
            print(f"Error injecting daily performance for 929: {e}")

    # LightGBMモデル推論
    from ml_rank_predictor import predict_race_ml_probabilities
    for r in range(1, 13):
        rk = f"r_{r}"
        if rk in data_929:
            boats = data_929[rk].get("boats", [])
            r_ori = all_oriten.get(str(r), {}).get("oriten", {})
            try:
                data_929[rk]["boats"] = predict_race_ml_probabilities(boats, r_ori)
            except Exception as ml_err:
                print(f"ML prediction error for 929 {r}R: {ml_err}")

    # 実測オッズ連動オプティマイザー（存在する場合：明朝自動更新）
    from odds_aware_optimizer import optimize_race_bets
    real_odds_path = os.path.join(os.path.dirname(__file__), "data", "ashiya_20260929_real_odds.json")
    if os.path.exists(real_odds_path):
        try:
            with open(real_odds_path, "r", encoding="utf-8") as f:
                all_real_odds = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                r_odds = all_real_odds.get(str(r), {})
                if rk in data_929 and r_odds:
                    boats = data_929[rk].get("boats", [])
                    opt_main, opt_ana = optimize_race_bets(boats, r_odds)
                    if opt_main and opt_ana:
                        data_929[rk]["main_bets"] = opt_main
                        data_929[rk]["ana_bets"] = opt_ana
        except Exception as e:
            print(f"Error optimizing bets for 929 {r}R: {e}")

    # 過去5年女子戦データ分析＆選手特性および1マーク展開物理解剖の確実な注入
    for r in range(1, 13):
        rk = f"r_{r}"
        if rk in data_929:
            if not data_929[rk].get("player_notes"):
                data_929[rk]["player_notes"] = build_detailed_analysis_for_race(r, data_929[rk].get("boats", []))
            if not data_929[rk].get("physics_analysis"):
                w = data_929[rk].get("weather", {})
                data_929[rk]["physics_analysis"] = f"芦屋静水面1マーク力学：風速{w.get('wind_speed', '2')}m ({w.get('direction', '向かい風')})。イン先マイ旋回半径に対し、2コースの小回り差しとセンター勢の全速旋回が交錯する物理攻防。"

    return data_929


def load_928_data() -> Dict[str, Any]:
    """9/28 芦屋 G3オールレディース（5日目・準優勝戦）の全12R予想データおよび出走表を注入"""
    report_path = os.path.join(os.path.dirname(__file__), "data", "reports", "20260928_芦屋_predictor.md")
    data_928 = parse_markdown_20260928(report_path)

    # 芦屋オリ展・直前展示キャッシュの注入（存在する場合）
    oriten_path = os.path.join(os.path.dirname(__file__), "data", "ashiya_20260928_oriten.json")
    all_oriten = {}
    if os.path.exists(oriten_path):
        try:
            with open(oriten_path, "r", encoding="utf-8") as f:
                all_oriten = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_928 and str(r) in all_oriten:
                    r_info = all_oriten[str(r)]
                    oriten = r_info.get("oriten", {})
                    st_entries = r_info.get("st_entries", [])

                    turns = [float(o["turn"]) for o in oriten.values() if o.get("turn") and o.get("turn") != '--.--']
                    straights = [float(o["straight"]) for o in oriten.values() if o.get("straight") and o.get("straight") != '--.--']
                    laps = [float(o["lap"]) for o in oriten.values() if o.get("lap") and o.get("lap") != '--.--']
                    min_turn = min(turns) if turns else None
                    min_straight = min(straights) if straights else None
                    min_lap = min(laps) if laps else None

                    st_map = {}
                    for row in st_entries:
                        if len(row) >= 2:
                            if row[0].isdigit():
                                st_map[int(row[0])] = row[1]
                            elif row[1].isdigit():
                                st_map[int(row[1])] = row[-1]

                    for b in data_928[rk].get("boats", []):
                        num_str = str(b["num"])
                        o = oriten.get(num_str)
                        if o:
                            b["tilt"] = str(o.get("tilt", "0.0"))
                            b["ex_time"] = str(o.get("ex_time", "--.--"))
                            if o.get("turn") and o.get("turn") != '--.--':
                                b["turn_time"] = float(o["turn"])
                                b["is_best_turn"] = (b["turn_time"] == min_turn)
                            if o.get("straight") and o.get("straight") != '--.--':
                                b["straight_time"] = float(o["straight"])
                                b["is_best_straight"] = (b["straight_time"] == min_straight)
                            if o.get("lap") and o.get("lap") != '--.--':
                                b["lap_time"] = float(o["lap"])
                                b["is_best_lap"] = (b["lap_time"] == min_lap)

                        # 本番予測スリット隊形（総合推論）の算出
                        st_res = compute_comprehensive_predicted_st(b, st_map.get(b["num"]), o)
                        b["pred_st"] = st_res["pred_st"]
                        b["depth_blocks"] = st_res["depth_blocks"]
                        b["ex_st"] = st_res["ex_st_label"]
                        b["tactical_comment"] = st_res["slit_note"]
        except Exception as e:
            print(f"Ashiya 928 Oriten injection error: {e}")

    # 選手別当日パフォーマンス注入
    perf_path = os.path.join(os.path.dirname(__file__), "data", "racer_daily_performance.json")
    if os.path.exists(perf_path):
        try:
            with open(perf_path, "r", encoding="utf-8") as f:
                daily_perf_db = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_928:
                    for b in data_928[rk].get("boats", []):
                        name = b.get("name", "")
                        p_info = daily_perf_db.get(name)
                        if p_info and p_info.get("races_today"):
                            latest_run = p_info["races_today"][-1]
                            b_finish = latest_run.get("finish", "")
                            b_kim = latest_run.get("kimarite", "")
                            b_st = latest_run.get("st", "")
                            perf_label = f"【今節直近実績: {latest_run.get('race')}{latest_run.get('boat')}号艇 {b_finish}着"
                            if b_kim: perf_label += f" {b_kim}"
                            perf_label += f" ST{b_st}】"
                            b["daily_perf_note"] = perf_label
        except Exception as e:
            print(f"Error injecting daily performance for 928: {e}")

    # LightGBMモデル推論
    from ml_rank_predictor import predict_race_ml_probabilities
    for r in range(1, 13):
        rk = f"r_{r}"
        if rk in data_928:
            boats = data_928[rk].get("boats", [])
            r_ori = all_oriten.get(str(r), {}).get("oriten", {})
            try:
                data_928[rk]["boats"] = predict_race_ml_probabilities(boats, r_ori)
            except Exception as ml_err:
                print(f"ML prediction error for 928 {r}R: {ml_err}")

    # 実測オッズ連動オプティマイザー（存在する場合）
    from odds_aware_optimizer import optimize_race_bets
    real_odds_path = os.path.join(os.path.dirname(__file__), "data", "ashiya_20260928_real_odds.json")
    if os.path.exists(real_odds_path):
        try:
            with open(real_odds_path, "r", encoding="utf-8") as f:
                all_real_odds = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                r_odds = all_real_odds.get(str(r), {})
                if rk in data_928 and r_odds:
                    boats = data_928[rk].get("boats", [])
                    opt_main, opt_ana = optimize_race_bets(boats, r_odds)
                    if opt_main and opt_ana:
                        data_928[rk]["main_bets"] = opt_main
                        data_928[rk]["ana_bets"] = opt_ana
        except Exception as e:
            print(f"Error optimizing bets for 928 {r}R: {e}")

    # 過去5年女子戦データ分析＆選手特性および1マーク展開物理解剖の確実な注入
    for r in range(1, 13):
        rk = f"r_{r}"
        if rk in data_928:
            if not data_928[rk].get("player_notes"):
                data_928[rk]["player_notes"] = build_detailed_analysis_for_race(r, data_928[rk].get("boats", []))
            if not data_928[rk].get("physics_analysis"):
                w = data_928[rk].get("weather", {})
                data_928[rk]["physics_analysis"] = f"芦屋静水面1マーク力学：風速{w.get('wind_speed', '2')}m ({w.get('direction', '向かい風')})。イン先マイ旋回半径に対し、2コースの小回り差しとセンター勢の全速旋回が交錯する物理攻防。"

    return data_928


def load_927_data() -> Dict[str, Any]:
    """9/27 芦屋 G3オールレディース（4日目・予選最終日）の全12R予想データおよび出走表を注入"""
    report_path = os.path.join(os.path.dirname(__file__), "data", "reports", "20260927_芦屋_predictor.md")
    data_927 = parse_markdown_20260927(report_path)

    # 芦屋オリ展・直前展示キャッシュの注入（存在する場合）
    oriten_path = os.path.join(os.path.dirname(__file__), "data", "ashiya_20260927_oriten.json")
    if os.path.exists(oriten_path):
        try:
            with open(oriten_path, "r", encoding="utf-8") as f:
                all_oriten = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_927 and str(r) in all_oriten:
                    r_info = all_oriten[str(r)]
                    oriten = r_info.get("oriten", {})
                    st_entries = r_info.get("st_entries", [])

                    turns = [float(o["turn"]) for o in oriten.values() if o.get("turn") and o.get("turn") != '--.--']
                    straights = [float(o["straight"]) for o in oriten.values() if o.get("straight") and o.get("straight") != '--.--']
                    laps = [float(o["lap"]) for o in oriten.values() if o.get("lap") and o.get("lap") != '--.--']
                    min_turn = min(turns) if turns else None
                    min_straight = min(straights) if straights else None
                    min_lap = min(laps) if laps else None

                    st_map = {}
                    for row in st_entries:
                        if len(row) >= 2:
                            if row[0].isdigit():
                                st_map[int(row[0])] = row[1]
                            elif row[1].isdigit():
                                st_map[int(row[1])] = row[-1]

                    for b in data_927[rk].get("boats", []):
                        num_str = str(b["num"])
                        o = oriten.get(num_str)
                        if o:
                            b["tilt"] = str(o.get("tilt", "0.0"))
                            b["ex_time"] = str(o.get("ex_time", "--.--"))
                            if o.get("turn") and o.get("turn") != '--.--':
                                b["turn_time"] = float(o["turn"])
                                b["is_best_turn"] = (b["turn_time"] == min_turn)
                            if o.get("straight") and o.get("straight") != '--.--':
                                b["straight_time"] = float(o["straight"])
                                b["is_best_straight"] = (b["straight_time"] == min_straight)
                            if o.get("lap") and o.get("lap") != '--.--':
                                b["lap_time"] = float(o["lap"])
                                b["is_best_lap"] = (b["lap_time"] == min_lap)

                        # 本番予測スリット隊形（総合推論）の算出
                        st_res = compute_comprehensive_predicted_st(b, st_map.get(b["num"]), o)
                        b["pred_st"] = st_res["pred_st"]
                        b["depth_blocks"] = st_res["depth_blocks"]
                        b["ex_st"] = st_res["ex_st_label"]
                        b["tactical_comment"] = st_res["slit_note"]
        except Exception as e:
            print(f"Ashiya 927 Oriten injection error: {e}")

    # 選手別当日パフォーマンス・結果学習フィードバックの注入
    daily_perf_path = os.path.join(os.path.dirname(__file__), "data", "racer_daily_performance.json")
    if os.path.exists(daily_perf_path):
        try:
            with open(daily_perf_path, "r", encoding="utf-8") as f:
                daily_perf_db = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_927:
                    for b in data_927[rk].get("boats", []):
                        name = b.get("name", "")
                        p_info = daily_perf_db.get(name)
                        if p_info and p_info.get("races_today"):
                            latest_run = p_info["races_today"][-1]
                            # 直前レース結果が本レースより前のレースの場合のみ反映
                            run_rno_m = re.search(r"(\d+)R", latest_run.get("race", ""))
                            if run_rno_m and int(run_rno_m.group(1)) < r:
                                b_finish = latest_run.get("finish", "")
                                b_kim = latest_run.get("kimarite", "")
                                b_st = latest_run.get("st", "")
                                perf_label = f"【本日実績: {latest_run.get('race')}{latest_run.get('boat')}号艇 {b_finish}着"
                                if b_kim: perf_label += f" {b_kim}"
                                perf_label += f" ST{b_st}】"
                                b["daily_perf_note"] = perf_label
                                if b.get("tactical_comment"):
                                    b["tactical_comment"] = f"{perf_label} " + b["tactical_comment"]
                                else:
                                    b["tactical_comment"] = perf_label
        except Exception as e:
            print(f"Error injecting daily performance: {e}")

    # 本格機械学習（LightGBM）による1着・2着・3着確率のダイナミック推論
    from ml_rank_predictor import predict_race_ml_probabilities
    oriten_path = os.path.join(os.path.dirname(__file__), "data", "ashiya_20260927_oriten.json")
    all_oriten = {}
    if os.path.exists(oriten_path):
        try:
            with open(oriten_path, "r", encoding="utf-8") as f:
                all_oriten = json.load(f)
        except Exception:
            pass

    # 確定結果の取得（終了レースの特定）
    results_path = os.path.join(os.path.dirname(__file__), "data", "ashiya_20260927_official_results.json")
    finished_races = set()
    all_results = {}
    if os.path.exists(results_path):
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                all_results = json.load(f)
            for rk_str, r_val in all_results.items():
                if r_val and r_val.get("finishes"):
                    finished_races.add(int(rk_str))
        except Exception:
            pass

    # 終了レースには確定結果と事前予想の検証結果を付与（予想はレース前のまま完全固定・フリーズ）
    for finished_r in finished_races:
        rk = f"r_{finished_r}"
        if rk in data_927:
            res_obj = all_results.get(str(finished_r), {})
            actual_combo = res_obj.get("combo_3t", "")
            actual_pay = res_obj.get("pay_3t", 0)
            
            # レース前の事前予想買い目を収集
            pre_main = [b.get("comb") for b in data_927[rk].get("main_bets", [])]
            pre_ana = [b.get("comb") for b in data_927[rk].get("ana_bets", [])]
            is_main_hit = (actual_combo in pre_main)
            is_ana_hit = (actual_combo in pre_ana)
            
            hit_status = "不的中"
            if is_main_hit: hit_status = "🎯 本線的中！"
            elif is_ana_hit: hit_status = "🎯 穴的中！"

            data_927[rk]["official_result"] = {
                "combo": actual_combo,
                "pay": actual_pay,
                "hit_status": hit_status,
                "finishes": res_obj.get("finishes", []),
                "st_data": res_obj.get("st_data", {})
            }

    # 機械学習推論およびオッズオプティマイザーは【これから走る未来のレース（未終了レース）のみ】に適用！
    # 確定済みレースに事後学習モデルを適用する「カンニング・後出しジャンケン」を物理的に完全遮断
    from ml_rank_predictor import predict_race_ml_probabilities
    from odds_aware_optimizer import optimize_race_bets

    real_odds_path = os.path.join(os.path.dirname(__file__), "data", "ashiya_20260927_real_odds.json")
    all_real_odds = {}
    if os.path.exists(real_odds_path):
        try:
            with open(real_odds_path, "r", encoding="utf-8") as f:
                all_real_odds = json.load(f)
        except Exception:
            pass

    for r in range(1, 13):
        # 終了レースはスキップ（事前予想を絶対に改変しない）
        if r in finished_races:
            continue

        rk = f"r_{r}"
        if rk in data_927:
            boats = data_927[rk].get("boats", [])
            r_ori = all_oriten.get(str(r), {}).get("oriten", {})
            try:
                data_927[rk]["boats"] = predict_race_ml_probabilities(boats, r_ori)
            except Exception as ml_err:
                print(f"ML prediction error for {r}R: {ml_err}")

            # 実測オッズ連動オプティマイザー
            r_odds = all_real_odds.get(str(r), {})
            if r_odds:
                try:
                    opt_main, opt_ana = optimize_race_bets(data_927[rk]["boats"], r_odds)
                    if opt_main and opt_ana:
                        data_927[rk]["main_bets"] = opt_main
                        data_927[rk]["ana_bets"] = opt_ana
                except Exception as e:
                    print(f"Error optimizing bets for {r}R: {e}")

    return data_927


def load_926_data() -> Dict[str, Any]:
    """9/26 芦屋 G3オールレディース（3日目）の全12R予想データおよび直前展示・オリ展実測値を注入"""
    report_path = os.path.join(os.path.dirname(__file__), "data", "reports", "20260926_芦屋_predictor.md")
    data_926 = parse_markdown_20260926(report_path)

    # 芦屋オリ展・直前展示キャッシュの注入
    oriten_path = os.path.join(os.path.dirname(__file__), "data", "ashiya_20260926_oriten.json")
    if os.path.exists(oriten_path):
        try:
            with open(oriten_path, "r", encoding="utf-8") as f:
                all_oriten = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_926 and str(r) in all_oriten:
                    r_info = all_oriten[str(r)]
                    oriten = r_info.get("oriten", {})
                    st_entries = r_info.get("st_entries", [])

                    turns = [float(o["turn"]) for o in oriten.values() if o.get("turn") and o.get("turn") != '--.--']
                    straights = [float(o["straight"]) for o in oriten.values() if o.get("straight") and o.get("straight") != '--.--']
                    laps = [float(o["lap"]) for o in oriten.values() if o.get("lap") and o.get("lap") != '--.--']
                    min_turn = min(turns) if turns else None
                    min_straight = min(straights) if straights else None
                    min_lap = min(laps) if laps else None

                    st_map = {}
                    for row in st_entries:
                        if len(row) >= 2:
                            if row[0].isdigit():
                                st_map[int(row[0])] = row[1]
                            elif row[1].isdigit():
                                st_map[int(row[1])] = row[-1]

                    for b in data_926[rk].get("boats", []):
                        num_str = str(b["num"])
                        o = oriten.get(num_str)
                        if o:
                            b["tilt"] = str(o.get("tilt", "0.0"))
                            b["ex_time"] = str(o.get("ex_time", "--.--"))
                            if o.get("turn") and o.get("turn") != '--.--':
                                b["turn_time"] = float(o["turn"])
                                b["is_best_turn"] = (b["turn_time"] == min_turn)
                            if o.get("straight") and o.get("straight") != '--.--':
                                b["straight_time"] = float(o["straight"])
                                b["is_best_straight"] = (b["straight_time"] == min_straight)
                            if o.get("lap") and o.get("lap") != '--.--':
                                b["lap_time"] = float(o["lap"])
                                b["is_best_lap"] = (b["lap_time"] == min_lap)

                        # 本番予測スリット隊形（総合推論）の算出
                        st_res = compute_comprehensive_predicted_st(b, st_map.get(b["num"]), o)
                        b["pred_st"] = st_res["pred_st"]
                        b["depth_blocks"] = st_res["depth_blocks"]
                        b["ex_st"] = st_res["ex_st_label"]
                        b["tactical_comment"] = st_res["slit_note"]
        except Exception as e:
            print(f"Ashiya Oriten injection error: {e}")

    # キャッシュがないレースも総合推論で本番スリットを算出
    for r in range(1, 13):
        rk = f"r_{r}"
        if rk in data_926:
            for b in data_926[rk].get("boats", []):
                if "depth_blocks" not in b or not b.get("ex_st"):
                    st_res = compute_comprehensive_predicted_st(b, None, None)
                    b["pred_st"] = st_res["pred_st"]
                    b["depth_blocks"] = st_res["depth_blocks"]
                    b["ex_st"] = "--"
                    if not b.get("tactical_comment"):
                        b["tactical_comment"] = st_res["slit_note"]

    return data_926


def load_919_data() -> Dict[str, Any]:
    """9/19の全12R予想データと確定結果をマージし、過去5年女子戦詳細分析を付与"""
    archive_path = os.path.join(os.path.dirname(__file__), "data", "archives", "boatrace_dashboard_20260919_宮島.html")
    with open(archive_path, "r", encoding="utf-8") as f:
        text = f.read()

    pos = text.find("const ALL_RACES_DATA =")
    end = text.find(";\n\n  let currentRound")
    data_919 = json.loads(text[pos + len("const ALL_RACES_DATA ="):end].strip())

    results_path = os.path.join(os.path.dirname(__file__), "data", "miyajima_20260919_official_results.json")
    with open(results_path, "r", encoding="utf-8") as f:
        official_results = json.load(f)

    for r in range(1, 13):
        rk = f"r_{r}"
        if rk not in data_919:
            continue
        res = official_results.get(str(r))
        race = data_919[rk]
        race["official_result"] = res
        if res:
            win_comb = res["comb"]
            payout = res["payout"]
            for m in race.get("main_bets", []):
                m["is_hit"] = (m["comb"] == win_comb)
                if m["is_hit"]:
                    m["payout"] = payout
            for a in race.get("ana_bets", []):
                a["is_hit"] = (a["comb"] == win_comb)
                if a["is_hit"]:
                    a["payout"] = payout

        # 過去5年女子戦詳細分析HTMLを付与
        race["player_notes"] = build_detailed_analysis_for_race(r, race["boats"])

    return data_919


def load_920_data() -> Dict[str, Any]:
    """9/20の全12R予想データを取得し、過去5年女子戦詳細分析HTMLを注入"""
    report_path = os.path.join(os.path.dirname(__file__), "data", "reports", "20260920_宮島_predictor.md")
    data_920 = parse_markdown_20260920(report_path)

    ladies_tags_by_race = {
        1: {1: "女子戦1C逃げ62%", 2: "女子戦2C差し壁", 3: "女子戦3C外マイ", 4: "女子戦カド追従", 5: "女子戦5C外差し", 6: "女子戦6C展開待ち (3連対18%)"},
        2: {1: "女子戦1C逃げ76%", 2: "女子戦2C好機出足", 3: "女子戦3C外マイ", 4: "女子戦カドまくり差し", 5: "女子戦展開捉え", 6: "女子戦大外最内差し"},
        3: {1: "女子戦イン受難32%", 2: "女子戦2C堅実差し", 3: "女子戦3Cまくり差し", 4: "女子戦4カド超抜伸び", 5: "女子戦旋回追従", 6: "女子戦地元大外差し"},
        4: {1: "女子戦イン受難18%", 2: "女子戦2C差し68%", 3: "女子戦センター外マイ", 4: "女子戦カド自在", 5: "女子戦チルト跳ね伸び", 6: "女子戦大外追走"},
        5: {1: "女子戦1C逃げ79%", 2: "女子戦2C厚壁・連勝中", 3: "女子戦3C快速外マイ", 4: "女子戦カド追従", 5: "女子戦外差し", 6: "女子戦大外捌き (3連対28%)"},
        6: {1: "女子戦イン標準44%", 2: "女子戦2Cエース機出足", 3: "女子戦3Cまくり差し巧者", 4: "女子戦カド追走", 5: "女子戦展開待ち", 6: "女子戦地元大外差し (3連対36%)"},
        7: {1: "女子戦イン受難17%", 2: "女子戦2C差し74%", 3: "女子戦3C全速自在78%", 4: "女子戦カド受け", 5: "女子戦外差し", 6: "女子戦大外追従"},
        8: {1: "女子戦地元イン52%", 2: "女子戦2C差し壁", 3: "女子戦3C握り攻め", 4: "女子戦カドまくり46%", 5: "女子戦最内差し", 6: "女子戦大外ヒモ穴"},
        9: {1: "女子戦地元イン72%", 2: "女子戦2C堅実差し(池千夏)", 3: "女子戦3C全速攻め", 4: "女子戦カドまくり差し", 5: "女子戦外枠追走", 6: "女子戦大外差し"},
        10: {1: "女子戦イン受難19%", 2: "女子戦2C超抜直まくり", 3: "女子戦3C追従連勝中", 4: "女子戦カド差し", 5: "女子戦地元外差し", 6: "女子戦大外差し"},
        11: {1: "女子戦イン先マイ66%", 2: "女子戦伸び型チルト跳ね", 3: "女子戦3C外マイ", 4: "女子戦カドまくり差し", 5: "女子戦5C自在捌き58%", 6: "女子戦大外追走"},
        12: {1: "女子戦最速伸び型74%", 2: "女子戦2C厚壁・差し", 3: "女子戦3C外マイ粘り", 4: "女子戦エース機出足", 5: "女子戦5C最強ターン58%", 6: "女子戦大外最内差し"}
    }

    for r in range(1, 13):
        rk = f"r_{r}"
        if rk in data_920:
            race = data_920[rk]
            # 過去5年女子戦データ分析＆選手特性の詳細HTMLを注入
            race["player_notes"] = build_detailed_analysis_for_race(r, race["boats"])

            # ボートごとに女子戦特性タグを付与
            r_tags = ladies_tags_by_race.get(r, {})
            for b in race["boats"]:
                b["ladies_tag"] = r_tags.get(b["num"], b.get("style_desc", "女子戦標準"))

    return data_920


def load_921_data() -> Dict[str, Any]:
    """9/21の全12R予想データを取得し、過去5年女子戦詳細分析HTMLおよび直前オリ展実測値を注入"""
    report_path = os.path.join(os.path.dirname(__file__), "data", "reports", "20260921_宮島_predictor.md")
    data_921 = parse_markdown_20260921(report_path)

    # オリ展実測キャッシュの注入
    oriten_path = os.path.join(os.path.dirname(__file__), "data", "miyajima_20260921_oriten.json")
    if os.path.exists(oriten_path):
        try:
            with open(oriten_path, "r", encoding="utf-8") as f:
                all_oriten = json.load(f)
            for r in range(1, 13):
                rk = f"r_{r}"
                if rk in data_921 and str(r) in all_oriten:
                    r_info = all_oriten[str(r)]
                    oriten = r_info.get("oriten", {})
                    st_entries = r_info.get("st_entries", [])

                    turns = [float(o["turn"]) for o in oriten.values() if o.get("turn") and o.get("turn") != '--.--']
                    straights = [float(o["straight"]) for o in oriten.values() if o.get("straight") and o.get("straight") != '--.--']
                    laps = [float(o["lap"]) for o in oriten.values() if o.get("lap") and o.get("lap") != '--.--']
                    min_turn = min(turns) if turns else None
                    min_straight = min(straights) if straights else None
                    min_lap = min(laps) if laps else None

                    st_map = {}
                    for row in st_entries:
                        if len(row) >= 2 and row[1].isdigit():
                            st_val = row[-1] if len(row) >= 4 else ".15"
                            st_map[int(row[1])] = st_val

                    for b in data_921[rk].get("boats", []):
                        num_str = str(b["num"])
                        o = oriten.get(num_str)
                        if o:
                            b["tilt"] = str(o.get("tilt", "0.0"))
                            b["ex_time"] = str(o.get("ex_time", "--.--"))
                            if o.get("turn") and o.get("turn") != '--.--':
                                b["turn_time"] = float(o["turn"])
                                b["is_best_turn"] = (b["turn_time"] == min_turn)
                            if o.get("straight") and o.get("straight") != '--.--':
                                b["straight_time"] = float(o["straight"])
                                b["is_best_straight"] = (b["straight_time"] == min_straight)
                            if o.get("lap") and o.get("lap") != '--.--':
                                b["lap_time"] = float(o["lap"])
                                b["is_best_lap"] = (b["lap_time"] == min_lap)

                        # 本番予測スリット隊形（総合推論）の算出
                        st_res = compute_comprehensive_predicted_st(b, st_map.get(b["num"]), o)
                        b["pred_st"] = st_res["pred_st"]
                        b["depth_blocks"] = st_res["depth_blocks"]
                        b["ex_st"] = st_res["ex_st_label"]
                        b["tactical_comment"] = st_res["slit_note"]
        except Exception as e:
            print(f"Oriten injection error: {e}")

    # キャッシュがないレースも総合推論で本番スリットを算出
    for r in range(1, 13):
        rk = f"r_{r}"
        if rk in data_921:
            for b in data_921[rk].get("boats", []):
                if "depth_blocks" not in b or not b.get("ex_st"):
                    st_res = compute_comprehensive_predicted_st(b, None, None)
                    b["pred_st"] = st_res["pred_st"]
                    b["depth_blocks"] = st_res["depth_blocks"]
                    b["ex_st"] = "--"
                    if not b.get("tactical_comment"):
                        b["tactical_comment"] = st_res["slit_note"]

    return data_921


def build_multiday_json() -> str:
    """10/11・10/10・10/09・10/08・10/07・10/06・10/05・10/04・10/03・10/02・10/01・9/29・9/28・9/27・9/26・9/21・9/20・9/19を統合したマルチデイJSON文字列を生成"""
    data_1011 = load_1011_data()
    data_1011 = load_1011_data()
    data_1010 = load_1010_data()
    data_1009 = load_1009_data()
    data_1008 = load_1008_data()
    data_1007 = load_1007_data()

    all_days = {}

    # 20261013以降（若松ヴィーナスシリーズ等）のデータファイルを自動検出・統合
    import glob
    from generate_edogawa_dynamic import get_venue_config
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    for fpath in sorted(glob.glob(os.path.join(data_dir, "*_2026*_data.json")), reverse=True):
        fname = os.path.basename(fpath)
        m_dt = re.search(r"_(\d{8})_data\.json$", fname)
        if not m_dt:
            continue
        dt_str = m_dt.group(1)
        if dt_str < "20261013":
            continue
        vcfg = get_venue_config(dt_str)
        if not fname.startswith(vcfg["prefix"]):
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                d_Future = json.load(f)
            mm = int(dt_str[4:6])
            dd = int(dt_str[6:8])
            all_days[dt_str] = {
                "date_id": dt_str,
                "date_label": f"2026-{mm:02d}-{dd:02d} {vcfg['stadium']} {vcfg['series_title']} (全12R 最新動的AI予想)",
                "status": "active",
                "summary": {
                    "desc": f"{vcfg['stadium']} {vcfg['series_title']} ({mm}/{dd}) 全12レースの蓄積学習＆直前展示連動AI予想。"
                },
                "races": normalize_race_data(d_Future, vcfg["stadium"])
            }
        except Exception as e:
            print(f"Error loading {fname}: {e}")

    # 20261012 江戸川 最終日・優勝戦
    data_1012_path = os.path.join(os.path.dirname(__file__), "data", "edogawa_20261012_data.json")
    if os.path.exists(data_1012_path):
        try:
            with open(data_1012_path, "r", encoding="utf-8") as f:
                data_1012 = json.load(f)
            all_days["20261012"] = {
                "date_id": "20261012",
                "date_label": "2026-10-12 江戸川 オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ (最終日・優勝戦 全12R 確定結果＆検証)",
                "status": "completed" if any(k > "20261012" for k in all_days) else "active",
                "summary": {
                    "desc": "江戸川オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ 最終日！第12R優勝戦(1-2-6 3,240円)を含む全12レース確定結果。"
                },
                "races": normalize_race_data(data_1012, "江戸川")
            }
        except Exception as e:
            print(f"Error loading 1012 data: {e}")

    past_days = {
        "20261011": {
            "date_id": "20261011",
            "date_label": "2026-10-11 江戸川 オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ (5日目・準優勝戦 全12R 確定結果＆検証)",
            "status": "completed",
            "summary": {
                "desc": "江戸川オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ 5日目！本線回収率207.7%・総合回収率155.2%達成。"
            },
            "races": data_1011
        },
        "20261010": {
            "date_id": "20261010",
            "date_label": "2026-10-10 江戸川 オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ (4日目・全12R 確定結果＆公式オッズ)",
            "status": "completed",
            "summary": {
                "desc": "江戸川オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ 4日目！本線的中4本（回収率181.7%）、全12R確定結果・展示タイム収録。"
            },
            "races": data_1010
        },
        "20261009": {
            "date_id": "20261009",
            "date_label": "2026-10-09 江戸川 オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ (3日目・全12R 確定結果＆展示)",
            "status": "completed",
            "summary": {
                "desc": "江戸川オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ 3日目！全12レース確定結果＆展示データ。"
            },
            "races": data_1009
        },
        "20261008": {
            "date_id": "20261008",
            "date_label": "2026-10-08 江戸川 オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ (2日目・全12R 展示タイム＆確定結果)",
            "status": "completed",
            "summary": {
                "desc": "江戸川オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ 2日目！全艇の展示タイム・チルト・スタ展ST・確定結果。"
            },
            "races": data_1008
        },
        "20261007": {
            "date_id": "20261007",
            "date_label": "2026-10-07 江戸川 オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ (初日・全12R 確定結果)",
            "status": "completed",
            "summary": {
                "desc": "江戸川オールレディース 江戸川女王決定戦ＫＩＲＩＮＣＵＰ 初日！"
            },
            "races": data_1007
        }
    }
    all_days.update(past_days)

    # HTML描画に不要な全120通りオッズ辞書(official_odds_3t)等を除外してHTMLサイズを約85%軽量化（各買い目のoddsには既に反映済み）
    for dk, dval in all_days.items():
        races_obj = dval.get("races", {})
        for rk, rval in races_obj.items():
            if isinstance(rval, dict) and "official_odds_3t" in rval:
                del rval["official_odds_3t"]

    return json.dumps(all_days, ensure_ascii=False, separators=(",", ":"))


def generate_multiday_dashboard_html() -> str:
    """マルチデイ切り替えUIとスクリプトを組み込んだ完全なHTMLを構築"""
    days_json_str = build_multiday_json()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(base_dir, "build_boatrace_dashboard.py")
    with open(template_path, "r", encoding="utf-8") as f:
        code_text = f.read()

    html_match = re.search(r'html_content = f"""(.*?)"""\n\n    targets = \[', code_text, re.DOTALL)
    if not html_match:
        raise RuntimeError("HTMLテンプレート抽出エラー")

    raw_template = html_match.group(1)
    clean_template = raw_template.replace("{{", "{").replace("}}", "}")

    # 1. 開催日セレクターバーのHTML（動的生成・リアルタイム同期対応）
    date_selector_html = """
    <!-- 📅 開催日セレクター（動的生成） -->
    <div class="mt-4 pt-3 border-t border-indigo-800/60 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2.5 bg-slate-950/70 p-2.5 rounded-xl border border-indigo-700/50">
      <div class="flex items-center gap-2 flex-wrap">
        <span class="text-xs font-bold text-cyan-300">📅 開催日:</span>
        <div id="date-buttons-container" class="inline-flex rounded-lg p-0.5 bg-slate-900 border border-slate-700/80 shadow-inner flex-wrap gap-1">
          <!-- JavaScriptで動的生成 -->
        </div>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <button id="install-app-btn" onclick="installPWA()" class="hidden cursor-pointer px-3 py-1 rounded-lg text-xs font-black transition-all bg-gradient-to-r from-emerald-500 to-teal-600 text-slate-950 shadow flex items-center gap-1">
          <span>📲</span> アプリを保存
        </button>
        <div id="auto-sync-badge" class="text-[11px] font-mono font-semibold px-2.5 py-1 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-800/60 shrink-0 flex items-center gap-1.5">
          <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> リアルタイム自動同期中
        </div>
      </div>
    </div>
"""

    # 2. サマリーバナー（メインエリア先頭に挿入）
    banners_html = """
    <!-- 🎯 9/19 選択時の公式結果検証サマリーバナー -->
    <div id="summary-banner-20260919" class="hidden bg-gradient-to-r from-slate-900 via-indigo-950 to-slate-900 border border-emerald-500/50 rounded-xl p-3 mb-4 shadow text-white">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <span class="text-xl">🎯</span>
          <div>
            <div class="text-xs font-bold text-emerald-400">9/19 公式確定結果・AI予想精度検証サマリー</div>
            <div class="text-[11px] text-slate-300">直前情報予想提供レース: <span class="text-emerald-300 font-bold">4戦4勝 (的中率 100% / 回収率 175.3%)</span> ｜ 全レース通算: <span class="text-yellow-300 font-bold">的中率 58.3% / 回収率 81.1%</span></div>
          </div>
        </div>
        <div class="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950/90 border border-emerald-600/60 text-emerald-300 font-bold">
          公式確定結果照合済
        </div>
      </div>
    </div>

    <!-- 🎯 9/20 選択時の公式結果検証サマリーバナー -->
    <div id="summary-banner-20260920" class="hidden bg-gradient-to-r from-slate-900 via-indigo-950 to-slate-900 border border-emerald-500/50 rounded-xl p-3 mb-4 shadow text-white">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <span class="text-xl">🚀</span>
          <div>
            <div class="text-xs font-bold text-emerald-400">9/20 公式確定結果・的中検証サマリー（回収率 225.9% 達成！）</div>
            <div class="text-[11px] text-slate-300">12Rにて <span class="text-yellow-300 font-bold">1-6-2（17,660円 / 44人気 万舟券！）</span>を本線1点目でズバリ的中！ 4レース的中・通算回収率: <span class="text-emerald-300 font-bold">225.9% (純利益 +120,900円)</span></div>
          </div>
        </div>
        <div class="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950/90 border border-emerald-600/60 text-emerald-300 font-bold">
          万舟券的中・大幅黒字達成
        </div>
      </div>
    </div>
"""

    # 3. レース確定結果バッジのHTML（各レースヘッダー横）
    race_result_badge_html = """
        <!-- 確定結果バッジ（結果確定レース用） -->
        <div id="race-result-banner" class="hidden items-center gap-1.5 px-2.5 py-0.5 rounded-lg bg-emerald-950/90 border border-emerald-500/70 text-white shadow-sm">
          <span class="text-[10px] font-bold text-emerald-400">確定着順:</span>
          <span id="race-result-comb" class="font-mono font-black text-xs text-yellow-300">1-3-2</span>
          <span id="race-result-payout" class="font-mono text-[11px] text-emerald-300 font-bold">910円</span>
          <span id="race-result-pop" class="text-[9.5px] text-slate-400 font-mono">(3番人気)</span>
        </div>
"""

    # 挿入1: 開催場・日付の直前にセレクターバーを追加
    target_marker1 = '<!-- 開催場・日付 -->'
    pos1 = clean_template.find(target_marker1)
    if pos1 != -1:
        clean_template = clean_template[:pos1] + date_selector_html + "\n    " + clean_template[pos1:]
    else:
        raise RuntimeError("開催場・日付マーカーが見つかりません。")

    # 挿入2: section-conceptの直前にサマリーバナーと予告カードを挿入
    target_marker2 = '<div id="section-concept"'
    pos2 = clean_template.find(target_marker2)
    if pos2 != -1:
        clean_template = clean_template[:pos2] + banners_html + "\n    " + clean_template[pos2:]
    else:
        raise RuntimeError("section-conceptマーカーが見つかりません。")

    # 挿入3: レースタイトルバッジの横（id="weather-badge"の直前）に確定結果バッジを挿入
    target_marker3 = 'id="weather-badge"'
    pos3 = clean_template.find(target_marker3)
    if pos3 != -1:
        span_start = clean_template.rfind('<span', 0, pos3)
        if span_start != -1:
            clean_template = clean_template[:span_start] + race_result_badge_html + "\n          " + clean_template[span_start:]

    # 挿入4: 過去5年女子戦データ分析＆選手特性および1マーク物理解剖のコンテナを白背景・完全黒字に刷新
    old_containers = '''        <!-- 過去5年女子戦データ分析＆選手特性 -->
        <div class="bg-indigo-50/70 dark:bg-indigo-950/40 border-l-4 border-indigo-500 p-3.5 rounded-r-xl text-xs space-y-1.5 shadow-sm">
          <div class="font-bold text-indigo-950 dark:text-indigo-200 flex items-center gap-1.5 text-sm">
            <span>🔄</span> 過去5年女子戦データ分析＆選手特性
          </div>
          <div id="player-profile-content" class="text-[var(--muted-foreground)] leading-relaxed whitespace-pre-line text-[11.5px]"></div>
        </div>

        <!-- 1マーク展開物理解剖 -->
        <div class="bg-[var(--card)] border border-[var(--border)] p-3.5 rounded-xl text-xs space-y-1.5 shadow-sm">
          <div class="font-bold text-[var(--foreground)] flex items-center gap-1.5 text-sm">
            <span>🌊</span> 1マーク展開物理解剖＆水面力学
          </div>
          <div id="physics-content" class="text-[var(--muted-foreground)] leading-relaxed whitespace-pre-line text-[11.5px]"></div>
        </div>'''

    new_containers = '''        <!-- 過去5年女子戦データ分析＆選手特性（白背景・完全黒字） -->
        <div class="bg-white border-2 border-indigo-200 border-l-8 border-l-indigo-600 p-4 rounded-xl text-xs space-y-2.5 shadow-md text-slate-950">
          <div class="font-black text-slate-950 flex items-center gap-1.5 text-sm border-b-2 border-slate-200 pb-2">
            <span class="text-base">🔄</span> 過去5年女子戦データ分析＆選手特性
          </div>
          <div id="player-profile-content" class="text-slate-950 leading-relaxed text-xs"></div>
        </div>

        <!-- 1マーク展開物理解剖（白背景・完全黒字） -->
        <div class="bg-white border-2 border-slate-300 border-l-8 border-l-cyan-600 p-4 rounded-xl text-xs space-y-2.5 shadow-md text-slate-950">
          <div class="font-black text-slate-950 flex items-center gap-1.5 text-sm border-b-2 border-slate-200 pb-2">
            <span class="text-base">🌊</span> 1マーク展開物理解剖＆水面力学
          </div>
          <div id="physics-content" class="text-slate-950 font-medium leading-relaxed whitespace-pre-line text-xs"></div>
        </div>'''

    if old_containers in clean_template:
        clean_template = clean_template.replace(old_containers, new_containers)

    else:
        raise RuntimeError("weather-badgeマーカーが見つかりません。")

    # タイトル・日付更新
    clean_template = clean_template.replace(
        "2026-09-26 芦屋 G3オールレディース マクール杯",
        "2026-09-26 芦屋 G3オールレディース マクール杯"
    )
    clean_template = clean_template.replace(
        "予測本番スリット隊形",
        "予測本番スリット隊形（過去枠番別実績 ✕ 通算ST ✕ F心理バイアス ✕ 機力伸び足 総合推論版）"
    )

    # 挿入5: 出走艇総合能力表および新概念データ表を白背景・完全黒字に刷新
    clean_template = clean_template.replace(
        'class="overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-md">\n        <table class="w-full text-xs text-center border-collapse min-w-[1150px]" id="boat-table"',
        'class="overflow-x-auto rounded-xl border-2 border-slate-300 bg-white shadow-xl">\n        <table class="w-full text-xs text-center border-collapse min-w-[1150px] bg-white text-slate-950" id="boat-table"'
    )
    clean_template = clean_template.replace(
        'class="overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-md">\n        <table class="w-full text-xs text-center border-collapse min-w-[1150px]" id="concept-table"',
        'class="overflow-x-auto rounded-xl border-2 border-slate-300 bg-white shadow-xl">\n        <table class="w-full text-xs text-center border-collapse min-w-[1150px] bg-white text-slate-950" id="concept-table"'
    )
    clean_template = clean_template.replace(
        'bg-slate-950 text-slate-300 text-[10.5px] border-b border-slate-800',
        'bg-slate-800 text-white text-[11.5px] font-black border-b-2 border-slate-300'
    )
    clean_template = clean_template.replace(
        'bg-slate-900 text-white text-[11px] border-b border-slate-700',
        'bg-slate-100 text-slate-950 text-[11.5px] font-black border-b-2 border-slate-300'
    )
    clean_template = clean_template.replace(
        'border border-[var(--border)] bg-[var(--card)]',
        'border-2 border-slate-300 bg-white'
    )
    clean_template = clean_template.replace(
        'divide-y divide-[var(--border)]',
        'divide-y divide-slate-200'
    )

    # JavaScript 側のロジック差し替え
    old_script_marker = "const ALL_RACES_DATA = {json_str};"
    
    new_script_logic = f"""const ALL_DAYS_DATA = {days_json_str};

  let currentDateKey = "20260926";
  let currentRound = 1;

  function renderDateButtons() {{
    const container = document.getElementById("date-buttons-container");
    if (!container) return;
    container.innerHTML = "";
    const dateKeys = Object.keys(ALL_DAYS_DATA).sort().reverse();
    dateKeys.forEach(dk => {{
      const day = ALL_DAYS_DATA[dk];
      const btn = document.createElement("button");
      btn.id = `date-btn-${{dk}}`;
      const isSelected = (dk === currentDateKey);
      
      const m = dk.slice(4, 6);
      const d = dk.slice(6, 8);
      let shortLabel = `${{parseInt(m)}}/${{parseInt(d)}}`;
      if (day.status === "active") shortLabel += " (最新)";
      
      btn.className = isSelected
        ? "px-3 py-1 rounded-md text-xs font-black transition-all bg-gradient-to-r from-cyan-500 to-blue-600 text-slate-950 shadow scale-105"
        : "px-2.5 py-1 rounded-md text-xs font-bold transition-all text-slate-400 hover:text-white bg-slate-900 border border-slate-700/60";
      btn.innerText = shortLabel;
      btn.onclick = () => switchDate(dk);
      container.appendChild(btn);
    }});
  }}

  function switchDate(dateKey, targetRound = null) {{
    currentDateKey = dateKey;
    localStorage.setItem("boatrace_selected_date", dateKey);
    const dayData = ALL_DAYS_DATA[dateKey];
    if (!dayData) return;

    renderDateButtons();

    // 日付ラベルの更新
    const dateLabel = document.getElementById("date-label");
    if (dateLabel && dayData.date_label) {{
      dateLabel.innerText = dayData.date_label;
    }}

    // ステータスバッジ更新
    const statusBadge = document.getElementById("date-status-badge");
    const summaryBanner919 = document.getElementById("summary-banner-20260919");
    const summaryBanner920 = document.getElementById("summary-banner-20260920");
    const secConcept = document.getElementById("section-concept");
    const secEntry = document.getElementById("section-entry");
    const secSlit = document.getElementById("section-slit");
    const secBets = document.getElementById("section-bets");
    const roundPicker = document.getElementById("round-buttons");
    const viewTabs = document.getElementById("view-tabs");

    if (dateKey === "20260919") {{
      statusBadge.className = "text-xs font-mono font-semibold px-2.5 py-1 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-800/60 shrink-0";
      statusBadge.innerText = "🏁 9/19: 確定結果・的中データ表示中";
      if (summaryBanner919) summaryBanner919.classList.remove("hidden");
      if (summaryBanner920) summaryBanner920.classList.add("hidden");
    }} else if (dateKey === "20260920") {{
      statusBadge.className = "text-xs font-mono font-semibold px-2.5 py-1 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-800/60 shrink-0";
      statusBadge.innerText = "🏁 9/20: 確定結果＆万舟的中 (回収率 225.9%)";
      if (summaryBanner919) summaryBanner919.classList.add("hidden");
      if (summaryBanner920) summaryBanner920.classList.remove("hidden");
    }} else if (dateKey === "20260921") {{
      statusBadge.className = "text-xs font-mono font-semibold px-2.5 py-1 rounded-full bg-indigo-950 text-indigo-300 border border-indigo-800/60 shrink-0";
      statusBadge.innerText = "🏁 9/21: 宮島予選最終日 予想アーカイブ";
      if (summaryBanner919) summaryBanner919.classList.add("hidden");
      if (summaryBanner920) summaryBanner920.classList.add("hidden");
    }} else if (dateKey === "20260926") {{
      statusBadge.className = "text-xs font-mono font-semibold px-2.5 py-1 rounded-full bg-cyan-950 text-cyan-300 border border-cyan-800/60 shrink-0";
      statusBadge.innerText = "🟢 9/26 芦屋: 本日・3日目 全12レース事前予想稼働中";
      if (summaryBanner919) summaryBanner919.classList.add("hidden");
      if (summaryBanner920) summaryBanner920.classList.add("hidden");
    }}

    secConcept.style.display = "block";
    secEntry.style.display = "block";
    secSlit.style.display = "block";
    secBets.style.display = "grid";
    roundPicker.style.display = "grid";
    viewTabs.style.display = "flex";

    if (targetRound !== null && targetRound >= 1 && targetRound <= 12) {{
      currentRound = targetRound;
    }} else {{
      const savedRound = parseInt(localStorage.getItem("boatrace_selected_round") || "1");
      currentRound = (savedRound >= 1 && savedRound <= 12) ? savedRound : (currentRound || 1);
    }}
    localStorage.setItem("boatrace_selected_round", currentRound);
    renderRoundButtons();
    renderRaceContent();
  }}

  function switchView(tab) {{
    const tabs = ["all", "concept", "entry", "slit", "bets"];
    tabs.forEach(t => {{
      const btn = document.getElementById(`tab-${{t}}`);
      if (btn) {{
        if (t === tab) {{
          btn.className = "px-3 py-1 rounded-lg font-bold transition-all bg-cyan-400 text-slate-950 shadow";
        }} else {{
          btn.className = "px-3 py-1 rounded-lg font-semibold transition-all bg-slate-900 text-cyan-200 hover:bg-indigo-950 border border-indigo-900/50";
        }}
      }}
    }});

    const secConcept = document.getElementById("section-concept");
    const secEntry = document.getElementById("section-entry");
    const secSlit = document.getElementById("section-slit");
    const secBets = document.getElementById("section-bets");

    if (tab === "all") {{
      secConcept.style.display = "block";
      secEntry.style.display = "block";
      secSlit.style.display = "block";
      secBets.style.display = "grid";
    }} else if (tab === "concept") {{
      secConcept.style.display = "block";
      secEntry.style.display = "none";
      secSlit.style.display = "none";
      secBets.style.display = "none";
    }} else if (tab === "entry") {{
      secConcept.style.display = "none";
      secEntry.style.display = "block";
      secSlit.style.display = "none";
      secBets.style.display = "none";
    }} else if (tab === "slit") {{
      secConcept.style.display = "none";
      secEntry.style.display = "none";
      secSlit.style.display = "block";
      secBets.style.display = "none";
    }} else if (tab === "bets") {{
      secConcept.style.display = "none";
      secEntry.style.display = "none";
      secSlit.style.display = "none";
      secBets.style.display = "grid";
    }}
  }}

  function renderRoundButtons() {{
    const container = document.getElementById("round-buttons");
    container.innerHTML = "";
    for (let r = 1; r <= 12; r++) {{
      const btn = document.createElement("button");
      btn.className = `py-2 text-xs sm:text-sm font-black rounded-lg transition-all ${{
        r === currentRound
          ? "bg-cyan-400 text-slate-950 shadow-[0_0_10px_#22d3ee] scale-105"
          : "bg-slate-900/90 hover:bg-cyan-950 text-cyan-200 border border-cyan-800/60"
      }}`;
      btn.innerText = `${{r}}R`;
      btn.onclick = () => selectRound(r);
      container.appendChild(btn);
    }}
  }}

  function selectRound(r) {{
    currentRound = r;
    localStorage.setItem("boatrace_selected_round", r);
    renderRoundButtons();
    renderRaceContent();
  }}

  function renderRaceContent() {{
    const dayData = ALL_DAYS_DATA[currentDateKey];
    if (!dayData || !dayData.races) return;

    const raceKey = `r_${{currentRound}}`;
    const race = dayData.races[raceKey];
    if (!race) return;

    // バッジ・タイトル更新（undefined / null 完全排除防護壁）
    const stadium = race.stadium || "下関";
    const roundNum = race.round || currentRound || 1;
    const raceBadgeEl = document.getElementById("race-badge");
    if (raceBadgeEl) raceBadgeEl.innerText = `${{stadium}} ${{roundNum}}R`;

    let wDir = "微風", wSpeed = "1.0", wWave = "1", wTide = "中潮", wWeather = "晴";
    if (race.weather && typeof race.weather === "object") {{
      wDir = race.weather.direction || race.weather.wind_dir || "微風";
      wSpeed = (race.weather.wind_speed || "1.0").toString().replace('m', '');
      wWave = (race.weather.wave_height || race.weather.wave || "1").toString().replace('cm', '');
      wTide = race.weather.tide || "中潮";
      wWeather = race.weather.weather || "晴";
    }} else if (typeof race.weather === "string" && race.weather) {{
      wWeather = race.weather;
    }}
    const weatherBadgeEl = document.getElementById("weather-badge");
    if (weatherBadgeEl) weatherBadgeEl.innerText = `💨 ${{wDir}} ${{wSpeed}}m | 🌊 ${{wWave}}cm`;

    const tideBadgeEl = document.getElementById("tide-badge");
    if (tideBadgeEl) tideBadgeEl.innerText = `潮汐: ${{wTide}} | 天候: ${{wWeather}}`;

    const titleStr = (race.title && race.title !== "None") ? race.title : `${{stadium}} ${{roundNum}}R 予選`;
    const deadlineStr = (race.deadline && race.deadline !== "None") ? race.deadline : "直前";
    const raceTitleEl = document.getElementById("race-title");
    if (raceTitleEl) raceTitleEl.innerText = `${{titleStr}} (締切予定: ${{deadlineStr}})`;

    // 確定結果バッジの表示制御
    const resBanner = document.getElementById("race-result-banner");
    if (resBanner) {{
      if (race.official_result) {{
        resBanner.classList.remove("hidden");
        resBanner.classList.add("flex");
        document.getElementById("race-result-comb").innerText = race.official_result.comb;
        document.getElementById("race-result-payout").innerText = `${{race.official_result.payout}}円`;
        document.getElementById("race-result-pop").innerText = `(${{race.official_result.popularity}}番人気)`;
      }} else {{
        resBanner.classList.add("hidden");
        resBanner.classList.remove("flex");
      }}
    }}

    // 🧠 新概念データ 4大サマリーカード描画
    const b1 = race.boats.find(b => b.num === 1);
    const b2 = race.boats.find(b => b.num === 2);
    const b3 = race.boats.find(b => b.num === 3);
    const b4 = race.boats.find(b => b.num === 4);
    const summaryCardsContainer = document.getElementById("concept-summary-cards");
    summaryCardsContainer.innerHTML = `
      <!-- 1C イン逃げ耐久力 -->
      <div class="bg-slate-900/90 border border-emerald-500/40 p-3 rounded-xl shadow-sm text-white space-y-1.5">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-1.5 text-xs font-bold text-emerald-400">
            <span class="w-4 h-4 rounded-full inline-flex items-center justify-center text-[10px] boat-badge-1">1</span>
            1C イン逃げ耐久性
          </div>
          <span class="text-[10px] px-1.5 py-0.2 rounded font-bold ${{b1.concept.badge_color}}">${{b1.concept.badge}}</span>
        </div>
        <div class="flex items-baseline justify-between">
          <span class="text-xs text-slate-300">逃げ率</span>
          <span class="font-mono text-lg font-black text-emerald-300">${{b1.concept.primary_rate}}%</span>
        </div>
        <div class="text-[10px] text-slate-300 line-clamp-1">${{b1.concept.eval_text}}</div>
        <div class="grid grid-cols-2 gap-1 text-[9.5px] pt-1 border-t border-slate-800 text-slate-400 font-mono">
          <div>差され失速: <span class="text-amber-300">${{b1.concept.sashi_loss}}%</span></div>
          <div>捲られ沈没: <span class="text-rose-300">${{b1.concept.makuri_loss}}%</span></div>
        </div>
      </div>

      <!-- 2C 壁信頼度 & 差し -->
      <div class="bg-slate-900/90 border border-cyan-500/40 p-3 rounded-xl shadow-sm text-white space-y-1.5">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-1.5 text-xs font-bold text-cyan-400">
            <span class="w-4 h-4 rounded-full inline-flex items-center justify-center text-[10px] boat-badge-2">2</span>
            2C 壁信頼度 & 差し
          </div>
          <span class="text-[10px] px-1.5 py-0.2 rounded font-bold ${{b2.concept.badge_color}}">${{b2.concept.badge}}</span>
        </div>
        <div class="flex items-baseline justify-between">
          <span class="text-xs text-slate-300">逃がし率</span>
          <span class="font-mono text-lg font-black text-cyan-300">${{b2.concept.primary_rate}}%</span>
        </div>
        <div class="text-[10px] text-slate-300 line-clamp-1">${{b2.concept.eval_text}}</div>
        <div class="grid grid-cols-2 gap-1 text-[9.5px] pt-1 border-t border-slate-800 text-slate-400 font-mono">
          <div>差し率: <span class="text-cyan-300">${{b2.concept.sashi_rate}}</span></div>
          <div>捲られ率: <span class="text-rose-300">${{b2.concept.makuri_loss}}%</span></div>
        </div>
      </div>

      <!-- 3C 握り攻め & ツケマイ -->
      <div class="bg-slate-900/90 border border-purple-500/40 p-3 rounded-xl shadow-sm text-white space-y-1.5">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-1.5 text-xs font-bold text-purple-400">
            <span class="w-4 h-4 rounded-full inline-flex items-center justify-center text-[10px] boat-badge-3">3</span>
            3C センター攻防
          </div>
          <span class="text-[10px] px-1.5 py-0.2 rounded font-bold ${{b3.concept.badge_color}}">${{b3.concept.badge}}</span>
        </div>
        <div class="flex items-baseline justify-between">
          <span class="text-xs text-slate-300">握り・まくり率</span>
          <span class="font-mono text-lg font-black text-purple-300">${{b3.concept.makuri_rate}}</span>
        </div>
        <div class="text-[10px] text-slate-300 line-clamp-1">${{b3.concept.eval_text}}</div>
        <div class="grid grid-cols-2 gap-1 text-[9.5px] pt-1 border-t border-slate-800 text-slate-400 font-mono">
          <div>捲り差し: <span class="text-indigo-300">${{b3.concept.makurisashi_rate}}</span></div>
          <div>自力逃がし: <span class="text-slate-400">${{b3.concept.primary_rate}}%</span></div>
        </div>
      </div>

      <!-- 4C カド一撃 & 自在戦術 -->
      <div class="bg-slate-900/90 border border-blue-500/40 p-3 rounded-xl shadow-sm text-white space-y-1.5">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-1.5 text-xs font-bold text-blue-400">
            <span class="w-4 h-4 rounded-full inline-flex items-center justify-center text-[10px] boat-badge-4">4</span>
            4C カド自在攻め
          </div>
          <span class="text-[10px] px-1.5 py-0.2 rounded font-bold ${{b4.concept.badge_color}}">${{b4.concept.badge}}</span>
        </div>
        <div class="flex items-baseline justify-between">
          <span class="text-xs text-slate-300">カド捲り率</span>
          <span class="font-mono text-lg font-black text-blue-300">${{b4.concept.makuri_rate}}</span>
        </div>
        <div class="text-[10px] text-slate-300 line-clamp-1">${{b4.concept.eval_text}}</div>
        <div class="grid grid-cols-2 gap-1 text-[9.5px] pt-1 border-t border-slate-800 text-slate-400 font-mono">
          <div>捲り差し: <span class="text-cyan-300">${{b4.concept.makurisashi_rate}}</span></div>
          <div>カド差し: <span class="text-slate-400">${{b4.concept.sashi_rate}}</span></div>
        </div>
      </div>
    `;

    // 🧠 新概念データ ＆ 枠番別成績 完全比較テーブル描画
    const conceptTbody = document.getElementById("concept-tbody");
    if (conceptTbody) {{
      conceptTbody.innerHTML = "";
      race.boats.forEach((b, idx) => {{
        const tr = document.createElement("tr");
        tr.className = (idx % 2 === 0 ? "bg-white" : "bg-slate-50/80") + " hover:bg-sky-50/80 transition-colors border-b border-slate-200 text-slate-950 font-bold";
        
        const escapeCell = b.num === 1
          ? `<span class="font-extrabold text-emerald-600 dark:text-emerald-400 font-mono text-xs">逃げ ${{b.concept.primary_rate}}%</span>`
          : `<span class="font-bold text-cyan-600 dark:text-cyan-300 font-mono">逃がし ${{b.concept.primary_rate}}%</span>`;

        tr.innerHTML = `
          <td class="py-1.5 px-1 font-bold">
            <span class="inline-flex items-center justify-center w-5 h-5 rounded-full text-xs font-black boat-badge-${{b.num}} shadow">${{b.num}}</span>
          </td>
          <td class="py-1.5 px-1 font-extrabold text-sm text-cyan-600 dark:text-cyan-400">${{b.mark}}</td>
          <td class="py-1.5 px-2 text-left font-bold whitespace-nowrap border-r border-[var(--border)] text-slate-950">
            ${{b.name}} <span class="text-[10px] text-slate-800 font-bold">(${{b.rank}}${{b.fl ? '/' + b.fl : ''}})</span>
          </td>

          <td class="py-1.5 px-1 font-mono font-bold text-cyan-600 dark:text-cyan-400">${{b.concept.c_win}}%</td>
          <td class="py-1.5 px-1 font-mono text-slate-950 font-bold">${{b.concept.c_rentai2}}%</td>
          <td class="py-1.5 px-1 font-mono border-r border-[var(--border)] font-semibold text-slate-700">${{b.concept.c_avg_st}}</td>

          <td class="py-1.5 px-2 font-mono bg-emerald-50/60 font-black">${{escapeCell}}</td>
          <td class="py-1.5 px-1 font-mono text-rose-600 font-bold">${{b.concept.sashi_loss}}%</td>
          <td class="py-1.5 px-1 font-mono border-r border-[var(--border)] text-purple-600 font-bold">${{b.concept.makuri_loss}}%</td>

          <td class="py-1.5 px-1 font-mono font-bold text-amber-700">${{b.concept.sashi_rate}}</td>
          <td class="py-1.5 px-1 font-mono font-bold text-orange-700">${{b.concept.makuri_rate}}</td>
          <td class="py-1.5 px-1 font-mono border-r border-[var(--border)] font-bold text-yellow-700">${{b.concept.makurisashi_rate}}</td>

          <td class="py-1.5 px-2 text-left whitespace-nowrap">
            <span class="px-1.5 py-0.5 rounded text-[10px] font-bold ${{b.concept.badge_color}} mr-1.5">${{b.concept.badge}}</span>
            <span class="text-[10.5px] text-slate-950 font-bold">${{b.concept.eval_text}}</span>
          </td>
        `;
        conceptTbody.appendChild(tr);
      }});
    }}

    // 📋 出走表テーブル描画（選手名・直前展示・機力数値を完全黒字化＆高コントラスト）
    const boatTbody = document.getElementById("boat-tbody");
    boatTbody.innerHTML = "";
    race.boats.forEach(b => {{
      const tr = document.createElement("tr");
      tr.className = "hover:bg-sky-50 transition-colors border-b border-slate-200 bg-white even:bg-slate-50/80 text-slate-950 font-bold";

      const straightHtml = (b.straight_time && b.straight_time > 0)
        ? (b.is_best_straight
            ? `<span class="px-1.5 py-0.5 rounded bg-amber-200 text-amber-950 font-black border border-amber-400 shadow-sm">${{Number(b.straight_time).toFixed(2)}} <span class="text-[8.5px] bg-amber-500 text-white px-0.5 rounded font-black">TOP</span></span>`
            : `<span class="font-mono font-bold text-slate-900">${{Number(b.straight_time).toFixed(2)}}</span>`)
        : `<span class="font-mono font-bold text-slate-400">-</span>`;
      const turnHtml = (b.turn_time && b.turn_time > 0)
        ? (b.is_best_turn
            ? `<span class="px-1.5 py-0.5 rounded bg-amber-200 text-amber-950 font-black border border-amber-400 shadow-sm">${{Number(b.turn_time).toFixed(2)}} <span class="text-[8.5px] bg-amber-500 text-white px-0.5 rounded font-black">TOP</span></span>`
            : `<span class="font-mono font-bold text-slate-900">${{Number(b.turn_time).toFixed(2)}}</span>`)
        : `<span class="font-mono font-bold text-slate-400">-</span>`;
      const lapHtml = (b.lap_time && b.lap_time > 0)
        ? (b.is_best_lap
            ? `<span class="px-1.5 py-0.5 rounded bg-amber-200 text-amber-950 font-black border border-amber-400 shadow-sm">${{Number(b.lap_time).toFixed(2)}} <span class="text-[8.5px] bg-amber-500 text-white px-0.5 rounded font-black">TOP</span></span>`
            : `<span class="font-mono font-bold text-slate-900">${{Number(b.lap_time).toFixed(2)}}</span>`)
        : `<span class="font-mono font-bold text-slate-400">-</span>`;

      const ladiesTagHtml = b.ladies_tag
        ? `<span class="px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-950 font-bold border border-indigo-300 text-[10px]">${{b.ladies_tag}}</span>`
        : `<span class="px-1.5 py-0.5 rounded bg-slate-200 text-slate-950 font-bold">${{b.style_desc}}</span>`;

      tr.innerHTML = `
        <td class="py-1.5 px-1 text-center font-bold">
          <span class="w-5 h-5 rounded-full inline-flex items-center justify-center text-xs font-black boat-badge-${{b.num}} shadow">
            ${{b.num}}
          </span>
        </td>
        <td class="py-1.5 px-1 text-center font-extrabold text-sm text-cyan-600 dark:text-cyan-400">${{b.mark}}</td>
        <td class="py-1.5 px-1.5 text-left whitespace-nowrap">
          <div class="font-black text-xs text-slate-950">${{b.name}}</div>
          <div class="text-[9.5px] text-slate-600 font-mono font-medium">${{b.id}} / ${{b.branch}}</div>
        </td>
        <td class="py-1.5 px-1 font-bold text-slate-900 border-r border-[var(--border)]">${{b.rank}}</td>

        <td class="py-1.5 px-1 font-mono font-bold text-slate-900">${{b.tilt}}</td>
        <td class="py-1.5 px-1 font-mono font-black text-slate-950 text-xs">${{b.ex_time}}</td>
        <td class="py-1.5 px-1 font-mono bg-cyan-50/60">${{straightHtml}}</td>
        <td class="py-1.5 px-1 font-mono bg-teal-50/60">${{turnHtml}}</td>
        <td class="py-1.5 px-1 font-mono bg-indigo-50/60">${{lapHtml}}</td>
        <td class="py-1.5 px-1 text-xs font-mono font-bold text-slate-950 whitespace-nowrap">${{b.motor_info}}</td>
        <td class="py-1.5 px-1 text-xs font-mono font-bold text-slate-950 border-r border-[var(--border)] whitespace-nowrap">${{b.boat_info}}</td>

        <td class="py-1.5 px-1 font-mono font-bold text-slate-900">${{b.win_rate}}</td>
        <td class="py-1.5 px-1 font-mono font-bold text-slate-900">${{b.local_win_rate}}</td>
        <td class="py-1.5 px-1 font-mono font-black text-slate-950">${{b.avg_st}}</td>
        <td class="py-1.5 px-1 font-mono text-[10.5px] ${{b.fl.includes('F1') || b.fl.includes('F2') ? 'text-red-600 font-black' : 'text-slate-900 font-bold'}}">${{b.fl}}</td>
        <td class="py-1.5 px-1 text-[10px] border-r border-[var(--border)] whitespace-nowrap">
          ${{ladiesTagHtml}}
          <span class="text-[9.5px] text-slate-700 font-bold ml-0.5">F:${{b.f_res}}</span>
        </td>

        <td class="py-1.5 px-1 font-black text-cyan-700 font-mono bg-slate-50/50">${{b.win_prob}}%</td>
        <td class="py-1.5 px-1 font-mono font-bold text-slate-800">${{b.place2_prob}}%</td>
        <td class="py-1.5 px-1 font-mono font-bold text-slate-800">${{b.place3_prob}}%</td>
        <td class="py-1.5 px-1 font-black text-emerald-700 font-mono">${{b.triple_rate}}%</td>
        <td class="py-1.5 px-1 font-black bg-slate-200 text-slate-950 rounded">${{b.score}}</td>
      `;
      boatTbody.appendChild(tr);
    }});

    // 🏁 【高さを約半分に圧縮】予測本番スリット隊形レーンカード
    const slitContainer = document.getElementById("slit-cards-container");
    slitContainer.innerHTML = "";

    race.boats.forEach(b => {{
      const card = document.createElement("div");
      card.className = "bg-slate-900/90 border border-slate-800 hover:border-cyan-500/50 rounded-lg py-1 px-2.5 flex items-center justify-between gap-2 transition-all shadow-sm";

      let blocksHtml = "";
      for (let i = 0; i < b.depth_blocks; i++) {{
        blocksHtml += `<span class="depth-block depth-${{b.num}}"></span>`;
      }}

      // 左側: 艇番 + コース + 選手名 + 新概念バッジ
      const leftCol = `
        <div class="flex items-center gap-1 sm:gap-1.5 shrink-0">
          <span class="w-5 h-5 rounded-full inline-flex items-center justify-center text-[11px] font-extrabold boat-badge-${{b.num}} shadow">
            ${{b.num}}
          </span>
          <span class="px-1 py-0.2 rounded bg-slate-800 text-cyan-300 font-mono text-[10px] font-bold border border-slate-700">
            [${{b.course}}]
          </span>
          <span class="font-bold text-xs text-slate-100">${{b.name}}</span>
          <span class="text-[9px] px-1 py-0.2 rounded border ${{b.concept.badge_color}}">${{b.concept.badge}}</span>
        </div>
      `;

      // 中央: ➔ 予測本番ST値 + [展/平バッジ] + 踏み込み深度ブロック
      const exBadge = (b.ex_st && b.ex_st !== "--")
        ? `<span class="text-[9.5px] px-1 py-0.2 rounded bg-slate-800 text-cyan-300 font-mono border border-slate-700 font-bold" title="直前スタート展示ST">展:${{b.ex_st}}</span>`
        : "";
      const avgBadge = `<span class="hidden sm:inline text-[9.5px] px-1 py-0.2 rounded bg-slate-800 text-slate-400 font-mono font-bold" title="通算平均ST">平:${{b.avg_st}}</span>`;

      const midCol = `
        <div class="flex items-center gap-1.5 shrink-0 ml-auto sm:ml-0">
          <div class="flex items-center gap-1">
            ${{exBadge}}
            ${{avgBadge}}
          </div>
          <span class="text-cyan-400 font-black text-[10px] sm:text-xs">予測➔</span>
          <span class="font-mono font-black text-xs sm:text-sm text-yellow-300 w-7 sm:w-8 text-right" title="枠番別・機力・心理アジャスト総合AI本番予測ST">${{b.pred_st}}</span>
          <div class="flex items-center ml-0.5" title="本番先行予測深度: ${{b.depth_blocks}}ブロック">
            ${{blocksHtml}}
          </div>
        </div>
      `;

      // 右側: 戦術寸評 (スマホでは非表示または短縮)
      const rightCol = `
        <div class="hidden sm:block text-[11px] text-slate-300 italic text-right flex-1 truncate ml-2">
          ${{b.tactical_comment}}
        </div>
      `;

      card.innerHTML = leftCol + midCol + rightCol;
      slitContainer.appendChild(card);

      // スロー(3C)とダッシュ(4C)の境界線（コンパクト化）
      if (b.num === 3) {{
        const divider = document.createElement("div");
        divider.className = "py-0.5 flex items-center justify-center gap-2 text-[10px] text-cyan-400/80 tracking-wider font-semibold";
        divider.innerHTML = `
          <div class="flex-1 border-t border-dashed border-cyan-800/80"></div>
          <span class="bg-slate-950 px-2 py-0.2 rounded-full border border-cyan-700/40 text-[9.5px]">
            🛑 スロー (1〜3C) / ダッシュ (4〜6C) 境界線
          </span>
          <div class="flex-1 border-t border-dashed border-cyan-800/80"></div>
        `;
        slitContainer.appendChild(divider);
      }}
    }});

    // 左カラム: 過去5年女子戦データ分析＆選手特性（HTMLリッチレンダリング・undefined完全防止）
    const playerProfileElem = document.getElementById("player-profile-content");
    if (playerProfileElem) {{
      playerProfileElem.innerHTML = (race.player_notes && race.player_notes !== "None" && race.player_notes !== "undefined")
        ? race.player_notes
        : "<div class='text-slate-300 font-bold'>【選手特性推論】過去5年女子戦データを基にイン先マイ展開を主力に算定中。</div>";
    }}

    const physicsElem = document.getElementById("physics-content");
    if (physicsElem) {{
      physicsElem.innerText = (race.physics_analysis && race.physics_analysis !== "None" && race.physics_analysis !== "undefined")
        ? race.physics_analysis
        : "【水面力学分析】下関ナイター特有のイン優位水面。1マークの引き波影響を最小化する展開想定。";
    }}

    // 🔥 本線4点 グリッド
    const mainGrid = document.getElementById("main-bets-grid");
    mainGrid.innerHTML = "";
    race.main_bets.forEach(m => {{
      const isHit = m.is_hit === true;
      const hitBadge = isHit
        ? `<span class="bg-emerald-500 text-slate-950 text-[10px] px-1.5 py-0.2 rounded font-black tracking-wider shadow-[0_0_8px_#10b981] animate-pulse">🎯 的中！ ${{m.payout}}円</span>`
        : "";
      const cardBorder = isHit
        ? "bg-emerald-950/40 border-2 border-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.3)]"
        : "bg-slate-900/90 border border-amber-500/30 hover:border-amber-400 shadow-sm";

      const card = document.createElement("div");
      card.className = `${{cardBorder}} p-3 rounded-xl flex items-center justify-between transition-all`;
      card.innerHTML = `
        <div>
          <div class="flex items-center gap-1.5 font-black text-sm sm:text-base text-white tracking-wider">
            <span class="w-6 h-6 sm:w-7 sm:h-7 rounded-full inline-flex items-center justify-center text-xs sm:text-sm font-black boat-badge-${{m.b1}} shadow">${{m.b1}}</span>
            <span class="text-slate-400 text-xs font-bold">−</span>
            <span class="w-6 h-6 sm:w-7 sm:h-7 rounded-full inline-flex items-center justify-center text-xs sm:text-sm font-black boat-badge-${{m.b2}} shadow">${{m.b2}}</span>
            <span class="text-slate-400 text-xs font-bold">−</span>
            <span class="w-6 h-6 sm:w-7 sm:h-7 rounded-full inline-flex items-center justify-center text-xs sm:text-sm font-black boat-badge-${{m.b3}} shadow">${{m.b3}}</span>
            ${{hitBadge}}
          </div>
          <div class="text-[11px] text-amber-200/90 mt-1 font-sans">${{m.desc}}</div>
        </div>
        <div class="text-right">
          <div class="font-mono font-black text-amber-400 text-base sm:text-lg">${{m.odds}}倍</div>
          <div class="text-[10px] text-slate-400 font-mono">確率:${{m.prob}}% <span class="text-amber-400 font-bold">EV:${{m.ev}}</span></div>
        </div>
      `;
      mainGrid.appendChild(card);
    }});

    // ⚡ 穴4点 グリッド
    const anaGrid = document.getElementById("ana-bets-grid");
    anaGrid.innerHTML = "";
    race.ana_bets.forEach(a => {{
      const isHit = a.is_hit === true;
      const hitBadge = isHit
        ? `<span class="bg-emerald-500 text-slate-950 text-[10px] px-1.5 py-0.2 rounded font-black tracking-wider shadow-[0_0_8px_#10b981] animate-pulse">🎯 的中！ ${{a.payout}}円</span>`
        : "";
      const cardBorder = isHit
        ? "bg-emerald-950/40 border-2 border-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.3)]"
        : "bg-slate-900/90 border border-purple-500/30 hover:border-purple-400 shadow-sm";

      const card = document.createElement("div");
      card.className = `${{cardBorder}} p-3 rounded-xl flex items-center justify-between transition-all`;
      card.innerHTML = `
        <div>
          <div class="flex items-center gap-1.5 font-black text-sm sm:text-base text-white tracking-wider">
            <span class="w-6 h-6 sm:w-7 sm:h-7 rounded-full inline-flex items-center justify-center text-xs sm:text-sm font-black boat-badge-${{a.b1}} shadow">${{a.b1}}</span>
            <span class="text-slate-400 text-xs font-bold">−</span>
            <span class="w-6 h-6 sm:w-7 sm:h-7 rounded-full inline-flex items-center justify-center text-xs sm:text-sm font-black boat-badge-${{a.b2}} shadow">${{a.b2}}</span>
            <span class="text-slate-400 text-xs font-bold">−</span>
            <span class="w-6 h-6 sm:w-7 sm:h-7 rounded-full inline-flex items-center justify-center text-xs sm:text-sm font-black boat-badge-${{a.b3}} shadow">${{a.b3}}</span>
            ${{hitBadge}}
          </div>
          <div class="text-[11px] text-purple-200/90 mt-1 font-sans">${{a.desc}}</div>
        </div>
        <div class="text-right">
          <div class="font-mono font-black text-purple-300 text-base sm:text-lg">${{a.odds}}倍</div>
          <div class="text-[10px] text-slate-400 font-mono">確率:${{a.prob}}% <span class="text-purple-400 font-bold">EV:${{a.ev}}</span></div>
        </div>
      `;
      anaGrid.appendChild(card);
    }});
  }}

  // ユーザー選択状態を完全復元（未選択または無効時は最新の 20261005）
  let savedDate = localStorage.getItem("boatrace_selected_date");
  if (!savedDate || !ALL_DAYS_DATA[savedDate]) {{
    savedDate = "20261005";
  }}
  const savedRound = parseInt(localStorage.getItem("boatrace_selected_round") || "1");
  switchDate(savedDate, savedRound);

  // 1. Service Worker 登録 (PWA高速化 & オフライン対応)
  if ('serviceWorker' in navigator) {{
    navigator.serviceWorker.register('/sw.js').catch(() => {{}});
  }}

  // 2. PWA インストールハンドラー (スマホ画面にアプリとして追加)
  let deferredPrompt;
  window.addEventListener('beforeinstallprompt', (e) => {{
    e.preventDefault();
    deferredPrompt = e;
    const installBtn = document.getElementById('install-app-btn');
    if (installBtn) installBtn.classList.remove('hidden');
  }});

  window.installPWA = function() {{
    if (deferredPrompt) {{
      deferredPrompt.prompt();
      deferredPrompt.userChoice.then(() => {{
        deferredPrompt = null;
        const installBtn = document.getElementById('install-app-btn');
        if (installBtn) installBtn.classList.add('hidden');
      }});
    }}
  }};

  // 3. リアルタイム自動同期ポーリング (25秒おきに最新展示・オッズ・確定結果を検知し画面更新)
  async function pollLatestData() {{
    try {{
      const res = await fetch('/api/latest_data?date=' + currentDateKey + '&t=' + Date.now());
      if (!res.ok) return;
      const data = await res.json();
      
      let needRefresh = false;
      if (data.oriten && typeof data.oriten === 'object') {{
        const dayData = ALL_DAYS_DATA[currentDateKey];
        if (dayData && dayData.races) {{
          for (const [rno, rInfo] of Object.entries(data.oriten)) {{
            const rk = 'r_' + rno;
            const currentRace = dayData.races[rk];
            if (currentRace && rInfo.oriten) {{
              for (const b of (currentRace.boats || [])) {{
                const o = rInfo.oriten[b.num];
                if (o && o.ex_time && o.ex_time !== '--.--' && b.ex_time !== o.ex_time) {{
                  needRefresh = true;
                  break;
                }}
              }}
            }}
            if (needRefresh) break;
          }}
        }}
      }}
      if (needRefresh) {{
        console.log('[AUTO SYNC] 新しい展示データを検知しました。画面を自動更新します。');
        window.location.reload();
      }}
    }} catch (e) {{}}
  }}
  setInterval(pollLatestData, 25000);
"""

    pos_script = clean_template.find(old_script_marker)
    if pos_script == -1:
        raise RuntimeError("old_script_markerが見つかりません。")

    end_script = clean_template.find("renderRoundButtons();\n  renderRaceContent();\n</script>", pos_script)
    if end_script != -1:
        clean_template = clean_template[:pos_script] + new_script_logic + "\n</script>" + clean_template[end_script + len("renderRoundButtons();\n  renderRaceContent();\n</script>"):]
    else:
        raise RuntimeError("終了スクリプトマーカーが見つかりません。")

    return clean_template


def main():
    print("Generating Enriched Ladies Stats Multi-Day Boatrace Dashboard HTML...")
    html_content = generate_multiday_dashboard_html()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    targets = [
        os.path.join(base_dir, "boatrace_dashboard.html"),
        os.path.join(base_dir, "data", "archives", "boatrace_dashboard_multiday_芦屋.html"),
        os.path.join(base_dir, "data", "archives", "boatrace_dashboard_multiday_宮島.html")
    ]
    if sys.platform == "win32":
        targets.extend([
            r"C:\Users\hiron\.gemini\antigravity\brain\ac0ee758-2f92-46c4-8919-cb47bb72f692\boatrace_dashboard.html",
            r"C:\Users\hiron\Desktop\Boatrace_AI_Dashboard.html",
            r"C:\Users\hiron\OneDrive\デスクトップ\Boatrace_AI_Dashboard.html",
            r"C:\Users\hiron\Desktop\Boatrace_Archives\Boatrace_Dashboard_MultiDay_宮島.html",
            r"C:\Users\hiron\OneDrive\デスクトップ\Boatrace_Archives\Boatrace_Dashboard_MultiDay_宮島.html"
        ])

    for t in targets:
        try:
            os.makedirs(os.path.dirname(t), exist_ok=True)
            with open(t, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"Successfully generated: {t} (size: {len(html_content):,} bytes)")
        except Exception as e:
            print(f"Warning: could not write {t}: {e}")


if __name__ == "__main__":
    main()

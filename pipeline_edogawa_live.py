# -*- coding: utf-8 -*-
"""
pipeline_edogawa_live.py
江戸川オールレディース リアルタイム自動更新パイプライン
タスクスケジューラから毎分/定期実行され、
1. 直前展示タイム・チルト・スタ展ST
2. 確定結果・払戻金・決まり手
を自動検知してJSONを更新し、ダッシュボードHTML再生成・クラウド同期まで一貫実行する。
"""

import os
import sys
import json
import re
import datetime
import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.boatrace.jp/"
}

def prevent_sleep():
    """Windowsが実行中に自動サスペンド/スリープするのを防止"""
    if sys.platform == "win32":
        try:
            import ctypes
            # ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001)
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        except Exception:
            pass

def run_pipeline(target_date: str = None):
    prevent_sleep()
    from generate_edogawa_dynamic import get_venue_config, generate_race_data_for_date
    JST = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime.now(JST)
    if target_date:
        date_str = target_date
    elif len(sys.argv) > 1 and len(sys.argv[1]) == 8 and sys.argv[1].isdigit():
        date_str = sys.argv[1]
    else:
        date_str = now.strftime("%Y%m%d")
    vcfg = get_venue_config(date_str)
    jcd = vcfg["jcd"]
    prefix = vcfg["prefix"]
    data_file = os.path.join(DATA_DIR, f"{prefix}_{date_str}_data.json")

    # セッションと自動リトライ（タイムアウト・レート制限耐性を極限化）
    session = requests.Session()
    session.headers.update(HEADERS)
    from urllib3.util.retry import Retry
    from requests.adapters import HTTPAdapter
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))

    if not os.path.exists(data_file):
        print(f"[{date_str}] Data file not found: {data_file}. Attempting auto-generation...")
        if not generate_race_data_for_date(date_str, jcd):
            return

    with open(data_file, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception as e:
            print(f"Error loading JSON: {e}")
            return

    changed = False

    from concurrent.futures import ThreadPoolExecutor
    from universal_oriten_engine import fetch_universal_oriten, TRANSCOSMOS_DOMAINS
    from test_correct_odds_parser import parse_boatrace_odds3t
    from generate_edogawa_dynamic import generate_bets_for_race

    # 0. 全レース確定結果の一括超高速プリフェッチ (Transcosmos系または公式resultlist)
    fast_results_map = {}
    if str(jcd).zfill(2) in TRANSCOSMOS_DOMAINS:
        dom = TRANSCOSMOS_DOMAINS[str(jcd).zfill(2)]
        ZEN_TO_HAN = str.maketrans("１２３４５６", "123456")
        try:
            w_resp = session.get(f"{dom}/sp/index.php?page=raceinfo-resultlist", headers={"User-Agent": "Mozilla/5.0 (iPhone)"}, timeout=6)
            if w_resp.status_code == 200:
                w_soup = BeautifulSoup(w_resp.text, "html.parser")
                for tr in w_soup.select("table tr, li, div.result_box"):
                    cells = [c.get_text(strip=True) for c in tr.select("th, td")]
                    if len(cells) >= 4 and "R" in cells[0]:
                        r_s = cells[0].replace("R", "").strip()
                        if r_s.isdigit():
                            r_num = int(r_s)
                            raw_c = cells[1].translate(ZEN_TO_HAN).replace(" ", "").replace("－", "-")
                            m_c = re.search(r"([1-6]-[1-6]-[1-6])", raw_c)
                            if m_c:
                                p_str = re.sub(r"[^\d]", "", cells[2])
                                fast_results_map[r_num] = {
                                    "comb": m_c.group(1),
                                    "payout": int(p_str) if p_str else 0,
                                    "popularity": re.sub(r"[^\d]", "", cells[3]),
                                    "kimarite": ""
                                }
        except Exception:
            pass

    # 公式 boatrace.jp の resultlist からも一括取得 (全国24場対応・1リクエストで全レース完了)
    if not fast_results_map:
        try:
            res_url = f"https://www.boatrace.jp/owpc/pc/race/resultlist?jcd={jcd}&hd={date_str}"
            res_resp = session.get(res_url, timeout=12)
            if res_resp.status_code == 200 and ("3連単" in res_resp.text or "1R" in res_resp.text):
                r_soup = BeautifulSoup(res_resp.text, "html.parser")
                for tr in r_soup.select("tbody tr"):
                    tds = tr.select("td")
                    if not tds or len(tds) < 3:
                        continue
                    txt0 = tds[0].get_text(strip=True)
                    m_r = re.search(r"^(\d{1,2})R", txt0)
                    if m_r:
                        r_num = int(m_r.group(1))
                        comb_raw = tds[1].get_text(strip=True)
                        m_comb = re.search(r"([1-6])\s*[-－]\s*([1-6])\s*[-－]\s*([1-6])", comb_raw)
                        if m_comb:
                            comb = f"{m_comb.group(1)}-{m_comb.group(2)}-{m_comb.group(3)}"
                            pay_raw = tds[2].get_text(strip=True)
                            m_pay = re.search(r"[\d,]+", pay_raw)
                            payout = int(m_pay.group(0).replace(",", "")) if m_pay else 0
                            fast_results_map[r_num] = {
                                "comb": comb,
                                "payout": payout,
                                "popularity": "",
                                "kimarite": ""
                            }
                # 決まり手反映
                for tr in r_soup.select("tbody tr"):
                    tds = tr.select("td")
                    if not tds:
                        continue
                    txt0 = tds[0].get_text(strip=True)
                    m_r = re.search(r"^(\d{1,2})R", txt0)
                    if m_r:
                        r_num = int(m_r.group(1))
                        row_text = tr.get_text(" ", strip=True)
                        for k in ["逃げ", "差し", "まくり", "捲り", "まくり差し", "捲り差し", "抜き", "恵まれ"]:
                            if k in row_text:
                                if r_num in fast_results_map:
                                    fast_results_map[r_num]["kimarite"] = k
                                break
        except Exception as e:
            print(f"resultlist error: {e}", flush=True)

    today_str = now.strftime("%Y%m%d")
    is_future = (date_str > today_str)

    def can_have_exhibition(race, now_dt):
        if is_future:
            return False
        if date_str < today_str:
            return True
        dl = race.get("deadline")
        if not dl or ":" not in dl:
            return True
        try:
            h, m = map(int, dl.split(":"))
            race_dt = now_dt.replace(hour=h, minute=m, second=0, microsecond=0)
            return now_dt >= (race_dt - datetime.timedelta(minutes=30))
        except Exception:
            return True

    def can_have_result(race, now_dt):
        if is_future:
            return False
        if date_str < today_str:
            return True
        dl = race.get("deadline")
        if not dl or ":" not in dl:
            return True
        try:
            h, m = map(int, dl.split(":"))
            race_dt = now_dt.replace(hour=h, minute=m, second=0, microsecond=0)
            return now_dt >= race_dt
        except Exception:
            return True

    def can_have_odds(race, now_dt):
        if is_future:
            return False
        if date_str < today_str:
            return True
        # 公式テレボートのオッズ提供開始は朝8:00以降
        if now_dt.hour < 8:
            return False
        is_fin = bool((race.get("official_result") and race["official_result"].get("comb")) or (r in fast_results_map))
        has_valid_odds = bool(race.get("official_odds_3t")) and all(
            m.get("odds") not in ["0.0", "0", None, ""] for m in race.get("main_bets", [])
        )
        return (not is_fin) or (not has_valid_odds)

    # 1. 公式3連単オッズおよびオリジナル展示データを必要なレースのみ並列取得
    races_needing_odds = []
    races_needing_oriten = []
    if not is_future:
        for r in range(1, 13):
            rk = f"r_{r}"
            if rk not in data:
                continue
            race = data[rk]
            is_fin = bool((race.get("official_result") and race["official_result"].get("comb")) or (r in fast_results_map))
            if can_have_odds(race, now):
                races_needing_odds.append(r)
            has_oriten = any(b.get("lap_time") and float(b.get("lap_time") or 0) > 0 for b in race.get("boats", []))
            if ((not has_oriten) or (not is_fin)) and can_have_exhibition(race, now):
                races_needing_oriten.append(r)

    fetched_odds_map = {}
    fetched_oriten_map = {}

    def _fetch_oriten_worker(rno):
        try:
            res_ori = fetch_universal_oriten(jcd, date_str, rno)
            if res_ori:
                return rno, res_ori
        except Exception:
            pass
        return rno, None

    if races_needing_oriten:
        with ThreadPoolExecutor(max_workers=6) as executor:
            for rno, ori_dict in executor.map(_fetch_oriten_worker, races_needing_oriten):
                if ori_dict:
                    fetched_oriten_map[rno] = ori_dict

    def _fetch_odds_worker(rno):
        u = f"https://www.boatrace.jp/owpc/pc/race/odds3t?rno={rno}&jcd={jcd}&hd={date_str}"
        try:
            resp_o = session.get(u, timeout=(3, 8))
            if resp_o.status_code == 200 and "データがありません" not in resp_o.text:
                parsed = parse_boatrace_odds3t(resp_o.text)
                if parsed and len(parsed) > 0:
                    return rno, parsed
        except Exception:
            pass
        return rno, None

    if races_needing_odds:
        with ThreadPoolExecutor(max_workers=6) as executor:
            for rno, parsed in executor.map(_fetch_odds_worker, races_needing_odds):
                if parsed:
                    fetched_odds_map[rno] = parsed
                    print(f"[{date_str} R{rno}] Fetched {len(parsed)} real odds", flush=True)

    # 1.1. beforeinfo & 確定結果の並列プリフェッチ
    fetched_beforeinfo_map = {}
    fetched_results_map = {}
    races_needing_bf = [
        r for r in range(1, 13)
        if f"r_{r}" in data and not all(b.get("ex_time") and b.get("ex_time") not in ["--.--", ""] for b in data[f"r_{r}"].get("boats", [])) and can_have_exhibition(data[f"r_{r}"], now)
    ]
    races_needing_res = [
        r for r in range(1, 13)
        if f"r_{r}" in data and not (data[f"r_{r}"].get("official_result") and data[f"r_{r}"]["official_result"].get("comb")) and (r not in fast_results_map) and can_have_result(data[f"r_{r}"], now)
    ]

    def _fetch_bf_worker(rno):
        u = f"https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno={rno}&jcd={jcd}&hd={date_str}"
        try:
            r_resp = session.get(u, timeout=(3, 8))
            if r_resp.status_code == 200 and ("展示タイム" in r_resp.text or "チルト" in r_resp.text):
                soup = BeautifulSoup(r_resp.text, "html.parser")
                b_map = {}
                for tbl in soup.select("table"):
                    txt = tbl.get_text()
                    if "展示タイム" in txt or "チルト" in txt:
                        for tr in tbl.select("tr"):
                            cells = [c.get_text(strip=True) for c in tr.select("th, td")]
                            if len(cells) >= 6 and cells[0] in ["1","2","3","4","5","6"]:
                                bnum = int(cells[0])
                                ext = cells[4]
                                tlt = cells[5]
                                if ext and ext not in ["", "\u00a0"]:
                                    b_map[bnum] = {"ex_time": ext, "tilt": tlt}
                if b_map:
                    return rno, b_map
        except Exception:
            pass
        return rno, None

    def _fetch_res_worker(rno):
        u = f"https://www.boatrace.jp/owpc/pc/race/raceresult?rno={rno}&jcd={jcd}&hd={date_str}"
        try:
            res_resp = session.get(u, timeout=(3, 8))
            if res_resp.status_code == 200 and "3連単" in res_resp.text:
                soup = BeautifulSoup(res_resp.text, "html.parser")
                combo, payout, pop, kimarite = None, 0, "", ""
                for tr in soup.select("table tr"):
                    cells = [c.get_text(strip=True) for c in tr.select("th, td")]
                    if len(cells) >= 4 and cells[0] == "3連単":
                        combo = cells[1]
                        payout = int(re.sub(r"[^\d]", "", cells[2]))
                        pop = cells[3]
                        break
                for tbl in soup.select("table"):
                    if "決まり手" in tbl.get_text():
                        td = tbl.select_one("tbody td")
                        if td:
                            kimarite = td.get_text(strip=True)
                            break
                if combo:
                    return rno, {"comb": combo, "payout": payout, "popularity": pop, "kimarite": kimarite}
        except Exception:
            pass
        return rno, None

    if races_needing_bf:
        with ThreadPoolExecutor(max_workers=6) as executor:
            for rno, b_map in executor.map(_fetch_bf_worker, races_needing_bf):
                if b_map:
                    fetched_beforeinfo_map[rno] = b_map

    if races_needing_res and str(jcd).zfill(2) not in TRANSCOSMOS_DOMAINS:
        with ThreadPoolExecutor(max_workers=6) as executor:
            for rno, res_obj in executor.map(_fetch_res_worker, races_needing_res):
                if res_obj:
                    fetched_results_map[rno] = res_obj

    for r in range(1, 13):
        rk = f"r_{r}"
        if rk not in data:
            continue

        race = data[rk]
        is_finished = bool(race.get("official_result") and race["official_result"].get("comb"))

        # 1.1. 並列取得したオリジナル展示＋展示タイム＋スタ展ST＋水面気象の即時反映
        w_ori = fetched_oriten_map.get(r)
        if w_ori:
            try:
                boats = race.get("boats", [])
                oriten_changed = False
                for b in boats:
                    b_num = b.get("num")
                    if b_num in w_ori:
                        ori = w_ori[b_num]
                        if ori.get("tilt") is not None and b.get("tilt") != str(ori["tilt"]):
                            b["tilt"] = str(ori["tilt"])
                            oriten_changed = True
                        if ori.get("ex_time") is not None:
                            ext_str = f"{ori['ex_time']:.2f}"
                            if b.get("ex_time") != ext_str:
                                b["ex_time"] = ext_str
                                oriten_changed = True
                        if ori.get("ex_st") and b.get("ex_st") != ori["ex_st"]:
                            b["ex_st"] = ori["ex_st"]
                            oriten_changed = True
                        if ori.get("weather") and isinstance(ori["weather"], dict) and len(ori["weather"]) > 0:
                            w_dict = race.get("weather") if isinstance(race.get("weather"), dict) else {}
                            for wk, wv in ori["weather"].items():
                                if wv and w_dict.get(wk) != wv:
                                    w_dict[wk] = wv
                                    oriten_changed = True
                            race["weather"] = w_dict

                        s_val = ori.get("straight")
                        if b.get("straight_time") != s_val:
                            b["straight"] = s_val
                            b["straight_time"] = s_val if s_val else 0.0
                            oriten_changed = True

                        t_val = ori.get("turn")
                        if b.get("turn_time") != t_val:
                            b["turn"] = t_val
                            b["turn_time"] = t_val if t_val else 0.0
                            oriten_changed = True

                        l_val = ori.get("lap")
                        if b.get("lap_time") != l_val:
                            b["lap"] = l_val
                            b["lap_time"] = l_val if l_val else 0.0
                            oriten_changed = True

                valid_straights = [b["straight_time"] for b in boats if b.get("straight_time") and b["straight_time"] > 0]
                min_straight = min(valid_straights) if valid_straights else 999.0
                for b in boats:
                    b["is_best_straight"] = bool(b.get("straight_time") and abs(b["straight_time"] - min_straight) < 0.001)

                valid_turns = [b["turn_time"] for b in boats if b.get("turn_time") and b["turn_time"] > 0]
                min_turn = min(valid_turns) if valid_turns else 999.0
                for b in boats:
                    b["is_best_turn"] = bool(b.get("turn_time") and abs(b["turn_time"] - min_turn) < 0.001)

                valid_laps = [b["lap_time"] for b in boats if b.get("lap_time") and b["lap_time"] > 0]
                min_lap = min(valid_laps) if valid_laps else 999.0
                for b in boats:
                    b["is_best_lap"] = bool(b.get("lap_time") and abs(b["lap_time"] - min_lap) < 0.001)

                if oriten_changed:
                    changed = True
                    print(f"[{date_str} R{r}] Injected live exhibition & oriten data!", flush=True)
            except Exception as e_ori:
                print(f"Error applying live oriten for R{r}: {e_ori}", flush=True)

        # 1.2. 並列プリフェッチしたboatrace.jpのbeforeinfoを参照
        if r in fetched_beforeinfo_map:
            b_map = fetched_beforeinfo_map[r]
            for bnum, binfo in b_map.items():
                if bnum <= len(race["boats"]):
                    target_b = race["boats"][bnum - 1]
                    if target_b.get("ex_time") != binfo["ex_time"] or target_b.get("tilt") != binfo["tilt"]:
                        target_b["ex_time"] = binfo["ex_time"]
                        target_b["tilt"] = binfo["tilt"]
                        changed = True

        # 1.5. 取得した3連単オッズの反映と、展示・オリ展・オッズ統合再計算
        if r in fetched_odds_map:
            real_odds = fetched_odds_map[r]
            if race.get("official_odds_3t") != real_odds:
                race["official_odds_3t"] = real_odds
                changed = True
        else:
            real_odds = race.get("official_odds_3t", {})

        has_bad_ana = any(
            a.get("comb") in ["1-2-3", "1-3-2"] or (0.0 < float(a.get("odds") or 0) < 25.0)
            for a in race.get("ana_bets", [])
        )
        if (not is_finished) or has_bad_ana:
            try:
                new_pred = generate_bets_for_race(r, race["boats"], stadium=race.get("stadium", "若松"), real_odds=real_odds)
                comb_probs = new_pred.get("comb_probs", {})
                new_m = [
                    {
                        "comb": c, "b1": c.split("-")[0], "b2": c.split("-")[1], "b3": c.split("-")[2],
                        "odds": f"{float(real_odds.get(c, 0.0)):.1f}" if real_odds.get(c) else "0.0",
                        "prob": f"{comb_probs.get(c, 1.5):.1f}%",
                        "desc": d
                    }
                    for c, d in new_pred["main_bets_raw"]
                ]
                new_a = [
                    {
                        "comb": c, "b1": c.split("-")[0], "b2": c.split("-")[1], "b3": c.split("-")[2],
                        "odds": f"{float(real_odds.get(c, 0.0)):.1f}" if real_odds.get(c) else "0.0",
                        "prob": f"{comb_probs.get(c, 0.5):.1f}%",
                        "desc": d
                    }
                    for c, d in new_pred["ana_bets_raw"]
                ]
                if race.get("main_bets") != new_m or race.get("ana_bets") != new_a:
                    race["main_bets"] = new_m
                    race["ana_bets"] = new_a
                    race["grade"] = new_pred["grade"]
                    race["grade_badge"] = new_pred["grade_badge"]
                    race["grade_title"] = new_pred["grade_title"]
                    race["core_scenario"] = new_pred["core_scenario"]
                    race["physics_detail"] = new_pred["physics_detail"]
                    changed = True
                # 既に確定済みのレースで買い目を再正規化した場合は的中フラグも同期
                if race.get("official_result") and race["official_result"].get("comb"):
                    res_c = race["official_result"]["comb"]
                    res_p = race["official_result"].get("payout", 0)
                    for m in race["main_bets"]:
                        m["is_hit"] = (m["comb"] == res_c)
                        if m["is_hit"]:
                            m["payout"] = res_p
                    for a in race["ana_bets"]:
                        a["is_hit"] = (a["comb"] == res_c)
                        if a["is_hit"]:
                            a["payout"] = res_p
                    if any(m.get("is_hit") for m in race["main_bets"]):
                        race["official_result"]["hit_status"] = "[HIT] 本線的中！"
                    elif any(a.get("is_hit") for a in race["ana_bets"]):
                        race["official_result"]["hit_status"] = "[HIT] 穴的中！"
                    else:
                        race["official_result"]["hit_status"] = "不的中"
            except Exception as e_recalc:
                print(f"Error recalculating R{r}: {e_recalc}")
        elif real_odds:
            for m in race.get("main_bets", []):
                comb = m.get("comb")
                if comb in real_odds:
                    odd_s = f"{float(real_odds[comb]):.1f}"
                    if m.get("odds") != odd_s:
                        m["odds"] = odd_s
                        changed = True
            for a in race.get("ana_bets", []):
                comb = a.get("comb")
                if comb in real_odds:
                    odd_s = f"{float(real_odds[comb]):.1f}"
                    if a.get("odds") != odd_s:
                        a["odds"] = odd_s
                        changed = True

        # 2. 確定結果のチェック＆即時保存（wmb.jpプリフェッチまたは個別result API）
        if not race.get("official_result") or not race["official_result"].get("comb"):
            combo = ""
            payout = 0
            pop = ""
            kimarite = ""

            if r in fast_results_map:
                combo = fast_results_map[r]["comb"]
                payout = fast_results_map[r]["payout"]
                pop = fast_results_map[r]["popularity"]
                kimarite = fast_results_map[r].get("kimarite", "")
                # 決まり手補完 (wmb.jp ajax req=result)
                if str(jcd).zfill(2) in TRANSCOSMOS_DOMAINS:
                    try:
                        dom = TRANSCOSMOS_DOMAINS[str(jcd).zfill(2)]
                        kr_resp = session.get(
                            f"{dom}/sp/ajax/ajax_yosou.php?targetday={date_str}&race={r}&req=result&run=0",
                            headers={"User-Agent": "Mozilla/5.0 (iPhone)", "X-Requested-With": "XMLHttpRequest", "Referer": f"{dom}/sp/"},
                            timeout=4
                        )
                        if kr_resp.status_code == 200:
                            kr_txt = BeautifulSoup(kr_resp.text, "html.parser").get_text(" ", strip=True)
                            for km_cand in ["逃げ", "逃　げ", "差し", "差　し", "まくり差し", "まくり", "抜き", "抜　き", "恵まれ"]:
                                if km_cand in kr_txt:
                                    kimarite = km_cand.replace("　", "")
                                    break
                    except Exception:
                        pass

            if not combo and r in fetched_results_map:
                f_res = fetched_results_map[r]
                combo = f_res["comb"]
                payout = f_res["payout"]
                pop = f_res["popularity"]
                kimarite = f_res["kimarite"]

            if combo:
                is_main_hit = any(m.get("comb") == combo for m in race.get("main_bets", []))
                is_ana_hit = any(a.get("comb") == combo for a in race.get("ana_bets", []))
                hit_status = "不的中"
                if is_main_hit:
                    hit_status = "[HIT] 本線的中！"
                elif is_ana_hit:
                    hit_status = "[HIT] 穴的中！"

                race["official_result"] = {
                    "comb": combo,
                    "payout": payout,
                    "popularity": pop,
                    "kimarite": kimarite,
                    "hit_status": hit_status
                }
                changed = True
                for m in race.get("main_bets", []):
                    m["is_hit"] = (m["comb"] == combo)
                    if m["is_hit"]:
                        m["payout"] = payout
                for a in race.get("ana_bets", []):
                    a["is_hit"] = (a["comb"] == combo)
                    if a["is_hit"]:
                        a["payout"] = payout
                print(f"[{date_str} R{r}] Official Result Confirmed: {combo} ({payout}円) -> {hit_status}")

    if changed:
        print(f"[{date_str}] New data detected! Updating JSON, learning DB, and regenerating HTML...")
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 蓄積学習データベース（会場別・選手別・モーター別実走統計）を即時自動更新
        try:
            from accumulated_learning_engine import build_and_save_learned_stats
            build_and_save_learned_stats()
        except Exception as e:
            print(f"Error updating accumulated learning stats: {e}")
        
        # HTML再生成（cmdのクォート構文バグを完全根絶するため直接モジュール実行）
        try:
            import build_dark_high_contrast_dashboard
            build_dark_high_contrast_dashboard.main()
            print("Dashboard rebuilt successfully.")
        except Exception as e:
            print(f"Error rebuilding dashboard: {e}")

        # クラウド同期（バックグラウンド非同期実行でレスポンス遅延をゼロ化）
        sync_script = os.path.join(BASE_DIR, "quick_sync.py")
        if os.path.exists(sync_script) and not os.environ.get("RENDER"):
            try:
                import quick_sync
                import threading
                threading.Thread(target=quick_sync.main, daemon=True).start()
                print("Quick sync launched in background.")
            except Exception as e:
                print(f"Error launching quick sync: {e}")

        # メール自動送信（非同期）
        try:
            import send_live_wakamatsu_email
            import threading
            threading.Thread(target=send_live_wakamatsu_email.send_wakamatsu_report, daemon=True).start()
            print("Summary email launched in background.")
        except Exception as e:
            print(f"Error launching email: {e}")
        
        print(f"[{date_str}] Pipeline cycle completed successfully!")
    else:
        print(f"[{date_str}] No changes detected.")

    # 3. 翌日（明日）の出走表が発表されているかをチェック＆自動事前生成
    tomorrow = now + datetime.timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%Y%m%d")
    tomorrow_vcfg = get_venue_config(tomorrow_str)
    tomorrow_file = os.path.join(DATA_DIR, f"{tomorrow_vcfg['prefix']}_{tomorrow_str}_data.json")

    # 16時以降、またはまだ明日のファイルが存在しない場合にチェック
    if not os.path.exists(tomorrow_file) and now.hour >= 16:
        print(f"Checking if tomorrow ({tomorrow_str} {tomorrow_vcfg['stadium']}) racelist is published...")
        try:
            success = generate_race_data_for_date(tomorrow_str, tomorrow_vcfg["jcd"])
            if success:
                print(f"Tomorrow ({tomorrow_str}) races generated automatically! Rebuilding dashboard...")
                import build_dark_high_contrast_dashboard
                build_dark_high_contrast_dashboard.main()
                import quick_sync
                quick_sync.main()
        except Exception as e:
            print(f"Error checking/generating tomorrow racelist: {e}")

    # 4. GitHub Actions 自爆停止コードは完全撤廃（常時稼働を維持）

    # 5. Pipeline completion
    print(f"[{date_str}] Live monitor check done.")

if __name__ == "__main__":
    run_pipeline()

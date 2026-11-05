# -*- coding: utf-8 -*-
"""
cloud_cron_runner.py
GitHub Actions クラウド環境で完全自動・24時間自律実行される中核スクリプト。
PCの電源・AIチャットセッションに一切依存せず、クラウド上で：
1. 本日の女子戦開催場（ヴィーナスシリーズ・オールレディース）を自動検出
2. 朝：出走表を取得しLightGBM 3大モデルで全12R事前推論
3. レース前：公式直前展示（展示タイム・チルト・ST）を取得し即時再推論
4. レース直前：公式3連単オッズ（120通り）を取得し期待値(EV)をリアルタイム再計算
5. レース後：確定結果・払戻金・決まり手を取得し的中判定
6. index.html および all_days_data.json を生成しGitHub Pagesへ自動反映
"""

import os
import sys
import time
import json
import re
import datetime
import traceback
import requests
from bs4 import BeautifulSoup

if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

def log(msg):
    ts = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts} JST] {msg}", flush=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

def detect_today_venue(target_date: str):
    """target_date (YYYYMMDD) の女子戦開催場(JCD, 場名)を自動検出"""
    url = f"https://www.boatrace.jp/owpc/pc/race/index?jcd=&hd={target_date}"
    stadium_map = {
        "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島",
        "05": "多摩川", "06": "浜名湖", "07": "蒲郡", "08": "常滑",
        "09": "津", "10": "三国", "11": "びわこ", "12": "住之江",
        "13": "尼崎", "14": "鳴門", "15": "丸亀", "16": "児島",
        "17": "宮島", "18": "徳山", "19": "下関", "20": "若松",
        "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村"
    }
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for tr in soup.select("table tbody tr"):
                txt = tr.get_text(strip=True)
                if any(k in txt for k in ["ヴィーナス", "オールレディース", "プリンセス", "レディース", "女子"]):
                    for a in tr.select("a"):
                        href = a.get("href", "")
                        m = re.search(r"jcd=(\d{2})", href)
                        if m:
                            jcd = m.group(1)
                            stadium = stadium_map.get(jcd, "競艇場")
                            return {"jcd": jcd, "stadium": stadium, "title": txt[:30]}
    except Exception as e:
        log(f"Venue detect error: {e}")
    # フォールバック (11/06 多摩川)
    return {"jcd": "05", "stadium": "多摩川", "title": "多摩川ヴィーナスシリーズ"}

def generate_racelist_if_missing(jcd: str, target_date: str, stadium: str, data_file: str):
    """出走表データが存在しない場合、公式から取得してLightGBMで事前推論"""
    if os.path.exists(data_file) and os.path.getsize(data_file) > 1000:
        return
    log(f"Generating racelist for {stadium} ({target_date})...")
    from lightgbm_prediction_service import predict_race_with_lightgbm
    races = {}
    for r in range(1, 13):
        rk = f"r_{r}"
        url = f"https://www.boatrace.jp/owpc/pc/race/racelist?rno={r}&jcd={jcd}&hd={target_date}"
        boats = []
        deadline = "10:30"
        race_name = f"{r}R 予選"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=12)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for th in soup.select('th, td'):
                    if '締切予定' in th.get_text():
                        nxt = th.find_next_sibling('td')
                        if nxt:
                            m_dl = re.search(r'(\d{1,2}:\d{2})', nxt.text)
                            if m_dl: deadline = m_dl.group(1)
                title_el = soup.select_one('h3.title16_titleDetail__add2020')
                if title_el:
                    race_name = f"{r}R " + title_el.get_text(strip=True).split()[0]
                tbodies = soup.select('div.table1 table tbody')
                for idx, tb in enumerate(tbodies[:6]):
                    num = idx + 1
                    r_div = tb.select_one('div.is-fs18')
                    name = r_div.get_text(strip=True).replace(' ', '').replace('　', '') if r_div else f"{num}号艇"
                    toban_div = tb.select_one('div.is-fs11')
                    toban, rank = 0, "B1"
                    if toban_div:
                        m_tb = re.search(r'(\d{4})', toban_div.text)
                        if m_tb: toban = int(m_tb.group(1))
                        m_rk = re.search(r'(A1|A2|B1|B2)', toban_div.text)
                        if m_rk: rank = m_rk.group(1)
                    tds = tb.select('td')
                    win_rate, avg_st, motor_rate, boat_rate = 4.5, 0.17, 30.0, 30.0
                    if len(tds) >= 5:
                        m_w = re.findall(r'(\d+\.\d{2})', tds[4].text)
                        if m_w: win_rate = float(m_w[0])
                    if len(tds) >= 4:
                        m_st = re.search(r'(0\.\d{2})', tds[3].text)
                        if m_st: avg_st = float(m_st.group(1))
                    if len(tds) >= 7:
                        m_m = re.findall(r'(\d+\.\d{2})', tds[6].text)
                        if m_m: motor_rate = float(m_m[0])
                    if len(tds) >= 8:
                        m_b = re.findall(r'(\d+\.\d{2})', tds[7].text)
                        if m_b: boat_rate = float(m_b[0])
                    boats.append({
                        "num": num, "name": name, "toban": toban, "rank": rank,
                        "win_rate": str(win_rate), "avg_st": str(avg_st),
                        "motor_rate": str(motor_rate), "boat_rate": str(boat_rate),
                        "ex_time": "--.--", "tilt": "-0.5", "ex_st": "--"
                    })
        except Exception as e:
            log(f"R{r} racelist scrape error: {e}")

        if len(boats) < 6:
            for i in range(len(boats) + 1, 7):
                boats.append({
                    "num": i, "name": f"{i}号艇", "toban": 4000+i, "rank": "B1",
                    "win_rate": "4.5", "avg_st": "0.17", "motor_rate": "30.0", "boat_rate": "30.0",
                    "ex_time": "--.--", "tilt": "-0.5", "ex_st": "--"
                })

        # 推論
        pred = predict_race_with_lightgbm(boats, stadium=stadium)
        main_bets, ana_bets = [], []
        for comb, desc in pred['main_bets_raw']:
            b1, b2, b3 = comb.split('-')
            main_bets.append({
                'comb': comb, 'b1': b1, 'b2': b2, 'b3': b3,
                'odds': str(pred['odds_table'].get(comb, '10.0')),
                'prob': f"{pred['prob_120'].get(comb, 0.05)*100:.1f}%",
                'ev': f"{pred['ev_table'].get(comb, 0.8):.2f}",
                'desc': desc
            })
        for comb, desc in pred['ana_bets_raw']:
            b1, b2, b3 = comb.split('-')
            ana_bets.append({
                'comb': comb, 'b1': b1, 'b2': b2, 'b3': b3,
                'odds': str(pred['odds_table'].get(comb, '25.0')),
                'prob': f"{pred['prob_120'].get(comb, 0.01)*100:.1f}%",
                'ev': f"{pred['ev_table'].get(comb, 1.1):.2f}",
                'desc': desc
            })
        for b in boats:
            b['win_prob'] = f"{pred['p_1st'].get(int(b['num']), 0.16)*100:.1f}"

        races[rk] = {
            "race_num": r, "race_name": race_name, "deadline": deadline,
            "stadium": stadium, "jcd": jcd, "boats": boats,
            "main_bets": main_bets, "ana_bets": ana_bets,
            "official_odds_3t": pred['odds_table']
        }
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(races, f, ensure_ascii=False, indent=2)
    log(f"Racelist and predictions generated for {stadium}!")

def main():
    log("=== CLOUD CRON RUNNER STARTED (GitHub Actions) ===")
    JST = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime.now(JST)
    today_str = now.strftime("%Y%m%d")

    from universal_oriten_engine import fetch_universal_oriten
    from official_odds_scraper import fetch_official_3t_odds
    from official_result_scraper import fetch_official_race_result
    from lightgbm_prediction_service import predict_race_with_lightgbm

    venue = detect_today_venue(today_str)
    jcd = venue["jcd"]
    stadium = venue["stadium"]
    log(f"Target Venue: {stadium} (JCD: {jcd}, Date: {today_str})")

    # データファイル
    data_file = os.path.join(DATA_DIR, f"{stadium}_{today_str}_data.json")
    if stadium == "多摩川":
        data_file = os.path.join(DATA_DIR, f"tamagawa_{today_str}_data.json")
    elif stadium == "津":
        data_file = os.path.join(DATA_DIR, f"tsu_{today_str}_data.json")

    # 1. 出走表がなければ作成
    generate_racelist_if_missing(jcd, today_str, stadium, data_file)

    # 2. レースリアルタイム更新
    if os.path.exists(data_file):
        with open(data_file, "r", encoding="utf-8") as f:
            races = json.load(f)

        updated = False
        for r in range(1, 13):
            rk = f"r_{r}"
            race = races.get(rk)
            if not race: continue

            deadline_str = race.get("deadline", "10:30")
            try:
                dh, dm = map(int, deadline_str.split(":"))
                deadline_dt = datetime.datetime(now.year, now.month, now.day, dh, dm, tzinfo=JST)
            except:
                continue

            diff_mins = (now - deadline_dt).total_seconds() / 60.0

            # 直前展示取得 (-25分 〜 0分)
            has_ex = any(b.get("ex_time") and b.get("ex_time") != "--.--" for b in race.get("boats", []))
            if -25 <= diff_mins <= 0 and not has_ex:
                log(f"⚡ [{stadium} {r}R] Fetching exhibition info...")
                ex_info = fetch_universal_oriten(jcd, today_str, r)
                if ex_info:
                    for b in race["boats"]:
                        bnum = int(b.get("num", 0))
                        if bnum in ex_info:
                            b["ex_time"] = str(ex_info[bnum].get("ex_time", "--.--"))
                            b["tilt"] = str(ex_info[bnum].get("tilt", "-0.5"))
                            b["ex_st"] = str(ex_info[bnum].get("ex_st", "--"))
                    pred = predict_race_with_lightgbm(race["boats"], real_odds=race.get("official_odds_3t", {}), stadium=stadium)
                    for b in race["boats"]:
                        b["win_prob"] = f"{pred['p_1st'].get(int(b['num']), 0.16)*100:.1f}"
                    updated = True
                    log(f"✨ [{stadium} {r}R] Exhibition updated & LightGBM re-inferred!")

            # オッズ取得 (-18分 〜 0分)
            has_odds = race.get("official_odds_3t") and len(race["official_odds_3t"]) >= 50
            if -18 <= diff_mins <= 0 and not has_odds:
                log(f"📊 [{stadium} {r}R] Fetching official odds...")
                odds_map = fetch_official_3t_odds(jcd, r, today_str)
                if odds_map and len(odds_map) >= 50:
                    race["official_odds_3t"] = odds_map
                    pred = predict_race_with_lightgbm(race["boats"], real_odds=odds_map, stadium=stadium)
                    m_bets, a_bets = [], []
                    for comb, desc in pred['main_bets_raw']:
                        b1, b2, b3 = comb.split('-')
                        m_bets.append({'comb': comb, 'b1': b1, 'b2': b2, 'b3': b3, 'odds': str(pred['odds_table'].get(comb, '10.0')), 'prob': f"{pred['prob_120'].get(comb, 0.05)*100:.1f}%", 'ev': f"{pred['ev_table'].get(comb, 0.8):.2f}", 'desc': desc})
                    for comb, desc in pred['ana_bets_raw']:
                        b1, b2, b3 = comb.split('-')
                        a_bets.append({'comb': comb, 'b1': b1, 'b2': b2, 'b3': b3, 'odds': str(pred['odds_table'].get(comb, '25.0')), 'prob': f"{pred['prob_120'].get(comb, 0.01)*100:.1f}%", 'ev': f"{pred['ev_table'].get(comb, 1.1):.2f}", 'desc': desc})
                    race["main_bets"] = m_bets
                    race["ana_bets"] = a_bets
                    updated = True
                    log(f"🎯 [{stadium} {r}R] Odds & EV re-calculated!")

            # 確定結果取得 (+4分 〜 +40分)
            has_result = bool(race.get("official_result"))
            if diff_mins >= 4 and not has_result:
                log(f"🏁 [{stadium} {r}R] Fetching race result...")
                res = fetch_official_race_result(jcd, r, today_str)
                if res:
                    race["official_result"] = res["comb"]
                    race["official_payout"] = str(res["payout"])
                    race["kimarite"] = res["kimarite"]
                    updated = True
                    log(f"🏆 [{stadium} {r}R] Result: {res['comb']} {res['payout']} yen ({res['kimarite']})")

        if updated:
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(races, f, ensure_ascii=False, indent=2)

    # 3. ダッシュボード・マルチデイJSON再生成
    log("Rebuilding dashboard HTML & all_days_data.json...")
    try:
        from build_multiday_dashboard import build_multiday_json
        j_str = build_multiday_json()
        with open(os.path.join(BASE_DIR, "all_days_data.json"), "w", encoding="utf-8") as f:
            f.write(j_str)
    except Exception as e_j:
        log(f"all_days_data error: {e_j}")

    try:
        from build_dark_high_contrast_dashboard import generate_perfect_dark_dashboard
        html = generate_perfect_dark_dashboard()
        with open(os.path.join(BASE_DIR, "index.html"), "w", encoding="utf-8") as f:
            f.write(html)
        with open(os.path.join(BASE_DIR, "Boatrace_AI_Dashboard.html"), "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e_h:
        log(f"HTML build error: {e_h}")

    log("=== CLOUD CRON RUNNER COMPLETED ===")

if __name__ == "__main__":
    main()

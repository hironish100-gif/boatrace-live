# -*- coding: utf-8 -*-
"""
cloud_cron_runner.py
GitHub Actions クラウドランナー上で完全自律動作するスクリプト。
PCの電源やAntigravityに一切依存せず、24時間クラウド上で自動更新を完結させる。
"""

import os
import sys
import json
import datetime
import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://www.boatrace.jp/"
}

def log(msg):
    ts = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def main():
    log("=== CLOUD CRON RUNNER STARTED ===")
    JST = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime.now(JST)
    today_str = now.strftime("%Y%m%d")
    tomorrow = now + datetime.timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%Y%m%d")
    cur_hm = now.hour * 100 + now.minute

    from generate_edogawa_dynamic import get_venue_config, generate_race_data_for_date

    today_vcfg = get_venue_config(today_str)
    tomorrow_vcfg = get_venue_config(tomorrow_str)

    today_file = os.path.join(DATA_DIR, f"{today_vcfg['prefix']}_{today_str}_data.json")
    tomorrow_file = os.path.join(DATA_DIR, f"{tomorrow_vcfg['prefix']}_{tomorrow_str}_data.json")

    # 1. 夜間フェーズ (20:30〜23:59): 翌日の出走表・AI予想を自動生成
    if 2030 <= cur_hm <= 2359 or cur_hm < 200:
        if not os.path.exists(tomorrow_file):
            log(f"[NIGHT] Checking racelist for tomorrow ({tomorrow_str} {tomorrow_vcfg['stadium']})...")
            try:
                success = generate_race_data_for_date(tomorrow_str, tomorrow_vcfg["jcd"])
                if success:
                    log(f"[NIGHT SUCCESS] Tomorrow ({tomorrow_str}) races generated!")
            except Exception as e:
                log(f"[NIGHT ERROR] {e}")

    # 2. 朝フェーズ (06:00〜14:00): 今日のデータが存在しない場合は自動生成
    elif 600 <= cur_hm <= 1400:
        if not os.path.exists(today_file):
            log(f"[MORNING] Generating today races ({today_str} {today_vcfg['stadium']})...")
            try:
                generate_race_data_for_date(today_str, today_vcfg["jcd"])
            except Exception as e:
                log(f"[MORNING ERROR] {e}")

    # 3. レース開催中フェーズ (14:00〜21:30): 確定結果・オッズの取得
    if 1400 <= cur_hm <= 2200:
        log(f"[LIVE] Fetching results & odds for {today_str} (jcd={today_vcfg['jcd']})...")
        try:
            from pipeline_edogawa_live import run_pipeline
            run_pipeline(today_str)
        except Exception as e:
            log(f"[LIVE ERROR] {e}")

    # 4. ダッシュボード再構築
    log("Rebuilding dashboard...")
    try:
        import build_dark_high_contrast_dashboard
        build_dark_high_contrast_dashboard.main()
    except Exception as e:
        log(f"Dashboard build error: {e}")

    # 5. all_days_data.json の生成
    log("Generating all_days_data.json...")
    try:
        from build_multiday_dashboard import build_multiday_json
        j_str = build_multiday_json()
        with open(os.path.join(BASE_DIR, "all_days_data.json"), "w", encoding="utf-8") as f:
            f.write(j_str)
    except Exception as e:
        log(f"all_days_data error: {e}")

    # 6. GitHub Pages への同期
    # GitHub Actions のステップ (git add -A && git commit && git push) が自動反映するため
    # スクリプト内での API による重複アップロードは行わない
    log("Files updated. Ready for Git Commit & Push step.")

    log("=== CLOUD CRON RUNNER COMPLETED ===")

if __name__ == "__main__":
    main()

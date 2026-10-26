# -*- coding: utf-8 -*-
"""
cloud_cron_runner.py
GitHub Actions クラウドランナーで24時間完全自律稼働するスクリプト。
PCの電源・ローカル環境に一切依存せず、出走表・AI予想・レース確定結果・オッズを自動同期。
"""

import os
import sys
import json
import datetime
import requests
from bs4 import BeautifulSoup

if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

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

    from generate_edogawa_dynamic import get_venue_config
    from fast_generate_today import generate_for_date_fast

    today_vcfg = get_venue_config(today_str)
    tomorrow_vcfg = get_venue_config(tomorrow_str)

    today_file = os.path.join(DATA_DIR, f"{today_vcfg['prefix']}_{today_str}_data.json")
    tomorrow_file = os.path.join(DATA_DIR, f"{tomorrow_vcfg['prefix']}_{tomorrow_str}_data.json")

    # 1. 最優先チェック: 本日(today_str)のデータが存在しない場合は時間帯を問わず即座に生成
    if not os.path.exists(today_file) or os.path.getsize(today_file) < 500:
        log(f"[TODAY MISSING] Generating today's races ({today_str} {today_vcfg['stadium']})...")
        try:
            success = generate_for_date_fast(today_str, today_vcfg["jcd"])
            if success:
                log(f"[TODAY SUCCESS] Today ({today_str}) races generated successfully!")
        except Exception as e:
            log(f"[TODAY ERROR] {e}")

    # 2. 翌日チェック: 16時以降、または夜間(20:00〜)に翌日のデータが存在しない場合は生成
    if (cur_hm >= 1600 or cur_hm < 200) and (not os.path.exists(tomorrow_file) or os.path.getsize(tomorrow_file) < 500):
        log(f"[NIGHT] Checking racelist for tomorrow ({tomorrow_str} {tomorrow_vcfg['stadium']})...")
        try:
            success = generate_for_date_fast(tomorrow_str, tomorrow_vcfg["jcd"])
            if success:
                log(f"[NIGHT SUCCESS] Tomorrow ({tomorrow_str}) races generated!")
        except Exception as e:
            log(f"[NIGHT ERROR] {e}")

    # 3. レース開催フェーズ (14:00〜22:00): 確定結果・オッズの取得
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

    # 6. GitHub Actions の後続ステップ (git add -A && git commit && git push) が自動反映
    log("Files updated. Ready for Git Commit & Push step.")
    log("=== CLOUD CRON RUNNER COMPLETED ===")

if __name__ == "__main__":
    main()

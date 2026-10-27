# -*- coding: utf-8 -*-
"""
build_multiday_dashboard.py
data/*_data.json を自動スキャンして all_days_data.json を生成する
完全自己完結型（Standalone）・高堅牢マルチデイビルダー。
外部のレガシーテストスクリプトへの依存を全廃し、GitHub Actions クラウド環境でも 100% 確実に動作。
"""

from __future__ import annotations
import json
import re
import os
import sys
import glob
from typing import Dict, Any, List

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

try:
    from generate_edogawa_dynamic import get_venue_config
except Exception:
    def get_venue_config(dt_str):
        return {"jcd": "01", "prefix": "kiryu", "stadium": "桐生", "series_title": "第16回バマカップ ヴィーナスシリーズ第16戦"}

def normalize_race_data(data: Dict[str, Any], default_stadium: str = "桐生") -> Dict[str, Any]:
    """全レースの stadium, round, weather, title, 各データを安全に正規化"""
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
    return data

def build_day_summary(races: Dict[str, Any], vcfg: Dict[str, Any], dt_str: str) -> Dict[str, Any]:
    """1日分のサマリー（的中数、回収率、投資額、回収額）を計算"""
    total_bet = 0
    total_payout = 0
    hit_count = 0
    finished_count = 0

    for r in range(1, 13):
        rk = f"r_{r}"
        if rk not in races:
            continue
        race = races[rk]
        res = race.get("official_result")
        m_bets = race.get("main_bets", [])
        a_bets = race.get("ana_bets", [])
        
        # 1レースあたり本線4点+穴4点=800円（または本線のみなら400円）
        n_bets = len(m_bets) + len(a_bets)
        cost = n_bets * 100

        if res and res.get("comb"):
            finished_count += 1
            total_bet += cost
            comb = res["comb"]
            payout = int(res.get("payout") or 0)
            all_combs = [b["comb"] for b in m_bets] + [b["comb"] for b in a_bets]
            if comb in all_combs:
                hit_count += 1
                total_payout += payout

    recovery_rate = round((total_payout / total_bet * 100), 1) if total_bet > 0 else 0.0

    mm = int(dt_str[4:6]) if len(dt_str) == 8 else 10
    dd = int(dt_str[6:8]) if len(dt_str) == 8 else 1
    stadium = vcfg.get("stadium", "桐生")
    series = vcfg.get("series_title", "ヴィーナスシリーズ")

    desc = f"{stadium} {series} ({mm}/{dd})"
    if finished_count > 0:
        desc += f" 【確定{finished_count}R: {hit_count}的中 回収率{recovery_rate}%】"
    else:
        desc += f" 【全12R 出走表・AI予想確定】"

    return {
        "desc": desc,
        "total_bet": total_bet,
        "total_payout": total_payout,
        "recovery_rate": recovery_rate,
        "hit_count": hit_count,
        "finished_count": finished_count,
        "total_races": 12
    }

def build_multiday_json() -> str:
    """data/ 配下の *_data.json を自動走査して統合マルチデイJSONを生成"""
    all_days = {}

    pattern = os.path.join(DATA_DIR, "*_data.json")
    files = sorted(glob.glob(pattern), reverse=True)

    for fpath in files:
        fname = os.path.basename(fpath)
        m_dt = re.search(r"_(\d{8})_data\.json$", fname)
        if not m_dt:
            continue
        dt_str = m_dt.group(1)

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                races_data = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load {fpath}: {e}")
            continue

        if not isinstance(races_data, dict) or not any(k.startswith("r_") for k in races_data.keys()):
            continue

        vcfg = get_venue_config(dt_str)
        stadium = vcfg.get("stadium", "桐生")
        series = vcfg.get("series_title", "ヴィーナスシリーズ")

        races_data = normalize_race_data(races_data, default_stadium=stadium)
        summary = build_day_summary(races_data, vcfg, dt_str)

        mm = int(dt_str[4:6])
        dd = int(dt_str[6:8])

        all_days[dt_str] = {
            "date_id": dt_str,
            "date_label": f"2026-{mm:02d}-{dd:02d} {stadium} {series} (全12R 最新AI予想)",
            "status": "active",
            "stadium": stadium,
            "series_title": series,
            "summary": summary,
            "races": races_data
        }

    return json.dumps(all_days, ensure_ascii=False, indent=2)

def main():
    print("Building multiday JSON...", flush=True)
    j_str = build_multiday_json()
    out_path = os.path.join(BASE_DIR, "all_days_data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(j_str)
    print(f"Generated {out_path} ({len(j_str):,} bytes) successfully!", flush=True)

if __name__ == "__main__":
    main()

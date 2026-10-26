# -*- coding: utf-8 -*-
"""
send_today_dashboard.py
毎朝の開催日にスマホへ送信する「最新AI予想＆全12R自信度ランキング配信エンジン」
・全12レースの自信度（AI算出の的中確率）ランキング表をHTML本文に完全内包
・レース特性（AI評価）も一目瞭然
・最新ダッシュボードHTMLを添付
"""

import os
import sys
import json
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

JST = timezone(timedelta(hours=9))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

SENDER_EMAIL = os.environ.get("GMAIL_SENDER", "hironish100@gmail.com")
APP_PASSWORD = os.environ.get("GMAIL_PWD", "znjb ahiw eimr peqx")
raw_recipients = os.environ.get("GMAIL_RECIPIENT", "hironish100@gmail.com,hironish7890@gmail.com")
RECIPIENTS = [r.strip() for r in raw_recipients.split(",") if r.strip()]

def get_target_date():
    now_jst = datetime.now(JST)
    return now_jst.strftime("%Y%m%d")

def generate_morning_summary_data(target_date="20261004"):
    data_path = os.path.join(DATA_DIR, f"shimonoseki_{target_date}_data.json")
    if not os.path.exists(data_path):
        data_path = os.path.join(DATA_DIR, "shimonoseki_20261004_data.json")

    with open(data_path, "r", encoding="utf-8") as f:
        races_data = json.load(f)

    traits_1004 = {
        1: "本線(28.8%)＋5号艇・6号艇連動(14.5%)",
        2: "相手枠分散傾向",
        3: "本線筋が極めて明瞭（最も自信度が高い）",
        4: "最も難解（大穴狙い配分）",
        5: "展開波乱の可能性大",
        6: "軸艇堅調・相手枠絞り込み",
        7: "センター勢の競り合い懸念",
        8: "本線主導",
        9: "波乱含み",
        10: "混戦模様",
        11: "本線中心",
        12: "予選最終戦・イン逃げ軸の信頼度高"
    }

    race_rankings = []
    for rno in range(1, 13):
        rk = f"r_{rno}"
        race = races_data.get(rk, {})
        m_prob = sum(float(b.get("prob", 0)) for b in race.get("main_bets", []))
        a_prob = sum(float(b.get("prob", 0)) for b in race.get("ana_bets", []))
        tot_prob = round(m_prob + a_prob, 1)

        trait = traits_1004.get(rno, "")
        if not trait:
            if tot_prob >= 55: trait = "本線筋が極めて明瞭（最も自信度が高い）"
            elif tot_prob >= 50: trait = "軸艇堅調・相手枠絞り込み"
            elif tot_prob >= 44: trait = "本線中心"
            elif tot_prob >= 40: trait = "本線主導"
            elif tot_prob >= 36: trait = "相手枠分散傾向"
            elif tot_prob >= 34: trait = "混戦模様"
            else: trait = "最も難解（大穴狙い配分）"

        race_rankings.append({
            "rno": rno,
            "total_prob": tot_prob,
            "main_prob": round(m_prob, 1),
            "ana_prob": round(a_prob, 1),
            "trait": trait
        })

    # 確率順にソートして順位を付与
    race_rankings.sort(key=lambda x: x["total_prob"], reverse=True)
    for rank, r in enumerate(race_rankings, 1):
        r["rank"] = rank

    # レース番号順に戻したリストも保持
    return race_rankings

def build_morning_email_html(target_date, rankings):
    formatted_date = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}"
    
    # ランキングテーブルの行生成
    table_rows = ""
    for r in rankings:
        rank_badge = f"<span style='font-weight: 900; color: #f59e0b;'>{r['rank']}位</span>"
        if r['rank'] == 1:
            rank_badge = "<span style='font-weight: 900; color: #ef4444; font-size: 15px;'>🥇 1位</span>"
        elif r['rank'] == 2:
            rank_badge = "<span style='font-weight: 900; color: #38bdf8; font-size: 14px;'>🥈 2位</span>"
        elif r['rank'] == 3:
            rank_badge = "<span style='font-weight: 900; color: #22c55e; font-size: 14px;'>🥉 3位</span>"

        prob_style = "color: #f8fafc; font-weight: bold;"
        if r['total_prob'] >= 50:
            prob_style = "color: #38bdf8; font-weight: 900; font-size: 14px;"

        table_rows += f"""
        <tr style='border-bottom: 1px solid #334155;'>
            <td style='padding: 8px; text-align: center;'>{rank_badge}</td>
            <td style='padding: 8px; text-align: center; font-weight: 900; font-size: 14px; color: #f8fafc;'>{r['rno']}R</td>
            <td style='padding: 8px; text-align: right; font-family: monospace; {prob_style}'>{r['total_prob']:.1f}%</td>
            <td style='padding: 8px; font-size: 11px; color: #94a3b8; font-family: monospace;'>本線:{r['main_prob']:.1f}%<br>穴:{r['ana_prob']:.1f}%</td>
            <td style='padding: 8px; font-size: 12px; color: #cbd5e1; font-weight: 600;'>{r['trait']}</td>
        </tr>
        """

    top1 = rankings[0]
    top2 = rankings[1]
    top3 = rankings[2]

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #020617; color: #f8fafc; padding: 16px; margin: 0;">
  <div style="max-width: 680px; margin: auto; background-color: #0f172a; border-radius: 12px; padding: 24px; border: 1px solid #1e293b; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
    
    <!-- ヘッダー -->
    <div style="border-bottom: 2px solid #38bdf8; padding-bottom: 14px; margin-bottom: 20px;">
      <span style="background-color: #0369a1; color: #e0f2fe; font-size: 11px; font-weight: 800; padding: 3px 8px; rounded: 4px; border-radius: 4px;">朝イチ配信</span>
      <h2 style="color: #38bdf8; margin: 8px 0 4px 0; font-size: 20px;">🚤【Boatrace AI】{formatted_date} 下関ヴィーナスシリーズ第14戦</h2>
      <p style="font-size: 13px; color: #94a3b8; margin: 0;">
        4日目・予選最終日（ナイター） 全12レース自信度ランキング＆最新予想ダッシュボード
      </p>
    </div>

    <!-- 本日の推奨ハイライト -->
    <div style="background-color: #1e293b; border-left: 4px solid #38bdf8; border-radius: 6px; padding: 14px; margin-bottom: 24px;">
      <div style="color: #38bdf8; font-weight: 900; font-size: 14px; margin-bottom: 6px;">🎯 本日のAI勝負どころ（自信度上位TOP3）:</div>
      <div style="font-size: 13px; color: #e2e8f0; line-height: 1.6;">
        ・<strong style="color: #f8fafc;">第1位【{top1['rno']}R】</strong>: 的中期待度 <strong style="color: #38bdf8;">{top1['total_prob']:.1f}%</strong> — {top1['trait']}<br>
        ・<strong style="color: #f8fafc;">第2位【{top2['rno']}R】</strong>: 的中期待度 <strong style="color: #38bdf8;">{top2['total_prob']:.1f}%</strong> — {top2['trait']}<br>
        ・<strong style="color: #f8fafc;">第3位【{top3['rno']}R】</strong>: 的中期待度 <strong style="color: #38bdf8;">{top3['total_prob']:.1f}%</strong> — {top3['trait']}
      </div>
    </div>

    <!-- 全12レース自信度ランキングテーブル -->
    <h3 style="color: #f8fafc; font-size: 15px; margin-bottom: 10px; display: flex; align-items: center; gap: 6px;">
      📊 全12レース 自信度（AI算出の的中確率）ランキング一覧
    </h3>
    <table style="width: 100%; font-size: 12px; border-collapse: collapse; margin-bottom: 24px; background-color: #020617; border-radius: 8px; overflow: hidden; border: 1px solid #1e293b;">
      <thead>
        <tr style="background-color: #1e293b; color: #94a3b8; text-align: left;">
          <th style="padding: 10px 8px; text-align: center; width: 55px;">順位</th>
          <th style="padding: 10px 8px; text-align: center; width: 45px;">R</th>
          <th style="padding: 10px 8px; text-align: right; width: 65px;">的中期待</th>
          <th style="padding: 10px 8px; width: 80px;">内訳</th>
          <th style="padding: 10px 8px;">レース特性（AIの評価）</th>
        </tr>
      </thead>
      <tbody>
        {table_rows}
      </tbody>
    </table>

    <!-- 補足説明 -->
    <div style="background-color: rgba(15, 23, 42, 0.8); border: 1px solid #334155; border-radius: 8px; padding: 14px; font-size: 12px; color: #cbd5e1; line-height: 1.6; margin-bottom: 20px;">
      <strong>💡 活用のポイント:</strong><br>
      ・<strong>上位レース（3R, 12R等）</strong>: 本線黄金ライン（1号艇軸）の信頼度が高く、資金配分による手堅い回収を狙えます。<br>
      ・<strong>中堅レース（1R等）</strong>: 前日実戦足上位の外枠（5・6コース）が連動する中穴配当（3,000円〜4,000円台）を射程に入れています。<br>
      ・<strong>下位レース（4R, 5R等）</strong>: 展開波乱の可能性が高いため、穴4点の高配当・EV重視フォーメーションを推奨します。
    </div>

    <p style="font-size: 12px; color: #94a3b8; line-height: 1.5; margin-bottom: 20px;">
      添付のHTMLファイル（Boatrace_AI_Dashboard.html）をタップまたはPCで開いていただくと、全12レースの出走表、新概念データ、展示タイム連動、買い目詳細をダークモードUIで閲覧できます。
    </p>

    <div style="font-size: 11px; color: #64748b; border-top: 1px solid #1e293b; padding-top: 12px; text-align: center;">
      ※本メールは Boatrace AI 自動予想・自律配信システムより毎朝お届けしています。
    </div>
  </div>
</body>
</html>
"""
    return html

def send_morning_mail():
    target_date = get_target_date()
    rankings = generate_morning_summary_data(target_date)
    html_content = build_morning_email_html(target_date, rankings)

    today_dt = datetime.now(JST)
    today_short = today_dt.strftime("%m/%d")
    subject = f"🚤【Boatrace AI】{today_short} 下関 ヴィーナスシリーズ第14戦 (全12R) 自信度ランキング＆最新予想ダッシュボード"

    dashboard_path = r"C:\Users\hiron\Desktop\Boatrace_AI_Dashboard.html"
    if not os.path.exists(dashboard_path):
        dashboard_path = os.path.join(BASE_DIR, "boatrace_dashboard.html")

    file_bytes = None
    if os.path.exists(dashboard_path):
        with open(dashboard_path, "rb") as f:
            file_bytes = f.read()

    for recipient in RECIPIENTS:
        try:
            print(f"Sending morning report to {recipient}...")
            msg = MIMEMultipart()
            msg["From"] = SENDER_EMAIL
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            if file_bytes:
                part = MIMEApplication(file_bytes, Name="Boatrace_AI_Dashboard.html")
                part["Content-Disposition"] = 'attachment; filename="Boatrace_AI_Dashboard.html"'
                msg.attach(part)

            server = smtplib.SMTP("smtp.gmail.com", 587, timeout=20)
            server.starttls()
            server.login(SENDER_EMAIL, APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, recipient, msg.as_string())
            server.quit()
            print(f"[SUCCESS] {recipient} 送信完了！")
        except Exception as e:
            print(f"[ERROR] {recipient} 送信失敗: {e}")

def send_mail(custom_subject: str = None):
    # 下位互換エイリアス
    send_morning_mail()

if __name__ == "__main__":
    send_morning_mail()

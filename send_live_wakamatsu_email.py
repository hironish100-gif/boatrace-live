# -*- coding: utf-8 -*-
import os
import sys
import json
import glob
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

SENDER_EMAIL = os.environ.get("GMAIL_SENDER", "hironish100@gmail.com")
APP_PASSWORD = os.environ.get("GMAIL_PWD", "znjb ahiw eimr peqx")
raw_recipients = os.environ.get("GMAIL_RECIPIENT", "hironish100@gmail.com,hironish7890@gmail.com")
RECIPIENTS = [r.strip() for r in raw_recipients.split(",") if r.strip()]

def get_latest_data_file(target_date: str = None):
    if target_date:
        for f in glob.glob(os.path.join(DATA_DIR, f"*_{target_date}_data.json")):
            return f, target_date
    
    # 確定結果が最も多く存在する最新日付のファイルを探索
    candidates = sorted(glob.glob(os.path.join(DATA_DIR, "*_202610*_data.json")), reverse=True)
    best_file = None
    best_date = None
    for cand in candidates:
        try:
            with open(cand, "r", encoding="utf-8") as fp:
                cd = json.load(fp)
            fin_count = sum(1 for rk in cd if cd[rk].get("official_result") and cd[rk]["official_result"].get("comb"))
            if fin_count > 0:
                # 日付抽出
                import re
                m = re.search(r"_(\d{8})_data\.json", cand)
                dt_str = m.group(1) if m else datetime.datetime.now().strftime("%Y%m%d")
                return cand, dt_str
        except Exception:
            pass
    if candidates:
        m = re.search(r"_(\d{8})_data\.json", candidates[0])
        dt_str = m.group(1) if m else datetime.datetime.now().strftime("%Y%m%d")
        return candidates[0], dt_str
    return None, None

def send_wakamatsu_report(target_date: str = None, force: bool = False):
    data_file, date_str = get_latest_data_file(target_date)
    if not data_file or not os.path.exists(data_file):
        print(f"Data file not found for date: {target_date}")
        return False

    with open(data_file, "r", encoding="utf-8") as f:
        d = json.load(f)

    # 日付・場名解析
    sample_race = next(iter(d.values())) if d else {}
    stadium = sample_race.get("stadium", "若松")
    m_date = f"{date_str[4:6]}/{date_str[6:8]}"
    day_num = int(date_str[6:8]) - 12 if "20261013" <= date_str <= "20261018" else 1

    hits = []
    rows = ""
    tot_pay = 0
    r_count = 0
    for r in range(1, 13):
        rk = f"r_{r}"
        race = d.get(rk, {})
        res = race.get("official_result")
        if res and res.get("comb"):
            r_count += 1
            comb = res.get("comb")
            pay = int(res.get("payout") or 0)
            status = res.get("hit_status", "不的中")
            is_hit = "HIT" in status
            if is_hit:
                tot_pay += pay
                hits.append(f"{r}R: {comb} ({pay:,}円)")
                b_style = "color:#22c55e;font-weight:bold;"
            else:
                b_style = "color:#94a3b8;"
            rows += f"""
            <tr style="border-bottom: 1px solid #334155;">
              <td style="padding:8px;text-align:center;font-weight:bold;">{r}R</td>
              <td style="padding:8px;font-weight:bold;font-family:monospace;">{comb}</td>
              <td style="padding:8px;text-align:right;font-family:monospace;">{pay:,}円</td>
              <td style="padding:8px;{b_style}">{status}</td>
            </tr>
            """

    last_sent_file = os.path.join(DATA_DIR, f"last_sent_{date_str}_rcount.txt")
    last_sent = 0
    if os.path.exists(last_sent_file):
        try:
            last_sent = int(open(last_sent_file).read().strip())
        except Exception:
            pass

    if not force and (r_count == 0 or r_count <= last_sent):
        print(f"[{date_str}] No new race results to send (r_count={r_count}, last_sent={last_sent})")
        return False

    inv = r_count * 800
    rec = round((tot_pay / inv) * 100, 1) if inv > 0 else 0
    balance = tot_pay - inv
    bal_sign = "+" if balance >= 0 else ""
    bal_color = "#22c55e" if balance >= 0 else "#f87171"

    status_tag = "最終確定版" if r_count == 12 else f"1R〜{r_count}R速報"
    subject = f"🌙【Boatrace AI】{m_date} {stadium}{day_num}日目 {status_tag}（的中{len(hits)}本・回収率{rec}%）"

    body = f"""<!DOCTYPE html>
<html lang="ja">
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 16px;">
  <div style="max-width: 650px; margin: auto; background-color: #1e293b; border-radius: 12px; padding: 24px; border: 1px solid #334155;">
    <h2 style="color: #38bdf8; margin-top: 0;">🌙 {stadium}ヴィーナスS {day_num}日目（{m_date}）全成績レポート</h2>
    <p style="font-size: 14px; color: #cbd5e1; line-height: 1.6;">
      {m_date}の全レース確定結果とAI予想の的中照合レポートをお届けします。
    </p>

    <div style="background-color: #0f172a; border-radius: 8px; padding: 16px; margin: 20px 0; border: 1px solid #38bdf8;">
      <table style="width: 100%; font-size: 14px; border-collapse: collapse;">
        <tr>
          <td style="color: #94a3b8; padding: 4px;">消化レース</td>
          <td style="font-weight: bold; color: #f8fafc; text-align: right;">{r_count} / 12 レース</td>
        </tr>
        <tr>
          <td style="color: #94a3b8; padding: 4px;">的中数</td>
          <td style="font-weight: bold; color: #22c55e; text-align: right; font-size: 18px;">{len(hits)} / {r_count} R ({round(len(hits)/r_count*100,1) if r_count else 0}%)</td>
        </tr>
        <tr>
          <td style="color: #94a3b8; padding: 4px;">投資総額</td>
          <td style="font-weight: bold; color: #f8fafc; text-align: right;">{inv:,} 円 (各R 800円)</td>
        </tr>
        <tr>
          <td style="color: #94a3b8; padding: 4px;">払戻総額</td>
          <td style="font-weight: bold; color: #22c55e; text-align: right; font-size: 16px;">{tot_pay:,} 円</td>
        </tr>
        <tr>
          <td style="color: #94a3b8; padding: 4px;">収支バランス</td>
          <td style="font-weight: bold; color: {bal_color}; text-align: right; font-size: 16px;">{bal_sign}{balance:,} 円</td>
        </tr>
        <tr>
          <td style="color: #94a3b8; padding: 4px;">本日の回収率</td>
          <td style="font-weight: bold; color: {bal_color}; text-align: right; font-size: 20px;">{rec}%</td>
        </tr>
      </table>
    </div>

    <h3 style="color: #f8fafc; border-bottom: 2px solid #38bdf8; padding-bottom: 6px;">📋 全レース結果照合一覧</h3>
    <table style="width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 10px;">
      <thead>
        <tr style="background-color: #0f172a; color: #94a3b8;">
          <th style="padding: 8px;">R</th>
          <th style="padding: 8px;">確定出目</th>
          <th style="padding: 8px; text-align: right;">払戻金</th>
          <th style="padding: 8px;">判定</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>

    <div style="margin-top: 24px; text-align: center;">
      <a href="https://hironish100-gif.github.io/boatrace-ai/" style="background: linear-gradient(135deg, #0284c7, #2563eb); color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; display: inline-block;">
        🚀 クラウド予想ダッシュボードを開く
      </a>
    </div>

    <p style="font-size: 11px; color: #64748b; margin-top: 24px; text-align: center;">
      ※本メールは Boatrace AI Cloud Autonomous Pipeline より自動配信されています。
    </p>
  </div>
</body>
</html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL
        msg["To"] = ", ".join(RECIPIENTS)
        msg.attach(MIMEText(body, "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())

        print(f"[SUCCESS] Email report sent successfully for {date_str} to {RECIPIENTS}!")
        with open(last_sent_file, "w") as f:
            f.write(str(r_count))
        return True
    except Exception as e:
        print(f"[ERROR] Failed to send email: {e}")
        return False

if __name__ == "__main__":
    t_date = sys.argv[1] if len(sys.argv) > 1 else None
    send_wakamatsu_report(t_date, force=True)

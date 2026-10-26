"""
predict_slit_formation.py
【自己学習・選手別F偏差データベース連動版】
過去の枠番別ST傾向・ST順位・F所持状況・機力伸び足・直前スタ展アジャストに加え、
1. 選手個々の「スタ展F時の本番平均ST偏差」データベース（racer_st_f_bias.json）
2. 確定結果からのオンライン誤差フィードバック重み（st_learning_weights.json）
を統合したリアルタイム自己学習型スリット隊形推論エンジン
"""

import os
import json
from typing import Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
RACER_F_BIAS_FILE = os.path.join(DATA_DIR, "racer_st_f_bias.json")
ST_WEIGHTS_FILE = os.path.join(DATA_DIR, "st_learning_weights.json")

def _get_learning_weights() -> Dict[str, Any]:
    if os.path.exists(ST_WEIGHTS_FILE):
        try:
            with open(ST_WEIGHTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "course_biases": {
            "1": -0.02, "2": 0.00, "3": -0.01, "4": -0.02, "5": +0.02, "6": +0.03
        },
        "default_f_adjust": +0.04
    }

def _get_racer_f_bias_db() -> Dict[str, Any]:
    if os.path.exists(RACER_F_BIAS_FILE):
        try:
            with open(RACER_F_BIAS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def compute_comprehensive_predicted_st(
    boat: Dict[str, Any],
    exhibition_st_str: Optional[str] = None,
    oriten_info: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    選手固有のスタ展F偏差データベースおよび学習済み重みを適用して本番STを推論
    """
    weights = _get_learning_weights()
    racer_f_db = _get_racer_f_bias_db()

    num = int(boat.get("num", 1))
    name = boat.get("name", "")
    rank = boat.get("rank", "B1")
    fl = boat.get("fl", "F0")
    
    # 1. 通算平均ST
    try:
        avg_st = float(boat.get("avg_st", 0.16))
    except Exception:
        avg_st = 0.16

    # 2. 級別・実力によるスタート巧者バイアス
    rank_bias = -0.01 if "A1" in rank else (0.01 if "B2" in rank else 0.0)
    
    # 3. 学習済みコース別バイアス（オンライン学習で更新された動的重み）
    learned_c_biases = weights.get("course_biases", {})
    c_bias = float(learned_c_biases.get(str(num), 0.0))

    # チルト跳ね・伸び型選手のカド攻め特権（堀之内・高田・藤原など）
    is_nobi_specialist = any(kw in name for kw in ["高田", "堀之内", "藤原", "山崎"])
    if is_nobi_specialist and num in [3, 4]:
        c_bias -= 0.015

    # 4. F所持ペナルティ（心理バイアス）
    if "F2" in fl:
        f_penalty = +0.08
    elif "F1" in fl:
        f_penalty = +0.035
    else:
        f_penalty = -0.005

    # 5. 機力・直線タイム補正（スリット付近の伸び足）
    motor_bias = 0.0
    if oriten_info:
        try:
            straight = float(oriten_info.get("straight", 7.35))
            if straight <= 7.30:
                motor_bias = -0.015
            elif straight >= 7.38:
                motor_bias = +0.01
        except Exception:
            pass

    # 6. 【核心】直前スタ展アジャスト推論（選手固有データベース連動）
    ex_adjust = 0.0
    clean_ex_st = None
    tendency_note = ""

    if exhibition_st_str:
        clean_str = exhibition_st_str.strip()
        try:
            if "F" in clean_str:
                clean_ex_st = clean_str
                # 選手個別のスタ展F時本番ST偏差DBを参照
                if name in racer_f_db:
                    p_bias = racer_f_db[name]
                    # 選手固有の平均Fアジャスト値を使用！
                    ex_adjust = float(p_bias.get("avg_f_adjust", 0.04))
                    tendency_note = f"【学習済み: {p_bias.get('tendency', '')}】"
                else:
                    # 未学習の選手はモデル学習済みデフォルトを使用
                    ex_adjust = float(weights.get("default_f_adjust", 0.04))
            else:
                val = float(clean_str.replace(".", "0."))
                clean_ex_st = clean_str
                if val <= 0.03:
                    ex_adjust = +0.025
                elif val <= 0.12:
                    ex_adjust = -0.015
                elif val >= 0.22:
                    ex_adjust = +0.02
        except Exception:
            pass

    # 総合予測STの算出（ベイズ統合）
    expected_st = avg_st + rank_bias + c_bias + f_penalty + motor_bias + ex_adjust
    
    # 現実的な範囲にクリップ（.08 〜 .35：ドカ遅れも許容できるよう拡張）
    pred_st_clamped = max(0.08, min(0.35, expected_st))
    pred_st_str = f".{int(round(pred_st_clamped * 100)):02d}"

    # スリット先行深度ブロック（基準0.26からの前進度）
    depth_blocks = int(round(max(2, min(14, (0.26 - pred_st_clamped) * 60.0))))

    # スリット戦術寸評の自動生成
    if tendency_note:
        slit_note = f"{tendency_note} (予測ST {pred_st_str})"
    elif "F1" in fl or "F2" in fl:
        slit_note = f"F所持で本番慎重アジャスト (予測ST {pred_st_str})"
    elif num == 1:
        slit_note = f"イン先マイ集中・スリット先行狙い (予測ST {pred_st_str})"
    elif num == 4 and is_nobi_specialist:
        slit_note = f"4カドから超抜伸びで一気に絞り込む (予測ST {pred_st_str})"
    elif clean_ex_st and "F" in clean_ex_st:
        slit_note = f"スタ展Fで本番はレバー放り安全アジャスト (予測ST {pred_st_str})"
    elif pred_st_clamped <= 0.12:
        slit_note = f"スリット鋭く踏み込み隊形優位 (予測ST {pred_st_str})"
    elif pred_st_clamped >= 0.20:
        slit_note = f"スタート大幅立ち遅れ懸念 (予測ST {pred_st_str})"
    else:
        slit_note = f"枠なり手堅くスリット追従 (予測ST {pred_st_str})"

    return {
        "pred_st": pred_st_str,
        "pred_st_num": round(pred_st_clamped, 2),
        "depth_blocks": depth_blocks,
        "ex_st_label": clean_ex_st if clean_ex_st else "--",
        "slit_note": slit_note
    }

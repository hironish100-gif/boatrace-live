import requests
from bs4 import BeautifulSoup
import json
import re

def parse_boatrace_odds3t(html: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.select('table')
    if len(tables) < 2:
        return {}
    table = tables[1]
    rows = table.select('tr')
    if len(rows) < 21:
        return {}

    all_odds = {}
    current_b2 = [None] * 7  # 1..6

    for r_idx in range(1, 21):
        tr = rows[r_idx]
        cells = tr.select('th, td')
        cell_idx = 0
        for b1 in range(1, 7):
            if cell_idx >= len(cells):
                break
            # もし2着セルが含まれる行（(r_idx - 1) % 4 == 0）なら3つのセル
            if (r_idx - 1) % 4 == 0:
                b2_str = cells[cell_idx].text.strip()
                cell_idx += 1
                try:
                    current_b2[b1] = int(b2_str)
                except:
                    pass
            
            if cell_idx >= len(cells):
                break
            b3_str = cells[cell_idx].text.strip()
            cell_idx += 1

            if cell_idx >= len(cells):
                break
            odd_str = cells[cell_idx].text.strip().replace(',', '')
            cell_idx += 1

            try:
                b2 = current_b2[b1]
                b3 = int(b3_str)
                odd_val = float(odd_str)
                comb = f"{b1}-{b2}-{b3}"
                all_odds[comb] = odd_val
            except Exception as e:
                pass

    return all_odds

# テスト
if __name__ == "__main__":
    url = "https://www.boatrace.jp/owpc/pc/race/odds3t?rno=1&jcd=19&hd=20261006"
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
    odds = parse_boatrace_odds3t(r.text)
    print("Parsed odds count:", len(odds))
    print("1-2-3:", odds.get("1-2-3"))
    print("1-2-4:", odds.get("1-2-4"))
    print("1-2-5:", odds.get("1-2-5"))
    print("1-2-6:", odds.get("1-2-6"))
    print("1-3-2:", odds.get("1-3-2"))
    print("2-1-3:", odds.get("2-1-3"))
    print("6-5-4:", odds.get("6-5-4"))

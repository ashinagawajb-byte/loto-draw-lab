"""Register recent published draws without changing seeded search checkpoints."""
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

from worker import query

URL = "https://takarakuji.rakuten.co.jp/backnumber/loto{game}/"
JST = timezone(timedelta(hours=9))
MAX_BYTES = 1_000_000


class ResultsTables(HTMLParser):
    """Read only the number tables and retain their row labels."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = self.row = self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table" and "tblNumberGuid" in (dict(attrs).get("class") or "").split():
            self.table = {}
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("th", "td") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.table[self.row[0]] = [value for value in self.row[1:] if value]
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def parse_results(html, game, today):
    k, b, limit = {6: (6, 1, 43), 7: (7, 2, 37)}[game]
    parser = ResultsTables()
    parser.feed(html)
    parser.close()
    results = {}
    for table in parser.tables:
        if "回号" not in table or not table.get("本数字"):
            continue
        round_text, = table["回号"]
        date_text, = table["抽せん日"]
        match = re.fullmatch(r"第([0-9]{1,5})回", round_text)
        draw_date = datetime.strptime(date_text, "%Y/%m/%d").date()
        if not match or int(match[1]) < 1 or draw_date > today:
            raise ValueError(f"LOTO{game}: invalid round or draw date")
        round_no = int(match[1])
        main_text, bonus_text = table["本数字"], table["ボーナス数字"]
        if (len(main_text) != k or len(bonus_text) != b
                or any(not re.fullmatch(r"[0-9]{1,2}", n) for n in main_text)
                or any(not re.fullmatch(r"\([0-9]{1,2}\)|[0-9]{1,2}", n) for n in bonus_text)):
            raise ValueError(f"LOTO{game} round {round_no}: invalid result format")
        main = sorted(map(int, main_text))
        bonus = sorted(int(n.strip("()")) for n in bonus_text)
        if len(set(main + bonus)) != k + b or any(not 1 <= n <= limit for n in main + bonus):
            raise ValueError(f"LOTO{game} round {round_no}: invalid numbers")
        if round_no in results and results[round_no] != (main, bonus):
            raise ValueError(f"LOTO{game} round {round_no}: conflicting published results")
        results[round_no] = main, bonus
    if not results:
        raise ValueError(f"LOTO{game}: no published results parsed")
    return results


def fetch_results(game):
    url = URL.format(game=game)
    with urllib.request.urlopen(url, timeout=12) as response:
        if response.geturl() != url:
            raise ValueError(f"LOTO{game}: result source redirected")
        blob = response.read(MAX_BYTES + 1)
    if len(blob) > MAX_BYTES:
        raise ValueError(f"LOTO{game}: result page exceeded size limit")
    return parse_results(blob.decode("utf-8"), game, datetime.now(JST).date())


def register(game, results):
    rounds = [str(round_no) for round_no in sorted(results)]
    placeholders = ",".join("?" for _ in rounds)
    registered = query(f"""
        SELECT d.round, d.main, d.bonus, j.round AS job
        FROM draws d LEFT JOIN jobs j USING (game,round)
        WHERE d.game=? AND d.round IN ({placeholders})""", [game, *rounds])
    existing = {row["round"]: row for row in registered}

    def matches(row, main, bonus):
        return sorted(json.loads(row["main"])) == main and sorted(json.loads(row["bonus"])) == bonus

    added = []
    for round_no in rounds:
        main, bonus = results[int(round_no)]
        row = existing.get(round_no)
        if row is None:
            query("INSERT OR IGNORE INTO draws(game,round,main,bonus) VALUES(?,?,?,?)",
                  [game, round_no, json.dumps(main), json.dumps(bonus)])
            row, = query("SELECT main,bonus FROM draws WHERE game=? AND round=?", [game, round_no])
        if not matches(row, main, bonus):
            raise ValueError(f"LOTO{game} round {round_no}: published result conflicts with stored result")
        if row.get("job") is None:
            inserted = query("INSERT OR IGNORE INTO jobs(game,round) VALUES(?,?) RETURNING round",
                             [game, round_no])
            added.extend(item["round"] for item in inserted)
    return added


def main():
    failed = False
    for game in (6, 7):
        try:
            results = fetch_results(game)
            added = register(game, results)
            print(f"LOTO{game}: checked through round {max(results)}; newly registered: {', '.join(added) or 'none'}")
        except Exception as exc:
            print(f"::warning title=Draw registration::LOTO{game}: {exc}")
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())

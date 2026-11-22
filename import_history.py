"""Bulk import public LOTO6/7 history into Cloudflare D1. Safe to rerun."""
import csv, json, os, pathlib
from worker import query

ROOT = pathlib.Path(__file__).resolve().parent
BATCH = 10

def import_csv(path, game):
    k, maxnum, b = (6, 43, 1) if game == 6 else (7, 37, 2)
    items = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                round_no = int(row["round"])
                main = [int(row[f"n{i}"]) for i in range(1, k + 1)]
                bonus = [int(row[f"bonus{i}"]) for i in range(1, b + 1)]
                values = main + bonus
                if round_no <= 0 or len(set(values)) != len(values) or not all(1 <= n <= maxnum for n in values):
                    raise ValueError("out-of-range or repeated number")
                items.append((game, str(round_no), json.dumps(main), json.dumps(bonus)))
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError(f"{path.name}: invalid row {len(items) + 2}: {exc}") from exc
    if len({row[1] for row in items}) != len(items):
        raise ValueError(f"{path.name}: duplicated round numbers")
    existing = query("SELECT COUNT(*) AS c FROM draws WHERE game=?", [game])
    count = int(existing[0]["c"]) if existing else 0
    if count >= len(items):
        print(f"History already present for LOTO{game}: {count} rows; skipping duplicate upload")
    else:
        for start in range(0, len(items), BATCH):
            batch = items[start : start + BATCH]
            values = ",".join(["(?,?,?,?)"] * len(batch))
            flat = [value for row in batch for value in row]
            query(f"INSERT OR IGNORE INTO draws(game,round,main,bonus) VALUES {values}", flat)
    # Avoid scanning all historic draws and re-checking jobs on every hourly run.
    # Both counts must agree with source rows before we skip the job backfill.
    job_rows = query("SELECT COUNT(*) AS c FROM jobs WHERE game=?", [game])
    job_count = int(job_rows[0]["c"]) if job_rows else 0
    if job_count < len(items) or count < len(items):
        # Uses existing schema defaults and never resets scanned progress.
        query("INSERT OR IGNORE INTO jobs(game,round) SELECT game,round FROM draws WHERE game=?", [game])
        print(f"Reconciled missing jobs for LOTO{game}")
    print(f"Imported/verified {len(items)} rows from {path}")

def run():
    found = False
    for game in (6, 7):
        path = ROOT / "data" / f"loto{game}.csv"
        if path.is_file():
            found = True
            import_csv(path, game)
        else:
            print(f"Waiting for {path.relative_to(ROOT)}")
    if not found:
        print("No history CSV files installed yet; no changes.")

if __name__ == "__main__":
    run()

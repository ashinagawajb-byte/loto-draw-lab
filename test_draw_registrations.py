from datetime import date
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from sync_draw_registrations import parse_results, register

ROOT = Path(__file__).resolve().parent


def table(round_no, main, bonus):
    rows = {
        "回号": [f"第{round_no}回"],
        "抽せん日": ["2026/11/23"],
        "本数字": main,
        "ボーナス数字": bonus,
    }
    return '<table class="tblType02 tblNumberGuid">' + "".join(
        f"<tr><th>{label}</th>" + "".join(f"<td><span>{n}</span></td>" for n in values) + "</tr>"
        for label, values in rows.items()
    ) + "</table>"


class RegistrationTests(unittest.TestCase):
    def test_latest_both_games(self):
        self.assertEqual(
            parse_results(table("2157", [13, 20, 22, 34, 38, 39], ["(33)", ""]), 6, date(2026, 11, 24)),
            {2157: ([13, 20, 22, 34, 38, 39], [33])},
        )
        self.assertEqual(
            parse_results(table("0704", [3, 4, 14, 16, 28, 36, 37], ["(21)", "(30)"]), 7, date(2026, 11, 24)),
            {704: ([3, 4, 14, 16, 28, 36, 37], [21, 30])},
        )
        with self.assertRaises(ValueError):
            parse_results(table("2157", [13, 20, 22, 34, 38, 39], ["(39)"]), 6, date(2026, 11, 24))
        with self.assertRaises(ValueError):
            parse_results(table("2157", [13, 20, 22, 34, 38, 39], ["(33)"]), 6, date(2026, 11, 22))

    def test_retry_and_job_backfill_preserve_existing_progress(self):
        with sqlite3.connect(":memory:") as db:
            db.row_factory = sqlite3.Row
            db.executescript((ROOT / "schema.sql").read_text())
            db.execute("INSERT INTO jobs(game,round,scanned,exact_count) VALUES(6,'2156',6000,1)")
            old = ([1, 5, 23, 26, 35, 42], [8])
            new = ([13, 20, 22, 34, 38, 39], [33])
            db.execute("INSERT INTO draws VALUES(6,'2156',?,?)", tuple(map(json.dumps, old)))

            def query(sql, args):
                return list(map(dict, db.execute(sql, args).fetchall()))

            with patch("sync_draw_registrations.query", side_effect=query):
                self.assertEqual(register(6, {2156: old, 2157: new}), ["2157"])
                self.assertEqual(register(6, {2156: old, 2157: new}), [])
                self.assertEqual(query("SELECT round,scanned,exact_count FROM jobs ORDER BY round", []), [
                    {"round": "2156", "scanned": 6000, "exact_count": 1},
                    {"round": "2157", "scanned": 0, "exact_count": 0},
                ])
                db.execute("DELETE FROM jobs WHERE round='2157'")
                self.assertEqual(register(6, {2157: new}), ["2157"])
                with self.assertRaises(ValueError):
                    register(6, {2157: (new[0], [40])})
                self.assertEqual(query("SELECT bonus FROM draws WHERE round='2157'", []), [{"bonus": "[33]"}])

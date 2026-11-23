"""Unit tests for frozen Site Analyzer five-ticket comparison intake."""
import csv
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from compare_models import load_site_predictions, load_raw_analyzer_files, classification, HEADERS

class AnalyzerComparisonTests(unittest.TestCase):
    def make_csv(self,folder,change=None):
        target=Path(folder)/'analyzer_frozen.csv'
        with target.open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=HEADERS);writer.writeheader()
            for ticket in range(1,6):
                row={'round':2157,'draw_date':'2026-11-23',
                    'locked_at_jst':'2026-11-23T18:20:00+09:00',
                    'model':'portfolio','generation':'G17','ticket':ticket}
                for i in range(1,7):row[f'n{i}']=i+ticket
                if change and ticket==3:row.update(change)
                writer.writerow(row)
        return target

    def test_valid_portfolio(self):
        with tempfile.TemporaryDirectory() as folder:
            found,meta=load_site_predictions(self.make_csv(folder))
            self.assertEqual(meta['loaded_rounds'],1)
            self.assertEqual(len(found[2157][0]['tickets']),5)
            self.assertEqual(found[2157][0]['generation'],'G17')
    def test_late_or_inconsistent_frozen_time_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=self.make_csv(folder,{'locked_at_jst':'2026-11-23T18:31:00+09:00'})
            with self.assertRaises(ValueError):load_site_predictions(path)
    def test_missing_site_file(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('compare_models.RAW_EXPORT',Path(folder)):
                found,meta=load_site_predictions(Path(folder)/'absent.csv')
            self.assertFalse(found)
            self.assertEqual(meta['state'],'awaiting_export')
    def test_actual_japanese_analyzer_csv(self):
        from compare_models import RAW_EXPORT
        exported=load_raw_analyzer_files(RAW_EXPORT)
        self.assertIn(2157,exported)
        portfolio=exported[2157][0]
        self.assertEqual(portfolio['generation'],'未記載')
        self.assertIsNone(portfolio['locked_at_jst'])
        self.assertEqual(portfolio['tickets'][0],[16,21,33,34,38,40])
        self.assertEqual(portfolio['tickets'][4],[2,9,13,18,26,28])

    def test_japanese_csv_rejects_partial_portfolio(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'loto6-2157-fixed-5tickets.csv'
            path.write_text('回,口,数字1,数字2,数字3,数字4,数字5,数字6\\n2157,1,1,2,3,4,5,6\\n',encoding='utf-8')
            with self.assertRaises(ValueError):load_raw_analyzer_files(folder)

    def test_grades(self):
        main={1,2,3,4,5,6}
        self.assertEqual(classification([1,2,3,4,5,6],main,7),1)
        self.assertEqual(classification([1,2,3,4,5,7],main,7),2)
        self.assertEqual(classification([1,2,3,4,5,8],main,7),3)
        self.assertEqual(classification([1,2,3,4,9,10],main,7),4)
        self.assertEqual(classification([1,2,3,9,10,11],main,7),5)
        self.assertEqual(classification([1,2,9,10,11,12],main,7),0)

if __name__=='__main__':unittest.main()

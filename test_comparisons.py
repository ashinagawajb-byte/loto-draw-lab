"""Unit tests for frozen Site Analyzer five-ticket comparison intake."""
import csv
import tempfile
import unittest
from pathlib import Path
from compare_models import load_site_predictions, classification, HEADERS

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
            found,meta=load_site_predictions(Path(folder)/'absent.csv')
            self.assertFalse(found)
            self.assertEqual(meta['state'],'awaiting_export')
    def test_grades(self):
        main={1,2,3,4,5,6}
        self.assertEqual(classification([1,2,3,4,5,6],main,7),1)
        self.assertEqual(classification([1,2,3,4,5,7],main,7),2)
        self.assertEqual(classification([1,2,3,4,5,8],main,7),3)
        self.assertEqual(classification([1,2,3,4,9,10],main,7),4)
        self.assertEqual(classification([1,2,3,9,10,11],main,7),5)
        self.assertEqual(classification([1,2,9,10,11,12],main,7),0)

if __name__=='__main__':unittest.main()

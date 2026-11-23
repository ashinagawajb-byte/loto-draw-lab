"""Protect DRAW LAB production cycle controls and official review page."""
import re
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PAGE=ROOT/"simulator"/"index.html"

class DrawCycleProductionTests(unittest.TestCase):
    def test_provisional_drive_selection_and_legacy_preserved(self):
        s=PAGE.read_text(encoding="utf-8")
        self.assertIn('<option value="continuous" selected>',s)
        self.assertIn('<option value="legacy">',s)
        self.assertIn("if($('rotationMode').value==='legacy')spinDirection*=-1;",s)
        self.assertNotIn("\n  spinDirection*=-1;\n",s)
        self.assertIn("rotationMode:$('rotationMode').value",s)
        self.assertIn("'rotationMode','draw'",s)
        self.assertIn("駆動軸の停止・回転方向は未測定",s)
        self.assertIn('href="./review.html"',s)
    def test_review_and_simulator_javascript_syntax(self):
        s=PAGE.read_text(encoding="utf-8")
        # Main app's JS is an ES module; use input-type=module for node syntax.
        modules=re.findall(r'<script\s+type="module"[^>]*>(.*?)</script>',s,re.S)
        if modules:
            for module in modules:
                subprocess.run(["node","--check","--input-type=module"],input=module,text=True,check=True,capture_output=True)
        else:
            # External imports are not executed in this test.
            self.assertIn('import RAPIER',s)
        review=(ROOT/"simulator"/"review.html").read_text(encoding="utf-8")
        self.assertIn("公式バックナンバー",review)
        scripts=re.findall(r'<script>([\s\S]*?)</script>',review)
        self.assertTrue(scripts)
        for script in scripts:
            subprocess.run(["node","--check"],input=script,text=True,check=True,capture_output=True)

if __name__=="__main__":unittest.main()

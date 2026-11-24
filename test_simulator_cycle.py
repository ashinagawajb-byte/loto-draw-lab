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
        self.assertIn('<option value="legacy" selected>', s)
        self.assertIn('<option value="continuous">', s)
        self.assertIn("spinDirection=rotationDirection(rotationMode,i+1);", s)
        self.assertIn("palletVisual.rotation.y=-palletAngle", s)
        self.assertIn("directions.push(spinDirection)", s)
        self.assertIn("rotationMode:$('rotationMode').value", s)
        self.assertIn("駆動軸の停止・回転方向は未測定", s)
        self.assertIn('href="./review.html"', s)

    def test_rotation_sequence_and_analyzer_csv(self):
        s = PAGE.read_text(encoding="utf-8")
        parser = s[s.index("function parseAnalyzerCSV("):s.index("function renderAnalyzer(")]
        rotation = next(line for line in s.splitlines() if line.startswith("function rotationDirection("))
        tests = r"""
const assert=require('node:assert/strict');
assert.deepEqual(Array.from({length:7},(_,i)=>rotationDirection('legacy',i)),[1,-1,1,-1,1,-1,1]);
assert.ok(Array.from({length:9},(_,i)=>rotationDirection('continuous',i)).every(x=>x===1));
const csv='回,口,数字1,数字2,数字3,数字4,数字5,数字6'+
 Array.from({length:5},(_,i)=>'\n'+[101,i+1,i+1,8,9,10,11,12].join(',')).join('');
assert.equal(parseAnalyzerCSV(csv).round,101);
assert.deepEqual(parseAnalyzerCSV(csv).tickets[4],[5,8,9,10,11,12]);
assert.throws(()=>parseAnalyzerCSV(csv.replace('101,5','102,5')));
assert.throws(()=>parseAnalyzerCSV(csv.replace(',10,11,12',',10,10,12')));
"""
        subprocess.run(["node"], input=parser+rotation+tests, text=True, check=True)

    def test_outer_gate_captures_only_forward_crossings_at_outer_rim(self):
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn('<option value="gate-v1">', page)
        gate = page[page.index("function gateCrossing("):page.index("function showGateLayout(")]
        tests = """
const assert = require('node:assert/strict');
const PALLET_SAFE_RADIUS = 2.14;
const point = (x,z,y=-1.60) => ({x,y,z});
assert.equal(gateCrossing(point(2.1,-.04),point(2.1,.12),1),.25);
assert.equal(gateCrossing(point(-2.1,-.04),point(-2.1,.12),-1),.25);
assert.equal(gateCrossing(point(2.1,-.04),point(2.1,.12),-1),null);
assert.equal(gateCrossing(point(2.1,.12),point(2.1,-.04),1),null);
assert.equal(gateCrossing(point(2.1,-.20),point(2.1,-.04),1),null);
assert.equal(gateCrossing(point(1.0,-.04),point(1.0,.12),1),null);
assert.equal(gateCrossing(point(2.1,-.04,-.5),point(2.1,.12,-.5),1),null);
"""
        subprocess.run(["node"], input=gate+tests, text=True, check=True)

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

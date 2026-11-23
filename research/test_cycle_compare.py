"""Protect source observations and the independent comparison UI."""
import csv
import io
import json
import re
import subprocess
import unittest
from pathlib import Path
from research.draw_cycle import OBSERVATIONS, replay, simulate

ROOT=Path(__file__).resolve().parent

class DrawCycleComparisonTests(unittest.TestCase):
    def test_observation_timing_and_held_gate(self):
        self.assertEqual(len(OBSERVATIONS),7)
        self.assertEqual([s for _,_,s in OBSERVATIONS],['main']*6+['bonus'])
        self.assertAlmostEqual(OBSERVATIONS[-1][0]-OBSERVATIONS[-2][0],148.1)
        main_intervals=[OBSERVATIONS[i][0]-OBSERVATIONS[i-1][0] for i in range(1,6)]
        self.assertAlmostEqual(sum(main_intervals)/len(main_intervals),46.8,places=1)
        c=list(replay(7))
        self.assertEqual(len(c),14)
        self.assertEqual(c[0][5],'gate_pocket_visible')
        self.assertEqual(c[1][5],'lower_guide_visible')
        self.assertEqual(c[0][6:9],('','',''))
    def test_shared_parameters_and_coasting(self):
        a=list(simulate('a',3,90,2,1,1))
        b=list(simulate('b',3,90,2,1,1))
        self.assertEqual([x[1] for x in a if x[5]=='synthetic_capture'],
                         [x[1] for x in b if x[5]=='synthetic_capture'])
        b_stop=[x for x in b if x[2]==1 and x[1]>10.3 and x[1]<11.0]
        self.assertTrue(b_stop)
        self.assertTrue(all(x[7]==0 and x[8]>0 for x in b_stop))
        self.assertTrue(all(x[7]==90 for x in a))
    def test_ui_embeds_no_sensitive_state_and_has_all_modes(self):
        page=(ROOT/'cycle_compare.html').read_text(encoding='utf-8')
        for label in ('同じ時刻の抽出機構','モデル C','Cの速度は未測定',
                      '下側ガイド','比較データCSV','canvas id="speedplot"'):
            self.assertIn(label,page)
        self.assertNotIn('CF_API_TOKEN',page)
        self.assertNotIn('fetch(',page)
        script=re.search(r'<script>([\s\S]*?)</script>',page)
        self.assertIsNotNone(script)
        # Node syntax check when installed (GitHub hosted runners have Node).
        subprocess.run(['node','--check'],input=script.group(1),text=True,check=True,capture_output=True)


    def test_browser_script_state_and_csv(self):
        page = (ROOT / "cycle_compare.html").read_text(encoding="utf-8")
        script = re.search(r"<script>([\s\S]*?)</script>", page).group(1)
        stubs = """
const assert = require("node:assert/strict");
const values = {scope:7, rpm:90, brake:1, dwell:2, accel:1, rate:1, zoom:"all"};
const elements = new Map();
const context = new Proxy({}, {get: ()=>()=>{}});
const nodes = id => {
 if (!elements.has(id)) elements.set(id, {value: values[id], clientWidth: 360,
  clientHeight: 220, getContext: ()=>context});
 return elements.get(id);
};
let exported;
URL.createObjectURL = blob => {exported=blob;return "blob:test";};
URL.revokeObjectURL = ()=>{};
const document = {getElementById:nodes,body:{append(){}},
 createElement(){return {click(){},remove(){}};}};
const window = {devicePixelRatio:1,addEventListener(){}};
const requestAnimationFrame = ()=>{};
const setTimeout = ()=>{};
"""
        checks = """
assert.equal(t, -8);
assert.equal($("count").textContent, "0/7");
for (const [model] of models.slice(0,3)) {
 assert.equal(sample(model,START).speed,0);
 assert.equal(sample(model,START).angle,0);
}
$("play").onclick();
tick(1000); tick(2000);
assert.equal(t,-7);
$("rate").value=40;
tick(2100);
assert.equal(t,-3);
$("play").onclick();
tick(2200);
assert.equal(t,-3);
$("jump").onchange({target:{value:"47.3"}});
assert.match($("event").textContent,/本数字2：13.*受け部で保持/);
assert.equal($("zoom").value,"detail");
$("rpm").value=100; $("brake").value=2; $("dwell").value=3; $("accel").value=1.6;
$("rpm").oninput();
$("time").oninput({target:{value:"2.3"}});
assert.equal(sample("a", t).motor,100);
assert.equal(sample("legacy", t).motor,-100);
assert.equal(sample("b", t).motor,0);
assert.ok(sample("b", t).speed>0);
assert.match($("phase-b").textContent,/惰性/);
$("time").oninput({target:{value:"2.5"}});
assert.equal($("status-c").textContent,"下側ガイドへ移動済");
$("time").oninput({target:{value:String(end)}});
$("play").onclick();
assert.equal(t,-8);
$("scope").value=6;
$("scope").onchange();
assert.equal(playing,false);
assert.equal(schedule.length,6);
assert.equal(end,241.7);
$("csv").onclick();
exported.text().then(text => console.log(JSON.stringify(text)));
"""
        result = subprocess.run(
            ["node", "-"], input=stubs + script + checks, text=True,
            check=True, capture_output=True,
        )
        rows = list(csv.DictReader(io.StringIO(json.loads(result.stdout))))
        observations = [row for row in rows if row["model"] == "c"]
        self.assertEqual(len(observations), 12)
        self.assertTrue(all(row["tier"] == "本数字" for row in observations))
        self.assertTrue(all(row["pallet_rpm_hypothesis"] == "" for row in observations))
        stopped = next(row for row in rows if row["model"] == "b" and row["relative_time_s"] == "2.3")
        self.assertEqual(float(stopped["pallet_rpm_hypothesis"]), 0)
        self.assertGreater(float(stopped["ball_mean_rpm_proxy"]), 0)

if __name__=='__main__':unittest.main()

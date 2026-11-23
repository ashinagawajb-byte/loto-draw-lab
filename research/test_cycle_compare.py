"""Protect source observations and the independent comparison UI."""
import csv
import io
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
        for label in ('代表球の周回軌道','モデル C','回転数の実測値がない',
                      '下側ガイド','比較データCSV','canvas id="speedplot"'):
            self.assertIn(label,page)
        self.assertNotIn('CF_API_TOKEN',page)
        self.assertNotIn('fetch(',page)
        script=re.search(r'<script>([\s\S]*?)</script>',page)
        self.assertIsNotNone(script)
        # Node syntax check when installed (GitHub hosted runners have Node).
        subprocess.run(['node','--check'],input=script.group(1),text=True,check=True,capture_output=True)

if __name__=='__main__':unittest.main()

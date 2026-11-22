"""Verify native scanner against Python reference, including known exact matches."""
import subprocess
import unittest
from pathlib import Path
from worker import shuffle

BIN=str(Path(__file__).with_name("seed_scan"))

def scan(game, start, count, main, bonus):
    cmd=[BIN,str(game),str(start),str(count),
         ",".join(map(str,main)),",".join(map(str,bonus))]
    output=subprocess.run(cmd,check=True,text=True,capture_output=True,timeout=15).stdout
    return [int(x) for x in output.splitlines() if x.strip()]

class NativeScannerTests(unittest.TestCase):
    def test_matches_reference_multiple_seeds_both_games(self):
        for game in (6,7):
            n=43 if game==6 else 37
            b=1 if game==6 else 2
            for target_seed in (0,1,42,97,12345,4294967295):
                shuffled=shuffle(n,target_seed)
                main=shuffled[:game]
                bonus=shuffled[game:game+b]
                start=max(0,target_seed-3)
                count=min(7,2**32-start)
                actual=scan(game,start,count,main,bonus)
                expected=[seed for seed in range(start,start+count)
                          if set(shuffle(n,seed)[:game])==set(main) and
                             set(shuffle(n,seed)[game:game+b])==set(bonus)]
                self.assertEqual(actual,expected,(game,target_seed))
                self.assertIn(target_seed,actual)
    def test_rejects_out_of_range_and_duplicate(self):
        p=subprocess.run([BIN,"6","4294967295","2","1,2,3,4,5,6","7"],
                         text=True,capture_output=True)
        self.assertNotEqual(p.returncode,0)
        p=subprocess.run([BIN,"6","0","2","1,1,3,4,5,6","7"],
                         text=True,capture_output=True)
        self.assertNotEqual(p.returncode,0)

if __name__=="__main__":unittest.main()

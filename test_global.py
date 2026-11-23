"""One-pass scanner regression tests: both games, repeated rounds, 32-bit edge."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from worker import shuffle
from global_search import targets, verify_match
BIN=str(Path(__file__).with_name('global_scan'))

class GlobalNativeTests(unittest.TestCase):
    def test_snapshot_and_known_vectors(self):
        text,digest,valid=targets()
        self.assertIn('6\t1\t',text)
        self.assertIn('7\t1\t',text)
        self.assertEqual(len(digest),64)
        self.assertTrue(valid)
    def test_reference_both_games_and_repeated_history(self):
        for seed in (0,1,42,999,4294967295):
            numbers6=shuffle(43,seed)
            numbers7=shuffle(37,seed)
            rows=[
                f'6\t100\t{",".join(map(str,numbers6[:6]))}\t{numbers6[6]}',
                f'6\t101\t{",".join(map(str,reversed(numbers6[:6])))}\t{numbers6[6]}',
                f'7\t200\t{",".join(map(str,numbers7[:7]))}\t{",".join(map(str,numbers7[7:9]))}',
            ]
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'targets.tsv'
                path.write_text('\n'.join(rows)+'\n')
                start=max(0,seed-2)
                count=min(5,2**32-start)
                result=subprocess.run([BIN,str(start),str(count),str(path)],
                    capture_output=True,text=True,check=True,timeout=15)
                observed={tuple(line.split('\t')) for line in result.stdout.splitlines()}
                for game,round_id in ((6,100),(6,101),(7,200)):
                    self.assertIn((str(game),str(round_id),str(seed)),observed)
                expected=set()
                for s in range(start,start+count):
                    for g,r,target in ((6,100,numbers6),(6,101,numbers6),(7,200,numbers7)):
                        actual=shuffle(43 if g==6 else 37,s)
                        if set(actual[:g])==set(target[:g]) and set(actual[g:g+(1 if g==6 else 2)])==set(target[g:g+(1 if g==6 else 2)]):
                            expected.add((str(g),str(r),str(s)))
                self.assertEqual(observed,expected)
    def test_invalid_range(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'targets.tsv'
            path.write_text('6\t1\t1,2,3,4,5,6\t7\n7\t1\t1,2,3,4,5,6,7\t8,9\n')
            bad=subprocess.run([BIN,'4294967295','2',str(path)],capture_output=True)
            self.assertNotEqual(bad.returncode,0)
if __name__=='__main__':
    unittest.main()

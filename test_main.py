"""Regression tests for separate main-only and full-match scanner output."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from worker import shuffle
from main_search import update_statistics
from global_search import targets

BIN=str(Path(__file__).with_name('global_scan'))

class MainOnlyTests(unittest.TestCase):
    def test_main_only_and_full_classification(self):
        for seed in (0, 42, 4294967295):
            s6=shuffle(43,seed);s7=shuffle(37,seed)
            rows=[
                f'6\t11\t{",".join(map(str,s6[:6]))}\t{s6[6]}',
                f'6\t12\t{",".join(map(str,reversed(s6[:6])))}\t{s6[7]}',
                f'7\t21\t{",".join(map(str,s7[:7]))}\t{s7[7]},{s7[8]}',
            ]
            valid={(6,'11'):(frozenset(s6[:6]),frozenset([s6[6]])),
                   (6,'12'):(frozenset(s6[:6]),frozenset([s6[7]])),
                   (7,'21'):(frozenset(s7[:7]),frozenset(s7[7:9]))}
            with tempfile.TemporaryDirectory() as folder:
                target=Path(folder)/'targets.tsv';target.write_text('\n'.join(rows)+'\n')
                main=subprocess.run([BIN,str(seed),'1',str(target),'main'],
                    capture_output=True,text=True,check=True,timeout=15)
                full=subprocess.run([BIN,str(seed),'1',str(target)],
                    capture_output=True,text=True,check=True,timeout=15)
                observed=set(main.stdout.splitlines())
                self.assertEqual(observed,{f'6\t11\t{seed}\t1',f'6\t12\t{seed}\t0',f'7\t21\t{seed}\t1'})
                self.assertEqual(set(full.stdout.splitlines()),{f'6\t11\t{seed}',f'7\t21\t{seed}'})
                hits=[(int(parts[0]),parts[1],int(parts[2]),int(parts[3]))
                      for row in observed for parts in [row.split('\t')]]
                stats=update_statistics({},hits,valid)
                self.assertEqual(stats['6:11']['bonus_count'],1)
                self.assertEqual(stats['6:12']['count'],1)
                self.assertEqual(stats['6:12']['bonus_count'],0)
                self.assertEqual(stats['7:21']['min_seed'],seed)
    def test_rejects_corrupt_hit(self):
        text,digest,valid=targets()
        game,round_id=next(iter(valid))
        with self.assertRaises(RuntimeError):
            update_statistics({},[(game,round_id,4294967295,1)],valid)

if __name__=='__main__':
    unittest.main()

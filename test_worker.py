"""No external services required. Run python -m unittest -q test_worker.py."""
import unittest
from worker import shuffle

class TestShuffle(unittest.TestCase):
    def test_v08_javascript_prng_vectors(self):
        expected={0:[32,5,43,25,42,30,28],1:[24,17,32,20,21,30,36],
                  42:[28,18,41,5,30,39,14],20261122:[6,12,4,7,20,15,38],
                  4294967295:[24,31,19,41,43,32,42]}
        for seed,numbers in expected.items():
            self.assertEqual(shuffle(43,seed)[:7],numbers)
    def test_uniqueness(self):
        for n in (43,37):
            for seed in range(40):
                self.assertEqual(sorted(shuffle(n,seed)),list(range(1,n+1)))
if __name__=='__main__':unittest.main()

"""Tests for official archive catalog and conservative retrospective behavior."""
import unittest
import re
import subprocess
from pathlib import Path
from research.update_official_archives import extract

ROOT=Path(__file__).parent

class ArchiveTests(unittest.TestCase):
    def test_extract_loto6_loto7_archive_only(self):
        html='''<h3><img alt="ロト7"></h3><table><tr><th>回号</th><th>抽せん日</th><th>動画</th></tr>
        <tr><td>第704回</td><td>2026年11月20日</td><td><a href="https://api01-platform.stream.co.jp/apiservice/demo">視聴する</a></td></tr></table>
        <h3><img alt="ロト6"></h3><table>
        <tr><td>第2157回</td><td>2026年11月23日</td><td><a href="https://api01-platform.stream.co.jp/apiservice/demo2">視聴する</a></td></tr>
        <tr><td>第2156回</td><td>2026年11月19日</td><td><a href="https://evil.example/override">視聴する</a></td></tr></table>'''
        x=extract(html)
        self.assertEqual([(r["game"],r["draw"]) for r in x],[("loto7",704),("loto6",2157)])
        self.assertEqual(x[1]["date"],"2026年11月23日")
        self.assertEqual(x[1]["status"],"unreviewed")
    def test_page_no_auto_fake_observation(self):
        page=(ROOT/"draw_retrospective.html").read_text()
        self.assertIn('id="catalogFile"',page)
        self.assertIn('id="download"',page)
        self.assertIn("既存記録を保護",page)
        self.assertIn("未測定のRPM",page)
        script=re.search(r'<script>([\s\S]*?)</script>',page).group(1)
        subprocess.run(["node","--check"],input=script,text=True,check=True,capture_output=True)

if __name__=="__main__":unittest.main()

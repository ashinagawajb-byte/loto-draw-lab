#!/usr/bin/env python3
"""List official recent LOTO6/7 archived digest links without downloading video.
No draw numbers or physical observations are inferred from the video index.
"""
import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

SOURCE="https://www.takarakuji-dream.jp/takarakuji/backnumber"

class ArchiveParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.section=None
        self.in_heading=False
        self.in_row=False
        self.in_cell=False
        self.in_anchor=False
        self.cell=""
        self.cells=[]
        self.link=""
        self.rows=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="h3":
            self.in_heading=True
            self.section=None
        if self.in_heading and tag=="img":
            alt=a.get("alt","")
            if "ロト6" in alt or "ロト６" in alt:self.section="loto6"
            if "ロト7" in alt or "ロト７" in alt:self.section="loto7"
        if tag=="tr":
            self.in_row=True;self.cells=[];self.link=""
        if tag in ("td","th") and self.in_row:
            self.in_cell=True;self.cell=""
        if tag=="a" and self.in_row:
            self.in_anchor=True
            href=a.get("href","")
            if href:self.link=urljoin(SOURCE,href)
    def handle_data(self,data):
        if self.in_cell:self.cell+=data
    def handle_endtag(self,tag):
        if tag=="h3":self.in_heading=False
        if tag in ("td","th") and self.in_cell:
            self.cells.append(self.cell.strip());self.in_cell=False
        if tag=="a":self.in_anchor=False
        if tag=="tr" and self.in_row:
            self.in_row=False
            if self.section in ("loto6","loto7"):
                whole=" ".join(self.cells)
                nr=re.search(r"第\s*(\d+)\s*回",whole)
                date=re.search(r"20\d{2}年\s*\d{1,2}月\s*\d{1,2}日",whole)
                if nr and date and self.link:
                    self.rows.append({"game":self.section,"draw":int(nr.group(1)),
                      "date":re.sub(r"\s+","",date.group()),"video_url":self.link,
                      "source_url":SOURCE,"status":"unreviewed"})
def extract(html):
    p=ArchiveParser();p.feed(html);seen=set();out=[]
    for row in p.rows:
        u=urlparse(row["video_url"])
        if u.scheme!="https" or u.hostname not in ("api01-platform.stream.co.jp","www.takarakuji-dream.jp"):
            continue
        k=(row["game"],row["draw"])
        if k not in seen:seen.add(k);out.append(row)
    return out
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",default="research/official_archive_catalog.json")
    args=ap.parse_args()
    req=urllib.request.Request(SOURCE,headers={"User-Agent":"LOTO-DRAW-LAB-Research/1.0 (official archive index only)"})
    with urllib.request.urlopen(req,timeout=20) as resp:
        raw=resp.read(2_000_000)
    rows=extract(raw.decode("utf-8","replace"))
    if not any(x["game"]=="loto6" for x in rows) or not any(x["game"]=="loto7" for x in rows):
        raise SystemExit("Could not recognize both LOTO6 and LOTO7 sections; refusing to overwrite catalog")
    data={"source":SOURCE,"retrieved_at":datetime.now(timezone.utc).isoformat(),
          "note":"Recent digest links only. Archive may remove older listings; neither video data nor results are extracted.",
          "draws":rows}
    with open(args.output,"w",encoding="utf-8") as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write("\n")
    print("Discovered",len(rows),"archive links")
if __name__=="__main__":main()

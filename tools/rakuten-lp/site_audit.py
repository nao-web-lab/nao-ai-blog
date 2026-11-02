#!/usr/bin/env python3
"""公開済み商品LP（/products/<カテゴリ>/<商品>/）を、LP品質ルール（RULES.md）に照らして全件監査する。

- 外部通信・APIは使わない（リポジトリ内のHTMLと原稿JSONだけを読む）
- 使い方:  python tools/rakuten-lp/site_audit.py            # 概要を表示
           python tools/rakuten-lp/site_audit.py --json out.json   # 1ページごとの詳細も保存
           python tools/rakuten-lp/site_audit.py --list thin       # 該当ページ一覧（thin / dup / noimg / ...）
- 判定は「機械で確認できる最低ライン」。内容の良し悪しの最終判断は人が行う。
"""

import argparse
import collections
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parents[1]
PRODUCTS = REPO_ROOT / "products"
CONTENT_DIR = TOOL_DIR / "data" / "content"
SITE = "https://nao-web-lab.github.io/nao-ai-blog"

# 公開候補にしない最低ライン（RULES.md「公開の最低ライン」と同じ値）
MIN_VISIBLE_CHARS = 1500      # 本文の文字数（ナビ・フッターを除く）
MIN_IMAGES = 2                # 商品画像の枚数
MIN_UNIQUE_RATIO = 0.55       # 同カテゴリの他ページと重ならない文の割合
DUP_SENTENCE_PAGES = 12       # 同じ文が何ページに出たら「定型文」とみなすか


class Page(HTMLParser):
    SKIP = {"script", "style", "noscript", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta = {}
        self.canonical = ""
        self.h1 = []
        self.h2 = []
        self.imgs = []
        self.links = []
        self.jsonld = []
        self.text = []
        self.fv_text = []
        self.sections = []
        self._stack = []
        self._skip = 0
        self._in_title = False
        self._in_h = None
        self._cur = ""
        self._in_script_ld = False
        self._ld_buf = ""
        self._region = []      # header/footer/nav を本文から除く
        self._in_fv = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "") or ""
        if tag in self.SKIP:
            self._skip += 1
            if tag == "script" and a.get("type") == "application/ld+json":
                self._in_script_ld = True
                self._ld_buf = ""
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            k = a.get("name") or a.get("property")
            if k:
                self.meta[k] = a.get("content", "")
        if tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href", "")
        if tag in ("header", "footer", "nav") and "lp-breadcrumb" not in cls:
            self._region.append(tag)
        if tag == "nav" and "lp-breadcrumb" in cls:
            self._region.append("nav")
        if tag == "section" and "lp-fv" in cls:
            self._in_fv += 1
        if tag == "section" and cls.startswith("lp-section"):
            self.sections.append(cls.split()[1].replace("lp-", "") if len(cls.split()) > 1 else "")
        if tag in ("h1", "h2", "h3"):
            self._in_h = tag
            self._cur = ""
        if tag == "img":
            self.imgs.append({"src": a.get("src", ""), "alt": a.get("alt"), "w": a.get("width"), "h": a.get("height"),
                              "loading": a.get("loading"), "fetchpriority": a.get("fetchpriority")})
        if tag == "a":
            self.links.append({"href": a.get("href", ""), "rel": a.get("rel", ""), "cls": cls})

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
            if tag == "script" and self._in_script_ld:
                self._in_script_ld = False
                try:
                    self.jsonld.append(json.loads(self._ld_buf))
                except Exception:
                    self.jsonld.append({"_invalid": True})
        if tag == "title":
            self._in_title = False
        if tag in ("header", "footer", "nav") and self._region:
            self._region.pop()
        if tag == "section" and self._in_fv:
            self._in_fv = max(0, self._in_fv - 1) if False else self._in_fv
        if tag == self._in_h:
            if tag == "h1":
                self.h1.append(self._cur.strip())
            elif tag == "h2":
                self.h2.append(self._cur.strip())
            self._in_h = None

    def handle_data(self, data):
        if self._in_script_ld:
            self._ld_buf += data
            return
        if self._skip:
            return
        if self._in_title:
            self.title += data
        if self._in_h:
            self._cur += data
        if not self._region:
            t = data.strip()
            if t:
                self.text.append(t)


def sentences(text: str):
    for s in re.split(r"(?<=[。！？!?])|\n", text):
        s = s.strip()
        if len(s) >= 14:
            yield s


def audit_page(path: Path):
    html = path.read_text(encoding="utf-8")
    p = Page()
    p.feed(html)
    rel = path.relative_to(REPO_ROOT).as_posix()
    body = "\n".join(p.text)
    aff_links = [l for l in p.links if "hb.afl.rakuten.co.jp" in l["href"]]
    bad_rel = [l for l in aff_links if not all(x in l["rel"].split() for x in ("nofollow", "sponsored"))]
    item_links = [l for l in p.links if re.match(r"https?://(item|www)\.rakuten\.co\.jp", l["href"])]
    prod_imgs = [i for i in p.imgs if "thumbnail.image.rakuten.co.jp" in i["src"]]
    ld_types = []
    for blk in p.jsonld:
        t = blk.get("@type") if isinstance(blk, dict) else None
        ld_types.append(t if isinstance(t, str) else str(t))
    pr_in_fv = bool(re.search(r'class="lp-pr"', html)) and html.find('class="lp-pr"') < html.find("<h1")
    btn_labels = re.findall(r'class="btn btn-primary lp-cta-btn"[^>]*>([^<]*)', html)
    return {
        "path": rel, "slug": path.parent.name, "category": path.parent.parent.name,
        "title": p.title.strip(), "description": p.meta.get("description", ""), "h1": p.h1[0] if p.h1 else "",
        "h1_count": len(p.h1), "h2_count": len(p.h2), "canonical": p.canonical,
        "robots": p.meta.get("robots", ""), "has_meta_keywords": "keywords" in p.meta,
        "og_image": p.meta.get("og:image", ""), "chars": len(re.sub(r"\s+", "", body)),
        "sections": [s for s in p.sections if s], "n_img": len(prod_imgs),
        "img_no_alt": sum(1 for i in prod_imgs if not (i["alt"] or "").strip()),
        "img_no_size": sum(1 for i in prod_imgs if not (i["w"] and i["h"])),
        "n_aff": len(aff_links), "bad_rel": len(bad_rel), "item_url_links": len(item_links),
        "ld_types": ld_types, "pr_before_h1": pr_in_fv,
        "cta_labels": btn_labels, "has_fetch_date": "時点" in body,
        "has_not_for": "not_for" in p.sections, "has_checkpoints": "checkpoints" in p.sections,
        "has_faq": "faq" in p.sections, "has_specs": "specs" in p.sections,
        "has_policy_link": "policy.html" in html, "has_compare": "compare" in p.sections,
        "sentences": list(sentences(body)),
    }


def run():
    pages = []
    for f in sorted(PRODUCTS.glob("*/*/index.html")):
        if f.parent.parent.name == "assets":
            continue
        pages.append(audit_page(f))

    # 文の重複（定型文）: 同じ文が多数のページに出ていないか
    sent_pages = collections.defaultdict(set)
    for pg in pages:
        for s in set(pg["sentences"]):
            sent_pages[hashlib.md5(s.encode()).hexdigest()].add(pg["path"])
    for pg in pages:
        ss = set(pg["sentences"])
        common = sum(1 for s in ss if len(sent_pages[hashlib.md5(s.encode()).hexdigest()]) >= DUP_SENTENCE_PAGES)
        pg["boiler_ratio"] = round(common / len(ss), 3) if ss else 0
        pg["unique_ratio"] = round(1 - pg["boiler_ratio"], 3)

    # 同カテゴリ内の近似重複（文の集合の Jaccard）
    by_cat = collections.defaultdict(list)
    for pg in pages:
        by_cat[pg["category"]].append(pg)
    for cat, lst in by_cat.items():
        sets = [set(hashlib.md5(s.encode()).hexdigest()[:10] for s in set(pg["sentences"]) if len(sent_pages[hashlib.md5(s.encode()).hexdigest()]) < DUP_SENTENCE_PAGES) for pg in lst]
        for i, a in enumerate(sets):
            best = 0.0
            for j, b in enumerate(sets):
                if i == j or not a or not b:
                    continue
                inter = len(a & b)
                if inter:
                    best = max(best, inter / min(len(a), len(b)))
            lst[i]["max_overlap"] = round(best, 3)

    titles = collections.Counter(pg["title"] for pg in pages)
    descs = collections.Counter(pg["description"] for pg in pages)
    h1s = collections.Counter(pg["h1"] for pg in pages)
    for pg in pages:
        pg["dup_title"] = titles[pg["title"]] > 1
        pg["dup_desc"] = descs[pg["description"]] > 1
        pg["dup_h1"] = h1s[pg["h1"]] > 1
        flags = []
        if pg["chars"] < MIN_VISIBLE_CHARS:
            flags.append("thin")
        if pg["n_img"] < MIN_IMAGES:
            flags.append("noimg")
        if pg["unique_ratio"] < MIN_UNIQUE_RATIO:
            flags.append("boiler")
        if pg.get("max_overlap", 0) >= 0.5:
            flags.append("dup")
        if pg["dup_title"] or pg["dup_desc"] or pg["dup_h1"]:
            flags.append("dupmeta")
        if pg["img_no_alt"] or pg["img_no_size"]:
            flags.append("imgattr")
        if pg["bad_rel"] or pg["item_url_links"]:
            flags.append("link")
        if pg["h1_count"] != 1 or "noindex" in pg["robots"]:
            flags.append("struct")
        if not pg["has_not_for"] or not pg["has_checkpoints"] or not pg["has_specs"]:
            flags.append("balance")
        if not pg["pr_before_h1"]:
            flags.append("pr")
        pg["flags"] = flags
    return pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--list", help="flag名の一覧を表示（thin/noimg/boiler/dup/dupmeta/imgattr/link/struct/balance/pr）")
    args = ap.parse_args()
    pages = run()
    n = len(pages)
    c = collections.Counter(f for pg in pages for f in pg["flags"])
    print(f"監査対象: {n}ページ")
    for k in ("pr", "link", "struct", "imgattr", "noimg", "thin", "boiler", "dup", "dupmeta", "balance"):
        print(f"  {k:8s} {c.get(k, 0):5d}")
    clean = sum(1 for pg in pages if not pg["flags"])
    print(f"  指摘なし  {clean:5d}")
    chars = sorted(pg["chars"] for pg in pages)
    print(f"  本文文字数 中央値={chars[n // 2]} 最小={chars[0]} 最大={chars[-1]}")
    print("  CTA文言の種類:", len(set(l for pg in pages for l in pg["cta_labels"])))
    print("  構造化データ:", collections.Counter(t for pg in pages for t in pg["ld_types"]))
    print("  meta keywords あり:", sum(pg["has_meta_keywords"] for pg in pages), "/ 広告方針リンクあり:", sum(pg["has_policy_link"] for pg in pages),
          "/ 比較表あり:", sum(pg["has_compare"] for pg in pages))
    if args.list:
        for pg in pages:
            if args.list in pg["flags"]:
                print(pg["path"], pg["chars"], pg["n_img"], pg.get("max_overlap"), pg["unique_ratio"])
    if args.json:
        for pg in pages:
            pg.pop("sentences", None)
        Path(args.json).write_text(json.dumps(pages, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

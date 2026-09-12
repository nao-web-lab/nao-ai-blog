#!/usr/bin/env python3
"""
Rebuilds sitemap.xml, robots.txt, and the lp/auto/index.html listing page
from whatever LPs currently exist under lp/auto/*/index.html.

Run by .github/workflows/rebuild-sitemap.yml on every push to main that
touches lp/auto/**, so the sitemap/robots/listing stay in sync with
whatever auto-lp has published (from the PC or from a phone-triggered run).
"""

import datetime
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE_BASE_URL = "https://nao-web-lab.github.io/nao-ai-blog"


def extract(html: str, pattern: str) -> str:
    m = re.search(pattern, html, re.I | re.S)
    return m.group(1).strip() if m else ""


def main() -> None:
    lp_root = REPO_ROOT / "lp" / "auto"
    entries = []
    for d in sorted(p for p in lp_root.glob("*") if p.is_dir()):
        index_file = d / "index.html"
        if not index_file.is_file():
            continue
        html = index_file.read_text(encoding="utf-8")
        title = extract(html, r"<title>(.*?)</title>")
        canonical = extract(html, r'<link rel="canonical" href="([^"]+)"')
        description = extract(html, r'<meta name="description" content="([^"]*)"')
        if not canonical:
            canonical = f"{SITE_BASE_URL}/lp/auto/{d.name}/"
        entries.append({"title": title or d.name, "url": canonical, "description": description})

    today = datetime.date.today().isoformat()

    urls = [f"{SITE_BASE_URL}/", f"{SITE_BASE_URL}/lp/auto/"] + [e["url"] for e in entries]
    sitemap_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for u in urls:
        sitemap_lines.append(f"  <url><loc>{u}</loc><lastmod>{today}</lastmod></url>")
    sitemap_lines.append("</urlset>")
    (REPO_ROOT / "sitemap.xml").write_text("\n".join(sitemap_lines) + "\n", encoding="utf-8")

    robots = f"User-agent: *\nAllow: /\nSitemap: {SITE_BASE_URL}/sitemap.xml\n"
    (REPO_ROOT / "robots.txt").write_text(robots, encoding="utf-8")

    cards = []
    for e in entries:
        desc_html = f"<p>{e['description']}</p>" if e["description"] else ""
        cards.append(f'<li class="lp-card"><a href="{e["url"]}">{e["title"]}</a>{desc_html}</li>')
    cards_html = "\n".join(cards) if cards else "<p>まだ公開されたLPはありません。</p>"

    listing_html = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>公開LP一覧 | NAO WEB LAB</title>
<meta name="description" content="NAO WEB LABで自動生成・公開したアフィリエイトLPの一覧です。">
<link rel="canonical" href="{SITE_BASE_URL}/lp/auto/">
<meta name="robots" content="index,follow">
<style>
  body {{ font-family: system-ui, -apple-system, "Hiragino Sans", "Yu Gothic", sans-serif; max-width: 720px; margin: 0 auto; padding: 24px 16px; line-height: 1.7; color: #222; }}
  h1 {{ font-size: 1.4rem; }}
  ul {{ list-style: none; padding: 0; margin: 20px 0; }}
  .lp-card {{ border: 1px solid #e2e2e2; border-radius: 8px; padding: 16px; margin-bottom: 12px; }}
  .lp-card a {{ font-weight: bold; text-decoration: none; color: #1a56db; font-size: 1.05rem; }}
  .lp-card p {{ margin: 8px 0 0; color: #555; font-size: 0.92rem; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>公開LP一覧</h1>
<p>これまでに自動生成・公開したLP(ランディングページ)の一覧です。</p>
<ul>
{cards_html}
</ul>
<p><a href="{SITE_BASE_URL}/">トップページに戻る</a></p>
</body>
</html>
"""
    (lp_root / "index.html").write_text(listing_html, encoding="utf-8")

    print(f"Rebuilt sitemap.xml / robots.txt / lp/auto/index.html for {len(entries)} LP(s).")


if __name__ == "__main__":
    main()

"""商品一覧(/products/)・カテゴリ別一覧(/products/<カテゴリ>/)の生成と、関連LPの選定。

一覧には「公開済み かつ ファイルが実在する」LPだけを載せる（存在しないLPへのリンクを作らない）。
"""

import unicodedata

from common import CONTENT_DIR, PRODUCTS_DIR, REPO_ROOT, read_json
from images import sized
from render import e, pick_specs

FAVICON = ("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2064%2064'%3E%3Crect%20width='64'%20height='64'%20rx='14'%20fill='%232563eb'/%3E%3Ctext%20x='32'%20y='44'%20font-family='Arial,Helvetica,sans-serif'%20font-size='34'%20font-weight='700'%20fill='%23ffffff'%20text-anchor='middle'%3EN%3C/text%3E%3C/svg%3E")


def published_entries(db: dict) -> list:
    out = []
    for rec in db.get("products", {}).values():
        if rec.get("status") != "published":
            continue
        if not (REPO_ROOT / rec["lp_path"]).exists():
            continue
        out.append(rec)
    out.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return out


def pick_related(rec: dict, entries: list, n: int) -> list:
    """AIが分析した related_needs（次に検討しそうな商品の種類）・キーワード・カテゴリの近さで関連LPを選ぶ。"""
    needs = set(rec.get("related_needs") or [])
    kws = set(rec.get("keywords") or [])
    scored = []
    for o in entries:
        if o["item_code"] == rec["item_code"]:
            continue
        s = 0.0
        o_terms = set(o.get("keywords") or []) | {o.get("product_type") or ""}
        for need in needs:
            if any(need and (need in t or t in need) for t in o_terms if t):
                s += 3
        s += len(kws & set(o.get("keywords") or [])) * 1.0
        if o.get("category") == rec.get("category"):
            s += 1.5
        if s >= 1.5:
            scored.append((s, o.get("final_score", 0), o))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [o for _, _, o in scored[:n]]


def related_items_for(rec: dict, entries: list, n: int, from_dir_depth: int = 3) -> list:
    up = "../" * from_dir_depth
    return [{
        "href": f"{up}{o['lp_path'].replace('index.html', '')}",
        "image": o["images"][0] if o.get("images") else "",
        "name": o["display_name"], "title": o.get("title") or o["display_name"],
        "category_label": o["category_label"],
    } for o in pick_related(rec, entries, n) if o.get("images")]


def _norm_type(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").replace(" ", "").replace("　", "")


def compare_rows(rec: dict, entries: list, n: int = 3, from_dir_depth: int = 3) -> list:
    """同じカテゴリ・同じ商品の種類のLPから、価格が近い順に最大n件を比較表用に返す。
    使う値は、各LPの原稿に保存済みの楽天APIの取得値（価格・レビュー・仕様）だけ。紹介料率などは使わない。"""
    ptype = _norm_type(rec.get("product_type"))
    if not ptype:
        return []
    up = "../" * from_dir_depth
    peers = []
    for o in entries:
        if o["item_code"] == rec["item_code"] or o.get("category") != rec.get("category"):
            continue
        if _norm_type(o.get("product_type")) != ptype:
            continue
        data = read_json(CONTENT_DIR / f"{o['slug']}.json", None)
        if not data:
            continue
        pr = data["product"]
        try:
            price, avg, cnt = int(pr["price"]), float(pr["review_average"]), int(pr["review_count"])
        except (KeyError, TypeError, ValueError):
            continue
        fetched = (pr.get("fetched_at") or o.get("created_at") or "")[:10].replace("-", "/")
        spec = pick_specs(pr.get("spec_rows"))
        peers.append({"href": f"{up}{o['lp_path'].replace('index.html', '')}", "name": o["display_name"], "price": price,
                      "review_average": avg, "review_count": cnt, "fetched": fetched, "spec": spec})
    base = rec.get("_price") or 0
    peers.sort(key=lambda x: abs(x["price"] - base) if base else x["price"])
    return peers[:n]


def _card(r, up):
    img = r["images"][0] if r.get("images") else ""
    img_html = (f'<img src="{e(sized(img, "300x300"))}" width="300" height="300" alt="{e(r["display_name"])}" loading="lazy" decoding="async">' if img else "")
    return (f'<li class="lp-related-card"><a href="{up}{e(r["lp_path"].replace("products/", "", 1).replace("index.html", ""))}">{img_html}'
            f'<span class="lp-related-cat">{e(r["category_label"])}</span><span class="lp-related-name">{e(r.get("title") or r["display_name"])}</span></a></li>')


def _page(title, desc, canonical, root, h1, lead, body, site_name):
    nav = (f'<li><a href="{root}index.html">ホーム</a></li><li><a href="{root}about.html">サイトについて</a></li>'
           f'<li><a href="{root}products/" aria-current="page">商品ガイド</a></li><li><a href="{root}contact.html">お問い合わせ</a></li>')
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{e(title)}｜{e(site_name)}</title>
<meta name="description" content="{e(desc)}">
<meta name="robots" content="index,follow">
<link rel="canonical" href="{e(canonical)}">
<link rel="icon" type="image/svg+xml" href="{FAVICON}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{e(site_name)}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(canonical)}">
<meta property="og:locale" content="ja_JP">
<link rel="stylesheet" href="{root}css/style.css">
<link rel="stylesheet" href="{root}products/assets/lp.css">
</head>
<body class="lp-body">
<a class="skip-link" href="#main-content">メインコンテンツへスキップ</a>
<header class="site-header"><div class="container header-inner">
<a class="site-logo" href="{root}index.html"><span class="site-logo-mark" aria-hidden="true">N</span>{e(site_name)}</a>
<button type="button" class="nav-toggle" aria-expanded="false" aria-controls="primary-nav" aria-label="メニューを開閉する"><span></span><span></span><span></span></button>
<nav id="primary-nav" class="site-nav" aria-label="メインナビゲーション"><ul>{nav}</ul></nav>
</div></header>
<main id="main-content"><section class="lp-list"><div class="container">
<div class="lp-list-head"><p class="lp-pr" role="note"><span class="lp-pr-badge">PR</span>楽天アフィリエイト広告を含みます<a href="{root}policy.html">広告・運営方針</a></p>
<h1 class="lp-h1">{e(h1)}</h1><p class="lp-list-lead">{e(lead)}</p></div>
{body}
<p class="lp-disclaimer">※このページで紹介している商品ページには、楽天アフィリエイトの広告リンクが含まれます。リンク先の楽天市場で商品が購入されると、運営者に報酬が支払われる場合があります。</p>
</div></section></main>
<footer class="site-footer"><div class="container footer-inner">
<p class="site-logo"><span class="site-logo-mark" aria-hidden="true">N</span>{e(site_name)}</p>
<nav class="footer-nav" aria-label="フッターナビゲーション"><ul><li><a href="{root}about.html">サイトについて</a></li><li><a href="{root}policy.html">広告・運営方針</a></li><li><a href="{root}products/">商品ガイド</a></li><li><a href="{root}contact.html">お問い合わせ</a></li><li><a href="{root}privacy.html">プライバシーポリシー</a></li></ul></nav>
<p class="footer-copyright">&copy; <span data-current-year>2026</span> {e(site_name)}</p>
</div></footer>
<script src="{root}js/main.js" defer></script>
</body>
</html>
"""


GUIDE_MIN = 5  # 同じ種類の商品がこの数以上あるときだけ「選び方・比較」ガイドを作る
GUIDE_DIR = PRODUCTS_DIR / "guide"


def guide_slug(ptype: str) -> str:
    import hashlib
    return "t-" + hashlib.sha1(_norm_type(ptype).encode("utf-8")).hexdigest()[:8]


def guide_groups(entries: list) -> dict:
    groups = {}
    for r in entries:
        t = _norm_type(r.get("product_type"))
        if t:
            groups.setdefault(t, []).append(r)
    return {t: v for t, v in groups.items() if len(v) >= GUIDE_MIN}


def _guide_page(title, desc, canonical, h1, lead, fv, body, site_name, ld, crumb_label, og_image):
    """選び方・比較ガイド用のページ枠。セクションごとに全幅の背景を使うため、一覧用の _page とは分ける。"""
    root = "../../../"
    nav = (f'<li><a href="{root}index.html">ホーム</a></li><li><a href="{root}about.html">サイトについて</a></li>'
           f'<li><a href="{root}products/" aria-current="page">商品ガイド</a></li><li><a href="{root}contact.html">お問い合わせ</a></li>')
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{e(title)}｜{e(site_name)}</title>
<meta name="description" content="{e(desc)}">
<meta name="robots" content="index,follow">
<link rel="canonical" href="{e(canonical)}">
<link rel="icon" type="image/svg+xml" href="{FAVICON}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{e(site_name)}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(canonical)}">
<meta property="og:image" content="{e(og_image)}">
<meta property="og:locale" content="ja_JP">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://thumbnail.image.rakuten.co.jp">
<link rel="stylesheet" href="{root}css/style.css">
<link rel="stylesheet" href="{root}products/assets/lp.css">
{ld}
</head>
<body class="lp-body lp-type-guide">
<a class="skip-link" href="#main-content">メインコンテンツへスキップ</a>
<header class="site-header"><div class="container header-inner">
<a class="site-logo" href="{root}index.html"><span class="site-logo-mark" aria-hidden="true">N</span>{e(site_name)}</a>
<button type="button" class="nav-toggle" aria-expanded="false" aria-controls="primary-nav" aria-label="メニューを開閉する"><span></span><span></span><span></span></button>
<nav id="primary-nav" class="site-nav" aria-label="メインナビゲーション"><ul>{nav}</ul></nav>
</div></header>
<nav class="lp-breadcrumb container" aria-label="パンくずリスト"><a href="{root}index.html">ホーム</a> <span aria-hidden="true">›</span> <a href="{root}products/">商品ガイド</a> <span aria-hidden="true">›</span> <span aria-current="page">{e(crumb_label)}</span></nav>
<main id="main-content">
<section class="tg-head"><div class="container">
<p class="lp-pr" role="note"><span class="lp-pr-badge">PR</span>楽天アフィリエイト広告を含みます<a href="{root}policy.html">広告・運営方針</a></p>
<h1 class="lp-h1">{e(h1)}</h1><p class="tg-lead">{e(lead)}</p>
{fv}
</div></section>
{body}
<div class="container container--narrow lp-disclaimer">
<p>※このページには楽天アフィリエイトの広告リンクが含まれます。リンク先の楽天市場で商品が購入されると、運営者に報酬が支払われる場合があります。商品の選び方・文章の作り方は<a href="{root}policy.html">広告・運営方針</a>に記載しています。</p>
<p>※商品画像は楽天アフィリエイトを通じて提供されている画像を使用しています（著作権は各ショップ・権利者に帰属します）。</p>
</div>
</main>
<footer class="site-footer"><div class="container footer-inner">
<p class="site-logo"><span class="site-logo-mark" aria-hidden="true">N</span>{e(site_name)}</p>
<nav class="footer-nav" aria-label="フッターナビゲーション"><ul><li><a href="{root}about.html">サイトについて</a></li><li><a href="{root}policy.html">広告・運営方針</a></li><li><a href="{root}products/">商品ガイド</a></li><li><a href="{root}contact.html">お問い合わせ</a></li><li><a href="{root}privacy.html">プライバシーポリシー</a></li></ul></nav>
<p class="footer-copyright">&copy; <span data-current-year>2026</span> {e(site_name)}</p>
</div></footer>
<script src="{root}js/main.js" defer></script>
</body>
</html>
"""


def guide_href_for(rec: dict, entries: list, from_dir_depth: int = 3):
    """LPから、その商品の種類の「選び方・比較」ガイドへのリンク (href, label, 件数)。ガイドが無ければ None。"""
    t = _norm_type(rec.get("product_type"))
    if not t:
        return None
    n = sum(1 for o in entries if _norm_type(o.get("product_type")) == t
            and (o.get("affiliate_url") or "").startswith("https://hb.afl.rakuten.co.jp/")
            and (CONTENT_DIR / f"{o['slug']}.json").exists())
    if n < GUIDE_MIN:
        return None
    return ("../" * from_dir_depth + f"products/guide/{guide_slug(t)}/", rec.get("product_type") or t, n)


def build_type_guides(db: dict, config: dict) -> list:
    """同じ種類の商品（例:ホエイプロテイン）の「選び方・比較」ガイドを書き出す（中身は type_guide.py）。
    値は各LPの原稿に保存済みの楽天APIの取得値と商品説明から抜き出した事実だけ。順位付けはしない（価格の安い順）。"""
    import type_guide
    site, name = config["site_base_url"], config["site_name"]
    entries = published_entries(db)
    groups = guide_groups(entries)
    built = {}
    for t, items in sorted(groups.items()):
        rows = type_guide.guide_rows(items, lambda r: read_json(CONTENT_DIR / f"{r['slug']}.json", None))
        if len(rows) >= GUIDE_MIN:
            built[t] = rows
    written = []
    for t, rows in built.items():
        first = rows[0]["r"]
        label = first.get("product_type") or t
        cat, cat_slug = first.get("category_label", ""), first.get("category", "")
        siblings = [(v[0]["r"].get("product_type") or k, guide_slug(k), len(v)) for k, v in sorted(built.items(), key=lambda kv: -len(kv[1]))
                    if k != t and v[0]["r"].get("category") == cat_slug][:8]
        lead, fv, body, title, desc, h1 = type_guide.render_guide_body(label, cat, cat_slug, rows, siblings)
        url = f"{site}/products/guide/{guide_slug(t)}/"
        latest = max(x["fetched"] for x in rows).replace("/", "-")
        ld = type_guide.jsonld(title, url, site, h1, latest)
        path = GUIDE_DIR / guide_slug(t) / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_guide_page(title, desc, url, h1, lead, fv, body, name, ld, f"{label}の選び方・比較",
                                    site + "/products/assets/og-default.png"), encoding="utf-8")
        written.append(path)
    return written


def _guide_nav(entries):
    g = guide_groups(entries)
    if not g:
        return ""
    chips = "".join(f'<li><a class="lp-chip" href="guide/{guide_slug(t)}/">{e(v[0].get("product_type") or t)}の比較（{len(v)}）</a></li>'
                    for t, v in sorted(g.items(), key=lambda x: -len(x[1])))
    return f'<nav aria-label="選び方・比較"><h2 class="lp-h2">選び方・価格比較から探す</h2><ul class="lp-chips">{chips}</ul></nav>'


def build_listings(db: dict, config: dict, ensure: list = ()) -> list:
    """一覧ページを書き出し、書き出したファイルのパスを返す。"""
    site = config["site_base_url"]
    name = config["site_name"]
    entries = published_entries(db)
    cats = {c["slug"]: c["label"] for c in config["categories"]}
    written = []

    # カテゴリ別
    by_cat = {}
    for r in entries:
        by_cat.setdefault(r["category"], []).append(r)
    for slug in ensure:
        by_cat.setdefault(slug, [])
    for slug, items in by_cat.items():
        label = cats.get(slug, slug)
        cards = "".join(_card(r, "../") for r in items) or "<li>このカテゴリのページは準備中です。</li>"
        body = f'<ul class="lp-related lp-related--grid">{cards}</ul><p class="lp-back"><a href="../">ほかのカテゴリも見る（商品ガイドのトップへ）</a></p>'
        html_text = _page(f"{label}の商品ガイド", f"{label}カテゴリの商品について、特徴・使う場面・購入前に確認したい点を商品情報をもとに整理したページの一覧です。",
                          f"{site}/products/{slug}/", "../../", f"{label}の商品ガイド",
                          f"{label}の商品を、楽天市場の商品情報をもとに1商品ずつ整理しています（{len(items)}件）。", body, name)
        path = PRODUCTS_DIR / slug / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html_text, encoding="utf-8")
        written.append(path)

    # 全体
    cat_links = "".join(f'<li><a class="lp-chip" href="{slug}/">{e(cats.get(slug, slug))}（{len(v)}）</a></li>' for slug, v in sorted(by_cat.items(), key=lambda x: -len(x[1])) if v)
    latest = "".join(_card(r, "") for r in entries[:60])
    body = (f'<nav aria-label="カテゴリ"><h2 class="lp-h2">カテゴリから探す</h2><ul class="lp-chips">{cat_links}</ul></nav>'
            f'{_guide_nav(entries)}'
            f'<h2 class="lp-h2">新着の商品ガイド</h2><ul class="lp-related lp-related--grid">{latest or "<li>まだ公開されたページはありません。</li>"}</ul>')
    html_text = _page("商品ガイド一覧", "楽天市場の商品について、どんな人に向いているか・特徴・購入前に確認したい点を1商品ずつ整理した商品ガイドの一覧です。",
                      f"{site}/products/", "../", "商品ガイド",
                      "楽天市場の商品情報をもとに、「自分に合う商品か」を判断するための情報を1商品ずつ整理しています。", body, name)
    (PRODUCTS_DIR / "index.html").write_text(html_text, encoding="utf-8")
    written.append(PRODUCTS_DIR / "index.html")
    written += build_type_guides(db, config)
    return written

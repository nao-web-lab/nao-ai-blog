"""LPのHTML組み立て。

- 共通デザイン: サイト共通の /css/style.css（ヘッダー・フッター・ボタン等）＋ /products/assets/lp.css（LP用パーツ）
- 商品ごとに layout（beauty/health/appliance/baby/food/interior/living）で section の並び順を変える
- 画像は「画像 → 短い説明 → 画像 → メリット」と文章と交互に配置。画像は必ずアフィリエイトリンクで包む
- 画像は縦横比を保ったまま枠内に収める(object-fit: contain)。トリミング・文字入れはしない
"""

import html
import json
from urllib.parse import quote

from images import sized

LAYOUTS = {
    "beauty":    ["worries", "for_whom", "reasons", "features", "gallery", "scenes", "specs", "checkpoints", "not_for", "faq"],
    "health":    ["worries", "for_whom", "features", "scenes", "gallery", "specs", "checkpoints", "not_for", "faq"],
    "appliance": ["worries", "features", "scenes", "gallery", "specs", "reasons", "for_whom", "checkpoints", "not_for", "faq"],
    "baby":      ["worries", "scenes", "features", "gallery", "checkpoints", "for_whom", "specs", "not_for", "faq"],
    "food":      ["features", "scenes", "gallery", "for_whom", "specs", "checkpoints", "not_for", "faq"],
    "interior":  ["scenes", "gallery", "features", "specs", "for_whom", "checkpoints", "not_for", "faq"],
    "living":    ["worries", "features", "scenes", "gallery", "for_whom", "specs", "checkpoints", "not_for", "faq"],
}
MID_CTA_AFTER = {"beauty": "features", "health": "features", "appliance": "specs", "baby": "features",
                 "food": "gallery", "interior": "features", "living": "features"}

DEFAULT_HEADINGS = {
    "worries": "こんなことで迷っていませんか", "for_whom": "この商品が向いている人", "reasons": "この商品を検討する理由",
    "features": "商品の特徴", "scenes": "使う場面", "gallery": "商品画像で確認する", "specs": "商品情報",
    "checkpoints": "購入前に確認したいポイント", "not_for": "向いていない可能性がある人", "faq": "よくある質問",
    "final": "楽天市場で詳細を確認する",
}

IMG_SIZE = "600x600"


def e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _aff(url, inner, cls="", label=""):
    aria = f' aria-label="{e(label)}"' if label else ""
    return f'<a class="{cls}" href="{e(url)}" target="_blank" rel="nofollow sponsored noopener"{aria}>{inner}</a>'


def _img(img, aff_url, eager=False, cls="lp-figure"):
    loading = 'fetchpriority="high" decoding="async"' if eager else 'loading="lazy" decoding="async"'
    tag = (f'<img src="{e(sized(img["url"], IMG_SIZE))}" width="600" height="600" alt="{e(img["alt"])}" {loading}>')
    cap = f'<figcaption>{e(img["caption"])}</figcaption>' if img.get("caption") else ""
    return f'<figure class="{cls}">{_aff(aff_url, tag, "lp-img-link", img["alt"] + "（楽天市場の商品ページへ）")}{cap}</figure>'


def _cta(p, c, variant="main"):
    label = (c.get("cta") or {}).get("main") or "楽天市場で商品の詳細を見る"
    sub = (c.get("cta") or {}).get("sub") or "価格・在庫・送料は楽天市場の商品ページでご確認ください"
    inner = e(label) + ' <span aria-hidden="true">›</span>'
    btn = _aff(p["affiliate_url"], inner, "btn btn-primary lp-cta-btn")
    return f'<div class="lp-cta lp-cta--{variant}">{btn}<p class="lp-cta-sub">{e(sub)}</p></div>'


def _section(key, heading, body, extra_cls=""):
    return f'<section class="lp-section lp-{key} {extra_cls}" id="{key}"><div class="container container--narrow"><h2 class="lp-h2">{e(heading)}</h2>{body}</div></section>'


def render_page(p: dict, c: dict, image_plan: list, related: list, ctx: dict) -> str:
    """p: 商品データ, c: 文章, image_plan: 画像, related: 関連LP, ctx: URL等"""
    aff = p["affiliate_url"]
    heads = {**DEFAULT_HEADINGS, **{k: v for k, v in (c.get("headings") or {}).items() if v}}
    main_img = image_plan[0] if image_plan else None
    extra_imgs = image_plan[1:]
    root = ctx["root_rel"]           # 例: ../../../
    fetched = ctx["fetched_date"]
    fv = c.get("fv") or {}

    # ---- sections
    blocks = {}
    w = c.get("worries") or {}
    if w.get("items"):
        items = "".join(f"<li>{e(x)}</li>" for x in w["items"])
        bridge = f'<p class="lp-bridge">{e(w.get("bridge"))}</p>' if w.get("bridge") else ""
        blocks["worries"] = _section("worries", heads["worries"], f'<ul class="lp-check lp-check--worry">{items}</ul>{bridge}', "section--muted")
    if c.get("for_whom"):
        items = "".join(f"<li>{e(x)}</li>" for x in c["for_whom"])
        blocks["for_whom"] = _section("for_whom", heads["for_whom"], f'<ul class="lp-check">{items}</ul>')
    if c.get("reasons"):
        cards = "".join(f'<div class="lp-reason"><span class="lp-reason-no">{i}</span><div><h3>{e(r["title"])}</h3><p>{e(r["body"])}</p></div></div>'
                        for i, r in enumerate(c["reasons"], 1))
        blocks["reasons"] = _section("reasons", heads["reasons"], f'<div class="lp-reasons">{cards}</div>')
    if c.get("features"):
        rows = []
        for i, f in enumerate(c["features"]):
            img = extra_imgs[i] if i < len(extra_imgs) else None
            media = _img(img, aff) if img else ""
            merit = f'<p class="lp-merit"><strong>読者にとってのメリット</strong>{e(f.get("merit"))}</p>' if f.get("merit") else ""
            side = " lp-feature--rev" if i % 2 else ""
            rows.append(f'<div class="lp-feature{side}{" lp-feature--noimg" if not img else ""}">{media}'
                        f'<div class="lp-feature-text"><h3><span class="lp-feature-no">{i + 1:02d}</span>{e(f["title"])}</h3><p>{e(f["body"])}</p>{merit}</div></div>')
        blocks["features"] = _section("features", heads["features"], "".join(rows))
    if c.get("scenes"):
        cards = "".join(f'<div class="lp-scene"><h3>{e(s["title"])}</h3><p>{e(s["body"])}</p></div>' for s in c["scenes"])
        blocks["scenes"] = _section("scenes", heads["scenes"], f'<div class="lp-scenes">{cards}</div>', "section--muted")
    if len(image_plan) >= 2:
        figs = "".join(_img(img, aff, cls="lp-gallery-item") for img in image_plan)
        note = '<p class="lp-note">画像は楽天市場の商品ページに掲載されているものです。タップすると商品ページが開きます。</p>'
        blocks["gallery"] = _section("gallery", heads["gallery"],
                                     f'<div class="lp-gallery" role="list" aria-label="商品画像">{figs}</div>'
                                     f'<p class="lp-gallery-hint" aria-hidden="true">← 横にスクロールできます →</p>{note}')
    # 商品情報（APIの取得値＋商品説明に根拠がある項目のみ）
    rows = [("商品名", e(p["display_name"]))]
    price_label = f'¥{p["price"]:,}' + ("（税込）" if p.get("tax_flag") == 0 else "") + f'<span class="lp-muted">　{e(fetched)}時点</span>'
    rows.append(("価格", price_label))
    if p.get("postage_flag") == 0:
        rows.append(("送料", f'送料込み<span class="lp-muted">　{e(fetched)}時点の表示</span>'))
    rows.append(("楽天市場のレビュー", f'平均 {p["review_average"]:.2f}（{p["review_count"]:,}件）<span class="lp-muted">　{e(fetched)}時点</span>'))
    if p.get("shop_name"):
        rows.append(("販売ショップ", e(p["shop_name"])))
    for r in p.get("spec_rows") or []:
        rows.append((e(r["label"]), e(r["value"])))
    table = "".join(f"<tr><th scope=\"row\">{k}</th><td>{v}</td></tr>" for k, v in rows)
    spec_img = f'<div class="lp-spec-img">{_img(main_img, aff)}</div>' if main_img else ""
    blocks["specs"] = _section("specs", heads["specs"],
                               f'<div class="lp-spec">{spec_img}<div class="lp-table-wrap"><table class="lp-table">{table}</table></div></div>'
                               f'<p class="lp-note">価格・送料・在庫・ポイントは変動します。購入前に楽天市場の商品ページで最新情報をご確認ください。'
                               f'記載のない仕様は、このページでは確認できていません。</p>')
    if c.get("checkpoints"):
        items = "".join(f"<li>{e(x)}</li>" for x in c["checkpoints"])
        blocks["checkpoints"] = _section("checkpoints", heads["checkpoints"], f'<ol class="lp-points">{items}</ol>', "section--muted")
    if c.get("not_for"):
        items = "".join(f"<li>{e(x)}</li>" for x in c["not_for"])
        blocks["not_for"] = _section("not_for", heads["not_for"], f'<ul class="lp-check lp-check--no">{items}</ul>')
    if c.get("faq"):
        items = "".join(f'<details class="faq-item"><summary>{e(f["q"])}</summary><p>{e(f["a"])}</p></details>' for f in c["faq"])
        blocks["faq"] = _section("faq", heads["faq"], items)

    order = LAYOUTS.get(p["layout"], LAYOUTS["living"])
    mid_after = MID_CTA_AFTER.get(p["layout"], "features")
    body_sections = []
    for key in order:
        if key in blocks:
            body_sections.append(blocks[key])
            if key == mid_after:
                body_sections.append(f'<div class="container container--narrow">{_cta(p, c, "mid")}</div>')

    # 関連商品
    related_html = ""
    if related:
        cards = "".join(
            f'<li class="lp-related-card"><a href="{e(r["href"])}">'
            f'<img src="{e(sized(r["image"], "300x300"))}" width="300" height="300" alt="{e(r["name"])}" loading="lazy" decoding="async">'
            f'<span class="lp-related-cat">{e(r["category_label"])}</span><span class="lp-related-name">{e(r["title"])}</span></a></li>'
            for r in related)
        related_html = _section("related", "あわせて検討されやすい商品", f'<ul class="lp-related">{cards}</ul>'
                                '<p class="lp-note">各ページにも楽天アフィリエイトのリンクを含みます。</p>', "section--muted")

    # ---- final CTA
    final_img = _img(main_img, aff, cls="lp-final-img") if main_img else ""
    summary = f'<p>{e(c.get("summary"))}</p>' if c.get("summary") else ""
    final = (f'<section class="lp-section lp-final" id="final"><div class="container container--narrow"><div class="lp-final-box">'
             f'<h2 class="lp-h2">{e(heads["final"])}</h2>{final_img}{summary}<p>{e((c.get("cta") or {}).get("final_lead"))}</p>'
             f'{_cta(p, c, "final")}</div></div></section>')

    # ---- FV
    points = "".join(f"<li>{e(x)}</li>" for x in fv.get("points") or [])
    fv_img = _img(main_img, aff, eager=True, cls="lp-fv-img") if main_img else ""
    stars = f'<p class="lp-rating">楽天市場のレビュー平均 <strong>{p["review_average"]:.2f}</strong>（{p["review_count"]:,}件・{e(fetched)}時点）</p>'
    fv_html = (f'<section class="lp-fv"><div class="container container--narrow">'
               f'<p class="lp-eyebrow">{e(fv.get("eyebrow"))}</p><h1 class="lp-h1">{e(c["h1"])}</h1>'
               f'<div class="lp-fv-grid">{fv_img}<div class="lp-fv-text"><p class="lp-catch">{e(fv.get("catch"))}</p>'
               f'<p class="lp-lead">{e(fv.get("lead"))}</p><ul class="lp-fv-points">{points}</ul>{stars}{_cta(p, c, "fv")}</div></div></div></section>')

    # ---- breadcrumb / JSON-LD
    crumbs = [("ホーム", f'{root}index.html', ctx["site_url"] + "/"),
              ("商品ガイド", f'{root}products/', ctx["site_url"] + "/products/"),
              (p["category_label"], f'{root}products/{p["category"]}/', ctx["site_url"] + f'/products/{p["category"]}/'),
              (p["display_name"], None, ctx["public_url"])]
    crumb_html = " <span aria-hidden=\"true\">›</span> ".join(
        f'<a href="{e(h)}">{e(n)}</a>' if h else f'<span aria-current="page">{e(n)}</span>' for n, h, _ in crumbs)
    ld = [
        {"@context": "https://schema.org", "@type": "BreadcrumbList",
         "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": u} for i, (n, _, u) in enumerate(crumbs)]},
        {"@context": "https://schema.org", "@type": "Product", "name": p["display_name"],
         "image": [sized(i["url"], IMG_SIZE) for i in image_plan], "description": c.get("meta_description", ""),
         "sku": p["item_code"], "category": p["category_label"]},
        {"@context": "https://schema.org", "@type": "WebPage", "name": c["title"], "url": ctx["public_url"],
         "datePublished": ctx["published"], "dateModified": ctx["modified"], "inLanguage": "ja"},
    ]
    ld_html = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld)

    title = f'{c["title"]}｜{ctx["site_name"]}'
    keywords = ", ".join(c.get("_keywords") or [])
    og_image = ctx["site_url"] + "/products/assets/og-default.png"
    nav = (f'<li><a href="{root}index.html">ホーム</a></li><li><a href="{root}about.html">サイトについて</a></li>'
           f'<li><a href="{root}products/">商品ガイド</a></li><li><a href="{root}contact.html">お問い合わせ</a></li>')

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{e(title)}</title>
<meta name="description" content="{e(c.get('meta_description'))}">
<meta name="robots" content="index,follow">
{f'<meta name="keywords" content="{e(keywords)}">' if keywords else ''}
<link rel="canonical" href="{e(ctx['public_url'])}">
<link rel="icon" type="image/svg+xml" href="{ctx['favicon']}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{e(ctx['site_name'])}">
<meta property="og:title" content="{e(c['title'])}">
<meta property="og:description" content="{e(c.get('og_description') or c.get('meta_description'))}">
<meta property="og:url" content="{e(ctx['public_url'])}">
<meta property="og:image" content="{e(og_image)}">
<meta property="og:locale" content="ja_JP">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://thumbnail.image.rakuten.co.jp">
{f'<link rel="preload" as="image" href="{e(sized(main_img["url"], IMG_SIZE))}" fetchpriority="high">' if main_img else ''}
<link rel="stylesheet" href="{root}css/style.css">
<link rel="stylesheet" href="{root}products/assets/lp.css">
{ld_html}
</head>
<body class="lp-body lp-layout-{e(p['layout'])}">
<a class="skip-link" href="#main-content">メインコンテンツへスキップ</a>
<header class="site-header"><div class="container header-inner">
<a class="site-logo" href="{root}index.html"><span class="site-logo-mark" aria-hidden="true">N</span>{e(ctx['site_name'])}</a>
<button type="button" class="nav-toggle" aria-expanded="false" aria-controls="primary-nav" aria-label="メニューを開閉する"><span></span><span></span><span></span></button>
<nav id="primary-nav" class="site-nav" aria-label="メインナビゲーション"><ul>{nav}</ul></nav>
</div></header>
<div class="lp-pr" role="note"><div class="container container--narrow"><span class="lp-pr-badge">PR</span>本ページは楽天アフィリエイトを利用した広告を含みます。リンク先の楽天市場で商品が購入されると、運営者に報酬が支払われる場合があります。</div></div>
<nav class="lp-breadcrumb container container--narrow" aria-label="パンくずリスト">{crumb_html}</nav>
<main id="main-content">
{fv_html}
{''.join(body_sections)}
{final}
{related_html}
<div class="container container--narrow lp-disclaimer">
<p>※本ページの内容は{e(fetched)}時点で楽天市場に登録されている商品情報をもとに作成しています。商品の仕様・価格・在庫・レビュー件数などは変更されている場合があります。最新の情報は楽天市場の商品ページでご確認ください。</p>
<p>※商品画像は楽天アフィリエイトを通じて提供されている画像を使用しています（著作権は各ショップ・権利者に帰属します）。</p>
<p class="lp-muted">最終更新: {e(ctx['modified'][:10])}</p>
</div>
</main>
<footer class="site-footer"><div class="container footer-inner">
<p class="site-logo"><span class="site-logo-mark" aria-hidden="true">N</span>{e(ctx['site_name'])}</p>
<nav class="footer-nav" aria-label="フッターナビゲーション"><ul><li><a href="{root}about.html">サイトについて</a></li><li><a href="{root}products/">商品ガイド</a></li><li><a href="{root}contact.html">お問い合わせ</a></li><li><a href="{root}privacy.html">プライバシーポリシー</a></li></ul></nav>
<p class="footer-copyright">&copy; <span data-current-year>2026</span> {e(ctx['site_name'])}</p>
</div></footer>
<script src="{root}js/main.js" defer></script>
</body>
</html>
"""

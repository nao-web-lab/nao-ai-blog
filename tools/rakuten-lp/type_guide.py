"""同じ種類の商品を並べた「選び方・比較」ガイド（/products/guide/t-xxxx/）のHTML組み立て。

方針（RULES.md に従う）
- 値はすべて、各LPの原稿(data/content)に保存済みの楽天APIの取得値と、商品説明から抜き出した事実(facts)・注意点だけを使う
- 順位・おすすめ順は付けない（価格の安い順）。紹介料率は使わない
- 商品画像は楽天APIのURLを直リンク（サイズ指定のみ）。画像は必ずアフィリエイトリンクで包む
- 図（価格の分布）はHTML/CSSで作り、同じ内容を文字でも書く
- 「各商品ページから抜粋」した注意点には、出典の商品ページへのリンクを付ける
"""

import difflib
import json
import statistics
import unicodedata

from images import sized
from render import e, pick_specs

# 「比べる仕様」に出しても判断材料になりにくい項目名
SKIP_LABELS = ("商品名", "ショップ", "メーカー", "製造", "生産", "原産", "工場", "販売", "広告文責", "JAN", "区分", "注意")
AFF_REL = 'target="_blank" rel="nofollow sponsored noopener"'


def _n(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").replace(" ", "").replace("　", "")


def _pick_unique(cands: list, limit: int, max_len: int = 70) -> list:
    """(文, 出典) の候補から、似た文を除いて最大limit件を選ぶ。商品が偏らないよう、同じ商品からは1件まで。"""
    out, seen_src, seen_txt = [], set(), []
    for text, src in cands:
        t = (text or "").strip().rstrip("。")
        if not t or len(t) > max_len or src["slug"] in seen_src:
            continue
        nt = _n(t)
        if any(difflib.SequenceMatcher(None, nt, s).ratio() > 0.55 for s in seen_txt):
            continue
        out.append((t, src))
        seen_src.add(src["slug"])
        seen_txt.append(nt)
        if len(out) >= limit:
            break
    return out


def _quartiles(prices: list) -> tuple:
    if len(prices) < 4:
        return min(prices), max(prices)
    q = statistics.quantiles(prices, n=4)
    return int(q[0]), int(q[2])


def _aff_img(row: dict, size: str, w: int, eager: bool = False) -> str:
    img = row["img"]
    if not img:
        return ""
    load = 'fetchpriority="high" decoding="async"' if eager else 'loading="lazy" decoding="async"'
    return (f'<a class="lp-img-link" href="{e(row["aff"])}" {AFF_REL} aria-label="{e(row["name"])}（楽天市場の商品ページへ）">'
            f'<img src="{e(sized(img["url"], size))}" width="{w}" height="{w}" alt="{e(img.get("alt") or row["name"])}" {load}></a>')


def guide_rows(items: list, read_content) -> list:
    """ガイドに載せる商品データを作る。原稿が無い・価格が読めない商品は載せない。"""
    rows = []
    for r in items:
        data = read_content(r)
        if not data:
            continue
        pr, ct, an = data["product"], data.get("content") or {}, data.get("analysis") or {}
        try:
            price, avg, cnt = int(pr["price"]), float(pr["review_average"]), int(pr["review_count"])
        except (KeyError, TypeError, ValueError):
            continue
        aff = pr.get("affiliate_url") or r.get("affiliate_url") or ""
        if not aff.startswith("https://hb.afl.rakuten.co.jp/"):
            continue  # 計測できないリンクは使わない
        plan = [i for i in (data.get("image_plan") or []) if i.get("url")]
        facts = [f for f in (an.get("facts") or []) if f and len(f) <= 60][:2]
        rows.append({
            "r": r, "slug": r["slug"], "name": r["display_name"], "price": price, "avg": avg, "cnt": cnt,
            "fetched": (pr.get("fetched_at") or r.get("created_at") or "")[:10].replace("-", "/"),
            "spec": pick_specs(pr.get("spec_rows"), 2), "spec_labels": [s.get("label", "") for s in pr.get("spec_rows") or []],
            "aff": aff, "img": plan[0] if plan else None, "facts": facts,
            "for_whom": (ct.get("for_whom") or [""])[0],
            "caution": ((an.get("cautions") or []) + (ct.get("checkpoints") or []) + [""])[0],
            "checkpoints": ct.get("checkpoints") or [], "cautions": an.get("cautions") or [],
            "not_for": ct.get("not_for") or an.get("not_for") or [], "worries": an.get("worries") or [],
            "postage_free": pr.get("postage_flag") == 0,
        })
    rows.sort(key=lambda x: x["price"])
    return rows


def render_guide_body(label: str, cat_label: str, cat_slug: str, rows: list, siblings: list) -> tuple:
    """(lead, fv_html, body_html, title, desc, h1) を返す。siblings: 同じカテゴリの他ガイド [(label, slug, n)]"""
    n = len(rows)
    prices = [x["price"] for x in rows]
    lo, hi = min(prices), max(prices)
    med = int(statistics.median(prices))
    q1, q3 = _quartiles(prices)
    latest = max(x["fetched"] for x in rows)
    oldest = min(x["fetched"] for x in rows)
    src = lambda x: {"slug": x["slug"], "name": x["name"], "href": "../../" + x["r"]["lp_path"].replace("products/", "", 1).replace("index.html", "")}

    # 仕様欄で比べやすい項目（2商品以上に記載がある項目名）
    lab_count = {}
    for x in rows:
        for lab in set(_n(l) for l in x["spec_labels"] if l):
            lab_count[lab] = lab_count.get(lab, 0) + 1
    common_labels = [l for l, c in sorted(lab_count.items(), key=lambda t: (-t[1], t[0])) if c >= 2 and not any(k in l for k in SKIP_LABELS)][:4]

    worries = _pick_unique([(w, src(x)) for x in rows for w in x["worries"]], 3, 60)
    cautions = _pick_unique([(c, src(x)) for x in rows for c in (x["cautions"] + x["checkpoints"])], 6, 70)
    not_for = _pick_unique([(c, src(x)) for x in rows for c in x["not_for"]], 4, 60)

    title = f"{label}の選び方｜{n}商品の価格・特徴・注意点を比較"
    h1 = f"{label}の選び方と{n}商品の比較"
    desc = (f"{label}を選ぶ前に確認したい点と、楽天市場で扱われている{n}商品の価格（¥{lo:,}〜¥{hi:,}）・レビュー数・特徴・注意点を一覧で比較。"
            f"順位付けはせず価格順に並べています。")
    lead = (f"{label}を買う前に、予算の目安・比べる仕様・自分に合わない条件を確認したい人向けのページです。"
            f"{n}商品を価格・楽天レビュー・特徴・注意点で並べました（{cat_label}）。")

    # ---- FV（PR表記・H1は外側の共通部品で出す）
    strip_rows = [x for x in rows if x["img"]][:4]
    strip = "".join(f'<li>{_aff_img(x, "300x300", 300, eager=(i == 0))}</li>' for i, x in enumerate(strip_rows))
    know = [("summary", "選ぶ前に決めること"), ("price", "価格帯"), ("table", "比較表"), ("items", "商品ごとの特徴"),
            ("check", "購入前の確認点"), ("notfor", "向いていない場合")]
    know_html = "".join(f'<a href="#{k}">{v}</a>' for k, v in know if k != "notfor" or not_for)
    fv = (f'<div class="tg-fv">'
          + (f'<ul class="tg-strip" aria-label="このガイドで比較している{e(label)}の商品画像（一部）">{strip}</ul>' if strip else "")
          + f'<div class="tg-fv-text">'
          f'<p class="lp-know"><span class="lp-know-label">このページで分かること</span>{know_html}</p>'
          f'<p class="tg-fv-cta"><a class="btn tg-btn-ghost" href="#table">{n}商品の比較表を見る <span aria-hidden="true">↓</span></a></p></div>'
          '</div>')

    # ---- 選ぶ前に決めること
    if common_labels:
        spec_sentence = f"このガイドの商品で、2件以上の商品ページに記載があった項目は「{e('・'.join(common_labels))}」です。"
    else:
        spec_sentence = "このガイドの商品は仕様の書き方がそろっていないため、量・サイズ・セット内容にあたる記載を商品ごとに探して比べてください。"
    worry_html = ""
    if worries:
        worry_html = ('<p class="tg-sub">各商品ページで整理した「よくある迷い」の例</p><ul class="lp-check lp-check--worry">'
                      + "".join(f'<li>{e(t)}</li>' for t, _ in worries) + '</ul>')
    summary = (
        f'<section class="lp-section" id="summary"><div class="container container--narrow">'
        f'<h2 class="lp-h2">{e(label)}を選ぶ前に決めておくこと</h2>'
        f'<ol class="tg-steps">'
        f'<li><span class="tg-step-no" aria-hidden="true">1</span><div><h3>予算の目安を決める</h3>'
        f'<p>このページの{n}商品は ¥{lo:,}〜¥{hi:,}。真ん中の価格（中央値）は ¥{med:,}'
        + (f'、半数が ¥{q1:,}〜¥{q3:,} の範囲' if n >= 4 else '') + f'です（{e(latest)}までの確認時点）。</p></div></li>'
        f'<li><span class="tg-step-no" aria-hidden="true">2</span><div><h3>比べる仕様をそろえる</h3>'
        f'<p>価格は量・サイズ・セット内容が違うと単純に比べられません。{spec_sentence}比較表の仕様欄と各商品ページで確認してください。</p></div></li>'
        f'<li><span class="tg-step-no" aria-hidden="true">3</span><div><h3>使う場面と、合わない条件を確認する</h3>'
        f'<p>レビューは件数と平均の両方を見ます。そのうえで、下の「購入前の確認点」「向いていない可能性がある場合」に当てはまらないかを確かめると、買ってからの「思っていたのと違う」を減らせます。</p></div></li>'
        f'</ol>{worry_html}</div></section>')

    # ---- 価格の分布（CSSの図＋文字）
    span = max(hi - lo, 1)
    dots = "".join(f'<span class="tg-dot" style="left:{(x["price"] - lo) / span * 100:.1f}%" title="{e(x["name"])} ¥{x["price"]:,}"></span>' for x in rows)
    band = (f'<span class="tg-band" style="left:{(q1 - lo) / span * 100:.1f}%;width:{(q3 - q1) / span * 100:.1f}%"></span>' if n >= 4 else "")
    medmark = f'<span class="tg-med" style="left:{(med - lo) / span * 100:.1f}%"><span>中央値 ¥{med:,}</span></span>'
    price = (
        f'<section class="lp-section section--muted" id="price"><div class="container container--narrow">'
        f'<h2 class="lp-h2">価格帯を図で見る</h2>'
        f'<figure class="tg-range" aria-describedby="tg-range-cap"><div class="tg-axis" aria-hidden="true">{band}{dots}{medmark}</div>'
        f'<div class="tg-axis-labels" aria-hidden="true"><span>¥{lo:,}</span><span>¥{hi:,}</span></div>'
        f'<figcaption id="tg-range-cap">点1つが1商品です。'
        + ("濃い帯は、価格の安い順に並べたときの真ん中の半数（" + f"¥{q1:,}〜¥{q3:,}" + "）。" if n >= 4 else "")
        + f'最安 ¥{lo:,}、最高 ¥{hi:,}、中央値 ¥{med:,}。</figcaption></figure>'
        f'<p class="lp-note">価格は{e(oldest)}〜{e(latest)}に当サイトが楽天市場で確認した表示価格です。送料・ポイント・クーポンは含みません。品質や優劣を示すものではありません。</p>'
        f'</div></section>')

    # ---- 比較表
    trs = ""
    for x in rows:
        s = src(x)
        spec = f'<span class="lp-muted lp-compare-spec">{e(x["spec"])}</span>' if x["spec"] else ""
        thumb = f'<span class="tg-thumb">{_aff_img(x, "128x128", 64)}</span>' if x["img"] else ""
        trs += (f'<tr><th scope="row"><div class="tg-row">{thumb}<span><a href="{e(s["href"])}">{e(x["name"])}</a>{spec}</span></div></th>'
                f'<td>¥{x["price"]:,}<span class="lp-muted lp-compare-date">{e(x["fetched"])}時点{"・送料込み表示" if x["postage_free"] else ""}</span></td>'
                f'<td>{x["avg"]:.2f}<span class="lp-muted lp-compare-date">{x["cnt"]:,}件</span></td></tr>')
    table = (
        f'<section class="lp-section" id="table"><div class="container container--narrow">'
        f'<h2 class="lp-h2">{e(label)} {n}商品の比較表（価格の安い順）</h2>'
        f'<p>順位やおすすめ順ではなく、価格の安い順です。商品名を押すと、当サイトの詳しい解説（向いている人・注意点・仕様）を読めます。画像を押すと楽天市場の商品ページが開きます。</p>'
        f'<div class="lp-table-wrap"><table class="lp-table lp-compare tg-table"><thead><tr><th scope="col">商品</th><th scope="col">価格</th><th scope="col">楽天レビュー</th></tr></thead><tbody>{trs}</tbody></table></div>'
        f'<p class="lp-note">価格・送料・在庫・ポイントは変動します。確認日は商品ごとに表示しています。購入前に楽天市場の商品ページで最新情報をご確認ください。</p>'
        f'</div></section>')

    # ---- 商品ごとの特徴（カード）
    cards = ""
    for x in rows:
        s = src(x)
        facts = "".join(f'<li>{e(f)}</li>' for f in x["facts"])
        who = f'<p class="tg-card-who"><b>向いている人</b>{e(x["for_whom"])}</p>' if x["for_whom"] else ""
        cau = f'<p class="tg-card-caution"><b>確認したい点</b>{e(x["caution"])}</p>' if x["caution"] else ""
        cards += (f'<li class="tg-card"><div class="tg-card-img">{_aff_img(x, "300x300", 300)}</div><div class="tg-card-body">'
                  f'<h3><a href="{e(s["href"])}">{e(x["name"])}</a></h3>'
                  f'<p class="tg-card-meta">¥{x["price"]:,}<span class="lp-muted">（{e(x["fetched"])}時点）</span>・楽天レビュー {x["avg"]:.2f}（{x["cnt"]:,}件）</p>'
                  + (f'<ul class="tg-card-facts">{facts}</ul>' if facts else "") + who + cau +
                  f'<p class="tg-card-links"><a href="{e(s["href"])}">詳しい解説を読む</a>'
                  f'<a href="{e(x["aff"])}" {AFF_REL}>楽天市場で価格・詳細を確認する <span aria-hidden="true">↗</span></a></p></div></li>')
    items = (
        f'<section class="lp-section section--muted" id="items"><div class="container container--narrow">'
        f'<h2 class="lp-h2">商品ごとの特徴と向いている人</h2>'
        f'<p>各商品の説明文に書かれている内容から、特徴・向いている人・確認したい点を1つずつ抜き出しました。</p>'
        f'<ul class="tg-cards">{cards}</ul></div></section>')

    # ---- 購入前の確認点・向いていない場合（出典リンクつき）
    def _src_list(lst, cls):
        return f'<ul class="{cls}">' + "".join(
            f'<li>{e(t)}<a class="tg-src" href="{e(s["href"])}">出典：{e(s["name"][:28])}{"…" if len(s["name"]) > 28 else ""}の解説</a></li>' for t, s in lst) + '</ul>'
    check = ""
    if cautions:
        check = (f'<section class="lp-section" id="check"><div class="container container--narrow">'
                 f'<h2 class="lp-h2">{e(label)}の購入前に確認したいこと</h2>'
                 f'<p>各商品の説明文にある注意点から、内容が重ならないものを抜粋しました。書かれている条件（期限・対応・付属品など）は出典の商品のものです。ほかの{e(label)}を選ぶときも、同じ観点で商品ページを確認すると判断しやすくなります。</p>'
                 + _src_list(cautions, "lp-points tg-points") + '</div></section>')
    nf = ""
    if not_for:
        nf = (f'<section class="lp-section section--muted" id="notfor"><div class="container container--narrow">'
              f'<h2 class="lp-h2">向いていない可能性がある場合</h2>'
              + _src_list(not_for, "lp-check lp-check--no") +
              f'<p class="lp-note">当てはまる場合は、比較表の別の商品も確認するか、購入を見送ることも検討してください。</p></div></section>')

    # ---- このガイドの作り方・関連
    sib = "".join(f'<li><a class="lp-chip" href="../{e(s)}/">{e(l)}の比較（{c}）</a></li>' for l, s, c in siblings)
    method = (
        f'<section class="lp-section" id="method"><div class="container container--narrow">'
        f'<h2 class="lp-h2">このガイドの作り方</h2><ul class="tg-method">'
        f'<li><b>選んだ商品</b>当サイトで1商品ずつ解説ページを作った{e(label)}のうち、楽天市場の情報を確認できた{n}件すべて。紹介料率は選定にも並び順にも使っていません。</li>'
        f'<li><b>数値の出どころ</b>価格・レビュー平均・レビュー件数は楽天市場の商品情報（各商品の確認日時点）。特徴・注意点は各商品の説明文から抜き出したもので、当サイトが実際に使って確かめたものではありません。</li>'
        f'<li><b>更新</b>商品ページの点検（毎日）に合わせて作り直しています。最終確認日 {e(latest)}。</li></ul>'
        + (f'<h3 class="tg-h3">{e(cat_label)}のほかの比較ガイド</h3><ul class="lp-chips">{sib}</ul>' if sib else "")
        + f'<p class="lp-back"><a href="../../{e(cat_slug)}/">{e(cat_label)}の商品ガイド一覧へ</a>　<a href="../../">商品ガイドのトップへ</a></p>'
        f'</div></section>')

    body = summary + price + table + items + check + nf + method
    return lead, fv, body, title, desc, h1


def jsonld(title: str, url: str, site_url: str, h1: str, modified: str) -> str:
    ld = [
        {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": site_url + "/"},
            {"@type": "ListItem", "position": 2, "name": "商品ガイド", "item": site_url + "/products/"},
            {"@type": "ListItem", "position": 3, "name": h1, "item": url}]},
        {"@context": "https://schema.org", "@type": "WebPage", "name": title, "url": url, "dateModified": modified, "inLanguage": "ja"},
    ]
    return "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld)

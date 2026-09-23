"""公開前の自動品質チェックと自動修正。

- 文章チェック: 誇張・断定・No.1/ランキング・レビュー捏造・体験談の創作・効果効能の断定・AIっぽい定型文・
  商品情報にない数値(スペック/価格の捏造)・必須項目・文字数・他LPとの重複
- 自動修正: 問題のある「文」だけを削除/置換（ページ全体を捨てずに済むように）
- HTMLチェック: title/description/H1/H2/canonical/OGP/構造化データ/viewport/PR表記/CTAリンク一致/
  画像URL(楽天の許可ホストのみ)/alt/width・height/lazy/内部リンク切れ
"""

import difflib
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from images import is_allowed

# 見つけたら「その文を削除」する表現（捏造・断定・煽り・根拠のない最上級）
HARD_PATTERNS = [
    r"絶対", r"必ず", r"確実に", r"100\s*[%％]", r"買わないと損", r"これ一択", r"日本一", r"No\.?\s*1", r"ナンバー\s*ワン",
    r"\d+\s*位", r"ランキング", r"受賞", r"金賞", r"殿堂", r"大絶賛", r"絶賛", r"口コミ(で|では|によると|の評判)", r"レビューでは",
    r"購入者の(声|多く)", r"リピーター(続出|多数)", r"満足度\s*\d", r"医師", r"専門家(も|が)(認め|推奨)", r"治る", r"治す", r"治り",
    r"完治", r"痩せ", r"やせる", r"効く", r"効き目", r"効果があ", r"効果的", r"予防", r"若返", r"消える", r"副作用", r"最安",
    r"在庫(わずか|残りわずか)", r"残りわずか", r"今だけ", r"期間限定", r"今すぐ", r"急いで", r"使ってみ(た|る|ると)", r"実際に使って",
    r"私(も|が)使", r"愛用して", r"手放せな", r"間違いな", r"誰でも", r"完璧",
    r"選ばれ(て|る|た)", r"支持され", r"定番の", r"大人気", r"話題の", r"公式(ストア|ショップ|サイト)", r"累計", r"販売(台数|個数|実績|数)",
    r"売上", r"突破", r"(肌質|肌タイプ|年齢)を問わず", r"どんな肌", r"敏感肌(でも|にも)",
]
# 見つけたら「その文を削除」する定型文（AIっぽい文章）
CLICHE_PATTERNS = [
    r"おすすめの商品です", r"いかがでしたでしょうか", r"いかがでしたか", r"ぜひチェックしてください", r"魅力的な商品です",
    r"注目の商品です", r"便利なアイテムです", r"生活を豊かに", r"ワンランク上", r"マストアイテム", r"必見", r"見逃せない",
    r"一度試してみる価値", r"間違いなし",
]
_HARD_RE = re.compile("|".join(HARD_PATTERNS), re.I)
_CLICHE_RE = re.compile("|".join(CLICHE_PATTERNS), re.I)
UNIT_RE = re.compile(r"(\d[\d,，\.．]*)\s*(円|%|％|mg|g|kg|ml|mL|L|cc|cm|mm|m|W|V|mAh|時間|分|秒|日分|日間|か月|ヶ月|年|枚|個|本|包|粒|袋|回|倍|℃|度|段階|種類|色|人|名|件|台|万)")
PRICE_RE = re.compile(r"[\d,，]+\s*円|￥\s*[\d,]+|¥\s*[\d,]+")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return s.replace(",", "").replace(" ", "")


def _split_sentences(text: str) -> list:
    parts = re.split(r"(?<=[。！？!?])", text)
    return [p for p in parts if p.strip()]


def _walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("_"):
                continue
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def _set(obj, path, value):
    tokens = re.findall(r"[^.\[\]]+|\[\d+\]", path)
    cur = obj
    for t in tokens[:-1]:
        cur = cur[int(t[1:-1])] if t.startswith("[") else cur[t]
    last = tokens[-1]
    if last.startswith("["):
        cur[int(last[1:-1])] = value
    else:
        cur[last] = value


def _sentence_problems(sentence: str, source_norm: str) -> list:
    probs = []
    for m in _HARD_RE.finditer(sentence):
        # 「綿100%」「果汁100%」のように商品情報に書かれている素材・原材料の表記は事実なので許可
        if re.fullmatch(r"100\s*[%％]", m.group(0)):
            ctx = _norm(sentence[max(0, m.start() - 4):m.end()])
            if any(ctx[i:] in source_norm for i in range(len(ctx) - 4)):
                continue
        probs.append(f"誇張/断定/捏造の恐れ「{m.group(0)}」")
        break
    m = _CLICHE_RE.search(sentence)
    if m:
        probs.append(f"定型文「{m.group(0)}」")
    if PRICE_RE.search(sentence):
        probs.append("本文中の価格表記（価格はシステムが取得値を表示する）")
    for num, unit in UNIT_RE.findall(sentence):
        token = _norm(num + unit)
        if token not in source_norm and _norm(num) + _norm(unit) not in source_norm:
            if unit in ("種類", "段階", "色", "個", "人", "名") and _norm(num) in ("1", "2", "3", "4", "5"):
                continue
            probs.append(f"商品情報にない数値「{num}{unit}」")
    return probs


TYPO_FIXES = [(re.compile(r"(お|ご)\1(?=[一-龥])"), r"\1"), (re.compile(r"([をにがはで])\1"), r"\1"), (re.compile(r"。。+"), "。")]


def fix_typos(text: str) -> str:
    for pat, rep in TYPO_FIXES:
        text = pat.sub(rep, text)
    return text


# 健康食品・サプリ・化粧品などでは、身体への作用を連想させる語も使わない（薬機法・健康増進法への配慮）
RISK_PATTERNS = {
    "supplement": [r"成長", r"身長", r"免疫", r"代謝", r"燃焼", r"脂肪", r"デトックス", r"アンチエイジング", r"若々し", r"体質", r"血(圧|糖|液)", r"不足を補", r"健康(に|維持|づくり)", r"元気"],
    "health_food": [r"成長", r"身長", r"免疫", r"代謝", r"燃焼", r"脂肪", r"デトックス", r"体質", r"血(圧|糖|液)", r"健康(に|維持|づくり)"],
    "cosmetics": [r"シミが", r"シワが", r"(消|改善|治|防止)(す|さ|で)", r"アンチエイジング", r"若返", r"細胞", r"浸透して", r"肌の奥"],
    "medical_device": [r"治療", r"症状", r"(痛|こり)が(取|と)れ", r"改善"],
}


def check_risk_text(content: dict, risk: str) -> list:
    """risk_category に応じた追加チェック。該当文を削除し、修正内容を返す。"""
    pats = RISK_PATTERNS.get(risk or "")
    if not pats:
        return []
    rx = re.compile("|".join(pats))
    fixes = []
    for path, text in list(_walk(content)):
        sentences = _split_sentences(text) if len(text) > 30 else [text]
        kept = [s for s in sentences if not rx.search(s)]
        if len(kept) != len(sentences):
            fixes.append(f"{path}: {risk}向けの表現基準で削除")
            _set(content, path, "".join(kept).strip())
    _drop_empty(content)
    return fixes


def check_and_fix_text(content: dict, source_text: str) -> tuple:
    """問題のある文を削除した content と、(削除した問題のリスト) を返す。"""
    source_norm = _norm(source_text)
    fixes = []
    for path, text in list(_walk(content)):
        typo_fixed = fix_typos(text)
        if typo_fixed != text:
            fixes.append(f"{path}: 誤字の可能性を修正")
            _set(content, path, typo_fixed)
            text = typo_fixed
        sentences = _split_sentences(text) if len(text) > 30 else [text]
        kept = []
        for s in sentences:
            probs = _sentence_problems(s, source_norm)
            if probs:
                fixes.append(f"{path}: {'/'.join(probs)} → 削除: {s.strip()[:60]}")
            else:
                kept.append(s)
        new = "".join(kept).strip()
        if new != text:
            _set(content, path, new)
    _drop_empty(content)
    return content, fixes


def _drop_empty(content: dict):
    for key in ("for_whom", "checkpoints", "not_for"):
        if isinstance(content.get(key), list):
            content[key] = [x for x in content[key] if isinstance(x, str) and x.strip()]
    if isinstance(content.get("worries"), dict):
        content["worries"]["items"] = [x for x in content["worries"].get("items", []) if x.strip()]
    if isinstance(content.get("fv"), dict):
        content["fv"]["points"] = [x for x in content["fv"].get("points", []) if x.strip()]
    for key, fields in (("features", ("title", "body")), ("reasons", ("title", "body")), ("scenes", ("title", "body")), ("faq", ("q", "a"))):
        if isinstance(content.get(key), list):
            content[key] = [x for x in content[key] if isinstance(x, dict) and all((x.get(f) or "").strip() for f in fields)]


def structural_issues(content: dict) -> list:
    """必須項目・文字数・構成の不足（hard issue）。"""
    issues = []
    fv = content.get("fv") or {}
    for label, val in (("title", content.get("title")), ("meta_description", content.get("meta_description")),
                       ("h1", content.get("h1")), ("fv.catch", fv.get("catch")), ("fv.lead", fv.get("lead")),
                       ("cta.main", (content.get("cta") or {}).get("main"))):
        if not (val or "").strip():
            issues.append(f"必須項目が空: {label}")
    if len(content.get("title") or "") > 48:
        issues.append("titleが長すぎる")
    md = content.get("meta_description") or ""
    if md and not (50 <= len(md) <= 160):
        issues.append(f"meta descriptionの文字数が不適切({len(md)}字)")
    if len(content.get("features") or []) < 2:
        issues.append("特徴が2つ未満")
    if len(content.get("faq") or []) < 2:
        issues.append("FAQが2つ未満")
    if len(content.get("checkpoints") or []) < 2:
        issues.append("購入前の確認ポイントが2つ未満")
    return issues


def style_issues(content: dict) -> list:
    """ページ内の単調さ（soft issue）。"""
    issues = []
    text = "".join(t for _, t in _walk(content))
    sentences = [s.strip() for s in _split_sentences(text) if len(s.strip()) > 5]
    run = 0
    for s in sentences:
        run = run + 1 if s.endswith("です。") else 0
        if run >= 4:
            issues.append("「〜です。」で終わる文が4回以上連続")
            break
    seen = {}
    for s in sentences:
        if len(s) > 15:
            seen[s] = seen.get(s, 0) + 1
    dups = [s for s, n in seen.items() if n > 1]
    if dups:
        issues.append(f"同じ文の重複: {dups[0][:30]}")
    if text.count("ぜひ") > 2:
        issues.append("「ぜひ」が多い")
    return issues


KEY_FIELDS = (("title",), ("h1",), ("fv", "catch"), ("fv", "lead"), ("worries", "bridge"), ("cta", "final_lead"))


def _get(content, keys):
    cur = content
    for k in keys:
        cur = (cur or {}).get(k) if isinstance(cur, dict) else None
    return cur or ""


def similarity_issues(content: dict, others: list, threshold: float = 0.8) -> list:
    """他のLP(最近のもの)とファーストビュー・見出し・CTAの文言が酷似していないか。"""
    issues = []
    for keys in KEY_FIELDS:
        mine = _get(content, keys)
        if len(mine) < 8:
            continue
        for o in others:
            theirs = _get(o, keys)
            if theirs and difflib.SequenceMatcher(None, mine, theirs).ratio() >= threshold:
                issues.append(f"他LPと酷似: {'.'.join(keys)}「{mine[:25]}」")
                break
    my_heads = set((content.get("headings") or {}).values())
    for o in others:
        same = my_heads & set((o.get("headings") or {}).values())
        same.discard("")
        if len(same) >= 4:
            issues.append("見出しの多くが他LPと同一（" + "、".join(sorted(same))[:120] + "）")
            break
    return issues


# ---------------------------------------------------------------- HTML
class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.text_in = {}
        self._stack = []
        self.jsonld = []
        self._in_jsonld = False

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        self._stack.append(tag)
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self._in_jsonld = True
            self.jsonld.append("")

    def handle_endtag(self, tag):
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        if tag == "script":
            self._in_jsonld = False

    def handle_data(self, data):
        if self._in_jsonld:
            self.jsonld[-1] += data
        if self._stack:
            self.text_in.setdefault(self._stack[-1], []).append(data)


def check_html(html: str, page_path: Path, public_url: str, affiliate_url: str, repo_root: Path) -> list:
    issues = []
    c = _Collector()
    c.feed(html)
    tags = c.tags

    def attrs_of(tag, **match):
        return [a for t, a in tags if t == tag and all(a.get(k) == v for k, v in match.items())]

    if not re.search(r"<title>[^<]{10,}</title>", html):
        issues.append("titleがない/短い")
    if not attrs_of("meta", name="description"):
        issues.append("meta descriptionがない")
    if html.count("<h1") != 1:
        issues.append("H1が1つではない")
    if html.count("<h2") < 3:
        issues.append("H2が少ない")
    canon = attrs_of("link", rel="canonical")
    if not canon or canon[0].get("href") != public_url:
        issues.append("canonicalが不正")
    for prop in ("og:title", "og:description", "og:url", "og:image", "og:type"):
        if not attrs_of("meta", property=prop):
            issues.append(f"OGP {prop} がない")
    if not attrs_of("meta", name="viewport"):
        issues.append("viewportがない（スマホ非対応）")
    if "PR" not in html or "アフィリエイト" not in html:
        issues.append("アフィリエイト(PR)表記がない")
    for j in c.jsonld:
        try:
            json.loads(j)
        except ValueError:
            issues.append("構造化データ(JSON-LD)の形式エラー")
    if not c.jsonld:
        issues.append("構造化データがない")

    # CTA / 外部リンク
    ext_links = [a for t, a in tags if t == "a" and (a.get("href") or "").startswith("http")]
    aff_links = [a for a in ext_links if "rakuten" in (a.get("href") or "")]
    if len(aff_links) < 2:
        issues.append("CTAが少ない")
    for a in aff_links:
        if a.get("href") != affiliate_url:
            issues.append(f"affiliate URLと一致しないリンク: {a.get('href')[:60]}")
        if "sponsored" not in (a.get("rel") or ""):
            issues.append("アフィリエイトリンクに rel=sponsored がない")
    for a in ext_links:
        host = urlparse(a.get("href")).netloc
        if host not in ("hb.afl.rakuten.co.jp", "nao-web-lab.github.io") and "rakuten" not in host:
            issues.append(f"想定外の外部リンク: {host}")

    # 画像
    imgs = [a for t, a in tags if t == "img"]
    for i, a in enumerate(imgs):
        src = a.get("src") or ""
        if src.startswith("http") and not is_allowed(src):
            issues.append(f"許可されていない画像URL: {src[:60]}")
        if not (a.get("alt") or "").strip():
            issues.append(f"altがない画像: {src[:50]}")
        if not (a.get("width") and a.get("height")):
            issues.append(f"width/height未指定の画像: {src[:50]}")
    if imgs:
        if imgs[0].get("loading") == "lazy":
            issues.append("ファーストビュー画像がlazy")
        if any(a.get("loading") != "lazy" for a in imgs[1:]):
            issues.append("2枚目以降の画像がlazyでない")

    # 内部リンク切れ
    for t, a in tags:
        href = a.get("href") if t in ("a", "link") else None
        if not href or href.startswith(("http", "#", "mailto:", "data:")):
            continue
        target = (page_path.parent / href.split("#")[0]).resolve()
        if target.is_dir():
            target = target / "index.html"
        try:
            target.relative_to(repo_root)
        except ValueError:
            issues.append(f"サイト外を指す相対リンク: {href}")
            continue
        if not target.exists():
            issues.append(f"リンク切れ: {href}")
    return issues


def is_valid_affiliate_url(url: str) -> bool:
    u = urlparse(url or "")
    return u.scheme == "https" and u.netloc == "hb.afl.rakuten.co.jp" and "item.rakuten.co.jp" in (url or "").replace("%2F", "/").replace("%3A", ":")


CTA_POOL = [
    "楽天市場で商品の詳細を見る", "楽天市場で最新の価格を確認する", "商品ページで仕様をチェックする",
    "楽天市場でサイズ・仕様を確かめる", "在庫と配送日を楽天市場で確認", "楽天市場の販売ページを開く",
    "楽天市場でレビュー件数と評価を見る", "カラー・種類を楽天市場で選ぶ", "楽天市場で送料と価格を確認する",
]


def diversify_cta(content: dict, others: list, rng) -> None:
    """CTAボタンの文言が直近のLPと同じにならないようにする（affiliate URLは変えない）。"""
    recent = [(_get(o, ("cta", "main"))) for o in others[:8]]
    cta = content.setdefault("cta", {})
    mine = cta.get("main") or ""
    too_similar = (not mine) or len(mine) > 22 or any(r and difflib.SequenceMatcher(None, mine, r).ratio() >= 0.8 for r in recent)
    if too_similar:
        choices = [c for c in CTA_POOL if c not in recent] or CTA_POOL
        cta["main"] = rng.choice(choices)


def check_image_texts(plan: list, source_text: str, product_name: str) -> list:
    """画像のalt・キャプションも同じ基準でチェック（画像内の販促文言をページ上で繰り返さない）。"""
    source_norm = _norm(source_text)
    fixes = []
    for i, img in enumerate(plan):
        if img.get("caption") and _sentence_problems(img["caption"], source_norm):
            fixes.append(f"画像{i + 1}のキャプションを削除: {img['caption'][:40]}")
            img["caption"] = ""
        if _sentence_problems(img.get("alt", ""), source_norm):
            img["alt"] = f"{product_name}の商品画像（{i + 1}枚目）"
            fixes.append(f"画像{i + 1}のaltを中立的な表現に変更")
    return fixes

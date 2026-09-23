"""AIによる商品分析・LP文章生成・セルフレビュー。

1商品あたりのGemini呼び出しは原則3回:
  ① analyze : 読者像・悩み・検索意図・LP化の可否・画像の役割（画像を添付してAIに確認させる）
  ② write   : ジャンル別の構成でセールスコピーを生成（文体・見出しの型を商品ごとに変える）
  ③ review  : 捏造・誇張・AIっぽい定型文・誤字をAI自身に点検させて修正版を返させる
その後 quality.py でプログラムによる機械チェックを行う（AIのチェックだけに頼らない）。
"""

import json
import random
import re

import gemini

VOICES = [
    ("落ち着いた解説調", "専門店のスタッフが、要点を順序立てて丁寧に説明するような文体。"),
    ("生活者目線の語りかけ調", "同じ悩みを持つ友人に、実感を込めて話しかけるような柔らかい文体。ただし体験談の捏造はしない。"),
    ("要点先出しの簡潔調", "結論→理由→補足の順で、短い文を重ねるテンポのよい文体。"),
    ("比較検討を手伝う整理調", "買う前に迷っている人の判断材料を、観点ごとに整理して示す文体。"),
    ("暮らしの場面から入る描写調", "具体的な生活の一場面を描いてから商品の特徴に入る文体。"),
]

HEADING_STYLES = [
    "問いかけ型（例：〜で困っていませんか？）を中心に",
    "言い切り型の短い見出し（例：〜が気になる人へ）を中心に",
    "ベネフィット型（例：〜の手間を減らしたいなら）を中心に",
    "場面描写型（例：朝の支度が慌ただしい日に）を中心に",
]

FORBIDDEN_FOR_PROMPT = [
    "絶対", "必ず", "確実に", "100%", "買わないと損", "これ一択", "日本一", "No.1", "ナンバーワン", "ランキング1位",
    "おすすめの商品です", "いかがでしたでしょうか", "ぜひチェックしてください", "魅力的な商品です", "注目の商品です",
    "便利なアイテムです", "あなたの生活を豊かにします", "口コミで大絶賛", "医師も認める", "治る", "痩せる",
]

LAYOUT_GUIDE = {
    "beauty": "悩み → 共感 → 向いている人 → 検討する理由 → 特徴とそこから分かるメリット → 画像で確認 → 使う場面 → 商品情報 → 購入前の確認点 → 向いていない人 → FAQ",
    "health": "悩み → 向いている人 → 特徴 → 使う場面 → 画像で確認 → 商品情報 → 購入前の確認点（体調・用途の注意を含む） → 向いていない人 → FAQ",
    "appliance": "困りごと → 機能と特徴 → 使用シーン → 画像で確認 → スペック → 検討する理由 → 向いている人 → 購入前の確認点（サイズ・電源・設置） → 向いていない人 → FAQ",
    "baby": "子育ての困りごと → 使う場面 → 特徴 → 画像で確認 → 購入前の確認点（対象月齢・安全面は商品情報の範囲で） → 向いている人 → 商品情報 → 向いていない人 → FAQ",
    "food": "商品の特徴 → 食べる/飲むシーン → 画像で確認 → 向いている人 → 商品情報（内容量・保存方法は記載がある範囲） → 購入前の確認点 → FAQ",
    "interior": "使用シーン → 画像で確認 → デザインと特徴 → サイズ・仕様 → 向いている人 → 購入前の確認点 → 向いていない人 → FAQ",
    "living": "困りごと → 特徴 → 使う場面 → 画像で確認 → 向いている人 → 商品情報 → 購入前の確認点 → 向いていない人 → FAQ",
}


def _facts_block(p: dict) -> str:
    if p.get("keyword"):
        how = f"検索ジャンル: {p['category_label']}（検索キーワード: {p['keyword']}）\n"
    else:
        how = "選定方法: 楽天市場の売れ筋商品から選定（カテゴリはあなたが判定する）\n"
    return (
        f"商品名(楽天の登録名): {p['item_name']}\n"
        f"表示用の商品名(販促文言除去後): {p['display_name']}\n"
        f"ショップ名: {p.get('shop_name') or '不明'}\n"
        f"価格(取得時点): {p['price']}円\n"
        f"楽天市場のレビュー件数: {p['review_count']}件 / 平均評価: {p['review_average']}（取得時点の数値。レビュー本文は取得していない）\n"
        + how +
        f"商品説明(楽天の登録内容。事実として使ってよいのはここに書かれている内容だけ):\n"
        f"<<<\n{p['caption'][:2500]}\n>>>\n"
    )


# ---------------------------------------------------------------- ① analyze
def analyze(p: dict, image_parts: list, categories: list = ()) -> dict:
    n_img = len(p["image_urls"])
    seen = sum(1 for x in image_parts if x)
    prompt = f"""あなたはアフィリエイトサイトの編集長で、商品選定・読者分析・SEOの専門家です。
次の楽天市場の商品を、購入検討者向けの紹介ページ(LP)にする価値があるか分析してください。

{_facts_block(p)}
この商品の画像は {n_img} 枚あり、そのうち最初の {seen} 枚を添付しています（添付順に index 1,2,3...）。

【厳守】
- 事実は上の商品説明・商品名・数値から読み取れる範囲に限る。推測で成分・効果・スペック・受賞歴・ランキングを作らない。
- 商品名や説明にある「ランキング1位」「No.1」等はショップ側の主張であり当サイトでは確認できないので、事実として扱わない。
- 健康・美容・食品で効果効能を断定する表現は使わない。
- 画像の説明は、添付画像に実際に写っているものだけを書く。見えない画像は "use": true のままで caption は空文字にする。
- クーポン・セール・ポイント・ランキング・受賞・販売実績(累計○万台等)の告知が主な内容の画像は "use": false にする。
  商品が主に写っている画像は使ってよいが、caption と alt では画像内の販促文言・実績・ランキングに一切触れない。
- 「選べる」「選択可能」は、商品説明に購入者が選べると明記されている場合だけ facts に書く（「いずれか」はショップ側が決める可能性があるので、選べるとは書かない）。
- 対象の肌質・年齢・体質などは、商品説明に書かれている範囲を超えて広げない（「肌質を問わず」「敏感肌でも」等は書かない）。

以下のJSONのみを出力:
{{
  "suitable": true または false（誤解を招かずに購入判断を助けるLPを作れるか。情報不足・規制が強い・商品の実体が曖昧なら false）,
  "reject_reason": "false の場合の理由（true なら空文字）",
  "product_type": "商品の種類を表す短い名詞（例: 電気ケトル）",
  "category_slug": "この商品に最も合うカテゴリを次から1つ: {_cat_text(categories)}",
  "display_name": "ページに表示する自然な商品名（元の商品名に含まれる語だけで作る。販促文言・記号・ランキング主張を含めない。40字以内）",
  "facts": ["商品説明から確認できる事実を短文で。最大10個"],
  "spec_rows": [{{"label": "項目名(例: 容量)", "value": "値", "source_quote": "根拠になる商品説明中の文字列をそのまま抜き出す"}}],
  "unknowns": ["購入者が気にしそうだが、この情報からは確認できないこと。最大5個"],
  "personas": ["この商品を検討しそうな人物像を具体的に。商品情報から自然に導ける範囲で3つ"],
  "worries": ["その人たちが抱えていそうな悩み・困りごと 3〜4個"],
  "search_intents": ["この商品を検索する人が知りたいこと。例: 〇〇 使い方 / 〇〇 サイズ 3〜5個"],
  "keywords": ["関連キーワード 3〜6個（詰め込み用ではなく内容に合うもの）"],
  "related_needs": ["この商品を見た人が次に検討しそうな商品の種類 3〜5個（例: 洗顔料, 化粧水）"],
  "cautions": ["購入前に確認したい点 3〜5個（サイズ・対応機種・原材料・使用上の注意など、情報がある範囲で）"],
  "not_for": ["向いていない可能性がある人 2〜3個"],
  "risk_category": "none / cosmetics / health_food / supplement / medical_device / food / baby / electric のいずれか",
  "scores": {{"problem_solving": 0〜15の整数, "target_clarity": 0〜10の整数, "lp_fit": 0〜5の整数}},
  "images": [{{"index": 1, "use": true, "role": "main / overview / usage / detail / size / package / other", "alt": "画像の内容を説明する自然な代替テキスト(40字以内)", "caption": "この画像から分かること(画像に写っている範囲で40字以内。見ていない画像は空文字)"}}]
}}"""
    return gemini.call(prompt, images=image_parts, temperature=0.4, mock=lambda: _mock_analyze(p))


def _cat_text(categories):
    return " / ".join(f"{c['slug']}({c['label']})" for c in categories) or "指定なし"


# ---------------------------------------------------------------- ② write
def write(p: dict, a: dict, avoid_phrases: list, rng: random.Random) -> dict:
    voice_name, voice_desc = rng.choice(VOICES)
    heading_style = rng.choice(HEADING_STYLES)
    layout = p["layout"]
    avoid = "\n".join(f"- {x}" for x in avoid_phrases[:40]) or "- （なし）"
    prompt = f"""あなたはプロのセールスコピーライター兼SEOライターです。
以下の楽天市場の商品について、購入を「煽る」のではなく「自分に合うか判断できる」紹介ページの文章を書いてください。
ページの目的は、読者が楽天市場の商品ページで詳細や最新の販売情報を確認したくなることです。

{_facts_block(p)}
【編集部の分析】
{json.dumps({k: a.get(k) for k in ("product_type", "display_name", "facts", "unknowns", "personas", "worries", "search_intents", "keywords", "cautions", "not_for")}, ensure_ascii=False, indent=1)}

【このページの構成（{layout}型）】{LAYOUT_GUIDE.get(layout, LAYOUT_GUIDE['living'])}
【文体】{voice_name}：{voice_desc}
【見出しの作り方】{heading_style}。各見出しは商品固有の言葉を含め、他の商品ページと同じ見出しにならないようにする。

【絶対に守るルール】
1. 事実は上の商品説明・数値・編集部の分析の facts に書かれた範囲だけ。書かれていない成分・スペック・効果・受賞歴・ランキング・在庫状況・価格は書かない。
2. レビュー本文は取得していないので「口コミでは〜」「購入者の声」「大絶賛」「リピーター続出」など、レビューの内容に触れる表現は使わない。レビュー件数と平均評価の数値はページ側で自動表示するので本文では触れなくてよい。
3. 実際に使った体験談・使用感を創作しない（「使ってみたら〜」等は禁止）。「〜と記載されています」「〜な設計です」のように情報の出どころが分かる書き方にする。
4. 効果効能の断定をしない（治る・痩せる・改善する・効く・予防する 等）。健康・美容・食品は特に慎重に。
4-1. 健康食品・サプリ・子ども向け食品では「成長」「身長」「免疫」「代謝」「健康維持」など体への作用を連想させる語を使わない。化粧品では「シミ・シワが消える/改善」「肌の奥まで浸透」などを使わない。
4-2. 人気や実績を示す表現（選ばれている・定番・大人気・累計○台・公式ストア 等）は、当サイトで確認できないので使わない。
4-3. 「選べる」は商品説明に購入者が選べると明記されている場合だけ。「いずれか」と書かれているものは「〜のいずれかと記載されています」と書く。
5. 次の語句・定型文は使わない: {', '.join(FORBIDDEN_FOR_PROMPT)}
6. 価格の数字は本文に書かない（ページ側で取得日時点の価格を自動表示する）。
7. 同じ語尾や同じ言い回しを連続させない。「〜です。〜です。」の単調な繰り返しを避ける。
8. 最近ほかの商品ページで使った次の表現とは違う言い回しにする:
{avoid}

以下のJSONのみを出力:
{{
  "title": "検索結果に表示するタイトル（商品の種類と読者が知りたいことを含め、32字前後。煽らない）",
  "meta_description": "検索結果の説明文（90〜120字。誰のどんな悩みに、商品のどの特徴が関係するかを具体的に）",
  "h1": "ページの大見出し（商品名を含め40字以内）",
  "og_description": "SNSでシェアされたときの説明（60字前後）",
  "fv": {{"eyebrow": "ページ上部の小さなラベル(15字以内。例: 〇〇を探している人へ)", "catch": "キャッチコピー(30字以内)", "lead": "リード文(80〜120字)", "points": ["商品の要点を短く3つ(各25字以内)"]}},
  "headings": {{"worries": "", "for_whom": "", "reasons": "", "features": "", "scenes": "", "gallery": "", "specs": "", "checkpoints": "", "not_for": "", "faq": "", "final": ""}},
  "worries": {{"items": ["読者の悩み 3〜4個（読者の言葉で）"], "bridge": "悩みに共感し、商品の特徴へつなぐ2〜3文"}},
  "for_whom": ["この商品が向いている人 3〜5個（具体的に）"],
  "reasons": [{{"title": "検討する理由の見出し", "body": "説明 80〜140字"}}],
  "features": [{{"title": "特徴の見出し", "body": "商品説明にある特徴の説明 80〜150字", "merit": "その特徴から考えられる読者にとってのメリット 40〜80字（断定しない）"}}],
  "scenes": [{{"title": "使用シーンの見出し", "body": "具体的な場面 60〜120字"}}],
  "checkpoints": ["購入前に確認したいポイント 3〜5個（楽天の商品ページで何を確認すべきかを具体的に）"],
  "not_for": ["向いていない可能性がある人 2〜3個"],
  "faq": [{{"q": "検索意図に沿った質問", "a": "商品情報の範囲での回答。分からないことは『商品ページでご確認ください』と案内する"}}],
  "cta": {{"main": "ボタン文言(20字以内。例: 楽天市場で商品の詳細を見る)", "sub": "ボタン下の補足(40字以内)", "final_lead": "ページ最後の後押しの文章(煽らず、判断材料を確認する行動を促す 80〜120字)"}},
  "summary": "ページ全体のまとめ(2〜3文)"
}}
features は3〜4個、reasons は2〜3個、scenes は2〜3個、faq は3〜5個にしてください。"""
    content = gemini.call(prompt, temperature=0.9, mock=lambda: _mock_write(p, a))
    content["_voice"] = voice_name
    content["_heading_style"] = heading_style
    return content


# ---------------------------------------------------------------- ③ review
def review(p: dict, content: dict, issues: list) -> dict:
    issue_text = "\n".join(f"- {x}" for x in issues) or "- （機械チェックでの指摘はなし）"
    clean = {k: v for k, v in content.items() if not k.startswith("_")}
    prompt = f"""あなたは広告審査と校正の担当者です。以下は楽天市場の商品紹介ページの原稿(JSON)です。
商品情報と照らして点検し、問題を直した原稿を同じJSON構造で返してください。

{_facts_block(p)}
【点検項目】
1. 商品説明に書かれていない事実（成分・スペック・効果・受賞歴・ランキング・在庫・価格）を書いていないか → 削除または「商品ページでご確認ください」に置き換え
2. レビューや口コミの内容を創作していないか、体験談を創作していないか → 削除
3. 効果効能の断定・誇張・煽り（絶対/必ず/治る/痩せる/改善/No.1/買わないと損 等）がないか → 断定しない表現へ
4. AIっぽい定型文（おすすめの商品です/いかがでしたでしょうか/ぜひチェックしてください/魅力的な/注目の/便利なアイテム 等）→ 具体的な表現へ
5. 誤字脱字・不自然な日本語・同じ語尾の連続
6. 見出しが商品固有の内容になっているか

【機械チェックでの指摘】
{issue_text}

原稿:
{json.dumps(clean, ensure_ascii=False, indent=1)}

出力は次のJSONのみ:
{{"fixed": {{原稿と同じ構造で修正済みの全文}}, "changes": ["修正内容の要約"]}}"""
    res = gemini.call(prompt, temperature=0.3, mock=lambda: {"fixed": clean, "changes": []})
    fixed = res.get("fixed") if isinstance(res, dict) else None
    if not isinstance(fixed, dict) or "fv" not in fixed:
        return content
    for k, v in content.items():
        if k.startswith("_"):
            fixed[k] = v
    fixed["_review_changes"] = res.get("changes", [])
    return fixed


# ---------------------------------------------------------------- mocks（オフラインテスト用）
def _mock_analyze(p):
    name = p["display_name"]
    typ = p["keyword"].split()[-1] if p.get("keyword") else p["display_name"].split()[0]
    return {
        "suitable": True, "reject_reason": "", "product_type": typ, "display_name": name,
        "facts": [s for s in re.split(r"[。\n]", p["caption"]) if 8 < len(s) < 60][:6],
        "spec_rows": [], "unknowns": ["長期間使用したときの耐久性"],
        "personas": [f"{typ}を初めて選ぶ人", "毎日の手間を少し減らしたい人", "買い替えを検討している人"],
        "worries": [f"{typ}の選び方が分からない", "今使っているものに不満がある", "どれも同じに見えて決められない"],
        "search_intents": [f"{typ} 選び方", f"{name} 特徴"], "keywords": [typ, "選び方"],
        "related_needs": [typ], "cautions": ["サイズと容量を確認する"], "not_for": ["すでに満足している人"],
        "risk_category": "none", "scores": {"problem_solving": 11, "target_clarity": 8, "lp_fit": 4},
        "images": [{"index": i + 1, "use": True, "role": "main" if i == 0 else "detail", "alt": f"{name}の画像{i + 1}", "caption": ""} for i in range(len(p["image_urls"]))],
    }


def _mock_write(p, a):
    typ = a["product_type"]
    r = random.Random(p["item_name"])
    opener = r.choice(["毎日のことだから", "選択肢が多いほど", "買い替えを考えると", "初めて選ぶときは"])
    closer = r.choice(["確かめてから選ぶと安心です", "比べてから決めても遅くありません", "納得して選ぶのが近道です"])
    facts = a["facts"] or ["商品ページに詳しい仕様が記載されています"]
    return {
        "title": f"{typ}を選ぶ前に確認したいこと｜{p['display_name'][:14]}",
        "meta_description": f"{typ}選びで迷っている人向けに、{p['display_name'][:20]}の特徴・使う場面・購入前に確認したい点を商品情報をもとに整理しました。",
        "h1": f"{p['display_name'][:30]}の特徴と選ぶ前の確認ポイント",
        "og_description": f"{typ}の特徴と確認ポイントを整理しました。",
        "fv": {"eyebrow": f"{typ}を探している人へ", "catch": f"{opener}{typ}の判断材料を", "lead": f"{facts[0]}。そんな{typ}について、商品ページの記載をもとに特徴と確認ポイントをまとめました。", "points": [f[:24] for f in facts[:3]]},
        "headings": {"worries": f"{typ}でこんなことに迷っていませんか", "for_whom": f"{typ}を検討しやすい人", "reasons": f"{p['display_name'][:10]}を候補に入れる理由", "features": f"{typ}としての特徴", "scenes": f"{typ}を使う場面", "gallery": f"{p['display_name'][:10]}を画像で見る", "specs": f"{typ}の商品情報", "checkpoints": f"{typ}を買う前の確認点", "not_for": "合わない可能性がある人", "faq": f"{typ}のよくある質問", "final": "商品ページで詳細を確認する"},
        "worries": {"items": a["worries"], "bridge": f"{opener}、{typ}選びは迷いやすいもの。{p['display_name'][:12]}の記載内容から整理します。"},
        "for_whom": a["personas"],
        "reasons": [{"title": "情報が具体的", "body": "商品ページに仕様や使い方が記載されており、購入前に比較しやすい商品です。"}, {"title": "日常で使いやすい", "body": f"{typ}として毎日の場面を想定した設計と記載されています。"}],
        "features": [{"title": f[:18], "body": f + "と記載されています。", "merit": "日々の使い勝手を考えるうえでの判断材料になります。"} for f in facts[:3]],
        "scenes": [{"title": "毎日の習慣に", "body": f"{typ}を日常の決まった時間に使う場面を想定できます。"}, {"title": "買い替えのタイミングに", "body": "今使っているものを見直すきっかけにもなります。"}],
        "checkpoints": a["cautions"] + ["最新の価格と送料", "配送予定日"],
        "not_for": a["not_for"],
        "faq": [{"q": f"{typ}のサイズは？", "a": "サイズは商品ページでご確認ください。"}, {"q": "送料はかかりますか？", "a": "最新の送料は楽天市場の商品ページでご確認ください。"}, {"q": "どこで買えますか？", "a": "楽天市場の商品ページから購入できます。"}],
        "cta": {"main": "楽天市場で商品の詳細を見る", "sub": "価格・在庫・送料は商品ページで最新情報をご確認ください", "final_lead": f"{p['display_name'][:16]}が気になったら、仕様とサイズを{closer}。"},
        "summary": f"{p['display_name']}の特徴を整理しました。",
    }

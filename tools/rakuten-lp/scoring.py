"""商品のLP化優先度スコアリング。

一次スコア(プログラム・最大70点) + 二次スコア(AI・最大30点) = 100点。
レビュー数だけ・価格だけ・評価だけで決まらないよう、各指標を対数や上限で頭打ちにしている。

一次スコア内訳（実データ＝楽天TOP商品のレビュー数が数千〜数万に偏っている点を踏まえ調整）:
  商品情報の充実度 15 / レビュー量 15 / 評価 10 / 価格の訴求しやすさ 10 / 画像の充実度 10 / 説明文の具体性 10
二次スコア（AIが商品ごとに判定）:
  悩み解決性 15 / ターゲットの明確さ 10 / LP化適性 5
"""

import math
import re

from rakuten_api import image_urls

# 商品名に付いている販促用の文言（ショップ側の主張。当サイトでは確認できないので表示しない）
PROMO_PATTERNS = [
    r"【[^】]*】", r"\[[^\]]*\]", r"＼[^／]*／", r"≪[^≫]*≫", r"《[^》]*》", r"★[^★\s]*★?",
    r"楽天\s*\d*\s*位", r"ランキング\s*\d*\s*位?(獲得|受賞)?", r"\d+\s*冠", r"No\.?\s*1", r"ナンバーワン", r"日本一",
    r"最大\s*[\d,]+\s*円\s*OFF", r"[\d,]+\s*円\s*OFF", r"\d+\s*%\s*OFF", r"クーポン\S*", r"ポイント\s*\d+\s*倍",
    r"P\s*\d+\s*倍", r"\d+\s*%\s*ポイントバック", r"ポイントバック", r"スーパーDEAL", r"送料無料", r"あす楽",
    r"\d{1,2}/\d{1,2}\s*\d{1,2}時?(開始|まで|〜)?", r"\d{1,2}日まで", r"期間限定", r"本日限定", r"SALE", r"セール",
    r"おすすめ", r"人気", r"話題", r"終了前に", r"祝日営業", r"営業日", r"\d+\s*日到着可", r"到着可", r"[\d,]+\s*円\s*[⇒→]\s*[\d,]+\s*円", r"[⇒→]",
    r"最短\S*出荷", r"即納", r"当日発送", r"翌日配送", r"敬老の日", r"母の日", r"父の日", r"クリスマス", r"楽天スーパーセール", r"お買い物マラソン",
]
_PROMO_RE = re.compile("|".join(PROMO_PATTERNS), re.I)


def clean_name(name: str, max_len: int = 60) -> str:
    """表示用の商品名。販促文言・ランキング主張を取り除き、長すぎる場合は単語境界で切る。"""
    s = _PROMO_RE.sub(" ", name or "")
    s = re.sub(r"[!！♪☆◆◇■□●○※【】\[\]]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" 　・/|-")
    if len(s) <= max_len:
        return s
    cut = s[:max_len]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > max_len * 0.5 else cut).strip()


def primary_score(item: dict) -> dict:
    name = item.get("itemName") or ""
    caption = item.get("itemCaption") or ""
    reviews = int(item.get("reviewCount") or 0)
    avg = float(item.get("reviewAverage") or 0)
    price = int(item.get("itemPrice") or 0)
    imgs = image_urls(item)

    detail = {}
    # 商品情報の充実度（説明文の長さ・名前・ショップ情報）
    info = 0
    info += min(len(caption) / 400, 1.0) * 9
    info += 3 if len(clean_name(name)) >= 8 else 0
    info += 3 if item.get("shopName") else 0
    detail["info"] = round(info, 1)

    # レビュー量（対数。20件→約4、1000件→約11、20000件→15で頭打ち）
    detail["reviews"] = round(min(math.log10(reviews + 1) / math.log10(20000) * 15, 15), 1) if reviews else 0

    # 評価（件数が少ないときは3.5方向に補正＝少数の高評価を過大評価しない）
    k = 30
    adj = (avg * reviews + 3.5 * k) / (reviews + k) if reviews else 0
    detail["rating"] = round(max(0.0, min((adj - 3.5) / 1.2, 1.0)) * 10, 1)

    # 価格の訴求しやすさ（LPで検討してもらいやすい価格帯を中心に評価）
    if 1500 <= price <= 15000:
        p = 10
    elif 800 <= price < 1500 or 15000 < price <= 40000:
        p = 7
    elif 300 <= price < 800 or 40000 < price <= 100000:
        p = 4
    else:
        p = 1 if price > 0 else 0
    detail["price"] = p

    # 画像の充実度（APIが返す利用可能画像。最大3枚が一般的）
    detail["images"] = {0: 0, 1: 4, 2: 7}.get(len(imgs), 10)

    # 説明文の具体性（数字・仕様・使い方などが書かれているか）
    spec_hits = len(re.findall(r"\d+(\.\d+)?\s*(cm|mm|ml|mL|g|kg|W|mAh|L|枚|個|包|日分|回|時間|分)", caption))
    usage_hits = sum(1 for w in ("使い方", "サイズ", "素材", "原材料", "成分", "容量", "仕様", "内容量", "対象", "お手入れ", "保証") if w in caption)
    detail["specificity"] = round(min(spec_hits * 1.2 + usage_hits * 1.5, 10), 1)

    total = round(sum(detail.values()), 1)
    return {"primary": total, "detail": detail, "image_count": len(imgs)}


def final_score(primary: float, ai: dict) -> float:
    ai_part = (
        min(max(float(ai.get("problem_solving", 0)), 0), 15)
        + min(max(float(ai.get("target_clarity", 0)), 0), 10)
        + min(max(float(ai.get("lp_fit", 0)), 0), 5)
    )
    return round(primary + ai_part, 1)


def passes_basic_filter(item: dict, config: dict, check_caption: bool = True) -> tuple:
    """LP化の最低条件。満たさない場合は (False, 理由)。"""
    if not item.get("affiliateUrl"):
        return False, "affiliateUrlなし"
    if not item.get("itemCode"):
        return False, "itemCodeなし"
    if int(item.get("reviewCount") or 0) < config["min_review_count"]:
        return False, "レビュー件数が少ない"
    if float(item.get("reviewAverage") or 0) < config["min_review_average"]:
        return False, "レビュー評価が基準未満"
    if check_caption and len(item.get("itemCaption") or "") < 60:
        return False, "商品説明が短すぎる（LPの根拠にできる情報が不足）"
    if not image_urls(item):
        return False, "利用可能な商品画像なし"
    name = item.get("itemName") or ""
    if re.search(r"訳あり|福袋|中古|アウトレット|お試し\s*\d+円|1円", name):
        return False, "LP化に不向きな商品種別（訳あり/福袋/中古等）"
    if re.search(r"医薬品|処方|コンタクトレンズ|たばこ|電子タバコ|アダルト|成人向け|ビール|ワイン|日本酒|焼酎|ウイスキー|ハイボール|チューハイ|サワー缶|酎ハイ|リキュール|お酒|ギフト券|商品券|チケット|ふるさと納税", name):
        return False, "広告表現の規制が強い/対象外カテゴリ"
    return True, ""


def rank_with_image_priority(cands: list, window: float = 3.0) -> list:
    """スコアが近い(window点以内)商品同士では、画像が多い方を優先する並び替え。
    画像枚数だけで品質を大きく損なわないよう、差が window 点を超える場合はスコアを優先。"""
    per_image = window / 3.0
    return sorted(cands, key=lambda c: c["score_for_rank"] + min(c["image_count"], 3) * per_image, reverse=True)


def trend_bonus(rank, source: dict) -> float:
    """ランキング順位による「売れ筋・流行」加点（並び順にだけ使う。LP上にはランキングを表示しない）。"""
    try:
        rank = int(rank)
    except (TypeError, ValueError):
        return 0.0
    bonus = 6 if rank <= 30 else 4 if rank <= 100 else 2 if rank <= 300 else 1
    if source.get("period") == "realtime":
        bonus += 1
    return float(bonus)

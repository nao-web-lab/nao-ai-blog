"""楽天市場 商品検索API の呼び出し（rakuten-threads-auto/rakuten_product_research.py と同じAPI・同じ認証方式を再利用）。

- 認証情報は環境変数 RAKUTEN_APPLICATION_ID / RAKUTEN_ACCESS_KEY / RAKUTEN_AFFILIATE_ID
- 楽天側で「許可IPアドレス」を設定しているため、自宅PCから実行する前提
- エラー時は例外を投げる（呼び出し側で1キーワード単位でスキップし、全体は止めない）
- モード RAKUTEN_LP_MOCK=1 のときは fixtures/mock_items.json を返す（オフラインテスト用）
"""

import os
import time

import requests

from common import TOOL_DIR, read_json, redact

API_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
RANKING_URL = "https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601"

_last_call = 0.0


class RakutenAPIError(Exception):
    pass


def _mock_items(keyword):
    data = read_json(TOOL_DIR / "fixtures" / "mock_items.json", {})
    return data.get(keyword, [])


def _auth():
    app_id = os.getenv("RAKUTEN_APPLICATION_ID")
    access_key = os.getenv("RAKUTEN_ACCESS_KEY")
    aff_id = os.getenv("RAKUTEN_AFFILIATE_ID")
    if not (app_id and access_key and aff_id):
        raise RakutenAPIError("楽天APIの認証情報(環境変数)が設定されていません")
    return {"applicationId": app_id, "accessKey": access_key, "affiliateId": aff_id, "format": "json", "formatVersion": 2}


def _get(url: str, params: dict, interval: float) -> list:
    global _last_call
    last_err = None
    for attempt in range(3):
        wait = interval - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        try:
            resp = requests.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            last_err = f"通信エラー: {type(e).__name__}"
            time.sleep(3 * (attempt + 1))
            continue
        if resp.status_code == 200:
            body = resp.json()
            items = body.get("Items", body.get("items", []))
            return [it.get("Item", it) if isinstance(it, dict) else it for it in items]
        if resp.status_code == 404:
            return []  # 該当なし（ページ範囲外など）
        if resp.status_code in (429, 500, 502, 503):
            last_err = f"HTTP {resp.status_code}"
            time.sleep(5 * (attempt + 1))
            continue
        raise RakutenAPIError(redact(f"HTTP {resp.status_code}: {resp.text[:300]}"))
    raise RakutenAPIError(redact(last_err or "不明なエラー"))


def search(keyword: str, page: int = 1, hits: int = 30, interval: float = 1.2, sort: str = "-reviewCount") -> list:
    """キーワード検索して商品(dict)のリストを返す。"""
    if os.getenv("RAKUTEN_LP_MOCK") == "1":
        return _mock_items(keyword) if page == 1 else []
    params = {**_auth(), "keyword": keyword, "hits": hits, "page": page, "sort": sort,
              "imageFlag": 1, "availability": 1}
    return _get(API_URL, params, interval)


def ranking(page: int = 1, interval: float = 1.2, period: str = None, age: int = None, sex: int = None, genre_id: int = None) -> list:
    """楽天市場ランキングAPI（ジャンル指定なし＝総合）。売れ筋・流行の商品を取得する。
    period="realtime" でリアルタイム（流行）、未指定でデイリー。age/sex で年代・性別別ランキング。"""
    if os.getenv("RAKUTEN_LP_MOCK") == "1":
        data = read_json(TOOL_DIR / "fixtures" / "mock_items.json", {})
        seen, out = set(), []
        for items in data.values():
            for it in items:
                if it["itemCode"] not in seen:
                    seen.add(it["itemCode"])
                    out.append(dict(it, rank=len(out) + 1))
        return out if page == 1 else []
    params = {**_auth(), "page": page}
    if period:
        params["period"] = period
    if genre_id:
        params["genreId"] = genre_id
    else:
        if age:
            params["age"] = age
        if sex is not None:
            params["sex"] = sex
    return _get(RANKING_URL, params, interval)


def lookup(item_code: str, interval: float = 1.2) -> dict:
    """商品コードで商品検索APIを引き、商品説明など詳細を補う（ランキングAPIに無い項目の補完用）。"""
    if os.getenv("RAKUTEN_LP_MOCK") == "1":
        return {}
    items = _get(API_URL, {**_auth(), "itemCode": item_code, "hits": 1}, interval)
    return items[0] if items else {}


def image_urls(item: dict) -> list:
    """APIが返した商品画像URLを重複なしで返す（楽天が提供する画像のみ。スクレイピングはしない）。"""
    urls = []
    for key in ("mediumImageUrls", "smallImageUrls"):
        for v in item.get(key) or []:
            u = v.get("imageUrl") if isinstance(v, dict) else v
            if not u:
                continue
            base = u.split("?")[0]
            if base not in [x.split("?")[0] for x in urls]:
                urls.append(u)
    return urls

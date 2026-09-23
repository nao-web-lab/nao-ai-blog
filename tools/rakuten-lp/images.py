"""商品画像の扱い。

ルール（楽天アフィリエイトの画像利用ルールに沿う）:
- 使うのは楽天APIが返した商品画像URLのみ。商品ページのスクレイピング・スクリーンショットはしない
- 画像ファイルは保存・再配布しない（楽天の画像サーバーのURLをそのまま表示する）
- 画像そのものへの文字入れ・合成・トリミングはしない。変えるのは楽天画像サーバーの
  表示サイズ指定(_ex=幅x高さ、縦横比を保った縮小/拡大)だけ。枠・影・余白はCSSで外側に付ける
- 画像は必ずアフィリエイトリンクと一緒に掲載する（LP内で画像をアフィリエイトリンクで包む）
"""

import base64
import os
import re
import time
from urllib.parse import urlparse

import requests

ALLOWED_HOSTS = ("thumbnail.image.rakuten.co.jp", "image.rakuten.co.jp", "tshop.r10s.jp", "shop.r10s.jp")


def is_allowed(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    return u.scheme == "https" and u.netloc in ALLOWED_HOSTS


def sized(url: str, size: str) -> str:
    """楽天画像サーバーの表示サイズ指定だけ変更する（画像の中身は加工しない）。"""
    base = url.split("?")[0]
    if "thumbnail.image.rakuten.co.jp" in base:
        return f"{base}?_ex={size}"
    return url


class ImageCheckError(Exception):
    """画像サーバーに一時的に接続できなかった（商品の問題ではないので、後日再試行する）。"""


def _check_one(url: str, timeout: int) -> str:
    """'ok' / 'missing'(画像が存在しない) / 'error'(一時的な失敗) を返す。"""
    target = sized(url, "600x600")
    for attempt in range(2):
        try:
            r = requests.head(target, timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/"):
                return "ok"
            # HEADに対応していない・Content-Typeを返さない場合があるのでGETでも確認（先頭だけ読む）
            r = requests.get(target, timeout=timeout, stream=True)
            ctype = r.headers.get("Content-Type", "")
            r.close()
            if r.status_code == 200 and ctype.startswith("image/"):
                return "ok"
            if r.status_code in (404, 410):
                return "missing"
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    return "error"


def verify(urls: list, timeout: int = 10) -> list:
    """実際に表示できる画像URLだけ残す。全部が一時的な失敗なら ImageCheckError。"""
    if os.getenv("RAKUTEN_LP_MOCK") == "1":
        return [u for u in urls if is_allowed(u)]
    ok, errors = [], 0
    for u in urls:
        if not is_allowed(u):
            continue
        res = _check_one(u, timeout)
        if res == "ok":
            ok.append(u)
        elif res == "error":
            errors += 1
        time.sleep(0.3)
    if not ok and errors:
        raise ImageCheckError(f"画像サーバーに接続できませんでした（{errors}件）")
    return ok


def fetch_for_analysis(urls: list, size: str = "400x400", limit: int = 3) -> list:
    """AIに画像の内容を確認させるため、一時的にメモリ上で取得する（保存しない）。"""
    if os.getenv("RAKUTEN_LP_MOCK") == "1":
        return []
    parts = []
    for u in urls[:limit]:
        try:
            r = requests.get(sized(u, size), timeout=15)
            ctype = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
            if r.status_code == 200 and ctype.startswith("image/") and len(r.content) < 3_000_000:
                parts.append({"mime_type": ctype, "data": base64.b64encode(r.content).decode("ascii")})
            else:
                parts.append(None)
        except requests.RequestException:
            parts.append(None)
    return parts


def build_image_plan(urls: list, ai_images: list, max_images: int, product_name: str) -> list:
    """AIの判定(ai_images: index/role/alt/caption/use)を元に、LPで使う画像と役割を決める。

    AIが画像を見られなかった場合は、画像の中身に触れない中立的なalt・キャプションにする
    （画像から確認できない情報を書かない）。"""
    by_index = {}
    for a in ai_images or []:
        try:
            idx = int(a.get("index"))
        except (TypeError, ValueError):
            continue
        by_index[idx] = a

    plan = []
    for i, u in enumerate(urls):
        a = by_index.get(i + 1)
        if a is not None and a.get("use") is False:
            continue  # AIが「LPに不要/不適切」と判定した画像
        alt = (a or {}).get("alt") or f"{product_name}の商品画像（{i + 1}枚目）"
        caption = (a or {}).get("caption") or ""
        role = (a or {}).get("role") or ("main" if i == 0 else "detail")
        alt = re.sub(r"\s+", " ", alt)[:80]
        plan.append({"url": u, "role": role, "alt": alt, "caption": caption, "seen_by_ai": a is not None})
        if len(plan) >= max_images:
            break
    if plan and plan[0]["role"] != "main":
        plan[0]["role"] = "main"
    return plan

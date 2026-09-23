"""Gemini API 呼び出し（rakuten-threads-auto/gemini_client.py の設計を再利用）。

違い:
- 失敗時に SystemExit ではなく GeminiError を投げる（1商品の失敗で全体を止めないため）
- 画像(inline_data)を添付できる（AIに商品画像の内容を確認させ、画像の選定・alt・説明文に使う）
- 呼び出し間隔と1回の実行あたりの上限回数を守る（無料枠のレート制限対策）
"""

import json
import os
import re
import time

import requests

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


class GeminiError(Exception):
    pass


class GeminiQuotaExceeded(GeminiError):
    """1回の実行で使える呼び出し回数を使い切った / 日次上限に達した。"""


_state = {"calls": 0, "last": 0.0, "interval": 7.0, "max_calls": 120}


def configure(interval: float, max_calls: int) -> None:
    _state["interval"] = interval
    _state["max_calls"] = max_calls


def calls_used() -> int:
    return _state["calls"]


def _url(model):
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def call(prompt: str, images: list = None, temperature: float = 0.8, mock=None) -> dict:
    """プロンプト(+画像)を送り、JSONをdictで返す。"""
    if os.getenv("RAKUTEN_LP_MOCK") == "1":
        if mock is None:
            raise GeminiError("モックが指定されていません")
        _state["calls"] += 1
        return mock()

    # LP専用のキー(GEMINI_API_KEY_LP)があればそちらを使う（Threads自動投稿の無料枠を食い合わないため）
    key = os.getenv("GEMINI_API_KEY_LP") or os.getenv("GEMINI_API_KEY")
    if not key:
        raise GeminiError("GEMINI_API_KEY が設定されていません")
    if _state["calls"] >= _state["max_calls"]:
        raise GeminiQuotaExceeded("今回の実行で使えるGemini呼び出し回数の上限に達しました")

    parts = [{"text": prompt}]
    for img in images or []:
        if img:
            parts.append({"inline_data": img})
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
    }

    models = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]
    last_error = ""
    quota_hits = 0
    for model in models:
        wait = 5
        for attempt in range(3):
            gap = _state["interval"] - (time.time() - _state["last"])
            if gap > 0:
                time.sleep(gap)
            _state["last"] = time.time()
            try:
                r = requests.post(_url(model), params={"key": key}, json=payload, timeout=120)
            except requests.RequestException as e:
                last_error = f"通信エラー: {type(e).__name__}"
                time.sleep(wait)
                wait = min(wait * 2, 60)
                continue
            if r.status_code == 200:
                try:
                    body = r.json()
                    text = body["candidates"][0]["content"]["parts"][0]["text"]
                    result = json.loads(text)
                    _state["calls"] += 1  # 成功した呼び出しだけ数える
                    return result
                except (KeyError, IndexError, ValueError) as e:
                    last_error = f"応答の解析に失敗: {type(e).__name__}"
                    print(f"    Gemini [{model}] {last_error} → 再試行", flush=True)
                    continue
            last_error = f"[{model}] HTTP {r.status_code}"
            print(f"    Gemini {last_error} → 待機して再試行", flush=True)
            if r.status_code == 429:
                quota_hits += 1
                if "PerDay" in r.text or "per day" in r.text.lower():
                    break  # このモデルの日次上限。次のモデルへ
            if r.status_code in (429, 500, 503):
                # Geminiが「何秒後に再試行してよいか」を返している場合はそれに従う（無駄な再試行を減らす）
                m = re.search(r'"retryDelay"\s*:\s*"(\d+)', r.text)
                delay = min(int(m.group(1)) + 1, 90) if m else wait
                time.sleep(delay)
                wait = min(wait * 2, 60)
                continue
            raise GeminiError(last_error)
    if quota_hits >= len(models):
        raise GeminiQuotaExceeded("Geminiの利用上限に達しました（翌日に持ち越し）")
    raise GeminiError(f"Gemini呼び出しに失敗しました: {last_error}")

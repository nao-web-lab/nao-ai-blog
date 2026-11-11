#!/usr/bin/env python3
"""Search Console の数字を自動で集めて、週1回まとめる（このPC専用）。

集めるもの
- 検索パフォーマンス（表示回数・クリック数・CTR・平均掲載順位）… 直近7日と、その前の7日
- 検索語句・ページの上位
- サイトマップのステータス
- 登録状況の抜き取り検査（URL検査API。1日 inspect_per_day 本ずつ、未検査・古い順に回る）

保存先は logs/gsc/（git管理外・公開しない）。週1回 LINE に短いまとめを送る。
詳しいまとめは logs/gsc/report-日付.md。分析を頼むときは、その中身をClaudeに貼る。

鍵（サービスアカウントのJSONファイル）は git管理外の場所に置き、パスだけを config.json の gsc.key_file に書く。
鍵の中身はログにも画面にも出さない。

使い方（PowerShell）:
  python tools\\rakuten-lp\\gsc_report.py --check     # 設定の確認（つながるか・権限があるか）
  python tools\\rakuten-lp\\gsc_report.py --weekly    # 今すぐ週次まとめを作る
  python tools\\rakuten-lp\\gsc_report.py --inspect 20 # 登録状況を20本だけ検査
毎日の実行（run_daily.py）の最後にも自動で呼ばれる（失敗してもLP作成には影響しない）。
"""

import argparse
import base64
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

from common import DB_PATH, LOG_DIR, REPO_ROOT, TOOL_DIR, load_config, log, now_jst, read_json, today_str, write_json

GSC_DIR = LOG_DIR / "gsc"
STATE_PATH = GSC_DIR / "state.json"
INSPECT_PATH = GSC_DIR / "inspection.json"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
API = "https://searchconsole.googleapis.com"
RECHECK_DAYS = 14
TIMEOUT = 30


class GscError(Exception):
    pass


# ---------------------------------------------------------------- 設定・認証
def gsc_config(config: dict) -> dict:
    g = {"enabled": True, "site_url": config["site_base_url"].rstrip("/") + "/",
         "key_file": "../../../rakuten-threads-auto/local/env/gsc-service-account.json",
         "inspect_per_day": 100, "report_weekday": 0}
    g.update(config.get("gsc") or {})
    return g


def key_path(g: dict) -> Path:
    p = Path(g["key_file"])
    return p if p.is_absolute() else (TOOL_DIR / p).resolve()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _sign_rs256(private_key_pem: str, message: bytes) -> bytes:
    """google-auth が無くても動くよう、cryptography で署名する（どちらも無ければ案内を出す）。"""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as e:
        raise GscError("署名用のライブラリがありません。PowerShellで `pip install cryptography` を実行してください") from e
    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    return key.sign(message, padding.PKCS1v15(), hashes.SHA256())


def access_token(g: dict) -> str:
    path = key_path(g)
    try:  # 鍵をリポジトリの中に置くと GitHub に公開されてしまうので、使わずに止める
        path.relative_to(REPO_ROOT)
        raise GscError("鍵ファイルがリポジトリ（nao-ai-blog）の中にあります。GitHubに公開されないよう、リポジトリの外（rakuten-threads-auto\\local\\env）へ移してください")
    except ValueError:
        pass
    if not path.exists():
        raise GscError(f"鍵ファイルが見つかりません: {path.name}（config.json の gsc.key_file の場所に置いてください）")
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        email, pem = info["client_email"], info["private_key"]
        token_uri = info.get("token_uri") or "https://oauth2.googleapis.com/token"
    except (json.JSONDecodeError, KeyError) as e:
        raise GscError("鍵ファイルの形式が正しくありません（サービスアカウントの「JSON」形式の鍵を使ってください）") from e
    now = int(time.time())
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64(json.dumps({"iss": email, "scope": SCOPE, "aud": token_uri, "iat": now, "exp": now + 3600}).encode())
    signing_input = f"{header}.{claims}".encode()
    assertion = f"{header}.{claims}.{_b64(_sign_rs256(pem, signing_input))}"
    r = requests.post(token_uri, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}, timeout=TIMEOUT)
    if r.status_code != 200:
        raise GscError(f"Googleの認証に失敗しました（{r.status_code}）。鍵ファイルが正しいか、Search Console APIが有効か確認してください")
    return r.json()["access_token"]


class Client:
    def __init__(self, g: dict, token: str):
        self.site = g["site_url"]
        self.h = {"Authorization": f"Bearer {token}"}

    def _req(self, method, url, body=None):
        for attempt in range(3):
            r = requests.request(method, url, headers=self.h, json=body, timeout=TIMEOUT)
            if r.status_code in (429, 500, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 403:
                raise GscError("Search Console の権限がありません。「設定 → ユーザーと権限」にサービスアカウントを追加してください")
            if r.status_code >= 400:
                msg = ""
                try:
                    msg = r.json().get("error", {}).get("message", "")[:150]
                except ValueError:
                    pass
                raise GscError(f"Search Console APIエラー（{r.status_code}）{msg}")
            return r.json()
        return {}

    def analytics(self, start, end, dims=(), limit=1000):
        body = {"startDate": start, "endDate": end, "dimensions": list(dims), "rowLimit": limit, "type": "web"}
        return self._req("POST", f"{API}/webmasters/v3/sites/{quote(self.site, safe='')}/searchAnalytics/query", body).get("rows", [])

    def sitemaps(self):
        return self._req("GET", f"{API}/webmasters/v3/sites/{quote(self.site, safe='')}/sitemaps").get("sitemap", [])

    def inspect(self, url):
        body = {"inspectionUrl": url, "siteUrl": self.site, "languageCode": "ja"}
        res = self._req("POST", f"{API}/v1/urlInspection/index:inspect", body)
        s = (res.get("inspectionResult") or {}).get("indexStatusResult") or {}
        return {"verdict": s.get("verdict", ""), "coverage": s.get("coverageState", ""), "last_crawl": (s.get("lastCrawlTime") or "")[:10],
                "fetch": s.get("pageFetchState", ""), "robots": s.get("robotsTxtState", ""), "indexing": s.get("indexingState", "")}


# ---------------------------------------------------------------- 分類
def page_type(url: str) -> str:
    path = urlparse(url).path
    if "/products/guide/" in path:
        return "比較ガイド"
    m = re.search(r"/products/([^/]+)/([^/]+)/$", path)
    if m:
        return "商品LP"
    if "/products/" in path:
        return "商品一覧"
    if "/guide/" in path:
        return "解説ガイド"
    if "/lp/" in path:
        return "旧LP"
    return "トップ・その他"


def lp_types() -> dict:
    """商品LPのURL → 商品の種類（DBの product_type）"""
    db = read_json(DB_PATH, {})
    return {r.get("lp_url", ""): r.get("product_type") or "不明"
            for r in (db.get("products") or {}).values() if r.get("status") == "published"}


def sitemap_urls() -> list:
    xml = (REPO_ROOT / "sitemap.xml").read_text(encoding="utf-8")
    return re.findall(r"<url><loc>([^<]+)</loc>(?:<lastmod>([^<]+)</lastmod>)?</url>", xml)


# ---------------------------------------------------------------- 登録状況の抜き取り検査
TYPE_ORDER = {"トップ・その他": 0, "解説ガイド": 1, "比較ガイド": 2, "商品一覧": 3, "商品LP": 4, "旧LP": 5}


def pick_for_inspection(n: int) -> list:
    """未検査のページを優先（大事な種類から・商品LPは新しい順）。その後、検査から日がたったページ。"""
    done = read_json(INSPECT_PATH, {})
    today = now_jst().date()
    fresh, stale = [], []
    for u, lastmod in sitemap_urls():
        rec = done.get(u)
        if not rec:
            fresh.append((TYPE_ORDER.get(page_type(u), 9), "".join(chr(0x10FFFF - ord(ch)) for ch in (lastmod or "")), u))
            continue
        try:
            age = (today - now_jst().fromisoformat(rec["checked"]).date()).days
        except (KeyError, ValueError):
            age = 999
        due = RECHECK_DAYS if rec.get("verdict") == "PASS" else 7  # 未登録のページは早めに再検査
        if age >= due:
            stale.append((rec.get("checked", ""), u))
    return ([u for _, _, u in sorted(fresh)] + [u for _, u in sorted(stale)])[:n]


def run_inspection(client: Client, n: int) -> int:
    done = read_json(INSPECT_PATH, {})
    targets = pick_for_inspection(n)
    count = 0
    for u in targets:
        try:
            res = client.inspect(u)
        except GscError as e:
            log(f"  登録状況の検査を中断: {e}")
            break
        done[u] = {**res, "checked": today_str()}
        count += 1
        time.sleep(0.3)
    write_json(INSPECT_PATH, done)
    return count


def index_summary() -> dict:
    done = read_json(INSPECT_PATH, {})
    in_sitemap = {u for u, _ in sitemap_urls()}
    types = lp_types()
    by_type = defaultdict(Counter)
    reasons = Counter()
    by_ptype = defaultdict(Counter)
    for u, r in done.items():
        if u not in in_sitemap:
            continue
        ok = r.get("verdict") == "PASS"
        t = page_type(u)
        by_type[t]["登録済み" if ok else "未登録"] += 1
        if not ok:
            reasons[r.get("coverage") or "不明"] += 1
        if t == "商品LP":
            by_ptype[types.get(u, "不明")]["登録済み" if ok else "未登録"] += 1
    weak = sorted(((k, v["未登録"], v["登録済み"] + v["未登録"]) for k, v in by_ptype.items() if v["登録済み"] + v["未登録"] >= 3),
                  key=lambda t: (-t[1] / t[2], -t[2]))[:5]
    total_checked = sum(sum(c.values()) for c in by_type.values())
    return {"checked": total_checked, "in_sitemap": len(in_sitemap), "by_type": {k: dict(v) for k, v in by_type.items()},
            "reasons": reasons.most_common(5), "weak_product_types": weak}


# ---------------------------------------------------------------- 週次まとめ
def _sum(rows):
    c = sum(r.get("clicks", 0) for r in rows)
    i = sum(r.get("impressions", 0) for r in rows)
    pos = (sum(r.get("position", 0) * r.get("impressions", 0) for r in rows) / i) if i else 0
    return {"clicks": int(c), "impressions": int(i), "ctr": (c / i if i else 0), "position": pos}


def _pct(now, prev):
    if not prev:
        return "（前週 0）" if now else ""
    return f"（前週比 {(now - prev) / prev * 100:+.0f}%）"


def weekly_report(client: Client, g: dict) -> dict:
    end = now_jst().date() - timedelta(days=3)  # 検索データは2〜3日遅れて確定する
    start = end - timedelta(days=6)
    pend, pstart = start - timedelta(days=1), start - timedelta(days=7)
    f = lambda d: d.isoformat()
    cur_total = _sum(client.analytics(f(start), f(end)))
    prev_total = _sum(client.analytics(f(pstart), f(pend)))
    pages = client.analytics(f(start), f(end), ("page",), 1000)
    queries = client.analytics(f(start), f(end), ("query",), 25)
    by_type = defaultdict(list)
    for r in pages:
        by_type[page_type(r["keys"][0])].append(r)
    sm = []
    for s in client.sitemaps():
        contents = s.get("contents") or [{}]
        sm.append({"path": s.get("path", ""), "last_downloaded": (s.get("lastDownloaded") or "")[:10],
                   "pending": s.get("isPending", False), "errors": int(s.get("errors", 0) or 0), "warnings": int(s.get("warnings", 0) or 0),
                   "submitted": int(contents[0].get("submitted", 0) or 0)})
    return {
        "made_at": now_jst().isoformat(timespec="seconds"), "period": [f(start), f(end)], "prev_period": [f(pstart), f(pend)],
        "total": cur_total, "prev_total": prev_total,
        "by_page_type": {k: _sum(v) for k, v in sorted(by_type.items())},
        "top_pages": [{"url": r["keys"][0], "clicks": r["clicks"], "impressions": r["impressions"], "position": round(r["position"], 1)}
                      for r in sorted(pages, key=lambda r: -r["impressions"])[:15]],
        "top_queries": [{"query": r["keys"][0], "clicks": r["clicks"], "impressions": r["impressions"], "position": round(r["position"], 1)}
                        for r in queries[:20]],
        "sitemaps": sm, "index": index_summary(),
    }


def short_text(rep: dict) -> str:
    t, p = rep["total"], rep["prev_total"]
    lines = [f"📊 Search Console 週次（{rep['period'][0][5:]}〜{rep['period'][1][5:]}）",
             f"表示 {t['impressions']:,}回{_pct(t['impressions'], p['impressions'])}",
             f"クリック {t['clicks']:,}回{_pct(t['clicks'], p['clicks'])}／平均順位 {t['position']:.1f}"]
    for s in rep["sitemaps"][:1]:
        st = "処理待ち" if s["pending"] else ("エラーあり" if s["errors"] else "取得済み")
        lines.append(f"サイトマップ: {st}（最終取得 {s['last_downloaded'] or '未取得'}）")
    ix = rep["index"]
    if ix["checked"]:
        ok = sum(v.get("登録済み", 0) for v in ix["by_type"].values())
        lines.append(f"登録状況（検査済み{ix['checked']}/{ix['in_sitemap']}本）: 登録済み {ok}本・未登録 {ix['checked'] - ok}本")
    if rep["top_queries"]:
        lines.append("検索語句: " + "、".join(q["query"] for q in rep["top_queries"][:3]))
    lines.append("詳細は logs\\gsc\\ の最新 report-*.md")
    return "\n".join(lines)


def markdown(rep: dict) -> str:
    t, p = rep["total"], rep["prev_total"]
    out = [f"# Search Console 週次まとめ（{rep['period'][0]}〜{rep['period'][1]}）", "",
           "> この内容をそのまま Claude に貼ると、分析と次の改善案を出せます。", "",
           "## 全体", "| 指標 | 今週 | 前週 |", "|---|---|---|",
           f"| 表示回数 | {t['impressions']:,} | {p['impressions']:,} |",
           f"| クリック数 | {t['clicks']:,} | {p['clicks']:,} |",
           f"| クリック率 | {t['ctr'] * 100:.2f}% | {p['ctr'] * 100:.2f}% |",
           f"| 平均掲載順位 | {t['position']:.1f} | {p['position']:.1f} |", "",
           "## ページの種類別（今週）", "| 種類 | 表示 | クリック | 平均順位 |", "|---|---|---|---|"]
    for k, v in rep["by_page_type"].items():
        out.append(f"| {k} | {v['impressions']:,} | {v['clicks']:,} | {v['position']:.1f} |")
    out += ["", "## 表示回数の多いページ", "| ページ | 表示 | クリック | 順位 |", "|---|---|---|---|"]
    for r in rep["top_pages"]:
        out.append(f"| {urlparse(r['url']).path} | {r['impressions']:,} | {r['clicks']:,} | {r['position']} |")
    out += ["", "## 検索語句", "| 語句 | 表示 | クリック | 順位 |", "|---|---|---|---|"]
    for r in rep["top_queries"]:
        out.append(f"| {r['query']} | {r['impressions']:,} | {r['clicks']:,} | {r['position']} |")
    out += ["", "## サイトマップ"]
    for s in rep["sitemaps"]:
        out.append(f"- {s['path']}: 最終取得 {s['last_downloaded'] or '未取得'} / 処理待ち {s['pending']} / エラー {s['errors']} / 警告 {s['warnings']} / 送信URL {s['submitted']}")
    ix = rep["index"]
    out += ["", f"## 登録状況（URL検査で抜き取り。検査済み {ix['checked']} / サイトマップ {ix['in_sitemap']} 本）",
            "| 種類 | 登録済み | 未登録 |", "|---|---|---|"]
    for k, v in sorted(ix["by_type"].items()):
        out.append(f"| {k} | {v.get('登録済み', 0)} | {v.get('未登録', 0)} |")
    if ix["reasons"]:
        out += ["", "未登録の理由（Googleの表示）:"] + [f"- {k}: {n}本" for k, n in ix["reasons"]]
    if ix["weak_product_types"]:
        out += ["", "未登録の割合が高い商品の種類（3本以上検査したもの）:"] + [f"- {k}: {u}/{n}本が未登録" for k, u, n in ix["weak_product_types"]]
    out += ["", "※ 検索データは2〜3日遅れて確定するため、期間の終わりは3日前です。登録状況は毎日少しずつ検査しているため、全ページの数ではありません。"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- 毎日の実行から呼ぶ入口
def daily_step(config: dict, notify=None, force_weekly: bool = False) -> str:
    """毎日の実行の最後に呼ぶ。未設定なら何もしない。失敗は例外にせずログに残す。戻り値は状況の短い文。"""
    g = gsc_config(config)
    if not g.get("enabled", True):
        return "Search Console: 無効"
    if not key_path(g).exists():
        log("Search Console: 未設定（鍵ファイルなし）のためスキップ")
        return "Search Console: 未設定"
    try:
        client = Client(g, access_token(g))
        n = run_inspection(client, int(g.get("inspect_per_day", 100)))
        log(f"Search Console: 登録状況を{n}本検査")
        state = read_json(STATE_PATH, {})
        due = now_jst().weekday() == int(g.get("report_weekday", 0)) and state.get("last_weekly") != today_str()
        if force_weekly or due:
            rep = weekly_report(client, g)
            stamp = today_str()
            write_json(GSC_DIR / f"report-{stamp}.json", rep)
            (GSC_DIR / f"report-{stamp}.md").write_text(markdown(rep), encoding="utf-8")
            state["last_weekly"] = stamp
            write_json(STATE_PATH, state)
            text = short_text(rep)
            log("Search Console 週次まとめを作成:\n" + text)
            if notify:
                notify(text)
        return f"Search Console: 検査{n}本"
    except (GscError, requests.RequestException) as e:
        log(f"Search Console: {e}")
        return f"Search Console: エラー（{str(e)[:60]}）"


def main() -> int:
    ap = argparse.ArgumentParser(description="Search Console の数字を集める")
    ap.add_argument("--check", action="store_true", help="設定の確認だけ行う")
    ap.add_argument("--weekly", action="store_true", help="今すぐ週次まとめを作る")
    ap.add_argument("--inspect", type=int, default=None, help="登録状況を指定本数だけ検査する")
    ap.add_argument("--notify", action="store_true", help="週次まとめをLINEにも送る")
    args = ap.parse_args()
    config = load_config()
    g = gsc_config(config)
    try:
        token = access_token(g)
        client = Client(g, token)
        if args.check:
            sm = client.sitemaps()
            client.analytics((now_jst().date() - timedelta(days=10)).isoformat(), (now_jst().date() - timedelta(days=3)).isoformat())
            log(f"OK: Search Console（{g['site_url']}）に接続できました。サイトマップ {len(sm)}件を確認")
            return 0
        if args.inspect:
            log(f"登録状況を{run_inspection(client, args.inspect)}本検査しました")
        if args.weekly:
            notify = None
            if args.notify:
                from run_daily import notify_line
                notify = notify_line
            rep = weekly_report(client, g)
            stamp = today_str()
            write_json(GSC_DIR / f"report-{stamp}.json", rep)
            md = GSC_DIR / f"report-{stamp}.md"
            md.write_text(markdown(rep), encoding="utf-8")
            print(short_text(rep))
            log(f"詳細: {md}")
            if notify:
                notify(short_text(rep))
        return 0
    except (GscError, requests.RequestException) as e:
        log(f"NG: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

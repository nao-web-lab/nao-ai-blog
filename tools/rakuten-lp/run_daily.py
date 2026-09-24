"""楽天商品リサーチ → AI選定 → LP生成 → 品質チェック → 一覧/サイトマップ更新 → git push の毎日実行スクリプト。

使い方（PowerShell / nao-ai-blog フォルダで）:
  python tools/rakuten-lp/run_daily.py --limit 3 --categories beauty,living,appliances --no-push   # テスト(公開しない)
  python tools/rakuten-lp/run_daily.py                                                               # 本番(品質基準を満たす商品をできるだけ多く)

  --limit N         今回の実行で新規作成する上限（本日分の残り本数とどちらか小さい方）
  --categories a,b  探索するカテゴリを限定（テスト用）
  --no-push         commit/pushしない（生成物の確認用）
  --mock            楽天API・Geminiを使わずモックデータで動作確認（オフライン）
"""

import argparse
import os
import random
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gemini  # noqa: E402
import images  # noqa: E402
import listing  # noqa: E402
import quality  # noqa: E402
import rakuten_api  # noqa: E402
import render  # noqa: E402
import scoring  # noqa: E402
import writer  # noqa: E402
from common import (CONTENT_DIR, DB_PATH, FAILED_LOG, GENERATED_LOG, LOG_DIR, REPO_ROOT, TOOL_DIR,  # noqa: E402
                    append_log, load_config, load_env_files, log, now_jst, read_json, redact, today_str, write_json)

EXCLUDE_RETRY_DAYS = 60
LOCK = LOG_DIR / "run.lock"
RUN_STARTED = now_jst()


class SkipProduct(Exception):
    """品質・適性の理由でLP化しない（エラーではない）。"""


class RetryLater(Exception):
    """今回は見送るが、商品自体の問題ではないので後日もう一度試す。"""


class CategoryFull(Exception):
    """AIが判定したカテゴリが本日の上限に達している（DBには記録せず、別の日に回す）。"""


# ---------------------------------------------------------------- DB
def load_db() -> dict:
    db = read_json(DB_PATH, {})
    db.setdefault("products", {})
    db.setdefault("state", {"next_category": 0})
    # 旧バージョンで「画像を確認できない」として除外した商品は、一時的な通信失敗の可能性があるので再挑戦の対象に戻す
    for rec in db["products"].values():
        if rec.get("status") == "excluded" and (rec.get("reason") == "利用可能な商品画像を確認できない" or str(rec.get("reason", "")).startswith("他LPとの重複")):
            rec["status"], rec["fail_count"] = "failed", 1
    return db


def save_db(db: dict) -> None:
    write_json(DB_PATH, db)


def slugify(item_code: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", item_code.lower()).strip("-")
    return s[:70] or "item"


def is_blocked(db: dict, code: str) -> bool:
    rec = db["products"].get(code)
    if not rec:
        return False
    if rec["status"] == "published":
        return True
    if rec["status"] == "excluded":
        try:
            from datetime import datetime
            age = (now_jst() - datetime.fromisoformat(rec["updated_at"])).days
        except (KeyError, ValueError):
            return True
        return age < EXCLUDE_RETRY_DAYS
    if rec["status"] == "failed":
        return rec.get("fail_count", 0) >= 3
    return False


# ---------------------------------------------------------------- research
def research(config: dict, db: dict, cats: list, need: int, made_today_by_cat: dict) -> list:
    """カテゴリをローテーションしながら候補を集める。足りなければ次のカテゴリへ自動で広げる。"""
    pool, seen = [], set()
    n = len(cats)
    start = db["state"].get("next_category", 0) % max(n, 1)
    target_pool = max(need * 3, 6)
    for step in range(n):
        cat = cats[(start + step) % n]
        room = config["max_per_category_per_day"] - made_today_by_cat.get(cat["slug"], 0)
        if room <= 0:
            continue
        kws = cat["keywords"][:]
        random.shuffle(kws)
        found_in_cat = 0
        for kw in kws[:3]:
            for page in range(1, config["rakuten_pages_per_keyword"] + 1):
                try:
                    items = rakuten_api.search(kw, page=page, hits=config["rakuten_hits_per_page"], interval=config["rakuten_interval_sec"])
                except rakuten_api.RakutenAPIError as e:
                    log(f"  楽天API失敗（{kw} p{page}）: {e} → このキーワードはスキップ")
                    append_log(FAILED_LOG, {"at": now_jst().isoformat(), "stage": "research", "keyword": kw, "error": redact(e)})
                    break
                if not items:
                    break
                for it in items:
                    code = it.get("itemCode")
                    if not code or code in seen or is_blocked(db, code):
                        continue
                    seen.add(code)
                    ok, why = scoring.passes_basic_filter(it, config)
                    if not ok:
                        continue
                    ps = scoring.primary_score(it)
                    if ps["primary"] < config["min_primary_score"]:
                        continue
                    pool.append({"item": it, "category": cat, "keyword": kw, "primary": ps["primary"],
                                 "score_detail": ps["detail"], "image_count": ps["image_count"], "score_for_rank": ps["primary"]})
                    found_in_cat += 1
        log(f"  [{cat['label']}] 候補 {found_in_cat}件")
        searched = step + 1
        if len(pool) >= target_pool and searched >= min(n, max(need, 3)):
            db["state"]["next_category"] = (start + step + 1) % n
            break
    else:
        db["state"]["next_category"] = (start + 1) % max(n, 1)

    # 画像が豊富な商品を「同程度のスコアなら」優先 → カテゴリが偏らないよう交互に並べる
    ranked = scoring.rank_with_image_priority(pool)
    by_cat = {}
    for c in ranked:
        by_cat.setdefault(c["category"]["slug"], []).append(c)
    interleaved = []
    while any(by_cat.values()):
        for slug in list(by_cat):
            if by_cat[slug]:
                interleaved.append(by_cat[slug].pop(0))
    return interleaved


def research_ranking(config: dict, db: dict, need: int) -> list:
    """楽天ランキング（ジャンル指定なし＝総合、年代・性別別）から売れ筋・流行商品を集める。
    カテゴリは固定せず、あとでAIが商品ごとに判定する。"""
    sources = config["ranking_sources"]
    n = len(sources)
    start = db["state"].get("next_ranking_source", 0) % n
    per_run = min(config.get("ranking_sources_per_run", 4), n)
    # 流行（リアルタイム総合）は毎回含め、残りは日ごとにローテーション
    picked = [sources[0]] + [sources[(start + i) % (n - 1) + 1] for i in range(per_run - 1)] if n > 1 else sources
    db["state"]["next_ranking_source"] = (start + per_run - 1) % max(n - 1, 1)
    other = next(c for c in config["categories"] if c["slug"] == "other")

    raw, seen = [], set()
    for src in picked:
        got = 0
        for page in range(1, config.get("ranking_pages_per_source", 3) + 1):
            try:
                items = rakuten_api.ranking(page=page, interval=config["rakuten_interval_sec"], period=src.get("period"),
                                            age=src.get("age"), sex=src.get("sex"))
            except rakuten_api.RakutenAPIError as e:
                log(f"  ランキングAPI失敗（{src['label']} p{page}）: {e}")
                append_log(FAILED_LOG, {"at": now_jst().isoformat(), "stage": "ranking", "source": src["label"], "error": redact(e)})
                break
            if not items:
                break
            for it in items:
                code = it.get("itemCode")
                if not code or code in seen or is_blocked(db, code):
                    continue
                seen.add(code)
                ok, _ = scoring.passes_basic_filter(it, config, check_caption=False)
                if not ok:
                    continue
                raw.append((it, src, scoring.trend_bonus(it.get("rank"), src)))
                got += 1
        log(f"  [楽天ランキング: {src['label']}] 候補 {got}件")

    # 商品説明が足りない商品は、商品コードで検索APIを引いて補う（上位から、回数上限あり）
    raw.sort(key=lambda x: (x[2], scoring.primary_score(x[0])["primary"]), reverse=True)
    pool, lookups = [], 0
    for it, src, bonus in raw:
        if len(pool) >= max(need * 4, 12):
            break
        if len(it.get("itemCaption") or "") < 60 and lookups < config.get("max_lookups_per_run", 80):
            lookups += 1
            try:
                detail = rakuten_api.lookup(it["itemCode"], interval=config["rakuten_interval_sec"])
            except rakuten_api.RakutenAPIError:
                detail = {}
            for k, v in detail.items():
                if k not in it or not it.get(k):
                    it[k] = v
        ok, _ = scoring.passes_basic_filter(it, config)
        if not ok:
            continue
        ps = scoring.primary_score(it)
        if ps["primary"] < config["min_primary_score"]:
            continue
        pool.append({"item": it, "category": other, "keyword": "", "source_label": src["label"], "primary": ps["primary"],
                     "score_detail": ps["detail"] | {"trend_bonus": bonus, "rank": it.get("rank")}, "image_count": ps["image_count"],
                     "score_for_rank": ps["primary"] + bonus, "from_ranking": True})
    log(f"  ランキング由来の候補: {len(pool)}件（商品説明の補完 {lookups}回）")
    return scoring.rank_with_image_priority(pool)


# ---------------------------------------------------------------- one product
def build_product(cand: dict, a: dict, verified_imgs: list) -> dict:
    it = cand["item"]
    name = it.get("itemName") or ""
    display = (a.get("display_name") or "").strip()
    # AIの表示名が元の商品名にない語を含む場合は採用しない（商品名の捏造防止）
    norm_name = quality._norm(name)
    if not display or any(tok and quality._norm(tok) not in norm_name for tok in re.split(r"[\s　]+", display)):
        display = scoring.clean_name(name, 40)
    caption = it.get("itemCaption") or ""
    norm_cap = quality._norm(caption)
    spec_rows = []
    for r in a.get("spec_rows") or []:
        q, v = (r.get("source_quote") or ""), (r.get("value") or "")
        if q and v and quality._norm(q) in norm_cap and quality._norm(v) in norm_cap and r.get("label"):
            spec_rows.append({"label": r["label"][:20], "value": v[:80]})
    return {
        "item_code": it["itemCode"], "item_name": name, "display_name": display, "caption": caption,
        "item_url": it.get("itemUrl", ""), "affiliate_url": it["affiliateUrl"], "shop_name": it.get("shopName", ""),
        "price": int(it.get("itemPrice") or 0), "review_count": int(it.get("reviewCount") or 0),
        "review_average": float(it.get("reviewAverage") or 0), "tax_flag": it.get("taxFlag"), "postage_flag": it.get("postageFlag"),
        "category": cand["category"]["slug"], "category_label": cand["category"]["label"], "layout": cand["category"]["layout"],
        "keyword": cand["keyword"], "image_urls": verified_imgs, "spec_rows": spec_rows[:8],
        "fetched_at": now_jst().isoformat(timespec="seconds"),
    }


def source_text(p: dict) -> str:
    return f"{p['item_name']}\n{p['caption']}\n{p['display_name']}\n{p['review_count']}件 {p['review_average']}"


def recent_contents(db: dict, limit: int = 60) -> list:
    recs = sorted((r for r in db["products"].values() if r["status"] == "published"), key=lambda r: r.get("created_at", ""), reverse=True)[:limit]
    out = []
    for r in recs:
        data = read_json(CONTENT_DIR / f"{r['slug']}.json", None)
        if data:
            out.append(data["content"])
    return out


def avoid_phrases(recents: list) -> list:
    out = []
    for c in recents[:15]:
        for keys in (("fv", "catch"), ("fv", "eyebrow"), ("cta", "main")):
            v = quality._get(c, keys)
            if v:
                out.append(v)
        out.extend(v for v in (c.get("headings") or {}).values() if v)
    return list(dict.fromkeys(out))


def page_ctx(config, p, slug, created, modified, fetched=None):
    site = config["site_base_url"]
    return {"site_url": site, "site_name": config["site_name"], "root_rel": "../../../",
            "public_url": f"{site}/products/{p['category']}/{slug}/", "fetched_date": (fetched or p.get("fetched_at") or created)[:10].replace("-", "/"),
            "published": created, "modified": modified, "favicon": listing.FAVICON}


def process(cand: dict, config: dict, db: dict, rng: random.Random, made_by_cat: dict = None) -> dict:
    it = cand["item"]
    code = it["itemCode"]
    if not quality.is_valid_affiliate_url(it.get("affiliateUrl")):
        raise SkipProduct("affiliate URLの形式が不正")

    # 画像: APIが返したURLのみ → 表示できるか確認 → AIに内容を確認させる
    verified = images.verify(rakuten_api.image_urls(it))
    if not verified:
        raise SkipProduct("利用可能な商品画像を確認できない")
    img_parts = images.fetch_for_analysis(verified)

    tmp_p = {"item_name": it.get("itemName", ""), "display_name": scoring.clean_name(it.get("itemName", "")),
             "caption": it.get("itemCaption", ""), "shop_name": it.get("shopName"), "price": it.get("itemPrice"),
             "review_count": it.get("reviewCount"), "review_average": it.get("reviewAverage"),
             "category_label": "未分類（AIが判定）" if cand.get("from_ranking") else cand["category"]["label"],
             "keyword": cand["keyword"], "image_urls": verified}
    a = writer.analyze(tmp_p, img_parts, config["categories"])
    # 検索キーワードとAIのカテゴリ判定が違う場合（例: 「バスタオル」で出産祝いのおむつケーキ）はAIの判定を採用
    ai_cat = next((c for c in config["categories"] if c["slug"] == a.get("category_slug")), None)
    if ai_cat and ai_cat["slug"] != cand["category"]["slug"]:
        log(f"  カテゴリをAI判定で変更: {cand['category']['label']} → {ai_cat['label']}")
        cand["category"] = ai_cat
    if made_by_cat is not None and made_by_cat.get(cand["category"]["slug"], 0) >= config["max_per_category_per_day"]:
        raise CategoryFull(cand["category"]["label"])
    # 同じ種類の商品（例: 紙おむつ、炭酸水）が1日に何本も並ばないようにする
    ptype = quality._norm(a.get("product_type") or "")
    if ptype:
        same = [r for r in db["products"].values() if r.get("status") == "published" and r.get("created_at", "").startswith(today_str())
                and r.get("product_type") and (ptype in quality._norm(r["product_type"]) or quality._norm(r["product_type"]) in ptype)]
        if len(same) >= config.get("max_per_product_type_per_day", 2):
            raise CategoryFull(f"{a.get('product_type')}（同じ種類の商品・1日{config.get('max_per_product_type_per_day', 2)}本まで）")
    ai_scores = a.get("scores") or {}
    final = scoring.final_score(cand["primary"], ai_scores)
    if not a.get("suitable", False):
        raise SkipProduct(f"AI判定でLP化に不向き: {a.get('reject_reason') or '理由未記載'}")
    if final < config["min_final_score"]:
        raise SkipProduct(f"最終スコア不足 {final}")

    p = build_product(cand, a, verified)
    plan = images.build_image_plan(verified, a.get("images"), config["max_images"], p["display_name"])
    if not plan:
        raise SkipProduct("LPに使える画像がない")

    recents = recent_contents(db)
    c = writer.write(p, a, avoid_phrases(recents), rng)
    c["_keywords"] = (a.get("keywords") or [])[:6]
    src = source_text(p)

    # チェック → AIレビューで修正 → 再チェック
    c, fixes1 = quality.check_and_fix_text(c, src)
    issues = quality.structural_issues(c) + quality.style_issues(c) + quality.similarity_issues(c, recents)
    c = writer.review(p, c, fixes1 + issues)
    c, fixes2 = quality.check_and_fix_text(c, src)
    fixes2 += quality.check_risk_text(c, a.get("risk_category"))
    fixes2 += quality.check_image_texts(plan, src, p["display_name"])
    quality.diversify_cta(c, recents, rng)
    hard = quality.structural_issues(c)
    sim = quality.similarity_issues(c, recents)
    if hard:
        raise SkipProduct("品質チェック不合格: " + " / ".join(hard))
    if sim:
        # 他LPと似すぎている部分だけ、もう一度AIに書き直させる（それでも似ていれば後日再挑戦）
        c = writer.review(p, c, ["次の部分が他の商品ページとほぼ同じ文言です。この商品ならではの言葉で全面的に書き換えてください: " + s for s in sim])
        c, fixes3 = quality.check_and_fix_text(c, src)
        fixes2 += fixes3 + quality.check_risk_text(c, a.get("risk_category"))
        quality.diversify_cta(c, recents, rng)
        hard = quality.structural_issues(c)
        sim = quality.similarity_issues(c, recents)
        if hard:
            raise SkipProduct("品質チェック不合格: " + " / ".join(hard))
        if sim:
            raise RetryLater("他LPとの重複（後日再挑戦）: " + " / ".join(sim))

    slug = slugify(code)
    lp_rel = f"products/{p['category']}/{slug}/index.html"
    now = now_jst().isoformat(timespec="seconds")
    rec = {
        "item_code": code, "slug": slug, "item_name": p["item_name"], "display_name": p["display_name"],
        "item_url": p["item_url"], "affiliate_url": p["affiliate_url"], "category": p["category"], "category_label": p["category_label"],
        "keyword": p["keyword"], "product_type": a.get("product_type", ""), "keywords": a.get("keywords") or [],
        "related_needs": a.get("related_needs") or [], "primary_score": cand["primary"], "score_detail": cand["score_detail"],
        "ai_scores": ai_scores, "final_score": final, "lp_path": lp_rel, "lp_url": f"{config['site_base_url']}/products/{p['category']}/{slug}/",
        "images": [x["url"] for x in plan], "image_count": len(plan), "title": c.get("title", ""),
        "status": "published", "created_at": now, "updated_at": now, "last_checked_at": now, "fail_count": 0,
        "voice": c.get("_voice"), "auto_fixes": len(fixes1) + len(fixes2),
    }
    entries = listing.published_entries(db)
    related = listing.related_items_for(rec, entries, config["related_links"])
    ctx = page_ctx(config, p, slug, now, now)
    html_text = render.render_page(p, c, plan, related, ctx)

    page_path = REPO_ROOT / lp_rel
    page_path.parent.mkdir(parents=True, exist_ok=True)
    listing.build_listings(db, config, ensure=[p["category"]])  # パンくずのリンク先(一覧ページ)を先に用意
    html_issues = quality.check_html(html_text, page_path, ctx["public_url"], p["affiliate_url"], REPO_ROOT)
    if html_issues:
        raise SkipProduct("HTMLチェック不合格: " + " / ".join(html_issues[:5]))

    page_path.write_text(html_text, encoding="utf-8")
    rec["related"] = [r["href"] for r in related]
    write_json(CONTENT_DIR / f"{slug}.json", {"product": p, "content": c, "image_plan": plan, "analysis": a})
    rec["review_changes"] = len(c.get("_review_changes") or [])
    return rec


def refresh_related(db: dict, config: dict) -> int:
    """新しいLPが増えたら、既存LPの「関連商品」リンクを更新する（存在するLPへのリンクだけ）。"""
    entries = listing.published_entries(db)
    updated = 0
    for rec in entries:
        related = listing.related_items_for(rec, entries, config["related_links"])
        hrefs = [r["href"] for r in related]
        if hrefs == rec.get("related"):
            continue
        data = read_json(CONTENT_DIR / f"{rec['slug']}.json", None)
        if not data:
            continue
        now = now_jst().isoformat(timespec="seconds")
        ctx = page_ctx(config, data["product"], rec["slug"], rec["created_at"], now)
        html_text = render.render_page(data["product"], data["content"], data["image_plan"], related, ctx)
        path = REPO_ROOT / rec["lp_path"]
        if quality.check_html(html_text, path, ctx["public_url"], rec["affiliate_url"], REPO_ROOT):
            continue
        path.write_text(html_text, encoding="utf-8")
        rec["related"] = hrefs
        rec["updated_at"] = now
        updated += 1
    return updated


# ---------------------------------------------------------------- git
def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失敗: {r.stderr.strip()[:300]}")
    return r.stdout


OUR_PATHS = ["products", "tools/rakuten-lp", "sitemap.xml", "robots.txt", "lp/auto/index.html"]  # tools/rakuten-lp: ツール自体の更新も一緒に公開（logsは.gitignoreで除外）


def unrelated_changes() -> list:
    out = git("status", "--porcelain")
    bad = []
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        if not any(path == p or path.startswith(p + "/") or path.startswith(p) for p in OUR_PATHS):
            bad.append(path)
    return bad


def publish(n_new: int) -> None:
    git("add", "--", *OUR_PATHS)
    if not git("diff", "--cached", "--name-only").strip():
        log("公開する変更はありません")
        return
    git("commit", "-m", f"Add {n_new} Rakuten product LP(s) {today_str()}")
    for attempt in range(3):
        try:
            git("pull", "--rebase", "--autostash", "origin", "main")
            git("push", "origin", "HEAD:main")
            log("GitHubへpushしました（数分後にGitHub Pagesへ反映されます）")
            return
        except RuntimeError as e:
            log(f"push失敗（{attempt + 1}回目）: {e}")
    raise RuntimeError("pushに3回失敗しました。ログ(tools/rakuten-lp/logs)の push失敗 の行を確認してください")


# ---------------------------------------------------------------- main
class _Tee:
    """画面とログファイルの両方に出力（タスクスケジューラ(pythonw)実行時は画面がないのでファイルのみ）。"""

    def __init__(self, path):
        self.f = open(path, "a", encoding="utf-8")
        self.console = sys.__stdout__

    def write(self, s):
        self.f.write(s)
        self.f.flush()
        if self.console:
            try:
                self.console.write(s)
            except Exception:
                pass

    def flush(self):
        self.f.flush()


def notify_line(text: str) -> None:
    """rakuten-threads-auto の LINE通知(local/line_notify.py)を再利用。無ければ何もしない。"""
    try:
        sys.path.insert(0, str((TOOL_DIR / "../../../rakuten-threads-auto/local").resolve()))
        from line_notify import send_line_message
        send_line_message(text)
    except Exception as e:
        log(f"LINE通知なし（{type(e).__name__}）")


def main() -> int:
    tee = _Tee(LOG_DIR / f"run_{now_jst().strftime('%Y-%m-%d_%H%M%S')}.log")
    sys.stdout = sys.stderr = tee
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--categories", default="")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--source", choices=["ranking", "keywords"], default=None, help="商品の探し方（既定: config.jsonのsource=ranking）")
    ap.add_argument("--notify", action="store_true", help="終了時にLINEへ結果を通知（タスクスケジューラ用）")
    args = ap.parse_args()

    if args.mock:
        os.environ["RAKUTEN_LP_MOCK"] = "1"
    config = load_config()
    load_env_files(config)
    gemini.configure(config["gemini_interval_sec"], config["gemini_max_calls_per_run"])

    if LOCK.exists() and (now_jst().timestamp() - LOCK.stat().st_mtime) < 3 * 3600:
        log("別の実行が進行中のため終了します（3時間以上前のロックは自動で無視します）")
        return 0
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    try:
        return run(config, args)
    except Exception as e:
        log(f"致命的なエラー: {redact(e)}")
        log(redact(traceback.format_exc()))
        if args.notify:
            notify_line(f"⚠️ 楽天LP自動生成でエラー\n{redact(e)[:200]}")
        return 1
    finally:
        LOCK.unlink(missing_ok=True)


def budget_exhausted(config: dict, db: dict) -> bool:
    """実行時間・Geminiの1日の利用枠を超えそうなら True（残りは翌日に回す）。"""
    elapsed = (now_jst() - RUN_STARTED).total_seconds() / 60
    if elapsed >= config.get("max_run_minutes", 300):
        log(f"実行時間の上限（{config.get('max_run_minutes')}分）に達したため、今回はここまで")
        return True
    used = db["state"].get("gemini_calls", {}).get(today_str(), 0) + gemini.calls_used()
    if used + 4 > config.get("gemini_daily_calls_limit", 450):
        log(f"本日のGemini利用上限（{config.get('gemini_daily_calls_limit')}回）に近づいたため、今回はここまで")
        return True
    return False


def process_pool(pool, config, db, rng, new_recs, made_by_cat, remaining, tried_codes) -> bool:
    """候補を順に処理。Geminiの上限に達したら True（それ以上続けない）を返す。"""
    img_errors = [0]
    for cand in pool:
        if len(new_recs) >= remaining:
            break
        if budget_exhausted(config, db):
            return True
        cat = cand["category"]["slug"]
        if made_by_cat.get(cat, 0) >= config["max_per_category_per_day"]:
            continue
        it = cand["item"]
        code = it["itemCode"]
        tried_codes.add(code)
        log(f"▶ {scoring.clean_name(it.get('itemName', ''), 40)}（{cand['category']['label']} / 一次{cand['primary']}点 / 画像{cand['image_count']}枚）")
        now = now_jst().isoformat(timespec="seconds")
        try:
            rec = process(cand, config, db, rng, made_by_cat)
            db["products"][code] = rec
            made_by_cat[rec["category"]] = made_by_cat.get(rec["category"], 0) + 1
            new_recs.append(rec)
            img_errors[0] = 0
            append_log(GENERATED_LOG, {k: rec[k] for k in ("item_code", "display_name", "item_url", "lp_url", "created_at", "final_score", "category", "image_count", "status")} | {"error": None})
            log(f"  ✔ 公開用に生成 {rec['lp_url']}（最終{rec['final_score']}点・画像{rec['image_count']}枚・自動修正{rec['auto_fixes']}件）")
        except CategoryFull as e:
            log(f"  – 見送り: 「{e}」は本日の上限に達したため別の日に回します")
            continue
        except SkipProduct as e:
            db["products"][code] = {"item_code": code, "item_name": it.get("itemName", ""), "affiliate_url": it.get("affiliateUrl"),
                                    "category": cat, "status": "excluded", "reason": str(e), "primary_score": cand["primary"],
                                    "created_at": now, "updated_at": now}
            log(f"  – 除外: {e}")
        except RetryLater as e:
            prev = db["products"].get(code, {})
            db["products"][code] = {"item_code": code, "item_name": it.get("itemName", ""), "affiliate_url": it.get("affiliateUrl"),
                                    "category": cat, "status": "failed", "fail_count": prev.get("fail_count", 0) + 1,
                                    "reason": str(e), "created_at": prev.get("created_at", now), "updated_at": now}
            log(f"  – 見送り: {e}")
            save_db(db)
            continue
        except images.ImageCheckError as e:
            prev = db["products"].get(code, {})
            db["products"][code] = {"item_code": code, "item_name": it.get("itemName", ""), "affiliate_url": it.get("affiliateUrl"),
                                    "category": cat, "status": "failed", "fail_count": prev.get("fail_count", 0) + 1,
                                    "reason": str(e), "created_at": prev.get("created_at", now), "updated_at": now}
            img_errors[0] += 1
            log(f"  ✖ 画像サーバーへの接続失敗（後日再試行）: {e}")
            if img_errors[0] >= 3:
                log("  画像サーバーへの接続失敗が続いているため60秒待機します")
                time.sleep(60)
                img_errors[0] = 0
            save_db(db)
            continue
        except gemini.GeminiQuotaExceeded as e:
            log(f"  Gemini上限: {e} → 今回はここまで")
            return True
        except Exception as e:  # 1商品の失敗で全体を止めない
            prev = db["products"].get(code, {})
            db["products"][code] = {"item_code": code, "item_name": it.get("itemName", ""), "affiliate_url": it.get("affiliateUrl"),
                                    "category": cat, "status": "failed", "fail_count": prev.get("fail_count", 0) + 1,
                                    "reason": redact(f"{type(e).__name__}: {e}"), "created_at": prev.get("created_at", now), "updated_at": now}
            append_log(FAILED_LOG, {"at": now, "item_code": code, "item_name": it.get("itemName", "")[:80], "stage": "generate",
                                    "error": redact(f"{type(e).__name__}: {e}"), "trace": redact(traceback.format_exc()[-800:])})
            log(f"  ✖ 失敗（次の商品へ進みます）: {redact(e)}")
        save_db(db)
    return False


def retract(db: dict, code: str, reason: str) -> None:
    """公開済みLPを取り下げる（ページとデータを削除し、DBに理由を残す）。"""
    import shutil
    rec = db["products"][code]
    page_dir = (REPO_ROOT / rec["lp_path"]).parent
    if page_dir.exists() and page_dir.parent.parent == REPO_ROOT / "products":
        shutil.rmtree(page_dir)
    (CONTENT_DIR / f"{rec.get('slug', '')}.json").unlink(missing_ok=True)
    rec["status"], rec["reason"] = "excluded", f"取り下げ: {reason}"
    rec["updated_at"] = now_jst().isoformat(timespec="seconds")
    log(f"取り下げ: {rec.get('display_name', code)}（{reason}）")


def retract_banned(db: dict) -> None:
    """基準変更で対象外になった商品（例: カラコン）の公開済みLPを取り下げる。"""
    for code, rec in list(db["products"].items()):
        if rec.get("status") == "published" and scoring.BANNED_NAME_RE.search(rec.get("item_name", "")):
            retract(db, code, "対象外カテゴリ（医療機器など）")


def audit_published(db: dict, config: dict) -> dict:
    """公開済みLPの定期点検（毎日、最後に点検した日が古い順に一定数）。

    1. 楽天APIで最新の商品情報を取得 → 価格・レビュー件数・評価・在庫を更新
       （商品ページが消えた/販売停止が2回続いたら取り下げ）
    2. 商品画像がまだ表示できるか確認 → 表示できない画像は外す（全滅なら取り下げ）
    3. 最新の品質ルールで文章を再チェック → 問題のある文を自動修正
       （必須項目が欠けるほどの問題なら取り下げ）
    4. HTMLを作り直してHTMLチェック → 合格したものだけ上書き
    """
    import copy
    n = config.get("audit_per_day", 30)
    summary = {"checked": 0, "updated": 0, "text_fixed": 0, "images_dropped": 0, "retracted": 0}
    targets = sorted((r for r in db["products"].values() if r.get("status") == "published"),
                     key=lambda r: r.get("last_checked_at", ""))[:n]
    today = today_str()
    for rec in targets:
        if rec.get("last_checked_at", "").startswith(today) and rec.get("created_at", "").startswith(today):
            continue  # 今日作ったばかりのページは点検不要
        code = rec["item_code"]
        data = read_json(CONTENT_DIR / f"{rec.get('slug', '')}.json", None)
        if not data:
            continue
        p, c, plan = data["product"], data["content"], data["image_plan"]
        changed = []
        summary["checked"] += 1
        now = now_jst().isoformat(timespec="seconds")

        # 1. 最新の商品情報
        try:
            item = rakuten_api.lookup(code, interval=config["rakuten_interval_sec"])
        except rakuten_api.RakutenAPIError as e:
            log(f"  点検スキップ（楽天API失敗）: {rec.get('display_name')} {e}")
            continue
        if not item:
            rec["missing_count"] = rec.get("missing_count", 0) + 1
            if rec["missing_count"] >= 2 and not os.getenv("RAKUTEN_LP_MOCK"):
                retract(db, code, "楽天市場で商品が見つからない（販売終了の可能性）")
                summary["retracted"] += 1
                continue
        else:
            rec["missing_count"] = 0
            if int(item.get("availability", 1) or 0) == 0:
                rec["unavailable_count"] = rec.get("unavailable_count", 0) + 1
                if rec["unavailable_count"] >= 2:
                    retract(db, code, "販売停止・在庫切れが続いている")
                    summary["retracted"] += 1
                    continue
            else:
                rec["unavailable_count"] = 0
            for key, field, cast in (("price", "itemPrice", int), ("review_count", "reviewCount", int),
                                     ("review_average", "reviewAverage", float)):
                if item.get(field) is not None and cast(item[field]) != p.get(key):
                    changed.append(f"{key}: {p.get(key)}→{item[field]}")
                    p[key] = cast(item[field])
            new_aff = item.get("affiliateUrl")
            if new_aff and quality.is_valid_affiliate_url(new_aff) and new_aff != p["affiliate_url"]:
                p["affiliate_url"] = rec["affiliate_url"] = new_aff
                changed.append("affiliate URL更新")
            p["fetched_at"] = now

        # 2. 画像
        try:
            alive = set(images.verify([i["url"] for i in plan]))
        except images.ImageCheckError:
            alive = {i["url"] for i in plan}  # 通信の問題なら今回は触らない
        kept = [i for i in plan if i["url"] in alive]
        if not kept:
            retract(db, code, "商品画像が表示できなくなった")
            summary["retracted"] += 1
            continue
        if len(kept) != len(plan):
            summary["images_dropped"] += len(plan) - len(kept)
            changed.append(f"画像{len(plan) - len(kept)}枚を除外")
            kept[0]["role"] = "main"
            plan = kept

        # 3. 文章（最新ルールで再チェック）
        c2 = copy.deepcopy(c)
        c2, fixes = quality.check_and_fix_text(c2, source_text(p))
        fixes += quality.check_risk_text(c2, (data.get("analysis") or {}).get("risk_category"))
        fixes += quality.check_image_texts(plan, source_text(p), p["display_name"])
        if fixes:
            if quality.structural_issues(c2):
                retract(db, code, "最新の品質基準を満たさない")
                summary["retracted"] += 1
                continue
            c = c2
            summary["text_fixed"] += 1
            changed.append(f"文章修正{len(fixes)}件")

        # 4. 再生成（情報の取得日も更新）
        entries = listing.published_entries(db)
        related = listing.related_items_for(rec, entries, config["related_links"])
        ctx = page_ctx(config, p, rec["slug"], rec["created_at"], now, fetched=p.get("fetched_at"))
        html_text = render.render_page(p, c, plan, related, ctx)
        path = REPO_ROOT / rec["lp_path"]
        issues = quality.check_html(html_text, path, ctx["public_url"], p["affiliate_url"], REPO_ROOT)
        rec["last_checked_at"] = now
        if issues:
            log(f"  点検: HTMLチェック不合格のため上書きしない {rec.get('display_name')}: {issues[:2]}")
            continue
        path.write_text(html_text, encoding="utf-8")
        write_json(CONTENT_DIR / f"{rec['slug']}.json", {**data, "product": p, "content": c, "image_plan": plan})
        rec["images"] = [i["url"] for i in plan]
        rec["image_count"] = len(plan)
        rec["related"] = [x["href"] for x in related]
        rec["updated_at"] = now
        if changed:
            summary["updated"] += 1
            append_log(LOG_DIR / "audit-log.json", {"at": now, "item_code": code, "name": rec.get("display_name"), "changes": changed})
    log(f"定期点検: {summary['checked']}本を点検 / 情報更新 {summary['updated']}本 / 文章修正 {summary['text_fixed']}本 / "
        f"画像除外 {summary['images_dropped']}枚 / 取り下げ {summary['retracted']}本")
    return summary


def run(config, args) -> int:
    log("=" * 50)
    log("楽天商品LP 自動生成")
    do_git = not args.no_push and not args.mock and (REPO_ROOT / ".git").exists()
    if do_git:
        bad = unrelated_changes()
        if bad:
            log(f"LP以外の未コミットの変更があるため、安全のため公開(push)は行いません: {bad[:5]}")
            do_git = False
        else:
            try:
                git("pull", "--rebase", "--autostash", "origin", "main")
            except RuntimeError as e:
                log(f"最新化(pull)に失敗: {e}")

    db = load_db()
    today = today_str()
    retract_banned(db)
    audit = {}
    if config.get("audit_per_day", 30) > 0:
        try:
            audit = audit_published(db, config)
        except Exception as e:  # 点検の失敗で新規作成を止めない
            log(f"定期点検でエラー（新規作成は続行）: {redact(e)}")
        save_db(db)
    made_today = [r for r in db["products"].values() if r["status"] == "published" and r.get("created_at", "").startswith(today)]
    made_by_cat = {}
    for r in made_today:
        made_by_cat[r["category"]] = made_by_cat.get(r["category"], 0) + 1
    remaining = config["daily_target"] - len(made_today)
    if args.limit is not None:
        remaining = min(remaining, args.limit)
    remaining = min(remaining, config["max_per_run"])
    log(f"本日の作成済み: {len(made_today)}本 / 1日の上限 {config['daily_target']}本 → 今回は最大{max(remaining, 0)}本（品質基準を満たす商品がある限り作成）")

    new_recs = []
    if remaining > 0:
        cats = [c for c in config["categories"] if c.get("keywords")]
        if args.categories:
            want = [s.strip() for s in args.categories.split(",")]
            cats = [c for c in cats if c["slug"] in want]
        rng = random.Random()
        tried_codes = set()
        stop = False
        for round_no in range(3):  # 候補が品質基準で除外され足りない場合は、次のジャンルへ広げて再探索
            if len(new_recs) >= remaining or stop:
                break
            use_ranking = (args.source or config.get("source", "ranking")) == "ranking" and not args.categories and round_no == 0
            if use_ranking:
                found = research_ranking(config, db, remaining - len(new_recs))
            elif round_no > 0 and not args.categories and not config.get("fallback_to_keywords", True):
                break
            else:
                found = research(config, db, cats, remaining - len(new_recs), made_by_cat)
            pool = [c for c in found if c["item"]["itemCode"] not in tried_codes]
            save_db(db)
            log(f"候補プール: {len(pool)}件（探索{round_no + 1}回目）")
            if not pool:
                break
            stop = process_pool(pool, config, db, rng, new_recs, made_by_cat, remaining, tried_codes)

    calls = db["state"].setdefault("gemini_calls", {})
    calls[today] = calls.get(today, 0) + gemini.calls_used()
    for d in sorted(calls)[:-7]:
        calls.pop(d)
    n_rel = refresh_related(db, config)
    listing.build_listings(db, config)
    save_db(db)
    try:
        sys.path.insert(0, str(REPO_ROOT / "tools" / "sitemap"))
        import rebuild_sitemap
        rebuild_sitemap.main()
    except Exception as e:
        log(f"sitemap更新に失敗: {e}")

    log(f"今回の新規LP: {len(new_recs)}本 / 関連リンク更新: {n_rel}本 / Gemini呼び出し: {gemini.calls_used()}回")
    if do_git and (new_recs or n_rel or audit.get("checked")):
        publish(len(new_recs))
    elif not do_git:
        log("--no-push（または公開停止条件）のため commit/push はしていません")
    if args.notify:
        done = len(made_today) + len(new_recs)
        notify_line(f"✅ 楽天LP自動生成\n本日 {done}本（今回 {len(new_recs)}本・Gemini {gemini.calls_used()}回）\n"
                    + (f"点検 {audit.get('checked', 0)}本（更新{audit.get('updated', 0)}・修正{audit.get('text_fixed', 0)}・取り下げ{audit.get('retracted', 0)}）\n" if audit else "")
                    + ("公開(push)済み" if do_git and new_recs else "未公開"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

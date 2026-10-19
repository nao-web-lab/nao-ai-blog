# 楽天商品LP 自動生成システム — 引き継ぎメモ（Claude Code 用）

このフォルダ（`nao-ai-blog/tools/rakuten-lp`）は、楽天市場の売れ筋・流行商品を自動で選び、
購入検討者向けのLPを生成して GitHub Pages（https://nao-web-lab.github.io/nao-ai-blog/products/）に毎日公開するツール。
オーナーは なおと（初心者にも分かる日本語で説明すること）。詳細な使い方は同じフォルダの README.md。

> このリポジトリは公開リポジトリ。このファイルやコードに APIキー・ID などの秘密情報を絶対に書かない。

## 現在の運用状態（2026-10-20 時点）
- 毎日 10:00 に Windows タスクスケジューラ「NaoAiBlog-RakutenLP」が起動
  （`pythonw tools\rakuten-lp\run_daily.py --notify`、登録は `register_task.ps1`、最長6時間）
- 1日30本を作成 → 公開済みLPを30本点検 → git commit/push → LINE通知。所要 約1時間
- 公開中 約830本 / DB: `data/database.json`（published / excluded / failed）
- 楽天APIは IP制限（このPCのみ）のため GitHub Actions では動かせない。必ずこのPCで実行する

## 処理の流れ（run_daily.py の main）
1. `retract_banned` … 対象外商品（カラコン等の医療機器・お酒・チケット等）を取り下げ
2. `audit_published` … 古い順に30本を点検：楽天APIで価格/レビュー/在庫/affiliateUrlを更新、
   2回続けて販売停止なら取り下げ、表示できない画像を外す、最新の品質ルールで文章を再チェック
3. `research_ranking` … 楽天ランキングAPI（総合リアルタイム・総合デイリー・年代性別別 計9種、ジャンル指定なし）
   → 不足時は config.json のジャンル別キーワード検索で補充
4. `scoring.py` … 一次スコア(70点)＋除外フィルタ（`passes_basic_filter` / `BANNED_NAME_RE`）
5. `writer.py`（Gemini 3回/商品）… analyze（画像付き・カテゴリ判定・二次スコア30点）→ write → review
6. `quality.py` … 誇張・ランキング主張・レビュー捏造・効能表現・定型文・本文中の価格・
   原文にない数値・直近LPとの類似・HTML（canonical/OGP/JSON-LD/PR表記/rel=sponsored/画像ホスト）をチェック・自動修正
7. `render.py` / `listing.py` … LP・一覧・カテゴリページ・関連リンク生成、`tools/sitemap/rebuild_sitemap.py` でサイトマップ
8. `publish` … `OUR_PATHS`（products, tools/rakuten-lp, sitemap.xml, robots.txt, lp/auto/index.html）だけを
   add → commit → `pull --rebase --autostash` → push。それ以外の未コミット変更があると自動pushを止める

## 守るべきルール（変更時も維持すること）
- 捏造しない・誇張しない：数値は楽天の商品説明に存在するものだけ。ランキング順位・「人気」「売れてる」等は書かない
- 楽天の画像ルール：APIが返す画像URL（thumbnail.image.rakuten.co.jp）を直リンクのみ。`?_ex=600x600` のリサイズのみ可。
  切り抜き・文字入れ・保存・再配布はしない。画像は必ずアフィリエイトリンク付き
- CTA・画像リンクは必ず API の `affiliateUrl`（https://hb.afl.rakuten.co.jp/…）。`itemUrl`（item.rakuten.co.jp）をリンクに使わない
  （2026-09-27 監査済み：全リンクが hb.afl で計測OK。計測IDは未使用）
- PR表記・`rel="nofollow sponsored noopener"` を必ず付ける
- 医療機器（カラコン等）・医薬品・お酒・チケット・ふるさと納税は扱わない

## デザイン（2026-10-20 全面改訂・公開済み）
- CSSは `products/assets/lp.css`（全LP・一覧で共通）。サイト共通の `css/style.css` は触らない（OUR_PATHS外で自動pushが止まる）
- 考え方は「売場の棚」：商品画像を淡い藍色のステージに置く／見出しは明朝体／強い色は購入ボタンの朱色だけ／一覧は罫線で区切る
- スマホは画面下に「楽天市場で見る」を固定表示（`.lp-sticky`、PCでは非表示）。確認ポイントはチェックを入れられる（保存はしない）
- PR表記は各ページ冒頭（商品名の上）に「PR｜楽天アフィリエイト広告を含みます」の1行、報酬の詳しい説明はページ下の注意書き。
  オーナーから「消したい」要望があったが、景品表示法（ステマ規制）と楽天規約のため冒頭の1行は必ず残す
- HTML構造を変えたら `--rerender` で全LPを作り直す（API・Gemini不使用、文章・更新日は据え置き、1本でも失敗したら公開しない）

## 秘密情報（値はここに書かない。変数名のみ）
`C:\Users\user\rakuten-threads-auto\local\env\common.env`（git管理外）を `config.json` の `env_files` から読み込む。
- `RAKUTEN_APPLICATION_ID` / `RAKUTEN_ACCESS_KEY` / `RAKUTEN_AFFILIATE_ID`
- `GEMINI_API_KEY_LP`（LP専用。GCPプロジェクト rakuten-lp）→ 無ければ `GEMINI_API_KEY`（Threads自動化と共用）
- LINE通知は `rakuten-threads-auto/local/line_notify.py` を利用

## 主な設定（config.json）
daily_target=30 / audit_per_day=30 / min_final_score=75 / min_review_count=20 / min_review_average=3.8 /
max_per_category_per_day=6 / max_per_product_type_per_day=2 / gemini_interval_sec=13 / gemini_daily_calls_limit=150 / max_run_minutes=300

## 作業するときの注意（重要）
- **10:00〜12:00頃は自動実行中**の可能性がある。この時間にコードを編集・git操作しない
  （過去に実行中の編集で push が3回失敗した）。`logs/` の最新 run_*.log の末尾で終了を確認してから作業する
- 動作確認は必ず公開しないモードで：
  `python tools\rakuten-lp\run_daily.py --no-push --limit 1`（オフライン確認は `--mock --no-push --limit 3`）
- 変更は小さく段階的に（1本 → 3本 → 本番）。既存の公開LPを壊さない
- `OUR_PATHS` 以外（index.html, lp/ など）を変更したら、自分でコミットするまで毎日の自動pushが止まる
- Gemini の 429/503 は自動で待機・再試行する仕様（異常ではない）
- `.github/workflows/rebuild-sitemap.yml` は保護されていて書き換えられない（不要）
- コマンドは PowerShell（Windows）前提で案内する

- 実行ログの「Rebuilt sitemap ... for 13 LP(s)」は旧 `lp/auto/` のLP数。商品ガイド（/products/）のURLは別途すべて sitemap.xml に入っている（異常ではない）

## ログ
`logs/`（git管理外）: run_日時.log（毎回の実行）、generated-products.json、failed-products.json、audit-log.json

## 今後の候補（未着手・オーナー判断待ち）
- トップページで商品ガイドを目立たせる / Google Analytics 導入（プライバシーポリシー更新も必要）
- Search Console の数字を見て1日の本数を調整 / Threads 自動化との連携
- 楽天アフィリエイトの計測IDで記事別に成果を分ける（APIのURLに付与できるか要確認）

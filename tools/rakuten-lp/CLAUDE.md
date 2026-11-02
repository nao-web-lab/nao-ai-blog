# 楽天商品LP 自動生成システム — 引き継ぎメモ（Claude Code 用）

このフォルダ（`nao-ai-blog/tools/rakuten-lp`）は、楽天市場の売れ筋・流行商品を自動で選び、
購入検討者向けのLPを生成して GitHub Pages（https://nao-web-lab.github.io/nao-ai-blog/products/）に毎日公開するツール。
オーナーは なおと（初心者にも分かる日本語で説明すること）。詳細な使い方は同じフォルダの README.md。

> このリポジトリは公開リポジトリ。このファイルやコードに APIキー・ID などの秘密情報を絶対に書かない。

## 最優先：LP作成・改修の指示書
- LP（楽天LP・A8解説ガイド・今後のあらゆるLP/商品紹介ページ）を作る・直すときは、必ず同じフォルダの `LP_BRIEF.md`（オーナーの指示書・全15項目）に従う。要点は `RULES.md`
- 着手前に、ページごとの「読者・検索意図・主キーワード・購入前の疑問・導線」を整理し、同じ検索意図のページが重複するなら新規作成より既存ページの更新・統合を優先する
- 材料（商品情報・画像・根拠）が足りないページは公開候補にしない。完了時は指示書15項目の7点報告（改善内容／検索意図／画像・図解／購入判断・導線／確認結果／未確認・不足素材／公開後の検証）を行う

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

## 共通ルール（2026-11-02追加）
- 全LPのルールは同じフォルダの `RULES.md`。変更・新規作成のときは必ず従う
- `site_audit.py`：公開ページをオフライン点検（PR・リンク・構造・薄いページ・重複）。`--json out.json` / `--list <flag>`
- LPに「同じ種類の商品と並べて確認する」比較表（`listing.compare_rows` / `run_daily.attach_compare`）と「このページで分かること」を追加
- Product構造化データ・meta keywords は廃止（要件を満たせないため）。PR行に `policy.html` へのリンクを付ける
- A8解説ガイドは `/guide/` 以下（例: car-lease/orico-de-noru）。手書き。sitemapは `rebuild_sitemap.py` が拾う

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

## 選び方・比較ガイド（2026-11-02追加）
- `listing.build_type_guides`：同じ product_type が5件以上あるとき `products/guide/t-xxxx/` に価格・レビュー・仕様の比較ガイドを自動生成（--rerender / 毎日の一覧更新で再生成）。商品ガイドトップにリンクあり
- 順位・おすすめ順は付けない（価格順）。`promo/posts_draft.md` はX/Threads/note投稿の下書き
- 2026-11-02 改訂：中身は `type_guide.py`。最初の画面（対象者・分かること・商品画像4枚・比較表へのボタン）→選ぶ前に決める3つ→価格分布図（CSS）→
  サムネイル付き比較表→商品ごとの特徴カード（事実2つ・向いている人・確認したい点）→出典つきの確認点・向いていない場合→このガイドの作り方
- 商品LPの比較表の下に、その種類のガイドへのリンク（`listing.guide_href_for` → ctx["type_guide"]）。ガイドが無い種類には出ない
- 楽天の画像サーバーはクラウド環境からは接続できない。スクリーンショット確認時は画像を仮画像に差し替えてレイアウトだけ見る

## 検索に見つけてもらうための設定（2026-11-02）
- `sitemap.xml` の lastmod は各ページの JSON-LD `dateModified`（一覧ページは配下の最新日）。日付が分からないページは lastmod を書かない
  （以前は毎日全URLを「今日」にしていたため、Google に lastmod を無視される状態だった）
- `lp/side-job/` など lp/auto 以外の手書きLPもサイトマップに載せる（noindex のページは除外）
- トップページ（index.html）に「公開中のガイド」セクション。比較ガイド一覧へは `products/#guides` で入る
- 比較ガイドの出力は毎回同じになるようにしている（項目名の並びを固定）。無駄な差分コミットを出さないため
- Search Console（URL検査・サイトマップ送信）はオーナーのGoogleアカウントでの手作業が必要（クラウド環境からは操作できない）

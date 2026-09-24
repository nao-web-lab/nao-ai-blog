# 楽天商品LP 自動生成（tools/rakuten-lp）

楽天市場APIで商品を探し、AI(Gemini)で分析・選定し、購入検討者向けのLPを生成して
`/products/<カテゴリ>/<商品>/` に公開するツールです。1日20本を目標に、不足分だけ作ります。

## 流れ
楽天ランキングAPI（ジャンル指定なしの総合リアルタイム＝流行、総合デイリー＝売れ筋、年代・性別別を日替わり）
→ 足りなければ config.json のジャンル別キーワード検索で補充 → 重複除外(商品ID) → 一次スコア(プログラム70点)
→ 画像確認(APIが返す画像のみ) → AI分析(読者・悩み・検索意図・画像の役割/二次スコア30点)
→ 構成・文章生成(ジャンル別構成・文体を商品ごとに変える) → 機械チェック → AIレビュー → 再チェック
→ HTML生成・HTMLチェック → 関連リンク更新 → 一覧/カテゴリ/サイトマップ更新 → git commit/push

## 公開済みLPの定期点検（毎日自動）
毎日の実行の最初に、最後の点検が古い順に30本（config.json の audit_per_day）を点検します。
- 楽天APIで最新の価格・レビュー件数・評価・在庫を取得してページを更新（取得日も更新）
- 商品が見つからない/販売停止が2回続いたら取り下げ
- 表示できなくなった画像を外す（全滅なら取り下げ）
- 最新の品質ルールで文章を再チェックして自動修正（基準を満たせなければ取り下げ）
- 変更内容は logs/audit-log.json に記録、結果はLINE通知に含まれます

## 実行（PowerShell）
```powershell
cd C:\Users\user\nao-ai-blog
python tools\rakuten-lp\run_daily.py --mock --no-push --limit 3 --categories beauty,living,appliances  # オフライン動作確認
python tools\rakuten-lp\run_daily.py --no-push --limit 3 --categories beauty,living,appliances         # 実データで3本（公開しない）
python tools\rakuten-lp\run_daily.py --limit 5                                                          # 5本作って公開
python tools\rakuten-lp\run_daily.py                                                                     # 本番（本日分の不足を作って公開）
python tools\rakuten-lp\run_daily.py --source keywords                                                  # ランキングではなくジャンル別キーワード検索で探す
```
毎日の自動実行は `register_task.ps1` を右クリック →「PowerShellで実行」。

## 秘密情報
コードには書きません。`rakuten-threads-auto\local\env\common.env`（git管理外）の
`RAKUTEN_APPLICATION_ID` / `RAKUTEN_ACCESS_KEY` / `RAKUTEN_AFFILIATE_ID` / `GEMINI_API_KEY` を読み込みます。

## ファイル
| ファイル | 役割 |
|---|---|
| config.json | 目標本数・しきい値・カテゴリ/キーワード |
| rakuten_api.py | 楽天API（rakuten-threads-autoと同じAPI） |
| scoring.py | スコアリング・販促文言の除去 |
| images.py | 画像の検証・選定（加工しない・保存しない） |
| gemini.py | Gemini呼び出し（リトライ・上限管理） |
| writer.py | 分析・文章生成・AIレビューのプロンプト |
| quality.py | 捏造/誇張/定型文/数値/重複/HTMLのチェックと自動修正 |
| render.py / listing.py | LP・一覧ページのHTML |
| data/database.json | 商品DB（重複防止・生成履歴） |
| data/content/*.json | 各LPの原稿（関連リンク更新時の再生成用） |
| logs/ | 実行ログ・generated-products.json・failed-products.json（git管理外） |

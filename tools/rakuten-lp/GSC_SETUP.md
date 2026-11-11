# Search Console の数字を自動で集める設定（最初の1回だけ）

毎朝のLP作成のあとに、Search Console の数字を自動で集めるための準備です。所要15分ほど。
終わると、毎週月曜に LINE へ短いまとめが届き、詳しい内容が `tools\rakuten-lp\logs\gsc\report-日付.md` に保存されます。

> 途中で作る「鍵ファイル」は、パスワードと同じ大事なものです。GitHub・LINE・チャットには絶対に貼らないでください。
> 置き場所は手順4のフォルダだけにしてください（リポジトリの中に置くと、プログラムが止まるようにしてあります）。

## 1. Search Console API を有効にする
1. https://console.cloud.google.com/ を開き、画面上部のプロジェクト選択で **rakuten-lp** を選ぶ
2. 上の検索窓に「Google Search Console API」と入力 → 出てきた項目を開く → **「有効にする」**

## 2. 自動処理用のアカウント（サービスアカウント）を作る
1. 左上のメニュー →「IAM と管理」→「サービス アカウント」
2. 「＋サービス アカウントを作成」
   - サービス アカウント名：`gsc-reader`（何でも可）
   - 「作成して続行」→ ロールは**何も選ばず**「続行」→「完了」
3. 一覧に出てきたメールアドレス（`gsc-reader@rakuten-lp.iam.gserviceaccount.com` のような形）を**メモ**する

## 3. 鍵ファイルを作る
1. 作ったサービスアカウントをクリック →「鍵」タブ →「鍵を追加」→「新しい鍵を作成」
2. 形式は **JSON** →「作成」。ファイルが自動でダウンロードされる
   - 「組織のポリシーで鍵の作成が無効」と出た場合は、ここで止めて Claude に知らせてください

## 4. 鍵ファイルを置く
ダウンロードしたファイルの名前を `gsc-service-account.json` に変えて、次のフォルダに移動します。

```
C:\Users\user\rakuten-threads-auto\local\env\gsc-service-account.json
```

（楽天やGeminiのキーが入っている `common.env` と同じフォルダです。ダウンロードフォルダに残った元のファイルは削除してください）

## 5. Search Console にアカウントを追加する
1. https://search.google.com/search-console でプロパティ `https://nao-web-lab.github.io/nao-ai-blog/` を選ぶ
2. 左下の「設定」→「ユーザーと権限」→「ユーザーを追加」
3. メールアドレスに手順2-3でメモしたアドレス、権限は **「制限付き」** →「追加」

## 6. つながるか確認する
PowerShell でリポジトリのフォルダに移動して、次を実行します。

```
python tools\rakuten-lp\gsc_report.py --check
```

- `OK: Search Console（…）に接続できました` → 完了です。翌朝から自動で動きます
- `NG: …` → 表示された文をそのまま Claude に貼ってください
- `署名用のライブラリがありません` → `pip install cryptography` を実行してから、もう一度確認

すぐに最初のまとめを見たい場合は、次を実行します（LINEにも送る場合は `--notify` を付ける）。

```
python tools\rakuten-lp\gsc_report.py --inspect 100 --weekly
```

## 分かること・分からないこと
- 分かる：検索での表示回数・クリック数・平均順位（全体、ページの種類別、ページ別、検索語句別）、サイトマップの状態、
  ページごとの登録状況（1日100本ずつ抜き取りで検査。約2週間で全ページを一巡）
- 分からない：Search Console の「ページ」画面に出る登録済み・未登録の**合計数**（Googleの窓口から取れないため、抜き取り検査で傾向を見ます）
- 検索の数字は2〜3日遅れて確定するので、まとめの期間の終わりは3日前です

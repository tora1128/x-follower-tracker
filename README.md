# X Follower Tracker

Xのフォロワー一覧を定期的に保存し、前回との差分から「いなくなった人」をCSVに出す小さなツールです。

## セットアップ

Finderで使う場合:

1. `初期設定.command` をダブルクリックします。
2. 開いた `.env` に `X_BEARER_TOKEN` と `X_USER_ID` または `X_USERNAME` を設定します。
3. 保存して閉じます。

ターミナルで設定する場合:

```bash
cd path/to/x-follower-tracker
cp .env.example .env
```

`.env` を編集します。

```env
X_BEARER_TOKEN=your_bearer_token_here
X_USER_ID=123456789
```

`X_USER_ID` がわからない場合は、代わりに `X_USERNAME` を使えます。

```env
X_BEARER_TOKEN=your_bearer_token_here
X_USERNAME=example_user
```

## 実行

```bash
python3 tracker.py
```

初回は比較対象がないため、現在のフォロワー一覧だけを保存します。2回目以降に差分CSVが作られます。

## ワンポチ確認

Finderで `今すぐ確認.command` をダブルクリックすると、前日0時以降で最初に保存されたスナップショットと現時点のフォロワー一覧を比較し、ブラウザで `reports/current.html` を開きます。

この確認では `data/followers_latest.json` は更新しません。現時点の結果を正式に保存したい場合は、通常どおり `python3 tracker.py` を実行します。

正確に前日0時と比較したい場合は、比較したい日の0時ごろに一度 `python3 tracker.py` を実行して、その時刻のスナップショットを保存してください。毎日自動実行する必要はありません。

## スマホで見る

Macとスマホが同じWi-Fiにいる場合、スマホのブラウザから確認画面を見られます。

1. Macで `今すぐ確認.command` を実行して、`reports/current.html` を作成または更新します。
2. Macで `スマホで見る.command` をダブルクリックします。
3. 表示された `http://.../reports/current.html` のURLをスマホのブラウザで開きます。

スマホ表示用サーバーを止めるには、`スマホで見る.command` のウィンドウで `control + C` を押してください。

## Webアプリとして使う

Macとスマホが同じWi-Fiにいる場合、スマホのブラウザから最新確認と正式保存を実行できます。X APIトークンはMac側の `.env` だけで使われ、スマホには保存されません。

1. Macで `Webアプリを起動.command` をダブルクリックします。
2. 表示された `http://.../?key=...` のURLをスマホのブラウザで開きます。
3. スマホ画面で `最新確認` または `正式保存` を押します。

`最新確認` は前日0時以降で最初に保存されたスナップショットと現時点を比較します。`正式保存` は現時点のフォロワー一覧を `data/` に保存し、前回保存との差分CSVを `reports/` に作ります。

Webアプリを止めるには、`Webアプリを起動.command` のウィンドウで `control + C` を押してください。URLには起動ごとに変わるアクセスキーが付きます。同じWi-Fi内でも、URLを知らない人は操作できません。

## スマホだけで使う配布

スマホだけで完結させる場合は、Macで起動するのではなく、このツールをクラウドやVPSに置いて公開URLを作ります。

配布相手には次の形式のURLだけを渡します。

```text
https://公開URL/?key=アクセスキー
```

クラウド配布用の設定例は `スマホだけで使う配布手順.md` を見てください。Render向けには `render.yaml` も同梱しています。サーバー側には `X_BEARER_TOKEN`、`X_USER_ID` または `X_USERNAME`、`WEB_APP_KEY`、必要に応じて `XFT_STORAGE_DIR` を設定します。

## 出力

- 最新スナップショット: `data/followers_latest.json`
- 履歴スナップショット: `data/followers_*.json`
- いなくなった人: `reports/removed_*.csv`
- ワンポチ確認画面: `reports/current.html`

## テスト用

API取得件数を制限して動作確認できます。

```bash
python3 tracker.py --limit 100
```

保存せずに確認する場合:

```bash
python3 tracker.py --dry-run
```

## 自動実行例

macOSのcronで毎日9時に実行する例です。

```cron
0 9 * * * cd /path/to/x-follower-tracker && /usr/bin/python3 tracker.py >> tracker.log 2>&1
```

## 配布用ZIPの作成

配布する前に、次のどちらかを実行します。

Finderで作る場合:

1. `配布用ZIPを作る.command` をダブルクリックします。
2. `dist/x-follower-tracker-YYYYMMDD.zip` を配布します。

ターミナルで作る場合:

```bash
./build_distribution.sh
```

配布用ZIPには `.env`、`data/`、`reports/`、`.DS_Store`、`dist/` は含めません。APIトークンや取得済みフォロワーデータを入れずに配布できます。

## 注意

このツールはX公式APIのフォロワー一覧を前回分と比較します。フォロー解除だけでなく、アカウント削除、凍結、非公開化、API制限などでも一覧から消えたように見える場合があります。

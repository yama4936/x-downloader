# twitterno

Xの公開投稿URLから動画を取得し、画質を選んでMP4をダウンロードするWebサイト。公開予定ドメイン: **x.yama.asia**。

追加費用をかけずに公開する手順は [DEPLOY.md](DEPLOY.md)。Render無料Web Service向けの `render.yaml` を用意している。無料枠の条件はサービス作成時に確認する。

## ローカル起動

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1 --limit-concurrency 40 --no-proxy-headers
```

ブラウザで http://localhost:8000 を開く。`/health` がヘルスチェック。

## VPSで公開

DockerとComposeが利用可能なサーバー向け。既存のWebサーバーが80/443番を使用中の場合、このComposeをそのまま起動せず、既存リバースプロキシからapp:8000へ接続するよう統合する。

1. DNSで `x.yama.asia` のAレコードをサーバーのIPv4に設定。IPv6で待ち受け可能な場合のみAAAAも設定。
2. サーバーでTCP 80/443を許可し、アプリからXおよび動画配信先へのHTTPS通信を許可する。
3. このディレクトリで `docker compose up -d --build` を実行。
4. CaddyがHTTPS証明書を自動取得する。`https://x.yama.asia/health` と実際の公開投稿で取得を確認する。

DNS、ホスティングへの接続、実際の動画取得はまだ検証していない。クラウド開発環境の通信許可にはXが含まれていないため、API検証はモックを使用。

## 運用上の仕様

- 入力はX / Twitterの投稿URLのみ。外部URLを直接取得できない。
- 動画配信先はHTTPSの `video.twimg.com` のみ。リダイレクトを追跡しない。
- ダウンロードリンクは10分で失効し、256 MiBを上限としてストリーミングする。
- 解析は最大3件同時、接続元ごとに毎分6回。投稿URLや動画をディスクに保存しない。
- メモリ内のリンクを使用するため、ワーカー数は1固定。再起動でリンクは失効する。
- 既定では転送ヘッダーを信頼しないため、プロキシ越しの利用者は同じ解析制限を共有する。本番で必要なら、信頼できるプロキシのIPのみを `--forwarded-allow-ips` に設定して `--proxy-headers` を有効化する。
- 公開前にインフラ側でリクエスト制限と帯域上限を設定する。大規模な利用には共有キャッシュ・ジョブキューが必要。
- 非公開投稿、認証必須投稿には非対応。Xの変更や制限で取得できない場合がある。yt-dlpの更新後は実投稿で動作確認する。

## テスト

```sh
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

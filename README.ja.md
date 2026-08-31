# fxtwitter skill

[English README](README.md)

**FxTwitter (FxEmbed) API v2** をClaudeから完全に扱えるようにする
[Claude Skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview)。
X/Twitterの投稿・スレッド・返信ツリー・プロフィール・タイムライン・メディア・
フォロワー・検索・サジェスト・トレンドを、APIキーもOAuthもログインもなしで取得する。

本体はPython 1ファイル・標準ライブラリのみのため、Claude.ai（Web/モバイル）、
Claude Code、Codex、素のシェルのいずれでもそのまま動く。

## 背景

Xは未認証アクセスを遮断しているため、`curl https://x.com/user/status/123` は
投稿ではなくログイン画面を返す。FxEmbedはこれを埋め込み用途で解決しており、
その公開JSON APIはエージェント用途で同じ問題を解決する。本Skillはそのv2 APIを
LLMが一発で正しく使える形にまとめたもの：入力の正規化、カーソルページング、
リトライ、コンテキストを圧迫しない出力、そして**挙動が直感に反する部分の明文化**。

通常のWeb調査中にも発火する — 検索結果がx.comリンクだった場合、ある主張の出典が投稿に
遡る場合、アカウント自体が一次情報源である場合など。ログイン壁のせいで回答が黙って
欠落することがなくなる。

## インストール

**Claude.ai（Web / モバイル）** — [releases](../../releases) から `fxtwitter.skill`
をダウンロードし、設定 → Capabilities → Skills でアップロード。または `.skill`
ファイルをチャットで開いて **Save skill** を押す。

**Claude Code / Codex など** — リポジトリをcloneし、skillsディレクトリから
中のskillを参照させる：

```bash
git clone https://github.com/mokouliszt/fxtwitter-skill.git
ln -s "$PWD/fxtwitter-skill/skills/fxtwitter" ~/.claude/skills/fxtwitter
# シンボリックリンクではなくコピーしたい場合：
# cp -r fxtwitter-skill/skills/fxtwitter ~/.claude/skills/fxtwitter
```

**単体CLIとして** — インストール不要：

```bash
cd skills/fxtwitter
python3 scripts/fxtwitter.py status https://x.com/jack/status/20
```

必要要件はPython 3.8以上のみ。

## 使い方

以下の例はすべて `skills/fxtwitter/` 直下で実行する前提。リポジトリルートから
実行する場合は `python3 skills/fxtwitter/scripts/fxtwitter.py ...` とパスを付ける。

```bash
# 投稿1件を日本語訳付き＋アカウント出自情報付きで取得
python3 scripts/fxtwitter.py status https://x.com/jack/status/20 --lang ja --about-account

# スレッドをMarkdownに展開
python3 scripts/fxtwitter.py thread <url> --format md --full-text --out thread.md

# いいね順の返信
python3 scripts/fxtwitter.py conversation <url> --ranking-mode likes --max-items 30

# アカウントの直近200件をJSON Linesで
python3 scripts/fxtwitter.py statuses NASA --all --max-items 200 --format jsonl

# 新着監視（終了コード4 = 新着なし）
python3 scripts/fxtwitter.py statuses NASA --since 1767225600

# 投稿の画像・動画を原寸でダウンロード
python3 scripts/fxtwitter.py download <url> --out-dir ./media

# 必要なフィールドだけ射影
python3 scripts/fxtwitter.py followers NASA --count 100 --select 'results[].screen_name'
```

投稿の指定は以下すべて受け付ける：

```
20
https://x.com/jack/status/20
https://twitter.com/jack/status/20/photo/1
d.fxtwitter.com/jack/status/20.mp4
https://vxtwitter.com/jack/status/20?s=46&t=abc
```

アカウントの指定は `@NASA` / `NASA` / `https://x.com/NASA` / `id:11348282`。

## エンドポイント網羅状況

v2の全オペレーション＋レガシーv1＋任意パス呼び出し。

| エンドポイント | コマンド |
| --- | --- |
| `GET /2/status/{id}` | `status` |
| `GET /2/status/{id}/reposts` | `reposts` |
| `GET /2/status/{id}/quotes` | `quotes` |
| `GET /2/thread/{id}` | `thread` |
| `GET /2/conversation/{id}` | `conversation` |
| `GET /2/profile/{handle}` | `profile` |
| `GET /2/profile/{handle}/about` | `about` |
| `GET /2/profile/{handle}/statuses` | `statuses` |
| `GET /2/profile/{handle}/articles` | `articles` |
| `GET /2/profile/{handle}/media` | `media` |
| `GET /2/profile/{handle}/followers` | `followers` |
| `GET /2/profile/{handle}/following` | `following` |
| `GET /2/search` | `search` |
| `GET /2/search/users` | `search-users` |
| `GET /2/typeahead` | `typeahead` |
| `GET /2/trends` | `trends` |
| `GET /2/openapi.json` | `spec` |
| `GET /status/{id}`, `/{handle}/status/{id}[/{lang}]`, `/{handle}`（v1） | `v1` |
| その他任意 | `get <path> --param k=v` |

## 出力フォーマット

| フォーマット | 用途 |
| --- | --- |
| `summary`（既定） | コンパクトなプレーンテキスト。JSONの約1/10のサイズ |
| `json` / `--raw` | ペイロード全体 |
| `jsonl` | 1投稿1行のJSON |
| `md` | レポート向けMarkdown |
| `urls`, `media-urls` | リンクのみ |
| `--select 'results[].id'` | 特定フィールドの射影 |

## 終了コード

| コード | 意味 |
| --- | --- |
| 0 | 成功 |
| 1 | ネットワーク／実行時エラー |
| 2 | 引数エラー |
| 3 | APIが2xx以外の `code` を返した |
| 4 | HTTP 204 — `statuses --since` で新着なし |

## 設定

| 環境変数 | 既定値 |
| --- | --- |
| `FXTWITTER_API_BASE` | `https://api.fxtwitter.com` |
| `FXTWITTER_USER_AGENT` | `fxtwitter-skill/<version>` |
| `FXTWITTER_TIMEOUT` | `30` |
| `FXTWITTER_FORMAT` | `summary` |

`FXTWITTER_API_BASE` にセルフホストしたFxEmbedインスタンスや、Bluesky用の
`https://api.fxbsky.app` を指定できる（レスポンス形状は揃えられている）。

## 既知の上流挙動

- **`User-Agent` ヘッダは必須。** 無いと `401` を返す。本クライアントは常に付与する。
- **`search` / `search-users` / `quotes` は公開インスタンスでは不安定。** これらは
  X側の検索バックエンドを経由するが、共有ゲストセッションが拒否されることが多く、
  その場合 `code: 404` と空の `results` が返る。`from:` 検索の代わりに `statuses`、
  `search-users` の代わりに `typeahead` を使う。認証情報付きのセルフホストで復旧する。
  本クライアントは空レスポンスを既定2回リトライする。
- **`count` はあくまでヒント。** 実際のページサイズは上流が決める。件数制御は
  `--max-items` で行う。
- **削除・非公開・凍結された投稿** はエラーではなく `tombstone` オブジェクトで返る。
- レート制限：IPあたり1000リクエスト/分。

## ディレクトリ構成

skill本体は `skills/` 配下に置いてある。将来的に複数skillを同一リポジトリで扱えるようにするためと、
Claude Codeのプラグイン規約（`skills/<name>/SKILL.md`）にそのまま乗るため。
パッケージ済み `.skill` に必要なものはすべて `skills/fxtwitter/` の中で完結している。

```
README.md, README.ja.md, LICENSE     リポジトリレベルのドキュメントとライセンス
skills/
  fxtwitter/
    SKILL.md                     Skill発火時にClaudeが読む指示
    LICENSE                      .skill単体配布時のための複製
    scripts/fxtwitter.py         CLI本体（標準ライブラリのみ）
    scripts/smoke_test.py        APIとクライアントの整合を確認するライブテスト
    references/endpoints.md      全エンドポイント・全パラメータ・既定値・上限
    references/schemas.md        全レスポンスオブジェクトのフィールド定義
    references/recipes.md        ワークフロー、検索構文、トラブルシュート
    references/url-modifiers.md  埋め込み側の d./g./m./t./i./o. 修飾子
```

`SKILL.md` 内のパスはskillディレクトリからの相対なので、リポジトリをどこに
チェックアウトしても影響を受けない。

## テスト

```bash
cd skills/fxtwitter
python3 scripts/smoke_test.py            # 実APIに約15リクエスト
python3 scripts/smoke_test.py --offline  # パース・整形のみ
```

## パッケージング

```bash
python3 -m scripts.package_skill skills/fxtwitter dist/
```

Anthropicの `skill-creator` 同梱パッケージャを使う場合は上記。手動なら
`skills/fxtwitter` を、アーカイブ内のトップ階層が `fxtwitter/` になるようzipし、
拡張子を `.skill` にリネームすればよい。

## ライセンス

MIT — [LICENSE](LICENSE) を参照。

本リポジトリは独立したクライアント実装であり、FxEmbedプロジェクト、X Corp.、
Anthropicのいずれとも提携・承認関係にない。
[FxEmbed](https://github.com/FxEmbed/FxEmbed) は別のMITライセンスプロジェクトであり、
[レート制限](https://docs.fxembed.com/api/introduction/)を尊重し、
大量利用時はセルフホストを検討すること。APIが返すのは実在する人物の公開情報である
点にも留意すること。

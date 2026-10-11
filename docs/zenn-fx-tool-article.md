---
title: "FastAPI + Next.js で FX 分析基盤を作った話 — BFF・ペーパー取引・OpenAI を叩かないテスト"
emoji: "📈"
type: "tech"
topics: ["python", "fastapi", "nextjs", "typescript", "fx"]
published: false
---

個人で動かしていた FX のテクニカル／ファンダメンタル分析ツールが、いつの間にか「チャートを見る」「指標を出す」「注文する」「テナントで分ける」まで伸びました。

この記事は `C:\devlop\fx` 相当の構成を、**実装判断のメモ**としてまとめたものです。売買の推奨ではありません。未設定のブローカーはペーパー取引に落ち、経済指標キーが無いときはサンプル系列を使います。

# 何を置いているか

スタックは次の通りです。

| 層 | 技術 |
|---|---|
| API | Python 3.12 / FastAPI / pandas / scikit-learn |
| UI | Next.js / React / TypeScript |
| DB | PostgreSQL 16（ホストは **5433**。5432 は空けておく） |
| 任意 | OpenAI、OANDA v20、FRED、TradingView Webhook |

画面の主な入口は次です。

- `/` — テクニカル指標（SMA/EMA、ボリンジャー、MACD、RSI、ストキャス、一目）
- `/fundamental` — 雇用統計・CPI・FOMC・日銀・GDP・カレンダー
- `/analysis` — トレンド／ニュース／SNS／経済／ボラティリティの統合
- `/dashboard` — チャート・ニュース・バックテスト・注文の一気通貫
- `/pro` — シグナル、市場ブリーフ、コーチング、ウォークフォワード、リスク
- `/ai` — OpenAI を使う総合レポート（キーが無いときはその経路だけスキップ）

API は Spring Boot ではなく FastAPI です。REST と BFF を同じプロセスに寄せています。

# 同一オリジンに閉じる

ブラウザから FastAPI へ直叩きすると、CORS・認証ヘッダー・タイムアウトが画面ごとに散らかります。とくに AI 分析は最大 120 秒かかります。

そこで Next.js の Route Handler を BFF にしています。`/api/ai/**` はフロントから見て同一オリジンで、中で FastAPI へ転送します。

```ts
const INTERNAL_API =
  process.env.INTERNAL_API_URL ||
  (process.env.NODE_ENV === "production" ? "http://127.0.0.1:8000" : "http://localhost:8000");

const AI_TIMEOUT_MS = 120_000;

async function proxyToBackend(request: NextRequest, path: string[]) {
  const target = `${INTERNAL_API}/api/ai/${path.join("/")}${request.nextUrl.search}`;
  const res = await fetch(target, {
    method: request.method,
    headers: forwardHeaders(request),
    cache: "no-store",
    signal: AbortSignal.timeout(AI_TIMEOUT_MS),
  });
  // ステータスと Content-Type はそのまま返す
}
```

転送するヘッダーは `Authorization`（JWT）、`X-API-Key`、必要なときの `cookie` だけです。全部を透過すると、内部向けヘッダーまで漏れます。

タイムアウトは 504、バックエンド未起動は 502 にして、画面には日本語の `detail` を返します。「Failed to fetch」だけ出して終わり、にはしません。

Railway ではフロントと API を同一サービスに載せ、`INTERNAL_API_URL` でループバックします。`NEXT_PUBLIC_API_URL` は空のままでよく、公開オリジンは一つです。

# テナントとペーパー取引

SaaS モード（`SAAS_ENABLED=true`）では、登録時にテナントが作られ、JWT または `X-API-Key: fx_...` で切ります。注文と TradingView シグナルは `tenant_id` で分けます。

プランは Free / Pro / Enterprise で、日次 API 上限と機能ゲートがあります。OANDA は Pro 以上です。課金の Webhook は任意で、未接続ならプラン変更はデモです。

ブローカーは最初から「無い」を正常系にしています。

- `OANDA_API_TOKEN` が無い → ペーパー注文として DB に残す
- OANDA が一時失敗 → 市場データの終値で補完する
- 扱えない銘柄を live で送る → 400 相当で止める

売りは OANDA の仕様どおり units を負数にします。トークンが無い状態で「発注できた」ように見せるのは危険なので、レスポンスに `broker: paper` と理由を載せます。

TradingView は Pine の `alert()` を Webhook で受けます。SaaS 時は `X-API-Key` でテナントを特定し、設定されていれば自動売買をバックグラウンドで走らせます。シークレット未設定の公開 URL は、誰でもシグナルを投げられる点に注意してください。

# 予測と「最適」を分けておく

テクニカルの横に RandomForest の価格予測と ATR/EWMA のボラティリティ予測があります。これは**学習データ上の当てはめ**であり、明日の確定値ではありません。

堅牢性はウォークフォワード（インサンプル／アウトオブサンプル）で見ます。`/api/pro/backtest/{symbol}` は単純バックテスト、Backtrader（RSI+MACD）、ウォークフォワードを並べます。格子を走査し切っていない解を「最適」とは書いていません。打ち切りは候補です。

ファンダメンタルは FRED が取れれば実データ、キーが無ければサンプルです。画面に出すときは、サンプル系列を実経済の確定値と書かないようにしています。

# フロントのテストでは OpenAI を叩かない

ダッシュボードはマウント直後に複数 API を呼びます。モック前に `render` すると、テストが実バックエンドや OpenAI に落ちます。

Vitest + Testing Library では順序を固定しています。

```
1. mockApis()          … マウント時の API をすべて spy
2. そのケースだけ vi.spyOn で上書き
3. render
4. waitReady()         … 見出しやセレクトが出るまで待つ
5. 操作
6. waitFor
```

禁止していることは次です。

- 実 HTTP / 実 OpenAI / 実ブローカー
- テスト内での `new OpenAI` や本番 URL
- 巨大な JSON をテストファイルに複製する（`fixtures.ts` を使う）

AI ダッシュボードのテストは「OpenAI を叩かない」ことが完了条件です。CI で課金もフレークも増やしたくない、というだけです。

# 起動

Python は 3.12 です。3.14 は TensorFlow / scikit-learn の都合で外しています。

```bash
docker compose up -d
# PostgreSQL → localhost:5433
# DynamoDB Local → localhost:8001（本番 Railway では未使用）
```

```bash
cd backend
py -3.12 -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env
python run.py
# API http://localhost:8000/docs
```

```bash
cd frontend
npm install
npm run dev
# UI http://localhost:3000
```

`.env` の要点です。

| 変数 | 意味 |
|---|---|
| `DATABASE_URL` | PostgreSQL |
| `SAAS_ENABLED` | `false` なら従来のオープン API |
| `JWT_SECRET` | 本番は長いランダム文字列 |
| `OPENAI_API_KEY` | 未設定なら AI タブだけ動かない |
| `OANDA_API_TOKEN` | 未設定ならペーパー |
| `FRED_API_KEY` | 未設定ならファンダはサンプル |

# デプロイでやったこと

リポジトリ直下に backend と frontend が並ぶと、Railpack は言語を判定できません。ルートの `Dockerfile` と `railway.toml` で、UI と `/api` を一つのサービスにまとめています。

| URL | 役割 |
|---|---|
| `/` | Next.js |
| `/api/*` | FastAPI |
| `/docs` | OpenAPI |
| `/health` | ヘルスチェック |

Postgres は Railway の `DATABASE_URL` を接続します。DynamoDB は本番では使いません。

# 作って分かったこと

1. **画面からの API は同一オリジンに寄せる。** CORS を「とりあえず `*`」にするより、BFF の方が認証とタイムアウトを一箇所に集められる。
2. **外部 API は最初から無い前提で書く。** OANDA / OpenAI / FRED が欠けても探索と表示は動かす。キーが付いたときだけ実データに切り替える。
3. **テストは課金経路を通さない。** `render` の前に mock する。順序を破ると実ネットに落ちる。
4. **予測とバックテストの言葉を分ける。** ウォークフォワードのラベルと、打ち切った候補を「最適」と呼ばない。
5. **ポートを先に決める。** このリポジトリは API 8000・画面 3000、Postgres はホスト 5433 です。他ツールとぶつからないようにする。

投資判断には使いません。現地のブローカー規約と、ペーパー／ライブの切り替えを先に確認してください。

公開前に Zenn の管理画面で `published: false` のままだと下書きです。投稿するときは `published: true` にするか、Web エディタへ本文だけ貼ってください。

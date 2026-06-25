# FX Tool

FX通貨ペアのテクニカル分析・ファンダメンタル分析ツール

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| バックエンド | Python, FastAPI, pandas, numpy, scikit-learn, TensorFlow, PyTorch, matplotlib |
| フロントエンド | TypeScript, React, Next.js, Recharts |
| データベース | PostgreSQL, DynamoDB (Local) |
| インフラ | Docker Compose |

## 機能

### テクニカル分析
- 移動平均線 (SMA / EMA)
- ボリンジャーバンド
- MACD
- RSI
- ストキャスティクス
- 一目均衡表
- トレードシグナル判定
- ML価格予測 (RandomForest)

### ファンダメンタル分析
- 米国雇用統計
- CPI（消費者物価指数）
- FOMC
- 日銀政策決定会合
- GDP
- 経済イベントカレンダー

### 統合トレードダッシュボード (`/dashboard`)
- **TradingView**: チャート埋め込み + Webhook でシグナル受信
- **ニュース分析**: ML キーワードセンチメント + OpenAI 分析
- **Backtrader**: RSI+MACD 戦略のバックテスト
- **OANDA**: 成行注文（API 未設定時はペーパー取引）
- **React ダッシュボード**: Next.js 統合 UI

### マーケット分析 (`/analysis`)
- **トレンド予測**: RandomForest + テクニカルルール + MTF 統合
- **ニュース分析**: Google News RSS + ML / OpenAI センチメント
- **SNS分析**: Reddit 投稿収集 + キーワードセンチメント
- **経済指標分析**: 雇用・CPI・FOMC・日銀・GDP のスコアリング
- **ボラティリティ予測**: ATR / EWMA + RandomForest 予測

> API 層は Spring Boot ではなく **FastAPI** で実装しています（同等の REST API / BFF 役割）。

## セットアップ

### 前提条件
- Python 3.12（3.14 は TensorFlow / scikit-learn 非対応のため 3.12 推奨）
- Node.js 20+
- Docker & Docker Compose

### 1. データベース起動

```bash
docker compose up -d
```

PostgreSQL: `localhost:5433` / DynamoDB Local: `localhost:8001`

> ポート5432が他のPostgreSQLと競合する場合があるため、5433を使用しています。

## SaaS 機能

マルチテナント対応（v2.0）:

| 機能 | 説明 |
|------|------|
| **テナント** | 組織単位のワークスペース（登録時に自動作成） |
| **認証** | JWT ログイン + API キー（`X-API-Key: fx_...`） |
| **プラン** | Free / Pro / Enterprise（日次 API 上限・機能ゲート） |
| **利用量** | テナントごとの日次 API カウント |
| **データ分離** | 注文・TradingView シグナルは `tenant_id` で分離 |

### プラン概要

| プラン | 月額 | API/日 | AI | OANDA | 統合分析 |
|--------|------|--------|-----|-------|----------|
| Free | $0 | 100 | ✗ | ✗ | ✗ |
| Pro | $49 | 2,000 | ✓ | ✓ | ✓ |
| Enterprise | $199 | 50,000 | ✓ | ✓ | ✓ |

### 認証 API

| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/api/auth/register` | 新規テナント + ユーザー登録 |
| POST | `/api/auth/login` | ログイン → JWT |
| GET | `/api/auth/me` | セッション・利用量 |
| GET/POST | `/api/auth/api-keys` | API キー管理 |
| GET | `/api/billing/plans` | プラン一覧 |
| POST | `/api/billing/upgrade` | プラン変更（デモ） |

UI: `/register` · `/login` · `/settings` · `/pricing`

TradingView Webhook（SaaS 時）: ヘッダー `X-API-Key` でテナントを特定

### 2. バックエンド

```bash
cd backend
py -3.12 -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
cp ../.env.example ../.env
python run.py
```

API: http://localhost:8000
API Docs: http://localhost:8000/docs

### 3. フロントエンド

```bash
cd frontend
npm install
npm run dev
```

UI: http://localhost:3000

## 環境変数

`.env.example` を `.env` にコピーして設定してください。

| 変数 | 説明 |
|------|------|
| `DATABASE_URL` | PostgreSQL接続文字列 |
| `SAAS_ENABLED` | SaaS モード（`false` で従来のオープン API） |
| `JWT_SECRET` | JWT 署名キー（本番必須・長いランダム文字列） |
| `JWT_EXPIRE_HOURS` | トークン有効時間（既定 72） |
| `NEXT_PUBLIC_SAAS_ENABLED` | フロントのログイン必須（`false` で UI もオープン） |
| `STRIPE_WEBHOOK_SECRET` | Stripe Webhook 署名（任意） |
| `DYNAMODB_ENDPOINT` | DynamoDB Local エンドポイント |
| `FRED_API_KEY` | FRED APIキー（ファンダメンタルデータ取得用、任意） |
| `OPENAI_API_KEY` | OpenAI APIキー（ニュース・AI分析用、任意） |
| `OANDA_API_TOKEN` | OANDA v20 API トークン（任意） |
| `OANDA_ACCOUNT_ID` | OANDA 口座 ID（任意） |
| `OANDA_ENVIRONMENT` | `practice` または `live` |
| `TRADINGVIEW_WEBHOOK_SECRET` | TradingView Webhook 認証用（任意） |

FRED APIキーは https://fred.stlouisfed.org/docs/api/api_key.html から無料取得できます。未設定時はサンプルデータが使用されます。

## API エンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/api/symbols` | 通貨ペア一覧 |
| GET | `/api/ohlcv/{symbol}` | OHLCVデータ |
| POST | `/api/data/sync/{symbol}` | Yahoo Finance → DB 同期 |
| GET | `/api/chart/{symbol}` | matplotlib チャート画像 (PNG) |
| GET | `/api/technical/{symbol}` | テクニカル分析（全指標） |
| GET | `/api/technical/{symbol}/signals` | トレードシグナル |
| GET | `/api/fundamental` | ファンダメンタルデータ |
| GET | `/api/fundamental/calendar` | 経済イベントカレンダー |
| GET | `/api/ml/predict/{symbol}` | ML価格予測 |
| POST | `/api/tradingview/webhook` | TradingView アラート Webhook |
| GET | `/api/tradingview/signals` | 受信シグナル一覧 |
| GET | `/api/news/analysis/{symbol}` | ML + OpenAI ニュース分析 |
| GET | `/api/backtest/backtrader/{symbol}` | Backtrader バックテスト |
| GET | `/api/oanda/status` | OANDA 口座状態 |
| GET/POST | `/api/oanda/orders` | 注文一覧 / 成行注文 |
| GET | `/api/dashboard` | 統合ダッシュボード BFF |
| GET | `/api/analysis/trend/{symbol}` | トレンド予測 |
| GET | `/api/analysis/news/{symbol}` | ニュース分析 |
| GET | `/api/analysis/sns/{symbol}` | SNS（Reddit）分析 |
| GET | `/api/analysis/economic/{symbol}` | 経済指標分析 |
| GET | `/api/analysis/volatility/{symbol}` | ボラティリティ予測 |
| GET | `/api/analysis/intelligence/{symbol}` | 5大分析 統合レポート |

## プロジェクト構成

```
fx/
├── backend/
│   ├── src/
│   │   ├── analysis/       # テクニカル・ファンダメンタル分析
│   │   ├── api/            # ダッシュボード BFF
│   │   ├── backtest/       # Backtrader
│   │   ├── broker/         # OANDA 注文
│   │   ├── tradingview/    # Webhook シグナル
│   ├── pine/               # Pine Script サンプル
│   ├── src/
│   │   ├── data/           # サンプルデータ生成
│   │   ├── db/             # PostgreSQL + DynamoDB
│   │   ├── ml/             # 機械学習モデル
│   │   └── main.py         # FastAPI アプリ
│   ├── db/init.sql         # PostgreSQL スキーマ
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── app/            # Next.js ページ
│       ├── components/     # React コンポーネント
│       ├── lib/            # API クライアント
│       └── types/          # TypeScript 型定義
├── docker-compose.yml
├── Dockerfile              # Railway バックエンド用（リポジトリルート）
├── Dockerfile.frontend     # Railway フロントエンド用（リポジトリルート）
├── railway.toml            # Railway バックエンド設定
└── .env.example
```

## Railway デプロイ

単一サービスでフロントエンド + バックエンドを配信します（ルート `Dockerfile`）。

| URL | 内容 |
|-----|------|
| `/` | FX Tool UI（Next.js） |
| `/api/*` | REST API（FastAPI） |
| `/docs` | API ドキュメント |
| `/health` | ヘルスチェック |

### 環境変数

| 変数 | 値 |
|------|-----|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `OPENAI_API_KEY` | Railway に登録した OpenAI API キー |
| `OPENAI_MODEL` | `gpt-4o-mini`（任意） |
| `JWT_SECRET` | 本番必須（Railway Secrets） |
| `SAAS_ENABLED` | `true`（SaaS モード） |
| `NEXT_PUBLIC_SAAS_ENABLED` | `true` |
| `OANDA_API_TOKEN` | OANDA practice/live トークン（任意） |
| `OANDA_ACCOUNT_ID` | OANDA 口座 ID（任意） |
| `TRADINGVIEW_WEBHOOK_SECRET` | Webhook 認証（任意） |

> DynamoDB は未使用（インメモリキャッシュ）。`NEXT_PUBLIC_API_URL` は未設定で OK（同一オリジン）。

### AI 分析機能（OpenAI）

| エンドポイント | 機能 |
|---|---|
| `GET /api/ai/news/{symbol}` | ニュース収集・センチメント分析 |
| `GET /api/ai/fundamental-analysis/{symbol}` | 経済指標 AI 分析 |
| `GET /api/ai/trading-decision/{symbol}` | 売買判断 |
| `GET /api/ai/risk/{symbol}` | リスク管理 |
| `GET /api/ai/report/{symbol}` | 総合レポート |

UI: `/ai` · 統合ダッシュボード: `/dashboard`

### TradingView 連携

1. `backend/pine/fx_webhook_strategy.pine` を TradingView に貼り付け
2. アラート作成 → Webhook URL: `https://<your-host>/api/tradingview/webhook`
3. メッセージに JSON（Pine 内の `alert()` 参照）
4. `TRADINGVIEW_WEBHOOK_SECRET` 設定時はヘッダー `X-Webhook-Secret` または JSON の `secret` を送信

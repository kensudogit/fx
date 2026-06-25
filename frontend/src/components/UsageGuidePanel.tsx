'use client'

/**
 * 画面右下のドラッグ可能な利用手順パネル（localStorage で位置・開閉を保存）。
 * FX専門家向けプレゼン — アーキテクチャ概要・分析ワークフローを表示。
 */
import { useCallback, useEffect, useRef, useState } from 'react'

const STORAGE_KEY = 'fx-tool-usage-guide-v3'
const PANEL_WIDTH = 440

type GuideStep = {
  title: string
  body: string
  items?: readonly string[]
}

type FeaturedBlock = {
  badge: string
  title: string
  body: string
  items?: readonly string[]
  variant?: 'architecture' | 'ai' | 'technical' | 'fundamental' | 'analysis' | 'dashboard' | 'pro' | 'saas' | 'devtools' | 'default'
}

const architectureFeatured: FeaturedBlock = {
  badge: 'Architecture',
  title: 'Next.js BFF + FastAPI 分析エンジン',
  body:
    'フロントは同一オリジンで FastAPI にプロキシ。OHLCV は Yahoo Finance 取得 → PostgreSQL 永続化。AI 機能は OpenAI API をバックエンド経由で呼び出し、API キーをクライアントに露出しません。',
  variant: 'architecture',
  items: [
    'Next.js — テクニカル / ファンダ / 分析 / AI / Pro / ダッシュボード / 自動取引',
    'FastAPI :8000 — 指標計算 · ML · OpenAI · SaaS 認証',
    'PostgreSQL — OHLCV · テナント · 注文 · チャット履歴',
    'SaaS — JWT ログイン · プラン制 · API キー · 利用量トラッキング',
    '/health — 生存確認 · /docs — Swagger API リファレンス',
  ],
}

const technicalFeatured: FeaturedBlock = {
  badge: 'Technical',
  title: 'テクニカル分析画面（/）の操作',
  body:
    '画面上部のコントロールで通貨ペア・期間を選び、チャートタブと右側のシグナルパネルで売買判断の材料を確認します。初回やデータが古い場合は必ず「データ同期」を実行してください。',
  variant: 'technical',
  items: [
    '通貨ペア — 画面上部のドロップダウン（USDJPY / EURUSD / GBPUSD 等）',
    '期間 — 90日 / 200日 / 365日（ローソク足の本数。中期トレンドは 200 日推奨）',
    'データ同期 — Yahoo Finance から最新 OHLCV を取得し DB に保存 → チャート再描画',
    'チャート画像 — 別タブで静的チャートを開く（プレゼン資料用）',
    'サマリー — 終値 · RSI(14) · MACD · ML予測価格 · モデル精度(R²)',
    'シグナルパネル — 各指標の買い/売りと総合判断（買い優勢 / 売り優勢 / 中立）',
  ],
}

const fundamentalFeatured: FeaturedBlock = {
  badge: 'Fundamental',
  title: 'ファンダメンタル分析画面（/fundamental）',
  body:
    '左カラムで主要指標の履歴を、右カラムで今後のイベントカレンダーを確認します。発表前後のボラティリティ想定や、AI 分析の前提知識として活用します。',
  variant: 'fundamental',
  items: [
    '経済指標タブ — 米国雇用統計 · CPI · FOMC · 日銀政策決定会合 · GDP',
    '指標テーブル — 日付 / 実績 / 予想 / 前回 / 単位（FRED API またはサンプル）',
    'イベントカレンダー — 日付 / イベント名 / 国 / 影響度（高・中）',
    '発表前 — 予想と前回の乖離を確認し、サプライズの方向を想定',
    '発表後 — 実績が予想を上回るか下回るかで通貨の方向性を判断',
  ],
}

const aiFeatured: FeaturedBlock = {
  badge: 'AI Analysis',
  title: 'OpenAI 統合 — ニュース〜リスクまで一気通貫（/ai）',
  body:
    'テクニカル指標とファンダメンタルデータをコンテキストに、OpenAI がニュース要約・売買判断・ポジションサイズを提案。ステータスバッジで API キー接続を確認してから実行。',
  variant: 'ai',
  items: [
    'ニュース収集 — RSS + AI センチメント（強気 / 弱気 / 中立）',
    'ファンダ AI — 雇用統計 · CPI · FOMC · 日銀 · GDP の影響評価',
    '売買判断 — buy / sell / hold + 根拠・信頼度',
    'リスク管理 — 口座残高から推奨ロット・損切り幅を算出',
    '統合レポート — 上記を 1 リクエストでまとめて取得',
  ],
}

const analysisFeatured: FeaturedBlock = {
  badge: 'Market Analysis',
  title: 'マーケット分析（/analysis）— 5 カテゴリ統合',
  body:
    'トレンド予測・ニュース・SNS・経済指標・ボラティリティをタブで切り替え。「総合」タブでは複合スコア（-100〜100）で方向感を一覧できます。',
  variant: 'analysis',
  items: [
    '総合 — 5分析の複合スコアと強気/弱気/中立の見通し',
    'トレンド予測 — RandomForest + テクニカルルール + MTF',
    'ニュース — Google News RSS + ML / OpenAI センチメント',
    'SNS — Reddit 投稿のセンチメント・エンゲージメント',
    '経済指標 — 雇用・CPI・FOMC 等のスコアリング',
    'ボラ予測 — ATR 現状と将来ボラのレジーム判定',
  ],
}

const dashboardFeatured: FeaturedBlock = {
  badge: 'Dashboard',
  title: '統合ダッシュボード（/dashboard）',
  body:
    'TradingView チャート・Webhook シグナル・ニュース ML・Backtrader・OANDA 注文を 1 画面に集約。実運用のコックピットとして利用します。自動約定は /autotrade で設定します。',
  variant: 'dashboard',
  items: [
    'TradingView — チャート埋め込み + Webhook でシグナル受信',
    'Webhook URL — /api/tradingview/webhook（X-API-Key ヘッダー）',
    'ニュース ML — ヘッドラインとセンチメントスコア',
    'Backtrader — RSI+MACD 戦略のバックテスト結果',
    'OANDA — 成行注文（未設定時はペーパー取引）',
    '自動取引 — /autotrade でマルチシグナル統合・自動約定を設定',
  ],
}

const autotradeFeatured: FeaturedBlock = {
  badge: 'Auto Trade',
  title: '自動取引エンジン（/autotrade）',
  body:
    'トライオートFX同様 — プリセット選択 · オートセレクト · 運用前シミュレーション · SL/TP 自動決済に対応。AI・テクニカル・統合分析を融合し OANDA / ペーパーで約定。Pro プラン以上。',
  variant: 'dashboard',
  items: [
    'セレクト — 5 種プリセット（安定型 / バランス / 積極 / レンジリピート / トレンド）',
    'オートセレクト — 運用資金 · 期間 · リスクの 3 問で最適プリセットを提案',
    'シミュレーション — 365 日 BT + 推奨/安全証拠金 + 運用可否（A〜D 評価）',
    'SL/TP — ATR ベースの損切り/利確を自動設定 · 逆シグナルで決済',
    'ドライラン — 評価のみ実行（ready / blocked / skipped）',
    'スケジューラ — 15 分間隔の自動サイクル · TradingView Webhook 即時実行',
    '最小 1,000 units — オープンポジション · 運用パフォーマンスを画面表示',
  ],
}

const aiProFeatured: FeaturedBlock = {
  badge: 'AI Pro',
  title: '差別化機能（/pro）— 7 つの AI 機能',
  body:
    'AI 売買シグナル・市場ブリーフ・コーチング・ウォークフォワード・高度リスク管理・口座一元管理・投資相談チャットを提供。差別化の核となる画面です。',
  variant: 'pro',
  items: [
    'AIシグナル — テクニカル + ML + OpenAI の統合売買方向',
    '市場ブリーフ — ニュース・SNS・経済指標の要約と市場影響',
    'AIコーチング — 売買履歴から改善提案（履歴が多いほど精度向上）',
    'バックテスト — 簡易BT + Backtrader + ウォークフォワード分析',
    'リスク管理 — 最大DD・資金配分・損切り/利確提案',
    '口座・通貨 — 複数口座と 4 通貨ペアの一元管理',
    'AIチャット — 投資相談（セッション履歴付き）',
  ],
}

const saasFeatured: FeaturedBlock = {
  badge: 'SaaS',
  title: 'アカウント・プラン・API キー',
  body:
    'マルチテナント対応。組織（テナント）単位でデータが分離され、プランに応じて日次 API 上限と機能が変わります。',
  variant: 'saas',
  items: [
    '新規登録 — /register で組織名・メール・パスワードを設定',
    'ログイン — /login → JWT が自動付与（未ログインはリダイレクト）',
    '設定 — /settings でプラン変更・利用量・API キー発行',
    '料金 — /pricing で Free / Pro / Enterprise を確認',
    'API キー — TradingView Webhook 等に X-API-Key ヘッダーで利用',
  ],
}

const claudeCodeFeatured: FeaturedBlock = {
  badge: 'Claude Code',
  title: 'Cursor から Claude Code へ移植',
  body:
    'コード自体の書き換えは不要。同じ Git リポジトリを Claude Code で開き、CLAUDE.md にプロジェクト文脈を書くことで Cursor と同等の開発支援が可能です。CLI · VS Code/Cursor 拡張 · Desktop で共通の設定が使えます。',
  variant: 'devtools',
  items: [
    'インストール — PowerShell: irm https://claude.ai/install.ps1 | iex',
    '起動 — cd fx && claude（初回は Anthropic アカウントでログイン）',
    '記憶 — /init で CLAUDE.md 自動生成 → FX Tool 固有の追記',
    '確認 — /memory で読み込みファイル一覧を表示',
    'Cursor 併用 — 拡張機能「Claude Code」を入れれば同じ IDE 内で利用可能',
  ],
}

const techStack = [
  'Python · FastAPI',
  'Next.js 15 · Recharts',
  'PostgreSQL · SaaS',
  'OpenAI gpt-4o-mini',
  'Backtrader · scikit-learn',
  'OANDA · TradingView',
  'Auto Trade Engine',
  'Yahoo Finance · Railway',
] as const

const archDiagram = `Browser (FX Expert)
    │ HTTPS + JWT / API Key
    ▼
Next.js :PORT (Railway)
    ├─ /              テクニカル分析
    ├─ /fundamental   経済指標カレンダー
    ├─ /analysis      マーケット分析（5カテゴリ）
    ├─ /ai            OpenAI 統合分析
    ├─ /pro           AI Pro（差別化7機能）
    ├─ /dashboard     統合ダッシュボード
    ├─ /autotrade     自動取引エンジン
    ├─ /login · /register · /settings
    └─ /api/* ──proxy──► FastAPI :8000
              ├─ Yahoo Finance (OHLCV)
              ├─ PostgreSQL (tenant · orders · chat)
              └─ OpenAI API (signals · brief · chat)`

type GuideSection = {
  label: string
  steps: readonly GuideStep[]
}

const guideSections: readonly GuideSection[] = [
  {
    label: 'クイックスタート',
    steps: [
      {
        title: 'パネル操作・画面遷移',
        body: '本パネルは全画面で表示されます。PC ではヘッダーをドラッグして位置を変更でき、▼▲ で折りたたみ可能です。スマホでは画面下部のボトムシートとして表示されます。',
        items: [
          'PC — ヘッダーをドラッグで移動 · ▼▲ で開閉 · 位置はブラウザに自動保存',
          'スマホ — 右上 ≡ でメニュー · 本パネルは画面下部（初期は折りたたみ）',
          '画面上部ナビ — テクニカル / ファンダ / マーケット分析 / AI / AI Pro / ダッシュボード / 自動取引 / 料金 / 設定',
          '推奨フロー — 登録 → テクニカル → 分析 → AI Pro → ダッシュボード → 自動取引',
          'プレゼン時 — パネルを画面端に寄せ、メイン画面を広く使う',
        ],
      },
      {
        title: '接続確認（最初に）',
        body: '本番・ローカル共通。障害切り分けとプレゼン前チェックの起点です。',
        items: [
          '本番 URL: https://fx-production-f5d5.up.railway.app/',
          '/health — Web + API 生存確認（200 OK）',
          '/register — 初回はアカウント作成（組織名 = テナント）',
          'AI分析画面 — 「接続準備完了」で OpenAI キー設定を確認',
          'Swagger: /docs — 全エンドポイント一覧・試験呼び出し',
        ],
      },
      {
        title: '初回セットアップ（5 分）',
        body: '初めて使う場合、またはチャートが空の場合の最短手順です。',
        items: [
          '① /register でアカウント作成 → ログイン',
          '② テクニカル分析 — USDJPY · 200日 · データ同期',
          '③ /analysis でマーケット分析「総合」タブを確認',
          '④ /pro で AIシグナル・市場ブリーフを実行',
          '⑤ /dashboard で TradingView + Backtrader を確認',
          '⑥ /settings で API キー発行（Webhook 連携用）',
          '⑦ /autotrade — オートセレクト or プリセット → シミュレーション → ドライラン → 有効化',
        ],
      },
    ],
  },
  {
    label: 'テクニカル分析 詳細',
    steps: [
      {
        title: 'チャートタブの使い分け',
        body: 'メインチャート下部の 6 タブを切り替えて、局面に応じた指標を確認します。',
        items: [
          '価格 + MA — 5 / 25 / 75 日移動平均線。トレンド方向とクロスを確認',
          'ボリンジャーバンド — 中心線 ±2σ。バンド幅の収縮（スクイーズ）後のブレイクに注目',
          '一目均衡表 — 雲の厚み・価格と雲の位置関係。転換線と基準線のクロス',
          'RSI — 0〜100 のオシレーター。70 超=過熱、30 未満=売られすぎ',
          'MACD — MACD 線とシグナル線のクロス、ヒストグラムのゼロライン突破',
          'ストキャスティクス — %K / %D。80 超・20 未満とクロスでタイミング判断',
        ],
      },
      {
        title: 'シグナルパネルの読み方',
        body: 'チャート右側「トレードシグナル」カードで、各指標の判定理由を確認できます。',
        items: [
          '現在価格 — 直近終値（シグナル算出の基準価格）',
          '総合判断 — 買いシグナル数 vs 売りシグナル数で「買い優勢 / 売り優勢 / 中立」',
          '個別シグナル — 指標名 · 買い/売りバッジ · 数値 · 判定理由テキスト',
          '使い方 — 単一指標より複数指標の一致（コンフルエンス）を重視',
          '注意 — レンジ相場ではシグナルが頻繁に反転するため、ファンダと併用',
        ],
      },
      {
        title: 'ML 予測の見方',
        body: 'RandomForest による翌営業日の価格方向の参考値です。最終判断の補助として使用してください。',
        items: [
          'ML予測価格 — サマリー欄に表示（status=success の場合のみ）',
          'モデル精度 (R²) — 1 に近いほど学習データへの適合度が高い',
          'データ不足時 — 先に「データ同期」を実行（最低 90 日分推奨）',
          '位置づけ — テクニカル・ファンダ・AI と合わせた「第 4 の視点」として説明',
        ],
      },
    ],
  },
  {
    label: 'ファンダメンタル 詳細',
    steps: [
      {
        title: '経済指標タブ別の確認ポイント',
        body: '左カラムのタブで指標種別を切り替え、実績と予想の乖離を確認します。',
        items: [
          '米国雇用統計 — 非農業部門雇用者数。ドル全体の方向感に直結',
          'CPI — インフレ指標。利下げ/利上げ観測とドル円に影響',
          'FOMC — 金利政策・声明文。ドル流動性とリスクオン/オフの転換点',
          '日銀政策決定会合 — 円金利・介入観測。USDJPY の決済通貨側分析に必須',
          'GDP — 成長率の加速/減速。中期的な通貨強弱の背景材料',
        ],
      },
      {
        title: 'イベントカレンダーの活用法',
        body: '右カラムで今後の重要イベントを日付順に確認し、ポジション保有時のリスク管理に使います。',
        items: [
          '影響度「高」— 発表前後 30 分はスプレッド拡大・スリッページに注意',
          '複数イベント同日 — ボラティリティが重なる日はロット縮小を検討',
          'AI 分析前 — 直近の高影響イベントを把握してから統合レポートを実行',
        ],
      },
    ],
  },
  {
    label: 'AI 分析 詳細',
    steps: [
      {
        title: 'AI 分析画面の基本操作（/ai）',
        body: '画面上部で通貨ペアと口座残高を設定し、タブごとに「AI分析を実行」で結果を取得します。',
        items: [
          '通貨ペア — テクニカル画面と同じドロップダウン',
          '口座残高（USD）— リスク管理・総合レポートタブで使用（デフォルト 10,000）',
          'ステータスバッジ —「接続準備完了」/「OPENAI_API_KEY が未設定です」',
          '分析時間 — 通常 30 秒〜1 分（統合レポートは最長）',
        ],
      },
      {
        title: 'タブ別 — 表示内容と読み方',
        body: '5 つのタブそれぞれの出力項目と、プレゼンでの説明ポイントです。',
        items: [
          '総合レポート — 売買判断 + ニュース + ファンダ AI + リスクを一画面表示（推奨）',
          'ニュース収集 — センチメント（強気/弱気/中立）· スコア · 要約 · 記事リンク一覧',
          '経済指標分析 — ペアバイアス · 信頼度% · 基軸/決済通貨分析 · 主要指標テーブル',
          '売買判断 — 買い/売り/様子見 · 信頼度 · エントリー/利確/損切り · RR比 · 根拠文',
          'リスク管理 — リスクレベル · 推奨ポジション% · 最大損失 · 推奨/回避条件リスト',
        ],
      },
      {
        title: '推奨デモフロー（プレゼン 10 分）',
        body: 'FX 専門家向けの実演順序。口座残高は実際の運用イメージに合わせて変更してください。',
        items: [
          '① /ai を開き、USDJPY · 口座残高 10,000 USD を設定',
          '②「総合レポート」タブを選択 →「AI分析を実行」',
          '③ 売買判断カード — 判断・信頼度・エントリー/利確/損切りを説明',
          '④ ニュース要約 — センチメントとキートピックで市場心理を補足',
          '⑤ リスク管理 — 推奨ポジションサイズと「避けるべき条件」を強調',
          '⑥ Q&A — ML/AI は補助。最終判断はトレーダーの責任である旨を明記',
        ],
      },
    ],
  },
  {
    label: 'AI Pro 詳細',
    steps: [
      {
        title: 'AI Pro 画面の基本操作（/pro）',
        body: '7 つの差別化機能をタブで切り替え。通貨ペアを選び「実行」で分析を開始します。',
        items: [
          'AIシグナル — 買い/売り/様子見 + 信頼度% + テクニカル根拠一覧',
          '市場ブリーフ — ニュース・SNS・経済指標の統合要約（OpenAI）',
          'AIコーチング — 過去の注文履歴から改善アドバイス',
          'バックテスト — 簡易BT · Backtrader · ウォークフォワード（IS/OOS比較）',
          'リスク管理 — 最大DD · 推奨ロット · 損切り/利確 · 通貨別資金配分',
          '口座・通貨 — 複数口座と全通貨ペアの残高・価格・注文数',
          'AIチャット — 投資相談（Enter で送信、履歴はセッション保存）',
        ],
      },
      {
        title: 'ウォークフォワードの読み方',
        body: 'バックテストタブ内のウォークフォワードは、過学習を検出するための OOS 検証です。',
        items: [
          'IS（In-Sample）— 学習期間の勝率',
          'OOS（Out-of-Sample）— 未知期間の勝率（こちらが重要）',
          '堅牢 — IS/OOS 乖離が小さく OOS 勝率 45% 以上',
          '弱い — 乖離大 → 戦略の過学習の可能性、パラメータ見直し',
        ],
      },
    ],
  },
  {
    label: '自動取引 詳細',
    steps: [
      {
        title: 'トライオートFX 相当機能の概要',
        body:
          'セレクト（プリセット）→ オートセレクト（3 問）→ シミュレーション → ドライラン → 有効化の順が推奨。Pro プラン以上 · OANDA 未設定時はペーパー取引。',
        items: [
          'セレクト — 安定型 / バランス / 積極 / レンジリピート / トレンドから 1 つ選択',
          'オートセレクト — 資金規模 · 運用期間 · リスク許容度で自動提案',
          'シミュレーション — 勝率 · 推奨証拠金 · 安全証拠金 · 運用可否を確認',
          'SL/TP — 損切り/利確を自動設定 · 逆シグナル決済 ON/OFF',
          '運用パフォーマンス — 約定率 · ブロック理由 · 週 1 回メンテヒント',
        ],
      },
      {
        title: 'セレクト — プリセット戦略',
        body: '用意されたルールから選ぶだけで設定が反映されます（トライオートFX セレクト相当）。',
        items: [
          '安定型 — 信頼度 75% · 低リスク 0.5% · MTF 一致必須（初心者向け）',
          'バランス型 — AI + テクニカル + 統合分析 · 標準リスク 1%（デフォルト）',
          '積極型 — 信頼度 55% · 取引頻度高 · TradingView 連携含む',
          'レンジリピート型 — テクニカル中心 · レンジ相場向け · クールダウン短め',
          'トレンドフォロー型 — MTF + AI 順張り · RR 2.5',
          '適用 — カードをクリックで即保存 · 現在のプリセット名が画面上部に表示',
        ],
      },
      {
        title: 'オートセレクト（3 問）',
        body: '3 つの質問に答えるだけで最適なプリセットと口座設定を提案します。',
        items: [
          '運用資金 — 小額 ($5,000) / 中程度 ($20,000) / 大額 ($100,000)',
          '運用期間 — 短期 / 中期 / 長期（クールダウン・スケジューラ間隔が変わる）',
          'リスク許容度 — 低 → 安定型 / 標準 → バランス / 高 → 積極型',
          '「提案を見る」— 推奨理由テキストのみ表示',
          '「適用して保存」— 設定を DB に保存してすぐ運用可能',
        ],
      },
      {
        title: '運用前シミュレーション',
        body: '有効化前に過去データでバックテストし、推奨証拠金を確認します（トライオートFX シミュレーション相当）。',
        items: [
          '「シミュレーション実行」— 選択通貨 · 365 日 · 現在プリセットで BT',
          '評価 A〜D — 勝率 55%+ で A/B · 45% 未満はプリセット見直し',
          '推奨証拠金 — 連敗リスクを考慮した最低目安',
          '安全証拠金 — 推奨の 1.5 倍（余裕を持った運用向け）',
          'ready_to_deploy — true ならドライラン → 有効化へ進める',
        ],
      },
      {
        title: '自動取引画面の基本操作（/autotrade）',
        body:
          '有効化前にシミュレーションとドライランを必ず実施。オープンポジション表で SL/TP を確認できます。',
        items: [
          '前提 — Pro プラン · ログイン済み · /settings でプラン確認',
          '有効化 — 「自動取引を有効化」チェックを ON',
          '通貨ペア — 画面上部ドロップダウンで評価対象を選択',
          '対象通貨 — 設定カードのチップで監視シンボルを複数選択可能',
          '更新 — 右上「更新」で設定 · スケジューラ · ログ · パフォーマンスを再取得',
        ],
      },
      {
        title: '設定項目の意味',
        body: 'エンジン設定カードでリスクとシグナル条件を調整。変更はフォーカスアウト時に自動保存。',
        items: [
          '最低信頼度 — 融合スコアの閾値（デフォルト 65%）',
          'リスク (%) — 1 トレードあたり口座残高に対する許容損失率',
          '口座残高 — ポジションサイズ · シミュレーションの基準',
          '日次上限 · クールダウン · イベント回避 — リスクガード',
          'シグナルソース — AI / テクニカル / 統合分析 / MTF / TradingView',
          '損切り (SL) を自動設定 — ATR × 1.5 幅で OANDA / ペーパーに付与',
          '利確 (TP) を自動設定 — リスクリワード比（デフォルト 2.0）',
          '逆シグナルで自動決済 — 保有中に反対方向シグナルで決済',
          'TradingView 即時実行 — Webhook 受信時に自動約定',
        ],
      },
      {
        title: '実行フロー（推奨手順）',
        body: 'トライオートFX と同様 — シミュレーション確認後に小ロットで開始 · 週 1 回見直し。',
        items: [
          '① /autotrade — オートセレクト or プリセットを選択',
          '②「シミュレーション実行」— 勝率 · 推奨証拠金を確認',
          '③「ドライラン評価」— ready / blocked と SL/TP 価格を確認',
          '④ blocked 時 — 信頼度 · MTF · イベント回避を調整',
          '⑤「自動取引を有効化」を ON',
          '⑥ 手動実行でペーパー/OANDA practice をテスト',
          '⑦ オープンポジション · 運用パフォーマンスを週 1 回確認',
          '⑧ 本番 — OANDA live · 最小 1,000 units から開始',
        ],
      },
      {
        title: '判定結果の読み方',
        body: '評価結果カード · 実行ログ · 運用パフォーマンスで状態を把握します。',
        items: [
          'ready — リスクガード通過 · 実行可能（ドライラン）',
          'executed — 約定完了（エントリー or close 決済）',
          'blocked — 信頼度不足 · MTF 不一致 · イベント · 日次上限 · ポジション保有中',
          'skipped — hold シグナル',
          'close — SL/TP 到達 or 逆シグナル決済',
          '約定率 — パフォーマンス欄で executed / total の比率を確認',
          'メンテヒント — ブロック多発時はプリセット変更を提案',
        ],
      },
      {
        title: '環境変数（運用者向け）',
        body: 'バックエンド .env でスケジューラと OANDA 接続を制御します。',
        items: [
          'AUTOTRADE_ENABLED=true — 起動時スケジューラ有効',
          'AUTOTRADE_INTERVAL_MINUTES=15 — 定期実行間隔（分）',
          'SAAS_DEFAULT_PLAN=pro — 新規登録時のプラン（2,000 API/日）',
          'OANDA_API_TOKEN · OANDA_ACCOUNT_ID — 未設定時ペーパー取引',
          'OANDA_ENVIRONMENT=practice — 本番前は practice 推奨',
          'TRADINGVIEW_WEBHOOK + X-API-Key — SaaS 時テナント特定に必須',
        ],
      },
    ],
  },
  {
    label: 'Claude Code 移植・開発',
    steps: [
      {
        title: '移植の考え方',
        body:
          'Claude Code への「移植」はアプリコードの書き換えではなく、同じ Git リポジトリを Claude Code で開発できるように環境と文脈を移す作業です。Railway デプロイや .env はそのまま使えます。',
        items: [
          'そのまま使える — Git リポジトリ · docker compose · npm · Python venv · Railway 設定',
          '移すもの — Cursor のチャット履歴 → CLAUDE.md に要点を書く',
          'Cursor Rules → CLAUDE.md または .claude/rules/*.md',
          '移せない — 過去の Cursor セッション履歴（手動で CLAUDE.md に要約）',
        ],
      },
      {
        title: 'インストールと起動（Windows）',
        body: 'Claude Code CLI を入れ、プロジェクトルートで起動します。Git for Windows があると Bash ツールが使えます。',
        items: [
          'PowerShell — irm https://claude.ai/install.ps1 | iex',
          'または — winget install Anthropic.ClaudeCode',
          '起動 — cd fx && claude（初回は Anthropic アカウントでログイン）',
          'Cursor 拡張 — 「Claude Code」を入れ Ctrl+Shift+P → Open in New Tab',
          'Web 版 — claude.ai/code（GitHub 連携 · ローカル不要）',
        ],
      },
      {
        title: 'ローカル環境の確認（移植前）',
        body: 'Claude Code に任せる前に、ローカルで起動できることを確認しておくとスムーズです。',
        items: [
          '① docker compose up -d（PostgreSQL :5433）',
          '② copy .env.example .env → DATABASE_URL · JWT_SECRET 等を設定',
          '③ backend — py -3.12 -m venv .venv → pip install -r requirements.txt → python run.py',
          '④ frontend — npm install → npm run dev（:3000）',
          '⑤ 確認 — http://localhost:3000 · http://localhost:8000/docs',
        ],
      },
      {
        title: 'CLAUDE.md の作成（最重要）',
        body:
          'Claude Code は毎セッション最初に CLAUDE.md を読みます。Cursor で毎回説明していた内容をここに書きます。',
        items: [
          '/init — リポジトリをスキャンして CLAUDE.md のたたき台を自動生成',
          '追記 — backend(FastAPI) + frontend(Next.js) · autotrade · Railway デプロイ',
          'コマンド — docker compose · npm run build · python run.py',
          '規約 — 変更は最小限 · Python 3.12 · コミットは明示指示時のみ',
          '禁止 — .env の編集・コミット（秘密情報）',
          '/memory — 読み込み済みファイル一覧を確認',
        ],
      },
      {
        title: 'Cursor 機能との対応表',
        body: 'Cursor で使っていた機能は Claude Code 側の設定ファイルに移せます。',
        items: [
          'Cursor Rules → CLAUDE.md + .claude/rules/*.md（paths でスコープ指定）',
          'User Rules → ~/.claude/CLAUDE.md（全プロジェクト共通）',
          '個人設定 → CLAUDE.local.md（.gitignore 推奨）',
          'Skills → .claude/commands/（/deploy 等のカスタムコマンド）',
          'MCP → .claude/settings.json の mcpServers',
          '権限 — .claude/settings.json で npm run · docker compose を allow',
        ],
      },
      {
        title: '日常の使い方・試しプロンプト',
        body: '移植完了の確認と、よく使う依頼例です。',
        items: [
          '確認 —「このリポジトリの構成と autotrade の主要ファイルを説明して」',
          'ビルド —「npm run build を実行して TypeScript エラーを直して」',
          '機能追加 —「AutoTradePanel をスマホ対応にして（コミットはしない）」',
          'API —「autotrade のエンドポイント一覧を README に追記して」',
          '注意 — .env · API キーは Claude に渡さない · Railway 本番は慎重に',
        ],
      },
    ],
  },
  {
    label: 'SaaS・アカウント',
    steps: [
      {
        title: 'アカウント登録とログイン',
        body: '本番環境ではログイン必須です。未ログイン時は /login にリダイレクトされます。',
        items: [
          '/register — 組織名（テナント）・メール・パスワード（8文字以上）',
          '/login — ログイン後 JWT がブラウザに保存',
          'ログアウト — ヘッダー右上のボタン',
          'JWT_SECRET — Railway 本番で必須（長いランダム文字列）',
        ],
      },
      {
        title: 'プランと API キー（/settings）',
        body: 'Free プランでも AI 分析・マーケット分析は利用可能（日次 API 上限あり）。',
        items: [
          'Free — 100 API/日 · テクニカル · 分析 · AI · Webhook',
          'Pro — 2,000 API/日 · AI Pro · OANDA · 自動取引 · 統合インテリジェンス',
          'API キー — 設定画面で発行 → TradingView Webhook に X-API-Key',
          '利用量 — 設定画面で本日の API 消費量を確認',
        ],
      },
    ],
  },
  {
    label: 'トラブルシュート・運用',
    steps: [
      {
        title: 'よくあるエラーと対処',
        body: '画面に赤いエラーバナーが出た場合の確認手順です。',
        items: [
          'データ取得に失敗 —「データ同期」を再実行。Yahoo Finance の一時障害の可能性',
          'AI分析に失敗 — OPENAI_API_KEY の設定・残高・レート制限を確認',
          '登録 500 エラー — Railway 再デプロイ · JWT_SECRET · DB 接続を確認',
          'AI Pro プラン制限 — 403 の場合 /settings でプラン確認',
          '自動取引 403 — Pro プラン以上が必要（/autotrade）',
          'blocked が続く — 最低信頼度を下げる · MTF 必須を OFF · イベント回避時間を短縮',
          '/health が 503 — Railway 再デプロイ。DATABASE_URL を確認',
          'チャートが空 — 同期未実施、または選択期間のデータが DB に無い',
        ],
      },
      {
        title: 'API エンドポイント（開発者向け）',
        body: '/docs から Swagger UI で試験可能。バックテスト・外部連携に利用します。',
        items: [
          'GET /api/symbols — 利用可能通貨ペア一覧',
          'POST /api/data/sync/{symbol}?days=200 — 市場データ同期',
          'GET /api/analysis/intelligence/{symbol} — 5大分析統合',
          'GET /api/pro/signals/{symbol} — AI 売買シグナル',
          'GET /api/pro/market-brief/{symbol} — 市場ブリーフ',
          'POST /api/pro/chat — AI 投資相談チャット',
          'GET /api/pro/backtest/{symbol} — BT + ウォークフォワード',
          'GET/PUT /api/autotrade/config — 自動取引設定',
          'GET /api/autotrade/presets — プリセット一覧',
          'POST /api/autotrade/presets/apply — プリセット適用',
          'POST /api/autotrade/autoselect — オートセレクト（3 問）',
          'GET /api/autotrade/simulate/{symbol} — 運用前シミュレーション',
          'GET /api/autotrade/performance — 運用パフォーマンス',
          'GET /api/autotrade/positions — オープンポジション',
          'POST /api/autotrade/evaluate/{symbol} — ドライラン評価',
          'POST /api/autotrade/run/{symbol} — 手動約定',
          'GET /api/autotrade/runs — 実行ログ',
          'GET /api/ai/report/{symbol}?balance=10000 — AI 統合レポート',
          'POST /api/auth/register · /api/auth/login — SaaS 認証',
        ],
      },
      {
        title: 'Railway 本番・ローカル開発',
        body: 'デプロイとローカル起動の参考情報です。',
        items: [
          '本番 — GitHub 連携 · DATABASE_URL · OPENAI_API_KEY · JWT_SECRET',
          'SaaS — SAAS_ENABLED=true · NEXT_PUBLIC_SAAS_ENABLED=true',
          'ローカル — docker compose up -d → backend :8000 → frontend npm run dev :3000',
          '環境変数 — OPENAI_API_KEY · OPENAI_MODEL=gpt-4o-mini · OANDA_*（任意）',
          '自動取引 — AUTOTRADE_ENABLED · AUTOTRADE_INTERVAL_MINUTES',
        ],
      },
      {
        title: 'プレゼン向け 15 分シナリオ',
        body: 'FX 専門家向け推奨トークトラック（本パネルを横に開いたまま実演可能）。',
        items: [
          '0–2分: 本パネルでアーキテクチャ・SaaS・サービストポロジを説明',
          '2–5分: テクニカル — USDJPY·200日·データ同期·シグナル',
          '5–7分: /analysis — 5カテゴリ分析と総合スコア',
          '7–11分: /pro — AIシグナル・市場ブリーフ・ウォークフォワード',
          '11–13分: /dashboard — TradingView + OANDA + Backtrader',
          '13–14分: /autotrade — プリセット · シミュレーション · SL/TP · ドライラン',
          '14–15分: /ai 総合レポート · /settings APIキー · /docs',
        ],
      },
    ],
  },
]

const L = {
  title: '利用手順',
  subtitle: 'Architecture & Ops',
  dragHint: 'ドラッグで移動',
  expand: '開く',
  collapse: '閉じる',
  heroTitle: 'FX 分析プラットフォーム',
  heroLead:
    'テクニカル × ファンダメンタル × OpenAI × AI Pro。通貨ペアの多角的分析・売買判断・リスク管理を SaaS 上で提供します。',
  stackLabel: 'Tech stack',
  diagramLabel: 'Service topology',
  workflowLabel: '詳細利用手順',
  scrollHint: '↓ 画面別の詳細手順・デモフローは下へ',
  footer:
    '▼▲ で開閉 · PC はヘッダーをドラッグして移動 · スマホは画面下部のボトムシート · 表示状態は自動保存されます。',
} as const

type SavedState = {
  x: number
  y: number
  expanded: boolean
}

function defaultPosition(mobile = false) {
  if (typeof window === 'undefined') return { x: 24, y: 24 }
  if (mobile || window.innerWidth < 768) {
    return { x: 8, y: Math.max(72, window.innerHeight - 72) }
  }
  const x = Math.max(16, window.innerWidth - PANEL_WIDTH - 24)
  const y = Math.max(72, window.innerHeight - 520)
  return { x, y }
}

function clampPosition(x: number, y: number, width: number, height: number) {
  const maxX = Math.max(8, window.innerWidth - width - 8)
  const maxY = Math.max(8, window.innerHeight - height - 8)
  return {
    x: Math.min(Math.max(8, x), maxX),
    y: Math.min(Math.max(8, y), maxY),
  }
}

function FeaturedSection({ block }: { block: FeaturedBlock }) {
  const variant = block.variant ?? 'default'
  return (
    <section
      className={`usage-guide-featured usage-guide-featured--${variant}`}
      aria-label={block.title}
    >
      <div className="usage-guide-featured-head">
        <span className="usage-guide-featured-badge">{block.badge}</span>
        <strong>{block.title}</strong>
      </div>
      <p>{block.body}</p>
      {block.items?.length ? (
        <ul className="usage-guide-items">
          {block.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}

export function UsageGuidePanel() {
  const panelRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    originX: number
    originY: number
  } | null>(null)

  const [ready, setReady] = useState(false)
  const [expanded, setExpanded] = useState(true)
  const [pos, setPos] = useState({ x: 24, y: 24 })
  const [dragging, setDragging] = useState(false)
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const mobile = window.innerWidth < 768
    setIsMobile(mobile)
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as SavedState
        setPos(mobile ? defaultPosition(true) : { x: parsed.x, y: parsed.y })
        setExpanded(mobile ? false : parsed.expanded)
      } catch {
        setPos(defaultPosition(mobile))
        if (mobile) setExpanded(false)
      }
    } else {
      setPos(defaultPosition(mobile))
      if (mobile) setExpanded(false)
    }
    setReady(true)
  }, [])

  useEffect(() => {
    if (!ready) return
    const payload: SavedState = { ...pos, expanded }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
  }, [pos, expanded, ready])

  useEffect(() => {
    if (!ready) return
    const onResize = () => {
      const mobile = window.innerWidth < 768
      setIsMobile(mobile)
      if (mobile) return
      const el = panelRef.current
      if (!el) return
      setPos((current) => clampPosition(current.x, current.y, el.offsetWidth, el.offsetHeight))
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [ready])

  const onHeaderPointerDown = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (isMobile) return
      if ((e.target as HTMLElement).closest('.usage-guide-toggle')) return
      dragRef.current = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        originX: pos.x,
        originY: pos.y,
      }
      setDragging(true)
      e.currentTarget.setPointerCapture(e.pointerId)
    },
    [pos.x, pos.y, isMobile],
  )

  const onHeaderPointerMove = useCallback((e: React.PointerEvent<HTMLElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== e.pointerId) return
    const el = panelRef.current
    const width = el?.offsetWidth ?? PANEL_WIDTH
    const height = el?.offsetHeight ?? 120
    setPos(
      clampPosition(
        drag.originX + (e.clientX - drag.startX),
        drag.originY + (e.clientY - drag.startY),
        width,
        height,
      ),
    )
  }, [])

  const onHeaderPointerUp = useCallback((e: React.PointerEvent<HTMLElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== e.pointerId) return
    dragRef.current = null
    setDragging(false)
    e.currentTarget.releasePointerCapture(e.pointerId)
  }, [])

  if (!ready) return null

  return (
    <div
      ref={panelRef}
      className={`usage-guide-panel${expanded ? ' is-expanded' : ' is-collapsed'}${dragging ? ' is-dragging' : ''}${isMobile ? ' is-mobile' : ''}`}
      style={
        isMobile
          ? undefined
          : { left: pos.x, top: pos.y, width: PANEL_WIDTH }
      }
      role="dialog"
      aria-label={L.title}
      aria-modal="false"
    >
      <header
        className="usage-guide-header"
        onPointerDown={onHeaderPointerDown}
        onPointerMove={onHeaderPointerMove}
        onPointerUp={onHeaderPointerUp}
        onPointerCancel={onHeaderPointerUp}
      >
        <div className="usage-guide-header-text">
          <span className="usage-guide-drag-icon" aria-hidden>
            ☰
          </span>
          <div className="usage-guide-header-titles">
            <strong>{L.title}</strong>
            <span className="usage-guide-header-sub">{L.subtitle}</span>
          </div>
          <span className="usage-guide-drag-hint">{L.dragHint}</span>
        </div>
        <button
          type="button"
          className="usage-guide-toggle"
          aria-label={expanded ? L.collapse : L.expand}
          aria-expanded={expanded}
          onClick={() => setExpanded((open) => !open)}
        >
          {expanded ? '▼' : '▲'}
        </button>
      </header>

      {expanded ? (
        <div className="usage-guide-body">
          <div className="usage-guide-hero">
            <p className="usage-guide-hero-kicker">FX Analysis Platform</p>
            <h2 className="usage-guide-hero-title">{L.heroTitle}</h2>
            <p className="usage-guide-hero-lead">{L.heroLead}</p>
            <div className="usage-guide-stack" aria-label={L.stackLabel}>
              {techStack.map((tag) => (
                <span key={tag} className="usage-guide-stack-pill">
                  {tag}
                </span>
              ))}
            </div>
          </div>

          <FeaturedSection block={architectureFeatured} />

          <figure className="usage-guide-diagram" aria-label={L.diagramLabel}>
            <figcaption>{L.diagramLabel}</figcaption>
            <pre>{archDiagram}</pre>
          </figure>

          <FeaturedSection block={technicalFeatured} />
          <FeaturedSection block={fundamentalFeatured} />
          <FeaturedSection block={analysisFeatured} />
          <FeaturedSection block={aiFeatured} />
          <FeaturedSection block={aiProFeatured} />
          <FeaturedSection block={dashboardFeatured} />
          <FeaturedSection block={autotradeFeatured} />
          <FeaturedSection block={saasFeatured} />
          <FeaturedSection block={claudeCodeFeatured} />

          <p className="usage-guide-scroll-hint">{L.scrollHint}</p>
          <h3 className="usage-guide-workflow-title">{L.workflowLabel}</h3>
          {guideSections.map((section) => (
            <div key={section.label} className="usage-guide-section">
              <p className="usage-guide-section-label">{section.label}</p>
              <ol className="usage-guide-steps">
                {section.steps.map((step) => (
                  <li key={step.title}>
                    <strong>{step.title}</strong>
                    <p>{step.body}</p>
                    {step.items?.length ? (
                      <ul className="usage-guide-items">
                        {step.items.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    ) : null}
                  </li>
                ))}
              </ol>
            </div>
          ))}
          <p className="usage-guide-footer">{L.footer}</p>
        </div>
      ) : null}
    </div>
  )
}

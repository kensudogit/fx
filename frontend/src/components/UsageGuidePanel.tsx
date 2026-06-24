'use client'

/**
 * 画面右下のドラッグ可能な利用手順パネル（localStorage で位置・開閉を保存）。
 * FX専門家向けプレゼン — アーキテクチャ概要・分析ワークフローを表示。
 */
import { useCallback, useEffect, useRef, useState } from 'react'

const STORAGE_KEY = 'fx-tool-usage-guide-v1'
const PANEL_WIDTH = 420

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
  variant?: 'architecture' | 'ai' | 'default'
}

const architectureFeatured: FeaturedBlock = {
  badge: 'Architecture',
  title: 'Next.js BFF + FastAPI 分析エンジン',
  body:
    'フロントは同一オリジンで FastAPI にプロキシ。OHLCV は Yahoo Finance 取得 → PostgreSQL 永続化。AI 機能は OpenAI API をバックエンド経由で呼び出し、API キーをクライアントに露出しません。',
  variant: 'architecture',
  items: [
    'Next.js — テクニカル / ファンダ / AI の 3 画面',
    'FastAPI :8000 — 指標計算 · ML · OpenAI 統合',
    'PostgreSQL — OHLCV キャッシュ · 経済イベント',
    'Railway 統合デプロイ — 外部公開は Next.js の PORT のみ',
    '/health — 生存確認 · /docs — Swagger API リファレンス',
  ],
}

const aiFeatured: FeaturedBlock = {
  badge: 'AI Analysis',
  title: 'OpenAI 統合 — ニュース〜リスクまで一気通貫',
  body:
    'テクニカル指標とファンダメンタルデータをコンテキストに、OpenAI がニュース要約・売買判断・ポジションサイズを提案。ML 予測（RandomForest）は補助シグナルとして併用。',
  variant: 'ai',
  items: [
    'ニュース収集 — RSS + AI センチメント（強気 / 弱気 / 中立）',
    'ファンダ AI — 雇用統計 · CPI · FOMC · 日銀 · GDP の影響評価',
    '売買判断 — buy / sell / hold + 根拠・信頼度',
    'リスク管理 — 口座残高から推奨ロット・損切り幅を算出',
    '統合レポート — 上記を 1 リクエストでまとめて取得',
  ],
}

const techStack = [
  'Python · FastAPI',
  'Next.js 15 · Recharts',
  'PostgreSQL',
  'OpenAI gpt-4o-mini',
  'Yahoo Finance',
  'scikit-learn · Railway',
] as const

const archDiagram = `Browser (FX Expert)
    │ HTTPS
    ▼
Next.js :PORT (Railway)
    ├─ /              テクニカル分析
    ├─ /fundamental   経済指標カレンダー
    ├─ /ai            OpenAI 統合分析
    └─ /api/* ──proxy──► FastAPI :8000
              ├─ Yahoo Finance (OHLCV)
              ├─ PostgreSQL (ohlcv_data)
              └─ OpenAI API (news · trade · risk)`

const L = {
  title: '利用手順',
  subtitle: 'Architecture & Ops',
  dragHint: 'ドラッグで移動',
  expand: '開く',
  collapse: '閉じる',
  heroTitle: 'FX 分析プラットフォーム',
  heroLead:
    'テクニカル × ファンダメンタル × OpenAI。通貨ペアの多角的分析と売買判断支援を 1 画面群で提供します。',
  stackLabel: 'Tech stack',
  diagramLabel: 'Service topology',
  scrollHint: '↓ 分析ワークフロー・デモ手順は下へ',
  footer:
    '▼▲ で開閉 · ヘッダーをドラッグして移動 · 表示位置は自動保存されます。',
  steps: [
    {
      title: '1. 接続確認（最初に）',
      body: '本番・ローカル共通。障害切り分けとプレゼン前チェックの起点です。',
      items: [
        '本番: https://fx-production-f5d5.up.railway.app/',
        '/health — Web + API 生存確認（200 OK）',
        '/api/ai/status — OpenAI API キー設定の有無',
        'Swagger: /docs — 全エンドポイント一覧',
      ],
    },
    {
      title: '2. テクニカル分析（/）',
      body: 'OHLCV チャート上で主要テクニカル指標を切り替え、複合シグナルと ML 予測を確認します。',
      items: [
        '通貨ペア選択 — USDJPY / EURUSD / GBPUSD 等',
        '期間 — 90 / 200 / 365 日（ローソク足本数）',
        '「データ同期」— Yahoo Finance → PostgreSQL へ最新足を取得',
        'タブ: 価格+MA · ボリンジャー · 一目均衡表 · RSI · MACD · ストキャス',
        'シグナルパネル — 各指標の買い/売り/中立を一覧表示',
        'ML 予測 — RandomForest による翌日方向の参考値',
      ],
    },
    {
      title: '3. 指標の読み方（テクニカル）',
      body: 'FX 専門家向け — 各指標が何を示すか、シグナル判定の考え方。',
      items: [
        'MA（5/25/75）— 短期・中期・長期トレンド。ゴールデン/デッドクロス',
        'ボリンジャーバンド — ±2σ。バンドタッチ・スクイーズでボラティリティ判断',
        '一目均衡表 — 雲（先行スパン）の上下でトレンド方向、転換線/基準線クロス',
        'RSI(14) — 70 超過買い / 30 未満売られすぎ。ダイバージェンスに注意',
        'MACD — シグナル線クロス、ヒストグラムのゼロライン',
        'ストキャス(14,3) — %K/%D のクロスと 80/20 水準',
      ],
    },
    {
      title: '4. ファンダメンタル分析（/fundamental）',
      body: '主要経済指標イベントと通貨への影響をカレンダー形式で確認します。',
      items: [
        '対象イベント — 米雇用統計 · CPI · FOMC · 日銀政策 · GDP',
        '重要度（高/中/低）と予想値・前回値の比較',
        '通貨ペア別の影響方向（ドル高/円高 等）のラベル表示',
        '/api/fundamental — JSON API（他ツール連携用）',
        '/api/fundamental/calendar — 日付順イベント一覧',
      ],
    },
    {
      title: '5. AI 分析（/ai）— 推奨デモフロー',
      body: 'OpenAI 連携が有効な場合のプレゼン向け操作順序。口座残高はリスク計算に使用します。',
      items: [
        '① 通貨ペア・口座残高（USD）を設定',
        '②「統合レポート」タブ → 分析実行（全要素を一括取得）',
        '③ ニュース — センチメント・要約・関連ヘッドライン',
        '④ ファンダ AI — 直近イベントの影響度と方向性',
        '⑤ 売買判断 — buy/sell/hold · 信頼度 · エントリー/利確/損切り案',
        '⑥ リスク — 推奨ロット · リスク% · 最大ドローダウン想定',
        'OPENAI_API_KEY 未設定時はルールベースのフォールバック表示',
      ],
    },
    {
      title: '6. API エンドポイント（開発者向け）',
      body: '外部システム連携・バックテスト用。同一オリジンまたは /docs から試験可能。',
      items: [
        'GET /api/symbols — 利用可能通貨ペア一覧',
        'POST /api/data/sync/{symbol}?days=200 — 市場データ同期',
        'GET /api/technical/{symbol} — 全指標計算結果',
        'GET /api/technical/{symbol}/signals — 売買シグナル配列',
        'GET /api/ml/predict/{symbol} — ML 価格方向予測',
        'GET /api/ai/report/{symbol}?balance=10000 — AI 統合レポート',
      ],
    },
    {
      title: '7. ローカル開発',
      body: 'PostgreSQL（port 5433）+ バックエンド + フロントを個別起動する場合。',
      items: [
        'docker compose up -d — PostgreSQL + DynamoDB Local',
        'backend: pip install -r requirements.txt → python run.py (:8000)',
        'frontend: npm install → npm run dev (:3000)',
        '.env — DATABASE_URL · OPENAI_API_KEY · OPENAI_MODEL',
        'フロントの next.config.ts が /api/* を :8000 にプロキシ',
      ],
    },
    {
      title: '8. Railway 本番デプロイ',
      body: 'GitHub 連携の統合 Docker イメージ。1 サービスで Next.js + FastAPI を起動。',
      items: [
        'リポジトリ: github.com/kensudogit/fx',
        '環境変数 — DATABASE_URL（Postgres プラグイン）',
        'OPENAI_API_KEY · OPENAI_MODEL=gpt-4o-mini（任意）',
        'railway.toml — healthcheckPath: /health',
        'デプロイ後 → /health OK → /ai で AI ステータス確認',
      ],
    },
    {
      title: '9. プレゼン向けデモシナリオ（15 分）',
      body: 'FX 専門家向け推奨トークトラック。質疑用のポイント付き。',
      items: [
        '0–2分: 利用手順パネルでアーキテクチャ概要（本パネル）',
        '2–6分: USDJPY · 200日 → データ同期 → 一目均衡表 + シグナル説明',
        '6–9分: ファンダページで直近 FOMC / 雇用統計の影響を確認',
        '9–13分: AI 統合レポート実行 → 売買判断とリスクを実演',
        '13–15分: /docs で API 拡張性 · バックテスト連携の可能性を説明',
        'Q&A: ML は補助、最終判断はファンダ+テクニカル+AI の合議という位置づけ',
      ],
    },
  ] satisfies readonly GuideStep[],
} as const

type SavedState = {
  x: number
  y: number
  expanded: boolean
}

function defaultPosition() {
  if (typeof window === 'undefined') return { x: 24, y: 24 }
  const x = Math.max(16, window.innerWidth - PANEL_WIDTH - 24)
  const y = Math.max(72, window.innerHeight - 480)
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

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as SavedState
        setPos({ x: parsed.x, y: parsed.y })
        setExpanded(parsed.expanded)
      } catch {
        setPos(defaultPosition())
      }
    } else {
      setPos(defaultPosition())
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
      const el = panelRef.current
      if (!el) return
      setPos((current) => clampPosition(current.x, current.y, el.offsetWidth, el.offsetHeight))
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [ready])

  const onHeaderPointerDown = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
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
    [pos.x, pos.y],
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
      className={`usage-guide-panel${expanded ? ' is-expanded' : ' is-collapsed'}${dragging ? ' is-dragging' : ''}`}
      style={{ left: pos.x, top: pos.y, width: PANEL_WIDTH }}
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

          <FeaturedSection block={aiFeatured} />

          <p className="usage-guide-scroll-hint">{L.scrollHint}</p>
          <ol className="usage-guide-steps">
            {L.steps.map((step) => (
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
          <p className="usage-guide-footer">{L.footer}</p>
        </div>
      ) : null}
    </div>
  )
}

'use client'

/**
 * 画面右下のドラッグ可能な利用手順パネル（localStorage で位置・開閉を保存）。
 * FX専門家向けプレゼン — アーキテクチャ概要・分析ワークフローを表示。
 */
import { useCallback, useEffect, useRef, useState } from 'react'

const STORAGE_KEY = 'fx-tool-usage-guide-v2'
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
  variant?: 'architecture' | 'ai' | 'technical' | 'fundamental' | 'default'
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
        body: '本パネルは全画面で表示されます。ヘッダーをドラッグして位置を変更でき、▼▲ で折りたたみ可能です。',
        items: [
          '画面上部ナビ — 「テクニカル分析」「ファンダメンタル分析」「AI分析」で画面切替',
          '本パネル — 右下付近に表示（位置・開閉状態はブラウザに自動保存）',
          '推奨フロー — テクニカル → ファンダ → AI の順で多角的に確認',
          'プレゼン時 — パネルを画面端に寄せ、メイン画面を広く使う',
        ],
      },
      {
        title: '接続確認（最初に）',
        body: '本番・ローカル共通。障害切り分けとプレゼン前チェックの起点です。',
        items: [
          '本番 URL: https://fx-production-f5d5.up.railway.app/',
          '/health — Web + API 生存確認（200 OK）',
          'AI分析画面 — 「接続準備完了」バッジで OpenAI キー設定を確認',
          'Swagger: /docs — 全エンドポイント一覧・試験呼び出し',
        ],
      },
      {
        title: '初回セットアップ（5 分）',
        body: '初めて使う場合、またはチャートが空の場合の最短手順です。',
        items: [
          '① テクニカル分析を開く → 通貨ペア USDJPY · 期間 200日 を選択',
          '②「データ同期」をクリック（完了まで数秒〜数十秒）',
          '③ チャートにローソク足が表示されることを確認',
          '④ 右のシグナルパネルで買い/売りシグナルが出ているか確認',
          '⑤ ファンダメンタル → AI分析 へ進み、統合レポートを実行',
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
    label: 'トラブルシュート・運用',
    steps: [
      {
        title: 'よくあるエラーと対処',
        body: '画面に赤いエラーバナーが出た場合の確認手順です。',
        items: [
          'データ取得に失敗 —「データ同期」を再実行。Yahoo Finance の一時障害の可能性',
          'AI分析に失敗 — OPENAI_API_KEY の設定・残高・レート制限を確認',
          '/health が 503 — Railway 再デプロイ。DATABASE_URL の Reference 変数を確認',
          'チャートが空 — 同期未実施、または選択期間のデータが DB に無い',
        ],
      },
      {
        title: 'API エンドポイント（開発者向け）',
        body: '/docs から Swagger UI で試験可能。バックテスト・外部連携に利用します。',
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
        title: 'Railway 本番・ローカル開発',
        body: 'デプロイとローカル起動の参考情報です。',
        items: [
          '本番 — GitHub 連携 · DATABASE_URL · OPENAI_API_KEY · /health チェック',
          'ローカル — docker compose up -d → backend :8000 → frontend npm run dev :3000',
          '環境変数 — DATABASE_URL · OPENAI_API_KEY · OPENAI_MODEL=gpt-4o-mini',
        ],
      },
      {
        title: 'プレゼン向け 15 分シナリオ',
        body: 'FX 専門家向け推奨トークトラック（本パネルを横に開いたまま実演可能）。',
        items: [
          '0–2分: 本パネルでアーキテクチャ・サービストポロジを概要説明',
          '2–6分: テクニカル — USDJPY·200日·データ同期·一目均衡表·シグナル',
          '6–9分: ファンダ — FOMC/雇用統計タブとイベントカレンダー',
          '9–13分: AI — 総合レポート実行·売買判断とリスク管理',
          '13–15分: /docs で API 拡張性 · バックテスト連携の可能性',
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
    'テクニカル × ファンダメンタル × OpenAI。通貨ペアの多角的分析と売買判断支援を 1 画面群で提供します。',
  stackLabel: 'Tech stack',
  diagramLabel: 'Service topology',
  workflowLabel: '詳細利用手順',
  scrollHint: '↓ 画面別の詳細手順・デモフローは下へ',
  footer:
    '▼▲ で開閉 · ヘッダーをドラッグして移動 · 表示位置は自動保存されます。',
} as const

type SavedState = {
  x: number
  y: number
  expanded: boolean
}

function defaultPosition() {
  if (typeof window === 'undefined') return { x: 24, y: 24 }
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

          <FeaturedSection block={technicalFeatured} />
          <FeaturedSection block={fundamentalFeatured} />
          <FeaturedSection block={aiFeatured} />

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

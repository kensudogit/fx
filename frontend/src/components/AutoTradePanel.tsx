/**
 * @file AutoTradePanel.tsx
 * @description 自動取引エンジンパネル — シグナル統合型の完全自動 FX 取引画面
 *
 * トライオートFX ライクな操作フローを提供する：
 *   1. プリセット選択    : 用意された戦略プリセットをワンクリックで適用
 *   2. オートセレクト   : 3 問（資金・期間・リスク）への回答から最適プリセットを自動選択
 *   3. シミュレーション : 過去 365 日のバックテストで推奨証拠金を算出
 *   4. ドライラン評価   : 実際の約定なしでシグナルを評価（evaluateAutoTrade）
 *   5. 実行             : 単一シンボルまたは全シンボルで実際に注文を発行
 *
 * シグナルソースは ai / technical / intelligence / mtf / tradingview の 5 種類を
 * 組み合わせ可能で、MTF 方向一致・イベント回避・SL/TP・逆シグナル決済などの
 * リスクコントロールオプションを提供する。
 *
 * 取引モード:
 *   - paper  : ペーパー（仮想）取引 — 実資金リスクなし
 *   - practice: OANDA デモ口座
 *   - live   : OANDA 本番口座（要注意）
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import {
  applyAutoTradePreset,
  autoSelectAutoTrade,
  evaluateAutoTrade,
  getAutoTradeConfig,
  getAutoTradePresets,
  getAutoTradeStatus,
  getSymbols,
  runAutoTradeAll,
  runAutoTradeSymbol,
  simulateAutoTrade,
  updateAutoTradeConfig,
} from "@/lib/api";
import type {
  AutoTradeConfig,
  AutoTradeEvaluateResult,
  AutoTradePreset,
  AutoTradeRun,
  AutoTradeSimulation,
  AutoTradeStatus,
} from "@/types";

/**
 * シグナルソースの英語キーを日本語ラベルに変換するマップ
 * エンジン設定の「シグナルソース」チップ選択 UI で利用する
 */
const SOURCE_LABELS: Record<string, string> = {
  ai: "AI シグナル",
  technical: "テクニカル",
  intelligence: "統合分析",
  mtf: "マルチTF",
  tradingview: "TradingView",
};

/**
 * 取引判定（decision）の英語値を日本語ラベルに変換するユーティリティ関数
 *
 * @param d - "executed" | "ready" | "blocked" | "skipped" | "failed" | "disabled"
 * @returns 対応する日本語ラベル（未知の値はそのまま返す）
 */
function decisionLabel(d: string) {
  const map: Record<string, string> = {
    executed: "約定",
    ready: "実行可能",
    blocked: "ブロック",
    skipped: "スキップ",
    failed: "失敗",
    disabled: "無効",
  };
  return map[d] ?? d;
}

/**
 * 取引判定に応じたテキストカラー CSS クラスを返すユーティリティ関数
 * executed / ready は買いカラー（緑）、blocked / failed は売りカラー（赤）
 *
 * @param d - 判定文字列
 * @returns CSS クラス名
 */
function decisionClass(d: string) {
  if (d === "executed" || d === "ready") return "text-buy";
  if (d === "blocked" || d === "failed") return "text-sell";
  return "";
}

/**
 * AutoTradePanel
 *
 * 自動取引エンジンのメインコンポーネント。
 * 設定・プリセット・オートセレクト・シミュレーション・実行ログを 1 画面に統合する。
 *
 * ## 主要な状態フロー
 * 1. マウント時: getAutoTradeConfig() + getAutoTradeStatus() を並列取得（load 関数）
 * 2. プリセット選択: handleApplyPreset() → applyAutoTradePreset() → 設定を即反映
 * 3. オートセレクト: handleAutoselect(false) で提案のみ、(true) で即時適用
 * 4. ドライラン: handleEvaluate() → evaluateAutoTrade() → 評価結果を画面表示（約定なし）
 * 5. 実行: handleRunSymbol() / handleRunAll() → confirm ダイアログ → 実際に注文送信
 */
export default function AutoTradePanel() {
  /** 通貨ペア一覧（セレクトボックス用）*/
  const [symbols, setSymbols] = useState<string[]>([]);
  /** 現在選択中の評価・実行対象通貨ペア */
  const [symbol, setSymbol] = useState("USDJPY");
  /** 自動取引エンジンの設定オブジェクト（API から取得） */
  const [config, setConfig] = useState<AutoTradeConfig | null>(null);
  /** エンジンの稼働状態・最近の実行履歴・パフォーマンス統計 */
  const [status, setStatus] = useState<AutoTradeStatus | null>(null);
  /** ドライラン / 実行後の評価結果（判定・理由・注文プラン） */
  const [evaluation, setEvaluation] = useState<AutoTradeEvaluateResult | null>(null);
  /** 利用可能な戦略プリセット一覧 */
  const [presets, setPresets] = useState<AutoTradePreset[]>([]);
  /** シミュレーション（バックテスト）の結果 */
  const [simulation, setSimulation] = useState<AutoTradeSimulation | null>(null);
  /** オートセレクトが返す推奨根拠テキスト */
  const [autoselectMsg, setAutoselectMsg] = useState<string | null>(null);

  /** オートセレクト用の運用資金規模（small / medium / large） */
  const [capital, setCapital] = useState("medium");
  /** オートセレクト用の運用期間（short / medium / long） */
  const [horizon, setHorizon] = useState("medium");
  /** オートセレクト用のリスク許容度（low / medium / high） */
  const [riskAppetite, setRiskAppetite] = useState("medium");

  /** 設定読み込み中フラグ（初期ローディングスピナーの表示制御） */
  const [loading, setLoading] = useState(true);
  /** 設定保存中フラグ（保存ボタンの無効化制御） */
  const [saving, setSaving] = useState(false);
  /** 評価・実行中フラグ（実行ボタンの無効化制御） */
  const [running, setRunning] = useState(false);
  /** シミュレーション処理中フラグ（シミュレーションカード専用） */
  const [simulating, setSimulating] = useState(false);
  /** シミュレーション専用エラーメッセージ（カード内に表示） */
  const [simError, setSimError] = useState<string | null>(null);
  /** エラーメッセージ */
  const [error, setError] = useState<string | null>(null);

  /**
   * 設定と稼働状態を並列取得する関数
   * useCallback でメモ化して不要な再生成を防ぐ（依存配列なし = 常に同一インスタンス）
   */
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // 設定と稼働状態を同時に取得してレイテンシを削減
      const [cfgRes, statusRes] = await Promise.all([getAutoTradeConfig(), getAutoTradeStatus()]);
      setConfig(cfgRes.config);
      setStatus(statusRes);
    } catch (e) {
      setError(e instanceof Error ? e.message : "読み込みに失敗しました");
    } finally {
      setLoading(false);
    }
  }, []);

  /**
   * マウント時の初期化副作用
   * - 通貨ペア一覧を取得してセレクトボックスを初期化
   * - 戦略プリセット一覧を取得（エラーは無視してプリセット表示を省略）
   * - 設定・稼働状態を取得（load 関数）
   */
  useEffect(() => {
    getSymbols().then((r) => setSymbols(r.symbols));
    getAutoTradePresets().then((r) => setPresets(r.presets)).catch(() => {});
    load();
  }, [load]);

  /**
   * 設定を部分更新して保存する関数
   * - patch: AutoTradeConfig の変更箇所のみを送信する
   * - 保存後に load() で最新状態を再取得して UI を同期する
   *
   * @param patch - 更新したいフィールドのみを含む部分オブジェクト
   */
  const saveConfig = async (patch: Partial<AutoTradeConfig>) => {
    if (!config) return;
    setSaving(true);
    setError(null);
    try {
      const res = await updateAutoTradeConfig(patch);
      setConfig(res.config);
      // サーバー側でプリセット合成等の副作用が発生する可能性があるため再取得する
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  /**
   * ドライラン評価ハンドラ
   * 実際の注文を発行せずに、現在のシグナル・設定条件で取引可否を判定する。
   * 結果は evaluation ステートに格納して画面に表示する。
   */
  const handleEvaluate = async () => {
    setRunning(true);
    setError(null);
    try {
      const res = await evaluateAutoTrade(symbol);
      setEvaluation(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "評価に失敗しました");
    } finally {
      setRunning(false);
    }
  };

  /**
   * 単一シンボル実行ハンドラ
   * confirm ダイアログで実際の約定が発生することをユーザーに確認してから
   * runAutoTradeSymbol() を呼び出す。
   * 実行後に load() でステータスを更新する。
   */
  const handleRunSymbol = async () => {
    if (
      !window.confirm(
        `${symbol} で自動取引を実行します。OANDA practice/live またはペーパー約定が発生する可能性があります。続行しますか？`,
      )
    ) {
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const res = await runAutoTradeSymbol(symbol);
      // 実行結果をドライラン評価欄に表示して取引内容を確認できるようにする
      setEvaluation(res);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "実行に失敗しました");
    } finally {
      setRunning(false);
    }
  };

  /**
   * 全シンボル一括実行ハンドラ
   * 監視中の全シンボルに対して自動取引を実行する。
   * 複数の約定が発生するため confirm ダイアログで強く確認する。
   */
  const handleRunAll = async () => {
    if (
      !window.confirm(
        "監視中の全シンボルで自動取引を実行します。複数の約定が発生する可能性があります。続行しますか？",
      )
    ) {
      return;
    }
    setRunning(true);
    setError(null);
    try {
      await runAutoTradeAll();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "一括実行に失敗しました");
    } finally {
      setRunning(false);
    }
  };

  /**
   * プリセット適用ハンドラ
   * 指定されたプリセット ID をサーバーに送信し、設定をプリセット値で上書きする。
   * 適用後に load() で最新状態に同期する。
   *
   * @param presetId - 適用するプリセットの ID
   */
  const handleApplyPreset = async (presetId: string) => {
    setSaving(true);
    setError(null);
    try {
      const res = await applyAutoTradePreset(presetId);
      setConfig(res.config);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "プリセット適用に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  /**
   * オートセレクトハンドラ
   * ユーザーが入力した 3 つのパラメータ（資金・期間・リスク許容度）をもとに
   * サーバーが最適プリセットを提案または即時適用する。
   *
   * @param apply - true: 提案されたプリセットを設定に即時適用する / false: 提案のみ表示
   */
  const handleAutoselect = async (apply: boolean) => {
    setRunning(true);
    setError(null);
    try {
      const res = await autoSelectAutoTrade({
        capital,
        horizon,
        risk_appetite: riskAppetite,
        apply,
      });
      // 提案根拠テキストを表示（apply の有無に関わらず表示）
      setAutoselectMsg(res.rationale);
      // apply=true の場合のみ設定を更新して UI に反映する
      if (apply) {
        setConfig(res.config);
        await load();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "オートセレクトに失敗しました");
    } finally {
      setRunning(false);
    }
  };

  /**
   * シミュレーションハンドラ
   * 指定シンボルの過去 365 日データでバックテストを実行し、
   * 勝率・評価グレード・推奨証拠金を算出する。
   * 実際の注文は発行しない。
   */
  const handleSimulate = async () => {
    setSimulating(true);
    setSimError(null);
    try {
      const res = await simulateAutoTrade(symbol, {
        accountBalance: config?.account_balance,
        presetId: config?.strategy_preset ?? "balanced",
      });
      setSimulation(res);
    } catch (e) {
      setSimError(e instanceof Error ? e.message : "シミュレーションに失敗しました");
    } finally {
      setSimulating(false);
    }
  };

  /** 初期ロード中かつ設定未取得の場合はスピナーを表示 */
  if (loading && !config) {
    return <div className="loading">自動取引設定を読み込み中...</div>;
  }

  /** 設定取得に失敗した場合は何も表示しない */
  if (!config) return null;

  /** スケジューラの稼働情報（status が null の場合は undefined） */
  const scheduler = status?.scheduler;
  /** 最近の実行ログ一覧（最大件数はサーバー側で制限） */
  const runs = status?.recent_runs ?? [];
  /** 累積パフォーマンス統計（約定率・損益・勝率） */
  const performance = status?.performance;
  /** 現在オープン中のポジション一覧 */
  const openPositions = status?.open_positions ?? [];

  return (
    <>
      <div className="page-header">
        <h1>自動取引エンジン</h1>
        <div className="controls">
          {/* ドライラン・実行対象の通貨ペアを選択 */}
          <div className="select-wrapper">
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          {/* 手動更新ボタン — 設定・稼働状態を再取得する */}
          <button type="button" className="btn-secondary" onClick={load} disabled={loading}>
            更新
          </button>
        </div>
      </div>

      <p className="hint stack-note">
        トライオートFX同様 — プリセット選択 · オートセレクト · シミュレーション · SL/TP 自動決済に対応。
      </p>

      {error && <p className="error-text">{error}</p>}

      {/* === モバイル用サマリーカード（performance データがある場合のみ表示） === */}
      {performance && (
        <div className="mobile-only autotrade-mobile-summary">
          <div className="autotrade-mobile-summary-row">
            {/* 自動取引の ON/OFF 状態をバッジで表示 */}
            <span className={`badge ${config.enabled ? "badge-buy" : "badge-neutral"}`}>
              {config.enabled ? "自動取引 ON" : "OFF"}
            </span>
            <span className="hint">{config.mode ?? "paper"}</span>
          </div>
          <div className="stat-grid">
            <div className="stat-item">
              <div className="label">約定率</div>
              <div className="value">{performance.summary.execution_rate_pct}%</div>
            </div>
            <div className="stat-item">
              <div className="label">実現損益</div>
              {/* 損益がプラスなら買いカラー（緑）、マイナスなら売りカラー（赤） */}
              <div
                className={`value ${
                  (performance.pnl?.total_realized_usd ?? 0) >= 0 ? "text-buy" : "text-sell"
                }`}
              >
                ${performance.pnl?.total_realized_usd ?? 0}
              </div>
            </div>
            <div className="stat-item">
              <div className="label">勝率</div>
              <div className="value">{performance.pnl?.win_rate_pct ?? 0}%</div>
            </div>
          </div>
          {/* モバイル用操作ボタン（ドライラン・実行） */}
          <div className="order-controls">
            <button type="button" className="btn-secondary" disabled={running} onClick={handleEvaluate}>
              ドライラン
            </button>
            {/* 自動取引が無効化されている場合は実行ボタンを無効化 */}
            <button type="button" className="btn-buy" disabled={running || !config.enabled} onClick={handleRunSymbol}>
              実行
            </button>
          </div>
        </div>
      )}

      {/* === デスクトップ用プリセット戦略選択カード === */}
      <div className="card desktop-only" style={{ marginBottom: "1.5rem" }}>
        <h2>セレクト — プリセット戦略</h2>
        <p className="hint">用意されたルールから選ぶだけで開始（現在: {config.strategy_preset ?? "balanced"}）</p>
        <div className="preset-grid">
          {presets.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`preset-card ${config.strategy_preset === p.id ? "preset-active" : ""}`}
              disabled={saving}
              onClick={() => handleApplyPreset(p.id)}
            >
              {/* 現在適用中のプリセットにはアクティブスタイルを適用 */}
              <strong>{p.label}</strong>
              <span className="hint">{p.description}</span>
              <span className="preset-meta">信頼度 {p.min_confidence}% · RR {p.risk_reward}</span>
            </button>
          ))}
        </div>
      </div>

      {/* === デスクトップ用オートセレクト + シミュレーションカード === */}
      <div className="grid-2 desktop-only" style={{ marginBottom: "1.5rem" }}>
        {/* オートセレクト: 3 問への回答から最適プリセットを AI が提案 */}
        <div className="card">
          <h2>オートセレクト（3 問）</h2>
          <div className="form-grid">
            {/* 運用資金規模の選択 — small/medium/large でプリセット候補を絞り込む */}
            <label>
              運用資金
              <select value={capital} onChange={(e) => setCapital(e.target.value)}>
                <option value="small">小額 ($5,000)</option>
                <option value="medium">中程度 ($20,000)</option>
                <option value="large">大額 ($100,000)</option>
              </select>
            </label>
            {/* 運用期間の選択 — トレードスタイル（スキャル/スイング等）に影響 */}
            <label>
              運用期間
              <select value={horizon} onChange={(e) => setHorizon(e.target.value)}>
                <option value="short">短期</option>
                <option value="medium">中期</option>
                <option value="long">長期</option>
              </select>
            </label>
            {/* リスク許容度の選択 — min_confidence と risk_percent に反映される */}
            <label>
              リスク許容度
              <select value={riskAppetite} onChange={(e) => setRiskAppetite(e.target.value)}>
                <option value="low">低</option>
                <option value="medium">標準</option>
                <option value="high">高</option>
              </select>
            </label>
          </div>
          <div className="order-controls" style={{ marginTop: "0.75rem" }}>
            {/* 提案のみ表示（apply=false）— 設定には保存しない */}
            <button type="button" className="btn-secondary" disabled={running} onClick={() => handleAutoselect(false)}>
              提案を見る
            </button>
            {/* 提案を設定に即時適用（apply=true）*/}
            <button type="button" className="btn-primary" disabled={running} onClick={() => handleAutoselect(true)}>
              適用して保存
            </button>
          </div>
          {/* AI が提案した根拠テキストを表示 */}
          {autoselectMsg && <p className="hint">{autoselectMsg}</p>}
        </div>

        {/* シミュレーション: 過去データでバックテストし推奨証拠金を算出 */}
        <div className="card">
          <h2>運用前シミュレーション</h2>
          <p className="hint">{symbol} · 過去 365 日バックテスト + 推奨証拠金</p>
          <button type="button" className="btn-secondary" disabled={simulating} onClick={handleSimulate}>
            {simulating ? "⏳ 計算中..." : "シミュレーション実行"}
          </button>
          {/* シミュレーション専用エラー — カード内に表示 */}
          {simError && (
            <p className="error-text" style={{ marginTop: "0.5rem" }}>
              ⚠ {simError}
            </p>
          )}
          {/* シミュレーション処理中インジケータ */}
          {simulating && (
            <p className="hint" style={{ marginTop: "0.5rem" }}>
              365 日分のデータでバックテストを実行しています。数秒お待ちください...
            </p>
          )}
          {/* シミュレーション結果が取得された場合のみ表示 */}
          {simulation && !simulating && (
            <div className="eval-result" style={{ marginTop: "1rem" }}>
              <div className="stat-grid">
                <div className="stat-item">
                  <div className="label">評価グレード</div>
                  <div className="value" style={{ color: simulation.assessment.grade === "A" || simulation.assessment.grade === "B" ? "#22c55e" : "#f59e0b" }}>
                    {simulation.assessment.grade}
                  </div>
                </div>
                <div className="stat-item">
                  <div className="label">勝率</div>
                  <div className="value">{simulation.backtest.win_rate}%</div>
                </div>
                <div className="stat-item">
                  <div className="label">取引数</div>
                  <div className="value">{simulation.backtest.total_trades}回</div>
                </div>
                <div className="stat-item">
                  <div className="label">推奨証拠金</div>
                  <div className="value">${simulation.capital.recommended_margin_usd.toLocaleString()}</div>
                </div>
                <div className="stat-item">
                  <div className="label">安全証拠金</div>
                  <div className="value">${simulation.capital.safe_margin_usd.toLocaleString()}</div>
                </div>
                <div className="stat-item">
                  <div className="label">運用可否</div>
                  <div className="value" style={{ color: simulation.assessment.ready_to_deploy ? "#22c55e" : "#f59e0b" }}>
                    {simulation.assessment.ready_to_deploy ? "✓ 可" : "要検討"}
                  </div>
                </div>
              </div>
              <p className="hint" style={{ marginTop: "0.5rem" }}>{simulation.assessment.summary}</p>
            </div>
          )}
        </div>
      </div>

      {/* === 累積パフォーマンス統計カード === */}
      {performance && (
        <div className="card" style={{ marginBottom: "1.5rem" }}>
          <h2>運用パフォーマンス</h2>
          <div className="stat-grid">
            <div className="stat-item">
              <div className="label">約定率</div>
              <div className="value">{performance.summary.execution_rate_pct}%</div>
            </div>
            <div className="stat-item">
              <div className="label">約定 / ブロック</div>
              <div className="value">
                {performance.summary.executed} / {performance.summary.blocked}
              </div>
            </div>
            <div className="stat-item">
              <div className="label">平均信頼度</div>
              <div className="value">{performance.summary.avg_confidence}%</div>
            </div>
            <div className="stat-item">
              <div className="label">実現損益</div>
              <div
                className={`value ${
                  (performance.pnl?.total_realized_usd ?? 0) >= 0 ? "text-buy" : "text-sell"
                }`}
              >
                ${performance.pnl?.total_realized_usd ?? 0}
              </div>
            </div>
            <div className="stat-item">
              <div className="label">勝率（決済）</div>
              <div className="value">
                {performance.pnl?.win_rate_pct ?? 0}% ({performance.pnl?.closed_trades ?? 0}件)
              </div>
            </div>
            {/* Redis 分散ロックが有効な場合のみ表示（複数インスタンス運用時） */}
            {scheduler?.distributed_lock && (
              <div className="stat-item">
                <div className="label">分散ロック</div>
                <div className="value" style={{ fontSize: "0.85rem" }}>
                  {scheduler.distributed_lock.backend === "redis" ? "Redis" : "単一プロセス"}
                </div>
              </div>
            )}
          </div>
          {/* 週次実現損益テーブル（データがある場合のみ表示） */}
          {performance.pnl?.weekly && performance.pnl.weekly.length > 0 && (
            <>
              <h3 style={{ marginTop: "1rem" }}>週次実現損益</h3>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>週（月曜〜）</th>
                    <th>損益 USD</th>
                    <th>決済数</th>
                    <th>勝ち</th>
                  </tr>
                </thead>
                <tbody>
                  {performance.pnl.weekly.map((w) => (
                    <tr key={w.week_start}>
                      <td>{w.week_start}</td>
                      {/* 損益プラスは緑、マイナスは赤 */}
                      <td className={w.realized_usd >= 0 ? "text-buy" : "text-sell"}>
                        ${w.realized_usd}
                      </td>
                      <td>{w.trades}</td>
                      <td>{w.wins}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <p className="hint">{performance.maintenance_hint}</p>
        </div>
      )}

      {/* === オープンポジション一覧（存在する場合のみ表示） === */}
      {openPositions.length > 0 && (
        <div className="card" style={{ marginBottom: "1.5rem" }}>
          <h2>オープンポジション</h2>
          <table className="data-table">
            <thead>
              <tr>
                <th>通貨</th>
                <th>方向</th>
                <th>数量</th>
                <th>参入</th>
                <th>SL</th>
                <th>TP</th>
              </tr>
            </thead>
            <tbody>
              {openPositions.map((p) => (
                <tr key={`${p.symbol}-${p.side}`}>
                  <td>{p.symbol}</td>
                  {/* 方向（buy/sell）に応じてテキストカラーを切り替え */}
                  <td className={p.side === "buy" ? "text-buy" : "text-sell"}>{p.side}</td>
                  <td>{p.units}</td>
                  <td>{p.entry_price}</td>
                  {/* SL/TP が設定されていない場合は「—」を表示 */}
                  <td>{p.stop_loss ?? "—"}</td>
                  <td>{p.take_profit ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid-2">
        {/* === エンジン設定カード: ON/OFF・各種パラメータ・通貨ペア・シグナルソース === */}
        <div className="card">
          <h2>エンジン設定</h2>
          {/* 自動取引の有効化/無効化トグル — チェックを変えると即座に saveConfig を呼ぶ */}
          <div className="autotrade-toggle">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={config.enabled}
                onChange={(e) => saveConfig({ enabled: e.target.checked })}
                disabled={saving}
              />
              自動取引を有効化
            </label>
            <span className={`badge ${config.enabled ? "badge-buy" : "badge-neutral"}`}>
              {config.enabled ? "ON" : "OFF"}
            </span>
          </div>

          {/* 数値パラメータ入力フィールド（onBlur で保存して不要なリクエストを削減） */}
          <div className="form-grid" style={{ marginTop: "1rem" }}>
            {/* 最低信頼度: この値未満のシグナルはブロックされる */}
            <label>
              最低信頼度 (%)
              <input
                type="number"
                min={30}
                max={95}
                value={config.min_confidence}
                onChange={(e) => setConfig({ ...config, min_confidence: Number(e.target.value) })}
                onBlur={() => saveConfig({ min_confidence: config.min_confidence })}
              />
            </label>
            {/* リスク率: 口座残高に対するトレードリスク割合 */}
            <label>
              リスク (%)
              <input
                type="number"
                min={0.1}
                max={10}
                step={0.1}
                value={config.risk_percent}
                onChange={(e) => setConfig({ ...config, risk_percent: Number(e.target.value) })}
                onBlur={() => saveConfig({ risk_percent: config.risk_percent })}
              />
            </label>
            {/* 口座残高: ポジションサイズ計算の基準値 */}
            <label>
              口座残高 (USD)
              <input
                type="number"
                min={100}
                value={config.account_balance}
                onChange={(e) => setConfig({ ...config, account_balance: Number(e.target.value) })}
                onBlur={() => saveConfig({ account_balance: config.account_balance })}
              />
            </label>
            {/* 日次上限: 1 日に発注できる最大取引回数 */}
            <label>
              日次上限
              <input
                type="number"
                min={1}
                max={20}
                value={config.max_daily_trades}
                onChange={(e) => setConfig({ ...config, max_daily_trades: Number(e.target.value) })}
                onBlur={() => saveConfig({ max_daily_trades: config.max_daily_trades })}
              />
            </label>
            {/* クールダウン: 連続取引を防ぐための待機時間（分） */}
            <label>
              クールダウン (分)
              <input
                type="number"
                min={0}
                max={1440}
                value={config.cooldown_minutes}
                onChange={(e) => setConfig({ ...config, cooldown_minutes: Number(e.target.value) })}
                onBlur={() => saveConfig({ cooldown_minutes: config.cooldown_minutes })}
              />
            </label>
            {/* イベント回避: 高影響経済指標の X 時間前から取引を停止 */}
            <label>
              イベント回避 (時間)
              <input
                type="number"
                min={0}
                max={48}
                value={config.event_blackout_hours}
                onChange={(e) =>
                  setConfig({ ...config, event_blackout_hours: Number(e.target.value) })
                }
                onBlur={() => saveConfig({ event_blackout_hours: config.event_blackout_hours })}
              />
            </label>
          </div>

          {/* 対象通貨ペアのチップ選択 — アクティブなペアは chip-active スタイル */}
          <div style={{ marginTop: "1rem" }}>
            <p className="label">対象通貨ペア</p>
            <div className="chip-group">
              {symbols.map((s) => {
                const active = config.symbols.includes(s);
                return (
                  <button
                    key={s}
                    type="button"
                    className={`chip ${active ? "chip-active" : ""}`}
                    onClick={() => {
                      const next = active
                        ? config.symbols.filter((x) => x !== s)
                        : [...config.symbols, s];
                      // 対象ペアが 0 件になる操作は無効（最低 1 ペアを維持）
                      if (next.length === 0) return;
                      saveConfig({ symbols: next });
                    }}
                  >
                    {s}
                  </button>
                );
              })}
            </div>
          </div>

          {/* シグナルソースのチップ選択 — 複数のシグナルを AND 条件で統合 */}
          <div style={{ marginTop: "1rem" }}>
            <p className="label">シグナルソース</p>
            <div className="chip-group">
              {Object.entries(SOURCE_LABELS).map(([key, label]) => {
                const active = config.sources.includes(key);
                return (
                  <button
                    key={key}
                    type="button"
                    className={`chip ${active ? "chip-active" : ""}`}
                    onClick={() => {
                      const next = active
                        ? config.sources.filter((x) => x !== key)
                        : [...config.sources, key];
                      // ソースが 0 件になる操作は無効（最低 1 ソースを維持）
                      if (next.length === 0) return;
                      saveConfig({ sources: next });
                    }}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* 高度なリスクコントロールオプション（チェックボックス群） */}
          <div className="checkbox-stack" style={{ marginTop: "1rem" }}>
            {/* MTF（マルチタイムフレーム）方向一致を必須にする — 逆張り回避に有効 */}
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={config.require_mtf_alignment}
                onChange={(e) => saveConfig({ require_mtf_alignment: e.target.checked })}
              />
              MTF 方向一致を必須
            </label>
            {/* TradingView Webhook 受信時に即時実行する — アラートから直接注文 */}
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={config.auto_execute_tradingview}
                onChange={(e) => saveConfig({ auto_execute_tradingview: e.target.checked })}
              />
              TradingView Webhook で即時実行
            </label>
            {/* SL（損切り）を ATR ベースで自動設定する */}
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={config.use_stop_loss !== false}
                onChange={(e) => saveConfig({ use_stop_loss: e.target.checked })}
              />
              損切り (SL) を自動設定
            </label>
            {/* TP（利確）を ATR × RR 比で自動設定する */}
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={config.use_take_profit !== false}
                onChange={(e) => saveConfig({ use_take_profit: e.target.checked })}
              />
              利確 (TP) を自動設定
            </label>
            {/* 逆シグナル検出時に既存ポジションを自動決済する */}
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={config.auto_exit_on_reverse !== false}
                onChange={(e) => saveConfig({ auto_exit_on_reverse: e.target.checked })}
              />
              逆シグナルで自動決済
            </label>
          </div>
        </div>

        {/* === スケジューラ情報 + 実行操作カード === */}
        <div className="card">
          <h2>スケジューラ & 実行</h2>
          {/* スケジューラが稼働中の場合のみ状態を表示 */}
          {scheduler && (
            <div className="stat-grid" style={{ marginBottom: "1rem" }}>
              <div className="stat-item">
                <div className="label">スケジューラ</div>
                <div className="value">
                  {scheduler.tenant_scheduler_enabled !== false ? "有効" : "無効"}
                  {scheduler.global_running ? " · 稼働中" : ""}
                </div>
              </div>
              <div className="stat-item">
                <div className="label">取引モード</div>
                {/* paper / practice / live のいずれか */}
                <div className="value">{scheduler.trading_mode ?? config.mode ?? "paper"}</div>
              </div>
              <div className="stat-item">
                <div className="label">間隔</div>
                <div className="value">{scheduler.interval_minutes} 分</div>
              </div>
              <div className="stat-item">
                <div className="label">最終実行</div>
                <div className="value" style={{ fontSize: "0.85rem" }}>
                  {/* 最終実行時刻を日本語ロケールで表示、未実行の場合は「—」 */}
                  {scheduler.last_run_at
                    ? new Date(scheduler.last_run_at).toLocaleString("ja-JP")
                    : "—"}
                </div>
              </div>
            </div>
          )}

          {/* 実行操作ボタン群 */}
          <div className="order-controls">
            {/* ドライラン評価: 実際の注文なしでシグナルを評価 */}
            <button type="button" className="btn-secondary" disabled={running} onClick={handleEvaluate}>
              ドライラン評価
            </button>
            {/* 単一シンボル実行: enabled=false の場合は無効化して誤操作を防ぐ */}
            <button type="button" className="btn-buy" disabled={running || !config.enabled} onClick={handleRunSymbol}>
              {symbol} を実行
            </button>
            {/* 全シンボル一括実行: 最も影響が大きいため enabled チェック必須 */}
            <button type="button" className="btn-primary" disabled={running || !config.enabled} onClick={handleRunAll}>
              全シンボル実行
            </button>
          </div>

          {/* ドライラン / 実行後の評価結果表示（evaluation データがある場合のみ） */}
          {evaluation && (
            <div className="eval-result" style={{ marginTop: "1rem" }}>
              <h3>評価結果 — {evaluation.symbol}</h3>
              <div className="stat-grid">
                <div className="stat-item">
                  <div className="label">判定</div>
                  <div className={`value ${decisionClass(evaluation.decision)}`}>
                    {decisionLabel(evaluation.decision)}
                  </div>
                </div>
                <div className="stat-item">
                  <div className="label">方向</div>
                  <div className={`value ${evaluation.action === "buy" ? "text-buy" : evaluation.action === "sell" ? "text-sell" : ""}`}>
                    {evaluation.action}
                  </div>
                </div>
                <div className="stat-item">
                  <div className="label">信頼度</div>
                  <div className="value">{evaluation.confidence}%</div>
                </div>
              </div>
              <p className="hint">{evaluation.reason}</p>
              {/* 注文プランが存在する場合（約定・実行可能ステータス時）に SL/TP を表示 */}
              {evaluation.signal_snapshot.order_plan ? (
                <p className="hint">
                  推奨: {evaluation.signal_snapshot.order_plan.side}{" "}
                  {evaluation.signal_snapshot.order_plan.units} units
                  {evaluation.signal_snapshot.order_plan.stop_loss != null && (
                    <> · SL {evaluation.signal_snapshot.order_plan.stop_loss}</>
                  )}
                  {evaluation.signal_snapshot.order_plan.take_profit != null && (
                    <> · TP {evaluation.signal_snapshot.order_plan.take_profit}</>
                  )}
                </p>
              ) : null}
            </div>
          )}
        </div>
      </div>

      {/* === 実行ログカード === */}
      <div className="card" style={{ marginTop: "1.5rem" }}>
        <h2>実行ログ</h2>
        {/* ログが 0 件の場合はガイダンスメッセージを表示 */}
        {runs.length === 0 ? (
          <p className="hint">実行ログはまだありません。ドライラン評価または自動取引を有効化してください。</p>
        ) : (
          <>
            {/* モバイル用: ログをカード形式で表示 */}
            <div className="mobile-only run-log-cards">
              {runs.map((r: AutoTradeRun) => (
                <article key={r.id ?? `${r.symbol}-${r.created_at}`} className="run-log-card">
                  <div className="run-log-card-head">
                    <strong>{r.symbol}</strong>
                    <span className={decisionClass(r.decision)}>{decisionLabel(r.decision)}</span>
                  </div>
                  <p>
                    {r.action} · {r.confidence ?? "—"}% · {r.units ?? "—"} units
                  </p>
                  <p className="hint">{r.reason}</p>
                  <p className="hint">
                    {r.created_at ? new Date(r.created_at).toLocaleString("ja-JP") : "—"} · {r.trigger}
                  </p>
                </article>
              ))}
            </div>
            {/* デスクトップ用: ログをテーブル形式で表示 */}
            <table className="data-table desktop-only">
            <thead>
              <tr>
                <th>時刻</th>
                <th>通貨</th>
                <th>方向</th>
                <th>判定</th>
                <th>信頼度</th>
                <th>数量</th>
                <th>トリガー</th>
                <th>理由</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r: AutoTradeRun) => (
                <tr key={r.id ?? `${r.symbol}-${r.created_at}`}>
                  <td>{r.created_at ? new Date(r.created_at).toLocaleString("ja-JP") : "—"}</td>
                  <td>{r.symbol}</td>
                  {/* 売買方向を色分け表示 */}
                  <td className={r.action === "buy" ? "text-buy" : r.action === "sell" ? "text-sell" : ""}>
                    {r.action}
                  </td>
                  <td className={decisionClass(r.decision)}>{decisionLabel(r.decision)}</td>
                  <td>{r.confidence ?? "—"}%</td>
                  <td>{r.units ?? "—"}</td>
                  <td>{r.trigger}</td>
                  <td>{r.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </>
        )}
      </div>
    </>
  );
}

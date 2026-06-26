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

const SOURCE_LABELS: Record<string, string> = {
  ai: "AI シグナル",
  technical: "テクニカル",
  intelligence: "統合分析",
  mtf: "マルチTF",
  tradingview: "TradingView",
};

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

function decisionClass(d: string) {
  if (d === "executed" || d === "ready") return "text-buy";
  if (d === "blocked" || d === "failed") return "text-sell";
  return "";
}

export default function AutoTradePanel() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [symbol, setSymbol] = useState("USDJPY");
  const [config, setConfig] = useState<AutoTradeConfig | null>(null);
  const [status, setStatus] = useState<AutoTradeStatus | null>(null);
  const [evaluation, setEvaluation] = useState<AutoTradeEvaluateResult | null>(null);
  const [presets, setPresets] = useState<AutoTradePreset[]>([]);
  const [simulation, setSimulation] = useState<AutoTradeSimulation | null>(null);
  const [autoselectMsg, setAutoselectMsg] = useState<string | null>(null);
  const [capital, setCapital] = useState("medium");
  const [horizon, setHorizon] = useState("medium");
  const [riskAppetite, setRiskAppetite] = useState("medium");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfgRes, statusRes] = await Promise.all([getAutoTradeConfig(), getAutoTradeStatus()]);
      setConfig(cfgRes.config);
      setStatus(statusRes);
    } catch (e) {
      setError(e instanceof Error ? e.message : "読み込みに失敗しました");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    getSymbols().then((r) => setSymbols(r.symbols));
    getAutoTradePresets().then((r) => setPresets(r.presets)).catch(() => {});
    load();
  }, [load]);

  const saveConfig = async (patch: Partial<AutoTradeConfig>) => {
    if (!config) return;
    setSaving(true);
    setError(null);
    try {
      const res = await updateAutoTradeConfig(patch);
      setConfig(res.config);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    } finally {
      setSaving(false);
    }
  };

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
      setEvaluation(res);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "実行に失敗しました");
    } finally {
      setRunning(false);
    }
  };

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
      setAutoselectMsg(res.rationale);
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

  const handleSimulate = async () => {
    setRunning(true);
    setError(null);
    try {
      const res = await simulateAutoTrade(symbol, {
        accountBalance: config?.account_balance,
        presetId: config?.strategy_preset ?? "balanced",
      });
      setSimulation(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "シミュレーションに失敗しました");
    } finally {
      setRunning(false);
    }
  };

  if (loading && !config) {
    return <div className="loading">自動取引設定を読み込み中...</div>;
  }

  if (!config) return null;

  const scheduler = status?.scheduler;
  const runs = status?.recent_runs ?? [];
  const performance = status?.performance;
  const openPositions = status?.open_positions ?? [];

  return (
    <>
      <div className="page-header">
        <h1>自動取引エンジン</h1>
        <div className="controls">
          <div className="select-wrapper">
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <button type="button" className="btn-secondary" onClick={load} disabled={loading}>
            更新
          </button>
        </div>
      </div>

      <p className="hint stack-note">
        トライオートFX同様 — プリセット選択 · オートセレクト · シミュレーション · SL/TP 自動決済に対応。
      </p>

      {error && <p className="error-text">{error}</p>}

      {performance && (
        <div className="mobile-only autotrade-mobile-summary">
          <div className="autotrade-mobile-summary-row">
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
          <div className="order-controls">
            <button type="button" className="btn-secondary" disabled={running} onClick={handleEvaluate}>
              ドライラン
            </button>
            <button type="button" className="btn-buy" disabled={running || !config.enabled} onClick={handleRunSymbol}>
              実行
            </button>
          </div>
        </div>
      )}

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
              <strong>{p.label}</strong>
              <span className="hint">{p.description}</span>
              <span className="preset-meta">信頼度 {p.min_confidence}% · RR {p.risk_reward}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="grid-2 desktop-only" style={{ marginBottom: "1.5rem" }}>
        <div className="card">
          <h2>オートセレクト（3 問）</h2>
          <div className="form-grid">
            <label>
              運用資金
              <select value={capital} onChange={(e) => setCapital(e.target.value)}>
                <option value="small">小額 ($5,000)</option>
                <option value="medium">中程度 ($20,000)</option>
                <option value="large">大額 ($100,000)</option>
              </select>
            </label>
            <label>
              運用期間
              <select value={horizon} onChange={(e) => setHorizon(e.target.value)}>
                <option value="short">短期</option>
                <option value="medium">中期</option>
                <option value="long">長期</option>
              </select>
            </label>
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
            <button type="button" className="btn-secondary" disabled={running} onClick={() => handleAutoselect(false)}>
              提案を見る
            </button>
            <button type="button" className="btn-primary" disabled={running} onClick={() => handleAutoselect(true)}>
              適用して保存
            </button>
          </div>
          {autoselectMsg && <p className="hint">{autoselectMsg}</p>}
        </div>

        <div className="card">
          <h2>運用前シミュレーション</h2>
          <p className="hint">{symbol} · 過去 365 日バックテスト + 推奨証拠金</p>
          <button type="button" className="btn-secondary" disabled={running} onClick={handleSimulate}>
            シミュレーション実行
          </button>
          {simulation && (
            <div className="eval-result" style={{ marginTop: "1rem" }}>
              <div className="stat-grid">
                <div className="stat-item">
                  <div className="label">評価</div>
                  <div className="value">{simulation.assessment.grade}</div>
                </div>
                <div className="stat-item">
                  <div className="label">勝率</div>
                  <div className="value">{simulation.backtest.win_rate}%</div>
                </div>
                <div className="stat-item">
                  <div className="label">推奨証拠金</div>
                  <div className="value">${simulation.capital.recommended_margin_usd.toLocaleString()}</div>
                </div>
                <div className="stat-item">
                  <div className="label">安全証拠金</div>
                  <div className="value">${simulation.capital.safe_margin_usd.toLocaleString()}</div>
                </div>
              </div>
              <p className="hint">{simulation.assessment.summary}</p>
            </div>
          )}
        </div>
      </div>

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
            {scheduler?.distributed_lock && (
              <div className="stat-item">
                <div className="label">分散ロック</div>
                <div className="value" style={{ fontSize: "0.85rem" }}>
                  {scheduler.distributed_lock.backend === "redis" ? "Redis" : "単一プロセス"}
                </div>
              </div>
            )}
          </div>
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
                  <td className={p.side === "buy" ? "text-buy" : "text-sell"}>{p.side}</td>
                  <td>{p.units}</td>
                  <td>{p.entry_price}</td>
                  <td>{p.stop_loss ?? "—"}</td>
                  <td>{p.take_profit ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid-2">
        <div className="card">
          <h2>エンジン設定</h2>
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

          <div className="form-grid" style={{ marginTop: "1rem" }}>
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

          <div className="checkbox-stack" style={{ marginTop: "1rem" }}>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={config.require_mtf_alignment}
                onChange={(e) => saveConfig({ require_mtf_alignment: e.target.checked })}
              />
              MTF 方向一致を必須
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={config.auto_execute_tradingview}
                onChange={(e) => saveConfig({ auto_execute_tradingview: e.target.checked })}
              />
              TradingView Webhook で即時実行
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={config.use_stop_loss !== false}
                onChange={(e) => saveConfig({ use_stop_loss: e.target.checked })}
              />
              損切り (SL) を自動設定
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={config.use_take_profit !== false}
                onChange={(e) => saveConfig({ use_take_profit: e.target.checked })}
              />
              利確 (TP) を自動設定
            </label>
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

        <div className="card">
          <h2>スケジューラ & 実行</h2>
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
                <div className="value">{scheduler.trading_mode ?? config.mode ?? "paper"}</div>
              </div>
              <div className="stat-item">
                <div className="label">間隔</div>
                <div className="value">{scheduler.interval_minutes} 分</div>
              </div>
              <div className="stat-item">
                <div className="label">最終実行</div>
                <div className="value" style={{ fontSize: "0.85rem" }}>
                  {scheduler.last_run_at
                    ? new Date(scheduler.last_run_at).toLocaleString("ja-JP")
                    : "—"}
                </div>
              </div>
            </div>
          )}

          <div className="order-controls">
            <button type="button" className="btn-secondary" disabled={running} onClick={handleEvaluate}>
              ドライラン評価
            </button>
            <button type="button" className="btn-buy" disabled={running || !config.enabled} onClick={handleRunSymbol}>
              {symbol} を実行
            </button>
            <button type="button" className="btn-primary" disabled={running || !config.enabled} onClick={handleRunAll}>
              全シンボル実行
            </button>
          </div>

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

      <div className="card" style={{ marginTop: "1.5rem" }}>
        <h2>実行ログ</h2>
        {runs.length === 0 ? (
          <p className="hint">実行ログはまだありません。ドライラン評価または自動取引を有効化してください。</p>
        ) : (
          <>
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

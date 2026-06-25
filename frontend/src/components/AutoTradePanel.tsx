"use client";

import { useCallback, useEffect, useState } from "react";
import {
  evaluateAutoTrade,
  getAutoTradeConfig,
  getAutoTradeStatus,
  getSymbols,
  runAutoTradeAll,
  runAutoTradeSymbol,
  updateAutoTradeConfig,
} from "@/lib/api";
import type { AutoTradeConfig, AutoTradeEvaluateResult, AutoTradeRun, AutoTradeStatus } from "@/types";

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

  if (loading && !config) {
    return <div className="loading">自動取引設定を読み込み中...</div>;
  }

  if (!config) return null;

  const scheduler = status?.scheduler;
  const runs = status?.recent_runs ?? [];

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
        AI・テクニカル・統合分析・MTF・TradingView を加重統合し、リスクガード通過後に OANDA / ペーパーで自動約定します。
      </p>

      {error && <p className="error-text">{error}</p>}

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
          </div>
        </div>

        <div className="card">
          <h2>スケジューラ & 実行</h2>
          {scheduler && (
            <div className="stat-grid" style={{ marginBottom: "1rem" }}>
              <div className="stat-item">
                <div className="label">スケジューラ</div>
                <div className="value">{scheduler.scheduler_running ? "稼働中" : "停止"}</div>
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
              <div className="stat-item">
                <div className="label">有効テナント</div>
                <div className="value">{scheduler.enabled_tenants}</div>
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
              {evaluation.signal_snapshot?.order_plan && (
                <p className="hint">
                  推奨: {(evaluation.signal_snapshot.order_plan as { side: string; units: number }).side}{" "}
                  {(evaluation.signal_snapshot.order_plan as { units: number }).units} units
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="card" style={{ marginTop: "1.5rem" }}>
        <h2>実行ログ</h2>
        {runs.length === 0 ? (
          <p className="hint">実行ログはまだありません。ドライラン評価または自動取引を有効化してください。</p>
        ) : (
          <table className="data-table">
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
        )}
      </div>
    </>
  );
}

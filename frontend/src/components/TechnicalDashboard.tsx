"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getTechnicalAnalysis,
  getTradingSignals,
  getMLPrediction,
  getSymbols,
  syncMarketData,
  getChartUrl,
  SOURCE_LABELS,
} from "@/lib/api";
import type { TechnicalAnalysis, TradingSignal, MLPrediction } from "@/types";
import PriceChart, { OscillatorChart } from "@/components/Chart";
import SignalPanel from "@/components/SignalPanel";
import MultiTimeframePanel from "@/components/MultiTimeframePanel";
import PositionSizePanel from "@/components/PositionSizePanel";
import BacktestPanel from "@/components/BacktestPanel";
import EventAlertBanner from "@/components/EventAlertBanner";

type IndicatorTab = "price" | "bb" | "ichimoku" | "rsi" | "macd" | "stochastic";

const DAY_OPTIONS = [90, 200, 365];

export default function TechnicalDashboard() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [symbol, setSymbol] = useState("USDJPY");
  const [days, setDays] = useState(200);
  const [data, setData] = useState<TechnicalAnalysis | null>(null);
  const [signals, setSignals] = useState<TradingSignal[]>([]);
  const [price, setPrice] = useState(0);
  const [prediction, setPrediction] = useState<MLPrediction | null>(null);
  const [activeTab, setActiveTab] = useState<IndicatorTab>("price");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [tech, sig, pred] = await Promise.all([
        getTechnicalAnalysis(symbol, days),
        getTradingSignals(symbol, days),
        getMLPrediction(symbol, days),
      ]);
      setData(tech);
      setSignals(sig.signals);
      setPrice(sig.price);
      setPrediction(pred);
    } catch (e) {
      setError(e instanceof Error ? e.message : "データ取得に失敗しました");
    } finally {
      setLoading(false);
    }
  }, [symbol, days]);

  useEffect(() => {
    getSymbols().then((res) => setSymbols(res.symbols));
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSync = async () => {
    setSyncing(true);
    setError(null);
    try {
      await syncMarketData(symbol, days);
      await loadData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "同期に失敗しました");
    } finally {
      setSyncing(false);
    }
  };

  if (loading && !data) {
    return <div className="loading">データを読み込み中...</div>;
  }

  const tabs: { key: IndicatorTab; label: string }[] = [
    { key: "price", label: "価格 + MA" },
    { key: "bb", label: "ボリンジャーバンド" },
    { key: "ichimoku", label: "一目均衡表" },
    { key: "rsi", label: "RSI" },
    { key: "macd", label: "MACD" },
    { key: "stochastic", label: "ストキャスティクス" },
  ];

  return (
    <>
      <EventAlertBanner />
      <div className="page-header">
        <h1>テクニカル分析</h1>
        <div className="controls">
          <div className="select-wrapper">
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="select-wrapper">
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
              {DAY_OPTIONS.map((d) => (
                <option key={d} value={d}>{d}日</option>
              ))}
            </select>
          </div>
          <button className="btn" onClick={handleSync} disabled={syncing}>
            {syncing ? "同期中..." : "データ同期"}
          </button>
          <a className="btn btn-secondary" href={getChartUrl(symbol, days)} target="_blank" rel="noreferrer">
            チャート画像
          </a>
        </div>
      </div>

      {data?.source && (
        <div className="source-badge">
          データソース: {SOURCE_LABELS[data.source] ?? data.source}
        </div>
      )}

      {error && <div className="error-banner">{error}</div>}

      {data && (
        <>
          <div className="stat-grid" style={{ marginBottom: "1.5rem" }}>
            <div className="stat-item">
              <div className="label">終値</div>
              <div className="value">{data.latest.close}</div>
            </div>
            <div className="stat-item">
              <div className="label">RSI (14)</div>
              <div className="value">{data.latest.rsi?.toFixed(1) ?? "-"}</div>
            </div>
            <div className="stat-item">
              <div className="label">MACD</div>
              <div className="value">{data.latest.macd?.toFixed(4) ?? "-"}</div>
            </div>
            {prediction?.status === "success" && (
              <>
                <div className="stat-item">
                  <div className="label">ML予測価格</div>
                  <div className="value">{prediction.prediction}</div>
                </div>
                <div className="stat-item">
                  <div className="label">モデル精度 (R²)</div>
                  <div className="value">{prediction.test_r2}</div>
                </div>
              </>
            )}
          </div>

          <MultiTimeframePanel symbol={symbol} />

          <div className="grid-2">
            <div className="card" style={{ gridColumn: "1 / -1" }}>
              <div className="tabs">
                {tabs.map((tab) => (
                  <button
                    key={tab.key}
                    className={`tab ${activeTab === tab.key ? "active" : ""}`}
                    onClick={() => setActiveTab(tab.key)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              {activeTab === "price" && <PriceChart data={data} showMA />}
              {activeTab === "bb" && <PriceChart data={data} showBB />}
              {activeTab === "ichimoku" && <PriceChart data={data} showIchimoku />}
              {activeTab === "rsi" && <OscillatorChart data={data} type="rsi" />}
              {activeTab === "macd" && <OscillatorChart data={data} type="macd" />}
              {activeTab === "stochastic" && <OscillatorChart data={data} type="stochastic" />}
            </div>

            <SignalPanel signals={signals} price={price} symbol={symbol} />
            <PositionSizePanel symbol={symbol} price={price} days={days} />
            <BacktestPanel symbol={symbol} days={days} />
          </div>
        </>
      )}
    </>
  );
}

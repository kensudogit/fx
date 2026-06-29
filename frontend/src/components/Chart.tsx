/**
 * React コンポーネント — Chart
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Area,
  ReferenceLine,
} from "recharts";
import type { TechnicalAnalysis } from "@/types";

interface PriceChartProps {
  data: TechnicalAnalysis;
  showMA?: boolean;
  showBB?: boolean;
  showIchimoku?: boolean;
}

export default function PriceChart({
  data,
  showMA = true,
  showBB = false,
  showIchimoku = false,
}: PriceChartProps) {
  const chartData = data.timestamps.map((ts, i) => ({
    date: ts.slice(5, 10),
    close: data.ohlcv.close[i],
    sma20: data.indicators.ma.sma_20[i],
    sma50: data.indicators.ma.sma_50[i],
    bbUpper: data.indicators.bollinger_bands.upper[i],
    bbMiddle: data.indicators.bollinger_bands.middle[i],
    bbLower: data.indicators.bollinger_bands.lower[i],
    tenkan: data.indicators.ichimoku.tenkan[i],
    kijun: data.indicators.ichimoku.kijun[i],
    senkouA: data.indicators.ichimoku.senkou_a[i],
    senkouB: data.indicators.ichimoku.senkou_b[i],
  }));

  return (
    <ResponsiveContainer width="100%" height={400}>
      <ComposedChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
        <XAxis
          dataKey="date"
          tick={{ fill: "var(--text-secondary)", fontSize: 11 }}
          interval="preserveStartEnd"
        />
        <YAxis
          domain={["auto", "auto"]}
          tick={{ fill: "var(--text-secondary)", fontSize: 11 }}
        />
        <Tooltip
          contentStyle={{
            background: "var(--bg-card)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            color: "var(--text-primary)",
          }}
        />
        {showBB && (
          <>
            <Area
              dataKey="bbUpper"
              stroke="none"
              fill="rgba(59, 130, 246, 0.05)"
              connectNulls
            />
            <Line
              dataKey="bbUpper"
              stroke="#3b82f6"
              strokeWidth={1}
              dot={false}
              connectNulls
            />
            <Line
              dataKey="bbMiddle"
              stroke="#3b82f6"
              strokeWidth={1}
              strokeDasharray="4 4"
              dot={false}
              connectNulls
            />
            <Line
              dataKey="bbLower"
              stroke="#3b82f6"
              strokeWidth={1}
              dot={false}
              connectNulls
            />
          </>
        )}
        {showIchimoku && (
          <>
            <Line dataKey="tenkan" stroke="#ef4444" strokeWidth={1} dot={false} connectNulls />
            <Line dataKey="kijun" stroke="#3b82f6" strokeWidth={1} dot={false} connectNulls />
            <Line dataKey="senkouA" stroke="#22c55e" strokeWidth={1} dot={false} connectNulls />
            <Line dataKey="senkouB" stroke="#f59e0b" strokeWidth={1} dot={false} connectNulls />
          </>
        )}
        <Line
          dataKey="close"
          stroke="#e8edf4"
          strokeWidth={2}
          dot={false}
          connectNulls
        />
        {showMA && (
          <>
            <Line
              dataKey="sma20"
              stroke="#f59e0b"
              strokeWidth={1}
              dot={false}
              connectNulls
            />
            <Line
              dataKey="sma50"
              stroke="#8b5cf6"
              strokeWidth={1}
              dot={false}
              connectNulls
            />
          </>
        )}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

interface OscillatorChartProps {
  data: TechnicalAnalysis;
  type: "rsi" | "macd" | "stochastic";
}

export function OscillatorChart({ data, type }: OscillatorChartProps) {
  const chartData = data.timestamps.map((ts, i) => ({
    date: ts.slice(5, 10),
    rsi: data.indicators.rsi[i],
    macd: data.indicators.macd.macd[i],
    signal: data.indicators.macd.signal[i],
    histogram: data.indicators.macd.histogram[i],
    stochK: data.indicators.stochastic.k[i],
    stochD: data.indicators.stochastic.d[i],
  }));

  if (type === "rsi") {
    return (
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
          <XAxis dataKey="date" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis domain={[0, 100]} tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
          <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text-primary)" }} />
          <ReferenceLine y={70} stroke="#ef4444" strokeDasharray="3 3" />
          <ReferenceLine y={30} stroke="#22c55e" strokeDasharray="3 3" />
          <Line dataKey="rsi" stroke="#8b5cf6" strokeWidth={2} dot={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (type === "macd") {
    return (
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
          <XAxis dataKey="date" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
          <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text-primary)" }} />
          <Bar dataKey="histogram" fill="#3b82f6" opacity={0.5} />
          <Line dataKey="macd" stroke="#f59e0b" strokeWidth={2} dot={false} connectNulls />
          <Line dataKey="signal" stroke="#ef4444" strokeWidth={1} dot={false} connectNulls />
        </ComposedChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
        <XAxis dataKey="date" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} interval="preserveStartEnd" />
        <YAxis domain={[0, 100]} tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
        <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text-primary)" }} />
        <ReferenceLine y={80} stroke="#ef4444" strokeDasharray="3 3" />
        <ReferenceLine y={20} stroke="#22c55e" strokeDasharray="3 3" />
        <Line dataKey="stochK" stroke="#3b82f6" strokeWidth={2} dot={false} connectNulls />
        <Line dataKey="stochD" stroke="#f59e0b" strokeWidth={1} dot={false} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  );
}

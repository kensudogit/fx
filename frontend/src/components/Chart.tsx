/**
 * @file Chart.tsx
 * @description FX チャートコンポーネント集 — Recharts を用いた価格・オシレーター描画
 *
 * 本ファイルには 2 種類のグラフコンポーネントが含まれる：
 *   - PriceChart    : ローソク足の終値ラインチャート + MA / ボリンジャーバンド / 一目均衡表
 *   - OscillatorChart: RSI / MACD / ストキャスティクスのいずれかを表示するサブチャート
 *
 * データは TechnicalAnalysis 型として外部から受け取り、内部で Recharts 用フォーマットに変換する。
 *
 * カラースキーム:
 *   - 終値ライン    : #e8edf4（明るいグレー）
 *   - SMA20         : #f59e0b（アンバー）
 *   - SMA50         : #8b5cf6（パープル）
 *   - BBバンド      : #3b82f6（ブルー）
 *   - 一目（転換線）: #ef4444（レッド）
 *   - 一目（基準線）: #3b82f6（ブルー）
 *   - 一目（先行A） : #22c55e（グリーン）
 *   - 一目（先行B） : #f59e0b（アンバー）
 *   - RSI ライン    : #8b5cf6（パープル）
 *   - MACD ヒスト   : #3b82f6（ブルー、透明度 50%）
 *   - MACD ライン   : #f59e0b（アンバー）
 *   - シグナル      : #ef4444（レッド）
 *   - Stoch %K      : #3b82f6（ブルー）
 *   - Stoch %D      : #f59e0b（アンバー）
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

/**
 * PriceChartProps — PriceChart コンポーネントのプロップス型
 */
interface PriceChartProps {
  /** テクニカル分析データ（OHLCV + インジケーター値の時系列配列を含む） */
  data: TechnicalAnalysis;
  /** SMA20 / SMA50 ラインを表示するか（デフォルト: true） */
  showMA?: boolean;
  /** ボリンジャーバンドを表示するか（デフォルト: false） */
  showBB?: boolean;
  /** 一目均衡表（転換線・基準線・先行スパン）を表示するか（デフォルト: false） */
  showIchimoku?: boolean;
}

/**
 * PriceChart
 *
 * FX 通貨ペアの終値ラインチャートを描画する主要グラフコンポーネント。
 * ComposedChart を使用して終値ライン・MA・BB・一目均衡表を重ね合わせる。
 *
 * データ変換:
 *   TechnicalAnalysis の配列データを日付をキーとするオブジェクト配列に変換し Recharts に渡す。
 *   timestamps は "YYYY-MM-DD" 形式で、slice(5,10) で "MM-DD" 表示に短縮する。
 *
 * 軸設定:
 *   - X 軸: 日付（MM-DD 形式）、両端のラベルを preserveStartEnd で維持
 *   - Y 軸: domain=["auto","auto"] で価格レンジに自動追従
 *
 * @param data         - テクニカル分析データ
 * @param showMA       - MA ライン表示フラグ
 * @param showBB       - ボリンジャーバンド表示フラグ
 * @param showIchimoku - 一目均衡表表示フラグ
 */
export default function PriceChart({
  data,
  showMA = true,
  showBB = false,
  showIchimoku = false,
}: PriceChartProps) {
  /**
   * TechnicalAnalysis の各時系列配列を Recharts 用データポイントに変換する。
   * timestamps[i] は "YYYY-MM-DD" 形式 → slice(5,10) で "MM-DD" を取り出す。
   * null の可能性があるインジケーター値は connectNulls で線を繋ぐ。
   */
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

  // 親要素の幅に 100% 追従、高さ 400px 固定
  return (
    <ResponsiveContainer width="100%" height={400}>
      {/* ComposedChart: Line + Bar + Area を混在させるための複合チャート */}
      <ComposedChart data={chartData}>
        {/* グリッド線: "3 3" = 3px 実線 3px 空白のダッシュパターン */}
        <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
        {/* X 軸: 日付（MM-DD）、preserveStartEnd で最初と最後のラベルを必ず表示 */}
        <XAxis
          dataKey="date"
          tick={{ fill: "var(--text-secondary)", fontSize: 11 }}
          interval="preserveStartEnd"
        />
        {/* Y 軸: 価格レンジに自動追従（auto）、フォント 11px */}
        <YAxis
          domain={["auto", "auto"]}
          tick={{ fill: "var(--text-secondary)", fontSize: 11 }}
        />
        {/* ツールチップ: ダークテーマに合わせたカードスタイル */}
        <Tooltip
          contentStyle={{
            background: "var(--bg-card)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            color: "var(--text-primary)",
          }}
        />

        {/* ボリンジャーバンド（showBB=true のときのみ描画） */}
        {showBB && (
          <>
            {/* 上バンドと下バンドの間を薄いブルーで塗り潰してチャネルを視覚化 */}
            <Area
              dataKey="bbUpper"
              stroke="none"
              fill="rgba(59, 130, 246, 0.05)"
              connectNulls
            />
            {/* 上バンドライン: ブルー #3b82f6、幅 1px */}
            <Line
              dataKey="bbUpper"
              stroke="#3b82f6"
              strokeWidth={1}
              dot={false}
              connectNulls
            />
            {/* 中央線（SMA20 相当）: ブルー・破線（strokeDasharray="4 4"） */}
            <Line
              dataKey="bbMiddle"
              stroke="#3b82f6"
              strokeWidth={1}
              strokeDasharray="4 4"
              dot={false}
              connectNulls
            />
            {/* 下バンドライン: ブルー #3b82f6、幅 1px */}
            <Line
              dataKey="bbLower"
              stroke="#3b82f6"
              strokeWidth={1}
              dot={false}
              connectNulls
            />
          </>
        )}

        {/* 一目均衡表（showIchimoku=true のときのみ描画） */}
        {showIchimoku && (
          <>
            {/* 転換線（直近 9 日間の高値+安値の中値）: レッド #ef4444 */}
            <Line dataKey="tenkan" stroke="#ef4444" strokeWidth={1} dot={false} connectNulls />
            {/* 基準線（直近 26 日間の高値+安値の中値）: ブルー #3b82f6 */}
            <Line dataKey="kijun" stroke="#3b82f6" strokeWidth={1} dot={false} connectNulls />
            {/* 先行スパン A（転換線+基準線の平均、26 日先行）: グリーン #22c55e */}
            <Line dataKey="senkouA" stroke="#22c55e" strokeWidth={1} dot={false} connectNulls />
            {/* 先行スパン B（直近 52 日間の中値、26 日先行）: アンバー #f59e0b */}
            <Line dataKey="senkouB" stroke="#f59e0b" strokeWidth={1} dot={false} connectNulls />
          </>
        )}

        {/* 終値ライン: 常に最前面に描画するため最後に配置。明るいグレー #e8edf4、幅 2px */}
        <Line
          dataKey="close"
          stroke="#e8edf4"
          strokeWidth={2}
          dot={false}
          connectNulls
        />

        {/* 移動平均線（showMA=true のときのみ描画） */}
        {showMA && (
          <>
            {/* SMA20（短期移動平均）: アンバー #f59e0b、幅 1px */}
            <Line
              dataKey="sma20"
              stroke="#f59e0b"
              strokeWidth={1}
              dot={false}
              connectNulls
            />
            {/* SMA50（中期移動平均）: パープル #8b5cf6、幅 1px */}
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

/**
 * OscillatorChartProps — OscillatorChart コンポーネントのプロップス型
 */
interface OscillatorChartProps {
  /** テクニカル分析データ（OHLCV + インジケーター値の時系列配列を含む） */
  data: TechnicalAnalysis;
  /** 表示するオシレーターの種類 */
  type: "rsi" | "macd" | "stochastic";
}

/**
 * OscillatorChart
 *
 * RSI / MACD / ストキャスティクスのいずれかを表示するサブチャートコンポーネント。
 * type プロップスに応じて異なるグラフレイアウトを返す（高さ 200px 固定）。
 * 親コンポーネント（テクニカル分析画面等）の価格チャート下部に配置して使用する。
 *
 * ## type ごとのグラフ仕様
 *
 * ### RSI（Relative Strength Index）
 *   - Y 軸: 0〜100 固定（オシレーターの振れ幅を統一）
 *   - 参照線: 70（買われすぎ・赤破線）/ 30（売られすぎ・緑破線）
 *   - ラインカラー: パープル #8b5cf6、幅 2px
 *
 * ### MACD（Moving Average Convergence/Divergence）
 *   - ヒストグラム（MACD - Signal の差分）: ブルー #3b82f6、透明度 50%
 *   - MACD ライン（短期 EMA - 長期 EMA）: アンバー #f59e0b、幅 2px
 *   - シグナルライン（MACD の 9 日 EMA）: レッド #ef4444、幅 1px
 *
 * ### ストキャスティクス（Stochastic Oscillator）
 *   - Y 軸: 0〜100 固定
 *   - 参照線: 80（買われすぎ・赤破線）/ 20（売られすぎ・緑破線）
 *   - %K ライン（高速ライン）: ブルー #3b82f6、幅 2px
 *   - %D ライン（%K の平滑化・低速ライン）: アンバー #f59e0b、幅 1px
 *
 * @param data - テクニカル分析データ
 * @param type - 表示するオシレーターの種類
 */
export function OscillatorChart({ data, type }: OscillatorChartProps) {
  /**
   * TechnicalAnalysis の各指標配列を Recharts 用データポイントに変換する。
   * 全オシレーターのデータをあらかじめ統合し、type に応じて使用するキーを切り替える。
   */
  const chartData = data.timestamps.map((ts, i) => ({
    date: ts.slice(5, 10),
    rsi: data.indicators.rsi[i],
    macd: data.indicators.macd.macd[i],
    signal: data.indicators.macd.signal[i],
    histogram: data.indicators.macd.histogram[i],
    stochK: data.indicators.stochastic.k[i],
    stochD: data.indicators.stochastic.d[i],
  }));

  // RSI チャート: Y 軸 0-100 固定、参照線 70/30 付き
  if (type === "rsi") {
    return (
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
          <XAxis dataKey="date" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} interval="preserveStartEnd" />
          {/* Y 軸を 0-100 に固定してオシレーターの振れ幅を一定に表示 */}
          <YAxis domain={[0, 100]} tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
          <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text-primary)" }} />
          {/* 70 ライン: RSI の買われすぎ境界（レッド破線） */}
          <ReferenceLine y={70} stroke="#ef4444" strokeDasharray="3 3" />
          {/* 30 ライン: RSI の売られすぎ境界（グリーン破線） */}
          <ReferenceLine y={30} stroke="#22c55e" strokeDasharray="3 3" />
          {/* RSI ライン: パープル #8b5cf6、幅 2px */}
          <Line dataKey="rsi" stroke="#8b5cf6" strokeWidth={2} dot={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // MACD チャート: ComposedChart でヒストグラム（Bar）とライン（Line）を混在
  if (type === "macd") {
    return (
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
          <XAxis dataKey="date" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} interval="preserveStartEnd" />
          {/* MACD は 0 を中心に正負の値をとるため自動スケールを使用 */}
          <YAxis tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
          <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text-primary)" }} />
          {/* MACD ヒストグラム: MACD - Signal の差分を棒グラフで視覚化、ブルー・透明度 50% */}
          <Bar dataKey="histogram" fill="#3b82f6" opacity={0.5} />
          {/* MACD ライン（短期 EMA - 長期 EMA）: アンバー #f59e0b、幅 2px */}
          <Line dataKey="macd" stroke="#f59e0b" strokeWidth={2} dot={false} connectNulls />
          {/* シグナルライン（MACD の 9 日 EMA）: レッド #ef4444、幅 1px */}
          <Line dataKey="signal" stroke="#ef4444" strokeWidth={1} dot={false} connectNulls />
        </ComposedChart>
      </ResponsiveContainer>
    );
  }

  // ストキャスティクスチャート（type === "stochastic"）: Y 軸 0-100 固定、参照線 80/20 付き
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
        <XAxis dataKey="date" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} interval="preserveStartEnd" />
        {/* Y 軸を 0-100 に固定して RSI と同スケールで比較しやすくする */}
        <YAxis domain={[0, 100]} tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
        <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text-primary)" }} />
        {/* 80 ライン: ストキャスティクスの買われすぎ境界（レッド破線） */}
        <ReferenceLine y={80} stroke="#ef4444" strokeDasharray="3 3" />
        {/* 20 ライン: ストキャスティクスの売られすぎ境界（グリーン破線） */}
        <ReferenceLine y={20} stroke="#22c55e" strokeDasharray="3 3" />
        {/* %K ライン（高速ライン）: ブルー #3b82f6、幅 2px */}
        <Line dataKey="stochK" stroke="#3b82f6" strokeWidth={2} dot={false} connectNulls />
        {/* %D ライン（%K の 3 日平滑化・低速ライン）: アンバー #f59e0b、幅 1px */}
        <Line dataKey="stochD" stroke="#f59e0b" strokeWidth={1} dot={false} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  );
}

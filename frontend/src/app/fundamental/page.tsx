/**
 * @file fundamental/page.tsx
 * @description ファンダメンタル分析ページ
 *
 * URL: /fundamental
 *
 * 主要機能:
 * - 米国雇用統計・CPI・FOMC・日銀政策決定会合・GDP などの経済指標データ表示
 * - FRED API または内製サンプルデータによる実績・予想・前回値の比較テーブル
 * - 今後の主要経済イベントカレンダーと残り日数バッジ
 * - イベントタイプタブによる指標切り替え
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

"use client";

import { useEffect, useState } from "react";
import { getFundamentalData, getCalendar } from "@/lib/api";
import type { FundamentalData, CalendarEvent } from "@/types";

/**
 * 経済指標イベントタイプの定義
 * - key: API レスポンスおよびステート管理で使用する識別子
 * - label: ユーザーに表示する日本語ラベル
 */
const EVENT_TYPES = [
  { key: "us_employment", label: "米国雇用統計" },
  { key: "cpi", label: "CPI" },
  { key: "fomc", label: "FOMC" },
  { key: "boj", label: "日銀政策決定会合" },
  { key: "gdp", label: "GDP" },
];

/**
 * daysUntil - 指定日付までの残り日数を計算するユーティリティ関数
 *
 * @param dateStr - 対象日付の文字列（ISO 8601 形式 "YYYY-MM-DD" を想定）
 * @returns 今日から対象日までの残り日数（当日は 0 以下を返す）
 */
function daysUntil(dateStr: string): number {
  const target = new Date(dateStr);
  const now = new Date();
  // ミリ秒差を 1 日のミリ秒数（86400000ms）で割り、切り上げて日数を算出
  return Math.ceil((target.getTime() - now.getTime()) / 86400000);
}

/**
 * FundamentalPage コンポーネント
 *
 * ファンダメンタル分析ページのメインコンポーネント。
 * 初期表示時に経済指標データと経済イベントカレンダーを並行取得し、
 * 左カラム：指標タブ切り替えテーブル
 * 右カラム：今後のイベントカレンダー
 * の 2 カラムレイアウトで表示する。
 */
export default function FundamentalPage() {
  // 経済指標データ全体（イベントタイプをキーとするマップ）
  const [data, setData] = useState<FundamentalData | null>(null);

  // 経済イベントカレンダーの一覧（日付・タイトル・国・影響度）
  const [calendar, setCalendar] = useState<CalendarEvent[]>([]);

  // 現在選択中の経済指標タイプ（デフォルト: 米国雇用統計）
  const [activeType, setActiveType] = useState("us_employment");

  // データ取得中かどうかを示すローディングフラグ
  const [loading, setLoading] = useState(true);

  /**
   * 初回マウント時にファンダメンタルデータとカレンダーを並行取得する
   * - getFundamentalData(): POST /api/fundamental — 各経済指標の実績・予想・前回値
   * - getCalendar(): GET /api/calendar — 今後の経済イベント一覧
   * 両リクエストを Promise.all で並列実行し、どちらかが失敗しても
   * finally でローディング状態を解除する
   */
  useEffect(() => {
    Promise.all([getFundamentalData(), getCalendar()])
      .then(([fund, cal]) => {
        setData(fund);
        setCalendar(cal.events);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  // データ取得中またはデータが未取得の場合はローディング表示を返す
  if (loading || !data) {
    return <div className="loading">データを読み込み中...</div>;
  }

  // 現在選択中のタイプに対応する経済指標データを取得
  const activeData = data.events[activeType];

  return (
    <>
      <h1 style={{ fontSize: "1.5rem", marginBottom: "1.5rem" }}>
        ファンダメンタル分析
      </h1>

      {/* 2 カラムグリッド: 左=経済指標テーブル / 右=イベントカレンダー */}
      <div className="grid-2">
        {/* 左カラム: 経済指標タブと詳細テーブル */}
        <div className="card">
          <h2>経済指標</h2>
          {/* イベントタイプ切り替えタブ（米雇用統計・CPI・FOMC等） */}
          <div className="tabs">
            {EVENT_TYPES.map((et) => (
              <button
                key={et.key}
                className={`tab ${activeType === et.key ? "active" : ""}`}
                onClick={() => setActiveType(et.key)}
              >
                {et.label}
              </button>
            ))}
          </div>

          {/* 選択中のイベントタイプのデータが存在する場合のみ表示 */}
          {activeData && (
            <>
              {/* データソース（FRED API か内製サンプルか）を明示する注記 */}
              <p style={{ color: "var(--text-secondary)", fontSize: "0.85rem", marginBottom: "1rem" }}>
                データソース: {activeData.source === "FRED" ? "FRED API" : "サンプルデータ"}
              </p>
              {/* 経済指標の実績・予想・前回値・単位を時系列で表示するテーブル */}
              <table>
                <thead>
                  <tr>
                    <th>日付</th>
                    <th>実績</th>
                    <th>予想</th>
                    <th>前回</th>
                    <th>単位</th>
                  </tr>
                </thead>
                <tbody>
                  {activeData.data.map((row, i) => (
                    <tr key={i}>
                      <td>{row.date}</td>
                      {/* 実績値は太字で強調表示 */}
                      <td style={{ fontWeight: 600 }}>{row.value}</td>
                      {/* 予想・前回・単位はデータが無い場合はハイフン表示 */}
                      <td>{row.forecast ?? "-"}</td>
                      <td>{row.previous ?? "-"}</td>
                      <td>{row.unit ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>

        {/* 右カラム: 今後の経済イベントカレンダー */}
        <div className="card">
          <h2>経済イベントカレンダー</h2>
          {/* 日付・残り日数・イベント名・対象国・影響度を一覧表示するテーブル */}
          <table>
            <thead>
              <tr>
                <th>日付</th>
                <th>あと</th>
                <th>イベント</th>
                <th>国</th>
                <th>影響度</th>
              </tr>
            </thead>
            <tbody>
              {calendar.map((event, i) => {
                // イベントまでの残り日数を計算
                const left = daysUntil(event.date);
                return (
                <tr key={i}>
                  <td>{event.date}</td>
                  <td>
                    {/* 残り日数に応じたバッジ表示:
                        0 以下: 「本日」（警告バッジ）
                        1〜3 日: 「X 日」（警告バッジ）
                        4 日以上: プレーンテキストで日数表示 */}
                    {left <= 0 ? (
                      <span className="badge badge-warn">本日</span>
                    ) : left <= 3 ? (
                      <span className="badge badge-warn">{left}日</span>
                    ) : (
                      `${left}日`
                    )}
                  </td>
                  <td>{event.title}</td>
                  <td>{event.country}</td>
                  {/* 影響度クラスで色分け表示（high=高、その他=中） */}
                  <td className={`impact-${event.impact}`}>
                    {event.impact === "high" ? "高" : "中"}
                  </td>
                </tr>
              );})}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

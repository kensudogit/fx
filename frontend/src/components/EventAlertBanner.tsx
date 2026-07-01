/**
 * @file EventAlertBanner.tsx
 * @description 重要経済イベントアラートバナー — 差し迫った高影響指標を画面上部に通知
 *
 * コンポーネントがマウントされると getEventAlerts(72) を呼び出し、
 * 直近 72 時間以内に予定されている高影響経済指標イベントを取得する。
 * 取得したイベントの中で最も近いものをバナーに表示し、
 * 追加件数がある場合は「他 N 件」と補足する。
 *
 * イベントが 0 件の場合はバナー自体を非表示にする（null を返す）ため、
 * 親レイアウトに影響を与えない。
 *
 * クリック可能な「カレンダー →」リンクで経済指標カレンダーページに遷移できる。
 */

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getEventAlerts } from "@/lib/api";
import type { EventAlert } from "@/types";

/**
 * EventAlertBanner
 *
 * 重要経済イベントが 72 時間以内に予定されている場合に表示するバナーコンポーネント。
 * 画面最上部または主要コンテンツの直上に配置して、トレーダーに事前警告を与える。
 *
 * アラートがない場合は null を返して何も表示しないため、
 * イベントのない平常時はレイアウトに余分なスペースが生まれない。
 */
export default function EventAlertBanner() {
  /** 直近 72 時間以内の高影響イベント一覧 — 初期値は空配列 */
  const [alerts, setAlerts] = useState<EventAlert[]>([]);

  /**
   * マウント時に経済イベントアラートを取得する副作用
   * 72 時間以内のイベントをフェッチし、エラー発生時は空配列にフォールバックして
   * バナーを非表示にする（エラー表示はしない）
   * 依存配列が空なのでコンポーネント初期化時に 1 回のみ実行される
   */
  useEffect(() => {
    getEventAlerts(72).then((r) => setAlerts(r.alerts)).catch(() => setAlerts([]));
  }, []);

  /** アラートが 0 件の場合はバナーを非表示（親レイアウトに影響を与えない） */
  if (alerts.length === 0) return null;

  /** 最も近いイベント（先頭要素）をバナーに強調表示する */
  const next = alerts[0];

  return (
    <div className="event-alert-banner">
      <strong>⚠ 重要イベント間近</strong>
      <span>
        {/* 最近接イベントのタイトル・国・残り時間を表示 */}
        {next.title}（{next.country}）— あと約 {Math.ceil(next.hours_until)} 時間
        {/* 2 件以上のアラートがある場合は残件数を「他 N 件」で補足 */}
        {alerts.length > 1 && ` 他 ${alerts.length - 1} 件`}
      </span>
      {/* 経済指標カレンダーページへの内部リンク */}
      <Link href="/fundamental">カレンダー →</Link>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getEventAlerts } from "@/lib/api";
import type { EventAlert } from "@/types";

export default function EventAlertBanner() {
  const [alerts, setAlerts] = useState<EventAlert[]>([]);

  useEffect(() => {
    getEventAlerts(72).then((r) => setAlerts(r.alerts)).catch(() => setAlerts([]));
  }, []);

  if (alerts.length === 0) return null;

  const next = alerts[0];

  return (
    <div className="event-alert-banner">
      <strong>⚠ 重要イベント間近</strong>
      <span>
        {next.title}（{next.country}）— あと約 {Math.ceil(next.hours_until)} 時間
        {alerts.length > 1 && ` 他 ${alerts.length - 1} 件`}
      </span>
      <Link href="/fundamental">カレンダー →</Link>
    </div>
  );
}

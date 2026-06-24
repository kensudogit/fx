"use client";

import { useEffect, useState } from "react";
import { getFundamentalData, getCalendar } from "@/lib/api";
import type { FundamentalData, CalendarEvent } from "@/types";

const EVENT_TYPES = [
  { key: "us_employment", label: "米国雇用統計" },
  { key: "cpi", label: "CPI" },
  { key: "fomc", label: "FOMC" },
  { key: "boj", label: "日銀政策決定会合" },
  { key: "gdp", label: "GDP" },
];

export default function FundamentalPage() {
  const [data, setData] = useState<FundamentalData | null>(null);
  const [calendar, setCalendar] = useState<CalendarEvent[]>([]);
  const [activeType, setActiveType] = useState("us_employment");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getFundamentalData(), getCalendar()])
      .then(([fund, cal]) => {
        setData(fund);
        setCalendar(cal.events);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading || !data) {
    return <div className="loading">データを読み込み中...</div>;
  }

  const activeData = data.events[activeType];

  return (
    <>
      <h1 style={{ fontSize: "1.5rem", marginBottom: "1.5rem" }}>
        ファンダメンタル分析
      </h1>

      <div className="grid-2">
        <div className="card">
          <h2>経済指標</h2>
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

          {activeData && (
            <>
              <p style={{ color: "var(--text-secondary)", fontSize: "0.85rem", marginBottom: "1rem" }}>
                データソース: {activeData.source === "FRED" ? "FRED API" : "サンプルデータ"}
              </p>
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
                      <td style={{ fontWeight: 600 }}>{row.value}</td>
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

        <div className="card">
          <h2>経済イベントカレンダー</h2>
          <table>
            <thead>
              <tr>
                <th>日付</th>
                <th>イベント</th>
                <th>国</th>
                <th>影響度</th>
              </tr>
            </thead>
            <tbody>
              {calendar.map((event, i) => (
                <tr key={i}>
                  <td>{event.date}</td>
                  <td>{event.title}</td>
                  <td>{event.country}</td>
                  <td className={`impact-${event.impact}`}>
                    {event.impact === "high" ? "高" : "中"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

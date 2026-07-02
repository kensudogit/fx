"""
FX Platform - 商用グレード テストレポートジェネレーター

pytest-json-report の JSON 出力を読み込み、
プロフェッショナルデザインの HTML レポートを生成する。

使い方:
    python generate_report.py                      # tests/report/results.json → tests/report/test_report.html
    python generate_report.py --input foo.json     # 入力ファイルを指定
    python generate_report.py --output bar.html    # 出力ファイルを指定
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ────────────────────────────────────────────────
# テストモジュール日本語マッピング
# ────────────────────────────────────────────────
MODULE_LABELS: dict[str, dict] = {
    "test_01_security": {
        "label": "01. セキュリティ",
        "icon": "🔐",
        "desc": "パスワードハッシュ / JWT / API キー / 暗号化",
    },
    "test_02_technical_indicators": {
        "label": "02. テクニカル指標",
        "icon": "📈",
        "desc": "SMA / EMA / ボリンジャーバンド / MACD / RSI",
    },
    "test_03_trading_signals": {
        "label": "03. 売買シグナル",
        "icon": "🚦",
        "desc": "シグナル生成 / バイアス集計 / バックテスト",
    },
    "test_04_pnl_position_sizing": {
        "label": "04. PnL・ポジションサイジング",
        "icon": "💰",
        "desc": "Pip 計算 / ロット算定 / 損益集計",
    },
    "test_05_strategy_presets": {
        "label": "05. 戦略プリセット",
        "icon": "⚙️",
        "desc": "プリセット一覧 / 適用 / バリデーション",
    },
    "test_06_simulation": {
        "label": "06. シミュレーション",
        "icon": "🔬",
        "desc": "バックテスト実行 / グレード評価 / 推奨資金",
    },
    "test_07_cache_infra": {
        "label": "07. キャッシュ・インフラ",
        "icon": "⚡",
        "desc": "キャッシュキー / put/get / SaaS プラン定義",
    },
    "test_08_api_endpoints": {
        "label": "08. API エンドポイント",
        "icon": "🌐",
        "desc": "/health / presets / simulate / CORS",
    },
}


def _module_key(nodeid: str) -> str:
    """nodeid からモジュールキーを抽出する。"""
    parts = nodeid.split("::")
    filename = parts[0].split("/")[-1].replace(".py", "")
    return filename


def _class_name(nodeid: str) -> str:
    parts = nodeid.split("::")
    return parts[1] if len(parts) >= 3 else "—"


def _test_name(nodeid: str) -> str:
    parts = nodeid.split("::")
    raw = parts[-1] if parts else nodeid
    return raw.replace("test_", "").replace("_", " ")


def _skip_reason(test: dict) -> str:
    """スキップ理由をテストデータから取得する。"""
    for phase in ("setup", "call", "teardown"):
        phase_data = test.get(phase, {})
        longrepr = phase_data.get("longrepr", "")
        if longrepr:
            # "Skipped: ..." 形式から理由部分を抽出
            m = re.search(r"Skipped:\s*(.+)", str(longrepr))
            if m:
                return m.group(1).strip()[:120]
    return "—"


def _duration_ms(test: dict) -> float:
    """合計実行時間をミリ秒で返す。"""
    total = 0.0
    for phase in ("setup", "call", "teardown"):
        total += test.get(phase, {}).get("duration", 0.0)
    return round(total * 1000, 1)


def build_report(data: dict) -> str:
    """JSON データから HTML 文字列を生成する。"""
    summary = data.get("summary", {})
    tests: list[dict] = data.get("tests", [])
    env = data.get("environment", {})
    created_ts: float = data.get("created", 0)
    duration_total: float = data.get("duration", 0.0)

    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    skipped = summary.get("skipped", 0)
    errors = summary.get("errors", 0)
    total = summary.get("total", len(tests))
    pass_rate = round(passed / total * 100) if total else 0

    # 日時フォーマット
    if created_ts:
        dt = datetime.fromtimestamp(created_ts, tz=timezone.utc).astimezone()
        created_str = dt.strftime("%Y年%m月%d日 %H:%M:%S")
    else:
        created_str = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")

    python_ver = env.get("Python", "—")
    platform_str = env.get("Platform", "—")

    # モジュール別集計
    modules: dict[str, dict] = {}
    for t in tests:
        mk = _module_key(t["nodeid"])
        if mk not in modules:
            modules[mk] = {"passed": 0, "failed": 0, "skipped": 0, "total": 0, "tests": []}
        modules[mk]["total"] += 1
        modules[mk][t["outcome"]] = modules[mk].get(t["outcome"], 0) + 1
        modules[mk]["tests"].append(t)

    # ────────── テスト行 HTML ──────────
    rows_html = ""
    for t in tests:
        outcome = t["outcome"]
        cls = {"passed": "row-pass", "failed": "row-fail", "skipped": "row-skip"}.get(outcome, "row-skip")
        badge = {
            "passed": '<span class="badge badge-pass">PASS</span>',
            "failed": '<span class="badge badge-fail">FAIL</span>',
            "skipped": '<span class="badge badge-skip">SKIP</span>',
        }.get(outcome, '<span class="badge badge-skip">—</span>')
        dur = _duration_ms(t)
        skip_msg = _skip_reason(t) if outcome == "skipped" else ""
        rows_html += f"""
        <tr class="{cls}" data-outcome="{outcome}">
          <td class="td-badge">{badge}</td>
          <td class="td-module">{MODULE_LABELS.get(_module_key(t['nodeid']), {}).get('label', _module_key(t['nodeid']))}</td>
          <td class="td-class">{_class_name(t['nodeid'])}</td>
          <td class="td-test">{_test_name(t['nodeid'])}{f'<br><span class="skip-msg">{skip_msg}</span>' if skip_msg else ''}</td>
          <td class="td-dur">{dur} ms</td>
        </tr>"""

    # ────────── モジュールカード HTML ──────────
    module_cards_html = ""
    for mk, mdata in modules.items():
        info = MODULE_LABELS.get(mk, {"label": mk, "icon": "🧪", "desc": ""})
        m_total = mdata["total"]
        m_passed = mdata.get("passed", 0)
        m_failed = mdata.get("failed", 0)
        m_skipped = mdata.get("skipped", 0)
        m_rate = round(m_passed / m_total * 100) if m_total else 0
        status_cls = "card-fail" if m_failed > 0 else ("card-skip" if m_passed == 0 else "card-pass")
        module_cards_html += f"""
        <div class="module-card {status_cls}">
          <div class="mc-header">
            <span class="mc-icon">{info['icon']}</span>
            <span class="mc-label">{info['label']}</span>
          </div>
          <p class="mc-desc">{info['desc']}</p>
          <div class="mc-bar-bg">
            <div class="mc-bar-fill" style="width:{m_rate}%"></div>
          </div>
          <div class="mc-stats">
            <span class="mc-pass">✓ {m_passed}</span>
            <span class="mc-skip">― {m_skipped}</span>
            <span class="mc-fail">✗ {m_failed}</span>
            <span class="mc-rate">{m_rate}%</span>
          </div>
        </div>"""

    # ────────── HTML テンプレート ──────────
    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FX Platform — テスト結果レポート</title>
<style>
/* ===== RESET & BASE ===== */
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#0a0f1e;
  --bg2:#0f1628;
  --bg3:#1a2235;
  --card:#141d2e;
  --card2:#1e2a3d;
  --border:#1f2e45;
  --border2:#2a3d5a;
  --text:#e2e8f0;
  --text2:#94a3b8;
  --text3:#64748b;
  --accent:#38bdf8;
  --accent2:#0ea5e9;
  --green:#22c55e;
  --green2:#16a34a;
  --red:#ef4444;
  --red2:#dc2626;
  --yellow:#f59e0b;
  --yellow2:#d97706;
  --radius:12px;
  --shadow:0 4px 24px rgba(0,0,0,0.4);
}}
html{{scroll-behavior:smooth}}
body{{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans JP',sans-serif;
  background:var(--bg);
  color:var(--text);
  min-height:100vh;
  font-size:14px;
  line-height:1.6;
}}

/* ===== GRID BACKGROUND ===== */
body::before{{
  content:'';
  position:fixed;
  inset:0;
  background-image:
    linear-gradient(rgba(56,189,248,0.03) 1px,transparent 1px),
    linear-gradient(90deg,rgba(56,189,248,0.03) 1px,transparent 1px);
  background-size:40px 40px;
  pointer-events:none;
  z-index:0;
}}

/* ===== LAYOUT ===== */
.container{{
  max-width:1280px;
  margin:0 auto;
  padding:0 24px 60px;
  position:relative;
  z-index:1;
}}

/* ===== HEADER ===== */
.header{{
  display:flex;
  align-items:center;
  justify-content:space-between;
  padding:28px 0 24px;
  border-bottom:1px solid var(--border);
  margin-bottom:36px;
  flex-wrap:wrap;
  gap:16px;
}}
.header-left{{display:flex;align-items:center;gap:16px}}
.logo{{
  width:48px;height:48px;
  background:linear-gradient(135deg,var(--accent2),#6366f1);
  border-radius:12px;
  display:flex;align-items:center;justify-content:center;
  font-size:22px;
  box-shadow:0 0 20px rgba(56,189,248,0.3);
}}
.header-title h1{{
  font-size:22px;font-weight:700;
  background:linear-gradient(90deg,var(--accent),#a78bfa);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  background-clip:text;
}}
.header-title p{{font-size:12px;color:var(--text3);margin-top:2px}}
.header-meta{{
  display:flex;flex-direction:column;align-items:flex-end;gap:4px;
  font-size:12px;color:var(--text3);
}}
.header-meta .meta-item{{display:flex;align-items:center;gap:6px}}
.status-dot{{
  width:8px;height:8px;border-radius:50%;
  background:{'var(--green)' if failed == 0 else 'var(--red)'};
  box-shadow:0 0 8px {'rgba(34,197,94,0.5)' if failed == 0 else 'rgba(239,68,68,0.5)'};
  animation:pulse 2s infinite;
}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:0.4}}}}

/* ===== KPI CARDS ===== */
.kpi-grid{{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
  gap:16px;
  margin-bottom:36px;
}}
.kpi-card{{
  background:var(--card);
  border:1px solid var(--border);
  border-radius:var(--radius);
  padding:24px;
  position:relative;
  overflow:hidden;
  transition:transform .2s,box-shadow .2s;
}}
.kpi-card:hover{{transform:translateY(-2px);box-shadow:var(--shadow)}}
.kpi-card::before{{
  content:'';position:absolute;top:0;left:0;right:0;height:3px;
}}
.kpi-total::before{{background:linear-gradient(90deg,var(--accent),#6366f1)}}
.kpi-pass::before{{background:linear-gradient(90deg,var(--green),#10b981)}}
.kpi-skip::before{{background:linear-gradient(90deg,var(--yellow),#f97316)}}
.kpi-fail::before{{background:linear-gradient(90deg,var(--red),#f43f5e)}}
.kpi-rate::before{{background:linear-gradient(90deg,var(--accent2),#818cf8)}}
.kpi-icon{{font-size:28px;margin-bottom:12px;display:block}}
.kpi-value{{
  font-size:42px;font-weight:800;line-height:1;
  margin-bottom:6px;
}}
.kpi-total .kpi-value{{color:var(--accent)}}
.kpi-pass .kpi-value{{color:var(--green)}}
.kpi-skip .kpi-value{{color:var(--yellow)}}
.kpi-fail .kpi-value{{color:{' var(--red)' if failed > 0 else 'var(--text3)'}}}
.kpi-rate .kpi-value{{
  background:linear-gradient(90deg,var(--accent),#818cf8);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  background-clip:text;
}}
.kpi-label{{font-size:12px;color:var(--text3);font-weight:500;text-transform:uppercase;letter-spacing:.08em}}

/* ===== PASS RATE BAR ===== */
.pass-rate-section{{
  background:var(--card);
  border:1px solid var(--border);
  border-radius:var(--radius);
  padding:24px;
  margin-bottom:36px;
}}
.prs-header{{
  display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;
}}
.prs-title{{font-size:15px;font-weight:600;color:var(--text)}}
.prs-pct{{
  font-size:28px;font-weight:800;
  background:linear-gradient(90deg,var(--green),var(--accent));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  background-clip:text;
}}
.bar-track{{
  height:12px;background:var(--bg3);border-radius:6px;overflow:hidden;
}}
.bar-fill{{
  height:100%;border-radius:6px;
  background:linear-gradient(90deg,var(--green2),var(--green),var(--accent));
  width:{pass_rate}%;
  transition:width 1s ease;
  position:relative;
}}
.bar-fill::after{{
  content:'';position:absolute;top:0;left:0;right:0;bottom:0;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,0.15),transparent);
  animation:shimmer 2s infinite;
}}
@keyframes shimmer{{0%{{transform:translateX(-100%)}}100%{{transform:translateX(100%)}}}}
.bar-legend{{
  display:flex;gap:20px;margin-top:12px;
}}
.bar-legend-item{{
  display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text2);
}}
.legend-dot{{width:8px;height:8px;border-radius:2px}}

/* ===== SECTION TITLE ===== */
.section-title{{
  font-size:16px;font-weight:700;color:var(--text);
  margin-bottom:16px;
  display:flex;align-items:center;gap:8px;
}}
.section-title::after{{
  content:'';flex:1;height:1px;background:var(--border);
}}

/* ===== MODULE CARDS ===== */
.module-grid{{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
  gap:16px;
  margin-bottom:36px;
}}
.module-card{{
  background:var(--card);
  border:1px solid var(--border);
  border-radius:var(--radius);
  padding:20px;
  transition:transform .2s,box-shadow .2s;
  position:relative;
  overflow:hidden;
}}
.module-card:hover{{transform:translateY(-2px);box-shadow:var(--shadow)}}
.module-card::before{{
  content:'';position:absolute;left:0;top:0;bottom:0;width:3px;
}}
.card-pass::before{{background:var(--green)}}
.card-fail::before{{background:var(--red)}}
.card-skip::before{{background:var(--yellow)}}
.mc-header{{display:flex;align-items:center;gap:10px;margin-bottom:8px}}
.mc-icon{{font-size:20px}}
.mc-label{{font-size:14px;font-weight:600;color:var(--text)}}
.mc-desc{{font-size:11px;color:var(--text3);margin-bottom:14px;line-height:1.5}}
.mc-bar-bg{{height:6px;background:var(--bg3);border-radius:3px;overflow:hidden;margin-bottom:12px}}
.mc-bar-fill{{height:100%;border-radius:3px;background:linear-gradient(90deg,var(--green2),var(--green));transition:width .8s ease}}
.mc-stats{{display:flex;gap:12px;font-size:12px}}
.mc-pass{{color:var(--green)}}
.mc-skip{{color:var(--yellow)}}
.mc-fail{{color:var(--red)}}
.mc-rate{{margin-left:auto;color:var(--accent);font-weight:600}}

/* ===== FILTER TABS ===== */
.filter-bar{{
  display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;
}}
.filter-btn{{
  padding:6px 16px;border-radius:20px;border:1px solid var(--border2);
  background:var(--card2);color:var(--text2);font-size:12px;font-weight:500;
  cursor:pointer;transition:all .15s;
}}
.filter-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.filter-btn.active{{background:var(--accent2);border-color:var(--accent2);color:#fff}}
.filter-btn.active-pass{{background:var(--green2);border-color:var(--green);color:#fff}}
.filter-btn.active-skip{{background:var(--yellow2);border-color:var(--yellow);color:#fff}}
.filter-btn.active-fail{{background:var(--red2);border-color:var(--red);color:#fff}}

/* ===== TABLE ===== */
.table-wrapper{{
  background:var(--card);
  border:1px solid var(--border);
  border-radius:var(--radius);
  overflow:hidden;
  margin-bottom:40px;
}}
.results-table{{
  width:100%;border-collapse:collapse;font-size:13px;
}}
.results-table thead{{
  background:var(--bg3);
  border-bottom:1px solid var(--border2);
}}
.results-table th{{
  padding:12px 16px;text-align:left;
  font-size:11px;font-weight:600;
  text-transform:uppercase;letter-spacing:.06em;
  color:var(--text3);
}}
.results-table tbody tr{{
  border-bottom:1px solid var(--border);
  transition:background .1s;
}}
.results-table tbody tr:last-child{{border-bottom:none}}
.results-table tbody tr:hover{{background:var(--card2)}}
.results-table td{{padding:11px 16px;vertical-align:middle}}
.td-badge{{width:70px}}
.td-module{{width:220px;color:var(--text2);font-size:12px}}
.td-class{{width:200px;color:var(--text3);font-size:12px}}
.td-test{{color:var(--text)}}
.td-dur{{width:90px;text-align:right;color:var(--text3);font-size:12px;font-variant-numeric:tabular-nums}}

/* ===== BADGES ===== */
.badge{{
  display:inline-block;padding:3px 10px;border-radius:4px;
  font-size:10px;font-weight:700;letter-spacing:.06em;
}}
.badge-pass{{background:rgba(34,197,94,.15);color:var(--green);border:1px solid rgba(34,197,94,.3)}}
.badge-fail{{background:rgba(239,68,68,.15);color:var(--red);border:1px solid rgba(239,68,68,.3)}}
.badge-skip{{background:rgba(245,158,11,.15);color:var(--yellow);border:1px solid rgba(245,158,11,.3)}}

/* ===== ROW COLORS ===== */
.row-fail{{background:rgba(239,68,68,.04)}}
.row-skip{{background:rgba(245,158,11,.03)}}
.row-pass{{background:transparent}}

/* ===== SKIP MESSAGE ===== */
.skip-msg{{font-size:11px;color:var(--text3);margin-top:2px;display:block;font-style:italic}}

/* ===== ENV SECTION ===== */
.env-grid{{
  display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:12px;
  background:var(--card);border:1px solid var(--border);
  border-radius:var(--radius);padding:20px;
  margin-bottom:40px;
}}
.env-item{{}}
.env-key{{font-size:11px;color:var(--text3);font-weight:600;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}}
.env-val{{font-size:13px;color:var(--text2)}}

/* ===== FOOTER ===== */
.footer{{
  text-align:center;color:var(--text3);font-size:12px;
  padding:24px 0;border-top:1px solid var(--border);
}}
.footer a{{color:var(--accent);text-decoration:none}}

/* ===== HIDDEN ===== */
.hidden{{display:none!important}}

/* ===== RESPONSIVE ===== */
@media(max-width:768px){{
  .header{{flex-direction:column;align-items:flex-start}}
  .header-meta{{align-items:flex-start}}
  .kpi-grid{{grid-template-columns:1fr 1fr}}
  .td-class,.td-module{{display:none}}
}}
</style>
</head>
<body>
<div class="container">

  <!-- ===== HEADER ===== -->
  <header class="header">
    <div class="header-left">
      <div class="logo">📊</div>
      <div class="header-title">
        <h1>FX Platform</h1>
        <p>テスト結果レポート — 顧客プレゼンテーション用</p>
      </div>
    </div>
    <div class="header-meta">
      <div class="meta-item">
        <span class="status-dot"></span>
        <span>{'全テスト PASS' if failed == 0 else f'{failed} 件の失敗'}</span>
      </div>
      <div class="meta-item">🕐 {created_str}</div>
      <div class="meta-item">⏱ 実行時間: {duration_total:.2f}s</div>
      <div class="meta-item">🐍 Python {python_ver}</div>
    </div>
  </header>

  <!-- ===== KPI CARDS ===== -->
  <div class="kpi-grid">
    <div class="kpi-card kpi-total">
      <span class="kpi-icon">🧪</span>
      <div class="kpi-value">{total}</div>
      <div class="kpi-label">総テスト数</div>
    </div>
    <div class="kpi-card kpi-pass">
      <span class="kpi-icon">✅</span>
      <div class="kpi-value">{passed}</div>
      <div class="kpi-label">Passed（成功）</div>
    </div>
    <div class="kpi-card kpi-skip">
      <span class="kpi-icon">⏭️</span>
      <div class="kpi-value">{skipped}</div>
      <div class="kpi-label">Skipped（スキップ）</div>
    </div>
    <div class="kpi-card kpi-fail">
      <span class="kpi-icon">{'❌' if failed > 0 else '🎯'}</span>
      <div class="kpi-value">{failed}</div>
      <div class="kpi-label">Failed（失敗）</div>
    </div>
    <div class="kpi-card kpi-rate">
      <span class="kpi-icon">🏆</span>
      <div class="kpi-value">{pass_rate}%</div>
      <div class="kpi-label">合格率</div>
    </div>
  </div>

  <!-- ===== PASS RATE BAR ===== -->
  <div class="pass-rate-section">
    <div class="prs-header">
      <span class="prs-title">テスト合格率</span>
      <span class="prs-pct">{pass_rate}%</span>
    </div>
    <div class="bar-track">
      <div class="bar-fill"></div>
    </div>
    <div class="bar-legend">
      <div class="bar-legend-item"><div class="legend-dot" style="background:var(--green)"></div>Passed: {passed}</div>
      <div class="bar-legend-item"><div class="legend-dot" style="background:var(--yellow)"></div>Skipped: {skipped}</div>
      <div class="bar-legend-item"><div class="legend-dot" style="background:var(--red)"></div>Failed: {failed}</div>
    </div>
  </div>

  <!-- ===== MODULE BREAKDOWN ===== -->
  <div class="section-title">モジュール別テスト結果</div>
  <div class="module-grid">
    {module_cards_html}
  </div>

  <!-- ===== RESULTS TABLE ===== -->
  <div class="section-title">テスト詳細一覧</div>

  <div class="filter-bar">
    <button class="filter-btn active" onclick="filterRows('all', this)">すべて ({total})</button>
    <button class="filter-btn" onclick="filterRows('passed', this)">✓ Passed ({passed})</button>
    <button class="filter-btn" onclick="filterRows('skipped', this)">― Skipped ({skipped})</button>
    <button class="filter-btn" onclick="filterRows('failed', this)">✗ Failed ({failed})</button>
  </div>

  <div class="table-wrapper">
    <table class="results-table" id="resultsTable">
      <thead>
        <tr>
          <th>結果</th>
          <th>モジュール</th>
          <th>クラス</th>
          <th>テスト名</th>
          <th style="text-align:right">実行時間</th>
        </tr>
      </thead>
      <tbody id="tableBody">
        {rows_html}
      </tbody>
    </table>
  </div>

  <!-- ===== ENVIRONMENT ===== -->
  <div class="section-title">実行環境</div>
  <div class="env-grid">
    <div class="env-item"><div class="env-key">Python</div><div class="env-val">{python_ver}</div></div>
    <div class="env-item"><div class="env-key">Platform</div><div class="env-val">{platform_str}</div></div>
    <div class="env-item"><div class="env-key">実行日時</div><div class="env-val">{created_str}</div></div>
    <div class="env-item"><div class="env-key">総実行時間</div><div class="env-val">{duration_total:.3f} 秒</div></div>
    <div class="env-item"><div class="env-key">合格率</div><div class="env-val">{pass_rate}% ({passed}/{total})</div></div>
    <div class="env-item"><div class="env-key">ステータス</div><div class="env-val" style="color:{'var(--green)' if failed==0 else 'var(--red)'}">{'✅ 全テスト合格' if failed==0 else f'⚠ {failed}件の失敗'}</div></div>
  </div>

  <!-- ===== FOOTER ===== -->
  <footer class="footer">
    <p>FX Platform — 自動生成テストレポート &nbsp;|&nbsp; {created_str} &nbsp;|&nbsp;
    <a href="/">ホームへ戻る</a></p>
  </footer>

</div>

<script>
function filterRows(outcome, btn) {{
  document.querySelectorAll('.filter-btn').forEach(b => {{
    b.classList.remove('active','active-pass','active-skip','active-fail');
  }});
  const classMap = {{passed:'active-pass', skipped:'active-skip', failed:'active-fail', all:'active'}};
  btn.classList.add(classMap[outcome] || 'active');

  document.querySelectorAll('#tableBody tr').forEach(row => {{
    if (outcome === 'all') {{
      row.classList.remove('hidden');
    }} else {{
      row.dataset.outcome === outcome
        ? row.classList.remove('hidden')
        : row.classList.add('hidden');
    }}
  }});
}}

// カウントアップアニメーション
function countUp(el, target, duration) {{
  let start = 0;
  const step = target / (duration / 16);
  const tick = () => {{
    start = Math.min(start + step, target);
    el.textContent = Math.floor(start);
    if (start < target) requestAnimationFrame(tick);
  }};
  requestAnimationFrame(tick);
}}
document.querySelectorAll('.kpi-value').forEach(el => {{
  const val = parseInt(el.textContent);
  if (!isNaN(val)) {{ el.textContent = '0'; countUp(el, val, 800); }}
}});
</script>
</body>
</html>"""
    return html


def main() -> int:
    parser = argparse.ArgumentParser(description="FX Platform テストレポートジェネレーター")
    parser.add_argument(
        "--input", "-i",
        default="tests/report/results.json",
        help="pytest-json-report の出力 JSON ファイル (default: tests/report/results.json)",
    )
    parser.add_argument(
        "--output", "-o",
        default="tests/report/test_report.html",
        help="出力 HTML ファイルパス (default: tests/report/test_report.html)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"[ERROR] JSON ファイルが見つかりません: {input_path}", file=sys.stderr)
        return 1

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    html = build_report(data)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    summary = data.get("summary", {})
    print(f"[OK] レポートを生成しました: {output_path}")
    print(f"     Passed: {summary.get('passed',0)}  Skipped: {summary.get('skipped',0)}  "
          f"Failed: {summary.get('failed',0)}  Total: {summary.get('total',0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

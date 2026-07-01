"""
ファンダメンタル分析データ取得・管理モジュール

米国連邦準備銀行（FRED API）および Finnhub 経済カレンダー API から
主要経済指標（雇用統計・CPI・FOMC・BOJ・GDP）のデータを取得し、
予想値・前回値と組み合わせた分析用データセットを提供する。

データ取得の優先順位:
  1. FRED API（fred_api_key が設定されている場合）
  2. Finnhub 経済カレンダー（finnhub_api_key が設定されている場合）
  3. 組み込みサンプルデータ / テンプレートイベント（フォールバック）

キャッシュ戦略:
  - 経済カレンダーは 3600 秒（1時間）のメモリキャッシュを使用する。
  - FRED データは呼び出し毎に取得（キャッシュなし）。
"""

from datetime import date, datetime, timedelta
from enum import Enum
import logging

import httpx
import pandas as pd

from src.config import settings

logger = logging.getLogger(__name__)

# ---- モジュールレベルのキャッシュ変数 ----
# 経済カレンダーのインメモリキャッシュ。None の場合は未取得。
_calendar_cache: list[dict] | None = None
# カレンダーデータのソース識別文字列（"finnhub" | "template"）
_calendar_source: str = "template"
# 最後にカレンダーを取得した日時。キャッシュ有効期限の計算に使用する。
_calendar_fetched_at: datetime | None = None


class EventType(str, Enum):
    """主要経済イベントの種別を表す列挙型。

    str を継承することで、辞書キーやJSON シリアライズに値文字列をそのまま使用できる。

    Attributes:
        US_EMPLOYMENT: 米国非農業部門雇用者数（NFP）。毎月第1金曜日発表。
        CPI: 消費者物価指数（Consumer Price Index）。インフレ動向を示す重要指標。
        FOMC: 連邦公開市場委員会の政策金利決定。年8回開催。
        BOJ: 日本銀行金融政策決定会合。年8回開催。
        GDP: 国内総生産成長率（Gross Domestic Product）。経済全体の成長を示す。
    """
    US_EMPLOYMENT = "us_employment"
    CPI = "cpi"
    FOMC = "fomc"
    BOJ = "boj"
    GDP = "gdp"


# 各 EventType に対応する日本語ラベル文字列のマッピング。
# UI 表示やレポート生成で使用する。
EVENT_LABELS = {
    EventType.US_EMPLOYMENT: "米国雇用統計",
    EventType.CPI: "CPI（消費者物価指数）",
    EventType.FOMC: "FOMC",
    EventType.BOJ: "日銀政策決定会合",
    EventType.GDP: "GDP",
}

# FRED（Federal Reserve Economic Data）のシリーズ ID マッピング。
# 各 EventType に対応する FRED の公式シリーズ ID を紐付ける。
# PAYEMS: 非農業部門雇用者数（月次・千人単位）
# CPIAUCSL: 都市部消費者物価指数（月次・季節調整済み）
# GDP: 実質 GDP 成長率（四半期・年率換算）
FRED_SERIES = {
    EventType.US_EMPLOYMENT: "PAYEMS",  # Nonfarm Payrolls
    EventType.CPI: "CPIAUCSL",  # CPI All Urban Consumers
    EventType.GDP: "GDP",  # Gross Domestic Product
}


async def fetch_fred_series(series_id: str, limit: int = 24) -> list[dict]:
    """FRED API から指定シリーズの経済指標データを取得する。

    St. Louis 連邦準備銀行が提供する FRED API を使用し、
    指定した経済指標の観測値を降順（最新から）で取得する。

    Args:
        series_id: FRED のシリーズ ID（例: "PAYEMS", "CPIAUCSL", "GDP"）。
        limit: 取得する最大件数。デフォルト 24 件（約2年分を想定）。

    Returns:
        観測値の辞書リスト。各要素は {"date": "YYYY-MM-DD", "value": float}。
        API キー未設定・通信失敗・非200レスポンスの場合は空リストを返す。

    Raises:
        この関数は例外を握りつぶし、失敗時は空リストを返す設計。
    """
    # fred_api_key が未設定の場合は API 呼び出しをスキップ
    if not settings.fred_api_key:
        return []

    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "sort_order": "desc",  # 最新データを先頭に取得
        "limit": limit,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params=params)
        if response.status_code != 200:
            return []
        data = response.json()

    observations = []
    for obs in data.get("observations", []):
        # FRED API は欠損値を "." 文字列で返すため、スキップする
        if obs["value"] == ".":
            continue
        observations.append(
            {
                "date": obs["date"],
                "value": float(obs["value"]),
            }
        )
    return observations


def get_sample_fundamental_data() -> dict[str, list[dict]]:
    """APIキー未設定時のフォールバック用サンプルファンダメンタルデータを返す。

    FRED API キーが設定されていない環境でも動作確認や UI 表示ができるよう、
    実際の過去データに基づいたサンプルデータを提供する。
    各指標データは [実績値, 予想値, 前回値] のフォーマットで格納されている。

    Returns:
        EventType.value をキーとする辞書。各値はデータポイントのリスト（降順）。
        各データポイントのキー:
          date: 発表日（YYYY-MM-DD 形式）
          value: 実績値
          previous: 前回値
          forecast: 市場予想値
          unit: 単位（"千人", "%", など）
          title: 指標名称（オプション）
    """
    return {
        # 米国非農業部門雇用者数（NFP）: 単位は千人
        # 予想を大幅に上回る場合は USD 買い要因、下回る場合は USD 売り要因となる
        EventType.US_EMPLOYMENT.value: [
            {"date": "2025-01-03", "value": 256000, "previous": 212000, "forecast": 165000, "unit": "千人"},
            {"date": "2024-12-06", "value": 227000, "previous": 119000, "forecast": 200000, "unit": "千人"},
            {"date": "2024-11-01", "value": 12000, "previous": 223000, "forecast": 113000, "unit": "千人"},
        ],
        # 消費者物価指数（CPI）: 前年同月比（%）で表示
        # 予想を上回るインフレは利上げ期待を高め USD 買い要因
        EventType.CPI.value: [
            {"date": "2025-01-15", "value": 3.0, "previous": 2.7, "forecast": 2.9, "unit": "%"},
            {"date": "2024-12-11", "value": 2.7, "previous": 2.6, "forecast": 2.7, "unit": "%"},
            {"date": "2024-11-13", "value": 2.6, "previous": 2.4, "forecast": 2.6, "unit": "%"},
        ],
        # FOMC 政策金利（FF レート）: 単位は %
        # 利上げ（value > previous）は USD 買い、利下げは USD 売り要因
        EventType.FOMC.value: [
            {"date": "2025-01-29", "value": 4.50, "previous": 4.50, "forecast": 4.50, "unit": "%", "title": "政策金利"},
            {"date": "2024-12-18", "value": 4.50, "previous": 4.75, "forecast": 4.50, "unit": "%", "title": "政策金利"},
            {"date": "2024-11-07", "value": 4.75, "previous": 5.00, "forecast": 4.75, "unit": "%", "title": "政策金利"},
        ],
        # 日本銀行政策金利（無担保コールレート翌日物）: 単位は %
        # 利上げ（value > previous）は JPY 買い（円高）要因
        EventType.BOJ.value: [
            {"date": "2025-01-24", "value": 0.50, "previous": 0.25, "forecast": 0.50, "unit": "%", "title": "政策金利"},
            {"date": "2024-12-19", "value": 0.25, "previous": 0.25, "forecast": 0.25, "unit": "%", "title": "政策金利"},
            {"date": "2024-10-31", "value": 0.25, "previous": 0.25, "forecast": 0.25, "unit": "%", "title": "政策金利"},
        ],
        # 米国 GDP 成長率（前期比年率換算、%）
        # 予想を上回る成長は USD 買い要因、下回る場合は景気後退懸念として USD 売り要因
        EventType.GDP.value: [
            {"date": "2025-01-30", "value": 2.3, "previous": 3.1, "forecast": 2.6, "unit": "%", "title": "米国GDP成長率"},
            {"date": "2024-10-30", "value": 2.8, "previous": 3.0, "forecast": 2.8, "unit": "%", "title": "米国GDP成長率"},
            {"date": "2024-07-25", "value": 2.8, "previous": 1.4, "forecast": 2.0, "unit": "%", "title": "米国GDP成長率"},
        ],
    }


async def get_fundamental_data(event_type: EventType | None = None) -> dict:
    """ファンダメンタル分析データを取得する。

    FRED API が利用可能な場合は実データを取得し、利用不可の場合はサンプルデータで補完する。
    event_type を指定すると対象指標のみ取得でき、省略すると全指標を返す。

    取得優先順位（指標ごとに個別に判定）:
      1. FRED_SERIES に登録されており、かつ fred_api_key が設定されている → FRED API
      2. 上記条件を満たさない、または FRED API が空応答 → サンプルデータ

    Args:
        event_type: 取得する指標の種別。None の場合は全 EventType を処理する。

    Returns:
        EventType.value をキーとする辞書。各値は以下のキーを持つ辞書:
          label: 日本語の指標名
          source: データソース識別文字列（"FRED" | "sample"）
          data: データポイントのリスト（降順）
    """
    # フォールバック用のサンプルデータを事前に用意する
    sample = get_sample_fundamental_data()

    # event_type が指定されている場合はその1件のみ処理、なければ全指標を処理
    if event_type:
        types = [event_type]
    else:
        types = list(EventType)

    result = {}
    for et in types:
        label = EVENT_LABELS[et]
        # FRED シリーズが存在し、かつ API キーが設定されている場合のみ実データを取得する
        if et in FRED_SERIES and settings.fred_api_key:
            fred_data = await fetch_fred_series(FRED_SERIES[et])
            if fred_data:
                result[et.value] = {
                    "label": label,
                    "source": "FRED",
                    "data": fred_data,
                }
                continue  # FRED データが取得できた場合はサンプルをスキップ

        # FRED が使えない場合はサンプルデータを使用する
        result[et.value] = {
            "label": label,
            "source": "sample",
            "data": sample.get(et.value, []),
        }

    return result


def get_upcoming_events() -> list[dict]:
    """今後の経済イベントリストを返す（キャッシュ優先）。

    キャッシュが存在する場合（Finnhub API から取得済み）はキャッシュを返し、
    キャッシュが存在しない場合はテンプレートベースの静的イベントを返す。

    Returns:
        経済イベント辞書のリスト（日付昇順）。
        各要素のキー: date, event_type, title, country, impact。
    """
    if _calendar_cache:
        return _calendar_cache
    # キャッシュ未取得の場合は静的テンプレートを返す
    return _template_events()


def get_calendar_source() -> str:
    """現在のカレンダーデータソース識別文字列を返す。

    Returns:
        "finnhub"（API から取得済み）または "template"（テンプレート使用中）。
    """
    return _calendar_source


async def refresh_economic_calendar(force: bool = False) -> list[dict]:
    """Finnhub API から経済カレンダーを更新する（1時間キャッシュ）。

    更新ロジック:
      1. キャッシュが有効（1時間以内）かつ force=False の場合 → キャッシュをそのまま返す。
      2. finnhub_api_key が設定されている場合 → Finnhub API から取得を試みる。
      3. API 取得に失敗した場合 → テンプレートイベントにフォールバックする。

    Args:
        force: True の場合、キャッシュの有効期限に関わらず強制的に再取得する。

    Returns:
        最新の経済イベント辞書リスト（日付昇順）。
    """
    global _calendar_cache, _calendar_source, _calendar_fetched_at

    now = datetime.now()
    # キャッシュが有効かどうかを確認（3600秒 = 1時間以内に取得済みか）
    if (
        not force
        and _calendar_cache
        and _calendar_fetched_at
        and (now - _calendar_fetched_at).total_seconds() < 3600
    ):
        return _calendar_cache

    # Finnhub API キーが設定されている場合は実データ取得を試みる
    if settings.finnhub_api_key:
        try:
            events = await _fetch_finnhub_calendar()
            if events:
                _calendar_cache = events
                _calendar_source = "finnhub"
                _calendar_fetched_at = now
                return events
        except Exception as e:
            # API 取得失敗時は警告ログを出してフォールバックに進む
            logger.warning("Finnhub calendar fetch failed: %s", e)

    # API 未設定または取得失敗の場合はテンプレートを使用
    _calendar_cache = _template_events()
    _calendar_source = "template"
    _calendar_fetched_at = now
    return _calendar_cache


async def _fetch_finnhub_calendar(days_ahead: int = 30) -> list[dict]:
    """Finnhub API から今後の経済カレンダーを取得する。

    Finnhub の /calendar/economic エンドポイントを呼び出し、
    指定期間内の経済イベントを取得・正規化して返す。

    impact の正規化ロジック:
      Finnhub は impact を "high"/"medium"/"low" または "3"/"2"/"1" で返すため、
      文字列と数値表現の両方を受け付けて統一された文字列に変換する。

    Args:
        days_ahead: 本日からの取得期間（日数）。デフォルト 30 日。

    Returns:
        正規化された経済イベント辞書のリスト（日付昇順）。
        取得失敗時は空リストを返す。
    """
    today = date.today()
    end = today + timedelta(days=days_ahead)
    url = "https://finnhub.io/api/v1/calendar/economic"
    params = {
        "from": today.isoformat(),
        "to": end.isoformat(),
        "token": settings.finnhub_api_key,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url, params=params)
        if response.status_code != 200:
            return []
        data = response.json()

    events = []
    for item in data.get("economicCalendar", []):
        # impact 値を小文字化して正規化
        # Finnhub は "high"/"3"（高影響）, "medium"/"2"（中影響）, その他（低影響）を返す
        impact_raw = (item.get("impact") or "").lower()
        if impact_raw in ("high", "3"):
            impact = "high"
        elif impact_raw in ("medium", "2"):
            impact = "medium"
        else:
            impact = "low"

        # 日付が取得できない場合は本日の日付を代用する
        event_date = item.get("time", "")[:10] or today.isoformat()
        country = (item.get("country") or "US").upper()
        title = item.get("event") or "経済指標"
        events.append({
            "date": event_date,
            "event_type": "economic",
            "title": title,
            "country": country,
            "impact": impact,
            "estimate": item.get("estimate"),
            "actual": item.get("actual"),
            "unit": item.get("unit"),
        })

    # 日付の昇順でソートして返す
    return sorted(events, key=lambda e: e["date"])


def _template_events() -> list[dict]:
    """組み込みテンプレートから今後の経済イベントカレンダーを動的生成する。

    FRED/Finnhub API が利用できない環境でも経済カレンダーを表示できるよう、
    典型的な発表スケジュールをテンプレートとして定義し、
    本日の日付を基準に相対日数でイベント日を計算して返す。

    各テンプレートの形式: (本日からの日数オフセット, EventType, 国コード, 影響度)

    Returns:
        経済イベント辞書のリスト（日付昇順）。
    """
    today = date.today()
    # テンプレート定義: (日数オフセット, イベント種別, 国コード, 影響度)
    templates = [
        (3, EventType.US_EMPLOYMENT, "US", "high"),   # 3日後: 米国雇用統計
        (7, EventType.CPI, "US", "high"),              # 7日後: CPI
        (14, EventType.FOMC, "US", "high"),            # 14日後: FOMC
        (21, EventType.BOJ, "JP", "high"),             # 21日後: 日銀会合
        (10, EventType.GDP, "US", "medium"),           # 10日後: GDP（中程度の影響）
        (1, EventType.CPI, "US", "high"),              # 1日後: CPI（早期アラート用）
        (28, EventType.US_EMPLOYMENT, "US", "high"),   # 28日後: 次月雇用統計
    ]
    events = []
    for offset, et, country, impact in templates:
        # 本日からの相対オフセットでイベント日を算出
        d = today + timedelta(days=offset)
        title = EVENT_LABELS[et]
        # GDP の場合、10日後のイベントは改定値として区別する
        if et == EventType.GDP and offset == 10:
            title = "米国GDP（改定値）"
        events.append({
            "date": d.isoformat(),
            "event_type": et.value,
            "title": title,
            "country": country,
            "impact": impact,
        })
    # 日付昇順でソートして返す
    return sorted(events, key=lambda e: e["date"])


def get_event_alerts(within_hours: int = 48) -> list[dict]:
    """指定時間以内に発表される高影響（high impact）イベントのアラートリストを返す。

    現在時刻から within_hours 時間以内に発表予定の「high」impact イベントを
    フィルタリングし、残り時間（hours_until）を付与して返す。
    トレーダーへの事前警告や取引制限判断に使用する。

    Args:
        within_hours: アラートを発する時間的範囲（時間単位）。デフォルト 48 時間。

    Returns:
        高影響イベント辞書のリスト。各要素には元のイベント情報に加えて
        hours_until（発表まで残り時間、小数点1桁）が追加される。
        発表済みイベントは含まれない（now <= event_dt の条件）。
    """
    now = datetime.now()
    # アラート対象期間の終端日時を計算
    deadline = now + timedelta(hours=within_hours)
    alerts = []
    for event in get_upcoming_events():
        # impact が "high" のイベントのみを対象とする
        if event["impact"] != "high":
            continue
        # 日付文字列（YYYY-MM-DD）を datetime に変換（時刻は 0:00:00 とする）
        event_dt = datetime.combine(date.fromisoformat(event["date"]), datetime.min.time())
        # 現在時刻から deadline までの範囲内に収まるイベントのみ抽出
        if now <= event_dt <= deadline:
            # 残り時間を時間単位で計算（小数点1桁に丸める）
            hours_left = (event_dt - now).total_seconds() / 3600
            alerts.append({**event, "hours_until": round(hours_left, 1)})
    return alerts

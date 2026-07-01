"""
マルチシグナル評価モジュール

AI・テクニカル分析・インテリジェンス・マルチタイムフレーム (MTF) の
4 ソース（+ オプションの TradingView）を並列収集・加重統合し、
最終的な売買アクションを決定する。

また、リスクガード（イベント回避・クールダウン・日次上限・信頼度閾値）による
注文可否判定と、ATR ベースのポジションサイジング（SL/TP 価格計算）も担う。

各シグナルソースのデフォルト加重:
    - AI シグナル       : 35% （LLM / ML モデルの総合判断）
    - テクニカル指標    : 25% （RSI / MACD / BB 等のルールベース）
    - インテリジェンス  : 20% （ファンダメンタル・センチメント複合）
    - MTF アライメント  : 10% （複数時間足の方向一致度）
    - TradingView 外部  : 10% （Pine Script 等の外部アラート）
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.ai.signals import generate_ai_signals
from src.analysis.fundamental import get_event_alerts
from src.analysis.market_context import MarketContext
from src.analysis.multi_timeframe import analyze_multi_timeframe
from src.analysis.position_sizing import calculate_position_size, pip_size
from src.analysis.signals import signals_from_row
from src.api.intelligence import build_intelligence
from src.autotrade.models import count_today_trades, last_executed_at
from src.autotrade.positions import has_open_position
from src.broker.oanda import get_account_summary
from src.config import settings
from src.infra.analysis_cache import cache_get, cache_key, cache_put
from src.ml.trend_predictor import predict_trend
from src.ml.volatility_predictor import predict_volatility


# シグナルソースの加重テーブル（合計は必ずしも 1.0 にならなくてよい）
# 各値は fuse_signals 内で conf * weight として使われる
SOURCE_WEIGHTS = {
    "ai": 0.35,           # AI / LLM による総合シグナル（最も高い加重）
    "technical": 0.25,    # テクニカル指標のルールベースシグナル
    "intelligence": 0.20, # ファンダメンタル・センチメントの複合指標
    "mtf": 0.10,          # マルチタイムフレームの方向アライメント
    "tradingview": 0.10,  # TradingView 外部 Webhook シグナル
}

# アクション文字列を数値スコアに変換するテーブル
# buy = +1.0（正方向）、sell = -1.0（負方向）、hold/alert = 0.0（ニュートラル）
ACTION_SCORE = {"buy": 1.0, "sell": -1.0, "hold": 0.0, "alert": 0.0}


def _normalize_action(action: str) -> str:
    """
    様々な表現のアクション文字列を "buy" / "sell" / "hold" に正規化する。

    AI モデルや外部シグナルは "long" / "bullish" / "short" / "bearish" 等
    多様な表現を使うため、統一フォーマットに変換する。

    Args:
        action: 正規化前のアクション文字列（None / 空文字を含む場合も処理）

    Returns:
        "buy" / "sell" / "hold" のいずれか
    """
    action = (action or "hold").lower()
    # ロング系キーワードが含まれていれば "buy" に統一
    if any(k in action for k in ("long", "bullish", "buy")):
        return "buy"
    # ショート系キーワードが含まれていれば "sell" に統一
    if any(k in action for k in ("short", "bearish", "sell")):
        return "sell"
    return "hold"


async def gather_signal_context(symbol: str, days: int = 200) -> dict[str, Any]:
    """
    全シグナルソースを並列収集し、統合コンテキスト辞書を返す。

    OHLCV・テクニカル指標・ML 予測・AI シグナル・インテリジェンスを
    asyncio を使って並列取得することで処理時間を最小化する。
    取得結果はキャッシュ（TTL: settings.signal_context_cache_ttl_seconds）に
    格納され、同一シンボル・同一 days での重複計算を排除する。

    収集ソースの処理順序（並列化ブロック単位）:
        1. MarketContext.load     : OHLCV + テクニカル指標を同期ロード（スレッド実行）
        2. analyze_multi_timeframe: MTF アライメントを同期計算（スレッド実行）
        3. predict_trend / predict_volatility: ML 予測を並列実行
        4. generate_ai_signals / build_intelligence: AI + ファンダメンタルを並列実行
        5. signals_from_row       : ルールベーステクニカルシグナルを算出

    Args:
        symbol: 通貨ペアシンボル（例: "USDJPY"）
        days:   OHLCV データの取得日数（デフォルト 200 日）

    Returns:
        以下のキーを含む辞書:
            - symbol:       シンボル（大文字）
            - price:        現在価格
            - source:       データソース識別子
            - atr:          ATR（Average True Range）値
            - ai:           AI シグナル（action / confidence）
            - technical:    テクニカルシグナル（action / confidence / signals リスト）
            - intelligence: インテリジェンスシグナル（action / confidence / composite_score / outlook）
            - mtf:          MTF シグナル（action / confidence / alignment / alignment_label）
            - ai_detail:    AI シグナルの詳細辞書

    Raises:
        なし（例外は呼び出し元で処理）
    """
    # キャッシュヒット確認（TTL 内の同一リクエストは再計算しない）
    key = cache_key("signal:context", symbol, days=days)
    cached = cache_get(key)
    if cached is not None:
        return cached

    # OHLCV + テクニカル指標をスレッドで同期ロード
    ctx = await asyncio.to_thread(MarketContext.load, symbol, days)
    latest = ctx.result_df.iloc[-1]   # 直近バーのデータ（指標値を含む）
    price = ctx.price
    atr = ctx.atr

    # MTF アライメントをスレッドで計算（複数時間足の方向性を一括評価）
    mtf = await asyncio.to_thread(analyze_multi_timeframe, symbol)

    # トレンド予測と ボラティリティ予測を並列実行（どちらも ML モデルを使用）
    trend, volatility = await asyncio.gather(
        asyncio.to_thread(
            predict_trend,
            symbol,
            days,
            result_df=ctx.result_df,
            source=ctx.source,
            mtf=mtf,
        ),
        asyncio.to_thread(
            predict_volatility,
            symbol,
            days,
            result_df=ctx.result_df,
            source=ctx.source,
        ),
    )

    # AI シグナル生成とインテリジェンス構築を並列実行
    ai, intelligence = await asyncio.gather(
        generate_ai_signals(symbol, days, ctx=ctx, mtf=mtf, trend=trend),
        build_intelligence(symbol, days, trend=trend, volatility=volatility),
    )

    # ルールベーステクニカルシグナルを算出し、buy/sell の多数決でアクションを決定
    rule_signals = signals_from_row(latest)
    buy_count = sum(1 for s in rule_signals if s["signal"] == "buy")
    sell_count = sum(1 for s in rule_signals if s["signal"] == "sell")
    if buy_count > sell_count:
        tech_action = "buy"
        # buy シグナルが多いほど信頼度を高くする（最大 90%）
        tech_conf = min(90, 45 + buy_count * 10)
    elif sell_count > buy_count:
        tech_action = "sell"
        # sell シグナルが多いほど信頼度を高くする（最大 90%）
        tech_conf = min(90, 45 + sell_count * 10)
    else:
        # 同数の場合は hold（信頼度は低め）
        tech_action = "hold"
        tech_conf = 40

    # MTF アライメント: "bullish" / "bearish" 等を正規化してアクションを決定
    mtf_action = _normalize_action(mtf.get("alignment", "neutral"))
    # MTF がアライメント方向に揃っていれば信頼度 70%、そうでなければ 45%
    mtf_conf = 70 if mtf_action in ("buy", "sell") else 45

    # インテリジェンス複合スコア: +25 超で buy、-25 未満で sell、それ以外は hold
    intel_score = intelligence.get("composite_score", 0)
    if intel_score > 25:
        intel_action = "buy"
        # スコアが大きいほど信頼度を高くする（最大 90%、基底 50%）
        intel_conf = min(90, 50 + abs(intel_score) * 0.4)
    elif intel_score < -25:
        intel_action = "sell"
        intel_conf = min(90, 50 + abs(intel_score) * 0.4)
    else:
        intel_action = "hold"
        intel_conf = 40

    result = {
        "symbol": symbol.upper(),
        "price": price,
        "source": ctx.source,
        "atr": atr,
        "ai": {"action": ai["action"], "confidence": ai["confidence"]},
        "technical": {"action": tech_action, "confidence": tech_conf, "signals": rule_signals},
        "intelligence": {
            "action": intel_action,
            "confidence": intel_conf,
            "composite_score": intel_score,
            "outlook": intelligence.get("outlook"),
        },
        "mtf": {
            "action": mtf_action,
            "confidence": mtf_conf,
            "alignment": mtf.get("alignment"),
            "alignment_label": mtf.get("alignment_label"),
        },
        "ai_detail": ai,
    }
    # 結果をキャッシュに保存（TTL は settings で設定）
    cache_put(key, result, ttl_seconds=settings.signal_context_cache_ttl_seconds)
    return result


def fuse_signals(context: dict, config: dict, tv_signal: dict | None = None) -> dict:
    """
    複数シグナルソースを加重スコアリングで統合し、最終アクションを決定する。

    統合ロジック:
        1. 設定の sources リストに含まれるシグナルソースのみを使用
        2. 各ソースのアクションを ACTION_SCORE で数値化（buy=+1, sell=-1, hold=0）
        3. conf * weight で加重し、スコアを累積
        4. 正規化スコア（score / total_weight）が:
               +0.25 超 → final_action = "buy"
               -0.25 未満 → final_action = "sell"
               それ以外 → final_action = "hold"
        5. 信頼度 = min(95, max(30, int(|normalized| * 100 + total_weight * 40)))
           （normalized スコアと総加重の両方から信頼度を算出）

    TradingView シグナルの扱い:
        - tv_signal が指定され、config["auto_execute_tradingview"]=True の場合のみ追加
        - TV シグナルには固定の高信頼度（0.85）と tradingview 加重を適用

    Args:
        context:   gather_signal_context が返すシグナルコンテキスト辞書
        config:    テナント設定辞書（sources / auto_execute_tradingview 等を使用）
        tv_signal: TradingView Webhook シグナル辞書（None の場合はスキップ）

    Returns:
        以下のキーを含む辞書:
            - action:     最終アクション（"buy" / "sell" / "hold"）
            - confidence: 最終信頼度（30〜95）
            - score:      正規化スコア（-1.0〜+1.0、小数点 4 桁）
            - breakdown:  各ソースの投票詳細リスト（source / action / weight）
            - context:    入力の context 辞書（そのまま引き継ぐ）
    """
    # 設定の sources が指定されていない場合はデフォルトの全ソースを使用
    sources = config.get("sources") or list(SOURCE_WEIGHTS.keys())
    votes: list[tuple[str, float, str]] = []

    # コンテキストのソースを名前でマッピング（"tradingview" は別途追加）
    mapping = {
        "ai": context["ai"],
        "technical": context["technical"],
        "intelligence": context["intelligence"],
        "mtf": context["mtf"],
    }
    for name in sources:
        if name not in mapping:
            continue
        src = mapping[name]
        action = _normalize_action(src["action"])
        # 信頼度を 0〜1 に正規化して加重を乗算
        conf = float(src.get("confidence", 50)) / 100
        weight = SOURCE_WEIGHTS.get(name, 0.1)
        votes.append((action, conf * weight, name))

    # TradingView シグナルが有効な場合は追加（高信頼度 0.85 で加重）
    if tv_signal and config.get("auto_execute_tradingview"):
        tv_action = _normalize_action(tv_signal.get("action", "hold"))
        if tv_action in ("buy", "sell"):
            votes.append((tv_action, 0.85 * SOURCE_WEIGHTS["tradingview"], "tradingview"))

    # 加重スコアを累積（buy=+, sell=-, hold=0）
    score = 0.0
    total_weight = 0.0
    breakdown: list[dict] = []
    for action, weighted, name in votes:
        score += ACTION_SCORE.get(action, 0) * weighted
        total_weight += weighted
        breakdown.append({"source": name, "action": action, "weight": round(weighted, 3)})

    # 総加重で正規化（ゼロ除算を回避）
    if total_weight > 0:
        normalized = score / total_weight
    else:
        normalized = 0.0

    # 閾値 ±0.25 でアクションを決定
    # （0.25 未満はノイズとして hold 扱い、過剰な売買を防止）
    if normalized > 0.25:
        final_action = "buy"
    elif normalized < -0.25:
        final_action = "sell"
    else:
        final_action = "hold"

    # 信頼度計算: スコアの絶対値（方向確信度）と総加重（情報量）を組み合わせる
    confidence = min(95, max(30, int(abs(normalized) * 100 + total_weight * 40)))

    return {
        "action": final_action,
        "confidence": confidence,
        "score": round(normalized, 4),
        "breakdown": breakdown,
        "context": context,
    }


def check_risk_guards(
    symbol: str,
    config: dict,
    tenant_id: int | None,
    fused: dict,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """
    注文を実行する前に複数のリスクガードを順番に検証する。

    ガードチェックは以下の順序で行われ、最初に失敗した条件で即座に False を返す。
    すべてのガードを通過した場合のみ True を返す。

    ガードチェックの順序と条件:

        1. hold シグナル判定
           - fused["action"] == "hold" の場合は注文不要のため即 False
           （これはリスクガードではなくシグナル条件だが最初に確認する）

        2. 最低信頼度チェック
           - fused["confidence"] < config["min_confidence"]（デフォルト 65%）
           - 信頼度が閾値を下回る場合は注文しない

        3. MTF アライメントチェック（require_mtf_alignment=True の場合のみ）
           - MTF アクションが hold でなく、かつ fused action と異なる場合はブロック
           - 例: MTF=sell なのに fused=buy の場合は不一致でブロック

        4. 高影響経済イベントによるブラックアウトチェック
           - event_blackout_hours（デフォルト 4 時間）以内に高影響イベントがある場合はブロック
           - 重要指標発表（CPI / 雇用統計 / FOMC 等）前後の誤エントリーを防ぐ

        5. 日次取引上限チェック
           - 当日の同一シンボルの約定件数が max_daily_trades（デフォルト 3 件）に達した場合はブロック

        6. クールダウンチェック
           - 直前の約定から cooldown_minutes（デフォルト 60 分）が経過していない場合はブロック
           - 連続エントリーによるドローダウン拡大を防ぐ

        7. 重複ポジションチェック（allow_add_to_position=False の場合）
           - 同一シンボルにオープンポジションが存在する場合はブロック
           - ナンピン・複数ポジション保有を禁止する設定

    Args:
        symbol:    通貨ペアシンボル
        config:    テナント設定辞書
        tenant_id: テナント識別子
        fused:     fuse_signals が返すシグナル統合結果辞書
        dry_run:   True でも同じ判定ロジックで評価する（ガードの動作は同一）

    Returns:
        (passed: bool, reason: str) のタプル
            passed=True  → "リスクチェック通過"
            passed=False → ブロック理由の日本語文字列
    """
    # ガード 1: hold シグナルは注文対象外（シグナル条件の先行チェック）
    if fused["action"] == "hold":
        return False, "シグナルが hold — エントリー条件未達"

    # ガード 2: 最低信頼度チェック（不明瞭なシグナルでの誤エントリーを防ぐ）
    min_conf = config.get("min_confidence", 65)
    if fused["confidence"] < min_conf:
        return False, f"信頼度 {fused['confidence']}% < 最低 {min_conf}%"

    # ガード 3: MTF アライメントチェック（複数時間足で方向が一致していないとブロック）
    if config.get("require_mtf_alignment"):
        mtf_action = fused["context"]["mtf"]["action"]
        # MTF が hold（ニュートラル）の場合は不一致とは見なさない
        if mtf_action != "hold" and mtf_action != fused["action"]:
            return False, f"MTF ({mtf_action}) とシグナル ({fused['action']}) が不一致"

    # ガード 4: 高影響経済イベントによるブラックアウト（重要指標発表前後は取引しない）
    blackout = config.get("event_blackout_hours", 4)
    if blackout > 0:
        alerts = get_event_alerts(blackout)
        if alerts:
            titles = ", ".join(a["title"] for a in alerts[:2])
            return False, f"高影響イベント前後 ({titles}) — ブラックアウト中"

    # ガード 5: 日次取引上限チェック（1 日の取引回数を制限してリスク管理）
    max_daily = config.get("max_daily_trades", 3)
    today_count = count_today_trades(tenant_id, symbol)
    if today_count >= max_daily:
        return False, f"本日の取引上限 ({max_daily}) に到達"

    # ガード 6: クールダウンチェック（前回約定から一定時間は再エントリーしない）
    cooldown = config.get("cooldown_minutes", 60)
    last = last_executed_at(tenant_id, symbol)
    if last and cooldown > 0:
        from datetime import datetime, timezone

        elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 60
        if elapsed < cooldown:
            return False, f"クールダウン中（残り {int(cooldown - elapsed)} 分）"

    # ガード 7: 重複ポジションチェック（allow_add_to_position=False の場合はナンピン禁止）
    if not config.get("allow_add_to_position", False) and has_open_position(tenant_id, symbol):
        return False, "同一通貨にオープンポジションあり — 決済後に再エントリー"

    # 全ガードを通過した場合のみ True を返す
    return True, "リスクチェック通過"


def compute_order_size(symbol: str, config: dict, context: dict, side: str, tenant_id: int | None = None) -> dict:
    """
    ATR ベースのポジションサイズとストップロス・テイクプロフィット価格を計算する。

    計算ロジック:
        1. 口座残高を取得（config["account_balance"] → ブローカー残高 → デフォルト 10,000 USD の優先順）
        2. リスク% と ATR から calculate_position_size でロット数を算出
        3. min_lots / max_lots の範囲にクランプ
        4. min_units を下限として units（通貨単位）に変換（1 lot = 100,000 units）
        5. ATR から SL 距離を算出し、RR 比でTP 距離を計算
        6. 価格精度は JPY ペアで小数点 3 桁、それ以外で 5 桁に丸める

    SL/TP の方向:
        - buy  の場合: SL = entry - stop_dist、TP = entry + tp_dist
        - sell の場合: SL = entry + stop_dist、TP = entry - tp_dist

    Args:
        symbol:    通貨ペアシンボル（例: "USDJPY"）
        config:    テナント設定辞書
                   （account_balance / risk_percent / min_lots / max_lots /
                     min_units / use_stop_loss / use_take_profit / risk_reward を使用）
        context:   gather_signal_context が返すコンテキスト辞書（price / atr を使用）
        side:      取引方向。"buy" または "sell"。
        tenant_id: テナント識別子（ブローカー残高取得に使用）

    Returns:
        以下のキーを含む辞書:
            - units:           注文ユニット数（整数、min_units 以上）
            - lots:            注文ロット数（float）
            - sizing:          calculate_position_size の詳細結果
            - account_balance: 使用した口座残高
            - side:            取引方向（"buy" / "sell"）
            - entry_price:     エントリー価格（現在価格）
            - stop_loss:       SL 価格（use_stop_loss=False の場合は None）
            - take_profit:     TP 価格（use_take_profit=False の場合は None）
            - stop_pips:       SL 距離（pips）
            - risk_reward:     RR 比（float）
    """
    trading_mode = config.get("mode", "paper")
    # 口座残高の優先順: config 設定値 → ブローカーから取得 → デフォルト 10,000 USD
    acct = get_account_summary(tenant_id, trading_mode)
    balance = float(config.get("account_balance") or acct.get("balance") or 10000)
    risk_pct = float(config.get("risk_percent", 1.0))
    price = context["price"]
    atr = context.get("atr")

    # ATR ベースでポジションサイズを計算（リスク% と ATR から適切なロット数を算出）
    sizing = calculate_position_size(symbol, price, balance, risk_pct, atr=atr)
    lots = sizing["recommended_lots"]
    # ロット数を min_lots〜max_lots の範囲に制限
    lots = max(float(config.get("min_lots", 0.01)), min(lots, float(config.get("max_lots", 1.0))))
    # ユニット数に変換（1 lot = 100,000 units）し、min_units 以上に制限
    min_units = int(config.get("min_units", 1000))
    units = max(min_units, int(lots * 100_000))

    # SL/TP 距離を計算
    stop_pips = sizing.get("stop_pips", 30)
    pip = pip_size(symbol)   # JPY ペアは 0.01、それ以外は 0.0001
    rr = float(config.get("risk_reward", 2.0))
    stop_dist = stop_pips * pip
    tp_dist = stop_dist * rr  # TP 距離 = SL 距離 × RR 比

    # 価格精度: JPY ペア（USDJPY 等）は小数点 3 桁、その他は 5 桁
    if side == "buy":
        stop_loss = round(price - stop_dist, 5 if not symbol.endswith("JPY") else 3) if config.get("use_stop_loss", True) else None
        take_profit = round(price + tp_dist, 5 if not symbol.endswith("JPY") else 3) if config.get("use_take_profit", True) else None
    else:
        stop_loss = round(price + stop_dist, 5 if not symbol.endswith("JPY") else 3) if config.get("use_stop_loss", True) else None
        take_profit = round(price - tp_dist, 5 if not symbol.endswith("JPY") else 3) if config.get("use_take_profit", True) else None

    return {
        "units": units,
        "lots": lots,
        "sizing": sizing,
        "account_balance": balance,
        "side": side,
        "entry_price": price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "stop_pips": stop_pips,
        "risk_reward": rr,
    }

"""
OpenAI による経済指標分析・売買判断・リスク管理モジュール。

このモジュールは FX トレードにおける三層分析（テクニカル・ファンダメンタル・ニュース）を
統合し、OpenAI GPT を用いてプロフェッショナルな売買判断とリスク評価を提供する。
OpenAI API が利用不可の場合はルールベースのフォールバック処理に切り替わる。
"""

import asyncio
import logging

import pandas as pd

from src.ai.client import _safe_number, chat_json
from src.ai.news import analyze_news
from src.analysis.fundamental import EVENT_LABELS, EventType, get_fundamental_data, get_upcoming_events
from src.analysis.technical import compute_all_indicators
from src.data.market_data import get_ohlcv_data

logger = logging.getLogger(__name__)

# 通貨ペアと基軸通貨・決済通貨のマッピング
# 分析時にどちらの国の経済指標を参照すべきかを決定するために使用する
CURRENCY_MAP = {
    "USDJPY": ("USD", "JPY"),
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "AUDUSD": ("AUD", "USD"),
}


def _calc_volatility(df: pd.DataFrame, period: int = 14) -> dict:
    """
    OHLCV データからボラティリティ指標を計算する。

    ATR（Average True Range）を用いて価格変動の大きさを定量化し、
    リスク管理の基礎データとして使用する。

    Args:
        df: OHLCV データを含む DataFrame（カラム: high, low, close が必須）
        period: ATR の計算期間（デフォルト 14 日）

    Returns:
        dict: 以下のキーを含むボラティリティ指標の辞書
            - atr: ATR の実値（価格単位）
            - atr_percent: ATR を現在値で割った割合（%）
            - daily_volatility: 日次リターンの標準偏差（%）
            - max_drawdown_30d: 直近 30 日間の最大ドローダウン（%）、データ不足時 None
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    # True Range の3要素を計算:
    #   1. 当日の高値 - 安値（通常の値動き幅）
    #   2. 前日終値から当日高値までのギャップ（上方ギャップ考慮）
    #   3. 前日終値から当日安値までのギャップ（下方ギャップ考慮）
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    # 指定期間の移動平均を取り ATR を算出する
    atr = tr.rolling(period).mean().iloc[-1]
    # 日次リターン（前日比変化率）を計算してボラティリティの基礎とする
    daily_returns = close.pct_change().dropna()
    # NaN チェックを行い、計算不能の場合は 0.0 にフォールバックする
    atr_val = float(atr) if pd.notna(atr) else 0.0
    close_val = float(close.iloc[-1])
    return {
        "atr": round(atr_val, 4),
        # ATR を現在価格で割ることで、異なる価格帯の通貨ペア間で比較可能にする
        "atr_percent": round(atr_val / close_val * 100, 3) if close_val else 0,
        # 日次リターンの標準偏差（%）= 実現ボラティリティの近似値
        "daily_volatility": round(float(daily_returns.std() * 100), 3) if len(daily_returns) else 0,
        # 直近 30 日間の最高値比較によるドローダウン計算（データ不足時は None を返す）
        "max_drawdown_30d": round(
            float((close / close.rolling(30).max() - 1).iloc[-1] * 100), 2
        )
        if len(close) >= 30
        else None,
    }


def _safe_round(val, digits=4):
    """
    None または NaN を安全に丸める。

    pandas の NaN や None が混在するデータを JSON シリアライズ可能な値に変換するための
    ユーティリティ関数。計算結果に欠損値が含まれる可能性があるためこの処理が必要。

    Args:
        val: 丸め対象の値（None, float, int など）
        digits: 小数点以下の桁数（デフォルト 4）

    Returns:
        float | None: 丸めた浮動小数点数、または None（入力が None/NaN の場合）
    """
    # None または float の NaN の場合は None を返し、JSON 出力に null として反映する
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    return round(float(val), digits)


def _build_technical_context(symbol: str, days: int = 200) -> dict:
    """
    テクニカル分析データを収集・計算してコンテキスト辞書を構築する。

    OHLCV データを取得し、各種テクニカル指標（RSI・MACD・ボリンジャーバンド等）を
    算出する。さらに、シンプルなルールベースで買い/売りシグナル数をカウントし、
    OpenAI プロンプトへの入力データとして整形する。

    Args:
        symbol: 通貨ペアのシンボル（例: "USDJPY"）
        days: 取得する過去データの日数（デフォルト 200 日）

    Returns:
        dict: テクニカル指標・シグナルカウント・ボラティリティを含む辞書
    """
    # OHLCV データを取得し、テクニカル指標を全て計算する
    df, source = get_ohlcv_data(symbol, days)
    result = compute_all_indicators(df)
    # 最新行（当日）の指標値を取得する
    latest = result.iloc[-1]

    # シンプルなルールベースでの買い/売りシグナルカウント
    # OpenAI への補足情報として、また AI 失敗時のフォールバックとして使用する
    buy_signals = 0
    sell_signals = 0
    rsi = latest["rsi"]
    if pd.notna(rsi):
        # RSI が 30 以下 = 売られすぎ = 買いシグナル
        if rsi < 30:
            buy_signals += 1
        # RSI が 70 以上 = 買われすぎ = 売りシグナル
        elif rsi > 70:
            sell_signals += 1
    if pd.notna(latest["macd"]) and pd.notna(latest["macd_signal"]):
        # MACD がシグナルラインを上回る = 上昇モメンタム = 買いシグナル
        if latest["macd"] > latest["macd_signal"]:
            buy_signals += 1
        # MACD がシグナルラインを下回る = 下降モメンタム = 売りシグナル
        elif latest["macd"] < latest["macd_signal"]:
            sell_signals += 1

    return {
        "source": source,
        "price": _safe_round(latest["close"], 4),
        "rsi": _safe_round(rsi, 2),
        "macd": _safe_round(latest["macd"], 4),
        "macd_signal": _safe_round(latest["macd_signal"], 4),
        "sma_20": _safe_round(latest["sma_20"], 4),
        "sma_50": _safe_round(latest["sma_50"], 4),
        "bb_upper": _safe_round(latest["bb_upper"], 4),
        "bb_lower": _safe_round(latest["bb_lower"], 4),
        "stoch_k": _safe_round(latest["stoch_k"], 2),
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        # ボラティリティはリスク管理・ポジションサイジングの計算に必須
        "volatility": _calc_volatility(result),
    }


async def analyze_fundamentals(symbol: str) -> dict:
    """
    経済指標データを OpenAI で分析し、ファンダメンタル的な通貨バイアスを評価する。

    対象通貨ペアの基軸通貨・決済通貨それぞれの経済状況を分析し、
    マクロ経済的な観点からの売買バイアス（bullish/bearish/neutral）を出力する。

    Args:
        symbol: 通貨ペアのシンボル（例: "USDJPY"）

    Returns:
        dict: OpenAI の分析結果を含む辞書（overview・pair_bias・key_indicators 等）
            - symbol: 通貨ペア
            - base: 基軸通貨コード
            - quote: 決済通貨コード
            - overview: 総合評価テキスト
            - pair_bias: "bullish" | "bearish" | "neutral"
            - confidence: AI の確信度（0-100）
    """
    # CURRENCY_MAP で未定義の通貨ペアは先頭3文字/後半3文字で分割する
    base, quote = CURRENCY_MAP.get(symbol.upper(), (symbol[:3], symbol[3:]))
    # 経済指標データとイベントカレンダーを並行取得する
    fund_data = await get_fundamental_data()
    calendar = get_upcoming_events()

    # 経済指標データをラベル付きで整理し、各指標の最新 3 件に絞る
    relevant_events = {}
    for key, data in fund_data.items():
        try:
            # EventType Enum からラベルを取得する
            label = EVENT_LABELS[EventType(key)]
        except ValueError:
            # 未知の EventType は data 内の label か key 自体を使用する
            label = data.get("label", key)
        relevant_events[label] = data.get("data", [])[:3]

    # OpenAI API をブロッキング呼び出しするため、スレッドプールで実行する
    # （asyncio イベントループをブロックしないため to_thread を使用）
    result = await asyncio.to_thread(
        chat_json,
        # システムプロンプト: マクロ経済アナリストとして JSON 形式で回答させる
        """あなたはマクロ経済アナリストです。経済指標データを分析し、JSONのみで回答してください。
出力形式:
{
  "overview": "総合評価（3-5文、日本語）",
  "base_currency_analysis": "基軸通貨の経済状況分析",
  "quote_currency_analysis": "決済通貨の経済状況分析",
  "key_indicators": [
    {"name": "指標名", "impact": "positive|negative|neutral", "comment": "解説"}
  ],
  "upcoming_risks": ["リスク1", "リスク2"],
  "pair_bias": "bullish|bearish|neutral",
  "confidence": 0
}""",
        # ユーザープロンプト: 通貨ペア情報・経済指標データ・今後のイベントを渡す
        f"""通貨ペア: {symbol} ({base}/{quote})

経済指標データ:
{relevant_events}

今後のイベント:
{calendar[:5]}""",
    )

    return {"symbol": symbol, "base": base, "quote": quote, **result}


def _trading_decision_from_context(
    symbol: str, technical: dict, news: dict, fund: dict
) -> dict:
    """
    テクニカル・ニュース・ファンダメンタルの三要素を統合し、OpenAI で売買判断を生成する。

    三種類の分析コンテキストを OpenAI に渡し、プロのFXトレーダーとして
    具体的な売買アクション・エントリー価格・利確/損切り水準を JSON で出力させる。

    Args:
        symbol: 通貨ペアのシンボル
        technical: テクニカル分析コンテキスト（`_build_technical_context` の戻り値）
        news: ニュース分析結果（`analyze_news` の戻り値）
        fund: ファンダメンタル分析結果（`analyze_fundamentals` の戻り値）

    Returns:
        dict: 売買判断を含む辞書
            - action: "buy" | "sell" | "hold"
            - confidence: 確信度（0-100）
            - entry_price: エントリー価格
            - take_profit: 利確目標価格
            - stop_loss: 損切り価格
            - risk_reward_ratio: リスクリワード比
            - reasoning: 判断理由（日本語）

    Raises:
        ValueError: OpenAI API エラーまたは JSON パースエラーの場合
    """
    # OpenAI にプロの FX トレーダーとして三つの視点（テクニカル・ニュース・ファンダ）
    # を統合した売買判断を生成させる
    result = chat_json(
        system="""あなたはプロのFXトレーダーです。売買判断をJSONで出力してください。
{
  "action": "buy|sell|hold",
  "confidence": 0,
  "entry_price": 0,
  "take_profit": 0,
  "stop_loss": 0,
  "timeframe": "短期|中期|長期",
  "reasoning": "判断理由（日本語）",
  "technical_view": "テクニカル見解",
  "fundamental_view": "ファンダメンタル見解",
  "news_view": "ニュース見解",
  "risk_reward_ratio": 0,
  "warnings": ["注意点"]
}""",
        # 現在価格・テクニカル指標・ニュースセンチメント・ファンダバイアスを入力する
        user=f"""通貨ペア: {symbol}
現在価格: {technical['price']}
テクニカル: {technical}
ニュース: 要約={news.get('summary')}, sentiment={news.get('sentiment')}
ファンダメンタル: {fund.get('overview')}, bias={fund.get('pair_bias')}""",
    )
    return {
        "symbol": symbol,
        "current_price": technical["price"],
        # テクニカルコンテキストをそのまま付与して呼び出し元が参照できるようにする
        "technical": technical,
        "news_sentiment": news.get("sentiment"),
        # OpenAI の判断結果をアンパックして統合する
        **result,
    }


def _risk_from_context(symbol: str, technical: dict, account_balance: float) -> dict:
    """
    テクニカルデータと口座残高を基に、OpenAI でリスク管理評価を生成する。

    ATR・RSI・口座残高を OpenAI に渡し、適切なポジションサイズ・レバレッジ・
    損切り/利確水準をリスク管理の観点から算出する。
    AI の出力に加え、口座残高ベースの実際のドル金額も計算して付与する。

    Args:
        symbol: 通貨ペアのシンボル
        technical: テクニカル分析コンテキスト（volatility キーが必須）
        account_balance: 口座残高（USD）

    Returns:
        dict: リスク管理評価を含む辞書
            - risk_level: "low" | "medium" | "high" | "extreme"
            - risk_score: リスクスコア（0-100）
            - position_size_percent: 推奨ポジションサイズ（口座の %）
            - position_size_usd: 推奨ポジションサイズ（USD 実額）
            - max_loss_percent: 最大許容損失（%）
            - max_loss_usd: 最大許容損失（USD 実額）
            - recommended_leverage: 推奨レバレッジ
            - stop_loss_price: 損切り価格
            - take_profit_price: 利確価格

    Raises:
        ValueError: OpenAI API エラーまたは JSON パースエラーの場合
    """
    price = technical["price"]
    vol = technical["volatility"]

    # OpenAI にリスク管理の専門家として評価を生成させる
    result = chat_json(
        system="""リスク管理評価をJSONで出力してください。
{
  "risk_level": "low|medium|high|extreme",
  "risk_score": 0,
  "position_size_percent": 2,
  "max_loss_percent": 1,
  "recommended_leverage": 3,
  "stop_loss_price": 0,
  "take_profit_price": 0,
  "risk_reward_ratio": 0,
  "volatility_assessment": "評価文",
  "market_conditions": "市場環境",
  "recommendations": ["推奨1"],
  "do_not_trade_if": ["条件1"]
}""",
        # ATR（実値と%）と RSI を渡してボラティリティ状況を AI に伝える
        user=f"""通貨ペア: {symbol}
現在価格: {price}
口座残高: ${account_balance:,.0f}
ATR: {vol['atr']} ({vol['atr_percent']}%)
RSI: {technical['rsi']}""",
    )

    # AI が返した % 値を実際の USD 金額に変換する
    # （AI が数値以外を返す可能性があるため _safe_number でデフォルト値付き変換）
    position_pct = _safe_number(result.get("position_size_percent"), 2)
    max_loss_pct = _safe_number(result.get("max_loss_percent"), 1)
    # 口座残高に対するパーセンテージから実際のドル金額を算出する
    result["position_size_usd"] = round(account_balance * position_pct / 100, 2)
    result["max_loss_usd"] = round(account_balance * max_loss_pct / 100, 2)

    return {
        "symbol": symbol,
        "account_balance": account_balance,
        "current_price": price,
        "volatility": vol,
        **result,
    }


def _rule_based_trading_fallback(
    symbol: str, technical: dict, news: dict, fund: dict, error: str | None = None
) -> dict:
    """
    OpenAI 失敗時のルールベース売買判断フォールバック。

    OpenAI API が利用不可またはエラーが発生した場合に、
    シンプルなスコアリングロジックで売買方向を決定する。
    ユーザーに対しては必ずフォールバックである旨を warnings に明示する。

    Args:
        symbol: 通貨ペアのシンボル
        technical: テクニカル分析コンテキスト
        news: ニュース分析結果
        fund: ファンダメンタル分析結果
        error: OpenAI エラーメッセージ（None の場合は非表示）

    Returns:
        dict: ルールベースの売買判断辞書（fallback=True フラグ付き）
            - action: "buy" | "sell" | "hold"
            - confidence: 信頼度（最大 75% に制限）
            - take_profit / stop_loss: ATR ベースの価格
            - warnings: フォールバックであることの警告メッセージ
            - fallback: True（フォールバックであることを識別するフラグ）
    """
    price = technical.get("price") or 0
    buy = technical.get("buy_signals", 0)
    sell = technical.get("sell_signals", 0)
    sentiment = news.get("sentiment", "neutral")
    bias = fund.get("pair_bias", "neutral")

    # テクニカルシグナルの差分をベーススコアとする
    # 正の値が大きいほど買い優勢、負の値が大きいほど売り優勢
    score = buy - sell
    # ニュースセンチメントをスコアに加算（各 ±1 ポイント）
    if sentiment == "bullish":
        score += 1
    elif sentiment == "bearish":
        score -= 1
    # ファンダメンタルバイアスをスコアに加算（各 ±1 ポイント）
    if bias == "bullish":
        score += 1
    elif bias == "bearish":
        score -= 1

    # 合計スコアが ±2 以上で方向性を決定する
    # （±1 は誤差範囲とみなし様子見とする）
    if score >= 2:
        action = "buy"
    elif score <= -2:
        action = "sell"
    else:
        action = "hold"

    # ATR が取得できない場合は現在価格の 0.5% を代替値として使用する
    atr = technical.get("volatility", {}).get("atr") or (price * 0.005 if price else 0.5)
    # リスクリワード比 2:1 を基準に利確・損切りラインを設定する
    if action == "buy":
        tp, sl = price + atr * 2, price - atr  # 利確 = ATR×2、損切り = ATR×1
    elif action == "sell":
        tp, sl = price - atr * 2, price + atr  # 売りの場合は上下を逆転する
    else:
        tp, sl = price, price  # 様子見の場合は現在価格をそのまま設定する

    # フォールバックであることをユーザーに必ず通知する
    warnings = ["OpenAI 応答不可 — ルールベースの参考判断です"]
    # エラー内容が存在する場合は先頭 120 文字を警告に含める
    if error:
        warnings.append(error[:120])

    return {
        "symbol": symbol,
        "current_price": price,
        "technical": technical,
        "news_sentiment": sentiment,
        "action": action,
        # 信頼度は最大 75% に制限する（OpenAI の精度より劣るため上限を設ける）
        # 基礎値 40% + シグナル強度に応じた加算（1シグナルあたり 10%）
        "confidence": min(75, 40 + abs(score) * 10),
        "entry_price": price,
        "take_profit": round(tp, 4),
        "stop_loss": round(sl, 4),
        "timeframe": "短期",
        "reasoning": "テクニカルシグナル・ニュースセンチメント・ファンダバイアスを統合したルールベース判断（OpenAI フォールバック）。",
        "technical_view": f"買いシグナル {buy} / 売りシグナル {sell}",
        "fundamental_view": fund.get("overview", "—")[:200],
        "news_view": news.get("summary", "—")[:200],
        "risk_reward_ratio": 2.0,
        "warnings": warnings,
        # フォールバック判断であることを呼び出し元が識別できるようにする
        "fallback": True,
    }


async def make_trading_decision(symbol: str, days: int = 200) -> dict:
    """
    テクニカル・ニュース・ファンダメンタルを統合した売買判断を生成する。

    三種類の分析を並行実行してコンテキストを収集し、OpenAI で総合的な判断を生成する。
    OpenAI が失敗した場合はルールベースフォールバックに切り替える。

    Args:
        symbol: 通貨ペアのシンボル（例: "USDJPY"）
        days: テクニカル分析に使用する過去データの日数（デフォルト 200）

    Returns:
        dict: 売買判断辞書（OpenAI またはルールベースフォールバック）
            - action: "buy" | "sell" | "hold"
            - confidence: 確信度（0-100）
            - entry_price / take_profit / stop_loss: 価格水準
            - fallback: フォールバック時のみ True
    """
    # テクニカル分析は同期処理のため先に実行する
    technical = _build_technical_context(symbol, days)
    # ニュース分析とファンダメンタル分析は独立しているため並行実行する
    news, fund = await asyncio.gather(
        analyze_news(symbol, limit=6),
        analyze_fundamentals(symbol),
    )
    try:
        # OpenAI API 呼び出しは同期関数のため to_thread で非同期化する
        return await asyncio.to_thread(_trading_decision_from_context, symbol, technical, news, fund)
    except ValueError as e:
        # OpenAI エラー時はルールベースフォールバックで応答し、サービスの継続性を保つ
        logger.warning("OpenAI trading decision failed, using rule fallback: %s", e)
        return _rule_based_trading_fallback(symbol, technical, news, fund, str(e))


async def assess_risk(symbol: str, days: int = 200, account_balance: float = 10000) -> dict:
    """
    指定通貨ペアのリスク管理評価を OpenAI で生成する。

    Args:
        symbol: 通貨ペアのシンボル（例: "USDJPY"）
        days: テクニカル分析に使用する過去データの日数（デフォルト 200）
        account_balance: 口座残高（USD、デフォルト 10,000）

    Returns:
        dict: リスク管理評価辞書（risk_level・position_size_usd 等を含む）
    """
    # テクニカルコンテキストを構築してからリスク評価を実行する
    technical = _build_technical_context(symbol, days)
    # OpenAI の同期呼び出しをスレッドプールで実行し、イベントループをブロックしない
    return await asyncio.to_thread(_risk_from_context, symbol, technical, account_balance)


async def generate_full_report(symbol: str, days: int = 200, account_balance: float = 10000) -> dict:
    """
    重複 API 呼び出しを避けた総合レポートを生成する。

    テクニカル分析を一度だけ実行し、その結果を売買判断・リスク評価の両方に使い回す。
    ニュース/ファンダメンタル分析と売買判断/リスク評価をそれぞれ並行実行することで
    レスポンスタイムを最小化する。

    Args:
        symbol: 通貨ペアのシンボル（例: "USDJPY"）
        days: テクニカル分析に使用する過去データの日数（デフォルト 200）
        account_balance: 口座残高（USD、デフォルト 10,000）

    Returns:
        dict: 以下のキーを含む総合レポート辞書
            - symbol: 通貨ペア
            - news: ニュース分析結果
            - fundamentals: ファンダメンタル分析結果
            - trading_decision: 売買判断
            - risk_management: リスク管理評価
    """
    # テクニカルコンテキストは売買判断・リスク評価の両方で使用するため一度だけ計算する
    technical = _build_technical_context(symbol, days)

    # ニュースとファンダメンタルは独立した外部 API を呼ぶため並行実行する
    news, fund = await asyncio.gather(
        analyze_news(symbol, limit=6),
        analyze_fundamentals(symbol),
    )

    # 売買判断とリスク評価はどちらも OpenAI を呼ぶが独立しているため並行実行する
    decision, risk = await asyncio.gather(
        asyncio.to_thread(_trading_decision_from_context, symbol, technical, news, fund),
        asyncio.to_thread(_risk_from_context, symbol, technical, account_balance),
    )

    return {
        "symbol": symbol,
        "news": news,
        "fundamentals": fund,
        "trading_decision": decision,
        "risk_management": risk,
    }

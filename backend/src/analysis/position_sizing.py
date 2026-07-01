"""
ポジションサイジング・pip 計算モジュール

このモジュールは FX トレードにおける適切なポジションサイズ（ロット数）を
固定リスク%法（Fixed Fractional Method）に基づいて算出する機能を提供する。

主な概念:
- pip: FX における最小価格変動単位。JPY ペアは 0.01、それ以外は 0.0001
- ロット: 取引単位。標準ロット = 100,000 通貨
- 固定リスク%法: 1 トレードで口座残高の一定割合（例: 1%）のみリスクにさらす手法
  - ポジションサイズ = リスク許容額 ÷ (ストップ幅 × 1pip 価値)
- ATR（Average True Range）: ボラティリティを測定する指標。動的ストップ幅の基準に使用

参考: ケリー基準（Kelly Criterion）とは異なり、固定リスク%法は
      勝率・オッズを事前に必要とせず、より保守的で実用的なアプローチ。
"""

from src.analysis.volatility import calc_atr


def pip_size(symbol: str) -> float:
    """通貨ペアの 1 pip の価格幅を返す。

    FX では通貨ペアによって最小変動単位が異なる。
    - JPY ペア（USDJPY, EURJPY 等）: 小数点第 2 位 = 0.01
    - その他ペア（EURUSD, GBPUSD 等）: 小数点第 4 位 = 0.0001

    Args:
        symbol: 通貨ペアシンボル（例: "USDJPY", "EURUSD"）。大文字小文字不問。

    Returns:
        1 pip に相当する価格幅（float）。JPY ペアは 0.01、それ以外は 0.0001。
    """
    return 0.01 if symbol.upper().endswith("JPY") else 0.0001


def pip_value_per_lot_usd(symbol: str, price: float) -> float:
    """標準ロット（100,000通貨）あたりの 1 pip の USD 価値を返す。

    ポジションサイズ計算のコア。1 pip が何ドルに相当するかを算出する。

    計算方法:
    - JPY ペア（例: USDJPY = 150.00 の場合）:
        pip_value = (100,000 × 0.01) ÷ 150.00 = 6.67 USD
        → ベース通貨 USD で評価するために現在レートで除算
    - USD クォートペア（例: EURUSD）:
        pip_value = 100,000 × 0.0001 = 10.00 USD
        → クォート通貨が USD なので、そのままドル換算可能

    Args:
        symbol: 通貨ペアシンボル（大文字小文字不問）。
        price:  現在の市場価格（bid/ask 中値を推奨）。

    Returns:
        1 標準ロット・1 pip あたりの USD 価値（float）。
        price が 0 または無効の場合は 0.0 を返す。
    """
    sym = symbol.upper()
    pip = pip_size(sym)
    if sym.endswith("JPY"):
        # USDJPY: 100k USD × 0.01 JPY / rate
        # JPY ペアは取引単位が JPY のため、現在レートで USD に換算する
        return (100_000 * pip) / price if price else 0.0
    if sym.endswith("USD"):
        # EURUSD, GBPUSD, AUDUSD 等のクォート通貨が USD のペア
        # pip_value = 100,000 通貨 × 0.0001 = 10 USD（固定）
        return 100_000 * pip
    # その他のペア（クロスカレンシー）は簡易的に同様に計算
    return 100_000 * pip


def pips_from_atr(atr: float, symbol: str, multiplier: float = 1.5) -> float:
    """ATR の価格幅を pip 数に変換する。

    ATR（Average True Range）をボラティリティベースの動的ストップ幅として
    pip 単位に変換する。デフォルトの乗数 1.5 は、通常の価格変動ノイズを
    吸収しつつ、過大なリスクを避けるための経験的な値。

    計算式:
        stop_pips = (ATR × multiplier) ÷ pip_size

    例: EURUSD で ATR = 0.0060、multiplier = 1.5 の場合
        → (0.0060 × 1.5) ÷ 0.0001 = 90 pips のストップ幅

    Args:
        atr:        ATR の価格幅（`calc_atr` の戻り値）。
        symbol:     通貨ペアシンボル。pip_size の計算に使用。
        multiplier: ATR への乗数（デフォルト 1.5）。
                    高ボラ環境では 2.0、低ボラ環境では 1.0 を推奨。

    Returns:
        pip 単位のストップ幅（float）。小数点第 1 位で丸め。
        pip_size が 0 の場合は 0.0 を返す。
    """
    pip = pip_size(symbol)
    return round(atr * multiplier / pip, 1) if pip else 0.0


def calculate_position_size(
    symbol: str,
    price: float,
    account_balance: float,
    risk_percent: float,
    stop_pips: float | None = None,
    atr: float | None = None,
    atr_multiplier: float = 1.5,
) -> dict:
    """固定リスク%法によるポジションサイズ（推奨ロット数）を算出する。

    【固定リスク%法（Fixed Fractional Method）の計算フロー】

    1. リスク許容額 = 口座残高 × (リスク% ÷ 100)
       例: 残高 $10,000 × 1% = $100 がリスク許容額

    2. ストップ幅（pip）の決定:
       - 明示的に stop_pips が指定された場合はそれを使用
       - 未指定の場合は ATR ベース（atr × multiplier ÷ pip_size）で算出
       - ATR も未指定の場合はデフォルト値（JPY: 30 pips、その他: 20 pips）

    3. 1 ロットあたりのリスク = ストップ幅 × 1 pip の USD 価値

    4. 推奨ロット数 = リスク許容額 ÷ 1 ロットあたりのリスク
       → min 0.01 ロット（マイクロロット）〜 max 100.0 ロットに制限

    5. テイクプロフィット = ストップ幅 × 2（リスクリワード比 1:2 を目安）

    Note:
        ケリー基準（Kelly Criterion）は f* = (bp - q) / b の形で
        理論的最適ベットサイズを求めるが、FX では勝率・オッズの事前推定が
        困難なため、本関数では固定リスク%法を採用している。

    Args:
        symbol:         通貨ペアシンボル（例: "USDJPY"）。
        price:          現在の市場価格（小数形式）。
        account_balance: 口座残高（USD）。
        risk_percent:   1 トレードで許容するリスク割合（%）。
                        推奨値: 0.5〜2.0%。2% 超は過大リスクとなる。
        stop_pips:      損切り幅（pip 単位）。None の場合は ATR から自動算出。
        atr:            ATR 値（`calc_atr` の戻り値）。stop_pips が None の時に使用。
        atr_multiplier: ATR に掛けるストップ幅の乗数（デフォルト 1.5）。

    Returns:
        以下のキーを持つ dict:
        - symbol: 通貨ペア（大文字）
        - price: 現在価格（小数点 4 桁）
        - account_balance: 口座残高 USD
        - risk_percent: 設定リスク%
        - risk_amount_usd: リスク許容額（USD）
        - stop_pips: 使用したストップ幅（pip）
        - pip_size: 1 pip の価格幅
        - pip_value_per_lot_usd: 1 ロット・1 pip の USD 価値
        - recommended_lots: 推奨ロット数（0.01〜100.0）
        - position_notional_usd: ポジション名目金額（USD）
        - max_loss_usd: 最大損失額（ストップロス到達時）
        - atr_based_stop: ATR ベースのストップを使用したかどうか（bool）
        - suggested_take_profit_pips: 推奨テイクプロフィット幅（pip）
    """
    sym = symbol.upper()
    pip_val = pip_value_per_lot_usd(sym, price)

    # ストップ幅の決定: 明示指定 > ATR ベース > デフォルト値
    if stop_pips is None or stop_pips <= 0:
        if atr and atr > 0:
            # ATR × 乗数をストップ幅として使用（ボラティリティに適応）
            stop_pips = pips_from_atr(atr, sym, atr_multiplier)
        else:
            # ATR が取得できない場合のフォールバックデフォルト値
            # JPY ペアは価格レンジが大きいため 30 pips、他は 20 pips
            stop_pips = 30.0 if sym.endswith("JPY") else 20.0

    # 固定リスク%法のコア計算
    # リスク許容額 = 口座残高 × リスク率
    risk_amount = account_balance * (risk_percent / 100)
    # 1 ロットあたりのリスク（ストップまで動いた場合の損失額）
    risk_per_lot = stop_pips * pip_val
    # 推奨ロット数 = リスク許容額 ÷ 1 ロットあたりのリスク
    lots = round(risk_amount / risk_per_lot, 2) if risk_per_lot > 0 else 0.0
    # 最小 0.01 ロット（マイクロロット）、最大 100 ロットに制限（リスク管理上の上限）
    lots = max(0.01, min(lots, 100.0))

    return {
        "symbol": sym,
        "price": round(price, 4),
        "account_balance": account_balance,
        "risk_percent": risk_percent,
        "risk_amount_usd": round(risk_amount, 2),
        "stop_pips": stop_pips,
        "pip_size": pip_size(sym),
        "pip_value_per_lot_usd": round(pip_val, 2),
        "recommended_lots": lots,
        # ポジション名目金額: 1 ロット = 100,000 通貨として計算
        "position_notional_usd": round(lots * 100_000, 0),
        # ストップロス到達時の実際の損失額（lots × 1 ロットのリスク）
        "max_loss_usd": round(lots * risk_per_lot, 2),
        # ストップが ATR ベースかどうかのフラグ（ユーザー向け情報）
        "atr_based_stop": atr is not None and (stop_pips == pips_from_atr(atr, sym, atr_multiplier)),
        # テイクプロフィット: ストップの 2 倍（リスクリワード比 1:2）を推奨
        "suggested_take_profit_pips": round(stop_pips * 2, 1),
    }

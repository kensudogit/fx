"""
運用前シミュレーションモジュール — 過去データバックテスト + 推奨証拠金

実際の自動売買を開始する前に、過去の価格データを使って
戦略の有効性を検証し、必要な証拠金を試算するモジュール。
トライオートFX のシミュレーション機能（セレクト確認画面）に相当する。

シミュレーションフロー:
    1. プリセットまたはカスタム設定を適用
    2. 過去 days 日分の OHLCV データを取得
    3. テクニカル指標を計算してバックテストを実行
    4. 連敗リスクを考慮した推奨証拠金を試算
    5. 勝率に基づく運用適性グレード（A/B/C/D）を判定
"""

from src.analysis.position_sizing import calculate_position_size, pip_size
from src.analysis.signals import backtest_signals
from src.analysis.technical import compute_all_indicators
from src.analysis.volatility import calc_atr
from src.autotrade.presets import apply_preset
from src.data.market_data import get_ohlcv_data


def simulate_strategy(
    symbol: str,
    days: int = 365,
    account_balance: float = 10000,
    preset_id: str | None = "balanced",
    risk_percent: float = 1.0,
) -> dict:
    """プリセットまたはカスタム設定での過去シミュレーションを実行する。

    バックテスト結果・推奨証拠金・運用適性グレードを返す。
    口座残高と連敗リスクを元に、安全運用に必要な証拠金も計算する。

    Args:
        symbol: 通貨ペアコード（例: "USDJPY"）
        days: 過去何日分のデータでシミュレーションするか（デフォルト: 365日）
        account_balance: 想定口座残高（USD、デフォルト: 10,000）
        preset_id: 使用するプリセット ID（None の場合はデフォルト設定のみ）
        risk_percent: 1トレードあたりのリスク割合（%）

    Returns:
        シミュレーション結果の辞書:
            - symbol: 通貨ペア
            - source: データ取得元（"oanda", "yahoo", "sample" 等）
            - period_days: シミュレーション期間（日）
            - preset_id: 適用したプリセット ID
            - backtest: バックテスト結果（勝率・トレード数・平均リターン等）
            - position_sizing: ポジションサイジング計算結果
            - capital: 証拠金試算情報（推奨・安全）
            - assessment: 運用適性評価（グレード・サマリー）
    """
    # プリセットが指定された場合は設定を適用（なければ空設定）
    config = apply_preset(preset_id) if preset_id else {}
    config["account_balance"] = account_balance
    config["risk_percent"] = risk_percent

    # 過去データを取得してテクニカル指標を計算
    df, source = get_ohlcv_data(symbol, days)

    # 一目均衡表の計算に最低 80 行必要。不足時は days を延長して再取得
    if len(df) < 80:
        df, source = get_ohlcv_data(symbol, max(days, 200))

    # それでもデータが不足する場合は計算不能として早期リターン
    if len(df) < 30:
        return {
            "symbol": symbol.upper(),
            "source": source,
            "period_days": days,
            "preset_id": preset_id,
            "backtest": {"total_trades": 0, "win_rate": 0, "avg_return_pct": 0},
            "position_sizing": {},
            "capital": {
                "input_balance": account_balance,
                "recommended_margin_usd": account_balance,
                "safe_margin_usd": account_balance * 1.5,
                "note": "データ不足のため証拠金試算をスキップしました。",
            },
            "assessment": {
                "grade": "D",
                "win_rate": 0,
                "total_trades": 0,
                "avg_return_pct": 0,
                "ready_to_deploy": False,
                "summary": "データ不足 — 先にテクニカル画面で「データ同期」を実行してください。",
            },
        }

    result_df = compute_all_indicators(df)

    # シグナルベースのバックテストを実行（勝率・平均リターン等を算出）
    bt = backtest_signals(result_df)

    # 現在価格と ATR（平均真の値幅）を取得してポジションサイズを計算
    price = float(result_df["close"].iloc[-1])
    atr = calc_atr(result_df)
    sizing = calculate_position_size(symbol, price, account_balance, risk_percent, atr=atr)

    # 連敗リスクに基づく推奨証拠金の試算
    # 勝率から想定最大連敗数を求め、その損失に耐えられる証拠金を計算
    max_loss_streak = _estimate_max_loss_streak(bt.get("win_rate", 50))
    # 推奨証拠金 = 口座残高 × (1 + 最大連敗数 × リスク% × 0.5)
    # 0.5 は連敗時の証拠金減少を考慮した安全係数
    recommended_margin = round(account_balance * (1 + max_loss_streak * risk_percent / 100 * 0.5), 0)
    # 安全運用証拠金 = 推奨の 1.5 倍（想定外の連敗にも対応できるバッファ）
    safe_margin = round(recommended_margin * 1.5, 0)

    # 勝率に基づく運用適性グレードの判定
    # A: 55%以上、B: 48-54%、C: 42-47%、D: 41%以下
    win_rate = bt.get("win_rate", 0)
    grade = "A" if win_rate >= 55 else "B" if win_rate >= 48 else "C" if win_rate >= 42 else "D"

    return {
        "symbol": symbol.upper(),
        "source": source,
        "period_days": days,
        "preset_id": preset_id,
        "backtest": bt,
        "position_sizing": sizing,
        "capital": {
            "input_balance": account_balance,
            "recommended_margin_usd": recommended_margin,
            "safe_margin_usd": safe_margin,
            "note": "推奨証拠金は連敗リスクを考慮。安全運用は推奨の 1.5 倍を目安に。",
        },
        "assessment": {
            "grade": grade,
            "win_rate": win_rate,
            "total_trades": bt.get("total_trades", 0),
            "avg_return_pct": bt.get("avg_return_pct", 0),
            # 勝率45%以上かつトレード数20以上を運用開始の目安とする
            "ready_to_deploy": win_rate >= 45 and bt.get("total_trades", 0) >= 20,
            "summary": _assessment_summary(grade, win_rate, bt.get("total_trades", 0)),
        },
    }


def _estimate_max_loss_streak(win_rate: float) -> int:
    """勝率から想定される最大連敗数を推定する。

    連敗数は勝率が低いほど大きくなる。
    証拠金計算の安全バッファとして使用する。

    Args:
        win_rate: 勝率（%、例: 55.0）

    Returns:
        想定最大連敗数:
            勝率 60%以上 → 3連敗（発生確率 0.4^3 ≈ 6.4%）
            勝率 50-59%  → 5連敗
            勝率 49%以下 → 7連敗（より保守的に設定）
    """
    if win_rate >= 60:
        return 3
    if win_rate >= 50:
        return 5
    return 7


def _assessment_summary(grade: str, win_rate: float, trades: int) -> str:
    """運用適性グレードと統計から人間向けのサマリー文を生成する。

    Args:
        grade: 運用適性グレード（"A", "B", "C", "D"）
        win_rate: バックテスト勝率（%）
        trades: バックテストでのトレード総数

    Returns:
        運用適性の日本語サマリー文字列。
        データ不足・合格・不合格の3パターンを返す。
    """
    # トレード数が少なすぎる場合は信頼性が低いため別メッセージを返す
    if trades < 10:
        return "データ不足 — 期間を延長するか別通貨ペアを検討してください。"
    if grade in ("A", "B"):
        return f"勝率 {win_rate}% — シミュレーション上、運用開始の条件を満たしています。"
    return f"勝率 {win_rate}% — プリセット変更または信頼度閾値の引き上げを推奨します。"

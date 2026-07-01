"""
高度リスク管理モジュール（ドローダウン・VaR・資金配分・損切り提案）

このモジュールは FX トレードにおける包括的なリスク評価を行い、
以下の指標を統合して「エントリー可否」の判断を支援する。

主な機能:
- 最大ドローダウン（MDD）: 高値からの最大下落率
- VaR（Value at Risk）: 歴史的シミュレーション法による損失リスク推計
- ボラティリティ逆数ウェイト法: 複数通貨ペアへの資金配分最適化
- シナリオ分析: ATR ベースの 3 シナリオ（強気・基本・弱気）
- ストレステスト: 連続損失時の口座残高シミュレーション
- リスクスコア（0〜100）: 複数要因を統合した総合リスク評価
- トレード適合性チェックリスト: マルチ TF・イベントリスク等の総合判定

リスク管理の基本方針:
- 1 トレードリスク: 推奨 1% 以下、2% 超は要警告
- 最大同時ポジションリスク: 口座残高の 5% 以下
- ストップロス: ATR × 1.5 倍を基準とし、ボラ環境に応じて調整
"""

import pandas as pd

from src.analysis.market_deep import assess_event_risk, build_market_analysis
from src.analysis.multi_timeframe import analyze_multi_timeframe
from src.analysis.position_sizing import calculate_position_size, pip_size
from src.analysis.technical import compute_all_indicators
from src.analysis.volatility import calc_atr, calc_volatility_stats
from src.data.market_data import get_ohlcv_data
from src.data.sample_data import SYMBOL_BASE_PRICES


def _max_drawdown(close: pd.Series) -> dict:
    """最大ドローダウン（MDD）と現在のドローダウンを計算する。

    ドローダウンとは、過去の高値（ピーク）から現在の価格までの下落率を示す指標。
    MDD（Maximum Drawdown）はトレード期間中の最悪の下落率であり、
    戦略のリスクを定量化する最も重要な指標の一つ。

    計算方法:
        rolling_max = 各時点での過去最高値（拡張ウィンドウ）
        drawdown(t) = (close(t) - rolling_max(t)) / rolling_max(t) × 100
        MDD = min(drawdown)  ← 最も深い谷（負の値）

    例: 高値 150.00 から 140.00 に下落した場合
        → ドローダウン = (140 - 150) / 150 × 100 = -6.67%

    Args:
        close: 終値の時系列 Series（pd.Series）。

    Returns:
        以下のキーを持つ dict:
        - max_drawdown_pct: 最大ドローダウン率（%、負の値）
        - current_drawdown_pct: 現在のドローダウン率（%）
        - peak_price: 現在の参照ピーク価格
    """
    # expanding().max() で各時点における過去の最高値を求める
    rolling_max = close.expanding().max()
    # 各時点のドローダウン率（%）を計算
    drawdown = (close - rolling_max) / rolling_max * 100
    mdd = float(drawdown.min())
    current_dd = float(drawdown.iloc[-1])
    return {
        "max_drawdown_pct": round(mdd, 2),
        "current_drawdown_pct": round(current_dd, 2),
        "peak_price": round(float(rolling_max.iloc[-1]), 4),
    }


def assess_advanced_risk(
    symbol: str,
    account_balance: float = 10000,
    risk_percent: float = 1.0,
    days: int = 200,
) -> dict:
    """指定通貨ペアの高度リスク評価を実施し、総合リスクレポートを返す。

    以下の情報を統合して評価する:
    1. テクニカル指標（全指標計算）
    2. ATR・ボラティリティ統計
    3. ドローダウン（MDD・現在値）
    4. ポジションサイズ推奨値（固定リスク%法）
    5. ストップロス / テイクプロフィット価格水準
    6. ボラティリティ逆数ウェイトによる資金配分

    【ボラティリティ逆数ウェイト法（Inverse Volatility Weighting）】
    各通貨ペアのボラティリティが低いほど多く配分し、
    全通貨ペアの期待リスクを均等化する手法。
        weight_i = (1 / vol_i) / Σ(1 / vol_j)
    高ボラ通貨には少額、低ボラ通貨には多額を配分する。

    Args:
        symbol:          評価対象の通貨ペア（例: "USDJPY"）。
        account_balance: 口座残高（USD）。デフォルト 10,000。
        risk_percent:    1 トレードリスク率（%）。デフォルト 1.0。
        days:            過去データ取得日数。デフォルト 200 日。

    Returns:
        symbol・source・account_balance・current_price・volatility・
        drawdown・position_sizing・stop_loss・take_profit・
        capital_allocation・risk_budget・recommendations を含む dict。
    """
    df, source = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    close = result_df["close"]
    price = float(close.iloc[-1])
    atr = calc_atr(result_df)
    vol = calc_volatility_stats(result_df)
    dd = _max_drawdown(close)

    # 固定リスク%法でポジションサイズを算出（ATR をストップ基準として使用）
    position = calculate_position_size(
        symbol, price, account_balance, risk_percent, atr=atr
    )

    # ATR × 1.5 倍をストップロス幅として採用（ボラティリティに基づく動的ストップ）
    # JPY ペアは小数点 3 桁、その他は 5 桁で丸め
    stop_price = price - atr * 1.5 if symbol.endswith("JPY") else price - atr * 1.5
    if symbol.endswith("JPY"):
        stop_price = round(price - atr * 1.5, 3)
    else:
        stop_price = round(price - atr * 1.5, 5)
    # テイクプロフィット = ストップ幅 × 2（リスクリワード比 1:2）
    tp_price = round(price + (price - stop_price) * 2, 5 if not symbol.endswith("JPY") else 3)

    # 複数通貨への資金配分（ボラ逆数ウェイト）
    # 各通貨の日次リターンの標準偏差（日次ボラティリティ）を計算し、
    # その逆数で配分比率を決定する
    allocations = []
    total_inv_vol = 0
    for sym in SYMBOL_BASE_PRICES:
        s_df, _ = get_ohlcv_data(sym, 60)
        # 日次リターンの標準偏差 = 日次ボラティリティの代理変数
        s_vol = float(s_df["close"].pct_change().std() or 0.01)
        # ボラが低い通貨ほど逆数が大きく、より多くの資金を配分される
        inv = 1 / max(s_vol, 0.0001)  # ゼロ除算防止のため最小値 0.0001 を設定
        total_inv_vol += inv
        allocations.append({"symbol": sym, "inverse_vol": round(inv, 2)})

    # 逆数の合計で正規化し、各通貨の配分比率と配分額を算出
    for a in allocations:
        a["weight_pct"] = round(a["inverse_vol"] / total_inv_vol * 100, 1)
        a["allocated_usd"] = round(account_balance * a["weight_pct"] / 100, 2)

    # リスクバジェット計算
    # 1 日あたりのリスク許容額（= 1 トレードのリスク額と同等に設定）
    daily_risk_budget = account_balance * risk_percent / 100
    # 同時ポジションの最大リスク上限: 口座残高の 5%（業界慣行）
    max_concurrent_risk = account_balance * 0.05

    return {
        "symbol": symbol.upper(),
        "source": source,
        "account_balance": account_balance,
        "current_price": price,
        "volatility": vol,
        "drawdown": dd,
        "position_sizing": position,
        "stop_loss": {
            "price": stop_price,
            "pips": position["stop_pips"],
            "atr_multiple": 1.5,  # ATR の 1.5 倍をストップとして採用
            "max_loss_usd": position["max_loss_usd"],
        },
        "take_profit": {
            "price": tp_price,
            "pips": position["suggested_take_profit_pips"],
            "risk_reward": 2.0,  # リスクリワード比 1:2（ストップの 2 倍を目標）
        },
        "capital_allocation": {
            "method": "inverse_volatility",  # ボラティリティ逆数ウェイト法
            "pairs": allocations,
        },
        "risk_budget": {
            "per_trade_usd": round(daily_risk_budget, 2),
            # 同時保有可能な最大ポジション数: 5% ÷ 1トレードリスクで算出
            "max_concurrent_exposure_usd": round(max_concurrent_risk, 2),
            "max_open_positions_suggested": max(1, int(max_concurrent_risk / max(daily_risk_budget, 1))),
        },
        "recommendations": _risk_recommendations(dd, vol, risk_percent),
    }


def _risk_recommendations(dd: dict, vol: dict, risk_pct: float) -> list[str]:
    """ドローダウン・ボラティリティ・リスク率に基づく推奨事項リストを生成する。

    各指標の閾値:
    - MDD < -10%: 大きな損失を記録しており、ポジション縮小を推奨
    - ATR% > 1.5%: 高ボラ環境。ストップ幅を広げないと振り落とされる
    - risk_pct > 2%: 1 トレードで 2% 超のリスクは破産リスクが急増

    Args:
        dd:       `_max_drawdown` の戻り値。
        vol:      `calc_volatility_stats` の戻り値。
        risk_pct: 設定リスク率（%）。

    Returns:
        推奨メッセージの文字列リスト（日本語）。
        問題なし の場合は「許容範囲」メッセージのみを返す。
    """
    recs = []
    # MDD が -10% を超える場合: 口座が大きく棄損しており、戦略の見直しが必要
    if dd["max_drawdown_pct"] < -10:
        recs.append(f"直近最大DD {dd['max_drawdown_pct']}% — ポジションサイズ縮小を検討")
    # ATR% が 1.5% 超: 高ボラ環境ではストップが刈られやすくなる
    if vol["atr_percent"] > 1.5:
        recs.append("高ボラ環境 — ストップ幅をATR×2に拡大")
    # リスク率 2% 超: 理論的には長期で破産確率が高まる水準
    if risk_pct > 2:
        recs.append("1トレードリスク2%超 — 1%以下への引き下げを推奨")
    if not recs:
        recs.append("現状のリスク水準は許容範囲 — ルール遵守を継続")
    return recs


def _historical_var(close: pd.Series, account_balance: float, confidence: float = 0.95) -> dict:
    """歴史的シミュレーション法による VaR（Value at Risk）を計算する。

    【VaR（Value at Risk）とは】
    「一定の確信度（信頼水準）のもとで、一定期間内に発生しうる最大損失額」を
    過去の実績データから推定するリスク指標。

    【歴史的シミュレーション法】
    - 過去の日次リターン分布をそのまま使用（正規分布を仮定しない）
    - 信頼水準 95% の VaR = リターン分布の下位 5% パーセンタイル
    - 例: 日次リターンの 5 パーセンタイルが -1.2% の場合
          VaR = 口座残高 × 1.2% の損失が 95% の確率で上限

    注意: VaR は「最悪ケースの損失」ではなく「通常の悪いケース」の推定。
          テールリスク（極端な損失）には CVaR/ES が必要。

    Args:
        close:           終値の時系列 Series。
        account_balance: 口座残高（USD）。VaR の USD 換算に使用。
        confidence:      信頼水準（デフォルト 0.95 = 95%）。

    Returns:
        以下のキーを持つ dict:
        - confidence: 設定した信頼水準
        - daily_var_pct: 日次 VaR（%）- 負の値
        - daily_var_usd: 日次 VaR（USD）
        - observations: 計算に使用した日数
        データが 20 日未満の場合は全て 0.0 を返す。
    """
    returns = close.pct_change().dropna()
    # 計算に必要な最低サンプル数（20 日）を確保できない場合はスキップ
    if len(returns) < 20:
        return {
            "confidence": confidence,
            "daily_var_pct": 0.0,
            "daily_var_usd": 0.0,
            "observations": len(returns),
        }
    # 信頼水準 95% の VaR: 下位 5% パーセンタイルのリターンを取得
    # quantile(1 - 0.95) = quantile(0.05) = 下位 5% の値（負の値）
    var_pct = float(returns.quantile(1 - confidence) * 100)
    var_usd = round(account_balance * abs(var_pct) / 100, 2)
    return {
        "confidence": confidence,
        "daily_var_pct": round(var_pct, 3),
        "daily_var_usd": var_usd,
        "observations": len(returns),
    }


def _scenario_analysis(symbol: str, price: float, atr: float) -> dict:
    """ATR を基準にした 1 日先の価格シナリオ分析を行う。

    ATR（Average True Range）は 1 日の典型的な値幅を表すため、
    これを基準とした 3 つのシナリオ（強気・現状・弱気）を設定する。

    シナリオ設定:
    - 強気（Bull）: 現在価格 + ATR（上方向に 1ATR 分移動）
    - 基本（Base）: 現在価格（変化なし）
    - 弱気（Bear）: 現在価格 - ATR（下方向に 1ATR 分移動）

    move_pips は ATR を pip 単位に換算したもので、
    各シナリオの変動幅を直感的に把握できる。

    Args:
        symbol: 通貨ペアシンボル。価格の丸め桁数と pip_size の決定に使用。
        price:  現在の市場価格。
        atr:    ATR 値（1 日の典型的な値幅）。

    Returns:
        horizon・bull・base・bear の各シナリオを含む dict。
        各シナリオは price・change_pips・label を持つ。
    """
    sym = symbol.upper()
    # JPY ペアは小数点 3 桁、その他は 5 桁で価格を丸める
    decimals = 3 if sym.endswith("JPY") else 5
    bull = round(price + atr, decimals)
    base = round(price, decimals)
    bear = round(price - atr, decimals)
    pip = pip_size(sym)
    # ATR を pip 単位に換算（ATR ÷ pip_size）
    move_pips = round(atr / pip, 1) if pip else 0
    return {
        "horizon": "1日（ATRベース）",
        "bull": {"price": bull, "change_pips": move_pips, "label": "上振れシナリオ"},
        "base": {"price": base, "change_pips": 0, "label": "現状維持"},
        "bear": {"price": bear, "change_pips": -move_pips, "label": "下振れシナリオ"},
    }


def _stress_test(account_balance: float, risk_percent: float, consecutive_losses: int = 3) -> dict:
    """連続損失（ストレスシナリオ）時の口座残高への影響をシミュレーションする。

    固定リスク%法を採用していても、連続損失が続くと口座残高は
    段階的に減少する。このストレステストは最悪シナリオを可視化する。

    計算方法（簡易固定額モデル）:
        1 トレードあたりの損失 = 口座残高 × risk_percent / 100
        合計損失 = 1 トレード損失 × 連続損失回数
        残高 = 初期口座残高 - 合計損失

    Note: 厳密な固定リスク%法は連続損失のたびに口座残高が更新されるが、
          本関数は分かりやすさのため固定額モデルを使用している。

    Args:
        account_balance:    初期口座残高（USD）。
        risk_percent:       1 トレードリスク率（%）。
        consecutive_losses: 想定する連続損失回数（デフォルト 3）。

    Returns:
        以下のキーを持つ dict:
        - consecutive_losses: 想定連続損失回数
        - loss_per_trade_usd: 1 トレードあたりの損失額（USD）
        - total_loss_usd: 合計損失額（USD）
        - remaining_balance_usd: 残高（USD）
        - remaining_pct: 残高率（%）
        - interpretation: 損失影響の説明文
    """
    per_trade = account_balance * risk_percent / 100
    total_loss = round(per_trade * consecutive_losses, 2)
    remaining = round(account_balance - total_loss, 2)
    remaining_pct = round(remaining / account_balance * 100, 1) if account_balance else 0
    return {
        "consecutive_losses": consecutive_losses,
        "loss_per_trade_usd": round(per_trade, 2),
        "total_loss_usd": total_loss,
        "remaining_balance_usd": remaining,
        "remaining_pct": remaining_pct,
        "interpretation": (
            f"{consecutive_losses}連敗で口座の{100 - remaining_pct:.1f}%を失う想定"
            if remaining_pct < 100
            else "ストレスシナリオなし"
        ),
    }


def _compute_risk_score(
    dd: dict,
    vol: dict,
    risk_pct: float,
    event_level: str,
    regime: str,
) -> dict:
    """複数のリスク要因を統合したリスクスコア（0〜100）を算出する。

    リスクスコアは 100 点満点からの減点方式で計算する。
    スコアが高いほどリスクが低く、安全にトレードできる状態を示す。

    【減点項目と根拠】
    - 現在 DD < -5%: -15 点（既存ポジションが含み損）
    - MDD < -15%: -20 点（過去の大きな損失履歴）
    - ATR% > 2.0%: -20 点（高ボラ環境）
    - ATR% > 1.5%: -10 点（中程度のボラ）
    - risk_pct > 2%: -25 点（過大リスク）
    - risk_pct > 1.5%: -10 点（やや高いリスク）
    - イベントリスク高: -25 点（重大経済指標・中銀発表等が近い）
    - イベントリスク中: -10 点
    - 高ボラレジーム: -15 点（相場全体が不安定）

    スコア判定基準:
    - 75〜100: リスク低（グリーン）→ 通常通りのエントリー可
    - 50〜74: リスク中（イエロー）→ ポジション縮小・待機を検討
    - 0〜49: リスク高（レッド）→ 新規エントリーは慎重に

    Args:
        dd:           `_max_drawdown` の戻り値。
        vol:          `calc_volatility_stats` の戻り値。
        risk_pct:     設定リスク率（%）。
        event_level:  イベントリスクレベル（"high" | "medium" | "low"）。
        regime:       相場レジーム（"trending" | "ranging" | "volatile"）。

    Returns:
        score（0〜100）・level（"low"|"medium"|"high"）・label（日本語説明）を含む dict。
    """
    score = 100
    # ドローダウンによる減点: 現在の含み損と最大損失履歴を評価
    if dd["current_drawdown_pct"] < -5:
        score -= 15
    if dd["max_drawdown_pct"] < -15:
        score -= 20
    # ボラティリティによる減点: ATR% で相場の荒れ具合を評価
    if vol["atr_percent"] > 2.0:
        score -= 20
    elif vol["atr_percent"] > 1.5:
        score -= 10
    # リスク率による減点: 1 トレードリスクの大きさを評価
    if risk_pct > 2:
        score -= 25
    elif risk_pct > 1.5:
        score -= 10
    # イベントリスクによる減点: 重大経済指標・中銀発表等の近接度
    if event_level == "high":
        score -= 25
    elif event_level == "medium":
        score -= 10
    # 相場レジームによる減点: 高ボラレジームは予測困難
    if regime == "volatile":
        score -= 15
    # スコアは 0〜100 の範囲に制限
    score = max(0, min(100, score))

    # スコアに応じたリスクレベルと推奨アクションを設定
    if score >= 75:
        level, label = "low", "リスク低 — 計画通りのエントリー可"
    elif score >= 50:
        level, label = "medium", "リスク中 — サイズ縮小・待機を検討"
    else:
        level, label = "high", "リスク高 — 新規エントリーは慎重に"
    return {"score": score, "level": level, "label": label}


def _build_checklist(
    mtf: dict,
    event_risk: dict,
    dd: dict,
    vol: dict,
    risk_pct: float,
    regime: str,
) -> list[dict]:
    """エントリー前チェックリストを構築する。

    各チェック項目を "pass" / "warn" / "fail" の 3 段階で評価する。
    これはトレード前の最終確認リストとして機能する。

    チェック項目と判定閾値:
    1. マルチ TF 整合: 複数時間足でトレンド方向が一致しているか
    2. イベントリスク: 48 時間以内の高影響経済指標・中銀イベント
    3. ドローダウン: 現在の含み損が許容範囲内か
       - < -8%: fail（深刻なドローダウン）
       - < -4%: warn（要注意水準）
       - その他: pass
    4. ボラティリティ: ATR% による相場の荒れ具合
       - > 2%: fail（高ボラ）
       - > 1.5%: warn（中ボラ）
    5. 1 トレードリスク: 設定リスク率の妥当性
       - > 2%: fail
       - > 1%: warn（推奨は 1% 以下）
    6. 相場レジーム: 現在の相場環境（トレンド/レンジ/高ボラ）

    Args:
        mtf:        `analyze_multi_timeframe` の戻り値。
        event_risk: `assess_event_risk` の戻り値。
        dd:         `_max_drawdown` の戻り値。
        vol:        `calc_volatility_stats` の戻り値。
        risk_pct:   設定リスク率（%）。
        regime:     相場レジーム文字列。

    Returns:
        各チェック項目（item・status・detail）を含む dict のリスト。
    """
    items: list[dict] = []

    # マルチTF整合チェック: bullish/bearish 系のアライメントであれば pass
    aligned = mtf.get("alignment") in ("bullish", "bearish", "bullish_bias", "bearish_bias")
    items.append({
        "item": "マルチTF整合",
        "status": "pass" if aligned else "warn",
        "detail": mtf.get("alignment_label", "—"),
    })

    # イベントリスクチェック: 高影響イベント（雇用統計・FOMC 等）が近い場合は fail
    ev = event_risk.get("level", "low")
    items.append({
        "item": "イベントリスク",
        "status": "fail" if ev == "high" else ("warn" if ev == "medium" else "pass"),
        "detail": event_risk.get("label", "—"),
    })

    # ドローダウンチェック: 現在 DD が深いほど追加リスクを取るべきでない
    items.append({
        "item": "ドローダウン",
        "status": "fail" if dd["current_drawdown_pct"] < -8 else ("warn" if dd["current_drawdown_pct"] < -4 else "pass"),
        "detail": f"現在DD {dd['current_drawdown_pct']}% / 最大 {dd['max_drawdown_pct']}%",
    })

    # ボラティリティチェック: ATR% が高いほどリスクが増大
    items.append({
        "item": "ボラティリティ",
        "status": "fail" if vol["atr_percent"] > 2 else ("warn" if vol["atr_percent"] > 1.5 else "pass"),
        "detail": f"ATR {vol['atr_percent']}%",
    })

    # リスク率チェック: 推奨は 1% 以下。2% 超は破産リスクが高まる
    items.append({
        "item": "1トレードリスク",
        "status": "fail" if risk_pct > 2 else ("warn" if risk_pct > 1 else "pass"),
        "detail": f"{risk_pct}% / 推奨1%以下",
    })

    # レジームチェック: volatile は方向感がなく損失リスクが高い
    items.append({
        "item": "相場レジーム",
        "status": "warn" if regime == "volatile" else ("pass" if regime == "trending" else "warn"),
        "detail": {"trending": "トレンド相場", "ranging": "レンジ相場", "volatile": "高ボラ相場"}.get(regime, regime),
    })

    return items


def _trade_readiness(checklist: list[dict]) -> tuple[str, str]:
    """チェックリストの結果からトレード適合性を判定する。

    判定ロジック:
    - "fail" が 1 件でもある → "red"（エントリー非推奨）
    - "warn" が 2 件以上 → "yellow"（条件付き、サイズ半減を推奨）
    - "warn" が 1 件 → "yellow"（注意してエントリー可）
    - 全て "pass" → "green"（条件良好）

    Args:
        checklist: `_build_checklist` の戻り値。

    Returns:
        (color, label) のタプル。
        color: "green" | "yellow" | "red"
        label: 日本語の推奨アクション説明
    """
    statuses = [c["status"] for c in checklist]
    if "fail" in statuses:
        return "red", "エントリー非推奨 — リスク要因を解消してから"
    if statuses.count("warn") >= 2:
        return "yellow", "条件付き — サイズ半減または待機を推奨"
    if "warn" in statuses:
        return "yellow", "注意 — ルールを厳守して限定エントリー"
    return "green", "条件良好 — 事前定義ルールに従ってエントリー可"


def build_risk_report(
    symbol: str,
    account_balance: float = 10000,
    risk_percent: float = 1.0,
    days: int = 200,
) -> dict:
    """総合リスクレポートを構築して返す。

    `assess_advanced_risk` の基本評価に加え、以下の高度分析を統合する:
    - VaR（Value at Risk）: 歴史的シミュレーション法
    - シナリオ分析: ATR ベースの 3 シナリオ（強気・基本・弱気）
    - ストレステスト: 3 連敗シミュレーション
    - リスクスコア（0〜100）: 複数要因統合スコア
    - イベントリスク: 48 時間以内の高影響イベント評価
    - 相場レジーム: 現在の市場環境分類
    - チェックリスト: エントリー前の 6 項目チェック
    - トレード適合性: 総合的なエントリー可否判定

    また、VaR が 1 トレードリスク上限の 2 倍を超える場合や
    高イベントリスク・高ボラレジームの場合は追加推奨事項を生成する。

    Args:
        symbol:          評価対象の通貨ペア（例: "USDJPY"）。
        account_balance: 口座残高（USD）。デフォルト 10,000。
        risk_percent:    1 トレードリスク率（%）。デフォルト 1.0。
        days:            過去データ取得日数。デフォルト 200 日。

    Returns:
        `assess_advanced_risk` の全キーに加え、
        value_at_risk・scenarios・stress_test・risk_score・
        event_risk・market_regime・checklist・
        trade_readiness・trade_readiness_label・recommendations を含む dict。
    """
    base = assess_advanced_risk(symbol, account_balance, risk_percent, days)
    df, _ = get_ohlcv_data(symbol, days)
    result_df = compute_all_indicators(df)
    close = result_df["close"]
    price = float(close.iloc[-1])
    atr = calc_atr(result_df)

    # 市場分析・マルチ TF 分析・イベントリスク評価を実施
    market = build_market_analysis(symbol, days)
    mtf = analyze_multi_timeframe(symbol.upper())
    # 48 時間以内のイベントリスクを評価（FOMC・雇用統計・中銀会合等）
    event_risk = assess_event_risk(48)
    regime = market["regime"]["regime"]

    # 各リスク指標を計算
    var = _historical_var(close, account_balance)
    scenarios = _scenario_analysis(symbol, price, atr)
    stress = _stress_test(account_balance, risk_percent)
    risk_score = _compute_risk_score(
        base["drawdown"], base["volatility"], risk_percent, event_risk["level"], regime
    )
    checklist = _build_checklist(
        mtf, event_risk, base["drawdown"], base["volatility"], risk_percent, regime
    )
    readiness, readiness_label = _trade_readiness(checklist)

    # 推奨事項リストを構築（基本推奨 + 状況に応じた追加推奨）
    recs = list(base["recommendations"])
    # 高影響イベントが近い場合は最優先で警告を追加
    if event_risk["level"] == "high":
        recs.insert(0, "48時間以内に高影響イベント — ポジション保有・新規エントリーを控える")
    # 高ボラレジームではスリッページリスクを警告
    if regime == "volatile":
        recs.append("高ボラレジーム — 指値・ストップのスリッページを想定")
    # VaR が 1 トレードリスクの 2 倍を超える場合は注意喚起
    if var["daily_var_usd"] > base["risk_budget"]["per_trade_usd"] * 2:
        recs.append(f"1日VaR ${var['daily_var_usd']} — 1トレードリスク上限を超えないよう注意")

    return {
        **base,
        "value_at_risk": var,
        "scenarios": scenarios,
        "stress_test": stress,
        "risk_score": risk_score,
        "event_risk": event_risk,
        "market_regime": market["regime"],
        "checklist": checklist,
        "trade_readiness": readiness,
        "trade_readiness_label": readiness_label,
        "recommendations": recs,
    }

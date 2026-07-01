"""
オートセレクトモジュール

3 問アンケート（運用金額 / 運用期間 / リスク許容度）と任意のスタイル指定から、
最適なストラテジープリセット・設定値を自動選択するユーティリティ。

トライオートFX の「かんたん設定」相当の機能として、初心者ユーザーが
専門知識なしに適切な設定を取得できるよう設計されている。

プリセット種類:
    - conservative (安定型)  : 低リスク・小ロット・長めのクールダウン
    - balanced    (バランス型): 標準リスク・中ロット・中程度のクールダウン
    - aggressive  (積極型)   : 高リスク・大ロット・短めのクールダウン
    - range_repeat (レンジ型) : レンジ相場を繰り返しトレードする設定
    - trend_follow (トレンド型): トレンド相場に追随する設定
"""

from src.autotrade.presets import STRATEGY_PRESETS, apply_preset
from src.data.sample_data import SYMBOL_BASE_PRICES

# 運用資金カテゴリと代表金額のマッピング
# - small  : 5,000 USD 相当の小額運用
# - medium : 20,000 USD 相当の中程度運用
# - large  : 100,000 USD 相当の大額運用
CAPITAL_MAP = {
    "small": 5000,
    "medium": 20000,
    "large": 100000,
}

# 運用期間カテゴリと対応するスケジューラ・クールダウン設定のマッピング
# - short  : 短期運用（頻繁なエントリー、短いクールダウン）
# - medium : 中期運用（標準設定）
# - long   : 長期運用（少数精鋭のエントリー、長いクールダウン）
HORIZON_MAP = {
    "short": {"cooldown_minutes": 30, "max_daily_trades": 4, "scheduler_interval_minutes": 10},
    "medium": {"cooldown_minutes": 60, "max_daily_trades": 3, "scheduler_interval_minutes": 15},
    "long": {"cooldown_minutes": 120, "max_daily_trades": 2, "scheduler_interval_minutes": 30},
}

# リスク許容度とプリセット ID のマッピング
# アンケート回答「low/medium/high」から appropriate なプリセットを選択する
RISK_PRESET = {
    "low": "conservative",   # 安定型: 損失を最小限に抑えることを優先
    "medium": "balanced",    # バランス型: リターンとリスクのバランスを重視
    "high": "aggressive",    # 積極型: 高リターンを目指し、より大きなリスクを許容
}

# トレードスタイルとプリセット ID のマッピング
# "auto" の場合はリスク許容度からプリセットを選択する
STYLE_PRESET = {
    "range": "range_repeat",  # レンジ相場向け: ボックス圏内の往復を繰り返す
    "trend": "trend_follow",  # トレンド相場向け: 上昇/下降トレンドへの追随
    "auto": None,             # 自動選択: risk_appetite でプリセットを決定
}


def autoselect(
    capital: str = "medium",
    horizon: str = "medium",
    risk_appetite: str = "medium",
    style: str = "auto",
    preferred_symbols: list[str] | None = None,
) -> dict:
    """
    運用金額・運用期間・リスク許容度の 3 軸 (+ 任意スタイル) から設定を生成。

    プリセット選択ロジック:
        1. style が "range" または "trend" の場合、スタイルに対応するプリセットを優先
        2. style が "auto" の場合、risk_appetite に対応するプリセットを使用
           - low    → conservative（安定型）
           - medium → balanced（バランス型）
           - high   → aggressive（積極型）

    Args:
        capital:           運用資金カテゴリ。"small" / "medium" / "large"。
                           不正値は "medium" にフォールバック。
        horizon:           運用期間カテゴリ。"short" / "medium" / "long"。
                           不正値は "medium" にフォールバック。
        risk_appetite:     リスク許容度。"low" / "medium" / "high"。
                           不正値は "medium" にフォールバック。
        style:             トレードスタイル。"range" / "trend" / "auto"。
                           不正値は "auto" にフォールバック。
        preferred_symbols: 優先通貨ペアリスト（例: ["USDJPY", "EURUSD"]）。
                           None の場合は ["USDJPY"] を使用。最大 3 件。
                           サポート外シンボルは除外される。

    Returns:
        以下のキーを含む辞書:
            - recommended_preset: 選択されたプリセット ID
            - preset_label:       プリセットの日本語ラベル
            - config:             適用済み設定辞書（account_balance・シンボル等を含む）
            - rationale:          選択理由の日本語説明文
            - questions_answered: アンケート回答内容（capital / horizon / risk_appetite / style）
    """
    # 各パラメータが不正値の場合はデフォルト値にフォールバック
    capital = capital if capital in CAPITAL_MAP else "medium"
    horizon = horizon if horizon in HORIZON_MAP else "medium"
    risk_appetite = risk_appetite if risk_appetite in RISK_PRESET else "medium"
    style = style if style in STYLE_PRESET else "auto"

    # プリセット選択: style が明示指定された場合はスタイルを優先、
    # auto の場合はリスク許容度に基づいて選択
    if style != "auto" and STYLE_PRESET[style]:
        preset_id = STYLE_PRESET[style]
    else:
        preset_id = RISK_PRESET[risk_appetite]

    # プリセットを適用し、資金額・期間設定を上書き
    config = apply_preset(preset_id)
    config["account_balance"] = CAPITAL_MAP[capital]
    config.update(HORIZON_MAP[horizon])

    # 通貨ペアのバリデーション: サポート外シンボルを除外し最大 3 件に制限
    symbols = preferred_symbols or ["USDJPY"]
    config["symbols"] = [s.upper() for s in symbols if s.upper() in SYMBOL_BASE_PRICES][:3]
    # バリデーション後にリストが空になった場合は USDJPY をデフォルトとする
    if not config["symbols"]:
        config["symbols"] = ["USDJPY"]

    preset = STRATEGY_PRESETS[preset_id]
    return {
        "recommended_preset": preset_id,
        "preset_label": preset["label"],
        "config": config,
        "rationale": _rationale(capital, horizon, risk_appetite, style, preset_id),
        "questions_answered": {
            "capital": capital,
            "horizon": horizon,
            "risk_appetite": risk_appetite,
            "style": style,
        },
    }


def _rationale(capital, horizon, risk, style, preset_id) -> str:
    """
    アンケート回答とプリセット選択理由を日本語テキストで返す内部ヘルパー。

    Args:
        capital:   運用資金カテゴリ（"small" / "medium" / "large"）
        horizon:   運用期間カテゴリ（"short" / "medium" / "long"）
        risk:      リスク許容度（"low" / "medium" / "high"）
        style:     トレードスタイル（"range" / "trend" / "auto"）
        preset_id: 選択されたプリセット ID

    Returns:
        「運用資金〇〇・期間〇〇・リスク〇〇に基づき、プリセット名を推奨します」
        という形式の日本語説明文
    """
    # 英語カテゴリキーを日本語表示名に変換
    cap_ja = {"small": "小額", "medium": "中程度", "large": "大額"}.get(capital, capital)
    hor_ja = {"short": "短期", "medium": "中期", "long": "長期"}.get(horizon, horizon)
    risk_ja = {"low": "低リスク", "medium": "標準", "high": "高リスク"}.get(risk, risk)
    preset = STRATEGY_PRESETS[preset_id]
    return (
        f"運用資金「{cap_ja}」· 期間「{hor_ja}」· リスク「{risk_ja}」に基づき、"
        f"「{preset['label']}」({preset['description'][:40]}…) を推奨します。"
    )

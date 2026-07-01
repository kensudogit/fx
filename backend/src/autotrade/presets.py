"""
プリセット戦略モジュール（トライオートFX セレクト相当）

定義済みの取引戦略設定（プリセット）を管理するモジュール。
各プリセットはリスク許容度・取引スタイル・シグナルソースなどの
パラメータセットを定義しており、ユーザーが目的に応じて選択できる。

プリセット種別:
    - conservative: 安定型（低リスク・高信頼度・初心者向け）
    - balanced: バランス型（AI + テクニカル統合・中程度リスク）
    - aggressive: 積極型（高頻度・低閾値・上級者向け）
    - range_repeat: レンジリピート型（ボリンジャーバンド中心・リピート売買）
    - trend_follow: トレンドフォロー型（MTF + ML 順張り）
"""

# プリセット定義辞書
# キー: プリセット ID（文字列）
# 値: 各取引パラメータを含む辞書
STRATEGY_PRESETS: dict[str, dict] = {
    "conservative": {
        # プリセット識別子
        "id": "conservative",
        # 表示名
        "label": "安定型",
        # プリセットの説明文（UI 表示用）
        "description": "低リスク・高信頼度。初心者向け。MTF一致とイベント回避を厳格化。",
        # 取引スタイル: "trend"（トレンドフォロー）または "range"（レンジ売買）
        "style": "trend",
        # シグナル採用の最低信頼度閾値（%）。これ未満のシグナルは無視される
        "min_confidence": 75,
        # 1トレードあたりの口座残高に対するリスク割合（%）
        "risk_percent": 0.5,
        # 1日あたりの最大取引回数
        "max_daily_trades": 2,
        # 連続取引間の最低待機時間（分）。過剰売買を防ぐクールダウン
        "cooldown_minutes": 120,
        # True の場合、複数時間足のトレンドが一致しているときのみエントリー
        "require_mtf_alignment": True,
        # 重要経済指標発表前後の取引回避時間（時間）
        "event_blackout_hours": 8,
        # 使用するシグナルソース（AI予測・テクニカル分析・マルチタイムフレーム）
        "sources": ["ai", "technical", "mtf"],
        # リスクリワード比（期待利益 / 許容損失）
        "risk_reward": 2.0,
        # True の場合、逆方向シグナルでポジションを自動決済
        "auto_exit_on_reverse": True,
        # 最小発注単位（通貨）
        "min_units": 1000,
    },
    "balanced": {
        "id": "balanced",
        "label": "バランス型",
        "description": "AI + テクニカル + 統合分析の標準構成。中程度のリスク。",
        "style": "trend",
        # 信頼度閾値を 65% に設定（conservative より緩め）
        "min_confidence": 65,
        # リスク 1.0%（conservative の2倍）
        "risk_percent": 1.0,
        # 1日3回まで取引可能
        "max_daily_trades": 3,
        # クールダウン 60分
        "cooldown_minutes": 60,
        "require_mtf_alignment": True,
        # 経済指標前後4時間を回避
        "event_blackout_hours": 4,
        # intelligence（統合分析）も追加
        "sources": ["ai", "technical", "intelligence", "mtf"],
        "risk_reward": 2.0,
        "auto_exit_on_reverse": True,
        "min_units": 1000,
    },
    "aggressive": {
        "id": "aggressive",
        "label": "積極型",
        "description": "信頼度閾値を下げ取引頻度を上げる。上級者向け。",
        "style": "trend",
        # 信頼度閾値を 55% まで引き下げ（取引機会を増やす）
        "min_confidence": 55,
        # リスク 1.5%（最大）
        "risk_percent": 1.5,
        # 1日5回まで取引可能
        "max_daily_trades": 5,
        # クールダウン 30分（短め）
        "cooldown_minutes": 30,
        # MTF一致不要（シグナルが揃わなくてもエントリー）
        "require_mtf_alignment": False,
        # 経済指標前後2時間のみ回避
        "event_blackout_hours": 2,
        # TradingView シグナルも追加（全ソース活用）
        "sources": ["ai", "technical", "intelligence", "mtf", "tradingview"],
        # リスクリワード比は 1.5（conservative/balanced より低め）
        "risk_reward": 1.5,
        "auto_exit_on_reverse": True,
        "min_units": 1000,
    },
    "range_repeat": {
        "id": "range_repeat",
        "label": "レンジリピート型",
        "description": "ボリンジャーバンド中心のレンジ売買。トライオートFX リピート系に近い構成。",
        # レンジ売買スタイル（トレンドフォローではない）
        "style": "range",
        # 信頼度閾値を 50% に設定（比較的緩い）
        "min_confidence": 50,
        "risk_percent": 0.8,
        # 高頻度（1日6回）のリピート売買
        "max_daily_trades": 6,
        # クールダウン短め（20分）
        "cooldown_minutes": 20,
        # レンジ売買なので MTF一致は不要
        "require_mtf_alignment": False,
        "event_blackout_hours": 4,
        # テクニカル分析のみ使用
        "sources": ["technical"],
        # 利確幅は小さめ（リピート売買の特性）
        "risk_reward": 1.2,
        # レンジ売買では逆シグナル決済を無効化（双方向保有）
        "auto_exit_on_reverse": False,
        "min_units": 1000,
    },
    "trend_follow": {
        "id": "trend_follow",
        "label": "トレンドフォロー型",
        "description": "MTF + ML トレンドに沿った順張り。テクニカルビルダー相当。",
        "style": "trend",
        "min_confidence": 60,
        "risk_percent": 1.0,
        # 1日4回まで（balanced と aggressive の中間）
        "max_daily_trades": 4,
        "cooldown_minutes": 45,
        # MTF一致必須（複数時間足でトレンドが揃っていることを確認）
        "require_mtf_alignment": True,
        "event_blackout_hours": 4,
        # テクニカル + MTF + AI の三位一体
        "sources": ["technical", "mtf", "ai"],
        # 高いリスクリワード比（2.5）でトレンド相場の利益を最大化
        "risk_reward": 2.5,
        "auto_exit_on_reverse": True,
        "min_units": 1000,
    },
}


def list_presets() -> list[dict]:
    """利用可能なプリセット一覧を UI 表示用に返す。

    内部パラメータ（sources, cooldown_minutes 等）は含めず、
    ユーザーが選択判断に必要な主要パラメータのみを返す。

    Returns:
        プリセット情報の辞書リスト。各辞書:
            - id: プリセット識別子
            - label: 表示名
            - description: 説明文
            - style: 取引スタイル（"trend" または "range"）
            - min_confidence: 最低信頼度閾値（%）
            - risk_percent: リスク割合（%）
            - risk_reward: リスクリワード比
    """
    return [
        {
            "id": p["id"],
            "label": p["label"],
            "description": p["description"],
            "style": p["style"],
            "min_confidence": p["min_confidence"],
            "risk_percent": p["risk_percent"],
            "risk_reward": p["risk_reward"],
        }
        for p in STRATEGY_PRESETS.values()
    ]


def apply_preset(preset_id: str, config: dict | None = None) -> dict:
    """指定プリセットのパラメータを既存設定にマージして返す。

    既存の config が指定された場合はそれをベースとし、
    プリセットのパラメータを上書きする（プリセット優先）。
    id, label, description, style はメタ情報のため除外する。

    Args:
        preset_id: 適用するプリセットの ID
        config: ベースとなる既存設定辞書（None の場合は空辞書をベースとする）

    Returns:
        プリセットパラメータをマージした設定辞書。
        strategy_preset キーにプリセット ID が記録される。

    Raises:
        ValueError: 指定された preset_id が存在しない場合
    """
    preset = STRATEGY_PRESETS.get(preset_id)
    if not preset:
        raise ValueError(f"Unknown preset: {preset_id}")

    # 既存設定をコピーしてベースとする
    base = {**(config or {})}

    # プリセットのパラメータをマージ（メタ情報キーは除外）
    for key, val in preset.items():
        if key not in ("id", "label", "description", "style"):
            base[key] = val

    # どのプリセットを適用したかを記録
    base["strategy_preset"] = preset_id
    return base

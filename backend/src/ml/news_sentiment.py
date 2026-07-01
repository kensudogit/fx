"""
機械学習ベースのニュースセンチメント分析モジュール

OpenAI API を使わずに、キーワードマッチングのみで
FX 関連ニュースヘッドラインのセンチメント（強気/弱気/中立）を判定するモジュール。

手法:
    - 強気（Bullish）キーワードと弱気（Bearish）キーワードの出現頻度を集計
    - スコア = (強気ヒット数 - 弱気ヒット数) / 総ヒット数 × 100
    - スコア > 15 → bullish、< -15 → bearish、それ以外 → neutral

対応言語:
    - 英語: rise, rally, gain, surge, strong, hawkish 等
    - 日本語: 上昇, 高, 強い, 買い, 好調 等

制限事項:
    - 文脈を考慮しない単純なキーワードマッチング
    - 否定表現（例: "not rising"）を正確に処理できない
    - OpenAI API 版（llm_sentiment）と比べて精度は低いが API コストゼロ
"""

import re
from collections import Counter

# 強気センチメントを示すキーワードセット（英語・日本語）
# hawkish（タカ派）= 利上げ・金融引き締め傾向、FX では通貨高要因
BULLISH_WORDS = {
    "rise", "rally", "gain", "surge", "strong", "hawkish", "beat", "growth",
    "上昇", "高", "強い", "買い", "好調", "拡大",
}

# 弱気センチメントを示すキーワードセット（英語・日本語）
# dovish（ハト派）= 利下げ・金融緩和傾向、FX では通貨安要因
BEARISH_WORDS = {
    "fall", "drop", "decline", "weak", "dovish", "miss", "recession", "cut",
    "下落", "低", "弱い", "売り", "悪化", "縮小",
}


def analyze_headlines_ml(headlines: list[str]) -> dict:
    """ニュースヘッドラインのリストからセンチメントを ML キーワード分析で判定する。

    処理フロー:
        1. 全ヘッドラインを結合して小文字化
        2. 正規表現で英数字・日本語文字をトークン化
        3. 強気/弱気キーワードとの部分一致でスコアを計算
        4. スコアに基づいてセンチメントラベルを決定
        5. 頻出トークンをキートピックとして抽出

    スコア計算:
        score = (bull - bear) / total × 100
        - -100 〜 +100 の範囲にクリップ
        - > +15 → bullish、< -15 → bearish、それ以外 → neutral

    Args:
        headlines: ニュースヘッドラインの文字列リスト

    Returns:
        センチメント分析結果の辞書:
            - method: 分析手法（"ml_keyword"）
            - sentiment: "bullish", "bearish", "neutral" のいずれか
            - sentiment_score: スコア（-100 〜 +100）
            - bullish_hits: 強気キーワードのヒット数
            - bearish_hits: 弱気キーワードのヒット数
            - key_topics: 頻出トークンのトップ5（3文字以上のもの）
            - summary: 日本語サマリー文
    """
    # 全ヘッドラインを1つの文字列に結合して小文字化
    text = " ".join(headlines).lower()

    # 英数字・ひらがな・カタカナ・漢字をトークンとして抽出
    # [a-zA-Zぁ-んァ-ン一-龥] は英字・ひらがな・カタカナ・漢字の文字クラス
    tokens = re.findall(r"[a-zA-Zぁ-んァ-ン一-龥]+", text)

    # 強気キーワードのヒット数を集計
    # 完全一致（t in BULLISH_WORDS）または部分一致（any(w in t for w in ...)）の両方を考慮
    bull = sum(1 for t in tokens if t in BULLISH_WORDS or any(w in t for w in BULLISH_WORDS))
    bear = sum(1 for t in tokens if t in BEARISH_WORDS or any(w in t for w in BEARISH_WORDS))

    # ゼロ除算を防ぐため、総ヒット数は最低 1
    total = bull + bear or 1

    # センチメントスコアを計算（-100 〜 +100 にクリップ）
    score = int((bull - bear) / total * 100)
    score = max(-100, min(100, score))

    # スコアに基づいてセンチメントラベルを決定
    if score > 15:
        sentiment = "bullish"   # 強気（買い優位）
    elif score < -15:
        sentiment = "bearish"   # 弱気（売り優位）
    else:
        sentiment = "neutral"   # 中立（方向感なし）

    # 頻出トークンからキートピックを抽出
    # 3文字以上のトークンのみ対象（単文字・2文字は意味をなさない場合が多い）
    # Counter.most_common(8) で上位8トークンを取得し、上位5件を返す
    topics = [w for w, c in Counter(tokens).most_common(8) if len(w) > 2][:5]

    return {
        "method": "ml_keyword",
        "sentiment": sentiment,
        "sentiment_score": score,
        "bullish_hits": bull,
        "bearish_hits": bear,
        "key_topics": topics,
        "summary": f"キーワード分析: 強気シグナル {bull} / 弱気シグナル {bear}",
    }

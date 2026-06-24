"""機械学習ベースのニュースセンチメント（OpenAI 不要）"""

import re
from collections import Counter

BULLISH_WORDS = {
    "rise", "rally", "gain", "surge", "strong", "hawkish", "beat", "growth",
    "上昇", "高", "強い", "買い", "好調", "拡大",
}
BEARISH_WORDS = {
    "fall", "drop", "decline", "weak", "dovish", "miss", "recession", "cut",
    "下落", "低", "弱い", "売り", "悪化", "縮小",
}


def analyze_headlines_ml(headlines: list[str]) -> dict:
    text = " ".join(headlines).lower()
    tokens = re.findall(r"[a-zA-Zぁ-んァ-ン一-龥]+", text)

    bull = sum(1 for t in tokens if t in BULLISH_WORDS or any(w in t for w in BULLISH_WORDS))
    bear = sum(1 for t in tokens if t in BEARISH_WORDS or any(w in t for w in BEARISH_WORDS))
    total = bull + bear or 1
    score = int((bull - bear) / total * 100)
    score = max(-100, min(100, score))

    if score > 15:
        sentiment = "bullish"
    elif score < -15:
        sentiment = "bearish"
    else:
        sentiment = "neutral"

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

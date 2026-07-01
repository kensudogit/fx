"""
SNS 分析モジュール（Reddit / Google News RSS フォールバック + センチメント分析）

このモジュールは SNS（主に Reddit）および Google News RSS から
FX 通貨ペアに関するコメント・ヘッドラインを収集し、
ML ベースのセンチメント分析を行って市場参加者の心理状態を定量化する。

【データ取得フロー】
1. Reddit 公開 JSON API: r/forex サブレディットを検索
2. フォールバック 1: Google News RSS フィード（Reddit 失敗時）
3. フォールバック 2: 事前定義サンプルデータ（RSS も失敗時）

【センチメント分析の仕組み】
- 収集したヘッドライン/投稿タイトルを ML モデル（`analyze_headlines_ml`）に入力
- モデルは各テキストのポジティブ/ネガティブ/ニュートラルスコアを算出
- 複数テキストの集計スコアから全体のセンチメント方向を決定

【エンゲージメント評価】
- Reddit の「スコア」（アップボート数 - ダウンボート数）とコメント数を集計
- 高エンゲージメント: スコア合計 > 100 または コメント合計 > 50
- 中エンゲージメント: スコア合計 > 30
- 低エンゲージメント: それ以外

【キャッシュ戦略】
センチメント分析は計算コストが高いため、`analysis_cache` を使用して
TTL（Time To Live）設定付きでキャッシュする（デフォルト設定は settings.sns_cache_ttl_seconds）。
"""

import logging
from datetime import datetime, timezone

import httpx

from src.config import settings
from src.infra.analysis_cache import cache_get, cache_key, cache_put
from src.ml.news_sentiment import analyze_headlines_ml

logger = logging.getLogger(__name__)

# 各通貨ペアの Reddit 検索クエリ（通貨ペア名と関連キーワードを OR 検索）
# より広い投稿を拾うために通貨ペア名と俗称の両方を含める
SYMBOL_REDDIT_QUERIES = {
    "USDJPY": "USDJPY OR dollar yen",
    "EURUSD": "EURUSD OR euro dollar",
    "GBPUSD": "GBPUSD OR pound dollar",
    "AUDUSD": "AUDUSD OR aussie dollar",
}

# Reddit と Google News RSS の両方が失敗した場合のサンプルデータ
# 最低限のデータ構造を保証するためのフォールバック
FALLBACK_SNS = {
    "USDJPY": [
        {"title": "Dollar/yen watching BOJ policy closely", "subreddit": "forex", "score": 42},
        {"title": "USDJPY breakout above 150?", "subreddit": "Forexstrategy", "score": 18},
    ],
    "EURUSD": [
        {"title": "ECB vs Fed — EURUSD range trade", "subreddit": "forex", "score": 35},
    ],
    "GBPUSD": [
        {"title": "Cable volatility ahead of UK data", "subreddit": "forex", "score": 28},
    ],
    "AUDUSD": [
        {"title": "AUDUSD tied to China PMI expectations", "subreddit": "forex", "score": 22},
    ],
}


async def _fetch_rss_as_posts(symbol: str, limit: int) -> list[dict]:
    """Reddit 失敗時に Google News RSS ヘッドラインを SNS 投稿形式で返す。

    Google News RSS から取得した記事を Reddit 投稿と同じスキーマに変換することで、
    後続の処理（センチメント分析・エンゲージメント計算）を共通化できる。

    RSS 記事の変換マッピング:
    - title → title（そのまま使用）
    - link → url
    - subreddit: "google_news"（固定値、プラットフォーム識別用）
    - score: 0（RSS には投票データがないため 0 を設定）
    - num_comments: 0（同上）
    - published → published_at
    - source: "google_news"（プラットフォームラベル表示用）

    Args:
        symbol: 通貨ペアシンボル（例: "USDJPY"）。RSS 検索クエリに使用。
        limit:  取得する最大記事数。

    Returns:
        SNS 投稿形式（Reddit スキーマ互換）の dict リスト。
        取得失敗または記事なしの場合は空リストを返す。
    """
    from src.ai.news import fetch_rss_news

    try:
        articles = await fetch_rss_news(symbol, limit)
        if not articles:
            return []
        return [
            {
                "title": a.get("title", ""),
                "url": a.get("link", ""),
                "subreddit": "google_news",
                "score": 0,
                "num_comments": 0,
                "published_at": a.get("published", datetime.now(timezone.utc).isoformat()),
                "source": "google_news",
            }
            for a in articles
            if a.get("title")  # タイトルが空の記事は除外
        ]
    except Exception as e:
        logger.warning("RSS SNS fallback failed for %s: %s", symbol, e)
        return []


async def fetch_reddit_posts(symbol: str, limit: int = 10) -> list[dict]:
    """Reddit 公開 JSON API から通貨ペア関連投稿を取得する（失敗時 RSS → サンプル）。

    【取得戦略（3 段階フォールバック）】
    1. Reddit r/forex サブレディット検索 API（メイン）
       - エンドポイント: https://www.reddit.com/r/forex/search.json
       - ソート: 新着順（"new"）
       - 検索クエリ: SYMBOL_REDDIT_QUERIES から通貨ペア固有のクエリを使用
    2. Google News RSS（Reddit 失敗時）
       - `_fetch_rss_as_posts` を使用して Reddit スキーマに変換
    3. 事前定義サンプルデータ（上記も失敗時）
       - FALLBACK_SNS から取得し、必要なフィールドを補完

    Reddit API の制約:
    - 1 リクエストあたり最大 25 件（limit=25 に上限制限）
    - 認証不要（公開 JSON API）だが、User-Agent を適切に設定する必要がある
    - レート制限: 過剰リクエストで一時的なブロックが発生する可能性あり

    Args:
        symbol: 通貨ペアシンボル（例: "USDJPY"）。大文字小文字不問。
        limit:  取得する最大投稿数（デフォルト 10）。最大 25 に制限。

    Returns:
        以下のキーを持つ dict のリスト:
        - title: 投稿タイトル
        - url: 投稿 URL（Reddit のパーマリンク）
        - subreddit: 投稿元サブレディット名
        - score: アップボート数 - ダウンボート数（エンゲージメント指標）
        - num_comments: コメント数（エンゲージメント指標）
        - published_at: 投稿日時（UTC ISO 形式）
        - source: データソース（"reddit" | "google_news" | "sample"）

    Raises:
        取得失敗時は例外を内部でキャッチしてフォールバックに移行するため、
        この関数自体は例外を raise しない。
    """
    query = SYMBOL_REDDIT_QUERIES.get(symbol.upper(), f"{symbol} forex")
    url = "https://www.reddit.com/r/forex/search.json"
    # restrict_sr=on: r/forex サブレディット内のみ検索（全体検索は除外）
    params = {"q": query, "sort": "new", "limit": min(limit, 25), "restrict_sr": "on"}

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            res = await client.get(
                url,
                params=params,
                headers={"User-Agent": "FXTool/1.0 (market analysis bot)"},
            )
            res.raise_for_status()
            data = res.json()

        posts = []
        for child in data.get("data", {}).get("children", [])[:limit]:
            p = child.get("data", {})
            title = p.get("title", "")
            if not title:
                continue
            posts.append({
                "title": title,
                "url": f"https://reddit.com{p.get('permalink', '')}",
                "subreddit": p.get("subreddit", "forex"),
                # score: コミュニティ評価の指標（高いほど注目度が高い）
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
                # created_utc: Unix タイムスタンプ（秒）→ ISO 形式に変換
                "published_at": datetime.fromtimestamp(
                    p.get("created_utc", 0), tz=timezone.utc
                ).isoformat(),
                "source": "reddit",
            })
        if posts:
            return posts
    except Exception as e:
        logger.warning("Reddit fetch failed for %s: %s", symbol, e)

    # フォールバック 1: Google News RSS から記事を取得
    rss_posts = await _fetch_rss_as_posts(symbol, limit)
    if rss_posts:
        return rss_posts

    # フォールバック 2: 事前定義サンプルデータを使用
    fallback = FALLBACK_SNS.get(
        symbol.upper(),
        [{"title": f"{symbol} forex discussion", "subreddit": "forex", "score": 10}],
    )
    # サンプルデータに欠けているフィールドを補完して返す
    return [
        {
            **p,
            "url": "",
            "num_comments": 0,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "source": "sample",
        }
        for p in fallback
    ]


async def analyze_sns(symbol: str, limit: int = 10) -> dict:
    """通貨ペアの SNS センチメント分析を実行し、結果を返す。

    【センチメントスコアリングと集計ロジック】
    1. 投稿取得: `fetch_reddit_posts` で最大 limit 件の投稿を取得
    2. ML 分析: 投稿タイトルを `analyze_headlines_ml` に渡して
               各タイトルのセンチメントスコアを算出
       - ポジティブスコア: 強気感情（上昇期待・良いニュース）
       - ネガティブスコア: 弱気感情（下落懸念・悪いニュース）
       - ニュートラルスコア: 中立的なコメント
    3. エンゲージメント評価: score（アップボート）と comments の合計から
       市場参加者の関心度を "high" / "medium" / "low" に分類
    4. サブレディット分布: どのコミュニティから情報が集まっているかを集計

    【エンゲージメント閾値の根拠】
    - high (> 100 スコア または > 50 コメント): 多くの参加者が反応している
      重要なニュースやイベントが発生している可能性が高い
    - medium (> 30 スコア): 一定の関心はあるが、ノイズも多い
    - low: 参加者の関心が低く、センチメントの信頼性は限定的

    Args:
        symbol: 分析対象の通貨ペア（例: "USDJPY"）。
        limit:  取得する最大投稿数（デフォルト 10）。

    Returns:
        以下のキーを持つ dict:
        - symbol: 通貨ペア（大文字）
        - collected_at: データ収集日時（UTC ISO 形式）
        - platform: データソース（"reddit" | "google_news" | "sample"）
        - platform_label: データソースの日本語ラベル
        - post_count: 取得した投稿数
        - posts: 投稿データのリスト
        - sentiment: ML センチメント分析結果（sentiment・sentiment_score 等）
        - engagement: エンゲージメントレベル（"high" | "medium" | "low"）
        - total_score: 全投稿のスコア合計
        - total_comments: 全投稿のコメント数合計
        - subreddits: サブレディット別の投稿数カウント
        - summary: 人間向けのサマリー文字列（日本語）
        キャッシュヒットの場合はキャッシュからそのまま返す。
    """
    # キャッシュキーを生成して既存キャッシュを確認（API コール削減）
    key = cache_key("sns", symbol, limit=limit)
    cached = cache_get(key)
    if cached is not None:
        return cached

    # 投稿取得 → ML センチメント分析
    posts = await fetch_reddit_posts(symbol, limit)
    headlines = [p["title"] for p in posts]
    sentiment = analyze_headlines_ml(headlines)

    # エンゲージメント集計: スコアとコメント数の合計で関心度を評価
    total_score = sum(p.get("score", 0) for p in posts)
    total_comments = sum(p.get("num_comments", 0) for p in posts)
    # エンゲージメント判定閾値
    # high: 合計スコア > 100 または コメント > 50（コミュニティで大きな話題）
    # medium: 合計スコア > 30（そこそこの関心）
    # low: それ以外（参加者の関心が薄い）
    engagement = "high" if total_score > 100 or total_comments > 50 else (
        "medium" if total_score > 30 else "low"
    )

    # サブレディット別の投稿数を集計（情報源の多様性を確認）
    sub_counts: dict[str, int] = {}
    for p in posts:
        sub = p.get("subreddit", "unknown")
        sub_counts[sub] = sub_counts.get(sub, 0) + 1

    # データソースの判定（最初の投稿の source を代表値として使用）
    primary_source = posts[0]["source"] if posts else "sample"
    platform_labels = {
        "reddit": "Reddit",
        "google_news": "Google News（Reddit 代替）",
        "sample": "サンプルデータ",
    }

    result = {
        "symbol": symbol.upper(),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "platform": primary_source,
        "platform_label": platform_labels.get(primary_source, primary_source),
        "post_count": len(posts),
        "posts": posts,
        "sentiment": sentiment,
        "engagement": engagement,
        "total_score": total_score,
        "total_comments": total_comments,
        "subreddits": sub_counts,
        # サマリー: プラットフォーム・件数・センチメント・エンゲージメントを 1 行でまとめる
        "summary": (
            f"{platform_labels.get(primary_source, primary_source)} {len(posts)}件 — "
            f"センチメント: {sentiment['sentiment']} "
            f"({sentiment['sentiment_score']}) / エンゲージメント: {engagement}"
        ),
    }
    # 結果をキャッシュに保存（TTL は設定値に従う）
    cache_put(key, result, ttl_seconds=settings.sns_cache_ttl_seconds)
    return result

"""
FX ニュース収集（RSS + OpenAI 分析）モジュール。

このモジュールは Google News RSS フィードから通貨ペア関連のニュースを収集し、
OpenAI GPT でセンチメント分析・市場影響評価・通貨見通しを生成する。
RSS 取得が失敗した場合は静的なフォールバックヘッドラインを使用し、
サービスの継続性を確保する。
"""

import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote

import httpx

from src.ai.client import chat_json

logger = logging.getLogger(__name__)

# 通貨ペアに対応した Google News 検索クエリのマッピング
# 英語クエリを使用することで国際的なニュースソースを幅広くカバーする
SYMBOL_NEWS_QUERIES = {
    "USDJPY": "USD JPY forex",
    "EURUSD": "EUR USD forex",
    "GBPUSD": "GBP USD forex",
    "AUDUSD": "AUD USD forex",
}

# RSS 取得失敗時に使用する静的フォールバックヘッドライン
# 各通貨ペアの重要な相場テーマを反映した代表的な見出しを定義する
FALLBACK_HEADLINES = {
    "USDJPY": [
        "米国金利動向がドル円相場を左右",
        "日銀金融政策への注目が高まる",
        "米経済指標発表を控えドル円は様子見",
    ],
    "EURUSD": [
        "欧州中央銀行の政策がユーロに影響",
        "米欧金利差がユーロドルに波及",
    ],
    "GBPUSD": [
        "英国経済指標にポンドが反応",
        "米国金利とポンドの動きに注目",
    ],
    "AUDUSD": [
        "中国経済指標が豪ドルに影響",
        "商品価格動向が豪ドル相場を左右",
    ],
}


def _fallback_articles(symbol: str) -> list[dict]:
    """
    RSS 取得失敗時に静的フォールバック記事リストを返す。

    ネットワークエラーや Google News のブロック時でも最低限のニュースデータを
    提供できるようにするための安全網。フォールバック記事には空の URL を設定する。

    Args:
        symbol: 通貨ペアのシンボル（例: "USDJPY"）

    Returns:
        list[dict]: フォールバックヘッドラインの記事リスト（各要素: title・url・published_at・source）
    """
    # 未登録の通貨ペアには汎用的なフォールバックヘッドラインを使用する
    headlines = FALLBACK_HEADLINES.get(symbol.upper(), [f"{symbol} 為替市場の動向"])
    return [
        {
            "title": title,
            # フォールバック記事は URL を持たないため空文字を設定する
            "url": "",
            # 現在時刻をフォールバック記事の公開日時として使用する
            "published_at": datetime.utcnow().isoformat(),
            # フォールバック記事のソースを識別可能にするためアプリ名を設定する
            "source": "FX Tool",
        }
        for title in headlines
    ]


async def fetch_rss_news(symbol: str, limit: int = 10) -> list[dict]:
    """
    Google News RSS からニュースを収集する（失敗時はフォールバックを返す）。

    通貨ペアに対応した検索クエリで Google News RSS を取得し、
    最新の limit 件のニュースを構造化された辞書のリストとして返す。
    タイムアウトや HTTP エラーの場合は静的フォールバック記事に切り替える。

    Args:
        symbol: 通貨ペアのシンボル（例: "USDJPY"）
        limit: 取得するニュースの最大件数（デフォルト 10）

    Returns:
        list[dict]: ニュース記事の辞書リスト（各要素: title・url・published_at・source）
                    RSS 取得失敗時はフォールバック記事リストを返す
    """
    # 通貨ペアに対応した検索クエリを取得（未登録の場合は汎用クエリを使用）
    query = SYMBOL_NEWS_QUERIES.get(symbol.upper(), f"{symbol} forex")
    # URL エンコードしてスペース等の特殊文字を安全に渡す
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"

    try:
        # timeout=15.0: ニュース取得は 15 秒以内に完了しなければタイムアウトする
        # follow_redirects=True: Google News がリダイレクトを使う場合に対応する
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={
                    # ブラウザと同じ User-Agent を設定して bot 対策を回避する
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    # RSS/XML 形式のコンテンツを優先的に受け入れる旨を指定する
                    "Accept": "application/rss+xml, application/xml, text/xml",
                },
            )
            # 4xx/5xx HTTP エラーがあれば例外を raise する
            response.raise_for_status()

        # XML 形式の RSS フィードをパースする
        root = ET.fromstring(response.content)
        items = []
        # RSS の <item> 要素を最大 limit 件だけ処理する
        for item in root.findall(".//item")[:limit]:
            title = item.findtext("title", "")
            # タイトルが空の記事はスキップする（品質管理）
            if not title:
                continue
            items.append(
                {
                    "title": title,
                    "url": item.findtext("link", ""),
                    "published_at": item.findtext("pubDate", ""),
                    # source タグがない場合は "Google News" をデフォルトとする
                    "source": item.findtext("source", "Google News"),
                }
            )
        # 1件以上取得できた場合のみ RSS の結果を返す
        if items:
            return items
    except Exception as e:
        # ネットワークエラー・パースエラー等は警告ログを記録してフォールバックに移行する
        logger.warning("RSS fetch failed for %s: %s", symbol, e)

    # RSS 取得失敗またはアイテムが 0 件の場合はフォールバック記事を返す
    return _fallback_articles(symbol)


async def analyze_news(symbol: str, limit: int = 8) -> dict:
    """
    ニュースを収集し、OpenAI でセンチメント分析・市場影響評価を行う。

    RSS から収集したニュースヘッドラインを OpenAI に渡し、
    FX アナリストの視点で市場への影響・感情・通貨見通しを JSON で生成させる。

    Args:
        symbol: 分析対象の通貨ペア（例: "USDJPY"）
        limit: 収集するニュースの最大件数（デフォルト 8）

    Returns:
        dict: ニュース分析結果を含む辞書
            - symbol: 通貨ペア
            - collected_at: データ収集時刻（ISO 8601 形式）
            - articles: 収集したニュース記事リスト
            - summary: 市場への影響の要約テキスト（3-5 文、日本語）
            - sentiment: "bullish" | "bearish" | "neutral"
            - sentiment_score: センチメントスコア（-100 から 100）
            - key_topics: 主要トピックのリスト
            - market_impact: "high" | "medium" | "low"
            - currency_outlook: 基軸・決済通貨それぞれの見通し辞書

    Raises:
        ValueError: OpenAI API エラーまたは JSON パースエラーの場合
    """
    # RSS からニュース記事を非同期で収集する
    articles = await fetch_rss_news(symbol, limit)
    # ヘッドラインを OpenAI プロンプト用のテキスト形式に整形する
    # ソース名を括弧付きで追記して信頼性の文脈を AI に伝える
    headlines = "\n".join(f"- {a['title']} ({a['source']})" for a in articles)

    # OpenAI のブロッキング呼び出しをスレッドプールで非同期実行する
    result = await asyncio.to_thread(
        chat_json,
        # FX アナリストとして bullish/bearish/neutral の三値で評価させる
        """あなたはFXアナリストです。ニュースヘッドラインを分析し、JSONのみで回答してください。
出力形式:
{
  "summary": "市場への影響を3-5文で要約（日本語）",
  "sentiment": "bullish|bearish|neutral のいずれか",
  "sentiment_score": -100から100の整数,
  "key_topics": ["トピック1", "トピック2"],
  "market_impact": "high|medium|low",
  "currency_outlook": {
    "base": "基軸通貨の見通し（1文）",
    "quote": "決済通貨の見通し（1文）"
  }
}""",
        # 通貨ペアとヘッドライン一覧を入力として渡す
        f"通貨ペア: {symbol}\n\nヘッドライン:\n{headlines}",
    )

    return {
        "symbol": symbol,
        # 分析実行時刻を記録してデータの鮮度を把握できるようにする
        "collected_at": datetime.utcnow().isoformat(),
        "articles": articles,
        # OpenAI の分析結果をアンパックして統合する
        **result,
    }

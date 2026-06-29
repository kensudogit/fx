"""起動時キャッシュウォームアップ"""

from __future__ import annotations

import asyncio
import logging

from src.api.intelligence import build_intelligence
from src.autotrade.evaluator import gather_signal_context
from src.config import settings
from src.ml.predictor import predict_price
from src.ml.trend_predictor import predict_trend
from src.analysis.multi_timeframe import analyze_multi_timeframe

logger = logging.getLogger(__name__)


async def warm_analysis_cache() -> None:
    """主要通貨ペアの分析キャッシュをバックグラウンドで事前構築"""
    if not settings.cache_warmup_enabled:
        return

    symbols = [s.strip().upper() for s in settings.cache_warmup_symbols.split(",") if s.strip()]
    if not symbols:
        return

    logger.info("cache warmup started for %s", symbols)

    async def warm_symbol(sym: str) -> None:
        try:
            await asyncio.to_thread(analyze_multi_timeframe, sym)
            await asyncio.to_thread(predict_trend, sym, 200)
            await asyncio.to_thread(predict_price, sym, 200)
            await build_intelligence(sym, 200)
            await gather_signal_context(sym, 200)
            logger.info("cache warmup done: %s", sym)
        except Exception as e:
            logger.warning("cache warmup failed for %s: %s", sym, e)

    await asyncio.gather(*(warm_symbol(s) for s in symbols))
    logger.info("cache warmup finished")

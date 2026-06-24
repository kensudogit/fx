"""初期データ投入スクリプト"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.market_data import sync_symbol_data
from src.data.sample_data import SYMBOL_BASE_PRICES


def main():
    print("=== FX Tool Data Seed ===")
    for symbol in SYMBOL_BASE_PRICES:
        print(f"Syncing {symbol}...", end=" ")
        try:
            result = sync_symbol_data(symbol, days=200)
            print(f"OK ({result['rows_synced']} rows, close={result['latest_close']})")
        except Exception as e:
            print(f"FAILED: {e}")
    print("Done.")


if __name__ == "__main__":
    main()

"""初期データ投入スクリプト — scripts.seed_data のテスト

DB への書き込みはモックへ差し替え、全通貨ペアの同期とエラー継続を検証する。
"""

import importlib
from unittest.mock import patch

import pytest

from src.data.sample_data import SYMBOL_BASE_PRICES

seed_data = importlib.import_module("scripts.seed_data")


def sync_result(rows: int = 200, close: float = 150.0) -> dict:
    """sync_symbol_data() の戻り値を模した辞書を返す。"""
    return {"symbol": "USDJPY", "rows_synced": rows, "latest_close": close,
            "latest_date": "2026-01-01"}


class TestMain:
    """main() のテスト"""

    def test_syncs_every_known_symbol(self, capsys):
        """定義済みの全通貨ペアを同期すること"""
        with patch.object(seed_data, "sync_symbol_data", return_value=sync_result()) as sync:
            seed_data.main()

        synced = [c.args[0] for c in sync.call_args_list]
        assert synced == list(SYMBOL_BASE_PRICES)

    def test_requests_200_days_of_history(self):
        """指標計算に足りる 200 日分を取得すること"""
        with patch.object(seed_data, "sync_symbol_data", return_value=sync_result()) as sync:
            seed_data.main()

        assert all(c.kwargs["days"] == 200 for c in sync.call_args_list)

    def test_reports_progress(self, capsys):
        """進捗と結果を標準出力へ書き出すこと"""
        with patch.object(seed_data, "sync_symbol_data", return_value=sync_result(rows=150)):
            seed_data.main()

        out = capsys.readouterr().out
        assert "FX Tool Data Seed" in out
        assert "150 rows" in out
        assert "Done." in out

    def test_one_failure_does_not_stop_the_rest(self, capsys):
        """1 銘柄の失敗で処理を止めないこと"""
        symbols = list(SYMBOL_BASE_PRICES)

        def sync(symbol, days):
            if symbol == symbols[0]:
                raise RuntimeError("network down")
            return sync_result()

        with patch.object(seed_data, "sync_symbol_data", side_effect=sync) as mock:
            seed_data.main()

        assert len(mock.call_args_list) == len(symbols)
        assert "FAILED: network down" in capsys.readouterr().out

    def test_completes_even_if_everything_fails(self, capsys):
        """全件失敗しても例外を送出せず完了すること"""
        with patch.object(seed_data, "sync_symbol_data", side_effect=RuntimeError("boom")):
            seed_data.main()

        assert "Done." in capsys.readouterr().out


class TestScriptStructure:
    """スクリプトの構成テスト"""

    def test_importing_does_not_run_main(self):
        """インポートだけでは同期処理を実行しないこと"""
        with patch.object(seed_data, "sync_symbol_data") as sync:
            importlib.reload(seed_data)
        sync.assert_not_called()

    def test_exposes_main(self):
        """main() を公開していること"""
        assert callable(seed_data.main)

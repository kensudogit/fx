"""ブローカー口座管理 — src.broker.accounts のテスト

DB はモックへ差し替え、口座一覧・作成・ポートフォリオ集計を検証する。
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import src.broker.accounts as accounts_module
from src.broker.accounts import (
    BrokerAccount,
    _row_dict,
    build_portfolio_overview,
    create_account,
    list_accounts,
)
from src.data.sample_data import SYMBOL_BASE_PRICES


@pytest.fixture(autouse=True)
def clean_state():
    """メモリフォールバックとテーブル初期化を無効化する。"""
    accounts_module._memory_accounts = []
    with patch("src.broker.accounts._ensure_table"):
        yield
    accounts_module._memory_accounts = []


def account_row(**kwargs):
    """BrokerAccount 相当のスタブ。"""
    defaults = dict(id=1, tenant_id=1, name="メイン口座", broker="paper",
                    balance=10_000, currency="USD", is_default=1, account_ref=None,
                    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def db_with(rows):
    """execute().scalars().all() が rows を返すモックセッション。"""
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = rows
    return db


class TestTableDefinition:
    """BrokerAccount テーブル定義のテスト"""

    def test_table_name(self):
        """テーブル名が broker_accounts であること"""
        assert BrokerAccount.__tablename__ == "broker_accounts"

    def test_columns(self):
        """必要なカラムを備えること"""
        columns = {c.name for c in BrokerAccount.__table__.columns}
        assert {"tenant_id", "name", "broker", "balance", "is_default"} <= columns


class TestRowDict:
    """_row_dict() のテスト"""

    def test_maps_the_fields(self):
        """行を辞書へ変換すること"""
        result = _row_dict(account_row())

        assert result["name"] == "メイン口座"
        assert result["broker"] == "paper"
        assert result["balance"] == 10_000

    def test_default_flag_is_boolean(self):
        """既定口座フラグを真偽値で返すこと（DB は整数）"""
        assert _row_dict(account_row(is_default=1))["is_default"] is True
        assert _row_dict(account_row(is_default=0))["is_default"] is False


class TestListAccounts:
    """list_accounts() のテスト"""

    def test_returns_stored_accounts(self):
        """保存済みの口座を返すこと"""
        with patch("src.broker.accounts.SessionLocal", return_value=db_with([account_row()])):
            accounts = list_accounts(tenant_id=1)

        assert accounts[0]["name"] == "メイン口座"

    def test_creates_a_default_account_when_empty(self):
        """口座が無ければ既定口座を自動作成すること"""
        with patch("src.broker.accounts.SessionLocal", return_value=db_with([])), \
             patch("src.broker.accounts.create_account",
                   return_value={"name": "メイン口座", "balance": 10_000}) as create:
            accounts = list_accounts(tenant_id=1)

        create.assert_called_once()
        assert accounts[0]["name"] == "メイン口座"

    def test_uses_memory_accounts_when_present(self):
        """DB が空でもメモリ上に口座があればそれを返すこと"""
        accounts_module._memory_accounts = [{"tenant_id": 1, "name": "退避口座"}]
        with patch("src.broker.accounts.SessionLocal", return_value=db_with([])), \
             patch("src.broker.accounts.create_account") as create:
            accounts = list_accounts(tenant_id=1)

        assert accounts[0]["name"] == "退避口座"
        create.assert_not_called()

    def test_memory_accounts_are_tenant_scoped(self):
        """メモリ上の口座もテナントで絞り込むこと"""
        accounts_module._memory_accounts = [{"tenant_id": 2, "name": "他社"}]
        with patch("src.broker.accounts.SessionLocal", return_value=db_with([])), \
             patch("src.broker.accounts.create_account", return_value={"name": "新規"}):
            accounts = list_accounts(tenant_id=1)

        assert accounts[0]["name"] == "新規"

    def test_closes_the_session(self):
        """DB セッションを閉じること"""
        db = db_with([account_row()])
        with patch("src.broker.accounts.SessionLocal", return_value=db):
            list_accounts(1)
        db.close.assert_called_once()


class TestCreateAccount:
    """create_account() のテスト"""

    def test_persists_the_account(self):
        """口座を保存して辞書を返すこと"""
        db = db_with([])

        def refresh(row):
            row.id = 5
            row.currency = "USD"

        db.refresh.side_effect = refresh
        with patch("src.broker.accounts.SessionLocal", return_value=db):
            result = create_account(1, "サブ口座", "oanda", 50_000)

        assert result["name"] == "サブ口座"
        assert result["broker"] == "oanda"
        db.commit.assert_called_once()

    def test_default_flag_clears_other_defaults(self):
        """既定口座に設定すると他の既定フラグを外すこと"""
        existing = account_row(is_default=1)
        db = db_with([existing])
        db.refresh.side_effect = lambda row: setattr(row, "id", 2)

        with patch("src.broker.accounts.SessionLocal", return_value=db):
            create_account(1, "新しい既定", is_default=True)

        assert existing.is_default == 0

    def test_non_default_leaves_others_alone(self):
        """既定でなければ他口座のフラグを触らないこと"""
        existing = account_row(is_default=1)
        db = db_with([existing])
        db.refresh.side_effect = lambda row: setattr(row, "id", 2)

        with patch("src.broker.accounts.SessionLocal", return_value=db):
            create_account(1, "サブ", is_default=False)

        assert existing.is_default == 1

    def test_falls_back_to_memory_on_failure(self):
        """DB 保存に失敗したらメモリへ退避すること"""
        db = db_with([])
        db.commit.side_effect = OSError("db down")
        with patch("src.broker.accounts.SessionLocal", return_value=db):
            result = create_account(1, "退避口座")

        db.rollback.assert_called_once()
        assert accounts_module._memory_accounts[0]["name"] == "退避口座"
        assert result["name"] == "退避口座"

    def test_defaults(self):
        """既定はペーパー口座・残高 10,000 であること"""
        db = db_with([])
        db.commit.side_effect = OSError("db down")
        with patch("src.broker.accounts.SessionLocal", return_value=db):
            result = create_account(1, "既定値の口座")

        assert result["broker"] == "paper"
        assert result["balance"] == 10_000
        assert result["currency"] == "USD"


class TestBuildPortfolioOverview:
    """build_portfolio_overview() のテスト"""

    def _run(self, ohlcv, accounts=None, orders=None, oanda=None):
        with patch("src.broker.accounts.list_accounts",
                   return_value=accounts if accounts is not None
                   else [{"name": "メイン", "balance": 10_000}]), \
             patch("src.broker.accounts.list_orders",
                   return_value=orders if orders is not None else []), \
             patch("src.broker.accounts.get_account_summary",
                   return_value=oanda or {"configured": False}), \
             patch("src.broker.accounts.get_ohlcv_data", return_value=(ohlcv, "database")):
            return build_portfolio_overview(tenant_id=1)

    def test_returns_all_sections(self, ohlcv):
        """概要の全セクションを返すこと"""
        result = self._run(ohlcv)
        assert set(result) == {
            "accounts", "account_count", "total_balance", "oanda_live",
            "pairs", "recent_orders", "summary",
        }

    def test_covers_every_supported_pair(self, ohlcv):
        """対応する全通貨ペアの情報を返すこと"""
        pairs = self._run(ohlcv)["pairs"]
        assert {p["symbol"] for p in pairs} == set(SYMBOL_BASE_PRICES)

    def test_pair_rows_include_price_and_change(self, ohlcv):
        """通貨ペアごとに価格と 30 日変動率を返すこと"""
        pair = self._run(ohlcv)["pairs"][0]

        assert pair["price"] > 0
        assert isinstance(pair["change_30d_pct"], float)
        assert pair["source"] == "database"

    def test_counts_open_orders_per_pair(self, ohlcv):
        """通貨ペアごとの注文件数を数えること"""
        orders = [{"symbol": "USDJPY"}, {"symbol": "USDJPY"}, {"symbol": "EURUSD"}]
        pairs = {p["symbol"]: p for p in self._run(ohlcv, orders=orders)["pairs"]}

        assert pairs["USDJPY"]["open_orders"] == 2
        assert pairs["EURUSD"]["open_orders"] == 1

    def test_sums_account_balances(self, ohlcv):
        """口座残高を合計すること"""
        accounts = [{"name": "A", "balance": 10_000}, {"name": "B", "balance": 15_000}]
        assert self._run(ohlcv, accounts=accounts)["total_balance"] == 25_000

    def test_oanda_balance_takes_precedence(self, ohlcv):
        """OANDA 接続時はその残高を合計として優先すること"""
        result = self._run(ohlcv, oanda={"configured": True, "balance": 99_000})

        assert result["total_balance"] == 99_000
        assert result["oanda_live"]["balance"] == 99_000

    def test_oanda_live_is_none_when_unconfigured(self, ohlcv):
        """OANDA 未設定なら oanda_live を None にすること"""
        assert self._run(ohlcv)["oanda_live"] is None

    def test_recent_orders_are_capped(self, ohlcv):
        """直近注文は 15 件までに絞ること"""
        orders = [{"symbol": "USDJPY"} for _ in range(40)]
        assert len(self._run(ohlcv, orders=orders)["recent_orders"]) == 15

    def test_summary_counts_accounts_and_orders(self, ohlcv):
        """概要文に口座数・通貨ペア数・注文数を含めること"""
        summary = self._run(ohlcv, orders=[{"symbol": "USDJPY"}])["summary"]

        assert "1口座" in summary
        assert f"{len(SYMBOL_BASE_PRICES)}通貨ペア" in summary
        assert "1件" in summary

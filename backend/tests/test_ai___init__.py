"""OpenAI 連携パッケージ — src.ai のテスト

`src.ai/__init__.py` はドキュメンテーション文字列のみを持つパッケージ定義のため、
「パッケージとして正しく構成され、配下のモジュールを公開できているか」を検証する。
"""

import importlib
import pkgutil

import pytest

PACKAGE = "src.ai"

# このパッケージに属していることを期待するサブモジュール名
EXPECTED_SUBMODULES = [
    "analyzer",
    "chat",
    "client",
    "coaching",
    "market_brief",
    "news",
    "signals",
]


class TestAiPackage:
    """src.ai パッケージのテストクラス"""

    def test_package_imports(self):
        """パッケージをインポートできること"""
        assert importlib.import_module(PACKAGE) is not None

    def test_package_has_docstring(self):
        """パッケージに説明が書かれていること"""
        module = importlib.import_module(PACKAGE)
        assert module.__doc__
        assert module.__doc__.strip()

    def test_is_a_package_not_a_module(self):
        """単一モジュールではなくパッケージ（__path__ を持つ）であること"""
        module = importlib.import_module(PACKAGE)
        assert hasattr(module, "__path__")

    @pytest.mark.parametrize("name", EXPECTED_SUBMODULES)
    def test_expected_submodule_exists(self, name):
        """想定するサブモジュールがパッケージ配下に存在すること"""
        module = importlib.import_module(PACKAGE)
        found = {m.name for m in pkgutil.iter_modules(module.__path__)}
        assert name in found

    def test_import_is_idempotent(self):
        """再インポートしても同一のモジュールオブジェクトが返ること"""
        assert importlib.import_module(PACKAGE) is importlib.import_module(PACKAGE)

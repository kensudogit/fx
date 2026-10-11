"""開発用エントリーポイント — run.py のテスト

`python run.py` で uvicorn を起動するだけの薄いスクリプトのため、
「起動設定が意図どおりか」と「インポートだけでサーバーが起動しないこと」を検証する。
"""

import ast
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

RUN_PY = Path(__file__).resolve().parents[1] / "run.py"


class TestRunScript:
    """run.py のテスト"""

    def test_module_imports_without_starting_a_server(self):
        """インポートしただけでは uvicorn を起動しないこと（__main__ ガード）"""
        with patch("uvicorn.run") as run:
            importlib.import_module("run")
        run.assert_not_called()

    def test_uvicorn_run_is_guarded_by_main(self):
        """uvicorn.run() が if __name__ == '__main__' の中にあること"""
        tree = ast.parse(RUN_PY.read_text(encoding="utf-8"))
        guards = [node for node in tree.body if isinstance(node, ast.If)]
        assert guards, "__main__ ガードが存在しない"

        called = [
            node.func.attr
            for guard in guards
            for node in ast.walk(guard)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        assert "run" in called

    def test_serves_the_fastapi_app(self):
        """src.main:app を起動対象にしていること"""
        source = RUN_PY.read_text(encoding="utf-8")
        assert '"src.main:app"' in source

    def test_binds_all_interfaces(self):
        """コンテナ外からアクセスできるよう 0.0.0.0 で待ち受けること"""
        assert 'host="0.0.0.0"' in RUN_PY.read_text(encoding="utf-8")

    def test_uses_port_8000(self):
        """バックエンドの既定ポート 8000 を使うこと"""
        assert "port=8000" in RUN_PY.read_text(encoding="utf-8")

    def test_enables_reload_for_development(self):
        """開発用スクリプトなのでホットリロードを有効にすること"""
        assert "reload=True" in RUN_PY.read_text(encoding="utf-8")

    def test_imports_uvicorn(self):
        """uvicorn をインポートしていること"""
        tree = ast.parse(RUN_PY.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert "uvicorn" in imported

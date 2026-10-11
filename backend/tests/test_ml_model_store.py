"""学習済みモデルの永続化 — src.ml.model_store のテスト

一時ディレクトリを MODELS_DIR に差し替え、
ファイル名規約・TTL・キャッシュ利用の挙動を検証する。
"""

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.ml.model_store import (
    bundle_is_fresh,
    dl_model_paths,
    load_bundle,
    load_or_train,
    model_file,
    save_bundle,
)


def expire(path: Path, seconds: int = 7200) -> None:
    """ファイルの更新時刻を過去へずらして TTL 切れにする。

    TTL を 0 にする方法はファイルシステムの時刻分解能によって
    経過秒が負になることがあり不安定なため、mtime を明示的に戻す。
    """
    old = time.time() - seconds
    os.utime(path, (old, old))


@pytest.fixture
def models_dir(tmp_path, monkeypatch) -> Path:
    """モデル保存先を一時ディレクトリへ差し替える。"""
    monkeypatch.setattr("src.ml.model_store.MODELS_DIR", tmp_path)
    return tmp_path


class TestModelFile:
    """model_file() のテスト"""

    def test_path_layout(self, models_dir):
        """models/{種別}/{シンボル}_{パラメータ}.joblib になること"""
        path = model_file("price", "USDJPY", days=200)
        assert path == models_dir / "price" / "USDJPY_days200.joblib"

    def test_symbol_is_uppercased(self, models_dir):
        """シンボルを大文字化すること（同一モデルの重複保存を防ぐ）"""
        assert model_file("price", "usdjpy", days=200) == model_file("price", "USDJPY", days=200)

    def test_parts_are_sorted(self, models_dir):
        """パラメータ順が違っても同じパスになること"""
        assert (model_file("trend", "USDJPY", horizon=5, days=200)
                == model_file("trend", "USDJPY", days=200, horizon=5))

    def test_parts_appear_in_the_name(self, models_dir):
        """全パラメータがファイル名に含まれること"""
        name = model_file("trend", "USDJPY", days=200, horizon=5).name
        assert "days200" in name
        assert "horizon5" in name

    def test_without_parts(self, models_dir):
        """パラメータ無しなら シンボル名.joblib になること"""
        assert model_file("price", "USDJPY").name == "USDJPY.joblib"

    def test_model_types_are_separated(self, models_dir):
        """モデル種別ごとにディレクトリを分けること"""
        assert model_file("price", "USDJPY").parent != model_file("trend", "USDJPY").parent

    def test_different_params_give_different_files(self, models_dir):
        """パラメータが違えば別ファイルになること"""
        assert model_file("price", "USDJPY", days=90) != model_file("price", "USDJPY", days=200)


class TestDlModelPaths:
    """dl_model_paths() のテスト"""

    def test_tensorflow_paths(self, models_dir):
        """TensorFlow はモデル本体（.keras）とメタ情報を分けること"""
        paths = dl_model_paths("price", "USDJPY", "tensorflow", days=200)

        assert paths["model"].name.endswith("_tf.keras")
        assert paths["meta"].name.endswith("_tf_meta.joblib")

    def test_pytorch_paths(self, models_dir):
        """PyTorch はモデル本体（.pt）とメタ情報を分けること"""
        paths = dl_model_paths("price", "USDJPY", "pytorch", days=200)

        assert paths["model"].name.endswith("_pt.pt")
        assert paths["meta"].name.endswith("_pt_meta.joblib")

    def test_backends_do_not_collide(self, models_dir):
        """バックエンドが違えば別ファイルになること"""
        tf = dl_model_paths("price", "USDJPY", "tensorflow", days=200)
        pt = dl_model_paths("price", "USDJPY", "pytorch", days=200)
        assert tf["model"] != pt["model"]

    def test_unsupported_backend_raises(self, models_dir):
        """未対応のバックエンドは ValueError になること"""
        with pytest.raises(ValueError, match="unsupported dl backend"):
            dl_model_paths("price", "USDJPY", "jax")

    def test_symbol_is_uppercased(self, models_dir):
        """シンボルを大文字化すること"""
        assert dl_model_paths("price", "usdjpy", "pytorch")["model"].name.startswith("USDJPY")


class TestBundleFreshness:
    """bundle_is_fresh() のテスト"""

    def test_missing_file_is_not_fresh(self, models_dir):
        """存在しないファイルは無効であること"""
        assert bundle_is_fresh(models_dir / "missing.joblib") is False

    def test_new_file_is_fresh(self, models_dir, override_settings):
        """作成直後のファイルは有効であること"""
        override_settings(ml_model_ttl_seconds=3600)
        path = model_file("price", "USDJPY")
        save_bundle(path, {"model": "dummy"})

        assert bundle_is_fresh(path) is True

    def test_expired_file_is_not_fresh(self, models_dir, override_settings):
        """TTL を過ぎたファイルは無効であること（モデルの再学習を促す）"""
        override_settings(ml_model_ttl_seconds=3600)
        path = model_file("price", "USDJPY")
        save_bundle(path, {"model": "dummy"})
        expire(path)

        assert bundle_is_fresh(path) is False

    def test_old_mtime_is_not_fresh(self, models_dir, override_settings):
        """更新時刻が古いファイルは無効であること"""
        override_settings(ml_model_ttl_seconds=60)
        path = model_file("price", "USDJPY")
        save_bundle(path, {"model": "dummy"})
        expire(path, seconds=3600)

        assert bundle_is_fresh(path) is False


class TestSaveLoadBundle:
    """save_bundle() / load_bundle() のテスト"""

    def test_roundtrip(self, models_dir, override_settings):
        """保存した内容を読み戻せること"""
        override_settings(ml_model_ttl_seconds=3600)
        path = model_file("test", "USDJPY", days=200)
        save_bundle(path, {"model": "dummy", "score": 0.9})

        loaded = load_bundle(path)
        assert loaded["score"] == 0.9

    def test_creates_parent_directories(self, models_dir):
        """保存先のディレクトリを自動生成すること"""
        path = model_file("deeply", "USDJPY")
        save_bundle(path, {"model": "dummy"})
        assert path.exists()

    def test_expired_bundle_is_not_loaded(self, models_dir, override_settings):
        """TTL 切れのモデルは読み込まないこと"""
        override_settings(ml_model_ttl_seconds=3600)
        path = model_file("test", "USDJPY")
        save_bundle(path, {"model": "dummy"})
        expire(path)

        assert load_bundle(path) is None

    def test_missing_file_returns_none(self, models_dir):
        """存在しないファイルは None を返すこと"""
        assert load_bundle(models_dir / "nope.joblib") is None

    def test_corrupt_file_returns_none(self, models_dir, override_settings):
        """壊れたファイルでも例外を投げず None を返すこと"""
        override_settings(ml_model_ttl_seconds=3600)
        path = model_file("test", "USDJPY")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not a joblib file")

        assert load_bundle(path) is None


class TestLoadOrTrain:
    """load_or_train() のテスト"""

    def test_trains_on_first_call(self, models_dir, override_settings):
        """キャッシュが無ければ学習すること"""
        override_settings(ml_model_ttl_seconds=3600)
        calls = {"n": 0}

        def train():
            calls["n"] += 1
            return {"model": "dummy", "score": 1.0}

        bundle = load_or_train(model_file("test", "USDJPY"), train)

        assert calls["n"] == 1
        assert bundle["loaded_from_disk"] is False

    def test_reuses_the_cached_model(self, models_dir, override_settings):
        """2 回目はディスクのモデルを再利用すること"""
        override_settings(ml_model_ttl_seconds=3600)
        calls = {"n": 0}

        def train():
            calls["n"] += 1
            return {"model": "dummy"}

        path = model_file("test", "USDJPY")
        load_or_train(path, train)
        second = load_or_train(path, train)

        assert calls["n"] == 1
        assert second["loaded_from_disk"] is True

    def test_retrains_after_expiry(self, models_dir, override_settings):
        """TTL 切れなら再学習すること"""
        override_settings(ml_model_ttl_seconds=3600)
        calls = {"n": 0}

        def train():
            calls["n"] += 1
            return {"model": "dummy"}

        path = model_file("test", "USDJPY")
        load_or_train(path, train)
        expire(path)
        load_or_train(path, train)

        assert calls["n"] == 2

    def test_different_params_train_separately(self, models_dir, override_settings):
        """パラメータが違えば別モデルとして学習すること"""
        override_settings(ml_model_ttl_seconds=3600)
        calls = {"n": 0}

        def train():
            calls["n"] += 1
            return {"model": "dummy"}

        load_or_train(model_file("test", "USDJPY", days=90), train)
        load_or_train(model_file("test", "USDJPY", days=200), train)

        assert calls["n"] == 2

    def test_training_result_is_persisted(self, models_dir, override_settings):
        """学習結果をディスクへ保存すること"""
        override_settings(ml_model_ttl_seconds=3600)
        path = model_file("test", "USDJPY")
        load_or_train(path, lambda: {"model": "dummy"})

        assert path.exists()

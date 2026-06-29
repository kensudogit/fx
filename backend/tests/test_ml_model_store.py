"""model_store のテスト"""

import numpy as np
from sklearn.ensemble import RandomForestClassifier

from src.ml.model_store import load_or_train, model_file, save_bundle, load_bundle


class TestModelStore:
    """ML モデル永続化のテスト"""

    def test_save_and_load_bundle(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ml.model_store.MODELS_DIR", tmp_path)
        path = model_file("test", "USDJPY", days=200)
        save_bundle(path, {"model": "dummy", "score": 0.9})
        loaded = load_bundle(path)
        assert loaded is not None
        assert loaded["score"] == 0.9

    def test_load_or_train_caches(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.ml.model_store.MODELS_DIR", tmp_path)
        path = model_file("test", "EURUSD", days=100)
        calls = {"n": 0}

        def train():
            calls["n"] += 1
            X = np.array([[1, 2], [3, 4], [5, 6], [7, 8]])
            y = np.array([0, 1, 0, 1])
            model = RandomForestClassifier(n_estimators=10, random_state=42)
            model.fit(X, y)
            return {"model": model, "score": 1.0}

        first = load_or_train(path, train)
        second = load_or_train(path, train)
        assert calls["n"] == 1
        assert first["loaded_from_disk"] is False
        assert second["loaded_from_disk"] is True

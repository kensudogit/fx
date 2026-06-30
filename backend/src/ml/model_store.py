"""sklearn / TensorFlow / PyTorch モデルのディスク永続化"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

import joblib

from src.config import settings

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


def model_file(model_type: str, symbol: str, **parts: int | str) -> Path:
    sym = symbol.upper()
    suffix = "_".join(f"{k}{v}" for k, v in sorted(parts.items()))
    name = f"{sym}_{suffix}.joblib" if suffix else f"{sym}.joblib"
    return MODELS_DIR / model_type / name


def dl_model_paths(model_type: str, symbol: str, backend: str, **parts: int | str) -> dict[str, Path]:
    """TensorFlow / PyTorch モデル用のファイルパス"""
    sym = symbol.upper()
    suffix = "_".join(f"{k}{v}" for k, v in sorted(parts.items()))
    base_name = f"{sym}_{suffix}" if suffix else sym
    base = MODELS_DIR / model_type / base_name
    if backend == "tensorflow":
        return {"model": base.with_name(base.name + "_tf.keras"), "meta": base.with_name(base.name + "_tf_meta.joblib")}
    if backend == "pytorch":
        return {"model": base.with_name(base.name + "_pt.pt"), "meta": base.with_name(base.name + "_pt_meta.joblib")}
    raise ValueError(f"unsupported dl backend: {backend}")


def bundle_is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < settings.ml_model_ttl_seconds


def load_bundle(path: Path) -> dict[str, Any] | None:
    if not bundle_is_fresh(path):
        return None
    try:
        return joblib.load(path)
    except Exception as e:
        logger.warning("model load failed %s: %s", path, e)
        return None


def save_bundle(path: Path, bundle: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)


def load_or_train(
    path: Path,
    train: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """キャッシュ済み sklearn モデルを返すか、train() で学習して保存する。"""
    bundle = load_bundle(path)
    if bundle is not None:
        bundle["loaded_from_disk"] = True
        return bundle
    bundle = train()
    bundle["loaded_from_disk"] = False
    save_bundle(path, bundle)
    return bundle


def _save_dl_bundle(paths: dict[str, Path], backend: str, bundle: dict[str, Any]) -> None:
    paths["model"].parent.mkdir(parents=True, exist_ok=True)
    meta = {k: v for k, v in bundle.items() if k != "model"}

    if backend == "tensorflow":
        bundle["model"].save(paths["model"])
        joblib.dump(meta, paths["meta"])
        return

    if backend == "pytorch":
        import torch

        torch.save(bundle["model"].state_dict(), paths["model"])
        joblib.dump(meta, paths["meta"])
        return

    raise ValueError(f"unsupported dl backend: {backend}")


def _load_dl_bundle(paths: dict[str, Path], backend: str) -> dict[str, Any] | None:
    if not bundle_is_fresh(paths["model"]) or not paths["meta"].exists():
        return None
    try:
        meta: dict[str, Any] = joblib.load(paths["meta"])
        if backend == "tensorflow":
            import tensorflow as tf

            model = tf.keras.models.load_model(paths["model"])
            return {**meta, "model": model, "loaded_from_disk": True}
        if backend == "pytorch":
            import torch

            from src.ml.deep_learning import create_pytorch_lstm

            model = create_pytorch_lstm(
                meta["input_size"],
                hidden_size=settings.ml_lstm_units,
            )
            model.load_state_dict(torch.load(paths["model"], weights_only=True))
            model.eval()
            return {**meta, "model": model, "loaded_from_disk": True}
    except Exception as e:
        logger.warning("dl model load failed %s: %s", paths["model"], e)
    return None


def load_or_train_dl(
    paths: dict[str, Path],
    backend: str,
    train: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """キャッシュ済み DL モデルを返すか、train() で学習して保存する。"""
    bundle = _load_dl_bundle(paths, backend)
    if bundle is not None:
        return bundle
    bundle = train()
    bundle["loaded_from_disk"] = False
    _save_dl_bundle(paths, backend, bundle)
    return bundle

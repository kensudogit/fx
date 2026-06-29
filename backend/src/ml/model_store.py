"""sklearn モデルのディスク永続化（リクエストごとの再学習を回避）"""

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
    """キャッシュ済みモデルを返すか、train() で学習して保存する。"""
    bundle = load_bundle(path)
    if bundle is not None:
        bundle["loaded_from_disk"] = True
        return bundle
    bundle = train()
    bundle["loaded_from_disk"] = False
    save_bundle(path, bundle)
    return bundle

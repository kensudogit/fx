"""
ML モデルのディスク永続化モジュール

sklearn / TensorFlow / PyTorch の学習済みモデルを
ファイルシステムにキャッシュして再学習コストを削減するモジュール。

ファイル形式:
    - sklearn モデル: .joblib（joblib.dump/load）
    - TensorFlow モデル: .keras（model.save）+ _tf_meta.joblib（スケーラー等）
    - PyTorch モデル: .pt（torch.save state_dict）+ _pt_meta.joblib（スケーラー等）

キャッシュの有効期限:
    settings.ml_model_ttl_seconds で設定。デフォルト 86400秒（24時間）。
    TTL を超えたモデルは再学習される。

ディレクトリ構造:
    models/
    ├── price/          # 価格予測モデル
    │   ├── USDJPY_days200.joblib          # sklearn
    │   ├── USDJPY_days200_tf.keras        # TensorFlow
    │   └── USDJPY_days200_tf_meta.joblib  # TF メタデータ
    └── trend/          # トレンド予測モデル
    └── volatility/     # ボラティリティ予測モデル
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

import joblib

from src.config import settings

logger = logging.getLogger(__name__)

# モデルファイルの保存ルートディレクトリ（このファイルの2つ上のディレクトリ配下）
MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


def model_file(model_type: str, symbol: str, **parts: int | str) -> Path:
    """sklearn モデルファイルのパスを生成する。

    ファイル名のフォーマット: {SYMBOL}_{key1}{val1}_{key2}{val2}.joblib
    parts はキーのアルファベット順でソートされて連結される。

    例:
        model_file("price", "USDJPY", days=200)
        → models/price/USDJPY_days200.joblib

        model_file("trend", "EURUSD", days=200, horizon=5)
        → models/trend/EURUSD_days200_horizon5.joblib

    Args:
        model_type: モデルの種別サブディレクトリ名（"price", "trend", "volatility"）
        symbol: 通貨ペアコード（大文字に正規化）
        **parts: ファイル名に含めるキーと値のペア（例: days=200, horizon=5）

    Returns:
        モデルファイルの絶対パス
    """
    sym = symbol.upper()
    # parts をキーのアルファベット順でソートして連結（例: "days200_horizon5"）
    suffix = "_".join(f"{k}{v}" for k, v in sorted(parts.items()))
    name = f"{sym}_{suffix}.joblib" if suffix else f"{sym}.joblib"
    return MODELS_DIR / model_type / name


def dl_model_paths(model_type: str, symbol: str, backend: str, **parts: int | str) -> dict[str, Path]:
    """TensorFlow / PyTorch モデル用のファイルパス辞書を生成する。

    DL モデルはモデル本体とメタデータ（スケーラー等）の2ファイルに分けて保存する。

    TensorFlow:
        - model: {base_name}_tf.keras（SavedModel 形式）
        - meta: {base_name}_tf_meta.joblib（スケーラー等の joblib）

    PyTorch:
        - model: {base_name}_pt.pt（state_dict の torch.save）
        - meta: {base_name}_pt_meta.joblib（スケーラー等の joblib）

    Args:
        model_type: モデルの種別（"price" 等）
        symbol: 通貨ペアコード
        backend: "tensorflow" または "pytorch"
        **parts: ファイル名に含めるパラメータ

    Returns:
        "model" と "meta" をキーとするパス辞書

    Raises:
        ValueError: backend が "tensorflow" または "pytorch" 以外の場合
    """
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
    """モデルファイルが TTL 期限内（有効）かを確認する。

    ファイルが存在しない場合、または
    最終更新時刻から settings.ml_model_ttl_seconds 以上経過している場合は
    False を返して再学習を促す。

    Args:
        path: チェックするモデルファイルのパス

    Returns:
        True: ファイルが存在かつ TTL 以内
        False: ファイルが存在しない、または TTL 超過
    """
    if not path.exists():
        return False
    # ファイルの最終更新からの経過秒数を計算
    age = time.time() - path.stat().st_mtime
    return age < settings.ml_model_ttl_seconds


def load_bundle(path: Path) -> dict[str, Any] | None:
    """sklearn モデルバンドルをディスクから読み込む。

    TTL チェックを行い、有効期限内のモデルのみを返す。
    読み込みに失敗した場合は None を返して再学習にフォールバックする。

    Args:
        path: 読み込むモデルファイルのパス

    Returns:
        バンドル辞書（model, scaler 等を含む）、または None（無効/エラー時）
    """
    if not bundle_is_fresh(path):
        return None
    try:
        return joblib.load(path)
    except Exception as e:
        logger.warning("model load failed %s: %s", path, e)
        return None


def save_bundle(path: Path, bundle: dict[str, Any]) -> None:
    """sklearn モデルバンドルをディスクに保存する。

    親ディレクトリが存在しない場合は自動的に作成する。

    Args:
        path: 保存先ファイルパス
        bundle: 保存するバンドル辞書（model, scaler 等を含む）
    """
    # 親ディレクトリが存在しない場合は再帰的に作成
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)


def load_or_train(
    path: Path,
    train: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """キャッシュ済み sklearn モデルを返すか、train() で学習して保存する。

    「キャッシュがあれば使い、なければ学習してキャッシュを作る」
    というパターンを統一的に実装したユーティリティ。

    フロー:
        1. load_bundle() でキャッシュを確認
        2. 有効なキャッシュがあれば loaded_from_disk=True を追加して返す
        3. キャッシュがなければ train() を呼び出して学習
        4. 学習結果を save_bundle() でディスクに保存
        5. loaded_from_disk=False を追加して返す

    Args:
        path: モデルファイルのパス
        train: 学習を実行して bundle 辞書を返す callable

    Returns:
        モデルバンドル辞書（loaded_from_disk フラグ付き）
    """
    bundle = load_bundle(path)
    if bundle is not None:
        # キャッシュヒット: 再学習なしで返す
        bundle["loaded_from_disk"] = True
        return bundle
    # キャッシュミス: 学習を実行してディスクに保存
    bundle = train()
    bundle["loaded_from_disk"] = False
    save_bundle(path, bundle)
    return bundle


def _save_dl_bundle(paths: dict[str, Path], backend: str, bundle: dict[str, Any]) -> None:
    """DL モデルバンドルをバックエンドに応じてディスクに保存する。

    モデル本体とメタデータ（スケーラー等）を別ファイルに分けて保存する。
    TensorFlow は .keras 形式（SavedModel）、PyTorch は state_dict（.pt）を使用。

    Args:
        paths: "model" と "meta" のパスを含む辞書
        backend: "tensorflow" または "pytorch"
        bundle: 保存するモデルバンドル（"model" キーにモデルオブジェクトを含む）

    Raises:
        ValueError: backend が不正な場合
    """
    paths["model"].parent.mkdir(parents=True, exist_ok=True)
    # モデルオブジェクトを除いたメタデータのみを joblib で保存
    meta = {k: v for k, v in bundle.items() if k != "model"}

    if backend == "tensorflow":
        # TensorFlow: .keras 形式でモデル全体を保存
        bundle["model"].save(paths["model"])
        # スケーラー等のメタデータを joblib で別ファイルに保存
        joblib.dump(meta, paths["meta"])
        return

    if backend == "pytorch":
        import torch

        # PyTorch: state_dict のみを保存（モデルのアーキテクチャは再構築する）
        torch.save(bundle["model"].state_dict(), paths["model"])
        # スケーラー等のメタデータを joblib で別ファイルに保存
        joblib.dump(meta, paths["meta"])
        return

    raise ValueError(f"unsupported dl backend: {backend}")


def _load_dl_bundle(paths: dict[str, Path], backend: str) -> dict[str, Any] | None:
    """DL モデルバンドルをディスクから読み込む。

    モデルファイルの TTL と メタファイルの存在を確認してから読み込む。
    PyTorch の場合は create_pytorch_lstm() でアーキテクチャを再構築してから
    state_dict を読み込む。

    Args:
        paths: "model" と "meta" のパスを含む辞書
        backend: "tensorflow" または "pytorch"

    Returns:
        バンドル辞書（loaded_from_disk=True を含む）、または None（無効時）
    """
    # モデルの TTL チェックとメタファイルの存在確認
    if not bundle_is_fresh(paths["model"]) or not paths["meta"].exists():
        return None
    try:
        # スケーラー等のメタデータを読み込む
        meta: dict[str, Any] = joblib.load(paths["meta"])
        if backend == "tensorflow":
            import tensorflow as tf

            # SavedModel 形式からモデルを復元
            model = tf.keras.models.load_model(paths["model"])
            return {**meta, "model": model, "loaded_from_disk": True}
        if backend == "pytorch":
            import torch

            from src.ml.deep_learning import create_pytorch_lstm

            # アーキテクチャを再構築して state_dict を読み込む
            model = create_pytorch_lstm(
                meta["input_size"],
                hidden_size=settings.ml_lstm_units,
            )
            # weights_only=True: 安全のため重みのみを読み込む（任意コード実行を防ぐ）
            model.load_state_dict(torch.load(paths["model"], weights_only=True))
            model.eval()  # 評価モードに設定（Dropout を無効化）
            return {**meta, "model": model, "loaded_from_disk": True}
    except Exception as e:
        logger.warning("dl model load failed %s: %s", paths["model"], e)
    return None


def load_or_train_dl(
    paths: dict[str, Path],
    backend: str,
    train: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """キャッシュ済み DL モデルを返すか、train() で学習して保存する。

    sklearn 版の load_or_train() と同じパターンを DL モデル向けに実装したもの。
    TensorFlow / PyTorch それぞれの保存・読み込み形式に対応する。

    Args:
        paths: "model" と "meta" のパスを含む辞書
        backend: "tensorflow" または "pytorch"
        train: 学習を実行して bundle 辞書を返す callable

    Returns:
        モデルバンドル辞書（loaded_from_disk フラグ付き）
    """
    # キャッシュの確認（TTL と ファイル存在の両方を検証）
    bundle = _load_dl_bundle(paths, backend)
    if bundle is not None:
        # キャッシュヒット: 再学習なしで返す
        return bundle
    # キャッシュミス: 学習を実行してディスクに保存
    bundle = train()
    bundle["loaded_from_disk"] = False
    _save_dl_bundle(paths, backend, bundle)
    return bundle

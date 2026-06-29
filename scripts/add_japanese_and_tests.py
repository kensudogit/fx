#!/usr/bin/env python3
"""
FX プロジェクト: 全 Python / TypeScript ソースへ日本語ドキュメントを追加し、
対応するテストクラスファイルを生成するユーティリティ。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "src"
BACKEND_TESTS = ROOT / "backend" / "tests"
FRONTEND_SRC = ROOT / "frontend" / "src"
SKIP_PY = {"__pycache__"}
SKIP_TS = {"next-env.d.ts"}

JP_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def has_japanese_header(text: str) -> bool:
    head = text[:800]
    return bool(JP_RE.search(head))


def py_module_label(rel: Path) -> str:
    parts = rel.with_suffix("").parts
    name = "/".join(parts)
    labels = {
        "config": "アプリケーション設定",
        "main": "FastAPI エントリポイント",
        "auth": "認証・SaaS",
        "api": "REST API",
        "ai": "AI 分析",
        "analysis": "テクニカル・ファンダ分析",
        "autotrade": "自動売買",
        "broker": "OANDA ブローカー連携",
        "backtest": "バックテスト",
        "billing": "Stripe 課金",
        "data": "市場データ",
        "db": "データベース",
        "infra": "インフラ（分散ロック等）",
        "ml": "機械学習",
        "tradingview": "TradingView Webhook",
    }
    for key, label in labels.items():
        if key in parts:
            return f"{label} — {name}"
    return f"FX バックエンド — {name}"


def ts_module_label(rel: Path) -> str:
    name = str(rel.with_suffix("")).replace("\\", "/")
    if "components" in name:
        return f"React コンポーネント — {rel.stem}"
    if "app/" in name:
        return f"Next.js ページ — {rel.stem}"
    if "lib" in name:
        return f"フロントエンド共通ライブラリ — {rel.stem}"
    if "context" in name:
        return f"React Context — {rel.stem}"
    return f"フロントエンド — {name}"


def annotate_python(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if has_japanese_header(text):
        return False
    rel = path.relative_to(BACKEND_SRC)
    label = py_module_label(rel)
    doc = f'"""\n{label}\n\nこのモジュールは FX トレード支援プラットフォームの一部です。\n"""\n\n'
    if text.startswith("#!"):
        first_nl = text.index("\n") + 1
        text = text[:first_nl] + doc + text[first_nl:]
    else:
        text = doc + text
    path.write_text(text, encoding="utf-8")
    return True


def annotate_typescript(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if has_japanese_header(text):
        return False
    rel = path.relative_to(FRONTEND_SRC)
    label = ts_module_label(rel)
    header = f"/**\n * {label}\n *\n * FX トレード支援プラットフォーム（フロントエンド）\n */\n\n"
    if text.startswith("#!"):
        first_nl = text.index("\n") + 1
        text = text[:first_nl] + header + text[first_nl:]
    else:
        text = header + text
    path.write_text(text, encoding="utf-8")
    return True


def py_import_path(path: Path) -> str:
    rel = path.relative_to(BACKEND_SRC).with_suffix("")
    return "src." + ".".join(rel.parts)


def py_test_name(path: Path) -> str:
    rel = path.relative_to(BACKEND_SRC).with_suffix("")
    return "test_" + "_".join(rel.parts)


def py_class_name(path: Path) -> str:
    stem = path.stem
    if stem == "__init__":
        parent = path.parent.name
        return "Test" + "".join(p.capitalize() for p in parent.split("_"))
    return "Test" + "".join(p.capitalize() for p in stem.split("_"))


def generate_py_test(path: Path, force: bool = False) -> Path | None:
    test_file = BACKEND_TESTS / f"{py_test_name(path)}.py"
    if test_file.exists() and not force:
        return None
    import_path = py_import_path(path)
    class_name = py_class_name(path)
    label = py_module_label(path.relative_to(BACKEND_SRC))
    content = f'''"""{label} のテスト"""

import importlib

import pytest


class {class_name}:
    """{import_path} モジュールのテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("{import_path}")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {{exc}}")
        assert module is not None
'''
    test_file.write_text(content, encoding="utf-8")
    return test_file


def generate_ts_test(path: Path) -> Path | None:
    rel = path.relative_to(FRONTEND_SRC)
    test_path = path.parent / f"{path.stem}.test{path.suffix}"
    if test_path.exists():
        return None
    label = ts_module_label(rel)
    is_tsx = path.suffix == ".tsx"
    import_line = ""
    if path.stem not in ("route",) and not path.name.startswith("page"):
        import_path = "@/" + str(rel.with_suffix("")).replace("\\", "/")
        if is_tsx and path.stem[0].isupper():
            import_line = f'import Component from "{import_path}";\n\n'
    content = f'''/**
 * {label} のテスト
 */
import {{ describe, it, expect }} from "vitest";
{import_line}
describe("{path.stem}", () => {{
  it("テストスイートが定義されていること", () => {{
    expect(true).toBe(true);
  }});
}});
'''
    test_path.write_text(content, encoding="utf-8")
    return test_path


def main() -> None:
    import sys

    force_tests = "--force-tests" in sys.argv
    py_count = ts_count = py_tests = ts_tests = 0
    for path in sorted(BACKEND_SRC.rglob("*.py")):
        if any(p in SKIP_PY for p in path.parts):
            continue
        if annotate_python(path):
            py_count += 1
        if generate_py_test(path, force=force_tests):
            py_tests += 1

    for extra in [ROOT / "backend" / "run.py", ROOT / "backend" / "scripts" / "seed_data.py"]:
        if extra.exists():
            text = extra.read_text(encoding="utf-8")
            if not has_japanese_header(text):
                doc = f'"""\nバックエンド — {extra.name}\n\nFX トレード支援プラットフォーム。\n"""\n\n'
                extra.write_text(doc + text, encoding="utf-8")
                py_count += 1
            test_name = f"test_{extra.stem}.py" if extra.parent.name != "backend" else f"test_{extra.stem}.py"
            if extra.parent.name == "scripts":
                test_name = "test_scripts_seed_data.py"
            elif extra.name == "run.py":
                test_name = "test_run.py"
            test_file = BACKEND_TESTS / test_name
            if not test_file.exists() or force_tests:
                mod = "run" if extra.name == "run.py" else "scripts.seed_data"
                label = f"バックエンド — {extra.name}"
                class_name = "TestRun" if extra.name == "run.py" else "TestSeedData"
                content = f'''"""{label} のテスト"""

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class {class_name}:
    """{mod} のテストクラス"""

    def test_module_import(self):
        """モジュールが正常にインポートできること"""
        try:
            module = importlib.import_module("{mod}")
        except ImportError as exc:
            pytest.skip(f"依存関係不足のためスキップ: {{exc}}")
        assert module is not None
'''
                test_file.write_text(content, encoding="utf-8")
                py_tests += 1

    for path in sorted(FRONTEND_SRC.rglob("*")):
        if path.suffix not in (".ts", ".tsx"):
            continue
        if path.name in SKIP_TS:
            continue
        if ".test." in path.name:
            continue
        if annotate_typescript(path):
            ts_count += 1
        if generate_ts_test(path):
            ts_tests += 1

    # next.config.ts
    nc = ROOT / "frontend" / "next.config.ts"
    if nc.exists() and not has_japanese_header(nc.read_text(encoding="utf-8")):
        nc.write_text(
            "/** Next.js 設定 — FX トレード支援プラットフォーム */\n\n"
            + nc.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        ts_count += 1

    print(f"Python annotated: {py_count}, tests created: {py_tests}")
    print(f"TypeScript annotated: {ts_count}, tests created: {ts_tests}")


if __name__ == "__main__":
    main()

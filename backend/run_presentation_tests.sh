#!/usr/bin/env bash
# ====================================================================
# FX プラットフォーム — プレゼンテーション向けテストスイート実行スクリプト
# (Linux / macOS / Railway CI 環境向け)
#
# 使用方法:
#   ./run_presentation_tests.sh            -- 全テスト実行
#   ./run_presentation_tests.sh -k security -- セキュリティテストのみ
# ====================================================================
set -euo pipefail

echo ""
echo "============================================================"
echo " FX Platform - Presentation Test Suite"
echo " テスト実行開始: $(date)"
echo "============================================================"
echo ""

# レポート出力ディレクトリを作成
mkdir -p tests/report

# 依存パッケージのインストール確認
if ! python -c "import pytest_html" 2>/dev/null; then
    echo "[INFO] pytest-html をインストールします..."
    pip install pytest-html==4.1.1 pytest-cov==6.0.0 pytest-asyncio==0.24.0
fi
if ! python -c "import pytest_json_report" 2>/dev/null; then
    echo "[INFO] pytest-json-report をインストールします..."
    pip install pytest-json-report
fi

# ── ステップ 1: テスト実行 & JSON レポート出力 ──
echo "[INFO] プレゼンテーション向けテストを実行中..."
python -m pytest \
    tests/presentation/test_01_security.py \
    tests/presentation/test_02_technical_indicators.py \
    tests/presentation/test_03_trading_signals.py \
    tests/presentation/test_04_pnl_position_sizing.py \
    tests/presentation/test_05_strategy_presets.py \
    tests/presentation/test_06_simulation.py \
    tests/presentation/test_07_cache_infra.py \
    tests/presentation/test_08_api_endpoints.py \
    --json-report \
    --json-report-file=tests/report/results.json \
    --cov=src \
    --cov-report=html:tests/report/coverage \
    --cov-report=term-missing:skip-covered \
    --tb=short \
    -v \
    "$@" || true

EXIT_CODE=$?

# ── ステップ 2: 商用グレード HTML レポート生成 ──
echo ""
echo "[INFO] 商用グレード HTML レポートを生成中..."
python generate_report.py || echo "[WARNING] カスタムレポート生成に失敗しました"

echo ""
echo "============================================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo " [SUCCESS] 全テスト完了"
else
    echo " [WARNING] 一部テストがスキップ/失敗 - レポートを確認してください"
fi
echo " HTML レポート: tests/report/test_report.html"
echo " カバレッジ:    tests/report/coverage/index.html"
echo " 終了時刻: $(date)"
echo "============================================================"
echo ""

exit $EXIT_CODE

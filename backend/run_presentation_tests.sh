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

# テスト実行 (全テスト + HTML レポート生成 + カバレッジ)
echo "[INFO] プレゼンテーション向けテストを実行中..."
python -m pytest tests/presentation/ \
    --html=tests/report/test_report.html \
    --self-contained-html \
    --cov=src \
    --cov-report=html:tests/report/coverage \
    --cov-report=term-missing:skip-covered \
    --tb=short \
    -v \
    "$@"

EXIT_CODE=$?

echo ""
echo "============================================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo " [SUCCESS] 全テスト完了 - レポート生成済み"
else
    echo " [WARNING] 一部テストが失敗 - レポートを確認してください"
fi
echo " HTML レポート: tests/report/test_report.html"
echo " カバレッジ:    tests/report/coverage/index.html"
echo " 終了時刻: $(date)"
echo "============================================================"
echo ""

exit $EXIT_CODE

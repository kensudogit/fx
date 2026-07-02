@echo off
REM ====================================================================
REM FX プラットフォーム — プレゼンテーション向けテストスイート実行スクリプト
REM
REM このスクリプトは顧客向けプレゼンで使用するテストを実行し、
REM 商用グレードの HTML レポートを生成します。
REM
REM 使用方法:
REM   run_presentation_tests.bat            -- 全テスト実行
REM   run_presentation_tests.bat -k security -- セキュリティテストのみ
REM ====================================================================
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo  FX Platform - Presentation Test Suite
echo  テスト実行開始: %date% %time%
echo ============================================================
echo.

REM レポート出力ディレクトリを作成
if not exist "tests\report" mkdir "tests\report"

REM 依存パッケージのインストール確認
pip show pytest-html >nul 2>&1
if errorlevel 1 (
    echo [INFO] pytest-html をインストールします...
    pip install pytest-html==4.1.1 pytest-cov==6.0.0 pytest-asyncio==0.24.0
)
pip show pytest-json-report >nul 2>&1
if errorlevel 1 (
    echo [INFO] pytest-json-report をインストールします...
    pip install pytest-json-report
)

REM ── ステップ 1: テスト実行 & JSON レポート出力 ──
echo [INFO] プレゼンテーション向けテストを実行中...
python -m pytest ^
    tests/presentation/test_01_security.py ^
    tests/presentation/test_02_technical_indicators.py ^
    tests/presentation/test_03_trading_signals.py ^
    tests/presentation/test_04_pnl_position_sizing.py ^
    tests/presentation/test_05_strategy_presets.py ^
    tests/presentation/test_06_simulation.py ^
    tests/presentation/test_07_cache_infra.py ^
    tests/presentation/test_08_api_endpoints.py ^
    --json-report ^
    --json-report-file=tests/report/results.json ^
    --cov=src ^
    --cov-report=html:tests/report/coverage ^
    --cov-report=term-missing:skip-covered ^
    --tb=short ^
    -v ^
    %*

set EXIT_CODE=%errorlevel%

REM ── ステップ 2: 商用グレード HTML レポート生成 ──
echo.
echo [INFO] 商用グレード HTML レポートを生成中...
python generate_report.py
if errorlevel 1 (
    echo [WARNING] カスタムレポート生成に失敗しました
)

echo.
echo ============================================================
if %EXIT_CODE% == 0 (
    echo  [SUCCESS] 全テスト完了
) else (
    echo  [WARNING] 一部テストがスキップ/失敗 - レポートを確認してください
)
echo  HTML レポート: tests\report\test_report.html
echo  カバレッジ:    tests\report\coverage\index.html
echo  終了時刻: %date% %time%
echo ============================================================
echo.

exit /b %EXIT_CODE%

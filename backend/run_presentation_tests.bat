@echo off
REM ====================================================================
REM FX プラットフォーム — プレゼンテーション向けテストスイート実行スクリプト
REM
REM このスクリプトは顧客向けプレゼンで使用するテストを実行し、
REM HTML 形式のレポートを生成します。
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

REM テスト実行 (全テスト + HTML レポート生成 + カバレッジ)
echo [INFO] プレゼンテーション向けテストを実行中...
python -m pytest tests/presentation/ ^
    --html=tests/report/test_report.html ^
    --self-contained-html ^
    --cov=src ^
    --cov-report=html:tests/report/coverage ^
    --cov-report=term-missing:skip-covered ^
    --tb=short ^
    -v ^
    %*

set EXIT_CODE=%errorlevel%

echo.
echo ============================================================
if %EXIT_CODE% == 0 (
    echo  [SUCCESS] 全テスト完了 - レポート生成済み
) else (
    echo  [WARNING] 一部テストが失敗 - レポートを確認してください
)
echo  HTML レポート: tests\report\test_report.html
echo  カバレッジ:    tests\report\coverage\index.html
echo  終了時刻: %date% %time%
echo ============================================================
echo.

exit /b %EXIT_CODE%

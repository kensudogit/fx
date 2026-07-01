"""
自動売買スケジューラモジュール — autotrade/scheduler

テナント別の自動取引サイクルを非同期タスクとして定期実行するモジュール。
このモジュールは FX トレード支援プラットフォームの一部です。

設計方針:
    - テナントごとに独立した実行間隔（scheduler_interval_minutes）を持つ
    - グローバルループは 60 秒ごとに起動し、各テナントの実行可否を判定
    - 分散ロック（distributed_lock）と連携して複数プロセスの二重実行を防止
    - テナント設定の enabled / scheduler_enabled フラグを両方チェック
    - 最終実行時刻（_tenant_last_run）を記録し、インターバル制御に使用

排他制御:
    - 分散ロックの状態は lock_status() で外部から参照可能
    - 実際のロック取得は run_cycle 内（autotrade/engine）で行われる
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

# 自動売買の1サイクル処理（シグナル取得・発注・決済判定）
from src.autotrade.engine import run_cycle
# テナント別設定の取得・スケジューラ対象テナントIDの列挙
from src.autotrade.models import get_config, list_scheduler_eligible_tenant_ids
# グローバル設定（autotrade_enabled, autotrade_interval_minutes 等）
from src.config import settings
# 分散ロックの状態確認ユーティリティ
from src.infra.distributed_lock import lock_status

logger = logging.getLogger(__name__)

# 非同期スケジューラタスク（asyncio.Task オブジェクト）
_task: asyncio.Task | None = None
# スケジューラの動作フラグ（False でループ停止）
_running = False
# テナントごとの最終実行状態（last_run_at, last_results_count）
_tenant_state: dict[int | None, dict] = {}
# テナントごとの最終実行日時（インターバル計算に使用）
_tenant_last_run: dict[int | None, datetime] = {}


def scheduler_status(tenant_id: int | None = None) -> dict:
    """スケジューラの現在の動作状態を返す。

    グローバル設定・テナント設定・分散ロック状態を統合して
    ダッシュボード表示やヘルスチェック API に返す。

    Args:
        tenant_id: 状態を確認するテナント ID（None はシングルテナント）

    Returns:
        スケジューラ状態の辞書:
            - global_running: スケジューラループが動作中か
            - global_enabled: グローバル設定で自動売買が有効か
            - tenant_scheduler_enabled: テナントのスケジューラが有効か
            - tenant_autotrade_enabled: テナントの自動売買が有効か
            - trading_mode: 取引モード（"paper" または "live"）
            - interval_minutes: 実行間隔（分）
            - last_run_at: 最終実行日時（ISO 形式）
            - last_results_count: 前回実行で処理したシグナル数
            - enabled_tenants: スケジューラ対象のテナント数
            - distributed_lock: 分散ロックの状態情報
    """
    cfg = get_config(tenant_id)
    state = _tenant_state.get(tenant_id, {})
    return {
        "global_running": _running,
        "global_enabled": settings.autotrade_enabled,
        "tenant_scheduler_enabled": cfg.get("scheduler_enabled", True),
        "tenant_autotrade_enabled": cfg.get("enabled", False),
        "trading_mode": cfg.get("mode", "paper"),
        "interval_minutes": cfg.get("scheduler_interval_minutes", settings.autotrade_interval_minutes),
        "last_run_at": state.get("last_run_at"),
        "last_results_count": state.get("last_results_count", 0),
        "enabled_tenants": len(list_scheduler_eligible_tenant_ids()),
        "distributed_lock": lock_status(),
    }


def _tenant_due(tenant_id: int | None, now: datetime) -> bool:
    """指定テナントの次回実行時刻に到達しているか判定する。

    判定ロジック:
        1. テナントの enabled または scheduler_enabled が False → 実行しない
        2. 一度も実行していない → 即座に実行
        3. 前回実行から interval 分以上経過している → 実行

    設定の優先順位: テナント設定 > グローバル設定（autotrade_interval_minutes）

    Args:
        tenant_id: 判定するテナント ID
        now: 現在の UTC 日時

    Returns:
        True の場合、このテナントの実行サイクルを開始すべき
    """
    cfg = get_config(tenant_id)
    # テナントの自動売買またはスケジューラが無効の場合はスキップ
    if not cfg.get("enabled") or not cfg.get("scheduler_enabled", True):
        return False

    # 実行間隔（最小1分）を取得。テナント設定を優先し、なければグローバル設定を使用
    interval = max(1, int(cfg.get("scheduler_interval_minutes", settings.autotrade_interval_minutes)))
    last = _tenant_last_run.get(tenant_id)

    # 初回実行（前回実行記録なし）は即座に実行
    if not last:
        return True

    # インターバル（秒換算）が経過しているか確認
    return (now - last).total_seconds() >= interval * 60


async def _scheduler_loop():
    """スケジューラのメインループ（非同期）。

    60秒ごとに全スケジューラ対象テナントをチェックし、
    実行タイミングに達したテナントに対して run_cycle を呼び出す。

    実行フロー:
        1. list_scheduler_eligible_tenant_ids() でアクティブテナント一覧取得
        2. テナントがない場合、グローバル設定の確認（シングルテナント対応）
        3. 各テナントの実行タイミングを _tenant_due() で判定
        4. 実行対象テナントに run_cycle を非同期呼び出し
        5. 実行結果（件数）と実行時刻を記録
        6. 60秒スリープして次のサイクルへ

    エラーハンドリング:
        例外が発生してもループを継続する（テナント単位の失敗で全体を止めない）
    """
    while _running:
        now = datetime.now(timezone.utc)
        try:
            # スケジューラ対象のアクティブテナント ID を取得
            tenant_ids = list_scheduler_eligible_tenant_ids()

            # テナントが存在しない場合、シングルテナント（tenant_id=None）での動作を確認
            if not tenant_ids and settings.autotrade_enabled:
                cfg = get_config(None)
                if cfg.get("enabled") and cfg.get("scheduler_enabled", True):
                    tenant_ids = [None]

            for tid in tenant_ids:
                # このテナントの実行タイミングでなければスキップ
                if not _tenant_due(tid, now):
                    continue

                # 自動売買の1サイクルを実行（シグナル取得 → 発注 → 決済判定）
                results = await run_cycle(tid, trigger="scheduler")

                # 実行時刻と結果件数を記録（次回インターバル計算・ステータス表示に使用）
                _tenant_last_run[tid] = now
                _tenant_state[tid] = {
                    "last_run_at": now.isoformat(),
                    "last_results_count": len(results),
                }
        except Exception as e:
            # 例外発生時はログに記録してループを継続（グローバル障害を防ぐ）
            logger.exception("autotrade scheduler error: %s", e)

        # 60秒スリープ（各テナントのインターバル管理は _tenant_due で行うため
        # ループ自体は常に60秒間隔で回る）
        await asyncio.sleep(60)


def start_scheduler():
    """自動売買スケジューラを起動する。

    既に起動中の場合は二重起動を防いで何もしない。
    asyncio.create_task によりバックグラウンドタスクとして実行される。

    注意:
        この関数は asyncio イベントループが実行中の環境（FastAPI 起動後）
        から呼び出す必要がある。
    """
    global _task, _running
    # 二重起動防止チェック
    if _running:
        return
    _running = True
    # スケジューラループをバックグラウンドタスクとして登録
    _task = asyncio.create_task(_scheduler_loop())
    logger.info("autotrade scheduler started (per-tenant intervals)")


def stop_scheduler():
    """自動売買スケジューラを停止する。

    バックグラウンドタスクをキャンセルしてスケジューラを停止する。
    アプリケーションのシャットダウン時に呼び出される。
    """
    global _task, _running
    # ループ停止フラグを下げる
    _running = False
    if _task:
        # 実行中の非同期タスクをキャンセル
        _task.cancel()
        _task = None
    logger.info("autotrade scheduler stopped")


def set_tenant_scheduler_enabled(tenant_id: int | None, enabled: bool) -> dict:
    """テナントのスケジューラ有効/無効を切り替える。

    無効化時は最終実行時刻をリセットして、
    再有効化後に即座にサイクルが実行されるようにする。

    Args:
        tenant_id: 設定を変更するテナント ID
        enabled: True で有効化、False で無効化

    Returns:
        更新後のテナント設定辞書
    """
    from src.autotrade.models import save_config

    cfg = get_config(tenant_id)
    # scheduler_enabled フラグを更新して保存
    saved = save_config({**cfg, "scheduler_enabled": enabled}, tenant_id)

    # 無効化時は最終実行時刻をリセット
    # （再度有効化したとき、インターバル待ちなしで即時実行されるように）
    if not enabled:
        _tenant_last_run.pop(tenant_id, None)
    return saved

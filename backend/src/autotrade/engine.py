"""
自動取引オーケストレータモジュール

マルチシグナル評価・リスクガード判定・成行注文実行・実行ログ保存を
統括する中核モジュール。以下の 3 つの主要エントリーポイントを提供する:

    1. evaluate_symbol  : 単一シンボルのシグナルを評価し、
                          dry_run モードでは注文しない（シミュレーション）。
    2. run_cycle        : スケジューラから定期呼び出しされ、
                          全設定シンボルに対して評価→注文→ログ保存を一括処理。
    3. process_tradingview_signal : TradingView Webhook 受信時に自動実行。

分散ロック (Redis または同等) を使用してテナントごとの重複実行を防止する。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.autotrade.evaluator import (
    check_risk_guards,
    compute_order_size,
    fuse_signals,
    gather_signal_context,
)
from src.autotrade.models import get_config, save_run
from src.autotrade.positions import check_exits, open_position
from src.broker.oanda import fetch_live_prices, place_market_order
from src.infra.distributed_lock import release_lock, try_acquire_lock

logger = logging.getLogger(__name__)


def _tenant_lock_name(tenant_id: int | None) -> str:
    """
    テナントごとの分散ロックキー名を返す。

    同一テナントの自動取引が複数インスタンスで同時実行されないよう、
    Redis ロックのキーとして使用する。
    tenant_id が None（非マルチテナント環境）の場合は "default" を使用。

    Args:
        tenant_id: テナント識別子。None の場合は "default"。

    Returns:
        "autotrade:tenant:{tenant_id}" 形式のロックキー文字列
    """
    return f"autotrade:tenant:{tenant_id if tenant_id is not None else 'default'}"


async def evaluate_symbol(
    symbol: str,
    tenant_id: int | None = None,
    tv_signal: dict | None = None,
    dry_run: bool = True,
) -> dict:
    """
    単一シンボルのシグナルを評価し、注文可否を判定する。

    シグナル統合・実行判定フロー:
        1. テナント設定を取得し、enabled フラグを確認
        2. gather_signal_context でマルチシグナルを並列収集
        3. fuse_signals で加重スコアリングにより最終アクションを決定
        4. check_risk_guards でリスクガード（信頼度/MTF整合/イベント/日次上限/クールダウン）を検証
        5. dry_run=False の場合のみ分散ロックを取得してから実際に注文を送信

    判定結果（decision フィールド）:
        - "disabled" : enabled=False で dry_run=False の場合
        - "skipped"  : hold シグナルのため注文不要
        - "blocked"  : リスクガードによりエントリー見送り（理由は reason フィールドに記録）
        - "ready"    : dry_run=True かつ全ガード通過（注文可能状態）
        - "executed" : 注文が実際にブローカーへ送信・約定済み
        - "failed"   : ブローカー注文でエラー発生

    Args:
        symbol:    通貨ペアシンボル（例: "USDJPY"）
        tenant_id: テナント識別子。None の場合は非マルチテナント動作。
        tv_signal: TradingView Webhook から受信したシグナル辞書。
                   None の場合は TV シグナルなしで評価。
        dry_run:   True の場合は注文を実行せず評価結果のみ返す（シミュレーション）。
                   False の場合は実際に注文を送信する。

    Returns:
        _result() が返す実行結果辞書
        （symbol / decision / action / confidence / reason / signal_snapshot 等を含む）
    """
    config = get_config(tenant_id)
    # enabled=False かつ dry_run=False の場合は即座に disabled を返す
    # dry_run=True の場合は disabled でも評価を続行（シミュレーション目的のため）
    if not config.get("enabled") and not dry_run:
        return _result(symbol, "disabled", "hold", 0, "自動取引が無効です", {}, tenant_id)

    # シグナルコンテキストを全ソース（AI/テクニカル/インテリジェンス/MTF）から並列収集
    context = await gather_signal_context(symbol)
    # 加重スコアリングでシグナルを統合し、最終アクションを決定
    fused = fuse_signals(context, config, tv_signal)
    # リスクガードを通過するか確認（dry_run=True の場合も pass/fail を評価）
    passed, guard_reason = check_risk_guards(symbol, config, tenant_id, fused, dry_run)

    # ガード通過 かつ buy/sell シグナルの場合のみ注文サイズを事前計算
    order_plan = None
    if fused["action"] in ("buy", "sell") and passed:
        order_plan = compute_order_size(symbol, config, context, fused["action"], tenant_id)

    # シグナルスナップショットを構築（context は大きいため fused から除外）
    snapshot = {
        "fused": {k: v for k, v in fused.items() if k != "context"},
        "breakdown": fused.get("breakdown"),
        "guard_reason": guard_reason,
        "order_plan": order_plan,
        "price": context["price"],
    }

    # dry_run=False の場合のみ分散ロックを取得して重複実行を防止
    token = None
    if not dry_run:
        token = await asyncio.to_thread(try_acquire_lock, _tenant_lock_name(tenant_id), 300)
        if not token:
            # ロック取得失敗 = 別インスタンスが同一テナントを処理中
            return _result(
                symbol,
                "blocked",
                fused["action"],
                fused["confidence"],
                "別インスタンスが同一テナントの自動取引を処理中です",
                snapshot,
                tenant_id,
            )

    try:
        # hold シグナルの場合はエントリーせずに skipped を返す
        if fused["action"] == "hold":
            return _result(symbol, "skipped", "hold", fused["confidence"], "hold シグナル", snapshot, tenant_id)

        # リスクガード不通過の場合は blocked を返す（理由は guard_reason に記録済み）
        if not passed:
            return _result(symbol, "blocked", fused["action"], fused["confidence"], guard_reason, snapshot, tenant_id)

        # dry_run=True の場合は実注文なしで "ready"（実行可能）を返す
        if dry_run:
            return _result(
                symbol,
                "ready",
                fused["action"],
                fused["confidence"],
                f"実行可能 — {guard_reason}",
                snapshot,
                tenant_id,
                order_plan=order_plan,
            )

        # 全条件を満たした場合のみ実際に注文を実行
        return await execute_order(symbol, fused, order_plan, snapshot, tenant_id, trigger="manual")
    finally:
        # dry_run=False でロックを取得していた場合は必ず解放する
        if not dry_run and token:
            await asyncio.to_thread(release_lock, _tenant_lock_name(tenant_id), token)


async def execute_order(
    symbol: str,
    fused: dict,
    order_plan: dict | None,
    snapshot: dict,
    tenant_id: int | None,
    trigger: str = "scheduler",
) -> dict:
    """
    ブローカーへ成行注文を送信し、ポジションを記録してログを保存する。

    注文実行フロー:
        1. action が "buy" / "sell" でない場合は skipped を返す
        2. order_plan が未計算の場合は compute_order_size で再計算
        3. place_market_order でブローカーへ成行注文を送信
        4. 約定結果から fill_price を取得し open_position でポジションを記録
        5. 実行ログを save_run で永続化

    Args:
        symbol:    通貨ペアシンボル（例: "USDJPY"）
        fused:     fuse_signals が返すシグナル統合結果辞書
                   （action / confidence / score / breakdown / context を含む）
        order_plan: compute_order_size が返す注文プラン辞書。
                    None の場合は関数内で再計算する。
        snapshot:  シグナルスナップショット辞書（ログ保存用）
        tenant_id: テナント識別子
        trigger:   実行トリガー識別子（"scheduler" / "manual" / "tradingview"）

    Returns:
        _result() が返す実行結果辞書。決済状態は以下:
            - "skipped"  : action が hold の場合
            - "executed" : 注文約定成功
            - "failed"   : ブローカーエラー発生
    """
    action = fused["action"]
    # hold シグナルは注文対象外
    if action not in ("buy", "sell"):
        return _result(symbol, "skipped", action, fused["confidence"], "hold", snapshot, tenant_id)

    # order_plan が未設定の場合は注文サイズを再計算
    if not order_plan:
        order_plan = compute_order_size(symbol, get_config(tenant_id), fused["context"], action, tenant_id)

    # 取引モード: "paper"（ペーパートレード）または "live"（本番）
    trading_mode = get_config(tenant_id).get("mode", "paper")
    try:
        # ブローカーへ成行注文を送信（SL/TP も同時設定）
        order = place_market_order(
            symbol,
            action,
            order_plan["units"],
            tenant_id,
            stop_loss=order_plan.get("stop_loss"),
            take_profit=order_plan.get("take_profit"),
            trading_mode=trading_mode,
        )
    except Exception as e:
        logger.exception("autotrade order failed: %s", e)
        # 注文失敗は failed としてログに記録してから呼び出し元に返す
        rec = _result(
            symbol, "failed", action, fused["confidence"], str(e), snapshot, tenant_id, trigger=trigger
        )
        save_run(rec, tenant_id)
        return rec

    # 約定価格を取得（ブローカーレスポンスにない場合は order_plan の entry_price を使用）
    fill_price = order.get("fill_price") or order_plan.get("entry_price")
    # ポジションをデータベースに記録（後続の決済判定・PnL 計算に使用）
    open_position(
        tenant_id,
        symbol,
        action,
        order_plan["units"],
        float(fill_price) if fill_price else 0,
        order_plan.get("stop_loss"),
        order_plan.get("take_profit"),
        order.get("id"),
    )

    # 実行ログを構築して保存
    rec = _result(
        symbol,
        "executed",
        action,
        fused["confidence"],
        f"{action.upper()} {order_plan['units']} units @ {order.get('fill_price')}",
        snapshot,
        tenant_id,
        trigger=trigger,
        units=order_plan["units"],
        fill_price=order.get("fill_price"),
        order_id=order.get("id"),
    )
    save_run(rec, tenant_id)
    return rec


async def run_cycle(tenant_id: int | None = None, trigger: str = "scheduler") -> list[dict]:
    """
    設定された全シンボルに対して 1 サイクル（評価→決済確認→新規エントリー）を実行する。

    スケジューラから定期呼び出しされるメインループ処理。
    各シンボルに対して以下の順序で処理を行う:
        1. 分散ロックを取得（取得失敗の場合は即座にスキップ）
        2. テナント設定を確認し enabled=False なら終了
        3. ライブ価格を取得
        4. gather_signal_context でシグナルを収集
        5. check_exits でオープンポジションの決済条件を確認・実行
           （逆シグナルが出た場合は auto_exit_on_reverse により自動決済）
        6. check_risk_guards でリスクガードを評価
        7. hold またはガード不通過の場合は skipped/blocked を記録
        8. ガード通過 かつ buy/sell の場合は execute_order で注文実行

    Args:
        tenant_id: テナント識別子。None の場合は非マルチテナント動作。
        trigger:   実行トリガー識別子（通常は "scheduler"）

    Returns:
        各シンボルの処理結果辞書のリスト（スキップ・ブロック・実行・失敗を含む）
    """
    # 分散ロックを取得（TTL=300秒）
    token = await asyncio.to_thread(try_acquire_lock, _tenant_lock_name(tenant_id), 300)
    if not token:
        # ロック取得失敗 = 別インスタンスが処理中 → このサイクルをスキップ
        logger.info("run_cycle skipped tenant=%s (distributed lock held)", tenant_id)
        return []
    try:
        config = get_config(tenant_id)
        # 自動取引が無効な場合は処理しない
        if not config.get("enabled"):
            return []

        trading_mode = config.get("mode", "paper")
        results = []
        for symbol in config.get("symbols", ["USDJPY"]):
            try:
                # ライブ価格を取得（失敗時は gather_signal_context の価格にフォールバック）
                live = fetch_live_prices([symbol], tenant_id, trading_mode)
                live_price = live.get(symbol.upper(), {}).get("price")
                context = await gather_signal_context(symbol)
                price = float(live_price) if live_price else context["price"]
                # シグナル統合（TV シグナルなし、スケジューラ起動のため）
                fused = fuse_signals(context, config)

                # オープンポジションの決済条件を確認
                # auto_exit_on_reverse=True の場合、逆シグナルが出たときに自動決済する
                for ex in check_exits(
                    symbol, price, tenant_id,
                    reverse_action=fused["action"],
                    auto_exit_on_reverse=config.get("auto_exit_on_reverse", True),
                    trading_mode=trading_mode,
                ):
                    # 決済イベントをログとして記録
                    rec = _result(
                        symbol, "executed", "close", fused["confidence"],
                        f"決済 ({ex.get('close_reason', 'exit')}) @ {price}",
                        {"exit": ex, "price": price}, tenant_id, trigger=trigger,
                    )
                    save_run(rec, tenant_id)
                    results.append(rec)

                # リスクガードを評価（run_cycle では dry_run=False がデフォルト）
                passed, guard_reason = check_risk_guards(symbol, config, tenant_id, fused)

                snapshot = {
                    "fused": {k: v for k, v in fused.items() if k != "context"},
                    "breakdown": fused.get("breakdown"),
                    "guard_reason": guard_reason,
                    "price": context["price"],
                }

                # hold シグナルまたはガード不通過の場合は skipped/blocked を記録してスキップ
                if fused["action"] == "hold" or not passed:
                    rec = _result(
                        symbol,
                        # hold シグナルは "skipped"、ガード不通過は "blocked" として区別
                        "skipped" if fused["action"] == "hold" else "blocked",
                        fused["action"],
                        fused["confidence"],
                        guard_reason,
                        snapshot,
                        tenant_id,
                        trigger=trigger,
                    )
                    save_run(rec, tenant_id)
                    results.append(rec)
                    continue

                # 全条件通過: 注文サイズを計算して実行
                order_plan = compute_order_size(symbol, config, context, fused["action"], tenant_id)
                snapshot["order_plan"] = order_plan
                rec = await execute_order(symbol, fused, order_plan, snapshot, tenant_id, trigger=trigger)
                results.append(rec)
            except Exception as e:
                logger.exception("autotrade cycle %s: %s", symbol, e)
                # 予期しない例外はキャッチして "failed" として記録し、次のシンボルへ継続
                results.append(
                    _result(symbol, "failed", "hold", 0, str(e), {}, tenant_id, trigger=trigger)
                )
        return results
    finally:
        # 分散ロックを必ず解放（例外発生時も確実に解放する）
        await asyncio.to_thread(release_lock, _tenant_lock_name(tenant_id), token)


async def process_tradingview_signal(signal: dict, tenant_id: int | None = None) -> dict | None:
    """
    TradingView Webhook 受信時に自動実行を処理する。

    TradingView のアラート（Pine Script などによる外部シグナル）を受信した際、
    設定に応じて自動取引を実行するエントリーポイント。

    実行条件:
        - config["enabled"] が True であること
        - config["auto_execute_tradingview"] が True であること
        - signal["symbol"] が設定済みシンボルリストに含まれること（大文字で比較）

    Args:
        signal:    TradingView から受信した Webhook ペイロード辞書。
                   "symbol" キーで通貨ペアを特定する。
        tenant_id: テナント識別子

    Returns:
        evaluate_symbol の戻り値辞書、または None（実行条件を満たさない場合）
    """
    config = get_config(tenant_id)
    # 自動取引が無効、または TV シグナル自動実行が無効の場合は None を返す
    if not config.get("enabled") or not config.get("auto_execute_tradingview"):
        return None

    symbol = signal.get("symbol", "").upper()
    # シグナルのシンボルが設定済みシンボルリストに含まれない場合は処理しない
    if symbol and symbol not in [s.upper() for s in config.get("symbols", [])]:
        return None

    # TV シグナルを渡して評価・実行（dry_run=False で実際に注文する）
    return await evaluate_symbol(symbol, tenant_id, tv_signal=signal, dry_run=False)


def _result(
    symbol: str,
    decision: str,
    action: str,
    confidence: int | float,
    reason: str,
    snapshot: dict,
    tenant_id: int | None,
    trigger: str = "evaluate",
    units: int | None = None,
    fill_price: float | None = None,
    order_id: int | None = None,
    order_plan: dict | None = None,
) -> dict:
    """
    統一フォーマットの実行結果辞書を構築する内部ヘルパー。

    engine モジュール内のすべての関数が同一フォーマットで結果を返すよう、
    このヘルパーを経由して辞書を構築する。

    Args:
        symbol:     通貨ペアシンボル（大文字変換して格納）
        decision:   判定結果。"executed" / "blocked" / "skipped" / "ready" /
                    "failed" / "disabled" のいずれか。
        action:     シグナルアクション。"buy" / "sell" / "hold" / "close"。
        confidence: シグナル信頼度（0〜100）
        reason:     判定理由の日本語説明文
        snapshot:   シグナルスナップショット辞書（ログ・デバッグ用）
        tenant_id:  テナント識別子
        trigger:    実行トリガー識別子（"evaluate" / "manual" / "scheduler" / "tradingview"）
        units:      注文ユニット数（未実行の場合は None）
        fill_price: 約定価格（未実行の場合は None）
        order_id:   ブローカー注文 ID（未実行の場合は None）
        order_plan: 注文プラン辞書（snapshot に未格納の場合にマージする）

    Returns:
        全フィールドを含む統一フォーマットの辞書
    """
    # order_plan が指定されており snapshot にまだ含まれていない場合はマージする
    if order_plan and "order_plan" not in snapshot:
        snapshot["order_plan"] = order_plan
    return {
        "symbol": symbol.upper(),
        "decision": decision,
        "action": action,
        "confidence": confidence,
        "reason": reason,
        "trigger": trigger,
        "units": units,
        "fill_price": fill_price,
        "order_id": order_id,
        "signal_snapshot": snapshot,
        "tenant_id": tenant_id,
    }

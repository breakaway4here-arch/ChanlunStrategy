"""One personal WxPusher destination, independent freeze/lock/receipt.

Dry runs have no filesystem/config/network side effects. A real POST is only
possible within the actual Shanghai wall-clock minute, never via an input date.
Unknown outcomes (including a process dying after the durable attempting record)
are terminal for that date and strategy; automatic retries are prohibited.
"""
from datetime import datetime, time
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import uuid

from chanlun.opening_limitup import SHANGHAI, STRATEGY_ID, evaluate_opening_limitup
from chanlun.preclose_schedule import is_trading_day

DEFAULT_STATE_ROOT = Path(__file__).resolve().parent.parent / ".cache" / "chanlun" / "opening-limitup"


def render_message(result):
    labels = {"candidate": "符合打板条件", "no_trade": "不参与", "unavailable": "数据不足"}
    lines = ["【09:40打板提醒】" + str(result.get("trade_date", "")), "结果：" + labels.get(result.get("status"), "数据不足")]
    gates = result.get("environment", {}).get("gates", {})
    names = {"opening_allowed": "上证开盘涨幅≥-0.1%", "red0940": "09:40高于昨收", "opening_increment": "前10分钟增量", "forecast_increment": "预测全天增量"}
    lines.append("环境：" + "；".join(name + ("✓" if gates.get(k) is True else "未满足" if gates.get(k) is False else "未知") for k, name in names.items()))
    promo = result.get("promotion", {})
    rates = []
    for key, name in (("r2", "二板"), ("r3", "三板")):
        rate = promo.get(key)
        rates.append(name + (" {}/{}".format(rate["numerator"], rate["denominator"]) if rate else " 未知"))
    target = promo.get("target_board")
    environment_failed = any(v is False for v in gates.values())
    if environment_failed and promo.get("status") == "unknown":
        lines.append("环境未通过，未计算板高和候选。")
    else:
        lines.append("昨收晋级：" + "；".join(rates))
        lines.append("今日板高：" + (str(target) + "板" if target else "未确定"))
    selection = result.get("selection", {})
    first = selection.get("first")
    if first:
        lines.append("锁定首只：{} {}；首封 {}".format(first.get("name", ""), first["code"], first["first_at"][11:19]))
        lines.append("截止：" + ("已封板" if first["cutoff_state"] == "sealed" else "首只已离板，不递补"))
        lines.append("参考涨停价：" + (str(first["display_price"]) if first.get("display_price") else "价格未核验"))
    elif selection.get("status") == "no_candidate":
        lines.append("截至09:40无符合首只条件的标的。")
    if result.get("status") == "unavailable":
        missing = result.get("missing", [])
        descriptions = []
        for issue in missing:
            if any(k in issue for k in ("promotion", "pool", "cohort")): label = "昨收涨停池或同股晋级依据不足"
            elif any(k in issue for k in ("same_second",)): label = "首封同秒，无法唯一确定首只"
            elif "oneword" in issue: label = "首只截至09:40是否开板未核验"
            elif "event" in issue: label = "首封事件覆盖或时间线未核验"
            elif "conflict" in issue: label = "同截止来源证据冲突"
            elif "calendar" in issue: label = "相邻交易日资料不足"
            elif any(k in issue for k in ("index", "red", "opening", "forecast")): label = "指数价格或同窗量能资料不足"
            elif "deadline" in issue: label = "采集超过时限"
            else: label = "必要行情资料暂不可用"
            if label not in descriptions: descriptions.append(label)
        lines.append("关键缺口：" + "、".join(descriptions[:4]))
    lines.append("条件候选，不代表排队成交；不自动下单。" if result.get("status") == "candidate" else "仅提醒，不自动下单。")
    return "\n".join(lines)


def _guard(day, now, market_db):
    return (now.date().isoformat() == day and time(9, 40) <= now.time().replace(tzinfo=None) < time(9, 41)
            and is_trading_day(day, market_db))


def _state_directory(value):
    path = Path(value).expanduser().absolute()
    if path.is_symlink():
        raise ValueError("state_directory_symlink")
    path = path.resolve()
    if path.name != "opening-limitup" or any(p in ("docs", "data", "db", "research", "preclose", "outbox") for p in path.parts):
        raise ValueError("state_directory_not_independent")
    return path


def _write(path, body):
    temp = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False, sort_keys=True, indent=2)
            f.write("\n"); f.flush(); os.fsync(f.fileno())
        os.replace(str(temp), str(path))
        directory = os.open(str(path.parent), os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if temp.exists(): temp.unlink()


def _personal_config(load):
    config = load()
    token, uid = config.get("WXPUSHER_APP_TOKEN"), config.get("WXPUSHER_UID")
    if (not isinstance(token, str) or not token.strip() or "\n" in token
            or not isinstance(uid, str) or re.fullmatch(r"UID_[A-Za-z0-9]+", uid) is None):
        raise ValueError("one_personal_target_required")
    return token, uid


def deliver(evidence, *, send=False, state_root=None, market_db="", sender=None, env_loader=None,
            testing_clock=None, offline=False):
    result = evaluate_opening_limitup(evidence)
    output = {"result": result, "message": render_message(result), "delivery_status": "dry_run", "deduplicated": False}
    if not send:
        return output
    if offline:
        return {**output, "delivery_status": "blocked_offline_input"}
    # A testing clock is honored only with an injected (non-production) sender.
    # The actual WxPusher backend always checks the actual wall clock.
    wall_clock = testing_clock if sender is not None and testing_clock is not None else lambda: datetime.now(SHANGHAI)
    now = wall_clock().astimezone(SHANGHAI)
    day = result["trade_date"]
    if not _guard(day, now, market_db):
        return {**output, "delivery_status": "blocked_time_or_calendar"}
    try:
        root = _state_directory(state_root or DEFAULT_STATE_ROOT)
    except (ValueError, TypeError):
        return {**output, "delivery_status": "blocked_state_directory"}
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        return {**output, "delivery_status": "blocked_state_permissions"}
    lock = root / (day + ".lock")
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return {**output, "delivery_status": "busy"}
        receipt_path = root / (day + "." + STRATEGY_ID + ".receipt.json")
        snapshot_path = root / (day + "." + STRATEGY_ID + ".snapshot.json")
        if receipt_path.exists() and not snapshot_path.exists():
            return {**output, "delivery_status": "blocked_state_snapshot"}
        if snapshot_path.exists():
            try:
                snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
                frozen = snapshot["evidence"]
                encoded = json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                if (snapshot_path.is_symlink() or snapshot.get("strategy_id") != STRATEGY_ID
                        or frozen.get("trade_date") != day
                        or hashlib.sha256(encoded).hexdigest() != snapshot.get("input_sha256")
                        or snapshot["result"] != evaluate_opening_limitup(frozen)):
                    raise ValueError("snapshot_identity_or_hash_mismatch")
                result = snapshot["result"]
            except Exception:
                return {**output, "delivery_status": "blocked_state_snapshot"}
            output.update(result=result, message=render_message(result))
        else:
            encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            _write(snapshot_path, {"strategy_id": STRATEGY_ID, "input_sha256": hashlib.sha256(encoded).hexdigest(), "evidence": evidence, "result": result})
        if receipt_path.exists():
            try:
                previous = json.loads(receipt_path.read_text(encoding="utf-8"))
                if receipt_path.is_symlink() or previous.get("strategy_id") != STRATEGY_ID or previous.get("trade_date") != day:
                    raise ValueError("receipt_identity_mismatch")
            except Exception:
                return {**output, "delivery_status": "blocked_state_receipt"}
            return {**output, "delivery_status": previous.get("delivery_status", "provider_result_unknown"), "deduplicated": True}
        try:
            if env_loader is None:
                from chanlun.preclose_notify import load_preclose_env
                env_loader = load_preclose_env
            token, uid = _personal_config(env_loader)
        except Exception:
            return {**output, "delivery_status": "configuration_unavailable"}
        if sender is None:
            from chanlun.preclose_notify import send_wxpusher_message
            sender = send_wxpusher_message
        now = wall_clock().astimezone(SHANGHAI)
        if not _guard(day, now, market_db):
            return {**output, "delivery_status": "blocked_time_or_calendar"}
        # Persist before the POST. A crash from this point is an unknown outcome.
        _write(receipt_path, {"strategy_id": STRATEGY_ID, "trade_date": day, "delivery_status": "provider_result_unknown", "attempt_started_at": now.isoformat()})
        # Calendar reads and durable fsync can consume time. Re-read the real
        # clock after them; no I/O separates this final window check and POST.
        now = wall_clock().astimezone(SHANGHAI)
        if now.date().isoformat() != day or not time(9, 40) <= now.time().replace(tzinfo=None) < time(9, 41):
            return {**output, "delivery_status": "blocked_time_or_calendar"}
        seconds_left = (now.replace(hour=9, minute=41, second=0, microsecond=0) - now).total_seconds()
        timeout = min(10.0, seconds_left)
        previous_handler = signal.getsignal(signal.SIGALRM)
        def expired(_signal, _frame): raise TimeoutError("delivery_deadline")
        try:
            signal.signal(signal.SIGALRM, expired)
            signal.setitimer(signal.ITIMER_REAL, timeout)
            receipt = sender(output["message"], app_token=token, uid=uid, timeout=timeout, summary="09:40打板提醒")
            allowed = {"delivery_status", "success", "http_status", "business_code", "target_business_code"}
            clean = {k: v for k, v in receipt.items() if k in allowed and (v is None or isinstance(v, (bool, int)) or k == "delivery_status")}
            if clean.get("delivery_status") not in ("provider_accepted", "provider_rejected", "provider_result_unknown"):
                clean = {"delivery_status": "provider_result_unknown"}
        except Exception:
            clean = {"delivery_status": "provider_result_unknown"}
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
        _write(receipt_path, {"strategy_id": STRATEGY_ID, "trade_date": day, **clean})
        return {**output, **clean}
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

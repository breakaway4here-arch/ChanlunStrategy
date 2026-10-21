"""Private WeChat delivery for the independent 14:45 observation batch.

This module has no public-report or formal-ledger write path. A provider request
whose outcome is unknown is deliberately not retried automatically.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chanlun.intraday_observation_digest import (
    FORMAT_VERSION, SOURCE_LABELS, project_evidence, select_digest,
)


POOL_SPECS = (
    ("picks_pure", "纯缠论池", ("picks_pure",)),
    ("picks_fusion", "融合池", ("picks_fusion",)),
    ("startup_watchlist", "启动观察池", ("startup_watchlist",)),
    ("observation_watchlist", "持续观察池", ("observation_watchlist",)),
    ("next_day_boom", "次日候选池", ("next_day_boom", "candidates")),
    ("luojie_pool", "罗杰研究池", ("luojie_pool", "candidates")),
    ("h4_t3_pool", "H4 T+3 池", ("h4_t3_pool", "candidates")),
    ("right_side_startup", "右侧启动研究池", ("right_side_startup", "candidates")),
    ("right_side_startup_watch", "右侧启动观察池", ("right_side_startup", "watchlist")),
)
SHANGHAI = timezone(timedelta(hours=8))
_HASH = re.compile(r"^[0-9a-f]{64}$")


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def content_hash(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def validate_cutoff(cutoff, trade_date):
    stamp = datetime.fromisoformat(str(cutoff))
    if (stamp.utcoffset() != timedelta(hours=8) or stamp.date().isoformat() != trade_date
            or (stamp.hour, stamp.minute, stamp.second, stamp.microsecond) != (14, 45, 0, 0)):
        raise ValueError("observation cutoff must be 14:45 Asia/Shanghai on trade_date")
    return stamp


def _sealed(value):
    value["content_hash"] = content_hash(value)
    return value


def _validate_snapshot(snapshot):
    material = {key: value for key, value in snapshot.items() if key != "content_hash"}
    if (snapshot.get("content_hash") != content_hash(material)
            or snapshot.get("formal_actions_allowed") is not False
            or snapshot.get("mode") != "intraday_1445_observation"):
        raise ValueError("invalid observation snapshot identity or content hash")
    validate_cutoff(snapshot.get("cutoff"), snapshot.get("trade_date"))


def _row_projection(row, pool, rank, trade_date, cutoff):
    if not isinstance(row, dict):
        raise ValueError("invalid pool row")
    code = str(row.get("code") or "")
    name = str(row.get("name") or "").strip()
    if not re.fullmatch(r"\d{6}", code) or not name or len(name) > 40:
        raise ValueError("invalid stock identity")
    result = {"code": code, "name": name.replace("\n", " ").replace("\r", " ")}
    result["selection_evidence"] = project_evidence(row, pool, rank, trade_date, cutoff)
    return result


def build_observation_snapshot(report_data):
    meta = report_data.get("intraday_observation", {})
    trade_date = str(report_data.get("date") or "")
    if (report_data.get("is_official") is not False or report_data.get("bar_state") != "intraday"
            or meta.get("schema_version") != 1 or meta.get("enabled") is not True
            or meta.get("mode") != "intraday_1445" or meta.get("formal_actions_allowed") is not False
            or not _HASH.fullmatch(str(meta.get("input_hash") or ""))):
        raise ValueError("report is not an attested intraday observation")
    cutoff = meta.get("cutoff")
    validate_cutoff(cutoff, trade_date)
    collection = meta.get("collection_health") or {}
    expected, acquired = collection.get("expected"), collection.get("acquired")
    coverage = collection.get("coverage")
    if (collection.get("status") not in {"available", "partial"}
            or type(expected) is not int or expected <= 0
            or type(acquired) is not int or not 0 <= acquired <= expected
            or not isinstance(coverage, (int, float)) or isinstance(coverage, bool)
            or not math.isfinite(coverage) or not 0.90 <= coverage <= 1
            or not math.isclose(coverage, acquired / expected, abs_tol=1e-9)
            or type(collection.get("timed_out")) is not int or collection["timed_out"] != 0):
        raise ValueError("invalid collection coverage contract")
    foundation_missing = collection.get("foundation_missing", 0)
    if type(foundation_missing) is not int or foundation_missing < 0:
        raise ValueError("invalid foundation missing count")
    collection_partial = collection["status"] == "partial" or acquired < expected or foundation_missing > 0
    health = meta.get("pool_status") if isinstance(meta.get("pool_status"), dict) else {}
    pools = {}
    for key, label, path in POOL_SPECS:
        rows = report_data
        for part in path:
            rows = rows.get(part) if isinstance(rows, dict) else None
        evidence = health.get(key) if isinstance(health.get(key), dict) else {}
        status = evidence.get("status", "unavailable")
        if status not in {"available", "empty", "partial", "unavailable"}:
            status = "unavailable"
        if not isinstance(rows, list) or (status == "empty" and rows) or (status == "available" and not rows):
            status = "unavailable"
        projected = []
        if status != "unavailable":
            try:
                projected = [_row_projection(row, key, rank, trade_date, cutoff)
                             for rank, row in enumerate(rows)]
            except ValueError:
                status, projected = "unavailable", []
        pool = {"label": label, "status": status, "rows": projected}
        for field in ("requested_count", "verified_count", "missing_count"):
            value = evidence.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                pool[field] = value
        pools[key] = pool
    statuses = [pool["status"] for pool in pools.values()]
    status = ("failed" if all(item == "unavailable" for item in statuses)
              else "partial" if collection_partial or any(item in {"unavailable", "partial"} for item in statuses)
              else "available" if any(pool["rows"] for pool in pools.values()) else "empty")
    return _sealed({
        "schema_version": 1, "mode": "intraday_1445_observation",
        "trade_date": trade_date, "cutoff": cutoff,
        "input_hash": meta["input_hash"],
        "run_id": "intraday-observation:{}:{}".format(trade_date, meta["input_hash"][:16]),
        "formal_actions_allowed": False, "status": status, "pools": pools,
        "input_coverage": {"status": "partial" if collection_partial else "available",
                           "expected": expected, "acquired": acquired,
                           "foundation_missing": foundation_missing},
        "missing_auxiliary_inputs": [key for key in (
            "sector_flows", "market_sentiment", "limit_up_pool", "market_indices",
        ) if key in (meta.get("missing_auxiliary_inputs") or [])],
    })


def build_failure_snapshot(trade_date, *, cutoff, failure_code, input_hash=None):
    validate_cutoff(cutoff, trade_date)
    if input_hash is not None and not _HASH.fullmatch(str(input_hash)):
        raise ValueError("invalid input hash")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", str(failure_code)):
        raise ValueError("invalid failure code")
    identity = input_hash or content_hash({"trade_date": trade_date, "cutoff": cutoff, "failure_code": failure_code})
    return _sealed({
        "schema_version": 1, "mode": "intraday_1445_observation",
        "trade_date": trade_date, "cutoff": cutoff, "input_hash": input_hash,
        "run_id": "intraday-observation:{}:{}".format(trade_date, identity[:16]),
        "formal_actions_allowed": False, "status": "failed", "pools": {},
        "failure_code": failure_code,
    })


def build_observation_digest(snapshot):
    _validate_snapshot(snapshot)
    return select_digest(snapshot)


def format_observation_messages(snapshot, *, max_chars=1200, max_bytes=None):
    """One shared, bounded UTF-8 notice; the private snapshot keeps every row."""
    digest = build_observation_digest(snapshot)
    byte_budget = min(2048, max_bytes) if max_bytes is not None else 2048
    if byte_budget < 250 or max_chars < 250:
        raise ValueError("message size too small")
    header = "【14:45观察精选】\n{} 数据截至14:45\n观察用途，盘后任务照常。批次 {}".format(
        snapshot["trade_date"], snapshot["content_hash"][:8])
    if snapshot["status"] == "failed":
        message = header + "\n精选0只 / 候选数量未知\n本次计算失败或关键数据不足，未提供候选池。"
        if len(message.encode("utf-8")) > byte_budget or len(message) > max_chars:
            raise ValueError("message size too small")
        return [message]
    notes = []
    coverage = snapshot.get("input_coverage", {})
    if coverage.get("status") == "partial":
        notes.append("已核验行情 {}/{} 只，存在数据缺口。".format(
            coverage["acquired"], coverage["expected"]))
        if coverage.get("foundation_missing", 0):
            notes.append("另有{}只基础数据不足未参与。".format(coverage["foundation_missing"]))
    unavailable = sum(pool["status"] == "unavailable" for pool in snapshot["pools"].values())
    partial = [pool for pool in snapshot["pools"].values() if pool["status"] == "partial"]
    if unavailable:
        notes.append("{}个池数据不足，暂不可用；候选数仅计已核验范围。".format(unavailable))
    if partial:
        counts = ["{}/{}".format(pool["verified_count"], pool["requested_count"])
                  for pool in partial if "verified_count" in pool and "requested_count" in pool]
        notes.append("{}个池覆盖不完整{}。".format(len(partial), "（" + "、".join(counts) + "）" if counts else ""))
    labels = {"sector_flows": "板块资金", "market_sentiment": "市场情绪",
              "limit_up_pool": "涨停生态", "market_indices": "市场指数"}
    missing = [labels[key] for key in snapshot.get("missing_auxiliary_inputs", []) if key in labels]
    if missing:
        notes.append("缺少{}信息。".format("、".join(missing)))
    states = {"confirmed": "技术确认·观察", "daily_candidate": "日线候选·观察", "research_candidate": "研究候选"}
    selected = list(digest["selected"])
    while True:
        lines = [header, "精选{}只 / 候选{}只（股票去重）".format(len(selected), digest["candidate_count"])]
        if selected:
            lines.append("按有效来源数、确认/数据依据及源内原序精选。")
            for index, row in enumerate(selected, 1):
                sources = "、".join("{}·{}".format(SOURCE_LABELS[family], states[row["source_states"][family]])
                                   for family in row["sources"])
                lines.append("{}. {} {}｜{}源：{}{}".format(index, row["name"], row["code"],
                    row["valid_source_count"], sources, "；另有待核/不通过记录" if row["has_pending"] else ""))
        elif digest["candidate_count"]:
            lines.append("精选依据不足，现有候选保留在私有完整归档。")
        elif snapshot["status"] == "empty":
            lines.append("本次未选出候选。")
        else:
            lines.append("已核验范围暂无候选，其余数据待核验。")
        if selected:
            lines.append("完整名单保留于本批私有归档。")
        message = "\n".join(lines + notes)
        if len(message.encode("utf-8")) <= byte_budget and len(message) <= max_chars:
            return [message]
        if not selected:
            raise ValueError("observation digest exceeds message size limit")
        selected.pop()


def freeze_observation_snapshot(path, snapshot):
    _validate_snapshot(snapshot)
    return freeze_json(path, snapshot)


def _sync_directory(path):
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def freeze_json(path, value):
    """Write a complete immutable JSON artifact; never replace an older batch."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    material = canonical_bytes(value) + b"\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".freeze-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(material)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, str(path))
            _sync_directory(path.parent)
        except FileExistsError:
            if path.read_bytes() != material:
                raise FileExistsError("immutable observation artifact already differs")
        return path
    finally:
        os.unlink(temporary)


def _replace_receipt(path, value):
    descriptor, temporary = tempfile.mkstemp(prefix=".receipt-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical_bytes(value) + b"\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, str(path))
        _sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _prior_format_result(receipt, identity):
    """An attempted old batch is immutable even when its text/hash changes."""
    if any(receipt.get(key) != identity.get(key) for key in ("run_id", "input_hash", "channel")):
        raise ValueError("outbox belongs to another observation batch")
    if identity.get("channel") == "wecom" and receipt.get("webhook_hash") != identity.get("webhook_hash"):
        raise ValueError("WeCom outbox belongs to another destination")
    if not isinstance(receipt.get("parts"), dict):
        raise ValueError("invalid observation receipt")
    if receipt.get("format_version") != FORMAT_VERSION and receipt["parts"]:
        total = len(receipt.get("message_hashes") or [])
        complete = bool(total and all(receipt["parts"].get(str(index), {}).get("state") == "sent"
                                      for index in range(total)))
        return {"status": "already_sent" if complete else "delivery_uncertain", "success": complete,
                "format_protected": True, "parts": total or len(receipt["parts"])}
    return None


def deliver_observation(snapshot, *, outbox_path, app_token, uid, sender=None, deadline=None, clock=None):
    """Send only to one existing WxPusher UID, with a durable per-part receipt."""
    _validate_snapshot(snapshot)
    if not app_token or not uid or isinstance(uid, (list, tuple)):
        raise ValueError("one personal WxPusher recipient is required")
    if sender is None:
        from chanlun.preclose_notify import send_wxpusher_message
        sender = send_wxpusher_message
    clock = clock or (lambda: datetime.now(SHANGHAI))
    path = Path(outbox_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    messages = format_observation_messages(snapshot)
    identity = {"run_id": snapshot["run_id"], "content_hash": snapshot["content_hash"],
                "input_hash": snapshot.get("input_hash"), "channel": "wxpusher",
                "format_version": FORMAT_VERSION,
                "message_hashes": [content_hash(message) for message in messages]}
    descriptor = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt = json.loads(path.read_text()) if path.exists() else dict(identity, parts={})
        protected = _prior_format_result(receipt, identity)
        if protected is not None:
            return protected
        if any(receipt.get(key) != value for key, value in identity.items()):
            raise ValueError("outbox belongs to another observation batch")
        if all(receipt["parts"].get(str(index), {}).get("state") == "sent" for index in range(len(messages))):
            return {"status": "already_sent", "success": True, "parts": len(messages)}
        for index, message in enumerate(messages):
            part = receipt["parts"].get(str(index), {})
            if part.get("state") == "sent":
                continue
            if part:
                return {"status": "delivery_uncertain", "success": False, "part": index + 1}
            if deadline is not None and clock() >= deadline:
                return {"status": "deadline_exceeded", "success": False, "part": index + 1}
            receipt["parts"][str(index)] = {"state": "dispatching", "message_hash": content_hash(message)}
            _replace_receipt(path, receipt)
            try:
                remaining = (deadline - clock()).total_seconds() if deadline is not None else 10.0
                if remaining <= 0:
                    result = {"success": False, "error": "deadline_exceeded"}
                else:
                    result = sender(message, app_token=app_token, uid=uid,
                                    timeout=min(10.0, remaining), summary="14:45观察精选")
            except Exception as exc:
                result = {"success": False, "error": type(exc).__name__}
            safe_result = {key: result[key] for key in (
                "success", "provider", "http_status", "business_code", "target_business_code",
                "provider_accepted", "delivery_status", "message_ids", "message_content_ids",
                "send_record_ids", "error",
            ) if key in result}
            successful = result.get("success") is True
            # The shared sender validates the target UID. "sent" denotes
            # provider acceptance only; IDs do not prove user receipt.
            receipt["parts"][str(index)].update(state="sent" if successful else "uncertain", response=safe_result)
            _replace_receipt(path, receipt)
            if not successful:
                return {"status": "delivery_uncertain", "success": False, "part": index + 1}
        return {"status": "sent", "success": True, "parts": len(messages)}


def deliver_wecom_observation(snapshot, *, outbox_path, webhook, deadline,
                              sender=None, clock=None, sleep=None):
    """Deliver one UTF-8 digest to the existing bot, independently of Wx.

    The sidecar binds the frozen parts and destination. A dispatch whose result
    is unknown stays protected, including after process interruption. "sent"
    means provider acceptance, never a claim that a group member read it.
    """
    _validate_snapshot(snapshot)
    if not isinstance(webhook, str) or not webhook:
        raise ValueError("one configured WeCom webhook is required")
    if sender is None:
        from chanlun.preclose_notify import send_wecom_text
        sender = send_wecom_text
    clock = clock or (lambda: datetime.now(SHANGHAI))
    sleep = sleep or time.sleep
    messages = format_observation_messages(snapshot, max_bytes=2048)
    identity = {"run_id": snapshot["run_id"], "content_hash": snapshot["content_hash"],
                "input_hash": snapshot.get("input_hash"), "channel": "wecom",
                "format_version": FORMAT_VERSION,
                "webhook_hash": hashlib.sha256(webhook.encode("utf-8")).hexdigest(),
                "message_hashes": [content_hash(message) for message in messages]}
    path = Path(outbox_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt = json.loads(path.read_text()) if path.exists() else dict(identity, parts={})
        protected = _prior_format_result(receipt, identity)
        if protected is not None:
            return protected
        if (any(receipt.get(key) != value for key, value in identity.items())
                or not isinstance(receipt.get("parts"), dict)):
            raise ValueError("WeCom outbox belongs to another batch, format or destination")

        def result(status, success=False):
            sent = sum(receipt["parts"].get(str(index), {}).get("state") == "sent"
                       for index in range(len(messages)))
            return {"status": status, "success": success, "parts": len(messages),
                    "accepted_parts": sent, "remaining_parts": len(messages) - sent}

        if all(receipt["parts"].get(str(index), {}).get("state") == "sent"
               for index in range(len(messages))):
            return result("already_sent", True)
        for index, message in enumerate(messages):
            part = receipt["parts"].get(str(index), {})
            if part.get("state") == "sent":
                continue
            if part:
                return result("provider_rejected" if part.get("state") == "rejected" else "delivery_uncertain")
            now = clock()
            if now >= deadline:
                return result("deadline_exceeded")
            if receipt.get("last_attempt_at"):
                earliest = datetime.fromisoformat(receipt["last_attempt_at"]) + timedelta(seconds=4)
                wait = (earliest - now).total_seconds()
                if wait > 0:
                    if earliest >= deadline:
                        return result("deadline_exceeded")
                    sleep(wait)
                    if clock() < earliest:
                        return result("rate_limited")
            now = clock()
            if now >= deadline:
                return result("deadline_exceeded")
            receipt["last_attempt_at"] = now.isoformat()
            receipt["parts"][str(index)] = {"state": "dispatching", "message_hash": content_hash(message),
                                            "attempted_at": now.isoformat()}
            _replace_receipt(path, receipt)
            try:
                remaining = (deadline - clock()).total_seconds()
                response = (sender(message, webhook=webhook, timeout=min(10.0, remaining))
                            if remaining > 0 else {"success": False, "error": "deadline_exceeded"})
                if not isinstance(response, dict):
                    raise TypeError("invalid provider response")
            except Exception as exc:
                response = {"success": False, "provider": "wecom", "provider_accepted": False,
                            "delivery_status": "provider_result_unknown", "error": type(exc).__name__}
            safe = {key: response[key] for key in (
                "success", "provider", "http_status", "business_code", "provider_accepted", "delivery_status", "error",
            ) if key in response}
            successful = response.get("success") is True
            rejected = response.get("delivery_status") == "provider_rejected" and not successful
            receipt["parts"][str(index)].update(
                state="sent" if successful else "rejected" if rejected else "uncertain", response=safe)
            _replace_receipt(path, receipt)
            if not successful:
                return result("provider_rejected" if rejected else "delivery_uncertain")
        return result("sent", True)

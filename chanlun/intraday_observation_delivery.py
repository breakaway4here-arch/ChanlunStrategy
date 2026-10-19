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
from datetime import datetime, timedelta, timezone
from pathlib import Path


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


def _row_projection(row):
    if not isinstance(row, dict):
        raise ValueError("invalid pool row")
    code = str(row.get("code") or "")
    name = str(row.get("name") or "").strip()
    if not re.fullmatch(r"\d{6}", code) or not name or len(name) > 40:
        raise ValueError("invalid stock identity")
    result = {"code": code, "name": name.replace("\n", " ").replace("\r", " ")}
    # The request is for pool membership. Unproven price bases, strategy actions
    # and account details must not leak into the private observation notice.
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
                projected = [_row_projection(row) for row in rows]
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


def format_observation_messages(snapshot, *, max_chars=1200):
    _validate_snapshot(snapshot)
    if max_chars < 250:
        raise ValueError("message size too small")
    header = "【14:45完整选股观察】\n{} 数据截至14:45\n观察用途，盘后任务照常。批次 {}".format(
        snapshot["trade_date"], snapshot["content_hash"][:8])
    if snapshot["status"] == "failed":
        return [header + "\n本次计算失败或关键数据不足，未提供候选池。"]
    lines = []
    coverage = snapshot.get("input_coverage", {})
    if coverage.get("status") == "partial":
        lines.append("已核验行情 {}/{} 只，存在数据缺口；空池仅代表已核验范围。".format(
            coverage["acquired"], coverage["expected"]))
        if coverage.get("foundation_missing", 0):
            lines.append("另有{}只基础数据不足未参与。".format(coverage["foundation_missing"]))
    if snapshot["status"] == "partial":
        lines.append("部分池数据不足，以下逐池说明。")
    labels = {"sector_flows": "板块资金", "market_sentiment": "市场情绪",
              "limit_up_pool": "涨停生态", "market_indices": "市场指数"}
    missing = [labels[key] for key in snapshot.get("missing_auxiliary_inputs", []) if key in labels]
    if missing:
        lines.append("本次缺少{}信息，对照盘后时需一并考虑。".format("、".join(missing)))
    for key, _label, _path in POOL_SPECS:
        pool = snapshot["pools"][key]
        status = pool["status"]
        if status == "unavailable":
            lines.append(pool["label"] + "：数据不足，暂不可用")
        elif status == "empty":
            lines.append(pool["label"] + "：本次未选出候选")
        else:
            coverage = ""
            if status == "partial":
                coverage = "，覆盖不完整"
                if "verified_count" in pool and "requested_count" in pool:
                    coverage += " {}/{}".format(pool["verified_count"], pool["requested_count"])
            lines.append("{}：{}只{}".format(pool["label"], len(pool["rows"]), coverage))
            if not pool["rows"]:
                lines.append("已核验范围暂无候选，其余数据待补齐")
            for row in pool["rows"]:
                lines.append("{} {}".format(row["name"], row["code"]))
    # Reserve room for the part counter before splitting; no names are truncated.
    limit = max_chars - len(header) - 30
    groups, current = [], []
    for line in lines:
        if len("\n".join(current + [line])) > limit and current:
            groups.append(current)
            current = []
        current.append(line)
    if current:
        groups.append(current)
    return [header + "\n第{}/{}条\n".format(index + 1, len(groups)) + "\n".join(group)
            for index, group in enumerate(groups)]


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
                "input_hash": snapshot.get("input_hash"), "channel": "wxpusher"}
    descriptor = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt = json.loads(path.read_text()) if path.exists() else dict(identity, parts={})
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
                                    timeout=min(10.0, remaining), summary="14:45完整选股观察")
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

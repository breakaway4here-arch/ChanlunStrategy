"""Publish isolated pre-close snapshots and send deliberately simple notices."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
import uuid
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from chanlun.decision_workbench import build_preclose_workbench, format_decision_notification, notification_semantics


WXPUSHER_SEND_URL = "https://wxpusher.zjiecode.com/api/send/message"
POOL_LABELS = (
    ("main", "主推"),
    ("h4_t3", "H4 T+3"),
    ("acceleration", "加速"),
)


def _pool_lines(snapshot):
    pools = snapshot.get("pools") if isinstance(snapshot, dict) else {}
    pools = pools if isinstance(pools, dict) else {}
    lines = []
    for key, label in POOL_LABELS:
        rendered = []
        rows = pools.get(key)
        rows = rows if isinstance(rows, (list, tuple)) else []
        for candidate in rows[:3]:
            if not isinstance(candidate, dict):
                continue
            name = str(candidate.get("name") or "").strip()
            code = str(candidate.get("code") or "").strip()
            try:
                price = float(candidate.get("reference_price"))
            except (TypeError, ValueError):
                continue
            if not name or not code or price <= 0:
                continue
            rendered.append("{} {}｜参考{:.2f}".format(name, code, price))
        lines.append("{}：{}".format(label, "；".join(rendered) if rendered else "本期未选出推荐票"))
    return lines


def format_preclose_message(snapshot):
    """Render only action-oriented fields, capped at three names per pool."""

    source = snapshot if isinstance(snapshot, dict) else {}
    pools = source.get("pools") if isinstance(source.get("pools"), dict) else {}
    has_rows = any(pools.get(key) for key, _label in POOL_LABELS)
    if source.get('status') not in ('available', 'empty'):
        return '【14:45预跑】\n预跑结果暂不可用，本次不提供候选；请查看页面状态。'
    if source.get("status") != "available" or not has_rows:
        return "【14:45预跑】\n本期未选出推荐票"
    return format_decision_notification(build_preclose_workbench(source), heading='14:45预跑')


def format_reconciliation_message(reconciliation, *, decision_projection=None):
    """Render the compact user-facing post-close comparison."""

    source = reconciliation if isinstance(reconciliation, dict) else {}
    status = source.get("status")
    formal_projection = (isinstance(decision_projection, dict)
            and decision_projection.get('phase') == 'formal'
            and decision_projection.get('report_date') == source.get('trade_date'))
    if status == "preclose_unavailable":
        message = "【盘后复核】\n预跑结果不可用，无法与正式结果比较；请以盘后正式结果为准。"
        if formal_projection:
            return message + "\n\n" + format_decision_notification(decision_projection)
        pools = source.get("pools") if isinstance(source.get("pools"), dict) else {}
        lines = [message]
        for key, label in POOL_LABELS:
            pool = pools.get(key) if isinstance(pools.get(key), dict) else {}
            rows = pool.get("formal")
            if not isinstance(rows, list):
                continue
            names = [str(row.get("name") or row.get("code") or "").strip()
                     for row in rows[:3] if isinstance(row, dict)]
            lines.append("正式{}：{}".format(label, "、".join(filter(None, names)) or "本期未选出推荐票"))
        return "\n".join(lines)
    if status != 'formal_pending' and formal_projection:
        return format_decision_notification(decision_projection)
    if status == "formal_pending":
        return "【盘后复核】\n今日正式结果尚未生成，暂不继续参考预跑清单"
    pools = source.get("pools") if isinstance(source.get("pools"), dict) else {}
    if status == "unchanged":
        counts = []
        for key, label in POOL_LABELS:
            pool = pools.get(key) if isinstance(pools.get(key), dict) else {}
            separator = " " if key == "h4_t3" else ""
            counts.append("{}{}{}只".format(
                label,
                separator,
                len(pool.get("retained") or []),
            ))
        return "\n".join([
            "【盘后复核】",
            "正式结果与14:45预跑一致",
            "｜".join(counts),
        ])
    lines = ["【盘后复核】与14:45预跑有变化"]
    for key, label in POOL_LABELS:
        pool = pools.get(key) if isinstance(pools.get(key), dict) else {}
        pieces = []
        for field, prefix in (
            ("retained", "保留 "),
            ("added_after_close", "正式新增 "),
            ("removed_after_close", "预跑有、正式无 "),
        ):
            names = []
            for item in (pool.get(field) or [])[:3]:
                if isinstance(item, dict):
                    name = str(item.get("name") or item.get("code") or "").strip()
                else:
                    name = str(item or "").strip()
                if name:
                    names.append(name)
            if names:
                pieces.append(prefix + "、".join(names))
        lines.append("{}：{}".format(label, "｜".join(pieces) if pieces else "无变化"))
    return "\n".join(lines)


def _safe_response(response, success, provider, payload=None):
    result = {
        "success": bool(success),
        "provider": provider,
        "http_status": int(getattr(response, "status_code", 0) or 0),
    }
    if success:
        result.update(provider_accepted=True, delivery_status="provider_accepted")
    if payload is None:
        try:
            payload = response.json()
        except Exception:
            payload = {}
    if isinstance(payload, dict):
        if "code" in payload:
            result["business_code"] = payload.get("code")
        if "errcode" in payload:
            result["business_code"] = payload.get("errcode")
        data = payload.get("data")
        if isinstance(data, list):
            for source, destination in (("messageId", "message_ids"),
                                        ("sendRecordId", "send_record_ids"),
                                        ("messageContentId", "message_content_ids")):
                values = [item[source] for item in data if isinstance(item, dict) and item.get(source) is not None]
                if values:
                    result[destination] = values[:10]
    return result


def _wxpusher_target_result(response, payload, uid):
    """One exact UID task receipt is acceptance; absent/ambiguous receipts stay unknown."""
    result = _safe_response(response, False, "wxpusher",
                            {"code": payload.get("code")} if isinstance(payload, dict) else {})
    result["delivery_status"] = "provider_result_unknown"
    if not isinstance(payload, dict):
        return result
    top_code = payload.get("code")
    if type(top_code) is int and top_code != 1000 and payload.get("success") is False:
        result["delivery_status"] = "provider_rejected"
        return result
    if type(top_code) is not int or top_code != 1000 or payload.get("success") is not True:
        return result
    rows = payload.get("data")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return result
    targets = [row for row in rows if row.get("uid") == str(uid)]
    if len(targets) != 1 or type(targets[0].get("code")) is not int:
        return result
    target = targets[0]
    success = target["code"] == 1000
    result = _safe_response(response, success, "wxpusher", dict(payload, data=[target]))
    result.update(target_business_code=target["code"],
                  delivery_status="provider_accepted" if success else "provider_rejected")
    return result


def _provider_exception_result(exc, provider, response):
    """Only an explicit HTTP rejection proves an attempted POST was not accepted."""
    status = int(getattr(response, "status_code", 0) or 0)
    return {"success": False, "provider": provider, "error": type(exc).__name__,
            "http_status": status,
            "delivery_status": "provider_rejected" if 400 <= status < 500 else "provider_result_unknown"}


def send_wxpusher_message(
    message,
    *,
    app_token,
    uid,
    post=None,
    timeout=10,
    summary="14:45预跑提醒",
):
    """Require HTTP, top-level success, and the exact recipient task's business code."""

    post = post or requests.post
    response = None
    try:
        response = post(
            WXPUSHER_SEND_URL,
            json={
                "appToken": str(app_token),
                "content": str(message),
                "summary": str(summary),
                "contentType": 1,
                "uids": [str(uid)],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return _wxpusher_target_result(response, payload, uid)
    except Exception as exc:
        return _provider_exception_result(exc, "wxpusher", response)


def send_wecom_text(message, *, webhook, post=None, timeout=10):
    """Send an optional WeCom text and require errcode == 0."""

    post = post or requests.post
    response = None
    try:
        response = post(
            str(webhook),
            json={"msgtype": "text", "text": {"content": str(message)}},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        code = payload.get("errcode") if isinstance(payload, dict) else None
        success = type(code) is int and code == 0
        result = _safe_response(response, success, "wecom", payload)
        result["delivery_status"] = ("provider_accepted" if success else
            "provider_rejected" if type(code) is int else "provider_result_unknown")
        return result
    except Exception as exc:
        return _provider_exception_result(exc, "wecom", response)


def load_preclose_env(path="~/.config/chanlun-strategy/preclose.env"):
    """Load the dedicated env file only when ownership and 0600 mode are exact."""

    env_path = Path(path).expanduser()
    file_stat = env_path.stat()
    if not stat.S_ISREG(file_stat.st_mode):
        raise PermissionError("pre-close env must be a regular file")
    if file_stat.st_uid != os.getuid():
        raise PermissionError("pre-close env owner mismatch")
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise PermissionError("pre-close env mode must be 0600")
    values = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError("invalid pre-close env line")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in {"\"", "'"} and value[-1:] == value[:1]:
            value = value[1:-1]
        if not key or not key.replace("_", "").isalnum() or not key[0].isalpha():
            raise ValueError("invalid pre-close env key")
        values[key] = value
    return values


class NotificationOutbox:
    """Append-only provider results used for content-hash/channel idempotency."""

    @staticmethod
    def _row_idempotency_key(row):
        for key in ("idempotency_key", "key", "event_key"):
            if key in row and row.get(key) is not None:
                value = str(row.get(key)).strip()
                if value:
                    return value
        return ""

    def __init__(self, path):
        self.path = Path(path).expanduser()

    def _rows(self):
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                rows.append(value)
        return rows

    def was_successful(
        self,
        content_hash,
        channel,
        idempotency_key=None,
        formal_hash=None,
    ):
        idempotency_key = (
            str(idempotency_key).strip() if idempotency_key is not None else None
        )
        formal_hash = str(formal_hash).strip() if formal_hash is not None else ""
        rows = self._rows()
        date_prefix = (idempotency_key or '').split(':', 1)[0] + ':'
        legacy_mapped = any(row.get('event_type') == 'legacy_migration'
            and row.get('formal_content_hash') == formal_hash
            and row.get('channel') == channel and row.get('success') is True
            and self._row_idempotency_key(row).startswith(date_prefix) for row in rows)
        for row in rows:
            if row.get("channel") != channel or row.get("success") is not True:
                continue

            if row.get("content_hash") != content_hash and (
                not formal_hash or row.get("content_hash") != formal_hash
            ):
                continue

            row_key = self._row_idempotency_key(row)
            if idempotency_key is None or row_key in ("", idempotency_key):
                return True

            if formal_hash and idempotency_key:
                row_key = self._row_idempotency_key(row)
                trade_date = idempotency_key.split(":", 1)[0]
                if not legacy_mapped and row_key == "{}:{}".format(trade_date, formal_hash):
                    return True
        return False

    def unconfirmed_result(self, content_hash, channel, idempotency_key=None):
        """A response lost after sending cannot safely authorize another POST."""
        legacy_network_errors = {"Timeout", "ReadTimeout", "ConnectTimeout", "TimeoutError",
                                 "ConnectionError", "SSLError", "ChunkedEncodingError",
                                 "ContentDecodingError", "JSONDecodeError", "ValueError", "HTTPError"}
        closed_dispatches = set()
        for row in reversed(self._rows()):
            if row.get("content_hash") != content_hash or row.get("channel") != channel:
                continue
            if idempotency_key is not None and self._row_idempotency_key(row) not in ("", idempotency_key):
                continue
            dispatch_id = row.get("dispatch_id")
            if row.get("dispatch_state") == "final" and dispatch_id:
                closed_dispatches.add(dispatch_id)
            elif row.get("dispatch_state") == "dispatching" and dispatch_id in closed_dispatches:
                continue
            response = row.get("response")
            if not isinstance(response, dict) or row.get("success") is True:
                continue
            if (response.get("delivery_status") == "provider_result_unknown"
                    or (not response.get("delivery_status") and response.get("error") in legacy_network_errors)):
                return dict(response, success=False, delivery_status="provider_result_unknown")
        return None

    def begin_dispatch(self, *, content_hash, channel, **context):
        """Fsync uncertainty before POST, so deadline/exit cannot leave an empty outbox."""
        dispatch_id = uuid.uuid4().hex
        self.record(content_hash=content_hash, channel=channel, success=False,
                    response={"success": False, "provider": channel,
                              "delivery_status": "provider_result_unknown", "error": "dispatching"},
                    dispatch_id=dispatch_id, dispatch_state="dispatching", **context)
        return dispatch_id

    def record(
        self,
        *,
        content_hash,
        channel,
        success,
        response,
        snapshot_id=None,
        idempotency_key=None,
        formal_content_hash=None,
        phase=None,
        event_type=None,
        summary_hash=None,
        dispatch_id=None,
        dispatch_state=None,
    ):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "content_hash": str(content_hash),
            "channel": str(channel),
            "success": bool(success),
            "response": response if isinstance(response, dict) else {},
        }
        if snapshot_id is not None:
            record["snapshot_id"] = str(snapshot_id)
        if idempotency_key is not None:
            record["idempotency_key"] = str(idempotency_key)
        if phase is not None:
            record["phase"] = str(phase)
        if event_type is not None:
            record["event_type"] = str(event_type)
        if summary_hash is not None:
            record["summary_hash"] = str(summary_hash)
        if formal_content_hash is not None:
            record["formal_content_hash"] = str(formal_content_hash)
        if dispatch_id is not None:
            record["dispatch_id"] = str(dispatch_id)
        if dispatch_state is not None:
            record["dispatch_state"] = str(dispatch_state)
        # ASCII escaping keeps a failed byte prefix decodable without changing JSON values.
        encoded = json.dumps(
            record,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        descriptor = os.open(
            str(self.path),
            os.O_CREAT | os.O_APPEND | os.O_RDWR,
            0o600,
        )
        try:
            size = os.fstat(descriptor).st_size
            # Preserve a failed partial row, but never concatenate the next intent onto it.
            prefix = b"\n" if size and os.pread(descriptor, 1, size - 1) != b"\n" else b""
            pending = memoryview(prefix + encoded.encode("ascii"))
            while pending:
                written = os.write(descriptor, pending)
                if written <= 0:
                    raise OSError("outbox write made no progress")
                pending = pending[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _request_result_error(exc):
    return {"success": False, "error": type(exc).__name__}


def _normalize_reconciliation_row(item):
    if not isinstance(item, dict):
        return {"value": str(item or "").strip()}
    normalized = {
        "code": str(item.get("code") or item.get("id") or "").strip(),
        "name": str(item.get("name") or "").strip(),
        "action": str(item.get("action") or item.get("decision") or "").strip(),
        "reason": str(item.get("reason") or "").strip(),
    }
    if item.get("reference_price") is not None:
        normalized["reference_price"] = str(item.get("reference_price"))
    return {k: v for k, v in normalized.items() if v}


def _reconciliation_signature_hash(reconciliation, *, decision_projection=None):
    if not isinstance(reconciliation, dict):
        return hashlib.sha256(b"").hexdigest()

    def _normalize_pool_rows(field_rows):
        rows = []
        for item in field_rows or []:
            if isinstance(item, (dict, str)):
                rows.append(_normalize_reconciliation_row(item))
        rows.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
        return rows

    pools = reconciliation.get("pools") if isinstance(reconciliation.get("pools"), dict) else {}
    event = {
        "trade_date": str(reconciliation.get("trade_date") or ""),
        "status": str(reconciliation.get("status") or ""),
        "event_type": str(
            reconciliation.get("event_type")
            or reconciliation.get("status")
            or "reconciled"
        ),
    }
    signature = {"event": event, "pools": {}}
    if (isinstance(decision_projection, dict)
            and decision_projection.get('report_date') == reconciliation.get('trade_date')
            and decision_projection.get('phase') == 'formal'):
        signature['decision'] = notification_semantics(decision_projection)
    for pool_name, _label in POOL_LABELS:
        pool = pools.get(pool_name) if isinstance(pools.get(pool_name), dict) else {}
        signature["pools"][pool_name] = {}
        for field in ("retained", "added_after_close", "removed_after_close"):
            signature["pools"][pool_name][field] = _normalize_pool_rows(pool.get(field))
        if reconciliation.get("status") == "preclose_unavailable":
            signature["pools"][pool_name]["formal"] = _normalize_pool_rows(pool.get("formal"))
    material = json.dumps(
        signature,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def publish_preclose_snapshot(
    snapshot,
    *,
    api_base,
    write_token,
    put=None,
    get=None,
    timeout=10,
    budget_remaining=None,
):
    """Recover finite transport failures; unknown writes must be read before retry."""

    put = put or requests.put
    get = get or requests.get
    base = str(api_base or "").strip().rstrip("/")
    token = str(write_token or "").strip()
    if not base or not token:
        return {"success": False, "error": "missing_publish_configuration"}
    initial_budget = float(budget_remaining()) if budget_remaining is not None else float(timeout) * 6
    deadline = time.monotonic() + max(0, initial_budget)

    def remaining_budget():
        remaining = deadline - time.monotonic()
        if budget_remaining is not None:
            remaining = min(remaining, float(budget_remaining()))
        return remaining

    def request_timeout():
        remaining = remaining_budget()
        if remaining <= 0:
            raise TimeoutError("pre-close delivery deadline")
        return min(float(timeout), remaining)

    def transient(exc):
        status = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
        if 400 <= status <= 499:
            return status == 429
        return status == 429 or 500 <= status <= 599 or isinstance(
            exc, (requests.ConnectionError, requests.Timeout,
                  requests.exceptions.ChunkedEncodingError, requests.exceptions.ContentDecodingError))

    def retry_after_seconds(exc):
        headers = getattr(getattr(exc, "response", None), "headers", {}) or {}
        value = headers.get("Retry-After", "")
        try:
            return max(0, float(value))
        except (TypeError, ValueError):
            try:
                return max(0, (parsedate_to_datetime(value) - datetime.now().astimezone()).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return 0

    needs_write = True
    write_payload = {}
    last_error = {"success": False, "error": "delivery_unconfirmed"}
    retry_after = 0
    for attempt in range(3):
        try:
            request_timeout()
            if attempt:
                delay = max(0.25 * (2 ** (attempt - 1)), retry_after)
                if delay > 30 or remaining_budget() <= delay:
                    raise TimeoutError("pre-close delivery deadline")
                time.sleep(delay)
                retry_after = 0
            if needs_write:
                try:
                    write_response = put(
                        base + "/api/preclose/snapshot", json=snapshot,
                        headers={"authorization": "Bearer " + token}, timeout=request_timeout())
                    write_response.raise_for_status()
                    try:
                        write_payload = write_response.json()
                    except ValueError:
                        write_payload = {}  # HTTP succeeded; exact GET still decides publication.
                except Exception as exc:
                    if not transient(exc):
                        return _request_result_error(exc)
                    last_error = _request_result_error(exc)
                    retry_after = retry_after_seconds(exc)
                # Even a failed PUT may have committed. GET is the only next action.
                needs_write = False
            try:
                read_response = get(
                    base + "/api/preclose/latest", params={"date": snapshot.get("trade_date")},
                    headers={"cache-control": "no-cache"}, timeout=request_timeout())
                if int(getattr(read_response, "status_code", 0) or 0) == 404:
                    # A confirmed absence differs from an unreachable/other snapshot.
                    needs_write = True
                    last_error = {"success": False, "error": "readback_not_found"}
                    continue
                read_response.raise_for_status()
                read_payload = read_response.json()
                request_timeout()
            except Exception as exc:
                if not transient(exc):
                    return _request_result_error(exc)
                last_error = _request_result_error(exc)
                retry_after = max(retry_after, retry_after_seconds(exc))
                continue
        except Exception as exc:
            return _request_result_error(exc)
        if not isinstance(read_payload, dict):
            return {"success": False, "error": "invalid_readback"}
        checks = {key + "_matches": bool(snapshot.get(key)) and read_payload.get(key) == snapshot.get(key)
                  for key in ("snapshot_id", "content_hash", "trade_date")}
        if not all(checks.values()):
            return dict(success=False, error="readback_mismatch", **checks)
        return {
            "success": True, "snapshot_id": read_payload.get("snapshot_id"),
            "content_hash": read_payload.get("content_hash"),
            "revision": write_payload.get("revision") if isinstance(write_payload, dict) else None,
            "write_status": write_payload.get("status") if isinstance(write_payload, dict) else None,
        }
    return last_error


def publish_preclose_and_notify(
    snapshot,
    *,
    api_base,
    write_token,
    wxpusher_app_token,
    wxpusher_uid,
    outbox,
    wecom_webhook=None,
    notify=True,
    put=None,
    get=None,
    post=None,
    timeout=10,
    budget_remaining=None,
):
    """Publish first; only a matching GET can unlock independent notifications."""

    publish = publish_preclose_snapshot(
        snapshot,
        api_base=api_base,
        write_token=write_token,
        put=put,
        get=get,
        timeout=timeout,
        budget_remaining=budget_remaining,
    )
    result = {"publish": publish, "notifications": {}}
    if not publish.get("success") or not notify:
        return result

    message = format_preclose_message(snapshot)
    content_hash = str(snapshot.get("content_hash") or "")
    channels = [("wxpusher", wxpusher_app_token and wxpusher_uid)]
    if wecom_webhook:
        channels.append(("wecom", True))
    for channel, configured in channels:
        remaining = float(budget_remaining()) if budget_remaining is not None else float(timeout)
        if remaining <= 0:
            result["notifications"][channel] = {"success": False, "error": "delivery_deadline"}
            break
        channel_timeout = min(float(timeout), remaining)
        unconfirmed = outbox.unconfirmed_result(content_hash, channel)
        already_sent = outbox.was_successful(content_hash, channel)
        dispatch_id = None
        if configured and not already_sent and not unconfirmed:
            dispatch_id = outbox.begin_dispatch(content_hash=content_hash, channel=channel,
                                                snapshot_id=snapshot.get("snapshot_id"))
            if budget_remaining is not None:
                channel_timeout = min(channel_timeout, float(budget_remaining()))
        if already_sent:
            delivery = {"success": True, "status": "already_sent"}
        elif unconfirmed:
            delivery = unconfirmed
        elif dispatch_id and channel_timeout <= 0:
            delivery = {"success": False, "error": "delivery_deadline", "delivery_status": "not_dispatched"}
        elif not configured:
            delivery = {"success": False, "error": "missing_channel_configuration"}
        elif channel == "wxpusher":
            delivery = send_wxpusher_message(
                message,
                app_token=wxpusher_app_token,
                uid=wxpusher_uid,
                post=post,
                timeout=channel_timeout,
            )
        else:
            delivery = send_wecom_text(
                message,
                webhook=wecom_webhook,
                post=post,
                timeout=channel_timeout,
            )
        if delivery.get("status") != "already_sent" and not unconfirmed:
            outbox.record(
                content_hash=content_hash,
                channel=channel,
                success=delivery.get("success") is True,
                response=delivery,
                snapshot_id=snapshot.get("snapshot_id"),
                dispatch_id=dispatch_id,
                dispatch_state="final" if dispatch_id else None,
            )
        result["notifications"][channel] = delivery
    return result


def publish_reconciliation(
    reconciliation,
    *,
    api_base,
    write_token,
    put=None,
    get=None,
    timeout=10,
):
    """PUT reconciliation and require the same public content hash on GET."""

    put = put or requests.put
    get = get or requests.get
    base = str(api_base or "").strip().rstrip("/")
    token = str(write_token or "").strip()
    if not base or not token:
        return {"success": False, "error": "missing_publish_configuration"}
    try:
        headers = {"authorization": "Bearer " + token}
        write_response = put(
            base + "/api/preclose/reconciliation",
            json=reconciliation,
            headers=headers,
            timeout=timeout,
        )
        if int(getattr(write_response, "status_code", 0) or 0) == 412:
            conflict_payload = write_response.json()
            revision = (
                conflict_payload.get("revision")
                if isinstance(conflict_payload, dict)
                else None
            )
            if not isinstance(revision, int) or revision < 1:
                return {"success": False, "error": "invalid_revision_conflict"}
            retry_headers = dict(headers)
            retry_headers["if-match"] = '"{}"'.format(revision)
            write_response = put(
                base + "/api/preclose/reconciliation",
                json=reconciliation,
                headers=retry_headers,
                timeout=timeout,
            )
        write_response.raise_for_status()
        write_payload = write_response.json()
        read_response = get(
            base + "/api/preclose/reconciliation",
            params={"date": reconciliation.get("trade_date")},
            headers={"cache-control": "no-cache"},
            timeout=timeout,
        )
        read_response.raise_for_status()
        read_payload = read_response.json()
    except Exception as exc:
        return _request_result_error(exc)
    if not isinstance(read_payload, dict):
        return {"success": False, "error": "invalid_readback"}
    checks = {
        "content_hash": read_payload.get("content_hash") == reconciliation.get("content_hash"),
        "preclose_content_hash": read_payload.get("preclose_content_hash")
        == reconciliation.get("preclose_content_hash"),
        "formal_content_hash": read_payload.get("formal_content_hash")
        == reconciliation.get("formal_content_hash"),
    }
    if not all(checks.values()):
        return {"success": False, "error": "readback_mismatch", "checks": checks}
    return {
        "success": True,
        "content_hash": read_payload.get("content_hash"),
        "preclose_content_hash": read_payload.get("preclose_content_hash"),
        "formal_content_hash": read_payload.get("formal_content_hash"),
        "revision": write_payload.get("revision") if isinstance(write_payload, dict) else None,
        "write_status": write_payload.get("status") if isinstance(write_payload, dict) else None,
    }


def send_reconciliation_notifications(
    reconciliation,
    *,
    outbox,
    wxpusher_app_token,
    wxpusher_uid,
    wecom_webhook=None,
    post=None,
    timeout=10,
    decision_projection=None,
):
    """Notify once per trade-date + phase + event type + summary hash + channel."""

    if reconciliation.get("status") == "formal_pending":
        return {}

    trade_date = str(reconciliation.get("trade_date") or "")
    formal_hash = str(reconciliation.get("formal_content_hash") or "")
    summary_hash = _reconciliation_signature_hash(reconciliation, decision_projection=decision_projection)
    event_type = str(
        reconciliation.get("event_type") or reconciliation.get("status") or "reconciled"
    )
    phase = "reconciliation"
    correction = (isinstance(decision_projection, dict)
        and decision_projection.get('report_date') == trade_date
        and decision_projection.get('phase') == 'formal') and any(
        row.get('success') is True and row.get('phase') == phase
        and outbox._row_idempotency_key(row).startswith(trade_date + ':')
        and row.get('summary_hash') and row.get('summary_hash') != summary_hash
        for row in outbox._rows()
    )
    if correction:
        event_type = 'correction'
    idempotency_key = "{}:{}:{}:{}".format(trade_date, phase, event_type, summary_hash)
    message = format_reconciliation_message(reconciliation, decision_projection=decision_projection)
    if correction:
        message = '【盘后结果更正】\n' + message
    result = {}
    channels = [("wxpusher", wxpusher_app_token and wxpusher_uid)]
    if wecom_webhook:
        channels.append(("wecom", True))
    for channel, configured in channels:
        unconfirmed = outbox.unconfirmed_result(summary_hash, channel, idempotency_key=idempotency_key)
        already_sent = outbox.was_successful(
            summary_hash,
            channel,
            idempotency_key=idempotency_key,
            formal_hash=formal_hash,
        )
        dispatch_id = None
        if configured and not already_sent and not unconfirmed:
            dispatch_id = outbox.begin_dispatch(content_hash=summary_hash, channel=channel,
                snapshot_id=reconciliation.get("snapshot_id"), idempotency_key=idempotency_key,
                formal_content_hash=formal_hash, phase=phase, event_type=event_type, summary_hash=summary_hash)
        if already_sent:
            delivery = {"success": True, "status": "already_sent"}
            if not outbox.was_successful(summary_hash, channel, idempotency_key=idempotency_key):
                outbox.record(content_hash=summary_hash, channel=channel, success=True,
                    response={'status': 'mapped_legacy_success'}, idempotency_key=idempotency_key,
                    formal_content_hash=formal_hash, phase=phase, event_type='legacy_migration', summary_hash=summary_hash)
        elif unconfirmed:
            delivery = unconfirmed
        elif not configured:
            delivery = {"success": False, "error": "missing_channel_configuration"}
        elif channel == "wxpusher":
            delivery = send_wxpusher_message(
                message,
                app_token=wxpusher_app_token,
                uid=wxpusher_uid,
                post=post,
                timeout=timeout,
                summary="盘后复核",
            )
        else:
            delivery = send_wecom_text(
                message,
                webhook=wecom_webhook,
                post=post,
                timeout=timeout,
            )
        if delivery.get("status") != "already_sent" and not unconfirmed:
            outbox.record(
                content_hash=summary_hash,
                channel=channel,
                success=delivery.get("success") is True,
                response=delivery,
                snapshot_id=reconciliation.get("snapshot_id"),
                idempotency_key=idempotency_key,
                formal_content_hash=formal_hash,
                phase=phase,
                event_type=event_type,
                summary_hash=summary_hash,
                dispatch_id=dispatch_id,
                dispatch_state="final" if dispatch_id else None,
            )
        result[channel] = delivery
    return result


def publish_reconciliation_and_notify(
    reconciliation,
    *,
    api_base,
    write_token,
    outbox,
    wxpusher_app_token,
    wxpusher_uid,
    wecom_webhook=None,
    notify=True,
    put=None,
    get=None,
    post=None,
    timeout=10,
    decision_projection=None,
):
    publish = publish_reconciliation(
        reconciliation,
        api_base=api_base,
        write_token=write_token,
        put=put,
        get=get,
        timeout=timeout,
    )
    result = {"publish": publish, "notifications": {}}
    if publish.get("success") and notify:
        result["notifications"] = send_reconciliation_notifications(
            reconciliation,
            outbox=outbox,
            wxpusher_app_token=wxpusher_app_token,
            wxpusher_uid=wxpusher_uid,
            wecom_webhook=wecom_webhook,
            post=post,
            timeout=timeout,
            decision_projection=decision_projection,
        )
    return result

"""Publish isolated pre-close snapshots and send deliberately simple notices."""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime
from pathlib import Path

import requests


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
    if source.get("status") != "available" or not has_rows:
        return "【14:47预跑】\n本期未选出推荐票"
    return "\n".join(
        ["【14:47预跑】14:56:30前有效"]
        + _pool_lines(source)
        + ["14:57后不再下单"]
    )


def format_reconciliation_message(reconciliation):
    """Render the compact user-facing post-close comparison."""

    source = reconciliation if isinstance(reconciliation, dict) else {}
    status = source.get("status")
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
            "正式结果与14:47预跑一致",
            "｜".join(counts),
        ])
    lines = ["【盘后复核】与14:47预跑有变化"]
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


def _safe_response(response, success, provider):
    result = {
        "success": bool(success),
        "provider": provider,
        "http_status": int(getattr(response, "status_code", 0) or 0),
    }
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
            message_ids = []
            for item in data:
                if isinstance(item, dict) and item.get("messageId") is not None:
                    message_ids.append(item.get("messageId"))
            if message_ids:
                result["message_ids"] = message_ids[:10]
    return result


def send_wxpusher_message(
    message,
    *,
    app_token,
    uid,
    post=None,
    timeout=10,
    summary="14:47预跑提醒",
):
    """Return success only when both HTTP and WxPusher business status succeed."""

    post = post or requests.post
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
        success = isinstance(payload, dict) and payload.get("success") is True
        return _safe_response(response, success, "wxpusher")
    except Exception as exc:
        return {
            "success": False,
            "provider": "wxpusher",
            "error": type(exc).__name__,
        }


def send_wecom_text(message, *, webhook, post=None, timeout=10):
    """Send an optional WeCom text and require errcode == 0."""

    post = post or requests.post
    try:
        response = post(
            str(webhook),
            json={"msgtype": "text", "text": {"content": str(message)}},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        success = isinstance(payload, dict) and payload.get("errcode") == 0
        return _safe_response(response, success, "wecom")
    except Exception as exc:
        return {
            "success": False,
            "provider": "wecom",
            "error": type(exc).__name__,
        }


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

    def was_successful(self, content_hash, channel, idempotency_key=None):
        return any(
            row.get("content_hash") == content_hash
            and row.get("channel") == channel
            and (
                idempotency_key is None
                or row.get("idempotency_key") == idempotency_key
            )
            and row.get("success") is True
            for row in self._rows()
        )

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
        if formal_content_hash is not None:
            record["formal_content_hash"] = str(formal_content_hash)
        encoded = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        descriptor = os.open(
            str(self.path),
            os.O_CREAT | os.O_APPEND | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(descriptor, encoded.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _request_result_error(exc):
    return {"success": False, "error": type(exc).__name__}


def publish_preclose_snapshot(
    snapshot,
    *,
    api_base,
    write_token,
    put=None,
    get=None,
    timeout=10,
):
    """PUT the frozen snapshot and require exact public GET identity/hash readback."""

    put = put or requests.put
    get = get or requests.get
    base = str(api_base or "").strip().rstrip("/")
    token = str(write_token or "").strip()
    if not base or not token:
        return {"success": False, "error": "missing_publish_configuration"}
    try:
        write_response = put(
            base + "/api/preclose/snapshot",
            json=snapshot,
            headers={"authorization": "Bearer " + token},
            timeout=timeout,
        )
        write_response.raise_for_status()
        write_payload = write_response.json()
        read_response = get(
            base + "/api/preclose/latest",
            params={"date": snapshot.get("trade_date")},
            headers={"cache-control": "no-cache"},
            timeout=timeout,
        )
        read_response.raise_for_status()
        read_payload = read_response.json()
    except Exception as exc:
        return _request_result_error(exc)
    if not isinstance(read_payload, dict):
        return {"success": False, "error": "invalid_readback"}
    identity_matches = read_payload.get("snapshot_id") == snapshot.get("snapshot_id")
    hash_matches = read_payload.get("content_hash") == snapshot.get("content_hash")
    if not identity_matches or not hash_matches:
        return {
            "success": False,
            "error": "readback_mismatch",
            "snapshot_id_matches": identity_matches,
            "content_hash_matches": hash_matches,
        }
    return {
        "success": True,
        "snapshot_id": read_payload.get("snapshot_id"),
        "content_hash": read_payload.get("content_hash"),
        "revision": write_payload.get("revision") if isinstance(write_payload, dict) else None,
        "write_status": write_payload.get("status") if isinstance(write_payload, dict) else None,
    }


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
):
    """Publish first; only a matching GET can unlock independent notifications."""

    publish = publish_preclose_snapshot(
        snapshot,
        api_base=api_base,
        write_token=write_token,
        put=put,
        get=get,
        timeout=timeout,
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
        if outbox.was_successful(content_hash, channel):
            delivery = {"success": True, "status": "already_sent"}
        elif not configured:
            delivery = {"success": False, "error": "missing_channel_configuration"}
        elif channel == "wxpusher":
            delivery = send_wxpusher_message(
                message,
                app_token=wxpusher_app_token,
                uid=wxpusher_uid,
                post=post,
                timeout=timeout,
            )
        else:
            delivery = send_wecom_text(
                message,
                webhook=wecom_webhook,
                post=post,
                timeout=timeout,
            )
        if delivery.get("status") != "already_sent":
            outbox.record(
                content_hash=content_hash,
                channel=channel,
                success=delivery.get("success") is True,
                response=delivery,
                snapshot_id=snapshot.get("snapshot_id"),
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
):
    """Notify once per trade_date + formal hash + channel."""

    trade_date = str(reconciliation.get("trade_date") or "")
    formal_hash = str(reconciliation.get("formal_content_hash") or "")
    idempotency_key = trade_date + ":" + formal_hash
    message = format_reconciliation_message(reconciliation)
    result = {}
    channels = [("wxpusher", wxpusher_app_token and wxpusher_uid)]
    if wecom_webhook:
        channels.append(("wecom", True))
    for channel, configured in channels:
        if outbox.was_successful(
            formal_hash,
            channel,
            idempotency_key=idempotency_key,
        ):
            delivery = {"success": True, "status": "already_sent"}
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
        if delivery.get("status") != "already_sent":
            outbox.record(
                content_hash=formal_hash,
                channel=channel,
                success=delivery.get("success") is True,
                response=delivery,
                snapshot_id=reconciliation.get("snapshot_id"),
                idempotency_key=idempotency_key,
                formal_content_hash=formal_hash,
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
        )
    return result

from __future__ import annotations

import hashlib
import json


def complete_save_receipt(receipt: dict) -> dict:
    """构造分别绑定请求体、响应体与观测时间的合成网络证据。"""
    result = {
        **receipt,
        "request_body_sha256": hashlib.sha256(b"synthetic-save-request").hexdigest(),
        "response_body_sha256": hashlib.sha256(b"synthetic-save-response").hexdigest(),
        "request_observed_at": "2026-07-15T07:59:58+08:00",
        "response_observed_at": "2026-07-15T07:59:59+08:00",
    }
    for kind in ("request", "response"):
        identity = {
            "kind": kind,
            "url": result["url"],
            "method": result["method"],
            "body_sha256": result[f"{kind}_body_sha256"],
            "observed_at": result[f"{kind}_observed_at"],
        }
        if kind == "response":
            identity["status"] = result["status"]
        digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        result[f"{kind}_evidence_id"] = f"dxm-network-{kind}:" + digest
    return result

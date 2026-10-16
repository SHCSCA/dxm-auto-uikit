"""独立被动监听窗口；不接入 OPEN 授权流程，不产生资格或保存结论。"""

from __future__ import annotations

import math
import json
import uuid

from src.execution.native_gate_capture import (
    NativeGateCaptureError, NativeGateCaptureLimits, NativeGateCaptureScope,
    body_facts, canonical_digest, capture_clock,
)
from src.execution.native_gate_evidence import NATIVE_GATE_URL
from src.services.structured_logging import get_logger, log_event


_LOGGER = get_logger("native_gate.capture")


class PassiveNativeGateCapture:
    def __init__(self, page, scope: NativeGateCaptureScope, *, scope_reader, clock=capture_clock):
        self.page, self.scope, self.scope_reader, self.clock = page, scope, scope_reader, clock
        self.capture_id = uuid.uuid4().hex
        self.active = self.closed = False
        self.started = self.last_stamp = self.closed_stamp = None
        self.listeners, self.events, self.requests, self.issues = [], [], {}, set()
        self.scope_facts = None
        self.registered = self.removed = self.observed_count = self.request_count = self.response_count = 0
        self.failed_count = 0
        self.finished_count = 0
        try:
            self.limits = NativeGateCaptureLimits.from_config_bus()
        except Exception:
            self._fail("NATIVE_GATE_CAPTURE_CONFIGURATION_INVALID")
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_CONFIGURATION_INVALID") from None

    def _fail(self, reason):
        if reason in self.issues:
            return
        self.issues.add(reason)
        log_event(_LOGGER, "native_gate_capture_incomplete", level="WARNING", reason_code=reason,
                  observed_event_count=self.observed_count, request_count=self.request_count,
                  response_count=self.response_count)

    def _check_scope(self):
        if (not isinstance(self.scope, NativeGateCaptureScope) or not callable(self.scope_reader)
                or self.scope_reader() != self.scope):
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_SCOPE_DRIFT")
        facts = self.scope.validate()
        if self.scope_facts is not None and facts != self.scope_facts:
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_SCOPE_DRIFT")
        if self.page.url != self.scope.source_page_url:
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_PAGE_DRIFT")

    def _stamp(self):
        stamp = self.clock()
        stamp.timestamp()
        value = stamp.monotonic_seconds
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_TIME_INVALID")
        if self.last_stamp and (value < self.last_stamp.monotonic_seconds or stamp.wall_time < self.last_stamp.wall_time):
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_TIME_REGRESSION")
        if self.started and (value - self.started.monotonic_seconds > self.limits.max_window_seconds
                or (stamp.wall_time - self.started.wall_time).total_seconds() > self.limits.max_window_seconds):
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_WINDOW_EXPIRED")
        self.last_stamp = stamp
        return stamp

    def __enter__(self):
        if self.listeners or self.closed:
            self._fail("NATIVE_GATE_CAPTURE_WINDOW_REUSED")
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_WINDOW_REUSED")
        try:
            self._check_scope()
            self.scope_facts = self.scope.validate()
            self.frame = self.page.main_frame
            for name, callback in (("request", self._on_request), ("response", self._on_response),
                                   ("requestfinished", self._on_request_finished), ("requestfailed", self._on_request_failed)):
                self.listeners.append((name, callback))
                self.page.on(name, callback)
                self.registered += 1
            self.started = self._stamp()
            self.active = True
        except Exception as exc:
            reason = str(exc) if isinstance(exc, NativeGateCaptureError) else "NATIVE_GATE_CAPTURE_START_FAILED"
            self._fail(reason)
            self.close()
            raise NativeGateCaptureError(reason) from None
        return self

    def __exit__(self, exc_type, _exc, _traceback):
        if exc_type is not None:
            self._fail("NATIVE_GATE_CAPTURE_CALLER_FAILED")
        self.close()
        return False

    def _event(self, request):
        if not self.active or getattr(request, "url", None) != NATIVE_GATE_URL:
            return None
        self.observed_count += 1
        if self.observed_count > self.limits.max_events:
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_EVENT_LIMIT")
        self._check_scope()
        if (request.method != "POST" or request.resource_type not in {"xhr", "fetch"}
                or request.frame is not self.frame or request.frame.page is not self.page):
            raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_REQUEST_SCOPE_INVALID")
        return self._stamp()

    def _record(self, owner, kind, stamp, **extra):
        facts, issue = body_facts(owner, kind, self.limits.max_body_bytes)
        if issue:
            self._fail(issue)
        result = {"kind": kind, "sequence": self.observed_count, "observed_at": stamp.timestamp(),
                  "monotonic_offset_seconds": stamp.monotonic_seconds - self.started.monotonic_seconds,
                  "url": NATIVE_GATE_URL, "method": "POST", **facts, **extra}
        result["event_id"] = "native-gate-capture:" + canonical_digest(
            {"capture_id": self.capture_id, "capture_scope_sha256": canonical_digest(self.scope_facts), **result})
        self.events.append(result)
        return result

    def _observe(self, operation):
        if not self.active:
            return
        try:
            operation()
        except Exception as exc:
            reason = str(exc) if isinstance(exc, NativeGateCaptureError) else "NATIVE_GATE_CAPTURE_OBSERVATION_FAILED"
            self._fail(reason)

    def _on_request(self, request):
        def observe():
            stamp = self._event(request)
            if stamp is None:
                return
            if id(request) in self.requests:
                raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_DUPLICATE_REQUEST")
            self.request_count += 1
            item = self._record(request, "request", stamp)
            self.requests[id(request)] = {"request": request, "event": item, "response_seen": False}
        self._observe(observe)

    def _on_response(self, response):
        def observe():
            request = response.request
            stamp = self._event(request)
            if stamp is None:
                return
            self.response_count += 1
            source = self.requests.get(id(request))
            if source is None or source["request"] is not request:
                raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_ORPHAN_RESPONSE")
            if source["response_seen"]:
                raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_DUPLICATE_RESPONSE")
            source["response_seen"] = True
            if (response.url != NATIVE_GATE_URL or type(response.status) is not int
                    or not 100 <= response.status <= 599):
                raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_RESPONSE_INVALID")
            source.update(response=response, headers_at=stamp.timestamp(), finished=False)
            if not 200 <= response.status < 300:
                self._fail("NATIVE_GATE_CAPTURE_HTTP_NON_SUCCESS")
        self._observe(observe)

    def _on_request_finished(self, request):
        def observe():
            stamp = self._event(request)
            if stamp is None:
                return
            source = self.requests.get(id(request))
            if source is None or source["request"] is not request or "response" not in source:
                raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_ORPHAN_RESPONSE")
            if source["finished"]:
                raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_DUPLICATE_FINISH")
            source["finished"] = True
            self.finished_count += 1
            response = source["response"]
            self._record(response, "response", stamp, status=response.status, headers_observed_at=source["headers_at"],
                         request_event_id=source["event"]["event_id"])
        self._observe(observe)

    def _on_request_failed(self, request):
        def observe():
            if self._event(request) is not None:
                self.failed_count += 1
                self._fail("NATIVE_GATE_CAPTURE_REQUEST_FAILED")
        self._observe(observe)

    def close(self):
        if self.closed:
            return
        self.active = False
        try:
            self._check_scope()
            self.closed_stamp = self._stamp()
        except Exception as exc:
            self._fail(str(exc) if isinstance(exc, NativeGateCaptureError) else "NATIVE_GATE_CAPTURE_CLOSE_FAILED")
        for name, callback in self.listeners:
            try:
                remover = getattr(self.page, "remove_listener", None)
                if not callable(remover):
                    remover = getattr(self.page, "off", None)
                if not callable(remover):
                    raise NativeGateCaptureError("NATIVE_GATE_CAPTURE_LISTENER_REMOVAL_UNAVAILABLE")
                remover(name, callback)
                self.removed += 1
            except Exception:
                self._fail("NATIVE_GATE_CAPTURE_LISTENER_REMOVAL_FAILED")
        self.closed = True
        self.requests.clear()

    def snapshot(self):
        issues = set(self.issues)
        if self.active or not self.closed:
            issues.add("NATIVE_GATE_CAPTURE_WINDOW_OPEN")
        if self.registered != 4 or self.removed != 4:
            issues.add("NATIVE_GATE_CAPTURE_LISTENERS_INCOMPLETE")
        if self.request_count != 1 or self.response_count != 1:
            issues.add("NATIVE_GATE_CAPTURE_PAIR_NOT_UNIQUE")
        if self.finished_count != 1:
            issues.add("NATIVE_GATE_CAPTURE_BODY_NOT_FINISHED")
        complete = not issues and self.started is not None and self.closed_stamp is not None and len(self.events) == 2
        body = {"schema": "dxm.native_gate_capture.v1", "capture_id": self.capture_id,
            "scope": self.scope_facts, "capture_complete": complete, "causal_binding": "unbound",
            "causal_action": None, "response_semantics": "unreviewed", "gate_outcome": "unknown",
            "authorization_produced": False, "events": self.events, "issues": sorted(issues),
            "window": {"started_at": self.started.timestamp() if self.started else None,
                "closed_at": self.closed_stamp.timestamp() if self.closed_stamp else None,
                "registered_listener_count": self.registered, "removed_listener_count": self.removed},
            "counts": {"observed_events": self.observed_count, "requests": self.request_count,
                "responses": self.response_count, "finished_requests": self.finished_count,
                "failed_requests": self.failed_count}}
        return json.loads(json.dumps({**body, "capture_sha256": canonical_digest(body)}))

#!/usr/bin/env python3
"""Run the bounded USB-only, write-free BISCUIT BROM diagnostic."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path
from typing import Any, Callable

from serial.tools import list_ports

from common import Device
from diagnostic_protocol import (
    DIAG_READY_MAGIC,
    DiagnosticProtocol,
    ProtocolError,
    decode_init_report,
)
from load_payload import load_payload

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PAYLOAD = ROOT / "brom-payload" / "build" / "diagnostic.bin"
EXPECTED_DIAGNOSTIC_SIZE = 9988
EXPECTED_DIAGNOSTIC_SHA256 = "5da666f7290b5762fa88f2b248472551323aa0c7dd1e03de41034a46e137915d"

_INIT_STAGE_NAMES = {
    0: "NONE",
    1: "GO_IDLE",
    2: "SEND_OP_COND_PROBE",
    3: "SELECT_VOLTAGE",
    4: "SEND_OP_COND_READY",
    5: "ALL_SEND_CID",
    6: "SET_RELATIVE_ADDR",
    7: "SELECT_CARD",
}


class DiagnosticProbeError(RuntimeError):
    """Probe failure which preserves the safe partial JSON result."""

    def __init__(self, message: str, result: dict[str, Any]):
        super().__init__(message)
        self.result = result


def _validate_brom_port(
    port: str,
    enumerate_ports: Callable[[], list[Any]] = lambda: list(list_ports.comports()),
) -> None:
    ports = list(enumerate_ports())
    requested = [item for item in ports if item.device == port]
    if len(requested) != 1:
        raise RuntimeError(f"selected port {port} was not found exactly once")
    selected = requested[0]
    if selected.vid != 0x0E8D or selected.pid != 0x0003:
        raise RuntimeError(f"selected port {port} is not MediaTek BROM (0e8d:0003)")
    brom_ports = [item for item in ports if item.vid == 0x0E8D and item.pid == 0x0003]
    if len(brom_ports) != 1:
        raise RuntimeError(
            f"expected exactly one MediaTek BROM USB device, found {len(brom_ports)}"
        )


def _validate_payload(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RuntimeError(f"missing or unsafe diagnostic payload: {path}") from error
    try:
        size = os.fstat(descriptor).st_size
        if size != EXPECTED_DIAGNOSTIC_SIZE:
            raise RuntimeError(
                f"diagnostic payload size mismatch: expected {EXPECTED_DIAGNOSTIC_SIZE}, got {size}"
            )
        data = os.read(descriptor, EXPECTED_DIAGNOSTIC_SIZE + 1)
        if len(data) != EXPECTED_DIAGNOSTIC_SIZE:
            raise RuntimeError("diagnostic payload changed while reading")
    finally:
        os.close(descriptor)
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_DIAGNOSTIC_SHA256:
        raise RuntimeError(
            f"diagnostic payload digest mismatch: expected {EXPECTED_DIAGNOSTIC_SHA256}, got {digest}"
        )
    return data


def _write_private_result(path: Path, rendered: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as output:
            output.write(rendered)
            output.flush()
            os.fsync(output.fileno())
    finally:
        os.close(descriptor)


def _init_dict(report: Any) -> dict[str, int | str]:
    return {
        "msdc_cfg": report.msdc_cfg,
        "go_idle": report.go_idle,
        "send_op_cond_probe": report.send_op_cond_probe,
        "ocr": report.ocr,
        "select_voltage": report.select_voltage,
        "send_op_cond_ready": report.send_op_cond_ready,
        "rocr": report.rocr,
        "all_send_cid": report.all_send_cid,
        "set_relative_addr": report.set_relative_addr,
        "select_card": report.select_card,
        "first_failed_stage": report.first_failed_stage,
        "first_failed_stage_name": _INIT_STAGE_NAMES.get(
            report.first_failed_stage, "UNKNOWN"
        ),
    }


def _require_ok(label: str, response: Any, payload_length: int | None = None) -> bytes:
    if response.status != 0:
        raise RuntimeError(f"{label} failed with status {response.status}")
    if payload_length is not None and len(response.payload) != payload_length:
        raise RuntimeError(
            f"{label} returned {len(response.payload)} bytes, expected {payload_length}"
        )
    return response.payload


def run_readonly_probe(protocol: DiagnosticProtocol, *, timeout: float = 5.0) -> dict[str, Any]:
    hello = protocol.hello(timeout=timeout)
    init = decode_init_report(hello.payload)
    result: dict[str, Any] = {
        "schema": "libreecho-brom-readonly-diagnostic-v1",
        "phase": "default-user-area-sector0",
        "status": "INIT_FAILED" if hello.status else "RUNNING",
        "init": _init_dict(init),
    }
    if (hello.status == 0) != (init.first_failed_stage == 0):
        message = "contradictory initialization status {} and failed stage {}".format(
            hello.status, init.first_failed_stage
        )
        result.update({"status": "FAILED", "error": message})
        raise DiagnosticProbeError(message, result)
    if hello.status != 0:
        return result

    try:
        first = _require_ok(
            "read default sector 0",
            protocol.read_default_sector0(timeout=timeout),
            512,
        )
        if first[510:512] != b"\x55\xAA":
            raise RuntimeError("default sector 0 is missing the protective-MBR signature")
        second = _require_ok(
            "repeat default sector 0",
            protocol.read_default_sector0(timeout=timeout),
            512,
        )
        if second != first:
            raise RuntimeError("default sector 0 changed across repeat read")
    except (ProtocolError, RuntimeError) as error:
        message = str(error)
        result.update({"status": "FAILED", "error": message})
        raise DiagnosticProbeError(message, result) from error

    result.update({
        "status": "PASS_PHASE1",
        "default_sector_identity": "PROTECTIVE_MBR",
        "default_sector_repeat": "MATCH",
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase-1 USB diagnostic for LibreEcho MT8163/BISCUIT default sector 0"
    )
    parser.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    parser.add_argument("--port", required=True, help="exact MediaTek BROM USB CDC path")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute-phase1-hardware", action="store_true")
    args = parser.parse_args()

    if not args.execute_phase1_hardware:
        parser.error("hardware access requires --execute-phase1-hardware")
    try:
        payload = _validate_payload(args.payload)
        _validate_brom_port(args.port)
    except RuntimeError as error:
        parser.error(str(error))
    if args.timeout <= 0 or args.timeout > 60:
        parser.error("timeout must be greater than zero and at most 60 seconds")

    device = Device(args.port)
    if device.dev is None:
        raise RuntimeError("BROM USB transport did not open")
    device.dev.timeout = min(args.timeout, 1.0)
    device.dev.write_timeout = args.timeout
    device.handshake(max_attempts=max(1, int(args.timeout)))
    load_payload(
        device,
        payload,
        expected_marker=struct.pack(">I", DIAG_READY_MAGIC),
        wait_for_user=False,
    )

    try:
        result = run_readonly_probe(DiagnosticProtocol(device.dev), timeout=args.timeout)
    except DiagnosticProbeError as error:
        result = error.result
    except (ProtocolError, RuntimeError) as error:
        result = {
            "schema": "libreecho-brom-readonly-diagnostic-v1",
            "status": "FAILED",
            "error": str(error),
        }

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        _write_private_result(args.output, rendered)
    sys.stdout.write(rendered)
    return 0 if result["status"] == "PASS_PHASE1" else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Behavior tests for the bounded Phase-1 USB read probe."""
from __future__ import annotations

import pathlib
import struct
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))

from diagnostic_cli import (  # noqa: E402
    DiagnosticProbeError,
    _validate_brom_port,
    _validate_payload,
    _write_private_result,
    run_readonly_probe,
)
from diagnostic_protocol import PARTITION_UNKNOWN, Response  # noqa: E402


class PortInfo:
    def __init__(self, device: str, vid: int | None, pid: int | None):
        self.device = device
        self.vid = vid
        self.pid = pid


class FakeProtocol:
    def __init__(self, init_status: int = 0):
        self.calls: list[str] = []
        self.init_status = init_status
        self.read_status = 0
        self.first_failed_stage_override: int | None = None
        self.change_second_read = False
        self.user = bytearray(512)
        self.user[510:512] = b"\x55\xAA"

    def hello(self, timeout: float = 5.0) -> Response:
        self.calls.append("hello")
        first_failed_stage = (
            self.first_failed_stage_override
            if self.first_failed_stage_override is not None
            else (4 if self.init_status else 0)
        )
        report = struct.pack(
            ">IIIIIIIIIII",
            0x1000, 0, 0, 0x00FF8000, 0,
            self.init_status & 0xFFFFFFFF, 0, 0, 0, 0,
            first_failed_stage,
        )
        return Response(1, 0x9000, PARTITION_UNKNOWN, 0, self.init_status, report)

    def read_default_sector0(self, timeout: float = 5.0) -> Response:
        self.calls.append("read_default_sector0")
        payload = bytes(self.user)
        if self.change_second_read and self.calls.count("read_default_sector0") == 2:
            payload = bytes([payload[0] ^ 1]) + payload[1:]
        return Response(
            1,
            0x9001,
            PARTITION_UNKNOWN,
            0,
            self.read_status,
            payload if self.read_status == 0 else b"",
        )


class DiagnosticCliTests(unittest.TestCase):
    def test_probe_uses_only_two_default_sector_reads(self) -> None:
        protocol = FakeProtocol()
        result = run_readonly_probe(protocol)
        self.assertEqual(protocol.calls, [
            "hello",
            "read_default_sector0",
            "read_default_sector0",
        ])
        self.assertEqual(result["status"], "PASS_PHASE1")
        self.assertEqual(result["default_sector_identity"], "PROTECTIVE_MBR")
        self.assertEqual(result["default_sector_repeat"], "MATCH")
        self.assertFalse(any("sha256" in key.lower() for key in result))
        self.assertNotIn("sector_bytes", result)
        self.assertNotIn("cid", result)
        self.assertIn("all_send_cid", result["init"])

    def test_initialization_failure_stops_before_read(self) -> None:
        protocol = FakeProtocol(init_status=-110)
        result = run_readonly_probe(protocol)
        self.assertEqual(protocol.calls, ["hello"])
        self.assertEqual(result["status"], "INIT_FAILED")
        self.assertEqual(result["init"]["first_failed_stage"], 4)
        self.assertEqual(result["init"]["first_failed_stage_name"], "SEND_OP_COND_READY")

    def test_contradictory_success_and_failed_stage_is_rejected(self) -> None:
        protocol = FakeProtocol(init_status=0)
        protocol.first_failed_stage_override = 4
        with self.assertRaisesRegex(DiagnosticProbeError, "contradictory initialization"):
            run_readonly_probe(protocol)
        self.assertEqual(protocol.calls, ["hello"])

    def test_default_sector_identity_must_have_protective_mbr_signature(self) -> None:
        protocol = FakeProtocol()
        protocol.user[510:512] = b"\0\0"
        with self.assertRaisesRegex(DiagnosticProbeError, "default sector 0"):
            run_readonly_probe(protocol)

    def test_framed_read_error_preserves_initialization_report(self) -> None:
        protocol = FakeProtocol()
        protocol.read_status = -110
        with self.assertRaisesRegex(DiagnosticProbeError, "default sector 0.*-110") as caught:
            run_readonly_probe(protocol)
        self.assertEqual(protocol.calls, ["hello", "read_default_sector0"])
        self.assertEqual(caught.exception.result["status"], "FAILED")
        self.assertEqual(caught.exception.result["init"]["first_failed_stage_name"], "NONE")
        self.assertIn("-110", caught.exception.result["error"])

    def test_default_sector_must_repeat_byte_for_byte(self) -> None:
        protocol = FakeProtocol()
        protocol.change_second_read = True
        with self.assertRaisesRegex(DiagnosticProbeError, "changed across repeat read"):
            run_readonly_probe(protocol)

    def test_unreviewed_payload_digest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            payload = pathlib.Path(temporary) / "diagnostic.bin"
            payload.write_bytes(b"not the reviewed payload")
            with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
                _validate_payload(payload)

    def test_brom_port_requires_exact_mediatek_vid_pid(self) -> None:
        ports = [PortInfo("/dev/ttyACM0", 0x0E8D, 0x0003)]
        _validate_brom_port("/dev/ttyACM0", lambda: ports)

    def test_wrong_or_ambiguous_brom_port_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "not MediaTek BROM"):
            _validate_brom_port(
                "/dev/ttyACM0",
                lambda: [PortInfo("/dev/ttyACM0", 0x1234, 0x5678)],
            )
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            _validate_brom_port(
                "/dev/ttyACM0",
                lambda: [
                    PortInfo("/dev/ttyACM0", 0x0E8D, 0x0003),
                    PortInfo("/dev/ttyACM1", 0x0E8D, 0x0003),
                ],
            )

    def test_result_file_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = pathlib.Path(temporary) / "evidence" / "result.json"
            _write_private_result(result, "{}\n")
            self.assertEqual(result.stat().st_mode & 0o777, 0o600)
            self.assertEqual(result.read_text(encoding="utf-8"), "{}\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)

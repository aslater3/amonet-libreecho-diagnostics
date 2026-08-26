#!/usr/bin/env python3
"""Source/build contracts for the write-free BROM diagnostic payload."""
from __future__ import annotations

import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / "brom-payload" / "diagnostic.c"
HEADER = ROOT / "brom-payload" / "diagnostic_protocol.h"
MMC_C = ROOT / "brom-payload" / "drivers" / "mmc.c"
MMC_H = ROOT / "brom-payload" / "drivers" / "mmc.h"
SD_C = ROOT / "brom-payload" / "drivers" / "sd.c"
MAKEFILE = ROOT / "brom-payload" / "Makefile"
HOST = ROOT / "modules" / "diagnostic_protocol.py"
CLI = ROOT / "modules" / "diagnostic_cli.py"


class DiagnosticPayloadContractTests(unittest.TestCase):
    def test_diagnostic_has_only_read_only_command_handlers(self) -> None:
        source = PAYLOAD.read_text(encoding="utf-8")
        self.assertIn("DIAG_CMD_HELLO", source)
        self.assertIn("DIAG_CMD_READ_DEFAULT_SECTOR0", source)
        for forbidden in (
            "mmc_write(",
            "mmc_set_part(",
            "mmc_switch(",
            "mmc_write_blocks(",
            "mmc_rpmb_write(",
            "rpmb_write",
            "WDT_RST",
            "0x1001",
            "0x1003",
            "0x2001",
            "0x3000",
        ):
            self.assertNotIn(forbidden, source)

    def test_diagnostic_rejects_nonzero_read_argument(self) -> None:
        source = PAYLOAD.read_text(encoding="utf-8")
        self.assertRegex(source, r"argument\s*!=\s*0")

    def test_payload_has_finite_three_request_state_machine(self) -> None:
        source = PAYLOAD.read_text(encoding="utf-8")
        self.assertIn("while (state < 3)", source)
        self.assertIn("state = init_status == 0 ? 1 : 3", source)
        self.assertIn("prior_state == 1 ? 2 : 3", source)
        self.assertIn("accept no further commands", source)

    def test_initialization_is_reported_and_gates_storage_commands(self) -> None:
        source = PAYLOAD.read_text(encoding="utf-8")
        self.assertIn("mmc_init_diagnostic", source)
        self.assertIn("init_report->first_failed_stage", source)
        self.assertIn("send_init_report", source)
        self.assertRegex(source, r"if\s*\(init_status\s*!=\s*0\)")

    def test_usb_liveness_precedes_command_driven_mmc_initialization(self) -> None:
        source = PAYLOAD.read_text(encoding="utf-8")
        ready = source.index("send_word(DIAG_READY_MAGIC)")
        initialize = source.index("mmc_init_diagnostic")
        hello = source.index("case DIAG_CMD_HELLO")
        self.assertLess(ready, hello)
        self.assertLess(hello, initialize)

    def test_mmc_diagnostic_api_preserves_each_stage_status(self) -> None:
        header = MMC_H.read_text(encoding="utf-8")
        source = MMC_C.read_text(encoding="utf-8")
        self.assertIn("struct mmc_init_report", header)
        self.assertIn("int mmc_init_diagnostic", header)
        for field in (
            "go_idle",
            "send_op_cond_probe",
            "send_op_cond_ready",
            "all_send_cid",
            "set_relative_addr",
            "select_card",
            "first_failed_stage",
        ):
            self.assertIn(field, header)
            self.assertIn(field, source)
        self.assertIn("R1_STATUS(cmd->resp[0])", source)
        self.assertGreaterEqual(source.count("mmc_r1_error(&cmd)"), 3)
        self.assertNotIn("cid[0]", PAYLOAD.read_text(encoding="utf-8"))

    def test_diagnostic_build_bounds_command_busy_response_and_pio_polling(self) -> None:
        source = SD_C.read_text(encoding="utf-8")
        self.assertIn('"timer.h"', source)
        self.assertGreaterEqual(source.count("gpt4_timeout_elapsed"), 4)
        self.assertIn("LIBREECHO_READONLY_DIAGNOSTIC", source)

    def test_host_and_payload_protocol_constants_match(self) -> None:
        c_source = HEADER.read_text(encoding="utf-8")
        py_source = HOST.read_text(encoding="utf-8")
        c_values = dict(re.findall(r"#define\s+(DIAG_[A-Z0-9_]+)\s+(0x[0-9A-Fa-f]+|[0-9]+)", c_source))
        py_values = dict(re.findall(r"^(DIAG_[A-Z0-9_]+)\s*=\s*(0x[0-9A-Fa-f]+|[0-9]+)", py_source, re.MULTILINE))
        required = {
            "DIAG_PROTOCOL_VERSION",
            "DIAG_READY_MAGIC",
            "DIAG_REQUEST_MAGIC",
            "DIAG_RESPONSE_MAGIC",
            "DIAG_CMD_HELLO",
            "DIAG_CMD_READ_DEFAULT_SECTOR0",
            "DIAG_PARTITION_UNKNOWN",
        }
        self.assertTrue(required.issubset(c_values))
        self.assertEqual({name: int(c_values[name], 0) for name in required},
                         {name: int(py_values[name], 0) for name in required})

    def test_makefile_builds_separate_diagnostic_artifact(self) -> None:
        source = MAKEFILE.read_text(encoding="utf-8")
        self.assertIn("build/diagnostic.bin", source)
        self.assertIn("diagnostic.c", source)
        self.assertIn("diagnostic_protocol.h", source)

    def test_built_diagnostic_drops_unreachable_write_and_rpmb_code(self) -> None:
        subprocess.run(["make", "-C", str(ROOT / "brom-payload"), "diagnostic"], check=True,
                       stdout=subprocess.DEVNULL)
        symbols = subprocess.run(
            ["arm-none-eabi-nm", str(ROOT / "brom-payload" / "build" / "diagnostic.elf")],
            check=True, text=True, capture_output=True,
        ).stdout
        for forbidden in (
            " mmc_write",
            " mmc_set_part",
            " mmc_switch",
            " __mmc_switch",
            " mmc_rpmb_write",
            " mmc_rpmb_read",
            " mmc_erase",
            " derive_rpmb_key",
        ):
            self.assertNotIn(forbidden, symbols)

    def test_historical_libreecho_payload_identity_is_unchanged(self) -> None:
        import hashlib

        subprocess.run(["make", "-C", str(ROOT / "brom-payload"), "all"], check=True,
                       stdout=subprocess.DEVNULL)
        payload = (ROOT / "brom-payload" / "build" / "payload.bin").read_bytes()
        self.assertEqual(len(payload), 17676)
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "16ff2539761a85fe6eea0dcb461b3904bfd0f01c431b49010ebeb5fc2407e5e5",
        )

    def test_cli_pin_matches_built_diagnostic(self) -> None:
        import hashlib

        subprocess.run(["make", "-C", str(ROOT / "brom-payload"), "diagnostic"], check=True,
                       stdout=subprocess.DEVNULL)
        payload = (ROOT / "brom-payload" / "build" / "diagnostic.bin").read_bytes()
        host = CLI.read_text(encoding="utf-8")
        size_match = re.search(r"^EXPECTED_DIAGNOSTIC_SIZE = (\d+)$", host, re.MULTILINE)
        hash_match = re.search(
            r'^EXPECTED_DIAGNOSTIC_SHA256 = "([0-9a-f]{64})"$', host, re.MULTILINE
        )
        self.assertIsNotNone(size_match)
        self.assertIsNotNone(hash_match)
        assert size_match is not None and hash_match is not None
        expected_size = int(size_match.group(1))
        expected_hash = hash_match.group(1)
        self.assertEqual(len(payload), expected_size)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_hash)


if __name__ == "__main__":
    unittest.main(verbosity=2)

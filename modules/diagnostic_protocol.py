"""Framed host protocol for the write-free LibreEcho BROM diagnostic."""
from __future__ import annotations

import dataclasses
import struct
import time
from typing import Any

DIAG_PROTOCOL_VERSION = 1
DIAG_READY_MAGIC = 0x4C454431
DIAG_REQUEST_MAGIC = 0x4C455251
DIAG_RESPONSE_MAGIC = 0x4C455250
DIAG_CMD_HELLO = 0x9000
DIAG_CMD_READ_DEFAULT_SECTOR0 = 0x9001
DIAG_PARTITION_UNKNOWN = 0xFFFFFFFF

_RESPONSE_WORDS = 8
_RESPONSE_BYTES = _RESPONSE_WORDS * 4
_MAX_PAYLOAD = 4096


class ProtocolError(RuntimeError):
    """The diagnostic stream is incomplete, stale, or malformed."""


@dataclasses.dataclass(frozen=True)
class Response:
    sequence: int
    command: int
    selected_partition: int
    target: int
    status: int
    payload: bytes


@dataclasses.dataclass(frozen=True)
class InitReport:
    msdc_cfg: int
    go_idle: int
    send_op_cond_probe: int
    ocr: int
    select_voltage: int
    send_op_cond_ready: int
    rocr: int
    all_send_cid: int
    set_relative_addr: int
    select_card: int
    first_failed_stage: int


def _signed32(value: int) -> int:
    return value - (1 << 32) if value & 0x80000000 else value


def encode_request(sequence: int, command: int, argument: int = 0) -> bytes:
    if not 0 < sequence <= 0xFFFFFFFF:
        raise ProtocolError("sequence must be between 1 and 0xffffffff")
    return struct.pack(
        ">IIIII",
        DIAG_REQUEST_MAGIC,
        DIAG_PROTOCOL_VERSION,
        sequence,
        command & 0xFFFFFFFF,
        argument & 0xFFFFFFFF,
    )


def read_exact(stream: Any, size: int, timeout: float) -> bytes:
    if size < 0 or timeout <= 0:
        raise ProtocolError("invalid exact-read request")
    deadline = time.monotonic() + timeout
    result = bytearray()
    original_timeout = getattr(stream, "timeout", None)
    try:
        while len(result) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if hasattr(stream, "timeout"):
                stream.timeout = remaining
            chunk = stream.read(size - len(result))
            if chunk:
                result.extend(chunk)
    finally:
        if hasattr(stream, "timeout"):
            stream.timeout = original_timeout
    timed_out = time.monotonic() > deadline
    if len(result) != size or timed_out:
        raise ProtocolError(f"short response: expected {size} bytes, received {len(result)}")
    return bytes(result)


def read_response(
    stream: Any,
    expected_sequence: int,
    expected_command: int,
    *,
    timeout: float = 5.0,
) -> Response:
    deadline = time.monotonic() + timeout
    header = read_exact(stream, _RESPONSE_BYTES, timeout)
    magic, version, sequence, command, selected, target, status_word, payload_len = struct.unpack(
        ">IIIIIIII", header
    )
    if magic != DIAG_RESPONSE_MAGIC:
        raise ProtocolError(f"response magic mismatch: {magic:#x}")
    if version != DIAG_PROTOCOL_VERSION:
        raise ProtocolError(f"protocol version mismatch: {version}")
    if sequence != expected_sequence:
        raise ProtocolError(f"response sequence mismatch: expected {expected_sequence}, got {sequence}")
    if command != expected_command:
        raise ProtocolError(f"response command mismatch: expected {expected_command:#x}, got {command:#x}")
    if payload_len > _MAX_PAYLOAD:
        raise ProtocolError(f"response payload is too large: {payload_len}")
    remaining = deadline - time.monotonic()
    if payload_len and remaining <= 0:
        raise ProtocolError(f"short response: expected {payload_len} bytes, received 0")
    payload = read_exact(stream, payload_len, remaining) if payload_len else b""
    return Response(sequence, command, selected, target, _signed32(status_word), payload)


def decode_init_report(payload: bytes) -> InitReport:
    if len(payload) != 44:
        raise ProtocolError(f"initialization report must be 44 bytes, got {len(payload)}")
    words = list(struct.unpack(">IIIIIIIIIII", payload))
    for index in (1, 2, 4, 5, 7, 8, 9):
        words[index] = _signed32(words[index])
    return InitReport(*words)


class DiagnosticProtocol:
    """Sequence-bound diagnostic client; framing failure poisons the session."""

    def __init__(self, stream: Any):
        self.stream = stream
        self.sequence = 1
        self.desynchronized = False

    def exchange(self, command: int, argument: int = 0, *, timeout: float = 5.0) -> Response:
        if self.desynchronized:
            raise ProtocolError("diagnostic session is desynchronized")
        sequence = self.sequence
        request = encode_request(sequence, command, argument)
        try:
            written = self.stream.write(request)
            if written != len(request):
                raise ProtocolError(
                    f"short request write: expected {len(request)} bytes, wrote {written}"
                )
            response = read_response(
                self.stream,
                sequence,
                command,
                timeout=timeout,
            )
        except ProtocolError:
            self.desynchronized = True
            raise
        except Exception as error:
            self.desynchronized = True
            raise ProtocolError(f"diagnostic transport failed: {error}") from error
        self.sequence = 1 if sequence == 0xFFFFFFFF else sequence + 1
        return response

    def hello(self, *, timeout: float = 5.0) -> Response:
        return self.exchange(DIAG_CMD_HELLO, timeout=timeout)

    def read_default_sector0(self, *, timeout: float = 5.0) -> Response:
        return self.exchange(DIAG_CMD_READ_DEFAULT_SECTOR0, 0, timeout=timeout)

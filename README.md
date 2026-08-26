# amonet

This is an exploit chain for Echo Show 5 (2019) (1st gen / checkers / AEOCH). It contains a MediaTek bootrom exploit and a LittleKernel bootloader exploit.

For installation instructions, see https://xdaforums.com/t/unlock-root-twrp-unbrick-amazon-echo-show-5-1st-gen-2019-checkers.4762900/

## LibreEcho USB-only read diagnostic

The `feature/libreecho-usb-readonly-diagnostics` branch carries a separate
BROM payload for diagnosing MT8163/BISCUIT eMMC initialization and the repeated
`switch_boot0()` / sector-read failure. It is not an installer and has not been
accepted on hardware yet.

Build it with the same ARM bare-metal toolchain used by Amonet. The host side
requires the hash-pinned PySerial wheel listed in `requirements-host.txt`:

```sh
python3 -m pip install --require-hashes -r requirements-host.txt
make -C brom-payload clean
make -C brom-payload diagnostic
sha256sum brom-payload/build/diagnostic.bin
# expected: 5cc4d47ed3c9d83ad72a2db5a4f216d76f652dcebea91e9aa2a76c69b78c700e
```

Run only after reviewing the source and explicitly opting into Phase-1 hardware
access. The BROM exploit loader changes volatile controller/MMIO/RAM state to
load code, but this Phase-1 payload exposes no persistent-storage mutation or
partition-selection command:

```sh
python3 modules/diagnostic_cli.py \
  --port /dev/ttyACM0 \
  --execute-phase1-hardware \
  --output diagnostic-result.json
```

The Phase-1 payload exposes only two framed USB commands:

1. `HELLO`: initialize MMC once and return each stage status;
2. `READ_DEFAULT_SECTOR0`: read sector `0` from the default user-area selection.

The host runs `HELLO`, reads default sector 0 twice, requires a protective-MBR
signature, compares both reads byte-for-byte in memory, and stops. Phase 1 does
not select boot0 and does not execute eMMC `CMD6`/`EXT_CSD_PART_CONFIG`.

Results contain initialization statuses and structural/equality verdicts, not raw
sectors, sector fingerprints, CID, serial, MAC, RPMB, or other private device
identity. The diagnostic ELF is linked with section garbage collection; tests
require eMMC write, partition switch, RPMB, erase and RPMB-key routines to be
absent. Diagnostic-only GPT4 bounds cover command busy, response and PIO polling.

After saving the result, remove power. Do not launch the normal Amonet installer
in the same session. Boot0 diagnosis remains a separate Phase-2 design and is
not included because eMMC partition selection writes `EXT_CSD_PART_CONFIG`.

A separate TTL UART remains optional. It may be captured on a controlled local
bench to compare the existing low-level messages with the new USB statuses, but
public users must not need UART to diagnose the installer.

### Payload provenance

The LibreEcho baseline on this branch is Roger Ortiz's public
`R0rt1z2/amonet` `mt8163-checkers` lineage plus the recovered LibreEcho command
`0x4000`, which reads one 32-bit MMIO register. That baseline rebuilds the
historical 17,676-byte payload with SHA-256
`16ff2539761a85fe6eea0dcb461b3904bfd0f01c431b49010ebeb5fc2407e5e5`.
The new diagnostic is a separate artifact and does not replace it.

## License

`brom-payload` includes code from Linux kernel, and is therefore licensed under GPLv2.

`modules` is licensed under MIT.

See LICENSE.MIT and LICENSE.GPL2 for more details.

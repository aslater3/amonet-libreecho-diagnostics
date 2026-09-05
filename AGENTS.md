# amonet-libreecho-diagnostics — Agent instructions

This repository contains the amonet MediaTek bootrom/preloader exploit chain and
fastboot recovery tooling for supported Echo Show devices. Read `README.md`,
`.gitmodules`, and the relevant script/Makefile before non-trivial work. Treat
all device-facing behavior as safety-critical.

## Operating contract

- Complete the user's requested outcome within its intended scope. A fix or
  implementation request authorizes reversible local preparation, an isolated
  purpose-named branch/worktree, necessary in-scope edits, local commits, and appropriate
  host validation. A review, diagnosis, explanation, or plan does not authorize
  project edits.
- Ask only for a material decision, genuine scope expansion, or a separately
  gated action. Preserve separate authorization for pushing, pull requests,
  merging, publication, releases, rebooting, flashing, partition writes, and
  other hardware changes.
- Subject to higher-priority system/developer instructions and these project
  safety boundaries, the user's current request takes precedence over
  procedural skill defaults. If an instruction blocks the requested outcome,
  identify its file, quote the exact blocking text, explain the conflict, and
  finish independent authorized work instead of silently abandoning it.
- Delegate independent bounded research, review, or host-test analysis only when
  it improves the result. Give each worker disjoint write ownership and verify
  its findings before reporting success.
- Use concise plain language. Report the result, exact evidence, and remaining
  blockers; distinguish host checks from live-device and artifact evidence.

## Repository workflow

- The reviewed default branch is `mt8163-echo-show`. Start work from its fetched
  current tip in a purpose-named branch such as `docs/<purpose>`; do not assume
  that a branch name or local checkout is current.
- Before editing, verify repository root, branch, `HEAD`, upstream/default-branch
  relation, worktree registration, and porcelain status. Preserve unrelated
  changes; do not reset, stash, clean, or repurpose another worktree.
- The `pl-payload` and `idmetool` dependencies are Git submodules. Initialize
  them only when the requested host build needs them:

```bash
git submodule update --init --recursive
```

- The payload Makefile's actual host build is:

```bash
make -C brom-payload
```

It requires the declared `arm-none-eabi-*` toolchain and initialized
submodules. There is no repository-local test runner or CI workflow declared;
do not invent one. For changed shell scripts, use the bounded syntax check
`bash -n <changed-script>`. For changed Python modules, use
`python3 -m compileall -q modules` and report it as syntax evidence, not a
functional device test. Run `git diff --check` before committing.

## Hardware safety gates

Run the smallest meaningful checks that establish all requested acceptance
criteria, plus all applicable required checks. Broaden or repeat testing only
when changes, failures or unresolved risks justify it. Do not add tests that
merely mirror reversible low-impact implementation details. Bounded background
checks and temporary local test servers are permitted when needed for authorized
validation; stop temporary processes afterward. Report unrelated failures
without fixing them silently or treating incomplete evidence as success.

By default, do not connect to, reboot, unlock, flash, erase, downgrade, or write
any physical device. In particular, do not run `bootrom-step.sh`,
`boot-fastboot.sh`, `gpt-fix.sh`, `fastboot-step.sh`, `fastbrick.sh`, or the
corresponding packaged scripts for a documentation or host-build task. The
workflow includes BROM/EMMC/RPMB/GPT/partition writes and fastboot flashing;
source inspection or a successful host compile is not hardware evidence.

A separately authorized device operation must first establish the exact supported
model/codename and device identity, verify the matching payload/artifact hashes,
record a recoverable backup and live UART/USB evidence plan, and preserve the
script's fail-closed mismatch/read-only checks. Require an explicit confirmation
for the exact write/reboot scope, stop on identity or readback failure, and never
improvise a direct fastboot/BROM workaround. Keep hardware evidence separate from
source, host-build, and package evidence. Do not publish serials, MAC addresses,
private paths, credentials, or raw device manifests.

## Completion and publication gates

Record the exact commit tested and exact commands/results. A local commit is not
a push, pull request, merge, release publication, or hardware deployment. Those
actions require explicit authorization and the applicable review/release gates.
When a publication workflow is authorized, perform its required read-only
checks with bounded waits. Hardware actions retain their separate gates.

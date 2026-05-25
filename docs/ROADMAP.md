# Roadmap

## Phase 1 — Foundation (in progress)

- [x] Project scaffolding
- [ ] ADB wrapper + device fingerprinting (`aur.device`)
- [ ] Boot/recovery image pulling and unpacking (`aur.device.bootimg`)
- [ ] CLI (`aur fingerprint`, `aur extract-boot`)

## Phase 2 — Generators

- [ ] TWRP device tree generator (wrap `twrpdtgen`, post-process)
- [ ] OrangeFox device tree variant generator
- [ ] CLI (`aur generate --base {twrp,orangefox}`)
- [ ] Validation pass on generated tree (sanity checks, missing fields)

## Phase 3 — Hybrid build exporter

- [ ] Docker compose + Dockerfile templates for TWRP and OrangeFox build envs
- [ ] Step-by-step plain-text instructions (for manual / cloud VM builds)
- [ ] Verification checklist (matches device codename, partition layout, kernel)
- [ ] CLI (`aur export-build --docker | --plain | --cloud-vm`)

## Phase 4 — GUI

- [ ] PyQt6 wizard (Connect → Fingerprint → Generate → Export)
- [ ] Device detail viewer
- [ ] Build plan viewer with copy-to-clipboard
- [ ] Settings (output dir, recovery base preference)

## Phase 5 — Beyond TWRP/OrangeFox

- [x] Backup orchestrator with sha256 verification (`aur backup`)
- [x] Restore orchestrator with explicit confirm + dangerous-partition gating (`aur restore`)
- [x] Image flashing helper with post-write verify (`aur flash`)
- [x] Partition verification (`aur verify --sha256`)
- [x] Reboot to system/recovery/bootloader/fastboot (`aur reboot`)
- [ ] Scheduled / scripted backup workflows (batch_backup is the building block)
- [ ] OpenRecoveryScript queue mode (write `/cache/recovery/openrecoveryscript`,
      reboot to recovery, recovery runs the queue, reboots back)
- [ ] Device-tree diff tool (compare two devices to catch porting issues)
- [ ] GUI page for recovery ops (currently CLI-only)

## Known hard problems we're not solving (yet)

- Devices with **non-standard boot image formats** (e.g., some MediaTek chipsets with sparse logos / vendor headers) — these need per-SoC handling.
- **A/B with dynamic partitions** (super partition) — twrpdtgen has partial support; OrangeFox handles it better.
- **VAB / VAB-retrofit** devices — requires recovery-as-boot, different build flags.
- Kernel source acquisition is **out of scope** — most OEMs publish kernel sources late or not at all. The generated build plan tells the user where to look (LineageOS device repos, kernel.org if applicable, OEM kernel source releases).

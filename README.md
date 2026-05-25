<div align="center">

```
   █████╗ ██╗   ██╗██████╗
  ██╔══██╗██║   ██║██╔══██╗
  ███████║██║   ██║██████╔╝
  ██╔══██║██║   ██║██╔══██╗
  ██║  ██║╚██████╔╝██║  ██║
  ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝
   Android Universal Recovery
```

**Fingerprint a phone over ADB · Generate a TWRP or OrangeFox device tree · Hand off a Docker/Linux/Cloud-VM build plan**

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-alpha-orange.svg)](docs/ROADMAP.md)
[![Tests](https://img.shields.io/badge/tests-15%20passing-success.svg)](tests/)

</div>

---

## What this is

AUR is a desktop tool that **generates a custom recovery image build plan for a specific Android phone**. It pulls the device's identity over ADB, extracts and analyses its boot/recovery image, and emits a ready-to-build TWRP or OrangeFox device tree alongside a self-contained build plan (Docker, plain Linux, or a fresh Ubuntu VM).

Once you flash that recovery onto the phone — or while you're still booted to root — AUR also drives **host-side recovery operations**: backup, restore, flash, and verify partitions with end-to-end SHA-256 protection.

> **There is no truly "universal" recovery image.** Recoveries are tied to a device's kernel, SoC boot format (MediaTek / Qualcomm / Exynos / Unisoc), partition table, A/B vs legacy layout, dynamic-partition scheme, and touch/display drivers. TWRP and OrangeFox themselves ship a separate build per device for exactly this reason. AUR takes the only path that actually works: **identify the phone first, then generate a recovery tailored to it.**

---

## Highlights

| | |
|---|---|
| **Generator pipeline** | ADB fingerprint → boot/recovery extract → twrpdtgen-backed tree → Docker/plain/cloud-VM build plan |
| **Dual recovery** | Generate TWRP, OrangeFox, or both from one fingerprint |
| **Recovery ops** | `backup` · `restore` · `flash` · `verify` · `reboot`, all SHA-256 verified |
| **Safety rails** | Writes to `userdata` / `system` / `vendor` / `super` refused without `--allow-dangerous`; userdata wipe needs a literal confirmation phrase |
| **GUI + CLI** | PyQt6 sidebar app for guided use; full Click CLI for scripting and CI |
| **Hybrid build** | AUR doesn't compile AOSP itself — it generates everything the build needs and hands off to Docker / Linux / your VM, so macOS hosts work fine |

---

## Architecture

```
        ┌──────────────────────┐
        │   PyQt6 GUI    /     │
        │   `aur` CLI          │
        └──────────┬───────────┘
                   │
   ┌───────────────┼────────────────┬────────────────┐
   ▼               ▼                ▼                ▼
┌────────┐   ┌──────────┐   ┌─────────────┐   ┌──────────────┐
│ device │   │ generator│   │   builder   │   │ recovery_ops │
│        │   │          │   │             │   │              │
│ adb    │   │ twrp     │   │ docker      │   │ backup       │
│ finger-│   │ orange-  │   │ plain       │   │ restore      │
│ print  │   │ fox      │   │ cloud-vm    │   │ flash        │
│ parts  │   │          │   │             │   │ verify       │
│ bootimg│   │          │   │             │   │ reboot       │
└────┬───┘   └────┬─────┘   └──────┬──────┘   └──────┬───────┘
     │            │                │                  │
     ▼            ▼                ▼                  ▼
  ┌─────┐    ┌──────────┐   ┌──────────────┐   ┌──────────┐
  │ adb │    │twrpdtgen │   │  Dockerfile  │   │  adb     │
  │     │    │ (3.0+)   │   │  / scripts   │   │  shell   │
  └─────┘    └──────────┘   └──────────────┘   └──────────┘
```

Source layout:

```
src/aur/
├── cli.py              # Click CLI: devices/fingerprint/extract-boot/...
├── recovery_ops.py     # backup/restore/flash/verify (host-side)
├── device/             # ADB wrapper, fingerprint, partition map, boot image
├── generator/          # twrpdtgen wrapper + OrangeFox overlay
├── builder/            # Docker / plain / cloud-VM build plans
└── gui/                # PyQt6 sidebar app
    ├── app.py          # MainWindow shell
    ├── theme.py        # QSS palette
    ├── widgets.py      # Card, Pill, LogPane, DeviceCard, ...
    ├── sidebar.py
    ├── state.py        # shared AppState
    ├── pages.py        # Dashboard, Connect, Generate, RecoveryOps, Settings
    └── workers.py      # QThread-based background jobs
```

---

## Requirements

|                  | Minimum                                              |
|------------------|------------------------------------------------------|
| OS               | macOS or Linux                                       |
| Python           | 3.10+                                                |
| ADB              | Android Platform Tools on `PATH`                     |
| Phone            | USB debugging enabled; **root or unlocked bootloader** needed to pull boot/recovery |
| Build host       | Docker, a Linux box, or a Linux VM (~80 GB disk, ~16 GB RAM during build) |

AUR runs on your laptop. The AOSP build that produces the actual `recovery.img` happens on a Linux host (Docker, a real Linux machine, or a VM) — see the **Hybrid build** section below.

---

## Quick start

```bash
# 1. clone & install
git clone <this-repo> AndroidUniversalRecovery
cd AndroidUniversalRecovery
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[gui]"

# 2. plug in the phone, enable USB debugging, authorize this host
aur devices

# 3. fingerprint it
aur fingerprint                   # writes out/<codename>/fingerprint.json

# 4. pull and unpack the recovery image (needs root)
aur extract-boot --kind recovery

# 5. generate device trees for TWRP + OrangeFox
aur generate --base both \
    --fingerprint-file out/<codename>/fingerprint.json \
    --image           out/<codename>/recovery.img

# 6. export a Docker build plan
aur export-build --base twrp --mode docker \
    --tree out/<codename>/trees/twrp/<vendor>/<codename>

# 7. (on a Linux box / Docker / VM) run the plan
cd build-plan && ./build.sh
```

Or skip the CLI and use the GUI:

```bash
aur-gui
```

---

## The GUI

A sidebar-driven PyQt6 app with a dark Catppuccin-inspired theme. Five pages:

| Page                 | What it does                                                                      |
|----------------------|-----------------------------------------------------------------------------------|
| **Dashboard**        | At-a-glance device summary; shortcut cards to the main workflows                  |
| **Connect**          | List ADB devices, pick one, fingerprint it                                        |
| **Generate recovery**| Extract → generate (TWRP / OrangeFox / both) → export build plan, all on one page |
| **Backup / Restore / Flash** | Host-side recovery ops with confirm-before-write and SHA-256 verification |
| **Settings**         | Output paths and defaults                                                         |

Visual style (rendered with Qt stylesheets, no images required):

```
┌──────────────┬───────────────────────────────────────────────┐
│  AUR         │   Dashboard                                    │
│  Android UR  │   Connect a device, then drive the generator…  │
│              │   ┌─────────────────────────────────────────┐  │
│  DEVICE      │   │  xiaomi / vayu                          │  │
│  ▣ Dashboard │   │  POCO X3 Pro · Android 12 · sm6150      │  │
│  ◆ Connect   │   │  [A/B]  [Dynamic Parts]  [Treble]  ...  │  │
│              │   └─────────────────────────────────────────┘  │
│  BUILD       │                                                │
│  ◆ Generate  │   ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│              │   │ Generate │  │ Recovery │  │ Connect  │    │
│  RECOVERY    │   │ recovery │  │   ops    │  │  other   │    │
│  ◆ Backup/…  │   │  [Start] │  │  [Open]  │  │ [Devices]│    │
│              │   └──────────┘  └──────────┘  └──────────┘    │
│  OTHER       │                                                │
│  ◆ Settings  │                                                │
├──────────────┴───────────────────────────────────────────────┤
│  ADB: 1 ONLINE   |   FP: vayu   |   out: ~/AUR_out           │
└──────────────────────────────────────────────────────────────┘
```

Status bar (bottom) shows live ADB state, current fingerprint, and the output directory.

---

## Hybrid build (why AUR doesn't compile recoveries itself)

Compiling a TWRP/OrangeFox image needs:

- ~50 GB of AOSP source (synced via `repo`)
- ~30 GB of build output
- 16+ GB of RAM during the link phase
- Linux with case-sensitive `ext4`
- 1–3 hours per build

That's a poor fit for a desktop generator. So AUR **separates concerns**: the generator runs on your laptop and produces a complete, portable device tree + build plan. The actual build runs wherever you have the resources.

| Mode      | What AUR writes                                       | Where you run it                              |
|-----------|--------------------------------------------------------|-----------------------------------------------|
| `docker`  | `Dockerfile` + `docker-compose.yml` + `build.sh`       | Docker Desktop / Docker Engine                |
| `plain`   | `BUILD.md` with copy-paste commands                    | An existing Linux machine                     |
| `cloud-vm`| `provision.sh` + `build.sh` + tree bundled for `scp`   | A fresh Ubuntu 22.04 VM (recommended ≥16 vCPU)|

After a successful build the output is at `out/target/product/<codename>/recoveryimage.img` (or `bootimage.img` on A/B+VAB devices).

---

## CLI reference

```
aur devices                                  # list connected adb devices
aur fingerprint                              # pull device info to ./out/<codename>/
aur extract-boot --kind recovery|boot|…      # pull and unpack a boot-class image
aur generate     --base twrp|orangefox|both  # generate device tree(s)
aur export-build --base twrp|orangefox       # render build plan
                 --mode docker|plain|cloud-vm

# Recovery operations (need root or a custom recovery on the device):
aur backup  -p boot -p recovery --out backups/
aur restore -p boot --image backups/boot.img    [--allow-dangerous] [--yes]
aur flash   --kind recovery --image my.img      [--yes]
aur verify  -p boot --sha256 <hex>
aur reboot  system|recovery|bootloader|fastboot
```

Add `--help` to any subcommand for the full option list.

---

## Safety

Custom recoveries are powerful and easy to misuse. AUR refuses by default whenever it can:

- `aur restore` and `aur flash` require explicit interactive confirmation (or `--yes`).
- Writes to `userdata`, `system`, `system_*`, `vendor`, `vendor_*`, `super`, `metadata`, `persist`, modem, NVRAM, MTK protect-fs partitions are refused unless `--allow-dangerous` is passed.
- `userdata` cannot be erased via `restore` or `wipe` — the API exposes a separate `format_userdata` that requires the literal phrase `"ERASE USERDATA"`, so the destructiveness is visible at every call site.
- Every write is SHA-256 verified against the local file after completion.

You are still responsible for verifying the generated artifacts before flashing. The generated build plan includes a per-device checklist (`AUR_NOTES.md`).

---

## Status

Alpha. Generator pipeline and recovery ops are implemented and tested; some niche device classes (MediaTek SoCs with vendor-auth boot images, VAB-retrofit, recovery-as-boot edge cases) still need hand-review of the generated tree. See [docs/ROADMAP.md](docs/ROADMAP.md) for the full picture.

---

## License

GPL-3.0-or-later. AUR wraps [`twrpdtgen`](https://github.com/twrpdtgen/twrpdtgen) (MIT) and uses TWRP and OrangeFox manifests at build time — credit to those projects for the underlying work.

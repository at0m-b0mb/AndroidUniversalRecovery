"""Plain-text BUILD.md renderer — for users who want to run the steps by hand
on an existing Linux box rather than wrap them in Docker.
"""

from __future__ import annotations

from pathlib import Path

from aur.builder._common import load_tree_info, write


TEMPLATE = """\
# Build plan (manual) — {base} for {vendor}/{codename}

> Run these on a Linux machine (Ubuntu 22.04 recommended). macOS hosts
> **must** use the Docker plan instead — AOSP needs case-sensitive ext4
> and Linux-only build deps.

## 1. Install dependencies (one-time)

```bash
sudo apt-get update
sudo apt-get install -y bc bison build-essential ccache cpio curl flex git \\
    gnupg gperf imagemagick lib32readline-dev lib32z1-dev libelf-dev \\
    liblz4-tool libncurses5 libsdl1.2-dev libssl-dev libxml2 libxml2-utils \\
    lzop openjdk-11-jdk-headless pngcrush python3 rsync schedtool \\
    squashfs-tools unzip wget xsltproc zip zlib1g-dev
```

## 2. Get `repo`

```bash
mkdir -p ~/bin
curl -fsSL https://storage.googleapis.com/git-repo-downloads/repo -o ~/bin/repo
chmod a+x ~/bin/repo
export PATH=~/bin:$PATH
```

## 3. Sync the source

```bash
mkdir -p ~/{base}-{codename} && cd ~/{base}-{codename}
repo init -u {manifest_url} -b {manifest_branch} --depth=1
repo sync -c -j$(nproc) --force-sync --no-clone-bundle --no-tags
```

This takes 30–90 minutes and ~30 GB.

## 4. Drop in the generated device tree

```bash
mkdir -p {device_tree_subpath}
rsync -a <path-to-this-tree>/ {device_tree_subpath}/
```

## 5. Build

```bash
source build/envsetup.sh
lunch {lunch_combo}
mka {build_target}
```

Output: `out/target/product/{codename}/{build_target}.img`.

## 6. Verify before flashing

- [ ] The output image is non-zero and at least a few MB.
- [ ] `file out/target/product/{codename}/{build_target}.img` shows
      "Android bootimg" or similar.
- [ ] `unpackbootimg -i <image>` extracts a kernel matching this device.
- [ ] Bootloader is unlocked on the target phone.
- [ ] You have a working stock recovery image to fall back to.

## 7. Flash (fastboot)

```bash
adb reboot bootloader
fastboot flash recovery out/target/product/{codename}/{build_target}.img
fastboot reboot
```

For A/B devices you may need `fastboot flash recovery_a` and `recovery_b`,
or boot the image temporarily with `fastboot boot` before flashing.
"""


def render_plain_plan(*, tree_dir: Path, base: str, out_dir: Path) -> None:
    info = load_tree_info(tree_dir, base)
    write(
        out_dir / "BUILD.md",
        TEMPLATE.format(
            base=info.base,
            vendor=info.vendor,
            codename=info.codename,
            manifest_url=info.manifest_url,
            manifest_branch=info.manifest_branch,
            lunch_combo=info.lunch_combo,
            build_target=info.build_target,
            device_tree_subpath=info.device_tree_subpath,
        ),
    )

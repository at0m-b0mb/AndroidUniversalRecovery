"""Cloud-VM build plan: a pair of scripts you can scp to a fresh Ubuntu VM.

provision.sh installs deps + repo; build.sh does the sync and the build.
The split lets users snapshot the VM after provisioning to skip ~5 min on
future builds.
"""

from __future__ import annotations

from pathlib import Path

from aur.builder._common import load_tree_info, write


PROVISION_SH = """\
#!/usr/bin/env bash
# AUR cloud-VM provisioner. Run once on a fresh Ubuntu 22.04 instance.
# Recommended: 16 vCPU / 32 GB RAM / 200 GB SSD.
set -euo pipefail

sudo apt-get update
sudo apt-get install -y bc bison build-essential ccache cpio curl flex git \\
    gnupg gperf imagemagick lib32readline-dev lib32z1-dev libelf-dev \\
    liblz4-tool libncurses5 libsdl1.2-dev libssl-dev libxml2 libxml2-utils \\
    lzop openjdk-11-jdk-headless pngcrush python3 rsync schedtool \\
    squashfs-tools unzip wget xsltproc zip zlib1g-dev tmux htop

mkdir -p "$HOME/bin"
curl -fsSL https://storage.googleapis.com/git-repo-downloads/repo -o "$HOME/bin/repo"
chmod a+x "$HOME/bin/repo"
grep -q 'export PATH=$HOME/bin:$PATH' "$HOME/.bashrc" \\
    || echo 'export PATH=$HOME/bin:$PATH' >> "$HOME/.bashrc"

git config --global user.email "aur@example.com"
git config --global user.name "AUR Builder"
git config --global color.ui false

echo "[ok] provisioning done. Snapshot the VM now, then run build.sh."
"""

BUILD_SH = """\
#!/usr/bin/env bash
# AUR cloud-VM builder for {base} {codename}.
# Expects ./tree/ next to this script with the generated device tree.
set -euo pipefail
export PATH="$HOME/bin:$PATH"

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$HOME/{base}-{codename}"

mkdir -p "$WORK"
cd "$WORK"

if [ ! -d .repo ]; then
  repo init -u {manifest_url} -b {manifest_branch} --depth=1
fi
repo sync -c -j"$(nproc)" --force-sync --no-clone-bundle --no-tags

mkdir -p {device_tree_subpath}
rsync -a --delete "$HERE/tree/" {device_tree_subpath}/

source build/envsetup.sh
lunch {lunch_combo}
mka {build_target}

OUT="out/target/product/{codename}/{build_target}.img"
echo
echo "[ok] build complete: $WORK/$OUT"
ls -lh "$OUT"
"""

README = """\
# Cloud-VM build plan — {base} for {vendor}/{codename}

## One-time

1. Spin up an Ubuntu 22.04 VM (≥16 vCPU, ≥32 GB RAM, ≥200 GB disk).
2. `scp -r ./build-plan/ ubuntu@<vm>:~/aur/`
3. `ssh ubuntu@<vm>` then:
   ```
   cd ~/aur/build-plan
   ./provision.sh
   ```
4. (Optional) snapshot the VM image.

## Each build

```
cd ~/aur/build-plan
tmux new -s aur                  # detach-friendly session
./build.sh
```

Output ends up at `~/{base}-{codename}/out/target/product/{codename}/{build_target}.img`.

`scp` it back to your local machine and verify before flashing.
"""


def render_cloud_vm_plan(*, tree_dir: Path, base: str, out_dir: Path) -> None:
    from aur.builder._common import write  # local re-import for clarity
    info = load_tree_info(tree_dir, base)
    ctx = dict(
        base=info.base,
        vendor=info.vendor,
        codename=info.codename,
        manifest_url=info.manifest_url,
        manifest_branch=info.manifest_branch,
        lunch_combo=info.lunch_combo,
        build_target=info.build_target,
        device_tree_subpath=info.device_tree_subpath,
    )
    write(out_dir / "provision.sh", PROVISION_SH, executable=True)
    write(out_dir / "build.sh", BUILD_SH.format(**ctx), executable=True)
    write(out_dir / "README.md", README.format(**ctx))
    # Copy the tree alongside the scripts so scp ships everything in one go.
    import shutil
    tree_dest = out_dir / "tree"
    if tree_dest.exists():
        shutil.rmtree(tree_dest)
    shutil.copytree(tree_dir, tree_dest)

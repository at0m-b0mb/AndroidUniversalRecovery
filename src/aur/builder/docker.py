"""Docker build plan renderer.

Produces a self-contained ``build-plan/`` directory the user can ``cd`` into
and run ``./build.sh`` from. The plan uses a TWRP/OrangeFox-friendly base
image with the right JDK and lunch dependencies already in place.
"""

from __future__ import annotations

from pathlib import Path

from aur.builder._common import TreeInfo, load_tree_info, write


DOCKERFILE = """\
# AUR-generated builder for {base} {codename}
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \\
    LANG=C.UTF-8 \\
    LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \\
    bc bison build-essential ca-certificates ccache cpio curl flex git \\
    git-lfs gnupg gperf imagemagick lib32readline-dev lib32z1-dev libelf-dev \\
    liblz4-tool libncurses5 libsdl1.2-dev libssl-dev libxml2 libxml2-utils \\
    lzop openjdk-11-jdk-headless pngcrush python3 python3-pip rsync schedtool \\
    squashfs-tools sudo unzip wget xsltproc zip zlib1g-dev \\
    && rm -rf /var/lib/apt/lists/*

# Drop privileges to a builder user — AOSP refuses to build as root.
RUN useradd -ms /bin/bash builder \\
    && echo "builder ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
USER builder
WORKDIR /home/builder

RUN git config --global user.email "aur@example.com" \\
    && git config --global user.name "AUR Builder" \\
    && git config --global color.ui false

# Fetch `repo` — Android's source manager.
RUN mkdir -p /home/builder/bin \\
    && curl -fsSL https://storage.googleapis.com/git-repo-downloads/repo \\
       -o /home/builder/bin/repo \\
    && chmod a+x /home/builder/bin/repo
ENV PATH="/home/builder/bin:$PATH"

CMD ["/bin/bash"]
"""

COMPOSE = """\
# AUR-generated compose for {base} {codename}
services:
  builder:
    build: .
    image: aur-{base}-builder:{codename}
    container_name: aur-{base}-{codename}
    working_dir: /home/builder/work
    volumes:
      - ./work:/home/builder/work
      - ./tree:/home/builder/tree:ro
    tty: true
    stdin_open: true
    shm_size: "2gb"
    ulimits:
      nofile: 65536
"""

BUILD_SH = """\
#!/usr/bin/env bash
# AUR-generated build driver for {base} {codename}.
# Usage:
#   ./build.sh        # full build (sync + lunch + make)
#   ./build.sh sync   # just sync the manifest
#   ./build.sh make   # skip sync, only run the build
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

MANIFEST_URL="{manifest_url}"
MANIFEST_BRANCH="{manifest_branch}"
LUNCH_COMBO="{lunch_combo}"
BUILD_TARGET="{build_target}"
DEVICE_TREE_SUBPATH="{device_tree_subpath}"

mkdir -p work tree
# Sync the tree into a read-only mount so the container can copy it into
# the source tree under device/{vendor}/{codename}.
rsync -a --delete "$HERE/../" tree/  # generated device tree lives one level up

docker compose build builder

action="${{1:-all}}"

run_in_container() {{
  docker compose run --rm builder bash -lc "$1"
}}

if [[ "$action" == "all" || "$action" == "sync" ]]; then
  run_in_container "
    cd /home/builder/work
    [ -d .repo ] || repo init -u $MANIFEST_URL -b $MANIFEST_BRANCH --depth=1
    repo sync -c -j\"$(nproc)\" --force-sync --no-clone-bundle --no-tags
  "
fi

if [[ "$action" == "all" || "$action" == "make" ]]; then
  run_in_container "
    set -e
    cd /home/builder/work
    mkdir -p $DEVICE_TREE_SUBPATH
    cp -a /home/builder/tree/. $DEVICE_TREE_SUBPATH/
    source build/envsetup.sh
    lunch $LUNCH_COMBO
    mka $BUILD_TARGET
  "
  echo
  echo \"[ok] build complete. Look for $BUILD_TARGET under work/out/target/product/{codename}/\"
fi
"""

README = """\
# Build plan — {base} for {vendor}/{codename}

This directory contains everything needed to build the {base} recovery
image for `{codename}` inside Docker.

## Prerequisites
- Docker Desktop (or Docker Engine + Compose v2)
- ~80 GB free disk, ~16 GB RAM
- Patience: first build is 1–3 hours depending on host

## Run

```
./build.sh           # one shot: sync + build
./build.sh sync      # only sync the AOSP manifest
./build.sh make      # only run lunch + make (assumes sync is done)
```

## What gets produced
After a successful build:
- `work/out/target/product/{codename}/{build_target}.img`

Verify it before flashing — see `../AUR_NOTES.md` in the device tree for
the per-device checklist.

## If the build fails
Most failures fall into a few buckets:
1. **Missing kernel source** — the device tree may reference a kernel path
   that doesn't exist in the synced manifest. Add a `kernel/{vendor}/{codename}`
   submodule (LineageOS / OEM source release) and re-run `./build.sh make`.
2. **`fstab` / `BoardConfig` mismatches** — check the per-device notes in
   the tree's `AUR_NOTES.md`.
3. **Disk full** — the AOSP source tree is ~50 GB; the output adds another
   20–30 GB.
"""


def render_docker_plan(*, tree_dir: Path, base: str, out_dir: Path) -> None:
    info = load_tree_info(tree_dir, base)
    ctx = dict(
        base=info.base,
        codename=info.codename,
        vendor=info.vendor,
        manifest_url=info.manifest_url,
        manifest_branch=info.manifest_branch,
        lunch_combo=info.lunch_combo,
        build_target=info.build_target,
        device_tree_subpath=info.device_tree_subpath,
    )
    write(out_dir / "Dockerfile", DOCKERFILE.format(**ctx))
    write(out_dir / "docker-compose.yml", COMPOSE.format(**ctx))
    write(out_dir / "build.sh", BUILD_SH.format(**ctx), executable=True)
    write(out_dir / "README.md", README.format(**ctx))

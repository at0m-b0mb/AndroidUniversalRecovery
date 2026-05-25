"""Hybrid build exporter.

AUR generates the device tree locally; the actual recovery build happens
elsewhere (Docker, Linux box, or cloud VM). This module renders one of three
build plans next to the generated tree:

  - docker:   Dockerfile + docker-compose + build.sh
  - plain:    BUILD.md with copy-paste commands
  - cloud-vm: provision.sh + build.sh designed for a fresh Ubuntu VM
"""

from __future__ import annotations

from pathlib import Path

from aur.builder.docker import render_docker_plan
from aur.builder.plain import render_plain_plan
from aur.builder.cloud_vm import render_cloud_vm_plan

_RENDERERS = {
    "docker": render_docker_plan,
    "plain": render_plain_plan,
    "cloud-vm": render_cloud_vm_plan,
}


def export_build_plan(*, tree_dir: Path, base: str, mode: str, out_dir: Path) -> Path:
    """Render a build plan for ``base`` (twrp|orangefox) in ``mode`` form."""
    if base not in ("twrp", "orangefox"):
        raise ValueError(f"unknown base: {base!r}")
    if mode not in _RENDERERS:
        raise ValueError(f"unknown mode: {mode!r}")

    out_dir.mkdir(parents=True, exist_ok=True)
    _RENDERERS[mode](tree_dir=tree_dir, base=base, out_dir=out_dir)
    return out_dir


__all__ = ["export_build_plan"]

"""Device-tree generation for TWRP and OrangeFox.

The public entrypoint is :func:`generate_tree`. Internally it always runs
the TWRP path (via twrpdtgen) and then, for OrangeFox, applies a thin
overlay on top of the TWRP tree.
"""

from __future__ import annotations

from pathlib import Path

from aur.device.fingerprint import DeviceFingerprint
from aur.generator.orangefox import orangefox_overlay
from aur.generator.twrp import generate_twrp_tree


def generate_tree(
    *,
    fp: DeviceFingerprint,
    image: Path,
    base: str,
    out_root: Path,
) -> dict[str, Path]:
    """Generate one or both device trees.

    Returns a mapping of base -> tree path. Always generates the TWRP tree
    first since the OrangeFox variant is an overlay on top of it.
    """
    if base not in {"twrp", "orangefox", "both"}:
        raise ValueError(f"unknown base: {base!r}")

    out_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, Path] = {}

    twrp_dir = generate_twrp_tree(fp=fp, image=image, out_root=out_root)
    if base in ("twrp", "both"):
        results["twrp"] = twrp_dir
    if base in ("orangefox", "both"):
        of_dir = orangefox_overlay(fp=fp, twrp_tree=twrp_dir, out_root=out_root)
        results["orangefox"] = of_dir
    return results


__all__ = ["generate_tree", "generate_twrp_tree", "orangefox_overlay"]

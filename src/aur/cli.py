"""AUR command-line interface.

Subcommands:
  devices         list connected adb devices
  fingerprint     pull device info -> out/<codename>/fingerprint.json
  extract-boot    pull and unpack boot.img / recovery.img
  generate        generate TWRP/OrangeFox device tree from fingerprint
  export-build    write a build plan for the chosen base
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from aur.device.adb import ADB, ADBError, NoDeviceError
from aur.device.bootimg import pull_image, unpack_image
from aur.device.fingerprint import DeviceFingerprint, fingerprint_device

console = Console()


def _default_out() -> Path:
    return Path.cwd() / "out"


def _select_adb(serial: str | None) -> ADB:
    """Build an ADB handle, surfacing useful errors."""
    try:
        adb = ADB(serial=serial)
    except ADBError as e:
        console.print(f"[red]error:[/] {e}")
        sys.exit(2)

    devices = ADB.list_devices()
    online = [d for d in devices if d.state == "device"]
    if not online and not adb.in_recovery():
        recoveries = [d for d in devices if d.state == "recovery"]
        if not recoveries:
            console.print(
                "[yellow]no authorized device found.[/] "
                "Connect a phone with USB debugging enabled and authorize this host."
            )
            sys.exit(1)
    return adb


@click.group()
@click.option("--serial", "-s", default=None, help="Target a specific adb device serial.")
@click.pass_context
def main(ctx: click.Context, serial: str | None) -> None:
    """Android Universal Recovery (AUR) — generator CLI."""
    ctx.ensure_object(dict)
    ctx.obj["serial"] = serial


@main.command()
def devices() -> None:
    """List connected adb devices."""
    try:
        devs = ADB.list_devices()
    except ADBError as e:
        console.print(f"[red]error:[/] {e}")
        sys.exit(2)

    if not devs:
        console.print("[yellow]no devices connected.[/]")
        return
    t = Table(title="ADB devices")
    t.add_column("serial")
    t.add_column("state")
    for d in devs:
        t.add_row(d.serial, d.state)
    console.print(t)


@main.command()
@click.option("--out", "out_dir", type=click.Path(path_type=Path), default=None,
              help="Output directory root (default: ./out).")
@click.pass_context
def fingerprint(ctx: click.Context, out_dir: Path | None) -> None:
    """Pull device info and write fingerprint.json."""
    adb = _select_adb(ctx.obj.get("serial"))
    try:
        fp = fingerprint_device(adb)
    except NoDeviceError as e:
        console.print(f"[red]no device:[/] {e}")
        sys.exit(1)
    except ADBError as e:
        console.print(f"[red]adb error:[/] {e}")
        sys.exit(2)

    base = (out_dir or _default_out()) / fp.codename
    fp_path = base / "fingerprint.json"
    fp.save_json(fp_path)

    t = Table(title=f"Device: {fp.manufacturer}/{fp.codename}", show_header=False)
    t.add_row("Brand / Model", f"{fp.brand} / {fp.model}")
    t.add_row("Platform", fp.platform)
    t.add_row("Arch", fp.arch)
    t.add_row("Android", f"{fp.android_release} (sdk {fp.android_sdk})")
    t.add_row("A/B", "yes" if fp.is_ab else "no")
    t.add_row("Dynamic partitions", "yes" if fp.has_dynamic_partitions else "no")
    t.add_row("Treble", "yes" if fp.is_treble else "no")
    t.add_row("Rooted", "yes" if fp.rooted else "no")
    t.add_row("Partitions found", str(len(fp.partitions)))
    t.add_row("Saved to", str(fp_path))
    console.print(t)


@main.command("extract-boot")
@click.option("--kind", type=click.Choice(["boot", "recovery", "vendor_boot", "init_boot"]),
              default="recovery", help="Which image to pull.")
@click.option("--out", "out_dir", type=click.Path(path_type=Path), default=None)
@click.option("--fingerprint-file", type=click.Path(path_type=Path, exists=True), default=None,
              help="Reuse a previously saved fingerprint.json instead of re-fingerprinting.")
@click.option("--image", type=click.Path(path_type=Path, exists=True), default=None,
              help="Skip pulling; use this local image file instead.")
@click.pass_context
def extract_boot(
    ctx: click.Context,
    kind: str,
    out_dir: Path | None,
    fingerprint_file: Path | None,
    image: Path | None,
) -> None:
    """Pull a boot-class image off the device and unpack it."""
    base_out = out_dir or _default_out()

    if image:
        # Manual mode: user gave us the image.
        codename = "manual"
        target_dir = base_out / codename / f"{kind}-extracted"
        unpacked = unpack_image(image, target_dir)
        _report_unpacked(unpacked)
        return

    if fingerprint_file:
        fp = DeviceFingerprint.load_json(fingerprint_file)
        adb = _select_adb(ctx.obj.get("serial"))
    else:
        adb = _select_adb(ctx.obj.get("serial"))
        fp = fingerprint_device(adb)

    target_root = base_out / fp.codename
    try:
        pulled = pull_image(adb, fp, kind, target_root)
    except ADBError as e:
        console.print(f"[red]could not pull {kind}.img:[/] {e}")
        sys.exit(2)

    console.print(f"[green]pulled[/] {pulled.local_path} (from {pulled.source_path})")

    unpacked = unpack_image(pulled.local_path, target_root / f"{kind}-extracted")
    _report_unpacked(unpacked)


def _report_unpacked(u) -> None:
    t = Table(title=f"Unpacked {u.image_path.name}", show_header=False)
    t.add_row("Output dir", str(u.out_dir))
    t.add_row("Header version", str(u.header_version) if u.header_version is not None else "?")
    t.add_row("Kernel", str(u.kernel) if u.kernel else "(missing)")
    t.add_row("Ramdisk", str(u.ramdisk) if u.ramdisk else "(missing)")
    t.add_row("DTB", str(u.dtb) if u.dtb else "(none)")
    console.print(t)


@main.command()
@click.option("--base", type=click.Choice(["twrp", "orangefox", "both"]), default="twrp",
              help="Which recovery base to generate a device tree for.")
@click.option("--fingerprint-file", type=click.Path(path_type=Path, exists=True), default=None,
              help="Use a saved fingerprint.json (skip live device read).")
@click.option("--image", type=click.Path(path_type=Path, exists=True), required=True,
              help="Path to a recovery.img or boot.img to base generation on.")
@click.option("--out", "out_dir", type=click.Path(path_type=Path), default=None)
@click.pass_context
def generate(
    ctx: click.Context,
    base: str,
    fingerprint_file: Path | None,
    image: Path,
    out_dir: Path | None,
) -> None:
    """Generate a recovery device tree from a fingerprint + image."""
    from aur.generator import generate_tree  # local import to keep CLI startup fast

    if fingerprint_file:
        fp = DeviceFingerprint.load_json(fingerprint_file)
    else:
        adb = _select_adb(ctx.obj.get("serial"))
        fp = fingerprint_device(adb)

    base_out = out_dir or _default_out()
    result = generate_tree(fp=fp, image=image, base=base, out_root=base_out)
    console.print(f"[green]generated[/] device tree(s) in: {result}")


@main.command("export-build")
@click.option("--base", type=click.Choice(["twrp", "orangefox"]), required=True)
@click.option("--mode", type=click.Choice(["docker", "plain", "cloud-vm"]), default="docker")
@click.option("--tree", "tree_dir", type=click.Path(path_type=Path, exists=True), required=True,
              help="Path to a generated device tree directory.")
@click.option("--out", "out_dir", type=click.Path(path_type=Path), default=None)
def export_build(base: str, mode: str, tree_dir: Path, out_dir: Path | None) -> None:
    """Write a build plan (Docker / plain / cloud VM) for the generated tree."""
    from aur.builder import export_build_plan
    target = out_dir or (tree_dir.parent / "build-plan")
    export_build_plan(tree_dir=tree_dir, base=base, mode=mode, out_dir=target)
    console.print(f"[green]build plan written to[/] {target}")


# --------------------------------------------------------------------------- #
# Recovery ops: backup / restore / flash / verify / wipe / reboot
# --------------------------------------------------------------------------- #

def _ops_from_ctx(ctx: click.Context, fingerprint_file: Path | None):
    """Build a RecoveryOps from a saved fingerprint, or fingerprint live."""
    from aur.recovery_ops import RecoveryOps, RecoveryOpsError

    adb = _select_adb(ctx.obj.get("serial"))
    if fingerprint_file:
        fp = DeviceFingerprint.load_json(fingerprint_file)
    else:
        fp = fingerprint_device(adb)
    try:
        return RecoveryOps(adb, fp)
    except RecoveryOpsError as e:
        console.print(f"[red]{e}[/]")
        sys.exit(3)


def _print_result(result) -> None:
    t = Table(title=f"{result.op}: {result.partition}", show_header=False)
    if result.local_path:
        t.add_row("Local", str(result.local_path))
    t.add_row("Bytes", f"{result.bytes_transferred:,}")
    if result.sha256:
        t.add_row("SHA256", result.sha256)
    console.print(t)


# The set we back up when `aur backup --all` is used. Skips userdata
# (gigantic), modem/persist (vendor-specific, often not unique-per-boot),
# and dynamic-only partitions inside super (which dd can't reach).
_CRITICAL_PARTITIONS_FOR_ALL = (
    "boot", "recovery", "vendor_boot", "init_boot",
    "dtbo", "vbmeta", "vbmeta_system", "vbmeta_vendor",
)


@main.command()
@click.option("--partition", "-p", "partitions", multiple=True,
              help="Partition name(s) — repeatable. Try 'aur fingerprint' to list.")
@click.option("--all", "backup_all", is_flag=True,
              help="Back up every boot-class + vbmeta partition that exists on the device.")
@click.option("--out", "out_dir", type=click.Path(path_type=Path),
              default=Path.cwd() / "backups", show_default=True)
@click.option("--fingerprint-file", type=click.Path(path_type=Path, exists=True), default=None)
@click.pass_context
def backup(ctx, partitions, backup_all, out_dir, fingerprint_file):
    """Back up one or more partitions from the device (sha256-verified).

    Use ``--all`` to grab every boot-class + vbmeta partition the device
    actually has — the safety net you want before a custom-recovery flash.
    """
    from aur.recovery_ops import RecoveryOpsError, batch_backup

    ops = _ops_from_ctx(ctx, fingerprint_file)

    if backup_all:
        present = {p.name for p in ops.fp.partitions}
        # Resolve slot suffixes for A/B devices: prefer the *active* slot.
        suffix = ops.fp.all_props.get("ro.boot.slot_suffix", "") if ops.fp.is_ab else ""
        wanted: list[str] = []
        for name in _CRITICAL_PARTITIONS_FOR_ALL:
            if suffix and f"{name}{suffix}" in present:
                wanted.append(f"{name}{suffix}")
            elif name in present:
                wanted.append(name)
        if not wanted:
            console.print(
                "[yellow]--all matched no partitions on this device.[/] "
                "Run `aur fingerprint` and try `-p <name>` explicitly."
            )
            sys.exit(1)
        partitions = tuple(wanted)
        console.print(f"[cyan]Backing up {len(partitions)} partition(s):[/] {', '.join(partitions)}")
    elif not partitions:
        console.print("[red]error:[/] either --partition / -p or --all is required.")
        sys.exit(2)

    target = out_dir / ops.fp.codename
    try:
        results = batch_backup(ops, partitions, target)
    except RecoveryOpsError as e:
        console.print(f"[red]backup failed:[/] {e}")
        sys.exit(2)
    for r in results:
        _print_result(r)


@main.command()
@click.option("--partition", "-p", required=True, help="Partition to write to.")
@click.option("--image", type=click.Path(path_type=Path, exists=True), required=True,
              help="Local image file to write.")
@click.option("--allow-dangerous", is_flag=True,
              help="Allow writing to system/userdata/vendor/super (very risky).")
@click.option("--no-verify", is_flag=True, help="Skip post-write sha256 verification.")
@click.option("--yes", is_flag=True, help="Skip the interactive confirmation prompt.")
@click.option("--fingerprint-file", type=click.Path(path_type=Path, exists=True), default=None)
@click.pass_context
def restore(ctx, partition, image, allow_dangerous, no_verify, yes, fingerprint_file):
    """Restore (write) a local image to a partition. Destructive."""
    from aur.recovery_ops import RecoveryOpsError

    ops = _ops_from_ctx(ctx, fingerprint_file)
    if not yes:
        click.confirm(
            f"About to write {image} → partition {partition!r} on "
            f"{ops.fp.manufacturer}/{ops.fp.codename}. Continue?",
            abort=True,
        )
    try:
        r = ops.restore_partition(
            partition, image,
            confirm=True, allow_dangerous=allow_dangerous, verify=not no_verify,
        )
    except RecoveryOpsError as e:
        console.print(f"[red]restore failed:[/] {e}")
        sys.exit(2)
    _print_result(r)


@main.command()
@click.option("--kind",
              type=click.Choice(["boot", "recovery", "vendor_boot", "init_boot", "dtbo"]),
              required=True)
@click.option("--image", type=click.Path(path_type=Path, exists=True), required=True)
@click.option("--yes", is_flag=True)
@click.option("--fingerprint-file", type=click.Path(path_type=Path, exists=True), default=None)
@click.pass_context
def flash(ctx, kind, image, yes, fingerprint_file):
    """Flash a boot-class image (boot/recovery/vendor_boot/init_boot/dtbo)."""
    from aur.recovery_ops import RecoveryOpsError

    ops = _ops_from_ctx(ctx, fingerprint_file)
    if not yes:
        click.confirm(
            f"Flash {image.name} to {kind} on {ops.fp.manufacturer}/{ops.fp.codename}?",
            abort=True,
        )
    try:
        r = ops.flash_image(kind, image, confirm=True)
    except RecoveryOpsError as e:
        console.print(f"[red]flash failed:[/] {e}")
        sys.exit(2)
    _print_result(r)


@main.command()
@click.option("--partition", "-p", required=True)
@click.option("--sha256", "expected", required=True, help="Expected SHA256 (hex).")
@click.option("--fingerprint-file", type=click.Path(path_type=Path, exists=True), default=None)
@click.pass_context
def verify(ctx, partition, expected, fingerprint_file):
    """Verify an on-device partition matches an expected SHA256."""
    from aur.recovery_ops import RecoveryOpsError

    ops = _ops_from_ctx(ctx, fingerprint_file)
    try:
        r = ops.verify_partition(partition, expected)
    except RecoveryOpsError as e:
        console.print(f"[red]verify failed:[/] {e}")
        sys.exit(2)
    _print_result(r)


@main.command()
@click.argument("target", type=click.Choice(["system", "recovery", "bootloader", "fastboot"]))
@click.pass_context
def reboot(ctx, target):
    """Reboot the device to a target mode."""
    adb = _select_adb(ctx.obj.get("serial"))
    try:
        adb.run("reboot", *([target] if target != "system" else []), timeout=20)
    except ADBError as e:
        # Disconnects are expected on reboot.
        if "closed" not in str(e).lower() and "connection" not in str(e).lower():
            console.print(f"[red]reboot failed:[/] {e}")
            sys.exit(2)
    console.print(f"[green]reboot → {target}[/]")


@main.command()
def doctor() -> None:
    """Check that everything AUR needs is installed and working.

    Walks the host environment and reports each dependency as ok / warn /
    fail. Exit code is non-zero if anything required is missing. Run this
    first when AUR misbehaves — it usually finds the cause in one shot.
    """
    import shutil

    rows: list[tuple[str, str, str, str]] = []  # (label, status, detail, kind)
    required_failures = 0

    # ---- adb (required) ----
    adb_path = shutil.which("adb")
    if adb_path:
        try:
            out = subprocess.run(
                [adb_path, "version"], capture_output=True, text=True, timeout=5,
            ).stdout.splitlines()[0]
        except Exception as e:
            rows.append(("adb", "WARN", f"found at {adb_path} but `adb version` failed: {e}", "warn"))
        else:
            rows.append(("adb", "OK", f"{out}  ({adb_path})", "ok"))
    else:
        rows.append(("adb", "FAIL", "not on PATH — install Android Platform Tools", "fail"))
        required_failures += 1

    # ---- twrpdtgen (required for generator) ----
    try:
        import twrpdtgen  # type: ignore  # noqa: F401
        from twrpdtgen.device_tree import DeviceTree  # type: ignore  # noqa: F401
        rows.append(("twrpdtgen", "OK", "importable; DeviceTree API present", "ok"))
    except ImportError as e:
        rows.append(("twrpdtgen", "FAIL", f"not installed: {e}", "fail"))
        required_failures += 1

    # ---- AIK manager (twrpdtgen's image extractor) ----
    try:
        from sebaubuntu_libs.libaik import AIKManager  # type: ignore  # noqa: F401
        rows.append(("AIKManager", "OK", "image extractor available", "ok"))
    except ImportError:
        rows.append(("AIKManager", "WARN",
                     "missing — `unpackbootimg` will be required as fallback", "warn"))

    # ---- unpackbootimg (preferred image extractor) ----
    upb = shutil.which("unpackbootimg")
    if upb:
        rows.append(("unpackbootimg", "OK", f"found at {upb}", "ok"))
    else:
        rows.append(("unpackbootimg", "WARN",
                     "not on PATH — falls back to AIKManager if installed", "warn"))

    # ---- Docker (only required for the docker build plan) ----
    docker = shutil.which("docker")
    if docker:
        rows.append(("docker", "OK", f"found at {docker} — `docker` build plans will work", "ok"))
    else:
        rows.append(("docker", "WARN",
                     "not on PATH — only matters if you pick the `docker` build plan", "warn"))

    # ---- Python version ----
    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        rows.append(("python", "OK", py, "ok"))
    else:
        rows.append(("python", "FAIL", f"{py} — AUR requires 3.10+", "fail"))
        required_failures += 1

    # ---- Render ----
    style = {"ok": "green", "warn": "yellow", "fail": "red"}
    t = Table(title="aur doctor", show_lines=False)
    t.add_column("check", style="bold")
    t.add_column("status")
    t.add_column("detail")
    for label, status, detail, kind in rows:
        t.add_row(label, f"[{style[kind]}]{status}[/]", detail)
    console.print(t)

    if required_failures:
        console.print(
            f"[red]{required_failures} required check(s) failed.[/] "
            "Fix the FAIL rows above before running other AUR commands."
        )
        sys.exit(1)
    console.print("[green]All required checks passed.[/]")


if __name__ == "__main__":  # pragma: no cover
    main()

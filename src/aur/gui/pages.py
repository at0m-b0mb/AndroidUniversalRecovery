"""Page widgets for the AUR main window.

Each page is a self-contained QWidget that reads/writes shared
:class:`aur.gui.state.AppState`. Pages don't depend on each other —
navigation order is handled entirely by the sidebar.

Layout rules used throughout:
  - Action buttons are wrapped in :func:`ActionRow` so they don't
    stretch to fill the card. The v1 GUI added buttons directly to
    a card's vertical body, which made them render as giant bars.
  - Form fields use :func:`FormRow` (label on the left, control on
    the right, both with a fixed height) so multi-row forms align
    and the controls are always visibly bordered.
  - Long pages live in a :class:`QScrollArea` (set up in :class:`_Page`)
    so we never clip content on smaller windows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from aur.device.adb import ADB, ADBError
from aur.device.fingerprint import DeviceFingerprint
from aur.gui.state import AppState
from aur.gui.widgets import (
    ActionRow,
    Card,
    DeviceCard,
    EmptyState,
    FormRow,
    KeyValueGrid,
    LogPane,
    PageHeader,
    Pill,
    StepCard,
    danger,
    ghost,
    primary,
)
from aur.gui.workers import (
    ExportRequest,
    ExportWorker,
    ExtractRequest,
    ExtractWorker,
    FingerprintWorker,
    GenerateRequest,
    GenerateWorker,
    RebootRequest,
    RebootWorker,
    RecoveryOpRequest,
    RecoveryOpWorker,
    run_worker,
)


# --------------------------------------------------------------------------- #
# base page
# --------------------------------------------------------------------------- #

class _Page(QWidget):
    """Common page layout: header on top, scrollable card column below."""

    def __init__(self, state: AppState, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.state = state
        self._thread = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scroll area wraps the entire page contents.
        scroll = QScrollArea()
        scroll.setObjectName("PageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        inner = QWidget()
        scroll.setWidget(inner)
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(36, 28, 36, 28)
        inner_layout.setSpacing(18)
        inner_layout.addWidget(PageHeader(title, subtitle))

        self.body = QVBoxLayout()
        self.body.setSpacing(14)
        inner_layout.addLayout(self.body, 1)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #

class DashboardPage(_Page):
    """At-a-glance device summary and shortcuts to the main workflows."""

    def __init__(self, state: AppState, on_navigate: Callable[[str], None]) -> None:
        super().__init__(
            state,
            title="Dashboard",
            subtitle="Connect a device, then drive the generator or recovery ops from here.",
        )
        self._on_navigate = on_navigate

        self.device_card = DeviceCard()
        self.body.addWidget(self.device_card)

        # Quick actions: three feature cards in a row.
        row = QHBoxLayout()
        row.setSpacing(14)

        gen_card = Card(
            "Generate recovery",
            "Pull boot/recovery from the device, generate a TWRP or OrangeFox tree, "
            "then export a Docker / cloud-VM build plan.",
        )
        gen_card.add(ActionRow(primary("Start", lambda: self._on_navigate("generate"))))

        ops_card = Card(
            "Recovery operations",
            "With a recovery on the device (or root), back up, restore, flash, and "
            "verify partitions with SHA-256 protection.",
        )
        ops_card.add(ActionRow(primary("Open", lambda: self._on_navigate("ops"))))

        conn_card = Card(
            "Connect another device",
            "Switch the active ADB device or fingerprint a new phone.",
        )
        conn_card.add(ActionRow(ghost("Devices", lambda: self._on_navigate("connect"))))

        for c in (gen_card, ops_card, conn_card):
            c.setMinimumWidth(260)
            c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            row.addWidget(c, 1)
        self.body.addLayout(row)

        # "Where my files live" card — reveals out_root in Finder/Files and
        # shows a roll-up of saved fingerprints so users can jump back into
        # past device work without re-fingerprinting.
        self.output_card = Card(
            "Output folder",
            f"AUR writes everything under {state.out_root}.",
        )
        self.output_card.add(ActionRow(
            ghost("Open output folder",
                  lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(state.out_root)))),
        ))
        self._recents_grid = KeyValueGrid()
        self.output_card.add(self._recents_grid)
        self.body.addWidget(self.output_card)

        self.body.addStretch(1)

        # Refresh the recents list whenever the underlying out_root changes
        # AND once now to populate on startup.
        state.out_root_changed.connect(self._refresh_recents)
        self._refresh_recents(state.out_root)

        state.fingerprint_changed.connect(self._update_device_card)

    def _update_device_card(self, fp) -> None:
        if fp is None:
            self.device_card.show_empty()
        else:
            self.device_card.show_fingerprint(fp)

    def _refresh_recents(self, out_root) -> None:
        """Refill the Output folder card's recents grid + caption."""
        self.output_card.set_caption(f"AUR writes everything under {out_root}.")
        self._recents_grid.clear()
        recents = self.state.saved_fingerprints()
        if not recents:
            self._recents_grid.add("Saved fingerprints", "(none yet)")
            return
        for fp_path in recents[:6]:
            self._recents_grid.add(fp_path.parent.name, str(fp_path.parent))


# --------------------------------------------------------------------------- #
# Connect — list / pick adb device, then fingerprint
# --------------------------------------------------------------------------- #

class ConnectPage(_Page):
    def __init__(self, state: AppState) -> None:
        super().__init__(
            state,
            title="Connect device",
            subtitle="Plug in the phone with USB debugging enabled, then refresh and pick a serial.",
        )

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Serial", "State", "", "Saved"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(180)

        self.empty_devices = EmptyState(
            glyph="◌",
            title="No devices found",
            hint="Connect a phone with USB debugging enabled, then hit Refresh.",
        )

        self.fp_btn = primary("Fingerprint selected device", self._do_fingerprint)
        self.fp_btn.setEnabled(False)
        self.ping_btn = ghost("Ping device", self._do_ping)
        self.ping_btn.setEnabled(False)

        card = Card(
            "ADB devices",
            "Devices the host can see. Only rows in state `device` or `recovery` can be fingerprinted.",
        )
        card.add(self.table)
        card.add(self.empty_devices)
        card.add(ActionRow(
            ghost("Refresh", self.refresh),
            self.ping_btn,
            self.fp_btn,
        ))
        self.body.addWidget(card)

        self.log = LogPane(
            max_lines=400,
            placeholder="Activity log will appear here.",
            mirror_path=state.out_root / "logs" / "connect.log",
        )
        log_card = Card("Activity")
        log_card.add(self.log)
        self.body.addWidget(log_card, 1)
        state.out_root_changed.connect(
            lambda p: self.log.set_mirror_path(p / "logs" / "connect.log"),
        )

        self.table.itemSelectionChanged.connect(self._sync_button_state)
        self.refresh()

    def refresh(self) -> None:
        try:
            devs = ADB.list_devices()
        except ADBError as e:
            self.log.log(str(e), level="error")
            devs = []
        saved = self.state.saved_fingerprints_by_serial()
        self.table.setRowCount(len(devs))
        for i, d in enumerate(devs):
            self.table.setItem(i, 0, QTableWidgetItem(d.serial))
            self.table.setItem(i, 1, QTableWidgetItem(d.state))
            pill_kind = "success" if d.state == "device" else (
                "warning" if d.state == "recovery" else "danger"
            )
            self.table.setCellWidget(i, 2, Pill(d.state, pill_kind))
            # 4th column: short-circuit to the codename if we already have a
            # fingerprint on disk for this serial. Lets the user spot
            # already-known devices at a glance and avoids re-fingerprinting.
            codename = saved.get(d.serial, "")
            if codename:
                self.table.setCellWidget(i, 3, Pill(codename, "info"))
            else:
                self.table.setItem(i, 3, QTableWidgetItem(""))

        # Toggle empty state vs table.
        has_devices = bool(devs)
        self.table.setVisible(has_devices)
        self.empty_devices.setVisible(not has_devices)

        self.log.log(
            f"Found {len(devs)} device(s)." if devs else "No devices visible to adb.",
            level="ok" if devs else "warn",
        )

        # If there's exactly one usable device, auto-select it — saves a click
        # and removes the "why is the button still disabled?" moment.
        usable = [
            (i, d) for i, d in enumerate(devs)
            if d.state in ("device", "recovery")
        ]
        if len(usable) == 1:
            self.table.selectRow(usable[0][0])

        self._sync_button_state()

    def _selected_serial(self) -> str | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        row = rows[0].row()
        state_item = self.table.item(row, 1)
        if state_item is None or state_item.text() not in ("device", "recovery"):
            return None
        serial_item = self.table.item(row, 0)
        return serial_item.text() if serial_item else None

    def _sync_button_state(self) -> None:
        usable = self._selected_serial() is not None
        self.fp_btn.setEnabled(usable)
        self.ping_btn.setEnabled(usable)

    def _do_fingerprint(self) -> None:
        serial = self._selected_serial()
        if not serial:
            return
        self.state.set_serial(serial)
        self.fp_btn.setEnabled(False)
        self.log.log(f"Fingerprinting {serial}…", level="step")
        worker = FingerprintWorker(serial=serial, out_root=self.state.out_root)
        worker.progress.connect(lambda m: self.log.log(m))
        worker.finished.connect(self._fp_done)
        worker.failed.connect(self._fp_fail)
        self._thread = run_worker(self, worker)

    def _fp_done(self, payload: dict) -> None:
        self.state.set_fingerprint(payload["fingerprint"])
        self.log.log(f"Saved {payload['path']}", level="ok")
        self.fp_btn.setEnabled(True)
        # The "Saved" column shows codename pills for known serials. Re-run
        # refresh so the freshly-saved fingerprint appears immediately.
        self.refresh()

    def _fp_fail(self, msg: str) -> None:
        self.log.log(msg, level="error")
        self.fp_btn.setEnabled(True)

    # ---- ping ----

    def _do_ping(self) -> None:
        """Round-trip `adb shell echo` to confirm the selected device responds.

        Synchronous because the call is sub-second; running it through a
        QThread would add overhead and the log glyph already conveys state.
        """
        serial = self._selected_serial()
        if not serial:
            return
        self.log.log(f"ping {serial}…", level="step")
        try:
            adb = ADB(serial=serial)
            out = adb.shell("echo aur-ping-$$", check=False, timeout=5).strip()
        except ADBError as e:
            self.log.log(f"ping failed: {e}", level="error")
            return
        if out.startswith("aur-ping-"):
            self.log.log(f"pong from {serial} ({out})", level="ok")
        else:
            self.log.log(f"unexpected response: {out!r}", level="warn")

    # ---- one-shot: auto-fingerprint when there's exactly one usable device ----

    def maybe_auto_fingerprint(self) -> None:
        """If exactly one usable device is present and we haven't already
        fingerprinted it in this session, kick off fingerprinting on its own.

        Called by :class:`MainWindow` after the Connect page is shown for
        the first time. Saves the user a click in the common one-device case.
        """
        if self.state.fingerprint is not None:
            return  # already done in this session
        try:
            devs = ADB.list_devices()
        except ADBError:
            return
        usable = [d for d in devs if d.state == "device"]
        if len(usable) != 1:
            return
        target = usable[0]
        # Don't auto-FP a device we've already saved on disk — the user can
        # see it in the "Saved" column and pick whether to refresh it.
        saved = self.state.saved_fingerprints_by_serial()
        if target.serial in saved:
            return
        self.log.log(
            f"auto-fingerprinting {target.serial} (only device, no saved fingerprint)",
            level="step",
        )
        self.state.set_serial(target.serial)
        worker = FingerprintWorker(serial=target.serial, out_root=self.state.out_root)
        worker.progress.connect(lambda m: self.log.log(m))
        worker.finished.connect(self._fp_done)
        worker.failed.connect(self._fp_fail)
        self._thread = run_worker(self, worker)


# --------------------------------------------------------------------------- #
# Generator — extract + generate + export, three numbered step cards
# --------------------------------------------------------------------------- #

class GeneratePage(_Page):
    def __init__(self, state: AppState, on_navigate: Callable[[str], None] | None = None) -> None:
        super().__init__(
            state,
            title="Generate recovery",
            subtitle="Pull the boot/recovery image, generate a device tree, and export a build plan.",
        )
        self._on_navigate = on_navigate

        self.device_card = DeviceCard()
        self.body.addWidget(self.device_card)

        # CTA card shown when no fingerprint exists. The three step cards below
        # are useless without one, so guide the user to Connect first.
        self.no_fp_card = Card(
            "Fingerprint a device first",
            "The generator reads the device codename, partition map, and boot image "
            "from a fingerprint. Open the Connect page and run Fingerprint, then "
            "come back here.",
        )
        if on_navigate is not None:
            self.no_fp_card.add(ActionRow(primary(
                "Open Connect →", lambda: on_navigate("connect"),
            )))
        self.body.addWidget(self.no_fp_card)

        state.fingerprint_changed.connect(self._on_fp)
        # Initial visibility matches current state.
        self.no_fp_card.setVisible(state.fingerprint is None)

        # ---- Step 1: extract ----------------------------------------------
        self.kind_box = QComboBox()
        self.kind_box.addItems(["recovery", "boot", "vendor_boot", "init_boot"])
        self.kind_box.setMinimumWidth(220)

        self.image_edit = QLineEdit()
        self.image_edit.setPlaceholderText("(leave blank to pull from device)")
        image_browse = ghost("Browse…", self._pick_image)

        self.extract_btn = primary("Pull / use image", self._do_extract)

        self.step1 = StepCard(
            1,
            "Extract image",
            caption="Pull a boot-class image off the device (needs root or a custom recovery), "
                    "or point AUR at a local .img file.",
            state="active",
        )
        self.step1.add(FormRow("Image kind", self.kind_box))
        self.step1.add(FormRow("Local image", self.image_edit, image_browse))
        self.step1.add(ActionRow(self.extract_btn))
        self.body.addWidget(self.step1)

        # ---- Step 2: generate ---------------------------------------------
        self.base_box = QComboBox()
        self.base_box.addItems(["twrp", "orangefox", "both"])
        self.base_box.setMinimumWidth(220)
        self.generate_btn = primary("Generate device tree", self._do_generate)
        self.generate_btn.setEnabled(False)

        self.step2 = StepCard(
            2,
            "Generate device tree",
            caption="Wraps twrpdtgen for TWRP; layers an overlay on top for OrangeFox.",
            state="locked",
        )
        self.step2.add(FormRow("Recovery base", self.base_box))
        self.step2.add(ActionRow(self.generate_btn))
        self.body.addWidget(self.step2)

        # ---- Step 3: export -----------------------------------------------
        self.tree_box = QComboBox()
        self.tree_box.setMinimumWidth(220)
        self.mode_box = QComboBox()
        self.mode_box.addItems(["docker", "plain", "cloud-vm"])
        self.mode_box.setMinimumWidth(220)
        self.export_btn = primary("Export build plan", self._do_export)
        self.export_btn.setEnabled(False)

        self.step3 = StepCard(
            3,
            "Export build plan",
            caption="Hybrid build: AUR writes the device tree + build instructions; "
                    "you run the actual AOSP build in Docker, on Linux, or on a cloud VM.",
            state="locked",
        )
        self.step3.add(FormRow("Tree", self.tree_box))
        self.step3.add(FormRow("Build host", self.mode_box))
        self.step3.add(ActionRow(self.export_btn))
        self.body.addWidget(self.step3)

        self.log = LogPane(
            placeholder="Activity log will appear here once you start a step.",
            mirror_path=state.out_root / "logs" / "generate.log",
        )
        log_card = Card("Activity")
        log_card.add(self.log)
        self.body.addWidget(log_card, 1)

        # Keep the mirror path in sync if the output dir changes (Settings page).
        state.out_root_changed.connect(
            lambda p: self.log.set_mirror_path(p / "logs" / "generate.log"),
        )
        state.trees_changed.connect(self._on_trees)

    def _on_fp(self, fp) -> None:
        if fp is None:
            self.device_card.show_empty()
            self.no_fp_card.setVisible(True)
        else:
            self.device_card.show_fingerprint(fp)
            self.no_fp_card.setVisible(False)

    def _on_trees(self, trees: dict[str, Path]) -> None:
        self.tree_box.clear()
        for base, path in trees.items():
            self.tree_box.addItem(f"{base}: {path.name}", (base, path))
        self.export_btn.setEnabled(bool(trees))
        if trees:
            self.step2.set_step_state("done")
            self.step3.set_step_state("active")

    def _pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick boot/recovery image", str(Path.home()),
            "Android images (*.img *.bin);;All files (*)",
        )
        if path:
            self.image_edit.setText(path)

    def _ensure_fp(self) -> DeviceFingerprint | None:
        fp = self.state.fingerprint
        if fp is None:
            QMessageBox.warning(
                self, "No fingerprint",
                "Fingerprint a device first (Connect page).",
            )
        return fp

    def _do_extract(self) -> None:
        fp = self._ensure_fp()
        if fp is None:
            return
        manual = self.image_edit.text().strip()
        req = ExtractRequest(
            serial=self.state.serial,
            fp=fp,
            out_root=self.state.out_root,
            kind=self.kind_box.currentText(),
            manual_image=Path(manual) if manual else None,
        )
        self.extract_btn.setEnabled(False)
        self.log.log(f"Extracting {req.kind}…", level="step")
        worker = ExtractWorker(req)
        worker.progress.connect(lambda m: self.log.log(m))
        worker.finished.connect(self._extract_done)
        worker.failed.connect(self._extract_fail)
        self._thread = run_worker(self, worker)

    def _extract_done(self, payload: dict) -> None:
        self.state.set_image_path(payload["image"])
        u = payload["unpacked"]
        self.log.log(f"Image at {payload['image']}", level="ok")
        self.log.log(
            f"  header v{u.header_version}, kernel={'yes' if u.kernel else 'no'}, "
            f"ramdisk={'yes' if u.ramdisk else 'no'}, dtb={'yes' if u.dtb else 'no'}",
        )
        self.extract_btn.setEnabled(True)
        self.generate_btn.setEnabled(True)
        self.step1.set_step_state("done")
        self.step2.set_step_state("active")

    def _extract_fail(self, msg: str) -> None:
        self.log.log(msg, level="error")
        self.extract_btn.setEnabled(True)

    def _do_generate(self) -> None:
        fp = self._ensure_fp()
        if fp is None or self.state.image_path is None:
            return
        req = GenerateRequest(
            fp=fp,
            image=self.state.image_path,
            base=self.base_box.currentText(),
            out_root=self.state.out_root / fp.codename,
        )
        self.generate_btn.setEnabled(False)
        self.log.log(f"Generating ({req.base})…", level="step")
        worker = GenerateWorker(req)
        worker.progress.connect(lambda m: self.log.log(m))
        worker.finished.connect(self._gen_done)
        worker.failed.connect(self._gen_fail)
        self._thread = run_worker(self, worker)

    def _gen_done(self, results: dict[str, Path]) -> None:
        self.state.set_trees(results)
        for base, path in results.items():
            self.log.log(f"{base} tree at {path}", level="ok")
        self.generate_btn.setEnabled(True)

    def _gen_fail(self, msg: str) -> None:
        self.log.log(msg, level="error")
        self.generate_btn.setEnabled(True)

    def _do_export(self) -> None:
        data = self.tree_box.currentData()
        if not data:
            return
        base, tree = data
        out_dir = tree.parent / f"build-plan-{base}-{self.mode_box.currentText()}"
        req = ExportRequest(
            tree_dir=tree, base=base, mode=self.mode_box.currentText(), out_dir=out_dir,
        )
        self.export_btn.setEnabled(False)
        self.log.log(f"Exporting {req.mode} plan for {req.base}…", level="step")
        worker = ExportWorker(req)
        worker.progress.connect(lambda m: self.log.log(m))
        worker.finished.connect(self._export_done)
        worker.failed.connect(self._export_fail)
        self._thread = run_worker(self, worker)

    def _export_done(self, path: Path) -> None:
        self.log.log(f"Plan written to {path}", level="ok")
        self.export_btn.setEnabled(True)
        self.step3.set_step_state("done")

    def _export_fail(self, msg: str) -> None:
        self.log.log(msg, level="error")
        self.export_btn.setEnabled(True)


# --------------------------------------------------------------------------- #
# Recovery operations — backup / restore / flash / verify
# --------------------------------------------------------------------------- #

class RecoveryOpsPage(_Page):
    def __init__(self, state: AppState) -> None:
        super().__init__(
            state,
            title="Recovery operations",
            subtitle="Back up, restore, flash, and verify on-device partitions. "
                     "Destructive actions require explicit confirmation.",
        )

        self.device_card = DeviceCard()
        self.body.addWidget(self.device_card)
        state.fingerprint_changed.connect(self._on_fp)

        # ---- Target card (shared partition picker) ----
        self.partition_box = QComboBox()
        self.partition_box.setEditable(True)
        self.partition_box.setMinimumWidth(220)

        target_card = Card(
            "Target partition",
            "Picked once for every action on this page. Populated from the current "
            "device fingerprint; you can also type a name (e.g. boot_a).",
        )
        target_card.add(FormRow("Partition", self.partition_box))
        self.body.addWidget(target_card)

        # ---- Backup card ----
        self.backup_dest = QLineEdit(str((Path.home() / "AUR_backups")))
        backup_browse = ghost("Browse…", lambda: self._pick_dir(self.backup_dest))
        self.backup_btn = primary("Back up partition", lambda: self._run("backup"))

        backup_card = Card(
            "Back up",
            "Reads the partition with dd, pulls to the host, and verifies SHA-256 end to end.",
        )
        backup_card.add(FormRow("Destination", self.backup_dest, backup_browse))
        backup_card.add(ActionRow(self.backup_btn))
        self.body.addWidget(backup_card)

        # ---- Restore / Flash card ----
        self.restore_image = QLineEdit()
        self.restore_image.setPlaceholderText("Pick a local .img file…")
        rb = ghost("Browse…", lambda: self._pick_file(self.restore_image))

        self.allow_dangerous = QCheckBox(
            "I understand — allow writes to system / vendor / userdata / super partitions"
        )

        self.restore_btn = danger("Restore (write) image", lambda: self._run("restore"))
        self.flash_btn = primary("Flash boot-class image", lambda: self._run("flash"))

        write_card = Card(
            "Write to device",
            "Restore is generic (write any image to any non-dangerous partition); "
            "Flash is restricted to boot/recovery/vendor_boot/init_boot/dtbo.",
        )
        write_card.add(FormRow("Local image", self.restore_image, rb))
        write_card.add(self.allow_dangerous)
        write_card.add(ActionRow(self.flash_btn, self.restore_btn))
        self.body.addWidget(write_card)

        # ---- Verify card ----
        self.verify_sha = QLineEdit()
        self.verify_sha.setPlaceholderText("expected sha256 (hex)")
        self.verify_btn = primary("Verify partition", lambda: self._run("verify"))
        verify_card = Card("Verify", "Compute SHA-256 of an on-device partition and compare.")
        verify_card.add(FormRow("Expected SHA-256", self.verify_sha))
        verify_card.add(ActionRow(self.verify_btn))
        self.body.addWidget(verify_card)

        # ---- Reboot card ----
        # The reboot workflow comes up repeatedly during flash work
        # (boot to bootloader → fastboot flash → reboot to recovery to verify
        # → reboot to system). Pinning it next to the write actions saves a
        # round-trip through `adb` in a terminal every time.
        self.reboot_recovery_btn = ghost("→ Recovery", lambda: self._reboot("recovery"))
        self.reboot_bootloader_btn = ghost("→ Bootloader", lambda: self._reboot("bootloader"))
        self.reboot_fastboot_btn = ghost("→ Fastboot", lambda: self._reboot("fastboot"))
        self.reboot_system_btn = primary("→ System", lambda: self._reboot("system"))

        reboot_card = Card(
            "Reboot device",
            "Common stops in the flash workflow: bootloader to write images, "
            "recovery to verify, system to confirm the device boots.",
        )
        reboot_card.add(ActionRow(
            self.reboot_recovery_btn,
            self.reboot_bootloader_btn,
            self.reboot_fastboot_btn,
            self.reboot_system_btn,
        ))
        self.body.addWidget(reboot_card)

        self.log = LogPane(
            placeholder="Activity log will appear here once you run an op.",
            mirror_path=state.out_root / "logs" / "recovery_ops.log",
        )
        log_card = Card("Activity")
        log_card.add(self.log)
        self.body.addWidget(log_card, 1)
        state.out_root_changed.connect(
            lambda p: self.log.set_mirror_path(p / "logs" / "recovery_ops.log"),
        )

    def _on_fp(self, fp) -> None:
        if fp is None:
            self.device_card.show_empty()
            self.partition_box.clear()
            return
        self.device_card.show_fingerprint(fp)
        self.partition_box.clear()
        self.partition_box.addItems([p.name for p in fp.partitions])

    def _pick_file(self, target: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick image", str(Path.home()),
            "Android images (*.img *.bin);;All files (*)",
        )
        if path:
            target.setText(path)

    def _pick_dir(self, target: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "Pick directory", target.text())
        if path:
            target.setText(path)

    def _ensure_fp(self):
        fp = self.state.fingerprint
        if fp is None:
            QMessageBox.warning(
                self, "No fingerprint",
                "Fingerprint a device first (Connect page).",
            )
            return None
        return fp

    def _selected_partition(self) -> str:
        return self.partition_box.currentText().strip()

    def _run(self, op: str) -> None:
        fp = self._ensure_fp()
        if fp is None:
            return
        part = self._selected_partition()
        if not part:
            QMessageBox.warning(self, "No partition", "Pick a partition first.")
            return

        req = RecoveryOpRequest(
            serial=self.state.serial, fp=fp, op=op, partition=part,
            allow_dangerous=self.allow_dangerous.isChecked(),
        )

        if op == "backup":
            req.dest_dir = Path(self.backup_dest.text()) / fp.codename
        elif op in ("restore", "flash"):
            img = self.restore_image.text().strip()
            if not img:
                QMessageBox.warning(self, "No image", "Pick a local image file first.")
                return
            req.image = Path(img)
            if op == "restore":
                ok = QMessageBox.question(
                    self, "Confirm write",
                    f"Write {req.image.name} to partition '{part}' on "
                    f"{fp.manufacturer}/{fp.codename}?\n\nThis is destructive.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if ok != QMessageBox.StandardButton.Yes:
                    self.log.log("Restore canceled.", level="warn")
                    return
            elif op == "flash":
                if part not in ("boot", "recovery", "vendor_boot", "init_boot", "dtbo"):
                    QMessageBox.warning(
                        self, "Wrong partition",
                        f"Flash is for boot-class partitions. Got {part!r}.",
                    )
                    return
        elif op == "verify":
            sha = self.verify_sha.text().strip().lower()
            if len(sha) != 64:
                QMessageBox.warning(self, "Bad hash", "Provide a 64-char hex SHA-256.")
                return
            req.sha256 = sha

        for btn in (self.backup_btn, self.restore_btn, self.flash_btn, self.verify_btn):
            btn.setEnabled(False)
        self.log.log(f"{op}: {part}", level="step")

        worker = RecoveryOpWorker(req)
        worker.progress.connect(lambda m: self.log.log(m))
        worker.finished.connect(self._op_done)
        worker.failed.connect(self._op_fail)
        self._thread = run_worker(self, worker)

    def _op_done(self, result) -> None:
        self.log.log(f"{result.op} {result.partition}: OK ({result.bytes_transferred:,} bytes)",
                     level="ok")
        if result.sha256:
            self.log.log(f"  sha256 {result.sha256}")
        if result.local_path:
            self.log.log(f"  local  {result.local_path}")
        self._reenable()

    def _op_fail(self, msg: str) -> None:
        self.log.log(msg, level="error")
        self._reenable()

    def _reenable(self) -> None:
        for btn in (self.backup_btn, self.restore_btn, self.flash_btn, self.verify_btn):
            btn.setEnabled(True)

    # ---- reboots ----

    def _reboot(self, target: str) -> None:
        """Issue an off-thread reboot. Reboots don't need a fingerprint —
        the only requirement is an ADB connection, which we don't enforce
        here because the user can read the ADB pill at the bottom of the
        window to know if the reboot will land.
        """
        for btn in (self.reboot_recovery_btn, self.reboot_bootloader_btn,
                    self.reboot_fastboot_btn, self.reboot_system_btn):
            btn.setEnabled(False)
        self.log.log(f"reboot → {target}", level="step")
        worker = RebootWorker(RebootRequest(serial=self.state.serial, target=target))
        worker.progress.connect(lambda m: self.log.log(m))
        worker.finished.connect(self._reboot_done)
        worker.failed.connect(self._reboot_fail)
        self._thread = run_worker(self, worker)

    def _reboot_done(self, payload: dict) -> None:
        self.log.log(f"reboot ok ({payload['target']})", level="ok")
        for btn in (self.reboot_recovery_btn, self.reboot_bootloader_btn,
                    self.reboot_fastboot_btn, self.reboot_system_btn):
            btn.setEnabled(True)

    def _reboot_fail(self, msg: str) -> None:
        self.log.log(msg, level="error")
        for btn in (self.reboot_recovery_btn, self.reboot_bootloader_btn,
                    self.reboot_fastboot_btn, self.reboot_system_btn):
            btn.setEnabled(True)


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

class SettingsPage(_Page):
    def __init__(self, state: AppState) -> None:
        super().__init__(
            state,
            title="Settings",
            subtitle="Configure paths and defaults.",
        )

        self.out_root_edit = QLineEdit(str(state.out_root))
        out_browse = ghost("Browse…", self._pick_out)
        save = primary("Save", self._save)

        card = Card(
            "Paths",
            "AUR writes fingerprints, pulled images, generated trees, and build plans "
            "under this directory.",
        )
        card.add(FormRow("Output directory", self.out_root_edit, out_browse))
        card.add(ActionRow(save))
        self.body.addWidget(card)

        about = Card(
            "About",
            "AUR is open source under GPL-3.0. Bug reports and patches welcome.",
        )
        kv = KeyValueGrid()
        kv.add("Version", "0.1.0")
        kv.add("Recovery bases", "TWRP · OrangeFox")
        kv.add("Build host modes", "Docker · Plain Linux · Cloud VM")
        kv.add("License", "GPL-3.0-or-later")
        about.add(kv)
        # "More details" opens the full About dialog (version-checked at runtime
        # so it always reflects the installed twrpdtgen and adb, not whatever
        # was true at package-build time).
        about.add(ActionRow(ghost("More details…", self._show_about)))
        self.body.addWidget(about)

        self.body.addStretch(1)

    def _show_about(self) -> None:
        from aur.gui.about import AboutDialog
        AboutDialog(self).exec()

    def _pick_out(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Output directory", self.out_root_edit.text() or str(Path.home()),
        )
        if path:
            self.out_root_edit.setText(path)

    def _save(self) -> None:
        self.state.set_out_root(Path(self.out_root_edit.text()))
        QMessageBox.information(self, "Saved", "Settings updated for this session.")

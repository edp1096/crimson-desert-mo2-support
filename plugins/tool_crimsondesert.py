import sys
import traceback
from pathlib import Path

import mobase
from basic_games.games.crimsondesert.constants import PLUGIN_VERSION_TUPLE
from PyQt6.QtCore import QCoreApplication, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


def _get_builder_class():
    try:
        from basic_games.games.crimsondesert.builder import CrimsonDesertBuilder
        return CrimsonDesertBuilder
    except ImportError:
        plugins_dir = str(Path(__file__).resolve().parent)
        if plugins_dir not in sys.path:
            sys.path.insert(0, plugins_dir)
        from basic_games.games.crimsondesert.builder import CrimsonDesertBuilder
        return CrimsonDesertBuilder


class BuildWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)  # current, total
    finished_signal = pyqtSignal(object)

    def __init__(self, builder, action):
        super().__init__()
        self._builder = builder
        self._action = action

    def run(self):
        try:
            if self._action in ("build", "force_build"):
                result = self._builder.build(
                    logger=self._emit_log,
                    on_progress=self._emit_progress,
                    force=(self._action == "force_build"),
                )
            elif self._action == "flush":
                self._builder.flush(logger=self._emit_log)
                result = None
            elif self._action == "remove_bundles":
                self._builder.remove_generated_bundles(logger=self._emit_log)
                result = None
            self.finished_signal.emit(result)
        except Exception as e:
            self.finished_signal.emit(e)

    def _emit_log(self, msg):
        self.log_signal.emit(msg)

    def _emit_progress(self, current, total):
        self.progress_signal.emit(current, total)


class BuildDialog(QDialog):
    def __init__(self, parent, builder, organizer=None):
        super().__init__(parent)
        self._builder = builder
        self._organizer = organizer
        self._worker = None
        self._last_action = None
        self.setWindowTitle("Crimson Desert PAZ Builder")
        self.setMinimumSize(640, 420)

        self._log = QTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("%v / %m mods (%p%)")
        self._progress.hide()

        self._auto_build_cb = QCheckBox("Auto build on Run", self)
        if organizer:
            self._auto_build_cb.setChecked(
                bool(organizer.pluginSetting("Crimson Desert PAZ Builder", "auto_build_on_run"))
            )
        self._auto_build_cb.toggled.connect(self._on_auto_build_toggled)

        self._scan_btn = QPushButton("Scan Mods", self)
        self._scan_btn.clicked.connect(self._on_scan)

        self._build_btn = QPushButton("Build", self)
        self._build_btn.clicked.connect(self._on_build)

        self._flush_btn = QPushButton("Flush", self)
        self._flush_btn.clicked.connect(self._on_flush)

        self._close_btn = QPushButton("Close", self)
        self._close_btn.clicked.connect(self.accept)

        row = QHBoxLayout()
        row.addWidget(self._scan_btn)
        row.addWidget(self._build_btn)
        row.addWidget(self._flush_btn)
        row.addStretch(1)
        row.addWidget(self._auto_build_cb)
        row.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._log, stretch=1)
        layout.addWidget(self._progress)
        layout.addLayout(row)

        QTimer.singleShot(100, self._on_scan)

    def _on_auto_build_toggled(self, checked):
        if self._organizer:
            self._organizer.setPluginSetting(
                "Crimson Desert PAZ Builder", "auto_build_on_run", checked
            )

    def _log_msg(self, msg):
        self._log.append(msg)
        self._log.moveCursor(QTextCursor.MoveOperation.End)

    def _update_progress(self, current, total):
        self._progress.setRange(0, total)
        self._progress.setValue(current)

    def _set_buttons(self, enabled):
        self._scan_btn.setEnabled(enabled)
        self._build_btn.setEnabled(enabled)
        self._flush_btn.setEnabled(enabled)
        self._close_btn.setEnabled(enabled)

    def _on_scan(self):
        self._log.clear()
        self._log_msg("Scanning active mods...")
        try:
            mods = self._builder.scan_mods()
            if not mods:
                self._log_msg("No Crimson Desert mods found.")
                return
            _TYPE_LABELS = {
                "json_patch": "json",
                "loose_files": "crimson",
                "mixed": "json+crimson",
                "paz_bundle": "paz",
                "asi": "asi",
            }
            for m in mods:
                label = _TYPE_LABELS.get(m.mod_type, m.mod_type)
                bnums = ", ".join(f"{n:04d}" for n in m.bundle_numbers) if m.bundle_numbers else ""
                bnum = f" [bundle {bnums}]" if bnums else ""
                tag = f"[{label}]".ljust(14)
                self._log_msg(f"  {tag} {m.name}{bnum}")
            self._log_msg(f"\nTotal: {len(mods)} mod(s)")
        except Exception:
            self._log_msg(f"Error:\n{traceback.format_exc()}")

    def _on_build(self):
        ver_change = self._builder.check_game_version_changed()
        if ver_change:
            prev, cur = ver_change
            reply = QMessageBox.question(
                self, "Game Updated",
                f"Game version changed ({prev} → {cur}).\n"
                "Rebuild all mods to match the new game archives?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._start_worker("force_build")
                return
        self._start_worker("build")

    def _on_flush(self):
        reply = QMessageBox.question(
            self, "Flush",
            "Remove all generated PAZ bundles and meta files?\n"
            "Game will revert to vanilla state.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._start_worker("flush")

    def _start_worker(self, action):
        if self._worker is not None and self._worker.isRunning():
            return
        self._last_action = action
        self._log.clear()
        self._set_buttons(False)
        self._progress.setValue(0)
        self._progress.show()

        self._worker = BuildWorker(self._builder, action)
        self._worker.log_signal.connect(self._log_msg)
        self._worker.progress_signal.connect(self._update_progress)
        self._worker.finished_signal.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self, result):
        self._progress.hide()
        self._set_buttons(True)
        self._worker = None

        if isinstance(result, Exception):
            self._log_msg(f"\nFailed:\n{result}")
        elif result is None:
            if self._last_action == "flush":
                self._log_msg("\nFlush complete.")
                QTimer.singleShot(0, self._check_orphaned_bundles)
            elif self._last_action == "remove_bundles":
                self._log_msg("\nRemove complete.")
        else:
            self._log_msg(f"\nDone. Built: {result.built_count}")
            for w in result.warnings:
                self._log_msg(f"Warning: {w}")

    def _check_orphaned_bundles(self):
        if not self._builder.has_orphaned_bundles():
            return
        reply = QMessageBox.question(
            self, "Remove 00xx",
            "Orphaned 00xx bundle folders found in mod directories.\n"
            "Remove them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._start_worker("remove_bundles")


class CrimsonDesertToolPlugin(mobase.IPluginTool):
    def __init__(self):
        super().__init__()
        self._organizer = None
        self._parentWidget = None

    def init(self, organizer):
        self._organizer = organizer
        return True

    def name(self):
        return "Crimson Desert PAZ Builder"

    def author(self):
        return "edp1096"

    def description(self):
        return self.__tr("Build per-mod PAZ archives from JSON patches and loose files.")

    def version(self):
        return mobase.VersionInfo(*PLUGIN_VERSION_TUPLE)

    def isActive(self):
        return True

    def settings(self):
        return [
            mobase.PluginSetting("auto_build_on_run", "Auto build before game launch", False),
        ]

    def displayName(self):
        return self.__tr("Crimson Desert/PAZ Builder")

    def tooltip(self):
        return self.__tr("Build per-mod PAZ archives.")

    def icon(self):
        return mobase.getIconForExecutable("")

    def setParentWidget(self, widget):
        self._parentWidget = widget

    def display(self):
        if self._organizer is None:
            return

        try:
            BuilderClass = _get_builder_class()
        except Exception:
            QMessageBox.critical(
                self._parentWidget, "PAZ Builder",
                f"Failed to load builder:\n{traceback.format_exc()}",
            )
            return

        game = self._organizer.managedGame()
        game_path = Path(game.gameDirectory().absolutePath())
        mods_path = Path(self._organizer.modsPath())
        overwrite_path = Path(self._organizer.overwritePath())
        profile_path = Path(self._organizer.profilePath())
        organizer = self._organizer

        def get_active_mods():
            result = []
            mod_list = organizer.modList()
            for priority, mod_name in enumerate(
                mod_list.allModsByProfilePriority()
            ):
                if mod_list.state(mod_name) & mobase.ModState.ACTIVE:
                    result.append((mod_name, priority))
            return result

        builder = BuilderClass(
            game_path=game_path,
            mods_path=mods_path,
            overwrite_path=overwrite_path,
            profile_path=profile_path,
            get_active_mods=get_active_mods,
        )

        dialog = BuildDialog(self._parentWidget, builder, self._organizer)
        dialog.exec()

    def __tr(self, value):
        return QCoreApplication.translate("CrimsonDesertToolPlugin", value)


def createPlugin():
    return CrimsonDesertToolPlugin()

from __future__ import annotations

import sys
from pathlib import Path

import mobase
from PyQt6.QtWidgets import QDialog, QMessageBox, QVBoxLayout, QLabel, QProgressBar
from PyQt6.QtCore import QThread, pyqtSignal, QCoreApplication

from ..basic_game import BasicGame
from .crimsondesert.constants import (
    ASI_LOADER_DLLS,
    BIN64_DIR,
    GAME_PROCESS,
    MOD_SOURCE_DIR,
    PLUGIN_VERSION,
)
from .crimsondesert.mod_classify import (
    is_bin64_file,
    is_junk,
    is_paz_bundle,
    is_valid_root,
    remove_junk,
    unwrap,
)


class CrimsonDesertModDataChecker(mobase.ModDataChecker):

    def dataLooksValid(
        self, filetree: mobase.IFileTree
    ) -> mobase.ModDataChecker.CheckReturn:
        status = self._evaluate(filetree)
        if status != mobase.ModDataChecker.INVALID:
            return status
        current = filetree
        while len(current) == 1 and isinstance(current[0], mobase.IFileTree):
            child = current[0]
            if self._evaluate(child) != mobase.ModDataChecker.INVALID:
                return mobase.ModDataChecker.FIXABLE
            current = child
        return mobase.ModDataChecker.INVALID

    def fix(self, filetree: mobase.IFileTree) -> mobase.IFileTree:
        unwrap(filetree)
        remove_junk(filetree)
        self._normalize(filetree)
        return filetree

    def _evaluate(self, tree: mobase.IFileTree) -> mobase.ModDataChecker.CheckReturn:
        has_valid = False
        has_fixable = False
        for entry in tree:
            name_cf = entry.name().casefold()
            if is_junk(entry):
                has_fixable = True
                continue
            if isinstance(entry, mobase.IFileTree):
                if is_valid_root(name_cf):
                    has_valid = True
                elif entry.name().isdigit() and is_paz_bundle(entry):
                    has_valid = True
                else:
                    has_fixable = True
                continue
            if is_bin64_file(entry):
                has_fixable = True
                continue
            has_fixable = True
        if has_valid and not has_fixable:
            return mobase.ModDataChecker.VALID
        if has_valid or has_fixable:
            return mobase.ModDataChecker.FIXABLE
        return mobase.ModDataChecker.INVALID

    def _normalize(self, tree: mobase.IFileTree):
        for entry in list(tree):
            name = entry.name()
            name_cf = name.casefold()
            if isinstance(entry, mobase.IFileTree):
                if is_valid_root(name_cf):
                    continue
                # Keep numbered PAZ bundle dirs at root (generated or pre-built)
                if name.isdigit() and is_paz_bundle(entry):
                    continue
                tree.move(entry, f"{MOD_SOURCE_DIR}/")
                continue
            if is_bin64_file(entry):
                tree.move(entry, f"{BIN64_DIR}/")
                continue
            tree.move(entry, f"{MOD_SOURCE_DIR}/")


class _BuildThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(object)

    def __init__(self, builder, force: bool = False):
        super().__init__()
        self._builder = builder
        self._force = force

    def run(self):
        try:
            result = self._builder.build(
                logger=lambda msg: self.log_signal.emit(msg),
                on_progress=lambda c, t: self.progress_signal.emit(c, t),
                force=self._force,
            )
            self.finished_signal.emit(result)
        except Exception as e:
            self.finished_signal.emit(e)


class _AutoBuildDialog(QDialog):
    def __init__(self, parent, builder, force: bool = False):
        super().__init__(parent)
        self.setWindowTitle("PAZ Builder - Auto Build")
        self.setMinimumWidth(400)
        self.success = False
        self._worker = None

        self._label = QLabel("Building...", self)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)

        layout = QVBoxLayout(self)
        layout.addWidget(self._label)
        layout.addWidget(self._progress)

        self._worker = _BuildThread(builder, force=force)
        self._worker.log_signal.connect(lambda msg: self._label.setText(msg))
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, current, total):
        self._progress.setRange(0, total)
        self._progress.setValue(current)

    def _on_finished(self, result):
        if isinstance(result, Exception):
            self._label.setText(f"Build failed: {result}")
            self.success = False
        else:
            self.success = True
        if self._worker is not None:
            self._worker.wait()
        self.accept()


class CrimsonDesertGame(BasicGame):
    Name = "Crimson Desert Support Plugin"
    Author = "edp1096"
    Version = PLUGIN_VERSION

    GameName = "Crimson Desert"
    GameShortName = "crimsondesert"
    GameBinary = "bin64/CrimsonDesert.exe"
    GameDataPath = "%GAME_PATH%"
    GameSaveExtension = "save"
    GameDocumentsDirectory = "%USERPROFILE%/AppData/Local/Pearl Abyss/CD"
    GameSavesDirectory = "%GAME_DOCUMENTS%/save"
    GameSteamId = 3321460

    def init(self, organizer: mobase.IOrganizer) -> bool:
        super().init(organizer)
        self._organizer = organizer
        self._register_feature(CrimsonDesertModDataChecker())
        organizer.onAboutToRun(self._on_about_to_run)
        return True

    def executables(self):
        return super().executables()

    def executableForcedLoads(self) -> list[mobase.ExecutableForcedLoadSetting]:
        """Scan active mods for ASI loader DLLs and register them for force loading."""
        found = self._scan_asi_loader_dlls()
        return [
            mobase.ExecutableForcedLoadSetting(GAME_PROCESS, lib).withEnabled(True)
            for lib in found
        ]

    def _scan_asi_loader_dlls(self) -> list[str]:
        """Find ASI loader DLLs in active mods' bin64/ folders."""
        if self._organizer is None:
            return []
        mods_path = Path(self._organizer.modsPath())
        mod_list = self._organizer.modList()
        found: list[str] = []
        for mod_name in mod_list.allModsByProfilePriority():
            if not (mod_list.state(mod_name) & mobase.ModState.ACTIVE):
                continue
            bin64_dir = mods_path / mod_name / BIN64_DIR
            if not bin64_dir.is_dir():
                continue
            for f in bin64_dir.iterdir():
                if f.is_file() and f.name.casefold() in ASI_LOADER_DLLS:
                    lib_path = str(f).replace("\\", "/")
                    if lib_path not in found:
                        found.append(lib_path)
        return found

    def _on_about_to_run(self, executable: str) -> bool:
        if not self._organizer.pluginSetting(
            "Crimson Desert PAZ Builder", "auto_build_on_run"
        ):
                return True

        from .crimsondesert.builder import CrimsonDesertBuilder

        org = self._organizer
        game_path = Path(org.managedGame().gameDirectory().absolutePath())
        mods_path = Path(org.modsPath())
        overwrite_path = Path(org.overwritePath())
        profile_path = Path(org.profilePath())

        def get_active_mods():
            result = []
            mod_list = org.modList()
            for priority, mod_name in enumerate(
                mod_list.allModsByProfilePriority()
            ):
                if mod_list.state(mod_name) & mobase.ModState.ACTIVE:
                    result.append((mod_name, priority))
            return result

        builder = CrimsonDesertBuilder(
            game_path=game_path,
            mods_path=mods_path,
            overwrite_path=overwrite_path,
            profile_path=profile_path,
            get_active_mods=get_active_mods,
        )

        force = False
        ver_change = builder.check_game_version_changed()
        if ver_change:
            prev, cur = ver_change
            reply = QMessageBox.question(
                None, "Game Updated",
                f"Game version changed ({prev} → {cur}).\n"
                "Rebuild all mods to match the new game archives?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            force = (reply == QMessageBox.StandardButton.Yes)

        dialog = _AutoBuildDialog(None, builder, force=force)
        dialog.exec()

        return dialog.success

"""Crimson Desert Mod Installer for MO2 (IPluginInstallerSimple).

- ASI/DLL → bin64/
- PAZ bundles (numbered dir + pamt/paz) → root as-is
- Everything else → mod.mohidden/ (original preserved, no modification)
- Junk → stripped
- Conflict detection: similar mod names + game entry path overlaps
"""

from __future__ import annotations

import json
import shutil
import zipfile
from difflib import SequenceMatcher
from pathlib import Path

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import mobase

from basic_games.games.crimsondesert.constants import (
    BIN64_DIR,
    GAME_SHORT_NAME,
    MANIFEST_FILENAME,
    MOD_SOURCE_DIR,
    PLUGIN_VERSION_TUPLE,
)
from basic_games.games.crimsondesert.mod_classify import (
    is_bin64_file,
    is_bin64_mod,
    is_junk,
    is_paz_bundle,
    remove_junk,
    unwrap,
)



def _sanitize_dir_name(mod_name: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_ ") else "_" for c in mod_name).strip()


def _is_pure_paz_mod(tree) -> bool:
    """Check if mod contains ONLY PAZ bundles (no json/xml/loose files)."""
    for entry in tree:
        if isinstance(entry, mobase.IFileTree):
            if entry.name().isdigit() and is_paz_bundle(entry):
                continue
            if entry.name().casefold() == "meta":
                continue
            return False
        elif entry.isFile():
            if is_junk(entry):
                continue
            return False
    return True


def _normalize(tree, mod_name: str = ""):
    # ASI / ShaderToggler mod: everything goes to bin64/
    if is_bin64_mod(tree):
        for entry in list(tree):
            if isinstance(entry, mobase.IFileTree) and entry.name().casefold() == BIN64_DIR:
                continue
            tree.move(entry, f"{BIN64_DIR}/")
        return

    # Pure PAZ mod (only numbered dirs with .pamt/.paz): keep at root
    if _is_pure_paz_mod(tree):
        return

    source_dir = f"{MOD_SOURCE_DIR}_{_sanitize_dir_name(mod_name)}" if mod_name else MOD_SOURCE_DIR
    for entry in list(tree):
        name = entry.name()
        name_cf = name.casefold()

        # Already placed
        if isinstance(entry, mobase.IFileTree) and (name_cf == BIN64_DIR or name_cf.startswith(MOD_SOURCE_DIR)):
            continue

        # meta/ → strip (builder generates unified papgt)
        if isinstance(entry, mobase.IFileTree) and name_cf == "meta":
            tree.remove(name)
            continue

        # ASI/DLL → bin64/
        if is_bin64_file(entry):
            tree.move(entry, f"{BIN64_DIR}/")
            continue

        # Everything else (including PAZ mixed with other content) → _mod_{mod_name}/
        tree.move(entry, f"{source_dir}/")


# --- Multi-preset detection ---

def _has_mod_content(tree) -> bool:
    """Check if a directory contains mod content (JSON, PAZ, game files)."""
    for entry in tree:
        if isinstance(entry, mobase.IFileTree):
            if entry.name().isdigit() and is_paz_bundle(entry):
                return True
            if _has_mod_content(entry):
                return True
        elif entry.isFile():
            name_cf = entry.name().casefold()
            if name_cf.endswith(".json"):
                return True
            if name_cf.endswith(
                (".dds", ".xml", ".lua", ".csv", ".pabgb", ".pabgh")
            ):
                return True
    return False


def _detect_presets(tree) -> list[str] | None:
    """Detect if tree has multiple independent sub-mod directories."""
    candidates = []
    for entry in tree:
        if isinstance(entry, mobase.IFileTree):
            name_cf = entry.name().casefold()
            if name_cf == BIN64_DIR or name_cf.startswith(MOD_SOURCE_DIR):
                return None
            if _has_mod_content(entry):
                candidates.append(entry.name())
        elif entry.isFile() and not is_junk(entry):
            return None
    return candidates if len(candidates) >= 2 else None


def _find_zip_prefix(all_entries: list[str], preset_name: str) -> str | None:
    """Find the zip path prefix for a preset directory."""
    for entry in all_entries:
        parts = entry.replace("\\", "/").rstrip("/").split("/")
        for i, part in enumerate(parts):
            if part == preset_name:
                return "/".join(parts[: i + 1]) + "/"
    return None


class _PresetDialog(QDialog):
    """Dialog for selecting presets to install as separate mods."""

    SEPARATE = 0
    AS_ONE = 1
    CANCEL = 2

    def __init__(self, parent, mod_name: str, presets: list[str],
                 installed: set[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Crimson Desert Installer — Multiple Presets")
        self.setMinimumWidth(400)
        self.result_action = self.CANCEL
        self.selected_presets: list[str] = []
        installed = installed or set()

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            f"<b>{mod_name}</b> contains {len(presets)} presets.<br>"
            "Install each as a separate mod?",
        ))

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget()
        cb_layout = QVBoxLayout(container)
        self._checkboxes: list[tuple[str, QCheckBox]] = []
        for name in presets:
            already = name in installed
            label = f"{name}  (installed)" if already else name
            cb = QCheckBox(label, container)
            cb.setChecked(not already)
            cb_layout.addWidget(cb)
            self._checkboxes.append((name, cb))
        cb_layout.addStretch(1)
        scroll.setWidget(container)
        scroll.setMaximumHeight(300)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(self)
        btn_separate = buttons.addButton(
            "Install Separately", QDialogButtonBox.ButtonRole.AcceptRole)
        btn_one = buttons.addButton(
            "Install as One Mod", QDialogButtonBox.ButtonRole.ActionRole)
        btn_cancel = buttons.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.RejectRole)

        btn_separate.clicked.connect(self._do_separate)
        btn_one.clicked.connect(lambda: self._finish(self.AS_ONE))
        btn_cancel.clicked.connect(lambda: self._finish(self.CANCEL))
        layout.addWidget(buttons)

    def _do_separate(self):
        self.selected_presets = [
            name for name, cb in self._checkboxes if cb.isChecked()
        ]
        self._finish(self.SEPARATE)

    def _finish(self, action):
        self.result_action = action
        self.accept()


class _ConflictDialog(QDialog):
    """Dialog showing mod name similarity and game entry path conflicts."""

    SKIP = 0
    RENAME = 1
    CANCEL = 2

    def __init__(self, parent, mod_name: str,
                 similar_mods: list[tuple[str, bool]],
                 entry_conflicts: list[tuple[str, list[str]]]):
        super().__init__(parent)
        self.setWindowTitle("Crimson Desert Installer — Conflict Detected")
        self.setMinimumWidth(520)
        self.result_action = self.CANCEL

        layout = QVBoxLayout(self)

        header = QLabel(f"Installing: <b>{mod_name}</b>", self)
        layout.addWidget(header)

        body_parts: list[str] = []

        if similar_mods:
            body_parts.append("<b>Similar mods found:</b>")
            for name, active in similar_mods:
                status = "active" if active else "inactive"
                body_parts.append(f"&nbsp;&nbsp;• {name} ({status})")

        if entry_conflicts:
            body_parts.append("")
            body_parts.append("<b>Game file conflicts:</b>")
            for entry_path, mod_names in entry_conflicts:
                body_parts.append(f"&nbsp;&nbsp;<code>{entry_path}</code>")
                for mn in mod_names:
                    body_parts.append(f"&nbsp;&nbsp;&nbsp;&nbsp;→ {mn}")

        detail = QTextEdit(self)
        detail.setReadOnly(True)
        detail.setHtml("<br>".join(body_parts))
        detail.setMinimumHeight(200)
        layout.addWidget(detail)

        rename_row = QHBoxLayout()
        rename_row.addWidget(QLabel("Mod name:", self))
        self._name_edit = QLineEdit(mod_name, self)
        self._name_edit.textChanged.connect(self._on_name_changed)
        self._name_edit.returnPressed.connect(self._do_rename)
        rename_row.addWidget(self._name_edit)
        layout.addLayout(rename_row)

        buttons = QDialogButtonBox(self)
        self._btn_rename = buttons.addButton(
            "Rename", QDialogButtonBox.ButtonRole.AcceptRole)
        self._btn_rename.setEnabled(False)
        btn_skip = buttons.addButton(
            "Skip", QDialogButtonBox.ButtonRole.ActionRole)
        btn_cancel = buttons.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.RejectRole)

        self._btn_rename.clicked.connect(lambda: self._do_rename())
        btn_skip.clicked.connect(lambda: self._finish(self.SKIP))
        btn_cancel.clicked.connect(lambda: self._finish(self.CANCEL))
        layout.addWidget(buttons)

        self._original_name = mod_name

        self.renamed_name = mod_name

    def _on_name_changed(self, text):
        changed = text.strip() != self._original_name and bool(text.strip())
        self._btn_rename.setEnabled(changed)

    def _do_rename(self):
        text = self._name_edit.text().strip()
        if text and text != self._original_name:
            self.renamed_name = text
            self._finish(self.RENAME)

    def _finish(self, action):
        self.result_action = action
        self.accept()


# --- Conflict detection helpers ---

_SIMILARITY_THRESHOLD = 0.6


def _find_similar_mods(
    mod_name: str, mod_list: mobase.IModList,
) -> list[tuple[str, bool]]:
    """Find existing mods with similar (but not identical) names."""
    results: list[tuple[str, bool]] = []
    incoming_cf = mod_name.casefold()
    for existing in mod_list.allMods():
        existing_cf = existing.casefold()
        if existing_cf == incoming_cf:
            continue  # exact match → let MO2 handle it
        ratio = SequenceMatcher(None, incoming_cf, existing_cf).ratio()
        if ratio >= _SIMILARITY_THRESHOLD:
            active = bool(mod_list.state(existing) & mobase.ModState.ACTIVE)
            results.append((existing, active))
    return results


def _find_entry_conflicts(
    mod_name: str, new_tree, organizer: mobase.IOrganizer,
) -> list[tuple[str, list[str]]]:
    """Find game entry path conflicts using manifest cache + live scan."""
    # Collect entry paths from the incoming mod tree
    incoming_paths: set[str] = set()
    for entry in _iter_tree(new_tree):
        if not entry.isFile():
            continue
        if is_junk(entry):
            continue
        parts = _tree_path(entry)
        if not parts:
            continue
        # Strip _mod_* prefix to get game-relative path
        first = parts[0].casefold()
        if first.startswith(MOD_SOURCE_DIR):
            parts = parts[1:]
        elif first == BIN64_DIR:
            continue  # bin64 files don't conflict at game entry level
        else:
            continue
        if parts:
            from basic_games.games.crimsondesert.builder import (
                _resolve_loose_entry_path,
            )
            resolved = _resolve_loose_entry_path(tuple(parts))
            if resolved:
                incoming_paths.add(resolved.casefold())

    if not incoming_paths:
        return []

    # Load cached entry_paths from manifest
    existing_entries: dict[str, list[str]] = {}  # entry_path -> [mod_names]
    profile_path = Path(organizer.profilePath())
    manifest_path = profile_path / MANIFEST_FILENAME
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for mname, paths in manifest.get("entry_paths", {}).items():
                if mname == str(mod_name):
                    continue
                for p in paths:
                    existing_entries.setdefault(p.casefold(), []).append(mname)
        except Exception:
            pass

    # Also do live scan for mods not yet in manifest
    mods_path = Path(organizer.modsPath())
    mod_list = organizer.modList()
    manifest_mod_names = set(existing_entries.get("__scanned__", []))
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_mod_names = set(manifest.get("entry_paths", {}).keys())
        except Exception:
            pass

    for existing_mod in mod_list.allMods():
        if existing_mod == str(mod_name):
            continue
        if existing_mod in manifest_mod_names:
            continue
        if not (mod_list.state(existing_mod) & mobase.ModState.ACTIVE):
            continue
        mod_dir = mods_path / existing_mod
        # Quick scan: look for _mod_* source dirs
        for d in mod_dir.iterdir() if mod_dir.is_dir() else []:
            if d.is_dir() and d.name.startswith(MOD_SOURCE_DIR):
                for f in d.rglob("*"):
                    if not f.is_file():
                        continue
                    rel = f.relative_to(d)
                    from basic_games.games.crimsondesert.builder import (
                        _resolve_loose_entry_path,
                    )
                    resolved = _resolve_loose_entry_path(tuple(str(p) for p in rel.parts))
                    if resolved:
                        existing_entries.setdefault(
                            resolved.casefold(), []
                        ).append(existing_mod)
                break  # only first _mod_* dir

    # Find overlaps
    conflicts: list[tuple[str, list[str]]] = []
    for path_cf in sorted(incoming_paths):
        mods_with_path = existing_entries.get(path_cf, [])
        if mods_with_path:
            conflicts.append((path_cf, sorted(set(mods_with_path))))
    return conflicts


def _iter_tree(tree):
    """Recursively iterate all entries in an IFileTree."""
    for entry in tree:
        yield entry
        if isinstance(entry, mobase.IFileTree):
            yield from _iter_tree(entry)


def _tree_path(entry) -> list[str]:
    """Get path parts for a file tree entry."""
    parts: list[str] = []
    current = entry
    while current is not None:
        name = current.name()
        if name:
            parts.append(name)
        try:
            current = current.parent()
        except Exception:
            break
        if current is None or not current.name():
            break
    parts.reverse()
    return parts


class CrimsonDesertInstaller(mobase.IPluginInstallerSimple):
    def __init__(self):
        super().__init__()
        self._organizer = None
        self._parentWidget = None
        self._archive_path: str | None = None

    def init(self, organizer):
        self._organizer = organizer
        return True

    def name(self):
        return "Crimson Desert Installer"

    def author(self):
        return "edp1096"

    def description(self):
        return self.__tr("Installs Crimson Desert mods with conflict detection.")

    def version(self):
        return mobase.VersionInfo(*PLUGIN_VERSION_TUPLE)

    def isActive(self):
        if self._organizer is None:
            return False
        try:
            game = self._organizer.managedGame()
            return bool(game) and game.gameShortName().casefold() == GAME_SHORT_NAME
        except Exception:
            return False

    def settings(self):
        return []

    def priority(self):
        return 999

    def isManualInstaller(self):
        return False

    def isArchiveSupported(self, tree):
        return self.isActive() and bool(len(tree))

    def setParentWidget(self, widget):
        self._parentWidget = widget

    def onInstallationStart(self, archive, reinstallation, current_mod):
        self._archive_path = str(archive) if archive else None
        return None

    def onInstallationEnd(self, result, new_mod):
        self._archive_path = None
        return None

    def install(self, name, tree, version, nexus_id):
        new_tree = tree.createOrphanTree()
        new_tree.merge(tree)
        unwrap(new_tree)
        remove_junk(new_tree)

        # --- Multi-preset detection ---
        presets = _detect_presets(new_tree)
        if presets and self._organizer:
            result = self._install_multi_preset(
                str(name), presets, new_tree)
            if result is not None:
                return result

        _normalize(new_tree, str(name))

        # --- Conflict detection ---
        if self._organizer is not None:
            mod_list = self._organizer.modList()
            mod_name = str(name)

            similar = _find_similar_mods(mod_name, mod_list)
            entry_conflicts = _find_entry_conflicts(
                mod_name, new_tree, self._organizer,
            )

            if similar or entry_conflicts:
                dialog = _ConflictDialog(
                    self._parentWidget, mod_name,
                    similar, entry_conflicts,
                )
                dialog.exec()
                action = dialog.result_action

                if action == _ConflictDialog.CANCEL:
                    return mobase.InstallResult.CANCELED
                elif action == _ConflictDialog.SKIP:
                    pass  # proceed with installation as-is
                elif action == _ConflictDialog.RENAME:
                    new_name = dialog.renamed_name
                    name.update(new_name, mobase.GuessQuality.USER)
                    # Rename _mod_* directory in the already-normalized tree
                    old_source = f"{MOD_SOURCE_DIR}_{_sanitize_dir_name(mod_name)}"
                    new_source = f"{MOD_SOURCE_DIR}_{_sanitize_dir_name(new_name)}"
                    for entry in list(new_tree):
                        if (isinstance(entry, mobase.IFileTree)
                                and entry.name() == old_source):
                            # Move all children to new dir name
                            for child in list(entry):
                                new_tree.move(child, f"{new_source}/")
                            new_tree.remove(old_source)
                            break

        return new_tree

    @staticmethod
    def _get_archive_mod_name(archive_path: Path) -> str:
        """Get clean mod name from .meta file or archive filename."""
        meta_file = archive_path.parent / (archive_path.name + ".meta")
        if meta_file.is_file():
            try:
                for line in meta_file.read_text(encoding="utf-8").splitlines():
                    if line.startswith("name="):
                        return line[5:].strip()
            except Exception:
                pass
        return archive_path.stem

    def _resolve_archive_path(self) -> Path | None:
        """Resolve archive file path from onInstallationStart."""
        if not self._archive_path:
            return None
        path = Path(self._archive_path)
        if path.is_file():
            return path
        # onInstallationStart might give just filename
        if self._organizer:
            for get_dir in ("downloadsPath", "basePath"):
                try:
                    base = Path(getattr(self._organizer, get_dir)())
                    if get_dir == "basePath":
                        base = base / "downloads"
                    candidate = base / path.name
                    if candidate.is_file():
                        return candidate
                except Exception:
                    pass
        return None

    def _install_multi_preset(
        self, base_name: str, presets: list[str],
        tree: mobase.IFileTree,
    ) -> mobase.InstallResult | None:
        """Show preset dialog and extract selected presets as separate mods."""
        mods_path = Path(self._organizer.modsPath())
        installed = {
            p for p in presets
            if (mods_path / f"{base_name} - {p}").is_dir()
        }

        dialog = _PresetDialog(
            self._parentWidget, base_name, presets, installed)
        dialog.exec()

        if dialog.result_action == _PresetDialog.AS_ONE:
            return None  # fall through to normal install
        if dialog.result_action == _PresetDialog.CANCEL:
            return mobase.InstallResult.CANCELED

        selected = dialog.selected_presets
        if not selected:
            return mobase.InstallResult.CANCELED

        archive_path = self._resolve_archive_path()
        if not archive_path:
            return None

        # Use clean name from .meta or archive filename, not MO2's GuessedString
        base_name = self._get_archive_mod_name(archive_path) or base_name

        any_created = False
        try:
            with zipfile.ZipFile(str(archive_path)) as zf:
                all_entries = zf.namelist()

                for preset_name in selected:
                    prefix = _find_zip_prefix(all_entries, preset_name)
                    if not prefix:
                        continue

                    mod_name = f"{base_name} - {preset_name}"
                    source_name = (
                        f"{MOD_SOURCE_DIR}_{_sanitize_dir_name(mod_name)}"
                    )
                    source_dir = mods_path / mod_name / source_name

                    if source_dir.is_dir():
                        shutil.rmtree(source_dir)

                    for info in zf.infolist():
                        if info.file_size == 0 and info.compress_size == 0:
                            continue
                        if not info.filename.startswith(prefix):
                            continue
                        rel = info.filename[len(prefix):].rstrip("/")
                        if not rel:
                            continue
                        if _should_skip_preset_entry(rel):
                            continue

                        dest = source_dir / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(zf.read(info))
                        any_created = True

                    # Write meta.ini
                    if any_created:
                        _write_meta_ini(
                            mods_path / mod_name,
                            archive_path,
                        )

        except (zipfile.BadZipFile, OSError):
            return None

        if not any_created:
            return None

        try:
            self._organizer.refresh()
        except Exception:
            pass

        return mobase.InstallResult.CANCELED

    def __tr(self, value):
        return QCoreApplication.translate("CrimsonDesertInstaller", value)


def _write_meta_ini(mod_dir: Path, archive_path: Path):
    """Write meta.ini for a manually created mod, using download .meta file."""
    mod_dir.mkdir(parents=True, exist_ok=True)
    ini_path = mod_dir / "meta.ini"

    # Read download .meta file (INI format, same dir as archive)
    meta_file = archive_path.parent / (archive_path.name + ".meta")
    meta: dict[str, str] = {}
    if meta_file.is_file():
        try:
            for line in meta_file.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.startswith("["):
                    k, _, v = line.partition("=")
                    meta[k.strip()] = v.strip()
        except Exception:
            pass

    lines = [
        "[General]",
        f"gameName={meta.get('gameName', GAME_SHORT_NAME)}",
        f"installationFile={archive_path.name}",
    ]

    for key in ("modID", "version", "modName", "repository",
                "category", "nexusDescription", "url"):
        if key in meta:
            lines.append(f"{key.lower() if key == 'modID' else key}={meta[key]}")

    modid = meta.get("modID", "")
    fileid = meta.get("fileID", "")
    if modid:
        lines.extend([
            "",
            "[installedFiles]",
            f"1\\modid={modid}",
            f"1\\fileid={fileid}",
            "size=1",
        ])

    ini_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _should_skip_preset_entry(rel: str) -> bool:
    """Check if a relative path should be skipped during preset extraction."""
    if not rel.replace("\\", "/").split("/"):
        return True
    return False


def createPlugin():
    return CrimsonDesertInstaller()

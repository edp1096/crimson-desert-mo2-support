"""Mod file classification helpers for Crimson Desert MO2 plugins.

Shared by game plugin (ModDataChecker) and installer.
"""

from __future__ import annotations

import mobase

from .constants import BIN64_DIR, MOD_SOURCE_DIR

# --- Constants ---

JUNK_FILENAMES = {
    "readme", "readme.txt", "readme.md",
    "changelog", "changelog.txt", "changelog.md",
    "license", "license.txt", "license.md",
}
JUNK_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
BIN64_SUFFIXES = {".asi", ".addon64", ".dll"}


# --- Classification ---

def is_junk(entry: mobase.FileTreeEntry) -> bool:
    name_cf = entry.name().casefold()
    if name_cf in JUNK_FILENAMES:
        return True
    if entry.isFile() and "." in name_cf:
        if f".{name_cf.rsplit('.', 1)[1]}" in JUNK_SUFFIXES:
            return True
    return False


def is_bin64_file(entry: mobase.FileTreeEntry) -> bool:
    if not entry.isFile():
        return False
    name_cf = entry.name().casefold()
    if "." in name_cf and f".{name_cf.rsplit('.', 1)[1]}" in BIN64_SUFFIXES:
        return True
    return False


def is_bin64_mod(tree: mobase.IFileTree) -> bool:
    """Check if tree contains .asi or .addon64 or .dll → entire mod goes to bin64."""
    for entry in tree:
        if isinstance(entry, mobase.IFileTree):
            if is_bin64_mod(entry):
                return True
        elif entry.isFile():
            name_cf = entry.name().casefold()
            if name_cf.endswith((".asi", ".addon64", ".dll")):
                return True
    return False


def is_paz_bundle(tree: mobase.IFileTree) -> bool:
    for entry in tree:
        if not isinstance(entry, mobase.IFileTree):
            if entry.name().casefold().endswith((".pamt", ".paz")):
                return True
    return False


def is_valid_root(name_cf: str) -> bool:
    return name_cf == BIN64_DIR or name_cf.startswith(MOD_SOURCE_DIR)


# --- Tree operations ---

def unwrap(tree: mobase.IFileTree):
    """Unwrap single-child wrapper directories, skipping junk."""
    while True:
        real = [e for e in tree if not is_junk(e)]
        if len(real) != 1 or not isinstance(real[0], mobase.IFileTree):
            break
        child = real[0]
        name_cf = child.name().casefold()
        if is_valid_root(name_cf):
            break
        # Stop at numbered dirs (game archive bundles) or "files/" (loose file root)
        if child.name().isdigit():
            break
        if name_cf == "files":
            break
        tree.merge(child)
        child.detach()
        for e in list(tree):
            if is_junk(e):
                tree.remove(e.name())


def remove_junk(tree: mobase.IFileTree):
    for entry in list(tree):
        if isinstance(entry, mobase.IFileTree):
            remove_junk(entry)
            if len(entry) == 0:
                tree.remove(entry.name())
            continue
        if is_junk(entry):
            tree.remove(entry.name())

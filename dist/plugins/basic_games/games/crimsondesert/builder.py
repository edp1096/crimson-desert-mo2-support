"""Crimson Desert mod builder — thin orchestrator.

Scans MO2 mod directories, delegates archive operations to the native
core library (paz_core.dll), and manages bundle numbering / caching.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .constants import (
    BIN64_DIR, MANIFEST_FILENAME, META_DIR, MOD_SOURCE_DIR,
    PAPGT_FILENAME, PATHC_FILENAME, PAVER_FILENAME,
)
from . import core
from .util import BuildLogger, clean_overwrite_meta

ProgressCallback = Callable[[int, int], None]


class BuildError(RuntimeError):
    pass


@dataclass(slots=True)
class JsonPatchFile:
    path: Path
    patches: list[dict]


@dataclass(slots=True)
class LooseFile:
    path: Path
    entry_path: str


@dataclass(slots=True)
class PazInMod:
    source_dir: Path


@dataclass(slots=True)
class ModInfo:
    name: str
    path: Path
    mod_type: str
    priority: int
    bundle_numbers: list[int] = field(default_factory=list)
    json_patches: list[JsonPatchFile] = field(default_factory=list)
    loose_files: list[LooseFile] = field(default_factory=list)
    paz_in_mod: list[PazInMod] = field(default_factory=list)


@dataclass(slots=True)
class BuildResult:
    built_count: int
    warnings: list[str]


def _noop_logger(msg: str):
    pass


def _resolve_loose_entry_path(rel_parts: tuple[str, ...]) -> str | None:
    return core.resolve_mod_file_path(rel_parts)


def _parse_json_mod(path: Path) -> list[dict] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    patches = data.get("patches")
    if not isinstance(patches, list) or not patches:
        return None
    valid = [
        p for p in patches
        if isinstance(p, dict)
        and isinstance(p.get("game_file"), str)
        and isinstance(p.get("changes"), list) and p["changes"]
    ]
    return valid if valid else None


class CrimsonDesertBuilder:
    def __init__(self, game_path: Path, mods_path: Path, overwrite_path: Path,
                 profile_path: Path,
                 get_active_mods: Callable[[], list[tuple[str, int]]]):
        self._game_path = game_path
        self._mods_path = mods_path
        self._overwrite_path = overwrite_path
        self._profile_path = profile_path
        self._get_active_mods = get_active_mods
        self._game_index: core.GameArchiveIndex | None = None
        self._dds_meta_for_pathc: list[tuple[str, bytes, tuple[int, int, int, int]]] = []
        self._resolved_paths: dict[str, dict[str, str]] = {}

    def _ensure_index(self):
        if self._game_index is None:
            self._game_index = core.GameArchiveIndex(self._game_path)

    def scan_mods(self) -> list[ModInfo]:
        mods = []
        for mod_name, priority in self._get_active_mods():
            mod_path = self._mods_path / mod_name
            if not mod_path.is_dir():
                continue
            info = self._classify_mod(mod_name, mod_path, priority)
            if info is not None:
                mods.append(info)
        return mods

    @staticmethod
    def _find_source_dir(mod_path: Path) -> Path | None:
        for d in mod_path.iterdir():
            if d.is_dir() and d.name.startswith(MOD_SOURCE_DIR):
                return d
        return None

    def _classify_mod(self, name: str, path: Path, priority: int) -> ModInfo | None:
        mod_dir = self._find_source_dir(path)
        has_bin64 = (path / BIN64_DIR).is_dir()
        has_paz = any(
            d.is_dir() and d.name.isdigit() and any(d.glob("*.pamt"))
            for d in path.iterdir()
            if d.is_dir() and d.name != BIN64_DIR
              and not d.name.startswith(MOD_SOURCE_DIR)
        )
        has_mod_dir = mod_dir is not None and mod_dir.is_dir()

        if not has_mod_dir and not has_paz and not has_bin64:
            return None
        if has_paz and not has_mod_dir:
            return ModInfo(name=name, path=path, mod_type="paz_bundle", priority=priority)
        if has_bin64 and not has_mod_dir and not has_paz:
            return ModInfo(name=name, path=path, mod_type="asi", priority=priority)
        if not has_mod_dir:
            return None

        json_patches: list[JsonPatchFile] = []
        loose_files: list[LooseFile] = []
        paz_in_mod: list[PazInMod] = []
        skip_dirs: set[str] = {META_DIR.casefold()}

        for d in mod_dir.iterdir():
            if d.is_dir() and d.name.isdigit() and any(d.glob("*.pamt")):
                paz_in_mod.append(PazInMod(source_dir=d))
                skip_dirs.add(d.name.casefold())

        for f in sorted(mod_dir.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(mod_dir)
            if not rel.parts:
                continue
            if rel.parts[0].casefold() in skip_dirs:
                continue
            if f.suffix.casefold() in (".pamt", ".paz"):
                continue
            if f.name.casefold() in ("manifest.json", "mod.json", "modinfo.json"):
                continue

            if f.suffix.casefold() == ".json":
                patches = _parse_json_mod(f)
                if patches is not None:
                    json_patches.append(JsonPatchFile(path=f, patches=patches))
                    continue
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and "modinfo" in data and "patches" not in data:
                        continue
                except Exception:
                    pass

            entry_path = _resolve_loose_entry_path(rel.parts)
            if entry_path:
                loose_files.append(LooseFile(path=f, entry_path=entry_path))

        if not json_patches and not loose_files and not paz_in_mod:
            return None

        if json_patches and loose_files:
            mod_type = "mixed"
        elif json_patches:
            mod_type = "json_patch"
        elif loose_files:
            mod_type = "loose_files"
        elif paz_in_mod:
            mod_type = "paz_bundle"
        else:
            return None

        return ModInfo(name=name, path=path, mod_type=mod_type,
                       priority=priority, json_patches=json_patches,
                       loose_files=loose_files, paz_in_mod=paz_in_mod)

    def build(self, logger: BuildLogger | None = None,
              on_progress: ProgressCallback | None = None,
              force: bool = False) -> BuildResult:
        log = logger or _noop_logger
        progress = on_progress or (lambda c, t: None)
        warnings: list[str] = []
        self._dds_meta_for_pathc = []
        self._resolved_paths = {}

        clean_overwrite_meta(self._overwrite_path)

        prev = self._load_manifest()
        prev_fp = prev.get("fingerprints", {})
        prev_bn = prev.get("bundles", {})
        prev_rp = prev.get("resolved_paths", {})

        for mn, nums in prev.get("copied_paz", {}).items():
            if isinstance(nums, int):
                nums = [nums]
            existing = prev_bn.get(mn)
            if existing is None:
                prev_bn[mn] = nums
            elif isinstance(existing, int):
                prev_bn[mn] = [existing] + nums
            elif isinstance(existing, list):
                prev_bn[mn] = existing + nums

        if force:
            log("Force rebuild: cleaning all...")
            self.flush(logger=log)
            prev_fp, prev_bn, prev_rp = {}, {}, {}
        else:
            self._flush_stale(logger=log)

        mods = self.scan_mods()
        buildable = [
            m for m in mods
            if m.mod_type in ("json_patch", "loose_files", "mixed") or m.paz_in_mod
        ]

        if not buildable:
            self._generate_papgt(mods, log)
            log("No buildable mods found.")
            return BuildResult(built_count=0, warnings=warnings)

        progress(0, len(buildable))
        occupied = self._scan_occupied_numbers()
        next_num = max(occupied, default=35) + 1

        def alloc():
            nonlocal next_num
            if next_num > 9999:
                raise BuildError("Bundle number exceeded 9999.\nPlease Flush and Build again.")
            n = next_num
            next_num += 1
            return n

        for mi in sorted(buildable, key=lambda m: m.priority, reverse=True):
            needs_build = bool(mi.json_patches or mi.loose_files)
            total_needed = (1 if needs_build else 0) + len(mi.paz_in_mod)
            prev_nums = prev_bn.get(mi.name, [])
            if isinstance(prev_nums, int):
                prev_nums = [prev_nums]
            if len(prev_nums) == total_needed:
                mi.bundle_numbers = list(prev_nums)
                for n in prev_nums:
                    occupied.add(n)
            else:
                mi.bundle_numbers = [alloc() for _ in range(total_needed)]

        step = 0
        built_count = 0
        skipped = 0

        for mi in buildable:
            needs_build = bool(mi.json_patches or mi.loose_files)
            idx = 0

            if needs_build:
                bnum = mi.bundle_numbers[idx]
                idx += 1
                bdir = mi.path / f"{bnum:04d}"
                fp = self._compute_mod_fingerprint(mi)

                if fp and fp == prev_fp.get(mi.name, "") and bdir.is_dir() and any(bdir.glob("*.pamt")):
                    log(f"Cached:    {mi.name} (unchanged)")
                    self._resolve_cached_dds(mi, prev_rp.get(mi.name))
                    skipped += 1
                else:
                    try:
                        self._build_mod(mi, bnum, log)
                        built_count += 1
                    except Exception as e:
                        warnings.append(f"Failed to build {mi.name}: {e}")
                        log(f"ERROR:     {mi.name}: {e}")

            for paz in mi.paz_in_mod:
                cnum = mi.bundle_numbers[idx]
                idx += 1
                dest = mi.path / f"{cnum:04d}"
                if not dest.exists():
                    shutil.copytree(str(paz.source_dir), str(dest))
                    log(f"PAZ copy:  {mi.name}/{paz.source_dir.name}/ -> {cnum:04d}/")
                    built_count += 1
                else:
                    log(f"Cached:    {mi.name}/{cnum:04d}/ (exists)")

            step += 1
            progress(step, len(buildable))

        self._generate_papgt(mods, log)
        self._generate_pathc(log)
        self._save_manifest(mods)

        if skipped:
            log(f"Skipped {skipped} cached mod(s).")
        return BuildResult(built_count=built_count, warnings=warnings)

    def _build_mod(self, mi: ModInfo, build_num: int, log: BuildLogger):
        log(f"Building:  {mi.name} ({mi.mod_type})")
        self._ensure_index()
        bdir = mi.path / f"{build_num:04d}"
        bdir.mkdir(parents=True, exist_ok=True)

        paz_payload = bytearray()
        packed: list[dict] = []

        for jpf in mi.json_patches:
            self._process_patches(jpf, paz_payload, packed, log)

        for lf in mi.loose_files:
            self._process_loose(lf, mi.name, paz_payload, packed, log)

        if not packed:
            log(f"Warning: No packable content in {mi.name}")
            if bdir.is_dir() and not any(bdir.iterdir()):
                bdir.rmdir()
            return

        paz_bytes = bytes(paz_payload)
        (bdir / "0.paz").write_bytes(paz_bytes)

        import ctypes as _ct
        entries_for_pamt = [
            {"path": p["path"], "paz_file": "0.paz", "offset": p["offset"],
             "comp_size": p["comp_size"], "orig_size": p["orig_size"],
             "flags": p["flags"], "paz_index": 0}
            for p in packed
        ]
        paz_infos = [[0, core.payload_checksum(paz_bytes), len(paz_bytes)]]
        lib = core._load_dll()
        out_len = _ct.c_int(0)
        ptr = lib.PazCoreBuildPamt(
            core._enc(json.dumps(entries_for_pamt)),
            core._enc(json.dumps(paz_infos)),
            0x610E0232, _ct.byref(out_len),
        )
        pamt_bytes = core._buf(ptr, out_len.value)
        (bdir / "0.pamt").write_bytes(pamt_bytes)

        log(f"Built:     {mi.name} -> {bdir.name}/ "
            f"({len(packed)} entries, {len(paz_bytes)} bytes)")

    def _process_patches(self, jpf: JsonPatchFile, payload: bytearray,
                         packed: list[dict], log: BuildLogger):
        for patch in jpf.patches:
            game_file = core.normalize_path(patch["game_file"])
            source_group = patch.get("source_group")
            changes = patch.get("changes", [])

            light = self._game_index.find(game_file, source_group)
            if light is None:
                log(f"  Warning: {game_file} not found")
                continue

            bundle = core.read_archive_index(
                str(self._game_path / light.group / "0.pamt"))
            source = None
            key = core.normalize_path(game_file).casefold()
            for e in bundle.entries:
                if core.normalize_path(e.path).casefold() == key:
                    source = e
                    break
            if source is None:
                basename = key.rsplit("/", 1)[-1] if "/" in key else key
                for e in bundle.entries:
                    if core.normalize_path(e.path).casefold().endswith("/" + basename):
                        source = e
                        break
            if source is None:
                log(f"  Warning: {game_file} not found in bundle {light.group}")
                continue

            try:
                data = core.extract_file(source)
                data = core.apply_hex_patches(data, changes)
                packed_data, flags = core.pack_file(data, source.flags, source.path)
            except Exception as e:
                log(f"  Warning: Patch failed for {game_file}: {e}")
                continue

            self._append(payload, packed, source.path, data, packed_data, flags)
            log(f"  Patched: {game_file} ({len(changes)} changes, {jpf.path.name})")

    def _process_loose(self, lf: LooseFile, mod_name: str, payload: bytearray,
                       packed: list[dict], log: BuildLogger):
        file_data = lf.path.read_bytes()
        original_path = lf.entry_path

        light = self._game_index.find(lf.entry_path)
        flags = light.flags if light else core.guess_flags(lf.entry_path)
        if light:
            lf.entry_path = light.path
        self._resolved_paths.setdefault(mod_name, {})[original_path] = lf.entry_path

        if lf.entry_path.lower().endswith(".dds") and len(file_data) >= 128:
            try:
                rec = core.dds_template_record(file_data)
                meta = core.dds_metadata(file_data)
                self._dds_meta_for_pathc.append((lf.entry_path, rec, meta))
            except Exception:
                pass

        try:
            packed_data, actual_flags = core.pack_file(file_data, flags, lf.entry_path)
        except Exception as e:
            log(f"  Warning: Pack failed for {lf.entry_path}: {e}")
            return

        self._append(payload, packed, lf.entry_path, file_data, packed_data, actual_flags)
        log(f"  Packed: {lf.entry_path}")

    def _append(self, payload: bytearray, packed: list[dict],
                path: str, plaintext: bytes, data: bytes, flags: int):
        offset = len(payload)
        payload.extend(data)
        pad = (16 - (len(payload) % 16)) % 16
        if pad:
            payload.extend(b"\x00" * pad)
        packed.append({
            "path": core.normalize_path(path),
            "offset": offset, "comp_size": len(data),
            "orig_size": len(plaintext), "flags": flags,
        })

    def _resolve_cached_dds(self, mi: ModInfo, cached: dict[str, str] | None = None):
        for lf in mi.loose_files:
            if cached and lf.entry_path in cached:
                lf.entry_path = cached[lf.entry_path]
            if not lf.entry_path.lower().endswith(".dds"):
                continue
            try:
                data = lf.path.read_bytes()
                if len(data) >= 128:
                    rec = core.dds_template_record(data)
                    meta = core.dds_metadata(data)
                    self._dds_meta_for_pathc.append((lf.entry_path, rec, meta))
            except Exception:
                pass

    def _flush_stale(self, logger: BuildLogger | None = None):
        log = logger or _noop_logger
        manifest = self._load_manifest()
        prev_bn = manifest.get("bundles", {})
        prev_fp = manifest.get("fingerprints", {})
        active = {name for name, _ in self._get_active_mods()}
        removed = 0

        for mn, nums in prev_bn.items():
            if isinstance(nums, int):
                nums = [nums]
            mp = self._mods_path / mn
            if mn not in active:
                continue
            src = self._find_source_dir(mp)
            if src is None:
                continue
            if self._fingerprint_dir(src) != prev_fp.get(mn, ""):
                for n in nums:
                    bd = mp / f"{int(n):04d}"
                    if bd.is_dir():
                        shutil.rmtree(bd)
                        log(f"Flushed (changed):  {mn}/{int(n):04d}/")
                        removed += 1

        for mn, nums in manifest.get("copied_paz", {}).items():
            if isinstance(nums, int):
                nums = [nums]
            mp = self._mods_path / mn
            for n in nums:
                bd = mp / f"{int(n):04d}"
                if bd.is_dir():
                    shutil.rmtree(bd)
                    log(f"Flushed (legacy):   {mn}/{int(n):04d}/")
                    removed += 1

        if removed:
            log(f"Flushed {removed} stale bundle(s).")

    def flush(self, logger: BuildLogger | None = None):
        log = logger or _noop_logger
        manifest = self._load_manifest()
        all_nums: dict[str, list[int]] = {}
        for mn, nums in manifest.get("bundles", {}).items():
            if isinstance(nums, int):
                nums = [nums]
            all_nums.setdefault(mn, []).extend(nums)
        for mn, nums in manifest.get("copied_paz", {}).items():
            if isinstance(nums, int):
                nums = [nums]
            all_nums.setdefault(mn, []).extend(nums)

        removed = 0
        for mn, nums in all_nums.items():
            mp = self._mods_path / mn
            for n in nums:
                bd = mp / f"{int(n):04d}"
                if bd.is_dir():
                    shutil.rmtree(bd)
                    log(f"Removed:            {mn}/{int(n):04d}/")
                    removed += 1

        clean_overwrite_meta(self._overwrite_path, log)
        mpath = self._manifest_path()
        if mpath.is_file():
            mpath.unlink()
        ow_meta = self._overwrite_path / META_DIR
        if ow_meta.is_dir() and not any(ow_meta.iterdir()):
            ow_meta.rmdir()
        if removed:
            log(f"Flushed {removed} bundle(s).")

    def has_orphaned_bundles(self) -> bool:
        for d in self._mods_path.iterdir():
            if not d.is_dir() or not self._find_source_dir(d):
                continue
            for sub in d.iterdir():
                if sub.is_dir() and sub.name.isdigit() and len(sub.name) == 4 and int(sub.name) >= 36:
                    return True
        return False

    def remove_generated_bundles(self, logger: BuildLogger | None = None):
        log = logger or _noop_logger
        removed = 0
        for d in self._mods_path.iterdir():
            if not d.is_dir() or not self._find_source_dir(d):
                continue
            for sub in d.iterdir():
                if sub.is_dir() and sub.name.isdigit() and len(sub.name) == 4 and int(sub.name) >= 36:
                    shutil.rmtree(sub)
                    log(f"Removed:            {d.name}/{sub.name}/")
                    removed += 1
        clean_overwrite_meta(self._overwrite_path, log)
        mpath = self._manifest_path()
        if mpath.is_file():
            mpath.unlink()
        log(f"Removed {removed} generated bundle(s)." if removed else "No generated bundles found.")

    def _generate_papgt(self, mods: list[ModInfo], log: BuildLogger):
        base = self._game_path / META_DIR / PAPGT_FILENAME
        if not base.exists():
            log(f"Warning: {base} not found")
            return
        try:
            template = core.read_registry_template(str(base))
        except Exception as e:
            log(f"Error: Cannot parse base papgt: {e}")
            return

        names: list[str] = []
        crc_map: dict[str, int] = {}
        all_bundles: list[tuple[str, Path]] = []

        for m in mods:
            for num in m.bundle_numbers:
                bn = f"{num:04d}"
                pamt = m.path / bn / "0.pamt"
                if pamt.is_file():
                    all_bundles.append((bn, pamt))

        for m in mods:
            for d in m.path.iterdir():
                if d.is_dir() and d.name.isdigit() and not d.name.startswith(MOD_SOURCE_DIR) and d.name != BIN64_DIR:
                    pamt = d / "0.pamt"
                    if pamt.is_file() and not any(bn == d.name for bn, _ in all_bundles):
                        all_bundles.append((d.name, pamt))

        for bn, pamt in all_bundles:
            if not pamt.is_file():
                continue
            try:
                crc_map[bn] = core.read_index_checksum(str(pamt))
                if bn not in names:
                    names.append(bn)
            except Exception as e:
                log(f"Warning: Cannot read CRC for {bn}: {e}")

        if not names:
            log("No mod bundles to register")
            return

        try:
            data = core.build_registry_bytes(template, names, crc_map)
        except Exception as e:
            raise BuildError(str(e)) from e

        out = self._overwrite_path / META_DIR
        out.mkdir(parents=True, exist_ok=True)
        (out / PAPGT_FILENAME).write_bytes(data)
        log(f"Generated {META_DIR}/{PAPGT_FILENAME} ({len(names)} bundle(s))")

    def _generate_pathc(self, log: BuildLogger):
        if not self._dds_meta_for_pathc:
            return
        base = self._game_path / META_DIR / PATHC_FILENAME
        if not base.exists():
            log(f"Warning: {base} not found")
            return
        try:
            pathc = core.read_texture_index(str(base))
        except Exception as e:
            log(f"Error: Cannot parse pathc: {e}")
            return

        added = 0
        for vpath, dds_rec, mip_sizes in self._dds_meta_for_pathc:
            try:
                _add_dds_entry_to_pathc(pathc, vpath, dds_rec, mip_sizes)
                added += 1
            except Exception as e:
                log(f"Warning: Cannot add DDS for {vpath}: {e}")

        if added == 0:
            return

        try:
            data = core.serialize_texture_index(pathc)
        except Exception as e:
            log(f"Error: Cannot serialize pathc: {e}")
            return

        out = self._overwrite_path / META_DIR
        out.mkdir(parents=True, exist_ok=True)
        (out / PATHC_FILENAME).write_bytes(data)
        log(f"Generated {META_DIR}/{PATHC_FILENAME} ({added} DDS texture(s))")

    def check_game_version_changed(self) -> tuple[str, str] | None:
        current = self._read_game_version()
        prev = self._load_manifest().get("game_version", "")
        if current and prev and current != prev:
            return (prev, current)
        return None

    def _read_game_version(self) -> str:
        try:
            return core.read_version(self._game_path / META_DIR / PAVER_FILENAME).label()
        except Exception:
            return ""

    def _scan_occupied_numbers(self) -> set[int]:
        nums: set[int] = set()
        if self._game_path.is_dir():
            for d in self._game_path.iterdir():
                if d.is_dir() and d.name.isdigit():
                    nums.add(int(d.name))
        if self._mods_path.is_dir():
            for md in self._mods_path.iterdir():
                if not md.is_dir():
                    continue
                for d in md.iterdir():
                    if d.is_dir() and d.name.isdigit() and not d.name.startswith(MOD_SOURCE_DIR):
                        nums.add(int(d.name))
        return nums

    def _manifest_path(self) -> Path:
        return self._profile_path / MANIFEST_FILENAME

    def _load_manifest(self) -> dict:
        p = self._manifest_path()
        if not p.is_file():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _fingerprint_dir(src_dir: Path) -> str:
        entries = []
        for f in sorted(src_dir.rglob("*")):
            if f.is_file():
                st = f.stat()
                entries.append(f"{f.relative_to(src_dir)}:{st.st_size}:{int(st.st_mtime)}")
        return "|".join(entries)

    @staticmethod
    def _compute_mod_fingerprint(mi: ModInfo) -> str:
        src = CrimsonDesertBuilder._find_source_dir(mi.path)
        return CrimsonDesertBuilder._fingerprint_dir(src) if src else ""

    @staticmethod
    def _collect_entry_paths(mi: ModInfo) -> list[str]:
        paths = []
        for jpf in mi.json_patches:
            for p in jpf.patches:
                gf = p.get("game_file")
                if isinstance(gf, str):
                    paths.append(core.normalize_path(gf))
        for lf in mi.loose_files:
            paths.append(lf.entry_path)
        return sorted(set(paths))

    def _save_manifest(self, mods: list[ModInfo]):
        prev = self._load_manifest()
        bundles = {k: v for k, v in prev.get("bundles", {}).items() if (self._mods_path / k).is_dir()}
        fps = {k: v for k, v in prev.get("fingerprints", {}).items() if (self._mods_path / k).is_dir()}
        eps = {k: v for k, v in prev.get("entry_paths", {}).items() if (self._mods_path / k).is_dir()}

        for m in mods:
            if m.bundle_numbers:
                bundles[m.name] = m.bundle_numbers
                fps[m.name] = self._compute_mod_fingerprint(m)
            ep = self._collect_entry_paths(m)
            if ep:
                eps[m.name] = ep

        rp = {k: v for k, v in prev.get("resolved_paths", {}).items() if (self._mods_path / k).is_dir()}
        for mn, mappings in self._resolved_paths.items():
            if mappings:
                rp[mn] = mappings

        manifest = {
            "game_version": self._read_game_version(),
            "bundles": bundles, "fingerprints": fps,
            "entry_paths": eps, "resolved_paths": rp,
        }
        p = self._manifest_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _add_dds_entry_to_pathc(pathc: dict, virtual_path: str,
                             dds_record: bytes, mip_sizes: tuple[int, int, int, int]):
    import bisect
    import base64

    rec_size = pathc["header"]["dds_record_size"]
    rec = bytearray(rec_size)
    to_copy = min(len(dds_record), rec_size)
    rec[:to_copy] = dds_record[:to_copy]
    rec_b64 = base64.b64encode(bytes(rec)).decode()

    dds_idx = -1
    for i, r in enumerate(pathc["dds_records"]):
        if r == rec_b64:
            dds_idx = i
            break
    if dds_idx < 0:
        pathc["dds_records"].append(rec_b64)
        dds_idx = len(pathc["dds_records"]) - 1

    target_hash = core.texture_path_hash(virtual_path)
    hashes = pathc["key_hashes"]
    idx = bisect.bisect_left(hashes, target_hash)
    selector = 0xFFFF0000 | (dds_idx & 0xFFFF)
    entry = {"selector": selector, "m1": mip_sizes[0], "m2": mip_sizes[1],
             "m3": mip_sizes[2], "m4": mip_sizes[3]}

    if idx < len(hashes) and hashes[idx] == target_hash:
        pathc["map_entries"][idx] = entry
    else:
        hashes.insert(idx, target_hash)
        pathc["map_entries"].insert(idx, entry)

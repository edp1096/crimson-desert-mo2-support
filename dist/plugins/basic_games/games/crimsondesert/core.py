"""Native core library wrapper for Crimson Desert archive operations.

Thin ctypes interface to paz_core.dll (Go implementation).
All archive parsing, crypto, compression, and building is delegated to the DLL.
"""

from __future__ import annotations

import ctypes
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# DLL loading
# ---------------------------------------------------------------------------

_DLL_NAME = "paz_core.dll"
_dll: ctypes.CDLL | None = None


def _load_dll() -> ctypes.CDLL:
    global _dll
    if _dll is not None:
        return _dll

    dll_path = Path(__file__).parent / _DLL_NAME
    if not dll_path.exists():
        raise FileNotFoundError(f"Native library not found: {dll_path}")

    _dll = ctypes.CDLL(str(dll_path))
    _setup_signatures(_dll)
    return _dll


def _setup_signatures(lib: ctypes.CDLL):
    lib.PazCoreFree.restype = None
    lib.PazCoreFree.argtypes = [ctypes.c_void_p]

    lib.PazCoreHashlittle.restype = ctypes.c_uint32
    lib.PazCoreHashlittle.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_uint32]

    lib.PazCoreParsePamt.restype = ctypes.c_char_p
    lib.PazCoreParsePamt.argtypes = [ctypes.c_char_p]
    lib.PazCoreReadPamtHeaderCrc.restype = ctypes.c_uint32
    lib.PazCoreReadPamtHeaderCrc.argtypes = [ctypes.c_char_p]

    lib.PazCoreExtractEntry.restype = ctypes.c_void_p
    lib.PazCoreExtractEntry.argtypes = [
        ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_uint16, ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int),
    ]
    lib.PazCorePackEntry.restype = ctypes.c_void_p
    lib.PazCorePackEntry.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_uint16, ctypes.c_char_p,
        ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint16),
    ]

    lib.PazCoreBuildPamt.restype = ctypes.c_void_p
    lib.PazCoreBuildPamt.argtypes = [
        ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_int),
    ]

    lib.PazCoreChacha20.restype = ctypes.c_void_p
    lib.PazCoreChacha20.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
    lib.PazCoreLZ4Decompress.restype = ctypes.c_void_p
    lib.PazCoreLZ4Decompress.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    lib.PazCoreLZ4Compress.restype = ctypes.c_void_p
    lib.PazCoreLZ4Compress.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]

    lib.PazCoreIsPrepackedDDS.restype = ctypes.c_int
    lib.PazCoreIsPrepackedDDS.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.PazCoreGetDDSMetadata.restype = None
    lib.PazCoreGetDDSMetadata.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]

    lib.PazCoreParsePapgt.restype = ctypes.c_char_p
    lib.PazCoreParsePapgt.argtypes = [ctypes.c_char_p]
    lib.PazCoreBuildPapgt.restype = ctypes.c_void_p
    lib.PazCoreBuildPapgt.argtypes = [
        ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int),
    ]

    lib.PazCoreReadPathc.restype = ctypes.c_char_p
    lib.PazCoreReadPathc.argtypes = [ctypes.c_char_p]
    lib.PazCoreSerializePathc.restype = ctypes.c_void_p
    lib.PazCoreSerializePathc.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
    lib.PazCoreGetPathcHash.restype = ctypes.c_uint32
    lib.PazCoreGetPathcHash.argtypes = [ctypes.c_char_p]

    lib.PazCoreReadPaver.restype = ctypes.c_char_p
    lib.PazCoreReadPaver.argtypes = [ctypes.c_char_p]
    lib.PazCoreSerializePaver.restype = ctypes.c_void_p
    lib.PazCoreSerializePaver.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]

    lib.PazCoreBuildGameIndex.restype = ctypes.c_uint64
    lib.PazCoreBuildGameIndex.argtypes = [ctypes.c_char_p]
    lib.PazCoreFreeGameIndex.restype = None
    lib.PazCoreFreeGameIndex.argtypes = [ctypes.c_uint64]
    lib.PazCoreFindLightEntry.restype = ctypes.c_char_p
    lib.PazCoreFindLightEntry.argtypes = [ctypes.c_uint64, ctypes.c_char_p, ctypes.c_char_p]

    lib.PazCoreResolveLooseEntryPath.restype = ctypes.c_char_p
    lib.PazCoreResolveLooseEntryPath.argtypes = [ctypes.c_char_p]
    lib.PazCoreInferFlags.restype = ctypes.c_uint16
    lib.PazCoreInferFlags.argtypes = [ctypes.c_char_p]
    lib.PazCoreApplyHexPatches.restype = ctypes.c_void_p
    lib.PazCoreApplyHexPatches.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int),
    ]

    lib.PazCoreBuildModPAZ.restype = ctypes.c_void_p
    lib.PazCoreBuildModPAZ.argtypes = [
        ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
    ]


def _buf(ptr, length: int) -> bytes:
    if not ptr or length <= 0:
        return b""
    lib = _load_dll()
    data = ctypes.string_at(ptr, length)
    lib.PazCoreFree(ptr)
    return data


def _enc(s: str) -> bytes:
    return s.encode("utf-8")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ArchiveEntry:
    path: str
    archive_file: str
    offset: int
    comp_size: int
    orig_size: int
    flags: int
    archive_index: int

    @property
    def compression_type(self) -> int:
        return self.flags & 0x0F

    @property
    def encryption_type(self) -> int:
        return (self.flags >> 4) & 0x0F


@dataclass(slots=True)
class ArchiveBundle:
    file_path: str
    directory: str
    archive_count: int
    entries: list[ArchiveEntry]
    extra_field: int


@dataclass(slots=True)
class IndexEntry:
    path: str
    flags: int
    group: str


@dataclass(slots=True)
class VersionInfo:
    major: int
    minor: int
    patch: int
    checksum: int

    def label(self) -> str:
        return f"v{self.major}.{self.minor:02d}.{self.patch:02d}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_hash(data: bytes, seed: int = 0x000C5EDE) -> int:
    lib = _load_dll()
    return lib.PazCoreHashlittle(data, len(data), seed)


def read_archive_index(pamt_path: str | Path) -> ArchiveBundle:
    lib = _load_dll()
    raw = lib.PazCoreParsePamt(_enc(str(pamt_path)))
    obj = json.loads(raw)
    if "error" in obj:
        raise RuntimeError(obj["error"])
    entries = [
        ArchiveEntry(
            path=e["path"], archive_file=e["paz_file"],
            offset=e["offset"], comp_size=e["comp_size"],
            orig_size=e["orig_size"], flags=e["flags"],
            archive_index=e["paz_index"],
        )
        for e in obj["entries"]
    ]
    return ArchiveBundle(
        file_path=obj["pamt_path"], directory=obj["paz_dir"],
        archive_count=obj["paz_count"], entries=entries,
        extra_field=obj["unknown_field"],
    )


def read_index_checksum(pamt_path: str | Path) -> int:
    lib = _load_dll()
    return lib.PazCoreReadPamtHeaderCrc(_enc(str(pamt_path)))


def extract_file(entry: ArchiveEntry, decrypt_xml: bool = True) -> bytes:
    lib = _load_dll()
    out_len = ctypes.c_int(0)
    ptr = lib.PazCoreExtractEntry(
        _enc(entry.archive_file), entry.offset, entry.comp_size,
        entry.orig_size, entry.flags, _enc(entry.path),
        1 if decrypt_xml else 0, ctypes.byref(out_len),
    )
    return _buf(ptr, out_len.value)


def pack_file(data: bytes, flags: int, entry_path: str,
              encrypt_xml: bool = True) -> tuple[bytes, int]:
    lib = _load_dll()
    out_len = ctypes.c_int(0)
    out_flags = ctypes.c_uint16(0)
    ptr = lib.PazCorePackEntry(
        data, len(data), flags, _enc(entry_path),
        1 if encrypt_xml else 0,
        ctypes.byref(out_len), ctypes.byref(out_flags),
    )
    return _buf(ptr, out_len.value), out_flags.value


def payload_checksum(data: bytes) -> int:
    return compute_hash(data)


def normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip("/")


def read_registry_template(path: str | Path) -> dict:
    lib = _load_dll()
    raw = lib.PazCoreParsePapgt(_enc(str(path)))
    obj = json.loads(raw)
    if "error" in obj:
        raise RuntimeError(obj["error"])
    return obj


def build_registry_bytes(template: dict, bundle_names: list[str],
                         checksum_map: dict[str, int]) -> bytes:
    lib = _load_dll()
    out_len = ctypes.c_int(0)
    ptr = lib.PazCoreBuildPapgt(
        _enc(json.dumps(template)),
        _enc(json.dumps(bundle_names)),
        _enc(json.dumps(checksum_map)),
        ctypes.byref(out_len),
    )
    result = _buf(ptr, out_len.value)
    if not result:
        raise RuntimeError("Failed to build registry")
    return result


def read_texture_index(path: str | Path) -> dict:
    lib = _load_dll()
    raw = lib.PazCoreReadPathc(_enc(str(path)))
    obj = json.loads(raw)
    if "error" in obj:
        raise RuntimeError(obj["error"])
    return obj


def serialize_texture_index(pathc_data: dict) -> bytes:
    lib = _load_dll()
    out_len = ctypes.c_int(0)
    ptr = lib.PazCoreSerializePathc(
        _enc(json.dumps(pathc_data)), ctypes.byref(out_len),
    )
    result = _buf(ptr, out_len.value)
    if not result:
        raise RuntimeError("Failed to serialize texture index")
    return result


def texture_path_hash(virtual_path: str) -> int:
    lib = _load_dll()
    return lib.PazCoreGetPathcHash(_enc(virtual_path))


def dds_metadata(data: bytes) -> tuple[int, int, int, int]:
    lib = _load_dll()
    out = (ctypes.c_uint32 * 4)()
    lib.PazCoreGetDDSMetadata(data, len(data), ctypes.cast(out, ctypes.c_void_p))
    return (out[0], out[1], out[2], out[3])


def dds_template_record(dds_data: bytes, record_size: int = 0x94) -> bytes:
    if len(dds_data) < 4 or dds_data[:4] != b"DDS ":
        raise ValueError("Not a valid DDS file.")
    rec = bytearray(record_size)
    to_copy = min(len(dds_data), record_size)
    rec[:to_copy] = dds_data[:to_copy]
    return bytes(rec)


def read_version(path: str | Path) -> VersionInfo:
    lib = _load_dll()
    raw = lib.PazCoreReadPaver(_enc(str(path)))
    obj = json.loads(raw)
    if "error" in obj:
        raise RuntimeError(obj["error"])
    return VersionInfo(**obj)


class GameArchiveIndex:
    def __init__(self, game_path: str | Path):
        lib = _load_dll()
        self._lib = lib
        self._handle = lib.PazCoreBuildGameIndex(_enc(str(game_path)))

    def close(self):
        if self._handle:
            self._lib.PazCoreFreeGameIndex(self._handle)
            self._handle = 0

    def __del__(self):
        self.close()

    def find(self, game_path: str, source_group: str | None = None) -> IndexEntry | None:
        sg = _enc(source_group) if source_group else None
        raw = self._lib.PazCoreFindLightEntry(self._handle, _enc(game_path), sg)
        if not raw or raw == b"null":
            return None
        obj = json.loads(raw)
        return IndexEntry(path=obj["path"], flags=obj["flags"], group=obj["bundle"])


def resolve_mod_file_path(rel_parts: tuple[str, ...] | list[str]) -> str | None:
    lib = _load_dll()
    raw = lib.PazCoreResolveLooseEntryPath(_enc(json.dumps(list(rel_parts))))
    result = raw.decode("utf-8") if raw else ""
    return result if result else None


def guess_flags(entry_path: str) -> int:
    lib = _load_dll()
    return lib.PazCoreInferFlags(_enc(entry_path))


def apply_hex_patches(data: bytes, changes: list[dict]) -> bytes:
    lib = _load_dll()
    out_len = ctypes.c_int(0)
    ptr = lib.PazCoreApplyHexPatches(
        data, len(data), _enc(json.dumps(changes)), ctypes.byref(out_len),
    )
    result = _buf(ptr, out_len.value)
    return result if result else data

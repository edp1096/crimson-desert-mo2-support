"""Quick test of paz_core.dll via ctypes."""
import ctypes
import json
import os
import sys

# Load DLL
dll_path = os.path.join(os.path.dirname(__file__), "paz_core.dll")
lib = ctypes.CDLL(dll_path)

# Setup function signatures
lib.PazCoreHashlittle.restype = ctypes.c_uint32
lib.PazCoreHashlittle.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_uint32]

lib.PazCoreParsePamt.restype = ctypes.c_char_p
lib.PazCoreParsePamt.argtypes = [ctypes.c_char_p]

lib.PazCoreExtractEntry.restype = ctypes.c_void_p
lib.PazCoreExtractEntry.argtypes = [
    ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
    ctypes.c_uint16, ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int),
]

lib.PazCoreFree.restype = None
lib.PazCoreFree.argtypes = [ctypes.c_void_p]

lib.PazCoreReadPamtHeaderCrc.restype = ctypes.c_uint32
lib.PazCoreReadPamtHeaderCrc.argtypes = [ctypes.c_char_p]


def test_hashlittle():
    """Test Jenkins hash against known values."""
    HASH_INITVAL = 0x000C5EDE

    data = b"test"
    result = lib.PazCoreHashlittle(data, len(data), HASH_INITVAL)
    print(f"Hashlittle('test', 0x{HASH_INITVAL:08X}) = 0x{result:08X}")

    # Compare with Python implementation
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "plugins", "basic_games", "games"))
    from crimsondesert.paz_tools import hashlittle as py_hashlittle

    py_result = py_hashlittle(data, HASH_INITVAL)
    print(f"Python hashlittle = 0x{py_result:08X}")
    assert result == py_result, f"MISMATCH: Go={result:#x} Python={py_result:#x}"
    print("  PASS: hash match\n")


def test_parse_pamt():
    """Test PAMT parsing."""
    game_dir = r"D:\games\steam\steamapps\common\Crimson Desert"
    pamt_path = os.path.join(game_dir, "0005", "0.pamt")

    result_json = lib.PazCoreParsePamt(pamt_path.encode("utf-8"))
    bundle = json.loads(result_json)

    if "error" in bundle:
        print(f"ERROR: {bundle['error']}")
        return

    entries = bundle["entries"]
    kliff = [e for e in entries if "unique_kliff_" in e["path"].lower() and "korean" in e["path"]]
    print(f"0005 total entries: {len(entries)}")
    print(f"0005 kliff korean wem: {len(kliff)}")
    print(f"  Sample: {kliff[0]['path']}" if kliff else "  None found")

    # Compare with Python
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "plugins", "basic_games", "games"))
    from crimsondesert.paz_tools import parse_pamt
    from pathlib import Path

    py_bundle = parse_pamt(Path(pamt_path))
    py_kliff = [e for e in py_bundle.entries if "unique_kliff_" in e.path.lower() and "korean" in e.path]
    print(f"  Python kliff count: {len(py_kliff)}")
    assert len(kliff) == len(py_kliff), f"MISMATCH: Go={len(kliff)} Python={len(py_kliff)}"
    print("  PASS: entry count match\n")


def test_extract_entry():
    """Test entry extraction."""
    game_dir = r"D:\games\steam\steamapps\common\Crimson Desert"
    pamt_path = os.path.join(game_dir, "0005", "0.pamt")

    result_json = lib.PazCoreParsePamt(pamt_path.encode("utf-8"))
    bundle = json.loads(result_json)
    entries = bundle["entries"]

    # Find a small kliff wem
    for e in entries:
        if "unique_kliff_abyss_lv1_0003_item_player_00000.wem" in e["path"] and "korean" in e["path"]:
            out_len = ctypes.c_int(0)
            ptr = lib.PazCoreExtractEntry(
                e["paz_file"].encode("utf-8"),
                e["offset"], e["comp_size"], e["orig_size"],
                e["flags"], e["path"].encode("utf-8"),
                1, ctypes.byref(out_len),
            )
            if ptr:
                data = ctypes.string_at(ptr, out_len.value)
                lib.PazCoreFree(ptr)
                print(f"Extracted: {e['path']} ({len(data)} bytes)")
                print(f"  Header: {data[:4]}")
                assert data[:4] == b"RIFF", "Expected RIFF header"
                print("  PASS: extraction OK\n")
            else:
                print(f"  FAIL: extraction returned null\n")
            break


def test_header_crc():
    """Test PAMT header CRC reading."""
    game_dir = r"D:\games\steam\steamapps\common\Crimson Desert"
    pamt_path = os.path.join(game_dir, "0005", "0.pamt")

    crc = lib.PazCoreReadPamtHeaderCrc(pamt_path.encode("utf-8"))
    print(f"PAMT header CRC: 0x{crc:08X}")
    print("  PASS: CRC read OK\n")


if __name__ == "__main__":
    test_hashlittle()
    test_parse_pamt()
    test_extract_entry()
    test_header_crc()
    print("All tests passed!")

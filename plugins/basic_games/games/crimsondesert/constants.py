from __future__ import annotations

PLUGIN_NAME = "Crimson Desert Support Plugin"
PLUGIN_AUTHOR = "edp1096"
PLUGIN_VERSION = "0.1.3"
PLUGIN_VERSION_TUPLE = (0, 1, 3, 0)

TOOL_PLUGIN_NAME = "Crimson Desert PAZ Builder"

GAME_SHORT_NAME = "crimsondesert"

MOD_SOURCE_DIR = "_mod_"
BIN64_DIR = "bin64"
META_DIR = "meta"

PAPGT_FILENAME = "0.papgt"
PATHC_FILENAME = "0.pathc"
PAVER_FILENAME = "0.paver"
MANIFEST_FILENAME = "crimson_manifest.json"

GAME_BINARY = "bin64/CrimsonDesert.exe"
GAME_PROCESS = "CrimsonDesert.exe"

# Ultimate ASI Loader x64 proxy DLL names
# https://github.com/ThirteenAG/Ultimate-ASI-Loader/releases
ASI_LOADER_DLLS = {
    "d3d9.dll", "d3d10.dll", "d3d11.dll", "d3d12.dll",
    "dinput8.dll", "dsound.dll", "version.dll",
    "wininet.dll", "winmm.dll", "winhttp.dll",
    "binkw64.dll", "bink2w64.dll",
    "xinput1_1.dll", "xinput1_2.dll", "xinput1_3.dll",
    "xinput1_4.dll", "xinput9_1_0.dll", "xinputuap.dll",
}

HASH_INITVAL = 0x000C5EDE
IV_XOR = 0x60616263
XOR_DELTAS = [
    0x00000000, 0x0A0A0A0A, 0x0C0C0C0C, 0x06060606,
    0x0E0E0E0E, 0x0A0A0A0A, 0x06060606, 0x02020202,
]

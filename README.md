Mod Organizer 2 Support for Crimson Desert

## Installation
1. Download this repository and extract the files.
1. Copy and overwrite the dist/plugins into your **MO2 installation folder/plugins** directory.

## Build
* Pre-requisites:
  * [Go](https://go.dev/dl/) >= 1.24
  * [Make](https://gnuwin32.sourceforge.net/packages/make.htm)
* Build
```sh
make
```

## Troubleshooting
* **Plugin Error on Launch:** If MO2 crashes with an `installer_omod` error during the first run, restart the application and **blacklist** the `omod` plugin in the resulting popup window.

---

> **Note:** Mod Organizer 2 (MO2) version **2.5.2 or higher (Portable Version)** is recommended.
> [MO2 Releases](https://github.com/Modorganizer2/modorganizer/releases)

Reference: https://github.com/lazorr410/crimson-desert-unpacker
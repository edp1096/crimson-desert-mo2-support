package main

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// PazEntry represents a file entry in a PAZ archive.
type PazEntry struct {
	Path     string `json:"path"`
	PazFile  string `json:"paz_file"`
	Offset   uint32 `json:"offset"`
	CompSize uint32 `json:"comp_size"`
	OrigSize uint32 `json:"orig_size"`
	Flags    uint16 `json:"flags"`
	PazIndex uint16 `json:"paz_index"`
}

func (e *PazEntry) CompressionType() int { return int(e.Flags & 0x0F) }
func (e *PazEntry) Compressed() bool     { return (e.Flags & 0x0F) != 0 }
func (e *PazEntry) EncryptionType() int  { return int((e.Flags >> 4) & 0x0F) }
func (e *PazEntry) Encrypted() bool      { return (e.Flags & 0xF0) != 0 }

// PamtBundle holds all entries from a PAMT file.
type PamtBundle struct {
	PamtPath     string     `json:"pamt_path"`
	PazDir       string     `json:"paz_dir"`
	PazCount     int        `json:"paz_count"`
	Entries      []PazEntry `json:"entries"`
	UnknownField uint32     `json:"unknown_field"`
}

type folderSpan struct {
	start int
	end   int
	path  string
}

const sentinel = 0xFFFFFFFF

// ParsePamt reads a PAMT file and returns all entries.
func ParsePamt(pamtPath string) (*PamtBundle, error) {
	data, err := os.ReadFile(pamtPath)
	if err != nil {
		return nil, err
	}
	if len(data) < 12 {
		return nil, fmt.Errorf("%s is too small", pamtPath)
	}

	pazDir := filepath.Dir(pamtPath)
	pos := 0

	// Header
	pos += 4 // integrity hash
	nPaz := int(binary.LittleEndian.Uint32(data[pos:]))
	pos += 4
	unk := binary.LittleEndian.Uint32(data[pos:])
	pos += 4
	pos += nPaz * 12

	// Name blobs
	dirBlob, pos := readBlob(data, pos)
	fnameBlob, pos := readBlob(data, pos)

	// Folders
	nFolders := int(binary.LittleEndian.Uint32(data[pos:]))
	pos += 4

	dirCache := make(map[int]string)
	var folders []folderSpan

	for i := 0; i < nFolders; i++ {
		_ = binary.LittleEndian.Uint32(data[pos:])
		noff := int(binary.LittleEndian.Uint32(data[pos+4:]))
		first := int(binary.LittleEndian.Uint32(data[pos+8:]))
		count := int(binary.LittleEndian.Uint32(data[pos+12:]))
		pos += 16

		if count > 0 {
			dp := normalizePath(reconstructPath(dirBlob, noff, dirCache))
			folders = append(folders, folderSpan{start: first, end: first + count, path: dp})
		}
	}
	sort.Slice(folders, func(i, j int) bool { return folders[i].start < folders[j].start })

	// Files
	nFiles := int(binary.LittleEndian.Uint32(data[pos:]))
	pos += 4

	fnameCache := make(map[int]string)
	entries := make([]PazEntry, 0, nFiles)
	fi_folder := 0

	for fi := 0; fi < nFiles; fi++ {
		if pos+20 > len(data) {
			return nil, fmt.Errorf("%s ended unexpectedly at file %d", pamtPath, fi)
		}
		noff := int(binary.LittleEndian.Uint32(data[pos:]))
		poff := binary.LittleEndian.Uint32(data[pos+4:])
		csz := binary.LittleEndian.Uint32(data[pos+8:])
		osz := binary.LittleEndian.Uint32(data[pos+12:])
		pidx := binary.LittleEndian.Uint16(data[pos+16:])
		fl := binary.LittleEndian.Uint16(data[pos+18:])
		pos += 20

		for fi_folder < len(folders) && fi >= folders[fi_folder].end {
			fi_folder++
		}

		dprefix := ""
		if fi_folder < len(folders) {
			f := folders[fi_folder]
			if f.start <= fi && fi < f.end {
				dprefix = f.path
			}
		}

		fname := normalizePath(reconstructPath(fnameBlob, noff, fnameCache))
		var vpath string
		if dprefix != "" {
			vpath = normalizePath(dprefix + "/" + fname)
		} else {
			vpath = fname
		}

		entries = append(entries, PazEntry{
			Path:     vpath,
			PazFile:  filepath.Join(pazDir, fmt.Sprintf("%d.paz", pidx)),
			Offset:   poff,
			CompSize: csz,
			OrigSize: osz,
			Flags:    fl,
			PazIndex: pidx,
		})
	}

	return &PamtBundle{
		PamtPath:     pamtPath,
		PazDir:       pazDir,
		PazCount:     nPaz,
		Entries:      entries,
		UnknownField: unk,
	}, nil
}

// ExtractEntryBytes reads raw bytes for a PazEntry.
// Handles decompression and decryption based on flags.
func ExtractEntryBytes(e *PazEntry, decryptXML bool) ([]byte, error) {
	nbytes := e.OrigSize
	if e.Compressed() {
		nbytes = e.CompSize
	}

	f, err := os.Open(e.PazFile)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	buf := make([]byte, nbytes)
	_, err = f.ReadAt(buf, int64(e.Offset))
	if err != nil {
		return nil, fmt.Errorf("read %s offset %d: %w", e.PazFile, e.Offset, err)
	}

	switch e.CompressionType() {
	case 0: // raw
		if decryptXML && e.Encrypted() {
			return ChaCha20Crypt(buf, filepath.Base(e.Path)), nil
		}
		return buf, nil
	case 1: // partial DDS
		return PartialDDSDecompress(buf, int(e.OrigSize)), nil
	case 2: // LZ4
		if decryptXML && e.Encrypted() {
			decrypted := ChaCha20Crypt(buf, filepath.Base(e.Path))
			decompressed, err := LZ4Decompress(decrypted, int(e.OrigSize))
			if err == nil {
				return decompressed, nil
			}
			// Fallback: try without decryption
		}
		return LZ4Decompress(buf, int(e.OrigSize))
	default:
		return buf, nil
	}
}

// PackEntryBytes packs plaintext into PAZ payload format.
// Returns (payload, actual_flags).
func PackEntryBytes(plaintext []byte, flags uint16, entryPath string, encryptXML bool) ([]byte, uint16) {
	compType := flags & 0x0F
	encType := (flags >> 4) & 0x0F
	actualFlags := flags

	var payload []byte

	switch compType {
	case 0: // raw
		payload = plaintext
	case 1: // partial DDS - pass through
		payload = plaintext
	case 2: // LZ4
		compressed := LZ4CompressCompat(plaintext)
		if compressed != nil {
			payload = compressed
		} else {
			payload = plaintext
			actualFlags = flags & 0xF0 // clear compression bits
		}
	default:
		payload = plaintext
	}

	// Encrypt if needed
	doEncrypt := encType == 3
	if strings.HasSuffix(strings.ToLower(entryPath), ".xml") {
		doEncrypt = doEncrypt && encryptXML
	}
	if doEncrypt {
		payload = ChaCha20Crypt(payload, filepath.Base(entryPath))
	}

	return payload, actualFlags
}

// ReadPamtHeaderCrc reads just the integrity hash from a PAMT file.
func ReadPamtHeaderCrc(pamtPath string) (uint32, error) {
	f, err := os.Open(pamtPath)
	if err != nil {
		return 0, err
	}
	defer f.Close()

	var buf [4]byte
	if _, err := f.Read(buf[:]); err != nil {
		return 0, err
	}
	return binary.LittleEndian.Uint32(buf[:]), nil
}

func readBlob(data []byte, pos int) ([]byte, int) {
	length := int(binary.LittleEndian.Uint32(data[pos:]))
	pos += 4
	blob := data[pos : pos+length]
	pos += length
	return blob, pos
}

func reconstructPath(blob []byte, at int, cache map[int]string) string {
	if at == int(sentinel) || at >= len(blob) {
		return ""
	}
	if v, ok := cache[at]; ok {
		return v
	}
	if at+5 > len(blob) {
		return ""
	}
	parent := int(binary.LittleEndian.Uint32(blob[at:]))
	slen := int(blob[at+4])
	if at+5+slen > len(blob) {
		return ""
	}
	seg := string(blob[at+5 : at+5+slen])
	prefix := reconstructPath(blob, parent, cache)
	result := prefix + seg
	cache[at] = result
	return result
}

func normalizePath(s string) string {
	s = strings.ReplaceAll(s, "\\", "/")
	return strings.Trim(s, "/")
}

// marshalPamtBundle serializes a PamtBundle to JSON.
func marshalPamtBundle(b *PamtBundle) string {
	data, _ := json.Marshal(b)
	return string(data)
}

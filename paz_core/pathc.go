package main

import (
	"encoding/binary"
	"fmt"
	"os"
	"sort"
	"strings"
)

// PathcHeader is the 28-byte header of 0.pathc.
type PathcHeader struct {
	Unknown0           uint32 `json:"unknown0"`
	Unknown1           uint32 `json:"unknown1"`
	DDSRecordSize      uint32 `json:"dds_record_size"`
	DDSRecordCount     uint32 `json:"dds_record_count"`
	HashCount          uint32 `json:"hash_count"`
	CollisionPathCount uint32 `json:"collision_path_count"`
	CollisionBlobSize  uint32 `json:"collision_blob_size"`
}

// PathcMapEntry is a hash-table entry (20 bytes).
type PathcMapEntry struct {
	Selector uint32 `json:"selector"`
	M1       uint32 `json:"m1"`
	M2       uint32 `json:"m2"`
	M3       uint32 `json:"m3"`
	M4       uint32 `json:"m4"`
}

// PathcCollisionEntry is a collision chain entry (24 bytes + path string).
type PathcCollisionEntry struct {
	PathOffset uint32 `json:"path_offset"`
	DDSIndex   uint32 `json:"dds_index"`
	M1         uint32 `json:"m1"`
	M2         uint32 `json:"m2"`
	M3         uint32 `json:"m3"`
	M4         uint32 `json:"m4"`
	Path       string `json:"path"`
}

// PathcFile holds a parsed 0.pathc file.
type PathcFile struct {
	Header           PathcHeader           `json:"header"`
	DDSRecords       [][]byte              `json:"dds_records"`
	KeyHashes        []uint32              `json:"key_hashes"`
	MapEntries       []PathcMapEntry       `json:"map_entries"`
	CollisionEntries []PathcCollisionEntry `json:"collision_entries"`
}

// ReadPathc parses a 0.pathc file.
func ReadPathc(path string) (*PathcFile, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(raw) < 0x1C {
		return nil, fmt.Errorf("%s is too small for a valid .pathc", path)
	}

	hdr := PathcHeader{
		Unknown0:           binary.LittleEndian.Uint32(raw[0:]),
		Unknown1:           binary.LittleEndian.Uint32(raw[4:]),
		DDSRecordSize:      binary.LittleEndian.Uint32(raw[8:]),
		DDSRecordCount:     binary.LittleEndian.Uint32(raw[12:]),
		HashCount:          binary.LittleEndian.Uint32(raw[16:]),
		CollisionPathCount: binary.LittleEndian.Uint32(raw[20:]),
		CollisionBlobSize:  binary.LittleEndian.Uint32(raw[24:]),
	}

	ddsOff := 0x1C
	hashOff := ddsOff + int(hdr.DDSRecordSize)*int(hdr.DDSRecordCount)
	mapOff := hashOff + int(hdr.HashCount)*4
	collOff := mapOff + int(hdr.HashCount)*20
	blobOff := collOff + int(hdr.CollisionPathCount)*24

	ddsRecords := make([][]byte, hdr.DDSRecordCount)
	for i := 0; i < int(hdr.DDSRecordCount); i++ {
		off := ddsOff + i*int(hdr.DDSRecordSize)
		rec := make([]byte, hdr.DDSRecordSize)
		copy(rec, raw[off:off+int(hdr.DDSRecordSize)])
		ddsRecords[i] = rec
	}

	keyHashes := make([]uint32, hdr.HashCount)
	for i := 0; i < int(hdr.HashCount); i++ {
		keyHashes[i] = binary.LittleEndian.Uint32(raw[hashOff+i*4:])
	}

	mapEntries := make([]PathcMapEntry, hdr.HashCount)
	for i := 0; i < int(hdr.HashCount); i++ {
		off := mapOff + i*20
		mapEntries[i] = PathcMapEntry{
			Selector: binary.LittleEndian.Uint32(raw[off:]),
			M1:       binary.LittleEndian.Uint32(raw[off+4:]),
			M2:       binary.LittleEndian.Uint32(raw[off+8:]),
			M3:       binary.LittleEndian.Uint32(raw[off+12:]),
			M4:       binary.LittleEndian.Uint32(raw[off+16:]),
		}
	}

	blob := raw[blobOff : blobOff+int(hdr.CollisionBlobSize)]
	collEntries := make([]PathcCollisionEntry, hdr.CollisionPathCount)
	for i := 0; i < int(hdr.CollisionPathCount); i++ {
		off := collOff + i*24
		poff := binary.LittleEndian.Uint32(raw[off:])
		ddsIdx := binary.LittleEndian.Uint32(raw[off+4:])
		m1 := binary.LittleEndian.Uint32(raw[off+8:])
		m2 := binary.LittleEndian.Uint32(raw[off+12:])
		m3 := binary.LittleEndian.Uint32(raw[off+16:])
		m4 := binary.LittleEndian.Uint32(raw[off+20:])

		pathStr := ""
		if int(poff) < len(blob) {
			end := int(poff)
			for end < len(blob) && blob[end] != 0 {
				end++
			}
			pathStr = string(blob[poff:end])
		}

		collEntries[i] = PathcCollisionEntry{
			PathOffset: poff, DDSIndex: ddsIdx,
			M1: m1, M2: m2, M3: m3, M4: m4, Path: pathStr,
		}
	}

	return &PathcFile{
		Header: hdr, DDSRecords: ddsRecords, KeyHashes: keyHashes,
		MapEntries: mapEntries, CollisionEntries: collEntries,
	}, nil
}

// SerializePathc serializes a PathcFile back to bytes.
func SerializePathc(pathc *PathcFile) []byte {
	// Rebuild collision blob
	collBlob := make([]byte, 0)
	collRows := make([][]byte, len(pathc.CollisionEntries))
	for i, entry := range pathc.CollisionEntries {
		poff := len(collBlob)
		collBlob = append(collBlob, []byte(entry.Path)...)
		collBlob = append(collBlob, 0)
		var row [24]byte
		binary.LittleEndian.PutUint32(row[0:], uint32(poff))
		binary.LittleEndian.PutUint32(row[4:], entry.DDSIndex)
		binary.LittleEndian.PutUint32(row[8:], entry.M1)
		binary.LittleEndian.PutUint32(row[12:], entry.M2)
		binary.LittleEndian.PutUint32(row[16:], entry.M3)
		binary.LittleEndian.PutUint32(row[20:], entry.M4)
		collRows[i] = row[:]
	}

	// Update counts
	pathc.Header.DDSRecordCount = uint32(len(pathc.DDSRecords))
	pathc.Header.HashCount = uint32(len(pathc.KeyHashes))
	pathc.Header.CollisionPathCount = uint32(len(pathc.CollisionEntries))
	pathc.Header.CollisionBlobSize = uint32(len(collBlob))

	// Write
	out := make([]byte, 0, 0x1C+len(pathc.DDSRecords)*int(pathc.Header.DDSRecordSize)+
		len(pathc.KeyHashes)*24+len(collRows)*24+len(collBlob))

	var hdr [28]byte
	binary.LittleEndian.PutUint32(hdr[0:], pathc.Header.Unknown0)
	binary.LittleEndian.PutUint32(hdr[4:], pathc.Header.Unknown1)
	binary.LittleEndian.PutUint32(hdr[8:], pathc.Header.DDSRecordSize)
	binary.LittleEndian.PutUint32(hdr[12:], pathc.Header.DDSRecordCount)
	binary.LittleEndian.PutUint32(hdr[16:], pathc.Header.HashCount)
	binary.LittleEndian.PutUint32(hdr[20:], pathc.Header.CollisionPathCount)
	binary.LittleEndian.PutUint32(hdr[24:], pathc.Header.CollisionBlobSize)
	out = append(out, hdr[:]...)

	for _, rec := range pathc.DDSRecords {
		out = append(out, rec...)
	}

	for _, h := range pathc.KeyHashes {
		var b [4]byte
		binary.LittleEndian.PutUint32(b[:], h)
		out = append(out, b[:]...)
	}

	for _, me := range pathc.MapEntries {
		var b [20]byte
		binary.LittleEndian.PutUint32(b[0:], me.Selector)
		binary.LittleEndian.PutUint32(b[4:], me.M1)
		binary.LittleEndian.PutUint32(b[8:], me.M2)
		binary.LittleEndian.PutUint32(b[12:], me.M3)
		binary.LittleEndian.PutUint32(b[16:], me.M4)
		out = append(out, b[:]...)
	}

	for _, row := range collRows {
		out = append(out, row...)
	}

	out = append(out, collBlob...)
	return out
}

// NormalizePathcPath normalizes a virtual path for PATHC hashing.
func NormalizePathcPath(pathStr string) string {
	p := strings.ReplaceAll(pathStr, "\\", "/")
	p = strings.TrimSpace(p)
	p = strings.Trim(p, "/")
	return "/" + p
}

// GetPathcHash hashes a virtual path for PATHC lookup.
func GetPathcHash(virtualPath string) uint32 {
	normalized := strings.ToLower(NormalizePathcPath(virtualPath))
	return Hashlittle([]byte(normalized), hashInitval)
}

// AddDDSEntry adds a DDS file to the PATHC index.
func AddDDSEntry(pathc *PathcFile, virtualPath string, ddsData []byte) int {
	recSize := int(pathc.Header.DDSRecordSize)
	ddsRec := make([]byte, recSize)
	toCopy := len(ddsData)
	if toCopy > recSize {
		toCopy = recSize
	}
	copy(ddsRec, ddsData[:toCopy])

	m := GetDDSMetadata(ddsData)

	// Deduplicate
	ddsIdx := -1
	for i, rec := range pathc.DDSRecords {
		if bytesEqual(rec, ddsRec) {
			ddsIdx = i
			break
		}
	}
	if ddsIdx < 0 {
		pathc.DDSRecords = append(pathc.DDSRecords, ddsRec)
		ddsIdx = len(pathc.DDSRecords) - 1
	}

	updatePathcEntry(pathc, virtualPath, ddsIdx, m)
	return ddsIdx
}

// AddDDSEntryFromMeta adds a DDS entry using pre-computed record and metadata.
func AddDDSEntryFromMeta(pathc *PathcFile, virtualPath string, ddsRecord []byte, mipSizes [4]uint32) int {
	recSize := int(pathc.Header.DDSRecordSize)
	rec := make([]byte, recSize)
	toCopy := len(ddsRecord)
	if toCopy > recSize {
		toCopy = recSize
	}
	copy(rec, ddsRecord[:toCopy])

	ddsIdx := -1
	for i, r := range pathc.DDSRecords {
		if bytesEqual(r, rec) {
			ddsIdx = i
			break
		}
	}
	if ddsIdx < 0 {
		pathc.DDSRecords = append(pathc.DDSRecords, rec)
		ddsIdx = len(pathc.DDSRecords) - 1
	}

	updatePathcEntry(pathc, virtualPath, ddsIdx, mipSizes)
	return ddsIdx
}

// GetDDSMetadata extracts mipmap size metadata from DDS data.
func GetDDSMetadata(data []byte) [4]uint32 {
	if len(data) < 128 || string(data[:4]) != ddsMagicStr {
		return [4]uint32{}
	}

	height := int(binary.LittleEndian.Uint32(data[12:]))
	width := int(binary.LittleEndian.Uint32(data[16:]))
	pitch := int(binary.LittleEndian.Uint32(data[20:]))
	mips := int(binary.LittleEndian.Uint32(data[28:]))
	if mips < 1 {
		mips = 1
	}

	pfFlags := binary.LittleEndian.Uint32(data[80:])
	fourcc := string(data[84:88])
	pfRGBBits := int(binary.LittleEndian.Uint32(data[88:]))

	var dxgi int = -1
	if fourcc == "DX10" && len(data) >= 148 {
		dxgi = int(binary.LittleEndian.Uint32(data[128:]))
	}

	// BC block bytes tables
	bcFourcc := map[string]int{
		"DXT1": 8, "ATI1": 8, "BC4U": 8, "BC4S": 8,
		"DXT3": 16, "DXT5": 16, "ATI2": 16, "BC5U": 16, "BC5S": 16,
	}
	bcDxgi := map[int]int{
		70: 8, 71: 8, 72: 8, 73: 16, 74: 16, 75: 16, 76: 16, 77: 16, 78: 16,
		79: 8, 80: 8, 81: 8, 82: 16, 83: 16, 84: 16,
		94: 16, 95: 16, 96: 16, 97: 16, 98: 16, 99: 16,
	}
	dxgiBPP := map[int]int{10: 64, 24: 32, 28: 32, 61: 8}

	blockBytes := 0
	if bb, ok := bcFourcc[fourcc]; ok {
		blockBytes = bb
	} else if dxgi >= 0 {
		if bb, ok := bcDxgi[dxgi]; ok {
			blockBytes = bb
		}
	}

	bpp := 0
	if blockBytes == 0 {
		if dxgi >= 0 {
			bpp = dxgiBPP[dxgi]
		}
		if bpp == 0 && (pfFlags&0x40) != 0 {
			bpp = pfRGBBits
		}
	}

	var sizes [4]uint32
	cw, ch := max(1, width), max(1, height)
	for i := 0; i < min(4, mips); i++ {
		var sz int
		if blockBytes > 0 {
			sz = max(1, (cw+3)/4) * max(1, (ch+3)/4) * blockBytes
		} else if bpp > 0 {
			sz = ((cw*bpp + 7) / 8) * ch
		} else if i == 0 && pitch > 0 {
			sz = pitch
		}
		sizes[i] = uint32(sz) & 0xFFFFFFFF
		cw = max(1, cw/2)
		ch = max(1, ch/2)
	}

	return sizes
}

func updatePathcEntry(pathc *PathcFile, virtualPath string, ddsIndex int, m [4]uint32) {
	targetHash := GetPathcHash(virtualPath)
	idx := sort.Search(len(pathc.KeyHashes), func(i int) bool {
		return pathc.KeyHashes[i] >= targetHash
	})

	selector := uint32(0xFFFF0000) | uint32(ddsIndex&0xFFFF)

	if idx < len(pathc.KeyHashes) && pathc.KeyHashes[idx] == targetHash {
		// Update existing
		pathc.MapEntries[idx].Selector = selector
		pathc.MapEntries[idx].M1 = m[0]
		pathc.MapEntries[idx].M2 = m[1]
		pathc.MapEntries[idx].M3 = m[2]
		pathc.MapEntries[idx].M4 = m[3]
	} else {
		// Insert at sorted position
		pathc.KeyHashes = append(pathc.KeyHashes, 0)
		copy(pathc.KeyHashes[idx+1:], pathc.KeyHashes[idx:])
		pathc.KeyHashes[idx] = targetHash

		pathc.MapEntries = append(pathc.MapEntries, PathcMapEntry{})
		copy(pathc.MapEntries[idx+1:], pathc.MapEntries[idx:])
		pathc.MapEntries[idx] = PathcMapEntry{Selector: selector, M1: m[0], M2: m[1], M3: m[2], M4: m[3]}
	}
}

func bytesEqual(a, b []byte) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

package main

import (
	"encoding/binary"
	"fmt"
	"os"
)

// ArchiveRecord is a single entry in 0.papgt.
type ArchiveRecord struct {
	Name    string `json:"name"`
	Flags   uint32 `json:"flags"`
	PamtCrc uint32 `json:"pamt_crc"`
}

// PapgtSnapshot is a parsed 0.papgt template.
type PapgtSnapshot struct {
	RawLength     int             `json:"raw_length"`
	ChecksumBytes []byte          `json:"checksum_bytes"` // first 4 bytes
	CountBytes    []byte          `json:"count_bytes"`    // bytes 8..12
	Records       []ArchiveRecord `json:"records"`
}

// ParsePapgt reads and parses a 0.papgt file.
func ParsePapgt(path string) (*PapgtSnapshot, error) {
	blob, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(blob) < 16 {
		return nil, fmt.Errorf("%s is too small for a valid 0.papgt", path)
	}

	records, err := locateAndDecode(blob)
	if err != nil {
		return nil, err
	}

	return &PapgtSnapshot{
		RawLength:     len(blob),
		ChecksumBytes: append([]byte{}, blob[0:4]...),
		CountBytes:    append([]byte{}, blob[8:12]...),
		Records:       records,
	}, nil
}

// BuildPapgtBytes rebuilds 0.papgt with mod bundles prepended.
func BuildPapgtBytes(template *PapgtSnapshot, modBundleNames []string, pamtCrcByName map[string]uint32) ([]byte, error) {
	existing := make(map[string]*ArchiveRecord)
	for i := range template.Records {
		existing[template.Records[i].Name] = &template.Records[i]
	}
	if len(existing) == 0 {
		return nil, fmt.Errorf("base 0.papgt has no archive entries")
	}

	// Collect: new mod bundles first, then originals
	var combined []ArchiveRecord
	for _, bname := range modBundleNames {
		if _, ok := existing[bname]; ok {
			continue
		}
		crc, ok := pamtCrcByName[bname]
		if !ok {
			return nil, fmt.Errorf("missing PAMT CRC for bundle %s", bname)
		}
		combined = append(combined, ArchiveRecord{Name: bname, Flags: 0x003FFF00, PamtCrc: crc})
	}
	combined = append(combined, template.Records...)

	// Serialize: string table + record block
	strtab := make([]byte, 0, len(combined)*5)
	recs := make([]byte, 0, len(combined)*12)
	for _, rec := range combined {
		var buf [12]byte
		binary.LittleEndian.PutUint32(buf[0:], rec.Flags)
		binary.LittleEndian.PutUint32(buf[4:], uint32(len(strtab)))
		binary.LittleEndian.PutUint32(buf[8:], rec.PamtCrc)
		recs = append(recs, buf[:]...)
		strtab = append(strtab, []byte(rec.Name)...)
		strtab = append(strtab, 0)
	}

	// Assemble
	out := make([]byte, 0, 12+len(recs)+4+len(strtab))
	out = append(out, template.ChecksumBytes...)
	out = append(out, 0, 0, 0, 0) // hash placeholder
	cnt := append([]byte{}, template.CountBytes...)
	cnt[0] = byte(len(combined) & 0xFF)
	out = append(out, cnt...)
	out = append(out, recs...)

	var stLen [4]byte
	binary.LittleEndian.PutUint32(stLen[:], uint32(len(strtab)))
	out = append(out, stLen[:]...)
	out = append(out, strtab...)

	// Compute hash over bytes[12:]
	hash := Hashlittle(out[12:], hashInitval)
	binary.LittleEndian.PutUint32(out[4:], hash)

	return out, nil
}

func tryDecodeAt(blob []byte, boundary int) []ArchiveRecord {
	total := len(blob)
	if boundary+4 > total {
		return nil
	}
	strtabLen := int(binary.LittleEndian.Uint32(blob[boundary:]))
	if boundary+4+strtabLen != total {
		return nil
	}
	recSpan := boundary - 12
	if recSpan < 0 || recSpan%12 != 0 {
		return nil
	}

	strtab := blob[boundary+4:]
	var result []ArchiveRecord

	for pos := 12; pos < boundary; pos += 12 {
		fl := binary.LittleEndian.Uint32(blob[pos:])
		noff := int(binary.LittleEndian.Uint32(blob[pos+4:]))
		crc := binary.LittleEndian.Uint32(blob[pos+8:])

		if noff >= strtabLen {
			return nil
		}
		// Find null terminator
		nul := -1
		for i := noff; i < len(strtab); i++ {
			if strtab[i] == 0 {
				nul = i
				break
			}
		}
		if nul < 0 {
			return nil
		}
		name := string(strtab[noff:nul])
		if len(name) != 4 {
			return nil
		}
		// Check all digits
		allDigit := true
		for _, c := range name {
			if c < '0' || c > '9' {
				allDigit = false
				break
			}
		}
		if !allDigit {
			return nil
		}
		result = append(result, ArchiveRecord{Name: name, Flags: fl, PamtCrc: crc})
	}

	if len(result) == 0 {
		return nil
	}
	return result
}

func locateAndDecode(blob []byte) ([]ArchiveRecord, error) {
	total := len(blob)
	lastCandidate := ((total - 4) / 4) * 4
	firstCandidate := 12

	for probe := lastCandidate; probe >= firstCandidate; probe -= 4 {
		result := tryDecodeAt(blob, probe)
		if result != nil {
			return result, nil
		}
	}
	return nil, fmt.Errorf("failed to locate record table in 0.papgt")
}

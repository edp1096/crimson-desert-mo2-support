package main

import (
	"encoding/binary"
	"fmt"
	"os"
)

// PaverInfo holds game version info from 0.paver.
type PaverInfo struct {
	Major    uint16 `json:"major"`
	Minor    uint16 `json:"minor"`
	Patch    uint16 `json:"patch"`
	Checksum uint32 `json:"checksum"`
}

func (p *PaverInfo) VersionString() string {
	return fmt.Sprintf("v%d.%02d.%02d", p.Major, p.Minor, p.Patch)
}

// ReadPaver reads a 0.paver file.
func ReadPaver(path string) (*PaverInfo, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(data) < 10 {
		return nil, fmt.Errorf("%s is too small for a valid 0.paver", path)
	}
	return &PaverInfo{
		Major:    binary.LittleEndian.Uint16(data[0:]),
		Minor:    binary.LittleEndian.Uint16(data[2:]),
		Patch:    binary.LittleEndian.Uint16(data[4:]),
		Checksum: binary.LittleEndian.Uint32(data[6:]),
	}, nil
}

// SerializePaver serializes PaverInfo to bytes.
func SerializePaver(info *PaverInfo) []byte {
	buf := make([]byte, 10)
	binary.LittleEndian.PutUint16(buf[0:], info.Major)
	binary.LittleEndian.PutUint16(buf[2:], info.Minor)
	binary.LittleEndian.PutUint16(buf[4:], info.Patch)
	binary.LittleEndian.PutUint32(buf[6:], info.Checksum)
	return buf
}

// Standalone tool to search game PAMT entries by filename.
// Build: go build -o find_entry.exe find_entry.go
// Usage: find_entry.exe "D:\games\steam\steamapps\common\Crimson Desert" inputmap

package main

import (
	"encoding/binary"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

func main() {
	if len(os.Args) < 3 {
		fmt.Fprintf(os.Stderr, "Usage: %s <game_path> <search_term>\n", os.Args[0])
		os.Exit(1)
	}
	gamePath := os.Args[1]
	search := strings.ToLower(os.Args[2])

	entries, err := os.ReadDir(gamePath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Cannot read %s: %v\n", gamePath, err)
		os.Exit(1)
	}

	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		name := e.Name()
		allDigit := true
		for _, c := range name {
			if c < '0' || c > '9' {
				allDigit = false
				break
			}
		}
		if !allDigit {
			continue
		}

		pamtPath := filepath.Join(gamePath, name, "0.pamt")
		if _, err := os.Stat(pamtPath); err != nil {
			continue
		}

		searchPamt(pamtPath, name, search)
	}
}

func searchPamt(pamtPath, groupName, search string) {
	data, err := os.ReadFile(pamtPath)
	if err != nil {
		return
	}
	if len(data) < 12 {
		return
	}

	pos := 0
	pos += 4 // integrity hash
	nPaz := int(binary.LittleEndian.Uint32(data[pos:]))
	pos += 4
	pos += 4 // unknown
	pos += nPaz * 12

	dirBlob, pos := readBlob2(data, pos)
	fnameBlob, pos := readBlob2(data, pos)

	nFolders := int(binary.LittleEndian.Uint32(data[pos:]))
	pos += 4

	type folderSpan struct {
		start, end int
		path       string
	}

	dirCache := make(map[int]string)
	var folders []folderSpan

	for i := 0; i < nFolders; i++ {
		if pos+16 > len(data) {
			return
		}
		_ = binary.LittleEndian.Uint32(data[pos:])
		noff := int(binary.LittleEndian.Uint32(data[pos+4:]))
		first := int(binary.LittleEndian.Uint32(data[pos+8:]))
		count := int(binary.LittleEndian.Uint32(data[pos+12:]))
		pos += 16

		if count > 0 {
			dp := normPath(reconstructPath2(dirBlob, noff, dirCache))
			folders = append(folders, folderSpan{start: first, end: first + count, path: dp})
		}
	}

	nFiles := int(binary.LittleEndian.Uint32(data[pos:]))
	pos += 4

	fnameCache := make(map[int]string)
	fi_folder := 0

	for fi := 0; fi < nFiles; fi++ {
		if pos+20 > len(data) {
			return
		}
		noff := int(binary.LittleEndian.Uint32(data[pos:]))
		_ = binary.LittleEndian.Uint32(data[pos+4:])  // offset
		_ = binary.LittleEndian.Uint32(data[pos+8:])  // comp_size
		_ = binary.LittleEndian.Uint32(data[pos+12:]) // orig_size
		_ = binary.LittleEndian.Uint16(data[pos+16:]) // paz_index
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

		fname := normPath(reconstructPath2(fnameBlob, noff, fnameCache))
		var vpath string
		if dprefix != "" {
			vpath = normPath(dprefix + "/" + fname)
		} else {
			vpath = fname
		}

		if strings.Contains(strings.ToLower(vpath), search) {
			fmt.Printf("group=%s  flags=0x%04X  path=%s\n", groupName, fl, vpath)
		}
	}
}

func readBlob2(data []byte, pos int) ([]byte, int) {
	length := int(binary.LittleEndian.Uint32(data[pos:]))
	pos += 4
	blob := data[pos : pos+length]
	pos += length
	return blob, pos
}

func reconstructPath2(blob []byte, at int, cache map[int]string) string {
	if at == 0xFFFFFFFF || at >= len(blob) {
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
	prefix := reconstructPath2(blob, parent, cache)
	result := prefix + seg
	cache[at] = result
	return result
}

func normPath(s string) string {
	s = strings.ReplaceAll(s, "\\", "/")
	return strings.Trim(s, "/")
}

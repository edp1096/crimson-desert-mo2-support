package main

import (
	"encoding/binary"
	"path/filepath"
	"sort"
	"strings"
)

// DirTrie serialises paths into the compact parent-pointer blob format used by PAMT.
type DirTrie struct {
	tree     map[string]interface{}
	offsets  map[uintptr]int // use string key instead
	nodeKeys map[string]int  // path -> offset
	buf      []byte
	dirNodes []dirNode
}

type dirNode struct {
	path   string
	offset int
}

func newDirTrie() *DirTrie {
	return &DirTrie{
		tree:     make(map[string]interface{}),
		nodeKeys: make(map[string]int),
	}
}

func (t *DirTrie) add(path string, register bool) int {
	segs := splitPath(path)
	if len(segs) == 0 {
		return int(sentinel)
	}

	// Walk/create trie
	node := t.tree
	full := ""
	for i, seg := range segs {
		if i == 0 {
			full = seg
		} else {
			full += "/" + seg
		}
		child, ok := node[seg]
		if !ok {
			child = make(map[string]interface{})
			node[seg] = child
		}
		node = child.(map[string]interface{})
	}

	off := t.ensureSerialized(segs)
	if register {
		t.dirNodes = append(t.dirNodes, dirNode{path: full, offset: off})
	}
	return off
}

func (t *DirTrie) ensureSerialized(segs []string) int {
	node := t.tree
	parentOff := int(sentinel)
	cumKey := ""

	for i, seg := range segs {
		if i == 0 {
			cumKey = seg
		} else {
			cumKey += "/" + seg
		}

		child := node[seg].(map[string]interface{})

		if _, exists := t.nodeKeys[cumKey]; !exists {
			off := len(t.buf)
			label := seg
			if i > 0 {
				label = "/" + seg
			}
			enc := []byte(label)

			var parentBytes [4]byte
			binary.LittleEndian.PutUint32(parentBytes[:], uint32(parentOff))
			t.buf = append(t.buf, parentBytes[:]...)
			t.buf = append(t.buf, byte(len(enc)))
			t.buf = append(t.buf, enc...)
			t.nodeKeys[cumKey] = off
		}

		parentOff = t.nodeKeys[cumKey]
		node = child
	}
	return parentOff
}

func (t *DirTrie) toBytes() []byte {
	return t.buf
}

func splitPath(s string) []string {
	s = strings.ReplaceAll(s, "\\", "/")
	s = strings.Trim(s, "/")
	if s == "" || s == "." {
		return nil
	}
	return strings.Split(s, "/")
}

// BuildPamtBytes builds a complete PAMT binary from entries.
func BuildPamtBytes(entries []PazEntry, pazInfos [][3]uint32, unknownField uint32) []byte {
	// Sort entries by dir (casefold) then filename (casefold)
	ordered := make([]PazEntry, len(entries))
	copy(ordered, entries)
	sort.Slice(ordered, func(i, j int) bool {
		di := strings.ToLower(filepath.Dir(normalizePath(ordered[i].Path)))
		dj := strings.ToLower(filepath.Dir(normalizePath(ordered[j].Path)))
		if di != dj {
			return di < dj
		}
		fi := strings.ToLower(filepath.Base(normalizePath(ordered[i].Path)))
		fj := strings.ToLower(filepath.Base(normalizePath(ordered[j].Path)))
		return fi < fj
	})

	// Build directory trie
	dirTrie := newDirTrie()
	dirsPerEntry := make([]string, len(ordered))
	uniqueDirs := make(map[string]bool)

	for i, e := range ordered {
		d := filepath.Dir(normalizePath(e.Path))
		d = strings.ReplaceAll(d, "\\", "/")
		dirsPerEntry[i] = d
		if d != "" && d != "." {
			uniqueDirs[d] = true
		}
	}

	sortedDirs := make([]string, 0, len(uniqueDirs))
	for d := range uniqueDirs {
		sortedDirs = append(sortedDirs, d)
	}
	sort.Slice(sortedDirs, func(i, j int) bool {
		return strings.ToLower(sortedDirs[i]) < strings.ToLower(sortedDirs[j])
	})
	for _, d := range sortedDirs {
		dirTrie.add(d, true)
	}

	// Build filename trie
	fnameTrie := newDirTrie()
	fnameOffsets := make([]int, len(ordered))
	for i, e := range ordered {
		name := filepath.Base(normalizePath(e.Path))
		fnameOffsets[i] = fnameTrie.add(name, false)
	}

	// Compute dir spans
	type span struct{ start, count int }
	dirSpans := make(map[string]*span)
	for idx, d := range dirsPerEntry {
		key := ""
		if d != "" && d != "." {
			key = normalizePath(d)
		}
		if s, ok := dirSpans[key]; ok {
			s.count++
		} else {
			dirSpans[key] = &span{start: idx, count: 1}
		}
	}

	// Assemble binary body
	body := make([]byte, 0, 4096)

	// PAZ file info
	for _, pi := range pazInfos {
		var buf [12]byte
		binary.LittleEndian.PutUint32(buf[0:], pi[0])
		binary.LittleEndian.PutUint32(buf[4:], pi[1])
		binary.LittleEndian.PutUint32(buf[8:], pi[2])
		body = append(body, buf[:]...)
	}

	// Name blobs
	dirBlob := dirTrie.toBytes()
	fnameBlob := fnameTrie.toBytes()
	body = appendU32(body, uint32(len(dirBlob)))
	body = append(body, dirBlob...)
	body = appendU32(body, uint32(len(fnameBlob)))
	body = append(body, fnameBlob...)

	// Directory hash table
	var dirRows [][]byte
	for _, dn := range dirTrie.dirNodes {
		s := dirSpans[dn.path]
		if s != nil && s.count > 0 {
			var row [16]byte
			hash := Hashlittle([]byte(dn.path), hashInitval)
			binary.LittleEndian.PutUint32(row[0:], hash)
			binary.LittleEndian.PutUint32(row[4:], uint32(dn.offset))
			binary.LittleEndian.PutUint32(row[8:], uint32(s.start))
			binary.LittleEndian.PutUint32(row[12:], uint32(s.count))
			dirRows = append(dirRows, row[:])
		}
	}
	body = appendU32(body, uint32(len(dirRows)))
	for _, row := range dirRows {
		body = append(body, row...)
	}

	// File records
	body = appendU32(body, uint32(len(ordered)))
	for i, e := range ordered {
		var rec [20]byte
		binary.LittleEndian.PutUint32(rec[0:], uint32(fnameOffsets[i]))
		binary.LittleEndian.PutUint32(rec[4:], e.Offset)
		binary.LittleEndian.PutUint32(rec[8:], e.CompSize)
		binary.LittleEndian.PutUint32(rec[12:], e.OrigSize)
		binary.LittleEndian.PutUint16(rec[16:], e.PazIndex)
		binary.LittleEndian.PutUint16(rec[18:], e.Flags)
		body = append(body, rec[:]...)
	}

	// Header: integrity_hash(4) + paz_count(4) + unknown(4)
	header := make([]byte, 12)
	binary.LittleEndian.PutUint32(header[4:], uint32(len(pazInfos)))
	binary.LittleEndian.PutUint32(header[8:], unknownField)

	full := append(header, body...)
	// Compute integrity hash over everything after first 12 bytes
	integrity := Hashlittle(full[12:], hashInitval)
	binary.LittleEndian.PutUint32(full[0:], integrity)

	return full
}

func appendU32(buf []byte, v uint32) []byte {
	var b [4]byte
	binary.LittleEndian.PutUint32(b[:], v)
	return append(buf, b[:]...)
}

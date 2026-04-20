package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
)

// LightEntry is a lightweight index entry (no offset/size).
type LightEntry struct {
	Path   string `json:"path"`
	Flags  uint16 `json:"flags"`
	Bundle string `json:"bundle"`
}

// GameIndex holds the light index for fast lookups.
type GameIndex struct {
	// key: casefold path → entries
	Global map[string][]LightEntry
	// key: bundle name → casefold path → entries
	ByGroup map[string]map[string][]LightEntry
}

// BuildGameIndex scans all game PAMTs and builds a lightweight index.
func BuildGameIndex(gamePath string) (*GameIndex, error) {
	idx := &GameIndex{
		Global:  make(map[string][]LightEntry),
		ByGroup: make(map[string]map[string][]LightEntry),
	}

	entries, err := os.ReadDir(gamePath)
	if err != nil {
		return idx, nil // empty index if game dir not found
	}

	// Collect and sort bundle dirs
	var bundleDirs []string
	for _, e := range entries {
		if e.IsDir() && isDigitString(e.Name()) {
			bundleDirs = append(bundleDirs, e.Name())
		}
	}
	sort.Strings(bundleDirs)

	// Parse all PAMTs in parallel
	type bundleResult struct {
		groupName string
		entries   []LightEntry
	}

	var wg sync.WaitGroup
	results := make(chan bundleResult, len(bundleDirs))

	for _, groupName := range bundleDirs {
		wg.Add(1)
		go func(gn string) {
			defer wg.Done()
			bundleDir := filepath.Join(gamePath, gn)
			pamtFiles, _ := filepath.Glob(filepath.Join(bundleDir, "*.pamt"))

			var lights []LightEntry
			for _, pamtPath := range pamtFiles {
				bundle, err := ParsePamt(pamtPath)
				if err != nil {
					continue
				}
				for _, entry := range bundle.Entries {
					lights = append(lights, LightEntry{
						Path:   entry.Path,
						Flags:  entry.Flags,
						Bundle: gn,
					})
				}
			}
			if len(lights) > 0 {
				results <- bundleResult{groupName: gn, entries: lights}
			}
		}(groupName)
	}

	go func() {
		wg.Wait()
		close(results)
	}()

	// Merge results
	for br := range results {
		groupEntries := make(map[string][]LightEntry)
		for _, light := range br.entries {
			key := strings.ToLower(normalizePath(light.Path))
			idx.Global[key] = append(idx.Global[key], light)
			groupEntries[key] = append(groupEntries[key], light)
		}
		idx.ByGroup[br.groupName] = groupEntries
	}

	return idx, nil
}

// FindLightEntry searches the index for an entry path.
func FindLightEntry(idx *GameIndex, gamePath string, sourceGroup string) *LightEntry {
	key := strings.ToLower(normalizePath(gamePath))

	// 1. Exact match in source group
	if sourceGroup != "" {
		for _, g := range []string{sourceGroup, strings.TrimLeft(sourceGroup, "0"), fmt.Sprintf("%04s", sourceGroup)} {
			if g == "" {
				g = "0"
			}
			if group, ok := idx.ByGroup[g]; ok {
				if lights, ok := group[key]; ok && len(lights) > 0 {
					return &lights[0]
				}
			}
		}
	}

	// 2. Exact match in global index
	if lights, ok := idx.Global[key]; ok && len(lights) > 0 {
		return &lights[0]
	}

	// 3. Suffix match: find entries ending with the query path
	suffix := "/" + key
	var suffixMatches []LightEntry
	for p, llist := range idx.Global {
		if strings.HasSuffix(p, suffix) {
			suffixMatches = append(suffixMatches, llist[0])
		}
	}
	if len(suffixMatches) == 1 {
		return &suffixMatches[0]
	}

	// 4. Filename fallback in source group
	basename := key
	if i := strings.LastIndex(key, "/"); i >= 0 {
		basename = key[i+1:]
	}

	if sourceGroup != "" {
		for _, g := range []string{sourceGroup, strings.TrimLeft(sourceGroup, "0"), fmt.Sprintf("%04s", sourceGroup)} {
			if g == "" {
				g = "0"
			}
			if group, ok := idx.ByGroup[g]; ok {
				var matches []LightEntry
				for p, llist := range group {
					if strings.HasSuffix(p, "/"+basename) || p == basename {
						matches = append(matches, llist[0])
					}
				}
				if len(matches) == 1 {
					return &matches[0]
				}
			}
		}
	}

	// 4. Filename fallback in global
	var matches []LightEntry
	for p, llist := range idx.Global {
		if strings.HasSuffix(p, "/"+basename) || p == basename {
			matches = append(matches, llist[0])
		}
	}
	if len(matches) == 1 {
		return &matches[0]
	}

	return nil
}

// InferFlags guesses compression flags from file extension.
func InferFlags(entryPath string) uint16 {
	ext := strings.ToLower(filepath.Ext(entryPath))
	switch ext {
	case ".xml":
		return 0x32 // LZ4 + ChaCha20
	case ".dds":
		return 0x01 // partial LZ4
	case ".lua", ".csv", ".txt", ".pabgb", ".pabgh":
		return 0x02 // LZ4
	}
	return 0x00
}

// ResolveLooseEntryPath resolves a relative mod path to a game archive entry path.
func ResolveLooseEntryPath(relParts []string) string {
	parts := make([]string, len(relParts))
	copy(parts, relParts)

	if len(parts) == 0 {
		return ""
	}

	// Strip "files/" prefix
	if strings.EqualFold(parts[0], "files") && len(parts) > 1 {
		parts = parts[1:]
	}

	// Strip archive number prefix
	if len(parts) > 1 && isDigitString(parts[0]) {
		parts = parts[1:]
	}

	if len(parts) == 0 {
		return ""
	}

	return normalizePath(strings.Join(parts, "/"))
}

// ApplyHexPatches applies hex offset patches to data.
func ApplyHexPatches(data []byte, changesJSON string) ([]byte, error) {
	var changes []map[string]interface{}
	if err := json.Unmarshal([]byte(changesJSON), &changes); err != nil {
		return data, err
	}

	result := make([]byte, len(data))
	copy(result, data)

	for _, change := range changes {
		offsetVal, ok := change["offset"]
		if !ok {
			continue
		}
		offset := int(toFloat64(offsetVal))

		patchedHex, ok := change["patched"]
		if !ok || patchedHex == nil {
			continue
		}

		patchedStr := fmt.Sprintf("%v", patchedHex)
		patched := hexDecode(patchedStr)
		if patched == nil {
			continue
		}

		if offset+len(patched) <= len(result) {
			copy(result[offset:], patched)
		}
	}

	return result, nil
}

// BuildModPAZ builds a PAZ+PAMT pair from packed entries.
// entries: list of {path, data (raw file bytes), flags}
// Returns (pazBytes, pamtBytes).
func BuildModPAZ(entriesJSON string, gamePath string) ([]byte, []byte, error) {
	var items []struct {
		Path      string `json:"path"`
		DataPath  string `json:"data_path"` // file to read
		Flags     uint16 `json:"flags"`
		PazFile   string `json:"paz_file,omitempty"`   // for extraction from game
		Offset    uint32 `json:"offset,omitempty"`
		CompSize  uint32 `json:"comp_size,omitempty"`
		OrigSize  uint32 `json:"orig_size,omitempty"`
		IsGameRef bool   `json:"is_game_ref,omitempty"` // true = extract from game PAZ
	}
	if err := json.Unmarshal([]byte(entriesJSON), &items); err != nil {
		return nil, nil, err
	}

	pazPayload := make([]byte, 0, 1024*1024)
	var packedEntries []PazEntry

	for _, item := range items {
		var fileData []byte
		var err error

		if item.IsGameRef {
			// Extract from game PAZ
			ref := &PazEntry{
				Path: item.Path, PazFile: item.PazFile,
				Offset: item.Offset, CompSize: item.CompSize,
				OrigSize: item.OrigSize, Flags: item.Flags,
			}
			fileData, err = ExtractEntryBytes(ref, true)
		} else {
			fileData, err = os.ReadFile(item.DataPath)
		}
		if err != nil {
			return nil, nil, fmt.Errorf("read %s: %w", item.Path, err)
		}

		payload, actualFlags := PackEntryBytes(fileData, item.Flags, item.Path, true)

		entryOffset := len(pazPayload)
		pazPayload = append(pazPayload, payload...)
		// 16-byte alignment padding
		if pad := (16 - (len(pazPayload) % 16)) % 16; pad > 0 {
			pazPayload = append(pazPayload, make([]byte, pad)...)
		}

		packedEntries = append(packedEntries, PazEntry{
			Path:     normalizePath(item.Path),
			PazFile:  "0.paz",
			Offset:   uint32(entryOffset),
			CompSize: uint32(len(payload)),
			OrigSize: uint32(len(fileData)),
			Flags:    actualFlags,
			PazIndex: 0,
		})
	}

	if len(packedEntries) == 0 {
		return nil, nil, fmt.Errorf("no entries to build")
	}

	pazBytes := pazPayload
	pamtBytes := BuildPamtBytes(
		packedEntries,
		[][3]uint32{{0, Hashlittle(pazBytes, hashInitval), uint32(len(pazBytes))}},
		0x610E0232,
	)

	return pazBytes, pamtBytes, nil
}

func isDigitString(s string) bool {
	if s == "" {
		return false
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

func toFloat64(v interface{}) float64 {
	switch val := v.(type) {
	case float64:
		return val
	case int:
		return float64(val)
	case json.Number:
		f, _ := val.Float64()
		return f
	}
	return 0
}

func hexDecode(s string) []byte {
	s = strings.ReplaceAll(s, " ", "")
	if len(s)%2 != 0 {
		return nil
	}
	result := make([]byte, len(s)/2)
	for i := 0; i < len(s); i += 2 {
		var b byte
		for j, c := range s[i : i+2] {
			var nibble byte
			switch {
			case c >= '0' && c <= '9':
				nibble = byte(c - '0')
			case c >= 'a' && c <= 'f':
				nibble = byte(c - 'a' + 10)
			case c >= 'A' && c <= 'F':
				nibble = byte(c - 'A' + 10)
			default:
				return nil
			}
			if j == 0 {
				b = nibble << 4
			} else {
				b |= nibble
			}
		}
		result[i/2] = b
	}
	return result
}

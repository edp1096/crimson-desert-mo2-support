package main

/*
#include <stdlib.h>
#include <stdint.h>
*/
import "C"
import (
	"encoding/json"
	"unsafe"
)

// --- Memory management ---

//export PazCoreFree
func PazCoreFree(ptr unsafe.Pointer) {
	C.free(ptr)
}

// --- Jenkins hash ---

//export PazCoreHashlittle
func PazCoreHashlittle(data *C.char, dataLen C.int, initval C.uint32_t) C.uint32_t {
	goData := C.GoBytes(unsafe.Pointer(data), dataLen)
	return C.uint32_t(Hashlittle(goData, uint32(initval)))
}

// --- PAMT parsing ---

//export PazCoreParsePamt
func PazCoreParsePamt(pamtPath *C.char) *C.char {
	path := C.GoString(pamtPath)
	bundle, err := ParsePamt(path)
	if err != nil {
		errJSON, _ := json.Marshal(map[string]string{"error": err.Error()})
		return C.CString(string(errJSON))
	}
	return C.CString(marshalPamtBundle(bundle))
}

// --- Entry extraction ---

//export PazCoreExtractEntry
func PazCoreExtractEntry(
	pazFile *C.char,
	offset C.uint32_t,
	compSize C.uint32_t,
	origSize C.uint32_t,
	flags C.uint16_t,
	entryPath *C.char,
	decryptXML C.int,
	outLen *C.int,
) unsafe.Pointer {
	entry := &PazEntry{
		Path:     C.GoString(entryPath),
		PazFile:  C.GoString(pazFile),
		Offset:   uint32(offset),
		CompSize: uint32(compSize),
		OrigSize: uint32(origSize),
		Flags:    uint16(flags),
	}

	data, err := ExtractEntryBytes(entry, decryptXML != 0)
	if err != nil {
		*outLen = 0
		return nil
	}

	*outLen = C.int(len(data))
	ptr := C.malloc(C.size_t(len(data)))
	copy((*[1 << 30]byte)(ptr)[:len(data)], data)
	return ptr
}

// --- Entry packing ---

//export PazCorePackEntry
func PazCorePackEntry(
	data unsafe.Pointer,
	dataLen C.int,
	flags C.uint16_t,
	entryPath *C.char,
	encryptXML C.int,
	outLen *C.int,
	outFlags *C.uint16_t,
) unsafe.Pointer {
	goData := C.GoBytes(data, dataLen)
	payload, actualFlags := PackEntryBytes(goData, uint16(flags), C.GoString(entryPath), encryptXML != 0)

	*outLen = C.int(len(payload))
	*outFlags = C.uint16_t(actualFlags)
	ptr := C.malloc(C.size_t(len(payload)))
	copy((*[1 << 30]byte)(ptr)[:len(payload)], payload)
	return ptr
}

// --- PAMT building ---

//export PazCoreBuildPamt
func PazCoreBuildPamt(entriesJSON *C.char, pazInfosJSON *C.char, unknownField C.uint32_t, outLen *C.int) unsafe.Pointer {
	var entries []PazEntry
	if err := json.Unmarshal([]byte(C.GoString(entriesJSON)), &entries); err != nil {
		*outLen = 0
		return nil
	}

	var pazInfos [][3]uint32
	if err := json.Unmarshal([]byte(C.GoString(pazInfosJSON)), &pazInfos); err != nil {
		*outLen = 0
		return nil
	}

	result := BuildPamtBytes(entries, pazInfos, uint32(unknownField))

	*outLen = C.int(len(result))
	ptr := C.malloc(C.size_t(len(result)))
	copy((*[1 << 30]byte)(ptr)[:len(result)], result)
	return ptr
}

// --- ChaCha20 ---

//export PazCoreChacha20
func PazCoreChacha20(data unsafe.Pointer, dataLen C.int, filename *C.char, outLen *C.int) unsafe.Pointer {
	goData := C.GoBytes(data, dataLen)
	result := ChaCha20Crypt(goData, C.GoString(filename))

	*outLen = C.int(len(result))
	ptr := C.malloc(C.size_t(len(result)))
	copy((*[1 << 30]byte)(ptr)[:len(result)], result)
	return ptr
}

// --- LZ4 ---

//export PazCoreLZ4Decompress
func PazCoreLZ4Decompress(data unsafe.Pointer, dataLen C.int, origSize C.int, outLen *C.int) unsafe.Pointer {
	goData := C.GoBytes(data, dataLen)
	result, err := LZ4Decompress(goData, int(origSize))
	if err != nil {
		*outLen = 0
		return nil
	}

	*outLen = C.int(len(result))
	ptr := C.malloc(C.size_t(len(result)))
	copy((*[1 << 30]byte)(ptr)[:len(result)], result)
	return ptr
}

//export PazCoreLZ4Compress
func PazCoreLZ4Compress(data unsafe.Pointer, dataLen C.int, outLen *C.int) unsafe.Pointer {
	goData := C.GoBytes(data, dataLen)
	result, err := LZ4Compress(goData)
	if err != nil || result == nil {
		*outLen = 0
		return nil
	}

	*outLen = C.int(len(result))
	ptr := C.malloc(C.size_t(len(result)))
	copy((*[1 << 30]byte)(ptr)[:len(result)], result)
	return ptr
}

// --- PAMT Header CRC ---

//export PazCoreReadPamtHeaderCrc
func PazCoreReadPamtHeaderCrc(pamtPath *C.char) C.uint32_t {
	crc, err := ReadPamtHeaderCrc(C.GoString(pamtPath))
	if err != nil {
		return 0
	}
	return C.uint32_t(crc)
}

// --- Partial DDS ---

//export PazCoreIsPrepackedDDS
func PazCoreIsPrepackedDDS(data unsafe.Pointer, dataLen C.int) C.int {
	goData := C.GoBytes(data, dataLen)
	if IsPrepackedDDS(goData) {
		return 1
	}
	return 0
}

// --- PAPGT ---

//export PazCoreParsePapgt
func PazCoreParsePapgt(path *C.char) *C.char {
	snap, err := ParsePapgt(C.GoString(path))
	if err != nil {
		errJSON, _ := json.Marshal(map[string]string{"error": err.Error()})
		return C.CString(string(errJSON))
	}
	data, _ := json.Marshal(snap)
	return C.CString(string(data))
}

//export PazCoreBuildPapgt
func PazCoreBuildPapgt(templateJSON *C.char, modNamesJSON *C.char, crcMapJSON *C.char, outLen *C.int) unsafe.Pointer {
	var template PapgtSnapshot
	if err := json.Unmarshal([]byte(C.GoString(templateJSON)), &template); err != nil {
		*outLen = 0
		return nil
	}

	var modNames []string
	if err := json.Unmarshal([]byte(C.GoString(modNamesJSON)), &modNames); err != nil {
		*outLen = 0
		return nil
	}

	var crcMap map[string]uint32
	if err := json.Unmarshal([]byte(C.GoString(crcMapJSON)), &crcMap); err != nil {
		*outLen = 0
		return nil
	}

	result, err := BuildPapgtBytes(&template, modNames, crcMap)
	if err != nil {
		*outLen = 0
		return nil
	}

	*outLen = C.int(len(result))
	ptr := C.malloc(C.size_t(len(result)))
	copy((*[1 << 30]byte)(ptr)[:len(result)], result)
	return ptr
}

// --- PATHC ---

//export PazCoreReadPathc
func PazCoreReadPathc(path *C.char) *C.char {
	pathc, err := ReadPathc(C.GoString(path))
	if err != nil {
		errJSON, _ := json.Marshal(map[string]string{"error": err.Error()})
		return C.CString(string(errJSON))
	}
	data, _ := json.Marshal(pathc)
	return C.CString(string(data))
}

//export PazCoreSerializePathc
func PazCoreSerializePathc(pathcJSON *C.char, outLen *C.int) unsafe.Pointer {
	var pathc PathcFile
	if err := json.Unmarshal([]byte(C.GoString(pathcJSON)), &pathc); err != nil {
		*outLen = 0
		return nil
	}

	result := SerializePathc(&pathc)
	*outLen = C.int(len(result))
	ptr := C.malloc(C.size_t(len(result)))
	copy((*[1 << 30]byte)(ptr)[:len(result)], result)
	return ptr
}

//export PazCoreGetPathcHash
func PazCoreGetPathcHash(virtualPath *C.char) C.uint32_t {
	return C.uint32_t(GetPathcHash(C.GoString(virtualPath)))
}

//export PazCoreGetDDSMetadata
func PazCoreGetDDSMetadata(data unsafe.Pointer, dataLen C.int, out unsafe.Pointer) {
	goData := C.GoBytes(data, dataLen)
	m := GetDDSMetadata(goData)
	outSlice := (*[4]C.uint32_t)(out)
	outSlice[0] = C.uint32_t(m[0])
	outSlice[1] = C.uint32_t(m[1])
	outSlice[2] = C.uint32_t(m[2])
	outSlice[3] = C.uint32_t(m[3])
}

// --- PAVER ---

//export PazCoreReadPaver
func PazCoreReadPaver(path *C.char) *C.char {
	info, err := ReadPaver(C.GoString(path))
	if err != nil {
		errJSON, _ := json.Marshal(map[string]string{"error": err.Error()})
		return C.CString(string(errJSON))
	}
	data, _ := json.Marshal(info)
	return C.CString(string(data))
}

//export PazCoreSerializePaver
func PazCoreSerializePaver(paverJSON *C.char, outLen *C.int) unsafe.Pointer {
	var info PaverInfo
	if err := json.Unmarshal([]byte(C.GoString(paverJSON)), &info); err != nil {
		*outLen = 0
		return nil
	}

	result := SerializePaver(&info)
	*outLen = C.int(len(result))
	ptr := C.malloc(C.size_t(len(result)))
	copy((*[1 << 30]byte)(ptr)[:len(result)], result)
	return ptr
}

// --- Builder: Game Index ---

//export PazCoreBuildGameIndex
func PazCoreBuildGameIndex(gamePath *C.char) C.uintptr_t {
	idx, err := BuildGameIndex(C.GoString(gamePath))
	if err != nil || idx == nil {
		return 0
	}
	handle := registerHandle(idx)
	return C.uintptr_t(handle)
}

//export PazCoreFreeGameIndex
func PazCoreFreeGameIndex(handle C.uintptr_t) {
	unregisterHandle(uint64(handle))
}

//export PazCoreFindLightEntry
func PazCoreFindLightEntry(handle C.uintptr_t, gamePath *C.char, sourceGroup *C.char) *C.char {
	idx := getHandle(uint64(handle))
	if idx == nil {
		return C.CString("{}")
	}
	gi := idx.(*GameIndex)
	sg := ""
	if sourceGroup != nil {
		sg = C.GoString(sourceGroup)
	}
	entry := FindLightEntry(gi, C.GoString(gamePath), sg)
	if entry == nil {
		return C.CString("null")
	}
	data, _ := json.Marshal(entry)
	return C.CString(string(data))
}

// --- Builder: Resolve, Infer, Patch ---

//export PazCoreResolveLooseEntryPath
func PazCoreResolveLooseEntryPath(relPartsJSON *C.char) *C.char {
	var parts []string
	json.Unmarshal([]byte(C.GoString(relPartsJSON)), &parts)
	result := ResolveLooseEntryPath(parts)
	return C.CString(result)
}

//export PazCoreInferFlags
func PazCoreInferFlags(entryPath *C.char) C.uint16_t {
	return C.uint16_t(InferFlags(C.GoString(entryPath)))
}

//export PazCoreApplyHexPatches
func PazCoreApplyHexPatches(data unsafe.Pointer, dataLen C.int, changesJSON *C.char, outLen *C.int) unsafe.Pointer {
	goData := C.GoBytes(data, dataLen)
	result, err := ApplyHexPatches(goData, C.GoString(changesJSON))
	if err != nil {
		*outLen = 0
		return nil
	}
	*outLen = C.int(len(result))
	ptr := C.malloc(C.size_t(len(result)))
	copy((*[1 << 30]byte)(ptr)[:len(result)], result)
	return ptr
}

// --- Builder: Build PAZ+PAMT ---

//export PazCoreBuildModPAZ
func PazCoreBuildModPAZ(entriesJSON *C.char, gamePath *C.char, pazOutLen *C.int, pamtOutLen *C.int) unsafe.Pointer {
	pazBytes, pamtBytes, err := BuildModPAZ(C.GoString(entriesJSON), C.GoString(gamePath))
	if err != nil {
		*pazOutLen = 0
		*pamtOutLen = 0
		return nil
	}

	// Return concatenated: [paz_bytes][pamt_bytes]
	total := len(pazBytes) + len(pamtBytes)
	ptr := C.malloc(C.size_t(total))
	buf := (*[1 << 30]byte)(ptr)[:total]
	copy(buf, pazBytes)
	copy(buf[len(pazBytes):], pamtBytes)

	*pazOutLen = C.int(len(pazBytes))
	*pamtOutLen = C.int(len(pamtBytes))
	return ptr
}

// --- Handle management for opaque pointers ---

var (
	handleCounter uint64 = 1
	handles              = make(map[uint64]interface{})
)

func registerHandle(obj interface{}) uint64 {
	h := handleCounter
	handleCounter++
	handles[h] = obj
	return h
}

func getHandle(h uint64) interface{} {
	return handles[h]
}

func unregisterHandle(h uint64) {
	delete(handles, h)
}

func main() {}

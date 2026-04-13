package main

import (
	"encoding/binary"
)

const (
	ddsMagicStr = "DDS "
	hdrBase     = 128
	hdrDX10     = 148
)

var ddsMagic = []byte(ddsMagicStr)

var fourccTile = map[string]int{
	"DXT1": 8, "ATI1": 8, "BC4U": 8, "BC4S": 8,
	"DXT3": 16, "DXT5": 16, "ATI2": 16, "BC5U": 16, "BC5S": 16,
	"DXT2": 16, "DXT4": 16,
}

var dxgi8 = map[uint32]bool{70: true, 71: true, 72: true, 79: true, 80: true, 81: true}
var dxgi16 = map[uint32]bool{
	73: true, 74: true, 75: true, 76: true, 77: true, 78: true,
	82: true, 83: true, 84: true, 94: true, 95: true, 96: true,
	97: true, 98: true, 99: true,
}

var tagFourcc = map[string]uint32{
	"DXT1": 12, "DXT2": 15, "DXT3": 15, "DXT4": 15, "DXT5": 15,
	"ATI1": 4, "ATI2": 4, "BC4U": 4, "BC4S": 4, "BC5U": 4, "BC5S": 4,
}

var tagDxgi = map[uint32]uint32{
	71: 12, 72: 12, 74: 15, 75: 15, 77: 15, 78: 15,
	80: 4, 81: 4, 83: 4, 84: 4, 95: 4, 96: 4, 98: 15, 99: 15,
}

type ddsInfo struct {
	w, h, depth, mips int
	fourcc            string
	caps2             uint32
	isDX10            bool
	hdrLen            int
	dxgi              uint32
	arrSize           uint32
	reserved1         [11]uint32
}

func parseDDSInfo(data []byte) *ddsInfo {
	info := &ddsInfo{}
	info.h = int(binary.LittleEndian.Uint32(data[12:]))
	info.w = int(binary.LittleEndian.Uint32(data[16:]))
	info.depth = int(binary.LittleEndian.Uint32(data[24:]))
	info.mips = int(binary.LittleEndian.Uint32(data[28:]))
	if info.mips < 1 {
		info.mips = 1
	}
	info.fourcc = string(data[84:88])
	info.caps2 = binary.LittleEndian.Uint32(data[112:])
	info.isDX10 = info.fourcc == "DX10"
	if info.isDX10 {
		info.hdrLen = hdrDX10
	} else {
		info.hdrLen = hdrBase
	}
	if info.isDX10 && len(data) >= hdrDX10 {
		info.dxgi = binary.LittleEndian.Uint32(data[0x80:])
		info.arrSize = binary.LittleEndian.Uint32(data[0x8C:])
	} else {
		info.arrSize = 1
	}
	for i := 0; i < 11; i++ {
		info.reserved1[i] = binary.LittleEndian.Uint32(data[32+i*4:])
	}
	return info
}

func (info *ddsInfo) tileBytes() int {
	if t, ok := fourccTile[info.fourcc]; ok {
		return t
	}
	if info.isDX10 {
		if dxgi8[info.dxgi] {
			return 8
		}
		if dxgi16[info.dxgi] {
			return 16
		}
	}
	return 0
}

func (info *ddsInfo) isMultiChunk() bool {
	if info.isDX10 && info.arrSize >= 2 {
		return false
	}
	return info.mips > 5 && info.caps2 == 0 && info.depth < 2
}

func mipBytes(w, h, tb int) int {
	bw := (w + 3) >> 2
	if bw < 1 {
		bw = 1
	}
	bh := (h + 3) >> 2
	if bh < 1 {
		bh = 1
	}
	return bw * bh * tb
}

func (info *ddsInfo) mipChain(count int) []int {
	tb := info.tileBytes()
	if tb == 0 {
		return nil
	}
	sizes := make([]int, 0, count)
	mw, mh := max(1, info.w), max(1, info.h)
	for i := 0; i < count; i++ {
		sizes = append(sizes, mipBytes(mw, mh, tb))
		mw = max(1, mw>>1)
		mh = max(1, mh>>1)
	}
	return sizes
}

// IsPrepackedDDS checks if DDS already has game-format mip info in reserved1.
func IsPrepackedDDS(data []byte) bool {
	if len(data) < hdrBase || string(data[:4]) != ddsMagicStr {
		return false
	}
	return binary.LittleEndian.Uint32(data[32:]) > 0 &&
		binary.LittleEndian.Uint32(data[36:]) > 0
}

// PartialDDSDecompress decompresses a partial-DDS (compression_type 1).
func PartialDDSDecompress(data []byte, origSize int) []byte {
	if len(data) < hdrBase || string(data[:4]) != ddsMagicStr {
		return data
	}
	info := parseDDSInfo(data)
	if len(data) < info.hdrLen {
		return data
	}

	bodyTotal := origSize - info.hdrLen
	multi := info.isMultiChunk()

	var cSizes, dSizes []int
	if !multi {
		cSizes = []int{int(info.reserved1[0])}
		dSizes = []int{bodyTotal}
	} else {
		chain := info.mipChain(1)
		expectedM0 := 0
		if len(chain) > 0 {
			expectedM0 = chain[0]
		}
		if expectedM0 > 0 && int(info.reserved1[1]) == expectedM0 {
			cSizes = []int{int(info.reserved1[0])}
			dSizes = []int{bodyTotal}
		} else {
			cSizes = make([]int, 4)
			for i := 0; i < 4; i++ {
				cSizes[i] = int(info.reserved1[i])
			}
			chain4 := info.mipChain(min(4, info.mips))
			if chain4 != nil {
				dSizes = chain4
			} else {
				dSizes = make([]int, 4)
				copy(dSizes, cSizes)
			}
		}
	}

	out := make([]byte, 0, origSize)
	out = append(out, data[:info.hdrLen]...)
	cur := info.hdrLen
	done := 0

	for i := 0; i < len(cSizes) && i < len(dSizes); i++ {
		cs, ds := cSizes[i], dSizes[i]
		if cs <= 0 || ds <= 0 {
			continue
		}
		if cs == ds {
			end := cur + ds
			if end > len(data) {
				end = len(data)
			}
			out = append(out, data[cur:end]...)
			cur += ds
		} else {
			end := cur + cs
			if end > len(data) {
				end = len(data)
			}
			blk := data[cur:end]
			if len(blk) >= cs {
				decompressed, err := LZ4Decompress(blk, ds)
				if err == nil {
					out = append(out, decompressed...)
				} else {
					out = append(out, blk...)
				}
			} else {
				out = append(out, blk...)
			}
			if cs > len(blk) {
				cur += cs
			} else {
				cur += len(blk)
			}
		}
		done += ds
	}

	tailLen := bodyTotal - done
	if tailLen > 0 && cur < len(data) {
		end := cur + tailLen
		if end > len(data) {
			end = len(data)
		}
		out = append(out, data[cur:end]...)
	}

	return out
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

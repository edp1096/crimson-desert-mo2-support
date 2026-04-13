package main

import (
	"bytes"

	"github.com/pierrec/lz4/v4"
)

// LZ4Decompress decompresses LZ4 block data to the given original size.
func LZ4Decompress(data []byte, origSize int) ([]byte, error) {
	dst := make([]byte, origSize)
	n, err := lz4.UncompressBlock(data, dst)
	if err != nil {
		return nil, err
	}
	return dst[:n], nil
}

// LZ4Compress compresses data using LZ4 block format.
func LZ4Compress(data []byte) ([]byte, error) {
	dst := make([]byte, lz4.CompressBlockBound(len(data)))
	var ht [1 << 16]int
	n, err := lz4.CompressBlock(data, dst, ht[:])
	if err != nil {
		return nil, err
	}
	if n == 0 {
		// incompressible
		return nil, nil
	}
	return dst[:n], nil
}

// LZ4CompressCompat compresses data compatible with the Python lz4_pure output.
// Returns nil if compressed is not smaller than original.
func LZ4CompressCompat(data []byte) []byte {
	compressed, err := LZ4Compress(data)
	if err != nil || compressed == nil || len(compressed) >= len(data) {
		return nil
	}
	// Verify round-trip
	rt, err := LZ4Decompress(compressed, len(data))
	if err != nil || !bytes.Equal(rt, data) {
		return nil
	}
	return compressed
}

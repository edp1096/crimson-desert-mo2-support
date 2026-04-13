package main

import (
	"encoding/binary"
	"path/filepath"
	"strings"

	"golang.org/x/crypto/chacha20"
)

const (
	hashInitval = 0x000C5EDE
	ivXOR       = 0x60616263
)

var xorDeltas = [8]uint32{
	0x00000000, 0x0A0A0A0A, 0x0C0C0C0C, 0x06060606,
	0x0E0E0E0E, 0x0A0A0A0A, 0x06060606, 0x02020202,
}

// filenameHash computes the Jenkins hash of a lowercased filename.
func filenameHash(filename string) uint32 {
	base := strings.ToLower(filepath.Base(filename))
	return Hashlittle([]byte(base), hashInitval)
}

// DeriveKeyIV derives ChaCha20 key (32 bytes) and IV (16 bytes) from a filename.
func DeriveKeyIV(filename string) (key [32]byte, iv [16]byte) {
	h := filenameHash(filename)
	for i, d := range xorDeltas {
		binary.LittleEndian.PutUint32(key[i*4:], (h^ivXOR)^d)
	}
	hBytes := [4]byte{}
	binary.LittleEndian.PutUint32(hBytes[:], h)
	for i := 0; i < 4; i++ {
		copy(iv[i*4:], hBytes[:])
	}
	return
}

// ChaCha20Crypt encrypts/decrypts data using filename-derived ChaCha20.
// ChaCha20 is XOR-based so encrypt == decrypt.
func ChaCha20Crypt(data []byte, filename string) []byte {
	key, iv := DeriveKeyIV(filename)

	// Go's chacha20 takes 32-byte key + 12-byte nonce + counter.
	// Python uses 16-byte nonce as: [counter_lo, nonce0, nonce1, nonce2]
	// iv[0:4] = counter initial value, iv[4:16] = 12-byte nonce
	counter := binary.LittleEndian.Uint32(iv[0:4])
	nonce := iv[4:16]

	cipher, err := chacha20.NewUnauthenticatedCipher(key[:], nonce)
	if err != nil {
		return data // fallback
	}
	cipher.SetCounter(counter)

	out := make([]byte, len(data))
	cipher.XORKeyStream(out, data)
	return out
}

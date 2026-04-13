package main

import "encoding/binary"

func rotl32(v, n uint32) uint32 {
	return (v << n) | (v >> (32 - n))
}

// Hashlittle implements Jenkins lookup3 hashlittle (little-endian, returns c).
func Hashlittle(data []byte, initval uint32) uint32 {
	rem := len(data)
	init := uint32(0xDEADBEEF) + uint32(rem) + initval
	s := [3]uint32{init, init, init}
	p := 0

	type mixStep struct{ t, x, r int }
	mix := [6]mixStep{
		{0, 2, 4}, {1, 0, 6}, {2, 1, 8},
		{0, 2, 16}, {1, 0, 19}, {2, 1, 4},
	}

	for rem > 12 {
		s[0] += binary.LittleEndian.Uint32(data[p:])
		s[1] += binary.LittleEndian.Uint32(data[p+4:])
		s[2] += binary.LittleEndian.Uint32(data[p+8:])
		for _, m := range mix {
			o := 3 - m.t - m.x
			s[m.t] -= s[m.x]
			s[m.t] ^= rotl32(s[m.x], uint32(m.r))
			s[m.x] += s[o]
		}
		p += 12
		rem -= 12
	}

	// Tail: pad with zeros, add partial words via masking
	tail := make([]byte, 12)
	copy(tail, data[p:p+rem])

	type tailStep struct {
		byteOff int
		idx     int
	}
	for _, ts := range []tailStep{{8, 2}, {4, 1}, {0, 0}} {
		boundary := ts.byteOff + 4
		if rem >= boundary {
			s[ts.idx] += binary.LittleEndian.Uint32(tail[ts.byteOff:])
		} else if rem > ts.byteOff {
			raw := binary.LittleEndian.Uint32(tail[ts.byteOff:])
			shift := 8 * (boundary - rem)
			mask := uint32(0xFFFFFFFF) >> shift
			s[ts.idx] += raw & mask
		}
	}

	if rem == 0 {
		return s[2]
	}

	// Final avalanche (7 steps)
	fin := [7]mixStep{
		{2, 1, 14}, {0, 2, 11}, {1, 0, 25},
		{2, 1, 16}, {0, 2, 4}, {1, 0, 14}, {2, 1, 24},
	}
	for _, m := range fin {
		s[m.t] ^= s[m.x]
		s[m.t] -= rotl32(s[m.x], uint32(m.r))
	}

	return s[2]
}

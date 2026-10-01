// SHA-256 implemented from FIPS 180-4 (no third-party code; licensing note in
// THIRD_PARTY_NOTES.md). Single-shot and streaming; all inputs are byte spans.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string>

namespace pe {

struct Sha256 {
    uint32_t state[8];
    uint64_t bitlen;
    uint8_t buf[64];
    size_t buf_len;
};

void sha256_init(Sha256 &s);
void sha256_update(Sha256 &s, const uint8_t *data, size_t len);
void sha256_final(Sha256 &s, uint8_t out[32]);

// Returns lowercase hex (64 chars).
std::string sha256_hex(const uint8_t *data, size_t len);
std::string sha256_hex_of_file(const std::string &path, bool *ok);

} // namespace pe

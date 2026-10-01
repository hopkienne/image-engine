#include "sha256.h"
#include "file_util.h"
#include <cstring>

namespace pe {

namespace {

constexpr uint32_t K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

inline uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

void compress(uint32_t state[8], const uint8_t block[64]) {
    uint32_t w[64];
    for (int i = 0; i < 16; i++) {
        w[i] = (uint32_t(block[i * 4]) << 24) | (uint32_t(block[i * 4 + 1]) << 16) |
               (uint32_t(block[i * 4 + 2]) << 8) | uint32_t(block[i * 4 + 3]);
    }
    for (int i = 16; i < 64; i++) {
        uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
        uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = state[0], b = state[1], c = state[2], d = state[3];
    uint32_t e = state[4], f = state[5], g = state[6], h = state[7];
    for (int i = 0; i < 64; i++) {
        uint32_t S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        uint32_t ch = (e & f) ^ (~e & g);
        uint32_t t1 = h + S1 + ch + K[i] + w[i];
        uint32_t S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t t2 = S0 + maj;
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }
    state[0] += a; state[1] += b; state[2] += c; state[3] += d;
    state[4] += e; state[5] += f; state[6] += g; state[7] += h;
}

std::string to_hex(const uint8_t d[32]) {
    static const char *hex = "0123456789abcdef";
    std::string out;
    out.reserve(64);
    for (int i = 0; i < 32; i++) {
        out.push_back(hex[d[i] >> 4]);
        out.push_back(hex[d[i] & 15]);
    }
    return out;
}

} // namespace

void sha256_init(Sha256 &s) {
    s.state[0] = 0x6a09e667; s.state[1] = 0xbb67ae85;
    s.state[2] = 0x3c6ef372; s.state[3] = 0xa54ff53a;
    s.state[4] = 0x510e527f; s.state[5] = 0x9b05688c;
    s.state[6] = 0x1f83d9ab; s.state[7] = 0x5be0cd19;
    s.bitlen = 0;
    s.buf_len = 0;
}

void sha256_update(Sha256 &s, const uint8_t *data, size_t len) {
    s.bitlen += uint64_t(len) * 8;
    while (len > 0) {
        size_t take = 64 - s.buf_len;
        if (take > len) take = len;
        std::memcpy(s.buf + s.buf_len, data, take);
        s.buf_len += take;
        data += take;
        len -= take;
        if (s.buf_len == 64) {
            compress(s.state, s.buf);
            s.buf_len = 0;
        }
    }
}

void sha256_final(Sha256 &s, uint8_t out[32]) {
    uint64_t bitlen = s.bitlen;
    uint8_t pad = 0x80;
    sha256_update(s, &pad, 1);
    uint8_t zero = 0;
    while (s.buf_len != 56) sha256_update(s, &zero, 1);
    std::memset(s.buf + 56, 0, 8);
    for (int i = 0; i < 8; i++) s.buf[56 + i] = uint8_t(bitlen >> (56 - 8 * i));
    compress(s.state, s.buf);
    s.buf_len = 0;
    for (int i = 0; i < 8; i++) {
        out[i * 4] = uint8_t(s.state[i] >> 24);
        out[i * 4 + 1] = uint8_t(s.state[i] >> 16);
        out[i * 4 + 2] = uint8_t(s.state[i] >> 8);
        out[i * 4 + 3] = uint8_t(s.state[i]);
    }
}

std::string sha256_hex(const uint8_t *data, size_t len) {
    Sha256 s;
    sha256_init(s);
    sha256_update(s, data, len);
    uint8_t d[32];
    sha256_final(s, d);
    return to_hex(d);
}

std::string sha256_hex_of_file(const std::string &path, bool *ok) {
    FILE *f = utf8_fopen(path, "rb");
    if (!f) {
        if (ok) *ok = false;
        return {};
    }
    Sha256 s;
    sha256_init(s);
    uint8_t buf[1 << 16];
    size_t n;
    while ((n = std::fread(buf, 1, sizeof(buf), f)) > 0) sha256_update(s, buf, n);
    bool fail = std::ferror(f) != 0;
    std::fclose(f);
    if (fail) {
        if (ok) *ok = false;
        return {};
    }
    uint8_t d[32];
    sha256_final(s, d);
    if (ok) *ok = true;
    return to_hex(d);
}

} // namespace pe

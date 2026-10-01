#include "sha256.h"
#include "file_util.h"
#include "test_helpers.h"
#include <cstring>

using namespace pe;

TEST_CASE("sha256 standard vectors") {
    CHECK(sha256_hex(nullptr, 0) ==
          "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    const char *abc = "abc";
    CHECK(sha256_hex(reinterpret_cast<const uint8_t *>(abc), 3) ==
          "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    const char *two_blocks = "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq";
    CHECK(sha256_hex(reinterpret_cast<const uint8_t *>(two_blocks),
                     std::strlen(two_blocks)) ==
          "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
}

TEST_CASE("sha256 one million 'a' (streamed across many blocks)") {
    std::vector<uint8_t> buf(100000, 'a');
    Sha256 s;
    sha256_init(s);
    for (int i = 0; i < 10; i++) sha256_update(s, buf.data(), buf.size());
    uint8_t d[32];
    sha256_final(s, d);
    static const char *hex = "0123456789abcdef";
    std::string out;
    for (int i = 0; i < 32; i++) {
        out.push_back(hex[d[i] >> 4]);
        out.push_back(hex[d[i] & 15]);
    }
    CHECK(out == "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
}

TEST_CASE("sha256 file hashing matches buffer hashing") {
    auto dir = pe_test::temp_dir("sha_file");
    auto path = dir / "blob.bin";
    std::vector<uint8_t> data(65536 + 37); // spans multiple fread chunks
    for (size_t i = 0; i < data.size(); i++) data[i] = uint8_t(i * 31 + 7);
    {
        FILE *f = utf8_fopen(path.u8string(), "wb");
        REQUIRE(f);
        std::fwrite(data.data(), 1, data.size(), f);
        std::fclose(f);
    }
    bool ok = false;
    std::string file_hash = sha256_hex_of_file(path.u8string(), &ok);
    REQUIRE(ok);
    CHECK(file_hash == sha256_hex(data.data(), data.size()));
}

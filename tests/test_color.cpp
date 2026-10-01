#include <doctest/doctest.h>
#include "color.h"
#include "icc_srgb.h"
#include "sha256.h"
#include <cmath>
#include <cstring>

using namespace pe;

TEST_CASE("built-in sRGB ICC profile is well-formed and deterministic") {
    std::vector<uint8_t> a, b;
    REQUIRE(build_srgb_icc_profile(a));
    REQUIRE(build_srgb_icc_profile(b));
    CHECK(a == b); // byte-for-byte deterministic
    REQUIRE(a.size() > 128);
    const uint32_t declared_size = (uint32_t(a[0]) << 24) | (uint32_t(a[1]) << 16) |
                                   (uint32_t(a[2]) << 8) | uint32_t(a[3]);
    CHECK(declared_size == a.size());
    CHECK(std::memcmp(a.data() + 36, "acsp", 4) == 0);
    CHECK(std::memcmp(a.data() + 12, "mntr", 4) == 0);
    CHECK(std::memcmp(a.data() + 16, "RGB ", 4) == 0);
    CHECK(std::memcmp(a.data() + 20, "XYZ ", 4) == 0);
    // tag count is 9 (desc, wtpt, r/g/bXYZ, r/g/bTRC, cprt)
    const uint32_t tag_count = (uint32_t(a[128]) << 24) | (uint32_t(a[129]) << 16) |
                               (uint32_t(a[130]) << 8) | uint32_t(a[131]);
    CHECK(tag_count == 9);
    CHECK(srgb_icc_sha256().size() == 64);
}

TEST_CASE("ICC colorants and media white use one D50 convention") {
    std::vector<uint8_t> profile;
    REQUIRE(build_srgb_icc_profile(profile));
    auto u32 = [&](size_t at) {
        return (uint32_t(profile.at(at))<<24)|(uint32_t(profile.at(at+1))<<16)|
               (uint32_t(profile.at(at+2))<<8)|profile.at(at+3);
    };
    double sum[3]={0,0,0},white[3]={0,0,0};
    int found=0;
    for(uint32_t i=0;i<u32(128);++i) {
        const size_t tag=132+i*12;
        const bool colorant=std::memcmp(profile.data()+tag,"rXYZ",4)==0 ||
            std::memcmp(profile.data()+tag,"gXYZ",4)==0 || std::memcmp(profile.data()+tag,"bXYZ",4)==0;
        const bool wtpt=std::memcmp(profile.data()+tag,"wtpt",4)==0;
        if(!colorant && !wtpt) continue;
        const size_t offset=u32(tag+4);
        for(int c=0;c<3;++c) {
            const double value=int32_t(u32(offset+8+c*4))/65536.0;
            if(colorant) sum[c]+=value; else white[c]=value;
        }
        ++found;
    }
    REQUIRE(found==4);
    for(int c=0;c<3;++c) CHECK(std::abs(sum[c]-white[c])<=2.0/65536.0);
}

TEST_CASE("sRGB encode reference values") {
    CHECK(std::abs(double(srgb_encode_f(0.0f))) < 1e-12);
    CHECK(std::abs(double(srgb_encode_f(1.0f)) - 1.0) < 1e-12);
    CHECK(std::abs(double(srgb_encode_f(0.1f)) - 0.3491902126) < 1e-6);
    CHECK(std::abs(double(srgb_encode_f(0.5f)) - 0.7353569831) < 1e-6);
    // linear threshold point
    CHECK(std::abs(double(srgb_encode_f(0.0031308f)) - 0.0404499356) < 1e-6);
}

TEST_CASE("sRGB decode inverts encode within tolerance") {
    for (int i = 1; i < 1000; i++) {
        double v = i / 1000.0;
        double roundtrip = srgb_decode_d(srgb_encode_d(v));
        CHECK(std::abs(roundtrip - v) < 1e-9);
    }
}

TEST_CASE("finite u16 encode cache is bit exact over the entire decoder input set") {
    const auto &table = srgb_u16_encode_table();
    size_t wrong_index = 0, changed = 0;
    for (uint32_t sample = 0; sample < 65536; ++sample) {
        const float value = float(sample) * (1.0f/65535.0f);
        wrong_index += uint32_t(value * 65535.0f + 0.5f) != sample;
        changed += table[sample] != srgb_encode_f(value);
    }
    CHECK(wrong_index == 0);
    CHECK(changed == 0);
}

TEST_CASE("sRGB clamps out-of-range input") {
    CHECK(std::abs(double(srgb_encode_f(-0.5f))) < 1e-12);
    CHECK(std::abs(double(srgb_encode_f(2.0f)) - 1.0) < 1e-12);
    CHECK(std::abs(double(srgb_decode_f(-0.5f))) < 1e-12);
    CHECK(std::abs(double(srgb_decode_f(1.5f)) - 1.0) < 1e-12);
}

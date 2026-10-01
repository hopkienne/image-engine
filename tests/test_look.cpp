#include "buffer.h"
#include "color.h"
#include "engine_limits.h"
#include "look.h"
#include "test_helpers.h"
#include <cmath>
#include <vector>

using namespace pe;
using namespace pe_test;

namespace {

EngineLimits test_limits() {
    EngineLimits lim;
    return lim;
}

void fill_ramp(RgbFloatBuffer &buf, uint32_t w, uint32_t h) {
    buf.width = w;
    buf.height = h;
    buf.domain = Domain::LookEncoded;
    buf.data.resize(size_t(w) * h * 3);
    for (uint32_t y = 0; y < h; y++)
        for (uint32_t x = 0; x < w; x++) {
            size_t i = (size_t(y) * w + x) * 3;
            buf.data[i + 0] = float(x) / float(w - 1);
            buf.data[i + 1] = float(y) / float(h - 1);
            buf.data[i + 2] = 0.25f;
        }
}

} // namespace

TEST_CASE("identity look package loads and leaves pixels unchanged (<=1e-6)") {
    auto dir = temp_dir("look_identity");
    std::string manifest_sha = make_look_package(dir, "identity-test-look",
                                                 identity_lut_text(), 17);
    auto look_validator = load_look_validator();
    LookPackage look;
    std::string err;
    REQUIRE_MESSAGE(load_look_package(dir.u8string(), test_limits(), look_validator, "baseline-v0", "cameraRaw", manifest_sha, look, err), err);
    CHECK(look.id == "identity-test-look");
    CHECK(look.dimension == 17);
    CHECK(look.table.size() == size_t(17) * 17 * 17 * 3);

    RgbFloatBuffer buf;
    fill_ramp(buf, 16, 16);
    std::vector<float> before = buf.data;
    cube3d_apply(look, buf, 1.0);
    double max_err = 0;
    for (size_t i = 0; i < buf.data.size(); i++)
        max_err = std::max(max_err, double(std::abs(buf.data[i] - before[i])));
    CHECK(max_err <= 1e-6);
}

TEST_CASE("amount=0 bypasses the LUT entirely") {
    auto dir = temp_dir("look_amount0");
    std::string manifest_sha =
        make_look_package(dir, "permuted-look", permuted_lut_text(), 17);
    auto look_validator = load_look_validator();
    LookPackage look;
    std::string err;
    REQUIRE_MESSAGE(load_look_package(dir.u8string(), test_limits(), look_validator, "baseline-v0", "cameraRaw", manifest_sha, look, err), err);
    RgbFloatBuffer buf;
    fill_ramp(buf, 8, 8);
    std::vector<float> before = buf.data;
    cube3d_apply(look, buf, 0.0);
    CHECK(buf.data == before); // bitwise unchanged
}

TEST_CASE("permuted LUT catches axis/channel mix-ups") {
    auto dir = temp_dir("look_permuted");
    std::string manifest_sha =
        make_look_package(dir, "permuted-look", permuted_lut_text(), 17);
    auto look_validator = load_look_validator();
    LookPackage look;
    std::string err;
    REQUIRE_MESSAGE(load_look_package(dir.u8string(), test_limits(), look_validator, "baseline-v0", "cameraRaw", manifest_sha, look, err), err);
    RgbFloatBuffer buf;
    buf.width = buf.height = 1;
    buf.domain = Domain::LookEncoded;
    buf.data = {0.5f, 0.0f, 1.0f}; // in: r=0.5 g=0 b=1
    cube3d_apply(look, buf, 1.0);
    // out(r,g,b) = (g,b,r) => (0, 1, 0.5). Grid points are exact.
    CHECK(std::abs(buf.data[0] - 0.0f) < 1e-6);
    CHECK(std::abs(buf.data[1] - 1.0f) < 1e-6);
    CHECK(std::abs(buf.data[2] - 0.5f) < 1e-6);
}

TEST_CASE("trilinear interpolation of a red ramp is linear between grid points") {
    auto dir = temp_dir("look_ramp");
    std::string manifest_sha =
        make_look_package(dir, "ramp-look", red_ramp_lut_text(), 17);
    auto look_validator = load_look_validator();
    LookPackage look;
    std::string err;
    REQUIRE_MESSAGE(load_look_package(dir.u8string(), test_limits(), look_validator, "baseline-v0", "cameraRaw", manifest_sha, look, err), err);
    RgbFloatBuffer buf;
    buf.width = buf.height = 1;
    buf.domain = Domain::LookEncoded;
    const float in = 0.5f + 0.0625f / 2.0f; // between grid 8 and 9
    buf.data = {in, 0.0f, 0.0f};
    cube3d_apply(look, buf, 1.0);
    CHECK(std::abs(buf.data[0] - in) < 1e-6); // identity along r
    CHECK(std::abs(buf.data[1]) < 1e-7);
    CHECK(std::abs(buf.data[2]) < 1e-7);

    SUBCASE("boundary clamp: input above 1 uses edge samples") {
        RgbFloatBuffer b2;
        b2.width = b2.height = 1;
        b2.domain = Domain::LookEncoded;
        b2.data = {1.5f, 0.0f, 0.0f};
        cube3d_apply(look, b2, 1.0);
        CHECK(std::abs(b2.data[0] - 1.0f) < 1e-6);
    }
}

TEST_CASE("amount blends linearly in the encoded domain") {
    auto dir = temp_dir("look_blend");
    std::string manifest_sha =
        make_look_package(dir, "ramp-look", red_ramp_lut_text(), 17);
    auto look_validator = load_look_validator();
    LookPackage look;
    std::string err;
    REQUIRE_MESSAGE(load_look_package(dir.u8string(), test_limits(), look_validator, "baseline-v0", "cameraRaw", manifest_sha, look, err), err);
    const float r = 0.4f, g = 0.7f, b = 0.2f;
    // amount 0.25: y = 0.75*x + 0.25*LUT(x); LUT(x) = (r, 0, 0)
    RgbFloatBuffer buf;
    buf.width = buf.height = 1;
    buf.domain = Domain::LookEncoded;
    buf.data = {r, g, b};
    cube3d_apply(look, buf, 0.25);
    CHECK(std::abs(buf.data[0] - (0.75 * r + 0.25 * r)) < 1e-6);
    CHECK(std::abs(buf.data[1] - (0.75 * g + 0.25 * 0.0)) < 1e-6);
    CHECK(std::abs(buf.data[2] - (0.75 * b + 0.25 * 0.0)) < 1e-6);
}

TEST_CASE("invalid LUT packages are rejected") {
    auto look_validator = load_look_validator();

    SUBCASE("row count mismatch") {
        auto dir = temp_dir("look_bad_rows");
        std::string lut = cube_header(17);
        for (int i = 0; i < 17 * 17 * 17 - 1; i++) lut += "0 0 0\n";
        std::string sha = make_look_package(dir, "bad-look", lut, 17);
        LookPackage look;
        std::string err;
        CHECK_FALSE(load_look_package(dir.u8string(), test_limits(), look_validator,
                                      "baseline-v0", "cameraRaw", sha, look, err));
        CHECK(err.find("row count") != std::string::npos);
    }
    SUBCASE("NaN row") {
        auto dir = temp_dir("look_bad_nan");
        std::string lut = "LUT_3D_SIZE 17\n";
        for (int i = 0; i < 17 * 17 * 17; i++) lut += (i == 100) ? "nan 0 0\n" : "0 0 0\n";
        std::string sha = make_look_package(dir, "bad-look", lut, 17);
        LookPackage look;
        std::string err;
        CHECK_FALSE(load_look_package(dir.u8string(), test_limits(), look_validator,
                                      "baseline-v0", "cameraRaw", sha, look, err));
        CHECK(err.find("non-finite") != std::string::npos);
    }
    SUBCASE("out-of-range row") {
        auto dir = temp_dir("look_bad_range");
        std::string lut = "LUT_3D_SIZE 17\n";
        for (int i = 0; i < 17 * 17 * 17; i++) lut += (i == 5) ? "1.5 0 0\n" : "0 0 0\n";
        std::string sha = make_look_package(dir, "bad-look", lut, 17);
        LookPackage look;
        std::string err;
        CHECK_FALSE(load_look_package(dir.u8string(), test_limits(), look_validator,
                                      "baseline-v0", "cameraRaw", sha, look, err));
        CHECK(err.find("non-finite or out-of-range") != std::string::npos);
    }
    SUBCASE("missing size") {
        auto dir = temp_dir("look_bad_size");
        std::string lut = "";
        for (int i = 0; i < 17; i++) lut += "0 0 0\n";
        std::string sha = make_look_package(dir, "bad-look", lut, 17);
        LookPackage look;
        std::string err;
        CHECK_FALSE(load_look_package(dir.u8string(), test_limits(), look_validator,
                                      "baseline-v0", "cameraRaw", sha, look, err));
    }
    SUBCASE("manifest hash pin mismatch") {
        auto dir = temp_dir("look_pin");
        std::string sha = make_look_package(dir, "pinned-look", identity_lut_text(), 17);
        LookPackage look;
        std::string err;
        CHECK_FALSE(load_look_package(dir.u8string(), test_limits(), look_validator,
                                      "baseline-v0", "cameraRaw",
                                      std::string(64, '0'), look, err));
        CHECK(err.find("manifest hash mismatch") != std::string::npos);
        CHECK(load_look_package(dir.u8string(), test_limits(), look_validator,
                                "baseline-v0", "cameraRaw", sha, look, err));
    }
    SUBCASE("asset hash mismatch") {
        auto dir = temp_dir("look_asset");
        std::string sha = make_look_package(dir, "asset-look", identity_lut_text(), 17);
        write_text(dir / "lut.cube", "LUT_3D_SIZE 17\n" + std::string(17 * 17 * 17, 'x'));
        LookPackage look;
        std::string err;
        CHECK_FALSE(load_look_package(dir.u8string(), test_limits(), look_validator,
                                      "baseline-v0", "cameraRaw", sha, look, err));
        CHECK(err.find("asset hash mismatch") != std::string::npos);
    }
    SUBCASE("unsupported pipeline") {
        auto dir = temp_dir("look_pipeline");
        std::string sha = make_look_package(dir, "pipe-look", identity_lut_text(), 17);
        LookPackage look;
        std::string err;
        CHECK_FALSE(load_look_package(dir.u8string(), test_limits(), look_validator,
                                      "some-other-pipeline", "cameraRaw", sha, look,
                                      err));
        CHECK(err.find("not compatible with pipeline") != std::string::npos);
    }
    SUBCASE("unsupported source kind") {
        auto dir = temp_dir("look_kind");
        std::string sha = make_look_package(dir, "kind-look", identity_lut_text(), 17);
        LookPackage look;
        std::string err;
        CHECK_FALSE(load_look_package(dir.u8string(), test_limits(), look_validator,
                                      "baseline-v0", "renderedImage", sha, look, err));
        CHECK(err.find("source kind") != std::string::npos);
    }
    SUBCASE("wrong LUT dimension vs manifest") {
        auto dir = temp_dir("look_dim");
        std::string sha = make_look_package(dir, "dim-look", identity_lut_text(33), 17);
        LookPackage look;
        std::string err;
        CHECK_FALSE(load_look_package(dir.u8string(), test_limits(), look_validator,
                                      "baseline-v0", "cameraRaw", sha, look, err));
        CHECK(err.find("does not match manifest") != std::string::npos);
    }
    SUBCASE("bad domain values in cube") {
        auto dir = temp_dir("look_domain");
        std::string lut = identity_lut_text();
        lut.replace(lut.find("DOMAIN_MAX"), 18, "DOMAIN_MAX 0 1 1       ");
        std::string sha = make_look_package(dir, "dom-look", lut, 17);
        LookPackage look;
        std::string err;
        CHECK_FALSE(load_look_package(dir.u8string(), test_limits(), look_validator,
                                      "baseline-v0", "cameraRaw", sha, look, err));
        CHECK(err.find("DOMAIN_MIN/MAX") != std::string::npos);
    }
    SUBCASE("empty look dir") {
        auto dir = temp_dir("look_missing");
        LookPackage look;
        std::string err;
        CHECK_FALSE(load_look_package(dir.u8string(), test_limits(), look_validator,
                                      "baseline-v0", "cameraRaw", "", look, err));
    }
}

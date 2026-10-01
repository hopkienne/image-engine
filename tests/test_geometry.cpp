#include "geometry.h"
#include "test_helpers.h"
#include <cmath>

using namespace pe;

namespace {

RgbFloatBuffer make_labeled(uint32_t w, uint32_t h) {
    RgbFloatBuffer buf;
    buf.width = w;
    buf.height = h;
    buf.domain = Domain::LinearBounded;
    buf.data.resize(size_t(w) * h * 3);
    for (uint32_t y = 0; y < h; y++)
        for (uint32_t x = 0; x < w; x++) {
            float v = float(y * w + x);
            size_t i = (size_t(y) * w + x) * 3;
            buf.data[i] = buf.data[i + 1] = buf.data[i + 2] = v;
        }
    return buf;
}

float label_at(const RgbFloatBuffer &b, uint32_t x, uint32_t y) {
    return b.data[(size_t(y) * b.width + x) * 3];
}

} // namespace

TEST_CASE("orientation normalization matches the dcraw flip bitmask") {
    // 3x2 grid labeled 0..5:
    //   0 1 2
    //   3 4 5
    SUBCASE("flip=3 (180)") {
        RgbFloatBuffer b = make_labeled(3, 2);
        normalize_orientation(b, 3);
        CHECK(b.width == 3);
        CHECK(b.height == 2);
        CHECK(label_at(b, 0, 0) == 5);
        CHECK(label_at(b, 2, 0) == 3);
        CHECK(label_at(b, 0, 1) == 2);
        CHECK(label_at(b, 2, 1) == 0);
    }
    SUBCASE("flip=6 (90 degrees clockwise)") {
        RgbFloatBuffer b = make_labeled(3, 2);
        normalize_orientation(b, 6);
        CHECK(b.width == 2);
        CHECK(b.height == 3);
        // transpose -> 0 3 / 1 4 / 2 5 ; then horizontal mirror:
        //   3 0
        //   4 1
        //   5 2
        CHECK(label_at(b, 0, 0) == 3);
        CHECK(label_at(b, 1, 0) == 0);
        CHECK(label_at(b, 0, 1) == 4);
        CHECK(label_at(b, 1, 1) == 1);
        CHECK(label_at(b, 0, 2) == 5);
        CHECK(label_at(b, 1, 2) == 2);
    }
    SUBCASE("flip=5 (90 degrees counterclockwise)") {
        RgbFloatBuffer b = make_labeled(3, 2);
        normalize_orientation(b, 5);
        CHECK(b.width == 2);
        CHECK(b.height == 3);
        // transpose -> 0 3 / 1 4 / 2 5 ; then vertical mirror:
        //   2 5
        //   1 4
        //   0 3
        CHECK(label_at(b, 0, 0) == 2);
        CHECK(label_at(b, 1, 0) == 5);
        CHECK(label_at(b, 0, 1) == 1);
        CHECK(label_at(b, 1, 1) == 4);
        CHECK(label_at(b, 0, 2) == 0);
        CHECK(label_at(b, 1, 2) == 3);
    }
    SUBCASE("flip=0 is a no-op") {
        RgbFloatBuffer b = make_labeled(3, 2);
        std::vector<float> before = b.data;
        normalize_orientation(b, 0);
        CHECK(b.data == before);
    }
}

TEST_CASE("crop maps normalized coords deterministically") {
    RgbFloatBuffer b = make_labeled(4, 4);
    REQUIRE(apply_crop(b, 0.25, 0.0, 0.5, 0.5));
    CHECK(b.width == 2);
        CHECK(b.height == 2);
    CHECK(label_at(b, 0, 0) == 1);
    CHECK(label_at(b, 1, 0) == 2);
    CHECK(label_at(b, 0, 1) == 5);
    CHECK(label_at(b, 1, 1) == 6);
    SUBCASE("out-of-bounds crop is clamped to the image") {
        RgbFloatBuffer c = make_labeled(4, 4);
        CHECK(apply_crop(c, 0.75, 0.75, 0.5, 0.5)); // extends past the edge
        CHECK(c.width == 1);
        CHECK(c.height == 1);
        CHECK(label_at(c, 0, 0) == 15);
    }
    SUBCASE("tiny crop clamps to one pixel") {
        RgbFloatBuffer c = make_labeled(2, 2);
        CHECK(apply_crop(c, 0.6, 0.6, 0.01, 0.01));
        CHECK(c.width == 1);
        CHECK(c.height == 1);
    }
}

TEST_CASE("90-degree rotations are lossless and correct") {
    // 2x3:
    //   1 2 3
    //   4 5 6
    SUBCASE("90 CW") {
        RgbFloatBuffer b = make_labeled(3, 2);
        b.data[0] = b.data[1] = b.data[2] = 1;
        b.data[3] = b.data[4] = b.data[5] = 2;
        b.data[6] = b.data[7] = b.data[8] = 3;
        b.data[9] = b.data[10] = b.data[11] = 4;
        b.data[12] = b.data[13] = b.data[14] = 5;
        b.data[15] = b.data[16] = b.data[17] = 6;
        rotate_quarter_turns(b, 1);
        CHECK(b.width == 2);
        CHECK(b.height == 3);
        //   4 1
        //   5 2
        //   6 3
        CHECK(label_at(b, 0, 0) == 4);
        CHECK(label_at(b, 1, 0) == 1);
        CHECK(label_at(b, 0, 1) == 5);
        CHECK(label_at(b, 1, 1) == 2);
        CHECK(label_at(b, 0, 2) == 6);
        CHECK(label_at(b, 1, 2) == 3);
    }
    SUBCASE("270 CW == 90 CCW") {
        RgbFloatBuffer b = make_labeled(3, 2);
        for (int v = 0; v < 6; v++)
            for (int c = 0; c < 3; c++) b.data[size_t(v) * 3 + c] = float(v + 1);
        rotate_quarter_turns(b, 3);
        CHECK(b.width == 2);
        CHECK(b.height == 3);
        //   3 6
        //   2 5
        //   1 4
        CHECK(label_at(b, 0, 0) == 3);
        CHECK(label_at(b, 1, 0) == 6);
        CHECK(label_at(b, 0, 1) == 2);
        CHECK(label_at(b, 1, 1) == 5);
        CHECK(label_at(b, 0, 2) == 1);
        CHECK(label_at(b, 1, 2) == 4);
    }
    SUBCASE("4 x 90 CW returns to identity") {
        RgbFloatBuffer b = make_labeled(3, 2);
        std::vector<float> before = b.data;
        for (int i = 0; i < 4; i++) rotate_quarter_turns(b, 1);
        CHECK(b.width == 3);
        CHECK(b.height == 2);
        CHECK(b.data == before);
    }
}

TEST_CASE("box downscale averages the covered area") {
    RgbFloatBuffer b = make_labeled(4, 2);
    REQUIRE(downscale_to_long_edge(b, 2));
    CHECK(b.width == 2);
        CHECK(b.height == 1);
    // column 0 covers source columns 0-1, both rows: (0+1+4+5)/4 = 2.5
    CHECK(std::abs(label_at(b, 0, 0) - 2.5f) < 1e-4);
    // column 1 covers columns 2-3: (2+3+6+7)/4 = 4.5
    CHECK(std::abs(label_at(b, 1, 0) - 4.5f) < 1e-4);
    SUBCASE("upscale is not performed") {
        RgbFloatBuffer c = make_labeled(3, 2);
        REQUIRE(downscale_to_long_edge(c, 64));
        CHECK(c.width == 3);
        CHECK(c.height == 2);
    }
}

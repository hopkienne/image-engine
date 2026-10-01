#include "cancel_flag.h"
#include "engine_impl.h"
#include "file_util.h"
#include "geometry.h"
#include "jpeg_encoder.h"
#include "look.h"
#include "raw_adapter.h"
#include "render.h"
#include "test_helpers.h"
#include <cstring>
#include <thread>
#include <limits>

using namespace pe;

namespace {
struct StopAt { const char *stage; int occurrence = 1; int seen = 0; };
void stop_at(CancelFlag &flag, const char *stage, void *data) noexcept {
    auto &stop = *static_cast<StopAt *>(data);
    if (std::strcmp(stage, stop.stage) == 0 && ++stop.seen == stop.occurrence) flag.request();
}
RgbFloatBuffer frame(uint32_t w, uint32_t h) {
    RgbFloatBuffer b;
    b.width = w; b.height = h; b.data.resize(size_t(w) * h * 3);
    for (size_t i = 0; i < b.data.size(); ++i) b.data[i] = float(i % 251) / 250;
    return b;
}
}

TEST_CASE("as-shot WB resolves optional green without accepting corrupt coefficients") {
    SourceProbe probe;
    probe.colors = 3;
    probe.cam_mul[0] = 256; probe.cam_mul[1] = 128;
    probe.cam_mul[2] = 192; probe.cam_mul[3] = 0;
    double wb[4] = {9,9,9,9};
    REQUIRE(resolve_as_shot_wb(probe,wb));
    CHECK(wb[0] == 2); CHECK(wb[1] == 1); CHECK(wb[2] == 1.5); CHECK(wb[3] == 1);
    SUBCASE("explicit second green is preserved") {
        probe.cam_mul[3] = 64;
        REQUIRE(resolve_as_shot_wb(probe,wb)); CHECK(wb[3] == 0.5);
    }
    SUBCASE("four-color or unknown metadata cannot omit a coefficient") {
        probe.colors = 4; CHECK_FALSE(resolve_as_shot_wb(probe,wb));
        probe.colors = 0; CHECK_FALSE(resolve_as_shot_wb(probe,wb));
    }
    SUBCASE("invalid required channels do not change the output") {
        for (int channel = 0; channel < 4; ++channel) {
            for (double invalid : {0.0,-1.0,std::numeric_limits<double>::infinity(),
                                   std::numeric_limits<double>::quiet_NaN()}) {
                if (channel == 3 && invalid == 0.0) continue;
                auto bad = probe; bad.cam_mul[channel] = invalid;
                CHECK_FALSE(resolve_as_shot_wb(bad,wb));
                CHECK(wb[0] == 2); CHECK(wb[1] == 1); CHECK(wb[2] == 1.5); CHECK(wb[3] == 1);
            }
        }
    }
    SUBCASE("overflow after normalization is rejected") {
        probe.cam_mul[0] = std::numeric_limits<double>::max();
        probe.cam_mul[1] = std::numeric_limits<double>::min();
        CHECK_FALSE(resolve_as_shot_wb(probe,wb));
    }
}

TEST_CASE("all orientation bitmasks retain exact channel values") {
    const int expected[8][6] = {
        {0,1,2,3,4,5}, {2,1,0,5,4,3}, {3,4,5,0,1,2}, {5,4,3,2,1,0},
        {0,3,1,4,2,5}, {2,5,1,4,0,3}, {3,0,4,1,5,2}, {5,2,4,1,3,0}};
    for (uint32_t flip = 0; flip < 8; ++flip) {
        auto b = frame(3,2);
        for (int i = 0; i < 6; ++i) for (int c = 0; c < 3; ++c) b.data[i*3+c] = float(i*10+c);
        normalize_orientation(b,flip);
        CHECK(b.width == (flip & 4 ? 2 : 3));
        CHECK(b.height == (flip & 4 ? 3 : 2));
        for (int i = 0; i < 6; ++i) for (int c = 0; c < 3; ++c)
            CHECK(b.data[i*3+c] == expected[flip][i]*10+c);
    }
}

TEST_CASE("full-frame crop and mirrors avoid replacement allocations") {
    auto b = frame(103,71);
    const auto original = b.data;
    const auto *allocation = b.data.data();
    REQUIRE(apply_crop(b,0,0,1,1));
    CHECK(b.data.data() == allocation);
    CHECK(b.data == original);
    normalize_orientation(b,3);
    CHECK(b.data.data() == allocation);
    normalize_orientation(b,3);
    CHECK(b.data == original);
}

TEST_CASE("cancellation interrupts pixel loops after work has started") {
    CancelFlag cancel;
    SUBCASE("resize source footprint") {
        auto b = frame(128,128);
        StopAt stop{"resize.source.row",2}; cancel.set_observer(stop_at,&stop);
        CHECK_THROWS_AS(downscale_to_long_edge(b,1,&cancel),Cancelled);
        CHECK(stop.seen == 2);
        CHECK(b.width == 128);
    }
    SUBCASE("crop rows") {
        auto b = frame(32,32);
        StopAt stop{"geometry.crop.row",2}; cancel.set_observer(stop_at,&stop);
        CHECK_THROWS_AS(apply_crop(b,0,0,0.5,0.5,&cancel),Cancelled);
        CHECK(stop.seen == 2);
    }
    SUBCASE("quantization chunks") {
        auto b = frame(64,64);
        StopAt stop{"quantize.chunk",2}; cancel.set_observer(stop_at,&stop);
        CHECK_THROWS_AS(quantize_to_rgb8(b,&cancel),Cancelled);
        CHECK(stop.seen == 2);
    }
    SUBCASE("LUT chunks") {
        auto b = frame(128,128);
        LookPackage lut; lut.dimension=17; lut.table.resize(17*17*17*3,0.5f);
        StopAt stop{"look.chunk",2}; cancel.set_observer(stop_at,&stop);
        CHECK_THROWS_AS(cube3d_apply(lut,b,1,&cancel),Cancelled);
        CHECK(stop.seen == 2);
    }
}

TEST_CASE("JPEG cancellation and codec errors release state and permit subsequent encoding") {
    Rgb8Buffer b; b.width=1024; b.height=512; b.data.resize(size_t(b.width)*b.height*3);
    uint32_t noise=1;
    for (auto &v:b.data) { noise=noise*1664525u+1013904223u; v=uint8_t(noise>>24); }
    JpegEncodeOptions opts;
    std::vector<uint8_t> out;
    std::string error;
    for (int i=0;i<12;++i) {
        CancelFlag cancel; StopAt stop{"jpeg.row",256}; cancel.set_observer(stop_at,&stop);
        CHECK_FALSE(encode_jpeg(b,opts,out,error,&cancel));
        CHECK(out.empty()); CHECK(stop.seen==256);
    }
    SUBCASE("libjpeg longjmp failure") {
        Rgb8Buffer huge; huge.width=70000; huge.height=1; huge.data.resize(210000);
        CHECK_FALSE(encode_jpeg(huge,opts,out,error));
        CHECK(out.empty()); CHECK(error.find("libjpeg error")!=std::string::npos);
    }
    SUBCASE("oversized ICC is a clean error") {
        std::vector<uint8_t> icc(70000); opts.icc=&icc;
        CHECK_FALSE(encode_jpeg(b,opts,out,error));
        CHECK(out.empty()); CHECK(error.find("ICC profile too large")!=std::string::npos);
        opts.icc=nullptr;
    }
    REQUIRE(encode_jpeg(b,opts,out,error));
    CHECK(out.size()>4096); CHECK(out[0]==0xff); CHECK(out[1]==0xd8);
}

TEST_CASE("exclusive staging creation has one winner and preserves content") {
    const auto path=pe_test::temp_dir("exclusive")/std::filesystem::u8path(u8"\u1ea3nh-staging.bin");
    std::filesystem::remove(path);
    FILE *first=nullptr,*second=nullptr;
    std::thread a([&]{first=utf8_fopen_exclusive(path.u8string());});
    std::thread b([&]{second=utf8_fopen_exclusive(path.u8string());});
    a.join();b.join();
    CHECK((first!=nullptr)!=(second!=nullptr));
    FILE *winner=first?first:second;
    REQUIRE(winner!=nullptr);
    CHECK(std::fwrite("sentinel",1,8,winner)==8);
    CHECK(std::fclose(winner)==0);
    CHECK(utf8_fopen_exclusive(path.u8string())==nullptr);
    std::ifstream content(path, std::ios::binary);
    std::string text((std::istreambuf_iterator<char>(content)), std::istreambuf_iterator<char>());
    CHECK(text=="sentinel");
    content.close();
    std::filesystem::remove(path);
}

TEST_CASE("pre-cancelled render neither opens source nor returns a stale output") {
    CancelFlag cancel;cancel.request();
    RenderRequest request;RenderOutput output;StageTimings timings;EngineLimits limits;
    output.encoded=frame(2,2);output.out_width=2;
    std::string error;int status=0;
    CHECK_FALSE(render_to_pixels("missing.raw",request,limits,&cancel,output,timings,status,error));
    CHECK(status==kPE_CANCELLED); CHECK(output.encoded.empty()); CHECK(output.out_width==0);
}

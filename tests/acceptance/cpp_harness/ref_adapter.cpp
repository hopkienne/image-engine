// AUD-016: standalone LibRaw reference adapter.
//
// Compiled WITHOUT photoengine_core: links LibRaw/zlib/jpeg directly. It
// re-implements the pinned P0 decoder configuration from the audited spec
// (README + audit policy), dumps the developed frame as packed RGB FP32 LE,
// and never touches engine code. Conformance scope: proves the engine's base
// development matches an independent integration of the SAME pinned LibRaw
// build+configuration. It shares LibRaw, so it does NOT certify camera color
// science (test plan section C caveat).
//
//   ref_adapter <source.raw> <out.f32> <out.json> <R> <G> <B> <G2>
#include <libraw/libraw.h>
#include <nlohmann/json.hpp>
#include <cstdio>
#include <string>
#include <vector>

int main(int argc, char **argv) {
    if (argc < 7) return 2;
    const char *source = argv[1];
    const char *out_f32 = argv[2];
    const char *out_json = argv[3];
    const double mul[4] = {atof(argv[4]), atof(argv[5]), atof(argv[6]), atof(argv[7])};

    LibRaw raw;
    int ret = raw.open_file(source);
    if (ret != LIBRAW_SUCCESS) {
        std::fprintf(stderr, "open failed: %s\n", LibRaw::strerror(ret));
        return 1;
    }
    ret = raw.unpack();
    if (ret != LIBRAW_SUCCESS) {
        std::fprintf(stderr, "unpack failed: %s\n", LibRaw::strerror(ret));
        return 1;
    }
    // Pinned P0 configuration copied from the audited spec (audit policy +
    // engine raw_developer_config_echo_json). Independent implementation.
    raw.imgdata.params.use_camera_wb = 0;
    raw.imgdata.params.use_auto_wb = 0;
    raw.imgdata.params.user_mul[0] = float(mul[0]);
    raw.imgdata.params.user_mul[1] = float(mul[1]);
    raw.imgdata.params.user_mul[2] = float(mul[2]);
    raw.imgdata.params.user_mul[3] = float(mul[3]);
    raw.imgdata.params.no_auto_bright = 1;
    raw.imgdata.params.output_bps = 16;
    raw.imgdata.params.output_color = 1;
    raw.imgdata.params.gamm[0] = 1.0;
    raw.imgdata.params.gamm[1] = 1.0;
    raw.imgdata.params.user_flip = 0;
    raw.imgdata.params.use_fuji_rotate = 0;
    raw.imgdata.params.user_qual = 3; // AHD
    raw.imgdata.params.med_passes = 0;
    raw.imgdata.params.highlight = 0;
    raw.imgdata.params.half_size = 0;
    raw.imgdata.params.four_color_rgb = 0;
    raw.imgdata.params.adjust_maximum_thr = 0.0f;
    raw.imgdata.params.exp_correc = 0;

    ret = raw.dcraw_process();
    if (ret != LIBRAW_SUCCESS) {
        std::fprintf(stderr, "dcraw_process failed: %s\n", LibRaw::strerror(ret));
        return 1;
    }
    const uint32_t w = raw.imgdata.sizes.iwidth;
    const uint32_t h = raw.imgdata.sizes.iheight;
    std::vector<float> pixels(size_t(w) * h * 3);
    const ushort(*image)[4] = raw.imgdata.image;
    for (size_t i = 0; i < size_t(w) * h; i++) {
        pixels[i * 3 + 0] = float(image[i][0]) * (1.0f / 65535.0f);
        pixels[i * 3 + 1] = float(image[i][1]) * (1.0f / 65535.0f);
        pixels[i * 3 + 2] = float(image[i][2]) * (1.0f / 65535.0f);
    }
    FILE *f = std::fopen(out_f32, "wb");
    if (!f) return 1;
    std::fwrite(pixels.data(), sizeof(float), pixels.size(), f);
    std::fclose(f);
    nlohmann::json d;
    d["width"] = w;
    d["height"] = h;
    d["channels"] = 3;
    d["sampleType"] = "float32";
    d["byteOrder"] = "little";
    d["transferFunction"] = "linear";
    d["note"] = "standalone LibRaw adapter output; u16/65535 normalized";
    d["librawVersion"] = LibRaw::version();
    f = std::fopen(out_json, "wb");
    if (f) {
        std::string t = d.dump(2);
        std::fwrite(t.data(), 1, t.size(), f);
        std::fclose(f);
    }
    raw.recycle();
    std::printf("{\"width\":%u,\"height\":%u}\n", w, h);
    return 0;
}

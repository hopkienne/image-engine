// JPEG encoder (libjpeg-turbo) for the export stage: 8-bit sRGB JFIF with an
// embedded ICC profile and a minimal EXIF APP1 (ColorSpace sRGB, Orientation
// normal, Software). No GPS or camera-identifying metadata is written.
#pragma once
#include "buffer.h"
#include <cstdint>
#include <string>
#include <vector>

namespace pe {

class CancelFlag;

struct JpegEncodeOptions {
    int quality = 92;                  // 1..100 (recipe schema enforces range)
    bool subsampling_444 = true;       // true: 4:4:4, false: 4:2:0
    const std::vector<uint8_t> *icc = nullptr; // optional APP2 profile
    std::string software_tag;          // EXIF Software value
};

// Encodes `buffer` to `out_bytes`. Deterministic for the same input/options.
bool encode_jpeg(const Rgb8Buffer &buffer, const JpegEncodeOptions &options,
                 std::vector<uint8_t> &out_bytes, std::string &error,
                 CancelFlag *cancel = nullptr);

} // namespace pe

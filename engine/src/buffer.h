// Pixel buffer + BufferDescriptor per docs/03 section 3.3:
// width, height, channels, channelOrder, sampleType, rowStride, alphaMode,
// orientationState, primaries, whitePoint, transferFunction, rangePolicy,
// referenceDomain. G1 uses two interleaved RGB FP32 domains and one u8 form.
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace pe {

enum class Domain {
    LinearBounded, // baseline-linear-bounded-v0
    LookEncoded,   // srgb-display-v1
};

struct BufferDescriptor {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t channels = 3;
    const char *channel_order = "RGB";
    const char *sample_type = "float32"; // or "uint8"
    uint64_t row_stride_bytes = 0;
    const char *alpha_mode = "opaque-1";
    const char *primaries = "sRGB";
    const char *white_point = "D65";
    const char *transfer_function = "linear"; // or "srgb-encoded"
    const char *range_policy = "bounded-[0,1]-full";
    const char *reference_domain = "baseline-linear-bounded-v0";
    const char *orientation_state = "baked-normalized"; // or "decoder-pending"

    static BufferDescriptor make(Domain domain, uint32_t w, uint32_t h,
                                 bool orientation_baked);
};

// Interleaved RGB float32 working buffer.
struct RgbFloatBuffer {
    uint32_t width = 0;
    uint32_t height = 0;
    Domain domain = Domain::LinearBounded;
    std::vector<float> data; // width*height*3, no row padding

    size_t pixel_count() const { return size_t(width) * height; }
    size_t value_count() const { return pixel_count() * 3; }
    bool empty() const { return width == 0 || height == 0; }
    BufferDescriptor descriptor() const;
};

// Interleaved RGB uint8 quantized buffer (pre-JPEG).
struct Rgb8Buffer {
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<uint8_t> data; // width*height*3
    bool empty() const { return width == 0 || height == 0; }
};

// Overflow-safe byte size for a w*h*channels*elem_size allocation request.
bool checked_buffer_bytes(uint64_t w, uint64_t h, uint64_t channels,
                          uint64_t elem_size, uint64_t &out_bytes);

} // namespace pe

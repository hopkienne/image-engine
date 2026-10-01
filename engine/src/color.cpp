#include "color.h"
#include <cmath>

namespace pe {

double srgb_decode_d(double v) {
    if (v <= 0.0) return 0.0;
    if (v >= 1.0) return 1.0;
    if (v <= 0.04045) return v / 12.92;
    return std::pow((v + 0.055) / 1.055, 2.4);
}

double srgb_encode_d(double v) {
    if (v <= 0.0) return 0.0;
    if (v >= 1.0) return 1.0;
    if (v <= 0.0031308) return v * 12.92;
    return 1.055 * std::pow(v, 1.0 / 2.4) - 0.055;
}

float srgb_encode_f(float v) { return float(srgb_encode_d(double(v))); }
float srgb_decode_f(float v) { return float(srgb_decode_d(double(v))); }

const std::array<float, 65536> &srgb_u16_encode_table() {
    static const auto values = [] {
        std::array<float, 65536> result{};
        for (size_t i = 0; i < result.size(); ++i)
            result[i] = srgb_encode_f(float(i) * (1.0f / 65535.0f));
        return result;
    }();
    return values;
}

} // namespace pe

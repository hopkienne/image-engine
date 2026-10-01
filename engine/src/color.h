// Color transfer helpers for the two G1 domains:
//   baseline-linear-bounded-v0 : linear sRGB primaries, D65, FP32, [0,1] bounded
//   srgb-display-v1            : sRGB-encoded (IEC 61966-2-1 transfer), [0,1]
// No fast-math, no approximation tables: exact piecewise curve in FP32/FP64.
#pragma once
#include <array>

namespace pe {

// Exact sRGB EOTF (decode: encoded -> linear). Input clamped to [0,1].
double srgb_decode_d(double v);
double srgb_encode_d(double v);
float srgb_encode_f(float v);
float srgb_decode_f(float v);

// Exact scalar results for the finite P0 u16/65535 input set, not an
// interpolated approximation. Used only before LUT, with exposure EV == 0.
const std::array<float, 65536> &srgb_u16_encode_table();

// Clamp helpers.
inline float clamp01f(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }

// Domain identifier strings (single source of truth, also used in reports).
constexpr const char *kDomainLinearBounded = "baseline-linear-bounded-v0";
constexpr const char *kDomainLook = "srgb-display-v1";

} // namespace pe

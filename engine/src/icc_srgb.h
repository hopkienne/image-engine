// Deterministic built-in sRGB ICC v2 matrix/TRC profile.
// Generated in-engine (no third-party profile shipped): sRGB primaries
// Bradford-adapted to D50, sRGB piecewise TRC as a 1024-entry curv table.
// Byte-for-byte deterministic, so the profile hash is stable across builds.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace pe {

// Builds the profile; returns false only on allocation failure.
bool build_srgb_icc_profile(std::vector<uint8_t> &out);

std::string srgb_icc_sha256();

} // namespace pe

// Engine resource limits (docs/09 section 9.1). Defaults are G1 host values;
// they can be overridden via the engine config JSON within hard bounds.
#pragma once
#include "strict_json.h"
#include <cstddef>
#include <cstdint>

namespace pe {

struct EngineLimits {
    uint64_t max_input_bytes = 1ull << 30;        // 1 GiB source file cap
    uint64_t max_pixels = 100'000'000;            // 100 MP
    uint64_t max_decoded_bytes = 3'200'000'000ull;// decoded stage budget cap
    size_t max_lut_bytes = 64 << 20;              // 64 MiB LUT file cap
    uint32_t max_lut_dimension = 65;
    JsonLimits json_limits() const { return JsonLimits{max_json_bytes, max_json_depth}; }
    size_t max_json_bytes = 2 * 1024 * 1024;
    size_t max_json_depth = 64;

    // Applies config JSON {"limits":{...}}; unknown keys are rejected.
    bool apply_config(const nlohmann::json &config, std::string &error);
};

} // namespace pe

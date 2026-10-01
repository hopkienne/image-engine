// Strict JSON parsing per docs/04_engine_contracts.md section 4.2:
// duplicate keys rejected, depth/size limited, non-finite numbers rejected.
// Built on nlohmann::json's SAX interface so the value model stays identical.
#pragma once
#include <nlohmann/json.hpp>
#include <string>

namespace pe {

struct JsonLimits {
    size_t max_bytes = 2 * 1024 * 1024; // maxJsonBytes
    size_t max_depth = 64;              // maxJsonDepth
};

// Parses `data` (exactly `size` bytes, must be complete UTF-8 JSON).
// On failure returns false and fills `error` (no input bytes echoed).
bool strict_json_parse(const char *data, size_t size, const JsonLimits &limits,
                       nlohmann::json &out, std::string &error);

// Convenience for strings.
inline bool strict_json_parse(const std::string &text, const JsonLimits &limits,
                              nlohmann::json &out, std::string &error) {
    return strict_json_parse(text.data(), text.size(), limits, out, error);
}

} // namespace pe

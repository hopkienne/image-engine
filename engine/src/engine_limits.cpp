#include "engine_limits.h"

namespace pe {

bool EngineLimits::apply_config(const nlohmann::json &config, std::string &error) {
    if (!config.is_object()) {
        error = "engine config must be a JSON object";
        return false;
    }
    for (auto kv = config.begin(); kv != config.end(); ++kv) {
        if (kv.key() == "configVersion") {
            if (!kv.value().is_number_integer() || kv.value().get<int>() != 1) {
                error = "engine config configVersion must be 1";
                return false;
            }
        } else if (kv.key() == "limits") {
            const nlohmann::json &lim = kv.value();
            if (!lim.is_object()) {
                error = "engine config limits must be an object";
                return false;
            }
            for (auto l = lim.begin(); l != lim.end(); ++l) {
                if (!l.value().is_number_unsigned() || l.value().get<uint64_t>() == 0) {
                    error = "limit '" + l.key() + "' must be a positive integer";
                    return false;
                }
                uint64_t v = l.value().get<uint64_t>();
                if (l.key() == "maxInputBytes") {
                    max_input_bytes = v;
                } else if (l.key() == "maxPixels") {
                    max_pixels = v;
                } else if (l.key() == "maxDecodedBytes") {
                    max_decoded_bytes = v;
                } else if (l.key() == "maxLutBytes") {
                    max_lut_bytes = size_t(v);
                } else if (l.key() == "maxLutDimension") {
                    if (v != 17 && v != 33 && v != 65) {
                        error = "maxLutDimension must be 17, 33 or 65";
                        return false;
                    }
                    max_lut_dimension = uint32_t(v);
                } else if (l.key() == "maxJsonBytes") {
                    max_json_bytes = size_t(v);
                } else if (l.key() == "maxJsonDepth") {
                    if (v < 4 || v > 1024) {
                        error = "maxJsonDepth must be within [4,1024]";
                        return false;
                    }
                    max_json_depth = size_t(v);
                } else {
                    error = "unknown engine limit '" + l.key() + "'";
                    return false;
                }
            }
        } else if (kv.key() == "assetSearchPaths") {
            // Handled by engine_impl (paths are strings); validate shape here.
            if (!kv.value().is_array()) {
                error = "assetSearchPaths must be an array of strings";
                return false;
            }
            for (const auto &p : kv.value()) {
                if (!p.is_string() || p.get<std::string>().empty()) {
                    error = "assetSearchPaths entries must be non-empty strings";
                    return false;
                }
            }
        } else {
            error = "unknown engine config key '" + kv.key() + "'";
            return false;
        }
    }
    return true;
}

} // namespace pe

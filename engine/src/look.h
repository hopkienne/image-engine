// Look package loading and the cube3d operator (docs/03 section 3.5).
// A look package is a directory containing manifest.json (look.schema.json v1)
// and a .cube LUT asset. Everything is validated before use: schema, version,
// domain, hashes, sample count, finiteness, dimension, safe asset path.
#pragma once
#include "buffer.h"
#include "schema_validate.h"
#include <memory>
#include <string>
#include <vector>

namespace pe {

struct EngineLimits;
class CancelFlag;

struct LookPackage {
    std::string id;
    std::string version;
    std::string name;
    std::string domain;              // must be srgb-display-v1
    std::string amount_policy;       // must be encoded-domain-linear-blend-v1
    std::vector<std::string> source_kinds;
    std::vector<std::string> compatible_pipelines;
    std::string asset_path;          // resolved inside the package dir
    std::string asset_sha256;        // verified against manifest
    std::string manifest_sha256;     // sha256 of manifest.json bytes
    uint32_t dimension = 0;          // 17/33/65
    std::vector<float> table;        // dimension^3 * 3 floats, red-fastest
    std::string license_file;
    std::string notes;
};

// Loads and fully validates a look package directory.
//   pipeline_id / source_kind: compatibility must match or loading fails.
//   manifest_sha256_expected: optional pin from a recipe (empty = any).
bool load_look_package(const std::string &dir, const EngineLimits &limits,
                       const MiniSchemaValidator &look_schema_validator,
                       const std::string &pipeline_id,
                       const std::string &source_kind,
                       const std::string &manifest_sha256_expected,
                       LookPackage &out, std::string &error);

// Applies the LUT + amount blend in the encoded look domain, in place.
// amount == 0 bypasses the LUT entirely (no-op by contract).
// amount outside [0,1] is rejected beforehand by recipe validation.
void cube3d_apply(const LookPackage &lut, RgbFloatBuffer &buffer, double amount,
                   CancelFlag *cancel = nullptr);

} // namespace pe

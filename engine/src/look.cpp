#include "look.h"
#include "cancel_flag.h"
#include "color.h"
#include "engine_limits.h"
#include "file_util.h"
#include "sha256.h"
#include "strict_json.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <set>

namespace pe {

namespace {

bool read_file_bytes(const std::string &path, size_t max_bytes,
                     std::vector<uint8_t> &out, std::string &error) {
    FILE *f = utf8_fopen(path, "rb");
    if (!f) {
        error = "cannot open file: " + path;
        return false;
    }
    out.clear();
    uint8_t buf[1 << 16];
    size_t n;
    while ((n = std::fread(buf, 1, sizeof(buf), f)) > 0) {
        out.insert(out.end(), buf, buf + n);
        if (out.size() > max_bytes) {
            std::fclose(f);
            error = "file exceeds size limit: " + path;
            return false;
        }
    }
    bool bad = std::ferror(f) != 0;
    std::fclose(f);
    if (bad) {
        error = "read error: " + path;
        return false;
    }
    return true;
}

bool parse_cube(const std::vector<uint8_t> &bytes, uint32_t expected_dimension,
                LookPackage &out, std::string &error) {
    std::string text(bytes.begin(), bytes.end());
    size_t pos = 0;
    int line_no = 0;
    uint32_t size = 0;
    bool have_min = false, have_max = false;
    float dmin[3] = {0, 0, 0}, dmax[3] = {1, 1, 1};
    std::vector<float> values;

    auto next_line = [&](std::string &line) -> bool {
        if (pos >= text.size()) return false;
        size_t nl = text.find('\n', pos);
        if (nl == std::string::npos) {
            line = text.substr(pos);
            pos = text.size();
        } else {
            line = text.substr(pos, nl - pos);
            pos = nl + 1;
        }
        if (!line.empty() && line.back() == '\r') line.pop_back();
        line_no++;
        return true;
    };

    while (true) {
        std::string line;
        if (!next_line(line)) break;
        const std::string trimmed_src = line;
        // trim
        size_t b = line.find_first_not_of(" \t");
        if (b == std::string::npos) continue;
        size_t e = line.find_last_not_of(" \t");
        line = line.substr(b, e - b + 1);
        if (line[0] == '#') continue;
        if (line.rfind("TITLE", 0) == 0) continue; // TITLE "..." accepted, ignored
        if (line.rfind("LUT_3D_SIZE", 0) == 0) {
            if (size != 0) {
                error = "LUT: duplicate LUT_3D_SIZE at line " + std::to_string(line_no);
                return false;
            }
            if (std::sscanf(line.c_str(), "LUT_3D_SIZE %u", &size) != 1 || size == 0) {
                error = "LUT: bad LUT_3D_SIZE at line " + std::to_string(line_no);
                return false;
            }
            continue;
        }
        if (line.rfind("DOMAIN_MIN", 0) == 0) {
            if (std::sscanf(line.c_str(), "DOMAIN_MIN %f %f %f", &dmin[0], &dmin[1],
                            &dmin[2]) != 3) {
                error = "LUT: bad DOMAIN_MIN at line " + std::to_string(line_no);
                return false;
            }
            have_min = true;
            continue;
        }
        if (line.rfind("DOMAIN_MAX", 0) == 0) {
            if (std::sscanf(line.c_str(), "DOMAIN_MAX %f %f %f", &dmax[0], &dmax[1],
                            &dmax[2]) != 3) {
                error = "LUT: bad DOMAIN_MAX at line " + std::to_string(line_no);
                return false;
            }
            have_max = true;
            continue;
        }
        if (line.rfind("LUT_1D_SIZE", 0) == 0 ||
            line.rfind("LUT_3D_INPUT_RANGE", 0) == 0) {
            error = "LUT: unsupported keyword at line " + std::to_string(line_no);
            return false;
        }
        // Data row: exactly three floats.
        float rv, gv, bv;
        if (std::sscanf(line.c_str(), "%f %f %f", &rv, &gv, &bv) != 3) {
            error = "LUT: invalid data row at line " + std::to_string(line_no) +
                    " (" + trimmed_src.substr(0, 64) + ")";
            return false;
        }
        if (!std::isfinite(rv) || !std::isfinite(gv) || !std::isfinite(bv) ||
            rv < 0.0f || rv > 1.0f || gv < 0.0f || gv > 1.0f || bv < 0.0f ||
            bv > 1.0f) {
            error = "LUT: non-finite or out-of-range value at line " +
                    std::to_string(line_no);
            return false;
        }
        values.push_back(rv);
        values.push_back(gv);
        values.push_back(bv);
    }

    if (size == 0) {
        error = "LUT: missing LUT_3D_SIZE";
        return false;
    }
    if (expected_dimension != 0 && size != expected_dimension) {
        error = "LUT: size " + std::to_string(size) + " does not match manifest " +
                std::to_string(expected_dimension);
        return false;
    }
    if (size != 17 && size != 33 && size != 65) {
        error = "LUT: unsupported dimension " + std::to_string(size);
        return false;
    }
    if (!have_min || !have_max || dmin[0] != 0.0f || dmin[1] != 0.0f ||
        dmin[2] != 0.0f || dmax[0] != 1.0f || dmax[1] != 1.0f || dmax[2] != 1.0f) {
        error = "LUT: DOMAIN_MIN/MAX must be [0,0,0] and [1,1,1] for srgb-display-v1";
        return false;
    }
    if (values.size() != size_t(size) * size * size * 3) {
        error = "LUT: row count " + std::to_string(values.size() / 3) +
                " does not match size^3 " + std::to_string(size_t(size) * size * size);
        return false;
    }
    out.dimension = size;
    out.table = std::move(values);
    return true;
}

} // namespace

bool load_look_package(const std::string &dir, const EngineLimits &limits,
                       const MiniSchemaValidator &look_schema_validator,
                       const std::string &pipeline_id,
                       const std::string &source_kind,
                       const std::string &manifest_sha256_expected,
                       LookPackage &out, std::string &error) {
    if (dir.empty()) {
        error = "look package directory is empty";
        return false;
    }
    std::string manifest_path = dir + "/manifest.json";
    std::vector<uint8_t> manifest_bytes;
    if (!read_file_bytes(manifest_path, limits.max_json_bytes, manifest_bytes, error)) {
        error = "look package manifest: " + error;
        return false;
    }
    // Pin check happens before parsing: an unexpected package is rejected even
    // if its content would otherwise be valid.
    std::string actual_manifest_hash = sha256_hex(manifest_bytes.data(), manifest_bytes.size());
    if (!manifest_sha256_expected.empty() &&
        manifest_sha256_expected != actual_manifest_hash) {
        error = "look package manifest hash mismatch (recipe pins " +
                manifest_sha256_expected + ", found " + actual_manifest_hash + ")";
        return false;
    }

    nlohmann::json manifest;
    std::string jerr;
    if (!strict_json_parse(reinterpret_cast<const char *>(manifest_bytes.data()),
                           manifest_bytes.size(), limits.json_limits(), manifest, jerr)) {
        error = "look manifest JSON: " + jerr;
        return false;
    }
    if (!look_schema_validator.validate(manifest, jerr)) {
        error = "look manifest schema: " + jerr;
        return false;
    }

    out.id = manifest["id"].get<std::string>();
    out.version = manifest["version"].get<std::string>();
    out.name = manifest["name"].get<std::string>();
    out.domain = manifest["domain"].get<std::string>();
    out.amount_policy = manifest["amountPolicy"].get<std::string>();
    out.license_file = manifest["licenseFile"].get<std::string>();
    out.notes = manifest["notes"].get<std::string>();
    out.manifest_sha256 = actual_manifest_hash;
    for (const auto &k : manifest["sourceKinds"]) out.source_kinds.push_back(k.get<std::string>());
    for (const auto &p : manifest["compatiblePipelines"])
        out.compatible_pipelines.push_back(p.get<std::string>());

    if (out.domain != "srgb-display-v1") {
        error = "look domain '" + out.domain + "' is not srgb-display-v1";
        return false;
    }
    if (out.amount_policy != "encoded-domain-linear-blend-v1") {
        error = "look amountPolicy '" + out.amount_policy + "' is not supported";
        return false;
    }
    // Status is recorded but never used to relax validation: prototype packages
    // go through the exact same checks as approved ones.
    const std::string status = manifest["status"].get<std::string>();
    (void)status;
    if (std::find(out.compatible_pipelines.begin(), out.compatible_pipelines.end(),
                  pipeline_id) == out.compatible_pipelines.end()) {
        error = "look is not compatible with pipeline '" + pipeline_id + "'";
        return false;
    }
    if (std::find(out.source_kinds.begin(), out.source_kinds.end(), source_kind) ==
        out.source_kinds.end()) {
        error = "look does not support source kind '" + source_kind + "'";
        return false;
    }

    const nlohmann::json &op = manifest["operator"];
    if (op["type"].get<std::string>() != "cube3d" || op["opVersion"].get<int>() != 1) {
        error = "only operator cube3d opVersion 1 is supported";
        return false;
    }
    if (op["interpolation"].get<std::string>() != "trilinear" ||
        op["axisOrder"].get<std::string>() != "red-fastest") {
        error = "only trilinear interpolation with red-fastest axis order is supported";
        return false;
    }
    // Asset path safety: the schema pattern already restricts the filename;
    // resolve defensively and require it to stay inside the package dir.
    std::string asset_name = op["asset"].get<std::string>();
    if (asset_name.find('/') != std::string::npos ||
        asset_name.find('\\') != std::string::npos ||
        asset_name.find("..") != std::string::npos) {
        error = "look asset path is not a plain package-local filename";
        return false;
    }
    std::string asset_path = dir + "/" + asset_name;

    out.asset_sha256 = op["assetSha256"].get<std::string>();
    uint32_t declared_dim = uint32_t(op["dimension"].get<int>());
    if (declared_dim != 17 && declared_dim != 33 && declared_dim != 65) {
        error = "look operator dimension is not 17/33/65";
        return false;
    }
    std::vector<uint8_t> asset_bytes;
    if (!read_file_bytes(asset_path, limits.max_lut_bytes, asset_bytes, error)) {
        error = "look asset: " + error;
        return false;
    }
    std::string asset_hash = sha256_hex(asset_bytes.data(), asset_bytes.size());
    if (asset_hash != out.asset_sha256) {
        error = "look asset hash mismatch (manifest pins " + out.asset_sha256 +
                ", found " + asset_hash + ")";
        return false;
    }
    if (!asset_bytes.empty() && asset_bytes[0] == 0x1F &&
        asset_bytes[1] == 0x8B) { // gzip magic: refuse non-plain data
        error = "look asset appears compressed; plain .cube text expected";
        return false;
    }
    LookPackage parsed;
    if (!parse_cube(asset_bytes, declared_dim, parsed, error)) return false;
    out.dimension = parsed.dimension;
    out.table = std::move(parsed.table);
    out.asset_path = asset_path;
    return true;
}

void cube3d_apply(const LookPackage &lut, RgbFloatBuffer &buffer, double amount, CancelFlag *cancel) {
    cancellation_point(cancel, "look");
    if (amount <= 0.0) return; // amount=0 bypasses the look entirely
    const uint32_t n = lut.dimension;
    const uint32_t nn = n * n;
    const float *table = lut.table.data();
    const float max_index = float(n - 1);
    const double a = std::min(amount, 1.0);
    const double ia = 1.0 - a;
    float *px = buffer.data.data();
    const size_t count = size_t(buffer.width) * buffer.height * 3;
    for_each_chunk(count, cancel, "look.chunk", [&](size_t begin, size_t end) {
        for (size_t i = begin; i < end; i += 3) {
            // Look domain inputs are already [0,1]; clamp defensively (range policy).
            const float r0 = clamp01f(px[i]);
            const float g0 = clamp01f(px[i + 1]);
            const float b0 = clamp01f(px[i + 2]);
            // Red index changes fastest: entry (r,g,b) -> r + n*g + n^2*b.
            const float fr = r0 * max_index, fg = g0 * max_index, fb = b0 * max_index;
            uint32_t r_lo = uint32_t(fr);
            uint32_t g_lo = uint32_t(fg);
            uint32_t b_lo = uint32_t(fb);
            uint32_t r_hi = r_lo + 1 < n ? r_lo + 1 : n - 1;
            uint32_t g_hi = g_lo + 1 < n ? g_lo + 1 : n - 1;
            uint32_t b_hi = b_lo + 1 < n ? b_lo + 1 : n - 1;
            const float tr = fr - float(r_lo);
            const float tg = fg - float(g_lo);
            const float tb = fb - float(b_lo);
            auto at = [&](uint32_t r, uint32_t g, uint32_t b, int c) -> float {
                return table[(r + n * g + nn * b) * 3 + c];
            };
            for (int c = 0; c < 3; c++) {
                const float c000 = at(r_lo, g_lo, b_lo, c);
                const float c100 = at(r_hi, g_lo, b_lo, c);
                const float c010 = at(r_lo, g_hi, b_lo, c);
                const float c110 = at(r_hi, g_hi, b_lo, c);
                const float c001 = at(r_lo, g_lo, b_hi, c);
                const float c101 = at(r_hi, g_lo, b_hi, c);
                const float c011 = at(r_lo, g_hi, b_hi, c);
                const float c111 = at(r_hi, g_hi, b_hi, c);
                const float c00 = c000 + (c100 - c000) * tr;
                const float c10 = c010 + (c110 - c010) * tr;
                const float c01 = c001 + (c101 - c001) * tr;
                const float c11 = c011 + (c111 - c011) * tr;
                const float c0 = c00 + (c10 - c00) * tg;
                const float c1 = c01 + (c11 - c01) * tg;
                const float looked = c0 + (c1 - c0) * tb;
                // Amount blend in the encoded look domain (docs/03 section 3.5).
                px[i + c] = float(ia * px[i + c] + a * looked);
            }
        }
    }, 4096 * 3);
}

} // namespace pe

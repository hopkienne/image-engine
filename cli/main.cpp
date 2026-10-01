// photo-cli: desktop CLI harness over the Shared Photo Engine (G1).
//
//   photo-cli probe <input.raw> --json
//   photo-cli init-recipe <input.raw> --look <look-dir> --out <recipe.json>
//                          [--amount 1.0] [--quality 92] [--subsampling 444]
//   photo-cli render <input.raw> --recipe <recipe.json> --look <look-dir>
//                    --out <output.jpg> --report <run.json>
//                    [--diagnostic-pixels <prefix>]
//
// Exit codes: 0 success, 1 engine error, 2 usage error.
// The engine C ABI is used for probe/export; the diagnostic render links the
// C++ core directly to obtain stage timings for the run report.
#include "photo_engine.h"
#include "cancel_flag.h"
#include "color.h"
#include "build_fingerprint.h"
#include "embedded_schemas.h"
#include "engine_impl.h"
#include "engine_limits.h"
#include "file_util.h"
#include "look.h"
#include "raw_adapter.h"
#include "recipe.h"
#include "render.h"
#include "schema_validate.h"
#include "sha256.h"
#include <nlohmann/json.hpp>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <shellapi.h>
#endif

using namespace pe;

namespace {

// ---------------------------------------------------------------- utils ----

std::string iso_now() {
    std::time_t t = std::time(nullptr);
    std::tm tm{};
#if defined(_WIN32)
    localtime_s(&tm, &t);
#else
    localtime_r(&t, &tm);
#endif
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S%z", &tm);
    return buf;
}

std::string basename_no_ext(const std::string &path) {
    namespace fs = std::filesystem;
    std::string name = fs::u8path(path).filename().u8string();
    size_t dot = name.find_last_of('.');
    if (dot != std::string::npos && dot > 0) name = name.substr(0, dot);
    std::string out;
    for (char c : name) {
        if (std::isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '-') out.push_back(c);
        else out.push_back('-');
    }
    if (out.empty()) out = "source";
    if (out.size() > 200) out = out.substr(0, 200);
    return out;
}

bool read_whole_file(const std::string &path, std::vector<uint8_t> &out,
                     std::string &error) {
    FILE *f = utf8_fopen(path, "rb");
    if (!f) {
        error = "cannot open " + path;
        return false;
    }
    out.clear();
    uint8_t buf[1 << 16];
    size_t n;
    while ((n = std::fread(buf, 1, sizeof(buf), f)) > 0) out.insert(out.end(), buf, buf + n);
    bool bad = std::ferror(f) != 0;
    std::fclose(f);
    if (bad) {
        error = "read error on " + path;
        return false;
    }
    return true;
}

void print_engine_error(pe_status st, const char *where) {
    std::string json_text;
    take_last_error_json(json_text);
    std::fprintf(stderr, "error[%s] at %s: %s\n", pe_status_name(int(st)), where,
                 json_text.c_str());
}

[[noreturn]] void usage_exit() {
    std::fprintf(stderr,
                 "usage:\n"
                 "  photo-cli probe <input.raw> --json\n"
                 "  photo-cli init-recipe <input.raw> --look <look-dir> --out <recipe.json>\n"
                 "          [--amount 1.0] [--quality 92] [--subsampling 444|420]\n"
                 "  photo-cli render <input.raw> --recipe <recipe.json> --look <look-dir>\n"
                 "          --out <output.jpg> --report <run.json> [--diagnostic-pixels <prefix>]\n"
                 "          [--audit-checkpoints <dir>]  (test-only stage dumps)\n");
    std::exit(2);
}

struct Args {
    std::string command;
    std::string input, look, out, recipe, report, dump_prefix, audit_dir;
    double amount = 1.0;
    int quality = 92;
    std::string subsampling = "444";
    bool json = false;
};

Args parse_args(int argc, char **argv) {
    Args a;
    if (argc < 2) usage_exit();
    a.command = argv[1];
    auto next = [&](int &i) -> std::string {
        if (i + 1 >= argc) usage_exit();
        return argv[++i];
    };
    for (int i = 2; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--json") a.json = true;
        else if (arg == "--look") a.look = next(i);
        else if (arg == "--out") a.out = next(i);
        else if (arg == "--recipe") a.recipe = next(i);
        else if (arg == "--report") a.report = next(i);
        else if (arg == "--diagnostic-pixels") a.dump_prefix = next(i);
        else if (arg == "--audit-checkpoints") a.audit_dir = next(i);
        else if (arg == "--amount") a.amount = std::stod(next(i));
        else if (arg == "--quality") a.quality = std::stoi(next(i));
        else if (arg == "--subsampling") a.subsampling = next(i);
        else if (arg.rfind("-", 0) != 0) {
            if (a.input.empty()) a.input = arg;
            else usage_exit();
        } else usage_exit();
    }
    return a;
}

nlohmann::json build_fingerprint_json() {
    nlohmann::json j;
    j["compiler"] = PHOTO_BUILD_COMPILER;
    j["cxxStandard"] = PHOTO_BUILD_CXX_STD;
    j["buildType"] = PHOTO_BUILD_TYPE;
    j["cxxFlags"] = PHOTO_BUILD_CXX_FLAGS;
    j["libraw"] = PHOTO_LIBRAW_VERSION;
    j["libjpegTurbo"] = PHOTO_LIBJPEG_TURBO_VERSION;
    j["jpegLibVersion"] = PHOTO_JPEG_LIB_VERSION;
    j["zlib"] = PHOTO_ZLIB_VERSION;
    j["developerBuild"] = PHOTO_DEVELOPER_BUILD;
    j["numericsNote"] = "no fast-math; -ffp-contract=off; SSE2 baseline";
    return j;
}

// Shared setup: engine + source (probe includes sha256 + kind).
bool open_engine_and_source(Args &a, Engine **out_engine, Source **out_source) {
    nlohmann::json config;
    config["configVersion"] = 1;
    if (!a.look.empty()) config["assetSearchPaths"] = nlohmann::json::array({a.look});
    std::string cfg_text = config.dump();
    pe_engine *engine = nullptr;
    pe_status st = pe_engine_create(cfg_text.data(), cfg_text.size(), &engine);
    if (st != PE_OK) {
        print_engine_error(st, "engine_create");
        return false;
    }
    *out_engine = reinterpret_cast<Engine *>(engine);
    pe_source *src = nullptr;
    st = pe_source_open_local(engine, a.input.data(), a.input.size(), &src);
    if (st != PE_OK) {
        print_engine_error(st, "source_open");
        return false;
    }
    *out_source = reinterpret_cast<Source *>(src);
    return true;
}

// ---------------------------------------------------------------- probe ----

int cmd_probe(Args &a) {
    if (a.input.empty() || !a.json) usage_exit();
    Engine *engine = nullptr;
    Source *source = nullptr;
    if (!open_engine_and_source(a, &engine, &source)) return 1;
    pe_blob *blob = nullptr;
    pe_status st = pe_source_info_json(reinterpret_cast<pe_source *>(source), &blob);
    if (st != PE_OK) {
        print_engine_error(st, "source_info");
        return 1;
    }
    size_t n = 0;
    const uint8_t *data = pe_blob_data(blob, &n);
    std::fwrite(data, 1, n, stdout);
    std::fputc('\n', stdout);
    pe_blob_release(blob);
    pe_source_release(reinterpret_cast<pe_source *>(source));
    pe_engine_destroy(reinterpret_cast<pe_engine *>(engine));
    return 0;
}

// ----------------------------------------------------------- init-recipe ----

int cmd_init_recipe(Args &a) {
    if (a.input.empty() || a.look.empty() || a.out.empty()) usage_exit();
    if (a.amount < 0.0 || a.amount > 1.0) {
        std::fprintf(stderr, "--amount must be within [0,1]\n");
        return 2;
    }
    if (a.subsampling != "444" && a.subsampling != "420") {
        std::fprintf(stderr, "--subsampling must be 444 or 420\n");
        return 2;
    }
    Engine *engine = nullptr;
    Source *source = nullptr;
    if (!open_engine_and_source(a, &engine, &source)) return 1;

    const SourceProbe &probe = source->probe;
    // asShot WB must be resolvable from the file (docs/03 section 3.6).
    double wb_norm[4];
    if (!resolve_as_shot_wb(probe, wb_norm)) {
        std::fprintf(stderr,
                     "{\"errorCode\":\"AS_SHOT_WB_UNAVAILABLE\",\"stage\":\"resolve_as_shot_wb\","
                     "\"sourceOpened\":true,\"rawUnpackTested\":false,\"recipeCreated\":false,"
                     "\"message\":\"As-shot white balance is unavailable. This is distinct from a RAW decode failure. "
                     "No fallback was applied. Custom WB requires verified values; product policy remains Proposed.\"}\n");
        return 1;
    }
    if (probe.kind != "cameraRaw") {
        std::fprintf(stderr, "error: this build only initializes recipes for "
                             "cameraRaw sources (probe says %s)\n", probe.kind.c_str());
        return 1;
    }

    nlohmann::json recipe;
    recipe["schemaVersion"] = 1;
    recipe["recipeId"] = basename_no_ext(a.input) + "-initial";
    recipe["source"] = {{"id", basename_no_ext(a.input)},
                        {"sha256", probe.sha256},
                        {"kind", probe.kind}};
    recipe["execution"] = {
        {"engineCompatibility", engine->identity.engine_compatibility},
        {"pipelineId", engine->identity.pipeline_id},
        {"pipelineVersion", engine->identity.pipeline_version},
        {"developerBuild", engine->identity.developer_build},
        {"cameraProfile", nullptr}};
    // LibRaw reports cam_mul on a raw scale (often x256, G1 = 256 or 1.0);
    // recipe v1 stores multipliers normalized to G = 1 (docs/03 section 3.6
    // convention, matching the synthetic example). Color results are
    // invariant to the absolute scale: dcraw normalizes by the max multiplier
    // internally, so only the ratios matter.
    recipe["adjustments"] = {
        {"exposureEV", 0},
        {"whiteBalance", {{"mode", "asShot"},
                          {"resolvedCameraMultipliers",
                           {wb_norm[0], wb_norm[1], wb_norm[2], wb_norm[3]}}}}};

    // Look pin comes from the package itself, verified through the engine path.
    RecipeModel dummy_model;
    dummy_model.pipeline_id = engine->identity.pipeline_id;
    dummy_model.source_kind = probe.kind;
    dummy_model.look_manifest_sha256 = ""; // no pin yet: accept the matched one
    LookPackage look;
    std::string error;
    if (!find_and_load_look_unpinned(*engine, a.look, probe.kind, look, error)) {
        std::fprintf(stderr, "error: look package: %s\n", error.c_str());
        return 1;
    }
    recipe["look"] = {{"id", look.id},
                      {"version", look.version},
                      {"manifestSha256", look.manifest_sha256},
                      {"amount", a.amount}};
    recipe["geometry"] = {{"crop", {{"left", 0}, {"top", 0}, {"width", 1}, {"height", 1}}},
                          {"rotationQuarterTurns", 0},
                          {"flipHorizontal", false}};
    recipe["grain"] = {{"enabled", false},
                       {"algorithm", "grain-v1-proposed"},
                       {"seed", 0},
                       {"amount", 0},
                       {"referenceLongEdge", 2048}};
    recipe["output"] = {{"format", "jpeg"},
                        {"colorSpace", "srgb"},
                        {"bitDepth", 8},
                        {"quality", a.quality},
                        {"subsampling", a.subsampling},
                        {"longEdge", nullptr},
                        {"metadataPolicy", "strip_location"}};

    // Self-check: the produced recipe must pass our own validators.
    SchemaValidators validators{engine->recipe_validator.get(), engine->look_validator.get()};
    EngineLimits defaults;
    nlohmann::json reparsed;
    std::string text = recipe.dump(2);
    if (!parse_recipe_json(text.data(), text.size(), defaults, validators, reparsed, error) ||
        !validate_recipe_semantics(reparsed, engine->identity, dummy_model, error)) {
        std::fprintf(stderr, "error: generated recipe failed self-check: %s\n", error.c_str());
        return 1;
    }

    if (path_exists(a.out)) {
        std::fprintf(stderr, "error: output path already exists: %s\n", a.out.c_str());
        return 1;
    }
    FILE *f = utf8_fopen(a.out, "wb");
    if (!f) {
        std::fprintf(stderr, "error: cannot write %s\n", a.out.c_str());
        return 1;
    }
    std::fwrite(text.data(), 1, text.size(), f);
    std::fclose(f);
    std::fprintf(stderr, "recipe written: %s (source sha256 %s, look %s %s)\n",
                 a.out.c_str(), probe.sha256.substr(0, 12).c_str(), look.id.c_str(),
                 look.version.c_str());
    pe_source_release(reinterpret_cast<pe_source *>(source));
    pe_engine_destroy(reinterpret_cast<pe_engine *>(engine));
    return 0;
}

// --------------------------------------------------------------- render ----

int cmd_render(Args &a) {
    if (a.input.empty() || a.recipe.empty() || a.look.empty() || a.out.empty() ||
        a.report.empty()) {
        usage_exit();
    }
    Engine *engine = nullptr;
    Source *source = nullptr;
    if (path_exists(a.out)) {
        std::fprintf(stderr, "error: output path already exists: %s\n", a.out.c_str());
        return 1;
    }
    if (!open_engine_and_source(a, &engine, &source)) return 1;

    std::vector<uint8_t> recipe_bytes;
    std::string error;
    if (!read_whole_file(a.recipe, recipe_bytes, error)) {
        std::fprintf(stderr, "error: %s\n", error.c_str());
        return 1;
    }
    const std::string recipe_sha = sha256_hex(recipe_bytes.data(), recipe_bytes.size());

    // Render once; share the exact pixels with diagnostics and JPEG export.
    RenderModelBundle bundle;
    if (!prepare_and_render(*engine, *source, recipe_bytes, bundle, error,
                            a.audit_dir.empty() ? nullptr : a.audit_dir.c_str(), !a.dump_prefix.empty() || !a.audit_dir.empty())) {
        std::fprintf(stderr, "error[%s]: %s\n", pe_status_name(bundle.status),
                     error.c_str());
        return 1;
    }

    nlohmann::json report;
    report["reportVersion"] = 1;
    report["generatedAt"] = iso_now();
    report["build"] = build_fingerprint_json();
    report["source"] = {
        {"path", source->path},
        {"sha256", source->probe.sha256},
        {"kind", source->probe.kind},
        {"make", source->probe.make},
        {"model", source->probe.model},
        {"fileSize", source->probe.file_size}};

    const RecipeModel &model = bundle.model;
    report["recipe"] = {
        {"path", a.recipe},
        {"sha256", recipe_sha},
        {"recipeId", model.recipe_id},
        {"pipelineId", model.pipeline_id},
        {"pipelineVersion", model.pipeline_version},
        {"developerBuild", model.developer_build},
        {"developerBuildMatchesEngine",
         model.developer_build == engine->identity.developer_build}};
    nlohmann::json long_edge_json =
        model.has_long_edge ? nlohmann::json(model.long_edge) : nlohmann::json(nullptr);
    nlohmann::json wb_multipliers_json = nlohmann::json::array(
        {model.wb_multipliers[0], model.wb_multipliers[1], model.wb_multipliers[2],
         model.wb_multipliers[3]});
    report["resolved"] = {
        {"exposureEV", model.exposure_ev},
        {"whiteBalance", {{"mode", model.wb_mode},
                          {"resolvedCameraMultipliers", wb_multipliers_json}}},
        {"look", {{"id", model.look_id},
                  {"version", model.look_version},
                  {"manifestSha256", model.look_manifest_sha256},
                  {"assetSha256", bundle.look.asset_sha256},
                  {"amount", model.look_amount},
                  {"dimension", bundle.look.dimension}}},
        {"geometry", {{"crop", {{"left", model.crop_left},
                                {"top", model.crop_top},
                                {"width", model.crop_width},
                                {"height", model.crop_height}}},
                      {"rotationQuarterTurns", model.rotation_quarter_turns},
                      {"flipHorizontal", model.flip_horizontal}}},
        {"output", {{"quality", model.quality},
                    {"subsampling", model.subsampling},
                    {"longEdge", long_edge_json},
                    {"metadataPolicy", model.metadata_policy}}}};
    report["decoderConfig"] = nlohmann::json::parse(raw_developer_config_echo_json());
    report["source"]["orientationFlipApplied"] = bundle.output.orientation_flip_applied;
    report["domain"] = {
        {"working", kDomainLinearBounded},
        {"look", kDomainLook},
        {"note", "P0 integer pipeline clips at the decoder white level; no "
                 "scene-linear unbounded claim and no highlight recovery"}};

    report["demosaicEvidence"] = {{"requested_quality", 3},
        {"cfa", bundle.output.cfa_filters == 9 ? "X-Trans" : bundle.output.cfa_filters > 1000 ? "Bayer" : "OTHER"},
        {"effective_algorithm", "UNKNOWN"}, {"note", "No dispatch instrumentation; user_qual alone is not an algorithm observation"}};
    report["timings"] = {
        {"readMetadataMs", bundle.timings.read_ms},
        {"unpackMs", bundle.timings.unpack_ms},
        {"rawProcessMs", bundle.timings.raw_process_ms},
        {"rawConvertAndEndpointScanMs", bundle.timings.raw_convert_ms},
        {"transferEncodeMs", bundle.timings.transfer_encode_ms},
        {"transferDecodeMs", bundle.timings.transfer_decode_ms},
        {"diagnosticCheckpointAndScanMs", bundle.timings.diagnostic_ms},
        {"developMs", bundle.timings.develop_ms},
        {"orientationMs", bundle.timings.orientation_ms},
        {"exposureMs", bundle.timings.exposure_ms},
        {"lookMs", bundle.timings.look_ms},
        {"geometryMs", bundle.timings.geometry_ms},
        {"resizeMs", bundle.timings.resize_ms},
        {"encodePrepMs", bundle.timings.encode_prep_ms},
        {"totalPipelineMs", bundle.timings.total_ms}};

    report["highlightDiagnostics"] = {
        {"collected", !a.dump_prefix.empty() || !a.audit_dir.empty()},
        {"channelOrder", "RGB"},
        {"developSaturatedChannelCounts", bundle.output.develop_saturated_channels},
        {"exposureClampedChannelCounts", bundle.output.exposure_clamped_channels},
        {"note", "Counts before crop/resize. The 16-bit develop endpoint can include valid white; "
                 "these counts do not prove sensor clipping. Lowering EV after develop cannot "
                 "recover detail already clipped by the decoder."}};

    const auto diagnostic_start = std::chrono::steady_clock::now();
    // Optional pre-quantize pixel dump (encoded sRGB FP32) with descriptor.
    if (!a.dump_prefix.empty()) {
        const RgbFloatBuffer &buf = bundle.output.encoded;
        std::string fp = a.dump_prefix;
        FILE *f = utf8_fopen(fp + ".f32", "wb");
        if (!f) {
            std::fprintf(stderr, "error: cannot write pixel dump\n");
            return 1;
        }
        std::fwrite(buf.data.data(), sizeof(float), buf.data.size(), f);
        std::fclose(f);
        nlohmann::json desc;
        desc["width"] = buf.width;
        desc["height"] = buf.height;
        desc["channels"] = 3;
        desc["channelOrder"] = "RGB";
        desc["sampleType"] = "float32";
        desc["byteOrder"] = "little-endian";
        desc["rowStrideBytes"] = uint64_t(buf.width) * 3 * sizeof(float);
        desc["transferFunction"] = "srgb-encoded";
        desc["primaries"] = "sRGB";
        desc["whitePoint"] = "D65";
        desc["rangePolicy"] = "bounded-[0,1]-full";
        desc["orientationState"] = "baked-normalized";
        desc["referenceDomain"] = kDomainLook;
        desc["note"] = "pre-quantize dump taken after final clamp+encode";
        FILE *df = utf8_fopen(fp + ".json", "wb");
        if (df) {
            std::string dtext = desc.dump(2);
            std::fwrite(dtext.data(), 1, dtext.size(), df);
            std::fclose(df);
        }
        report["diagnosticDump"] = {{"file", fp + ".f32"},
                                    {"descriptor", fp + ".json"},
                                    {"sha256", sha256_hex(
                                                   reinterpret_cast<const uint8_t *>(
                                                       buf.data.data()),
                                                   buf.data.size() * sizeof(float))}};
    }

    report["timings"]["diagnosticWriteHashMs"] = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - diagnostic_start).count();
    // Encode the validated render through the shared export path, then publish.
    const std::string staging = a.out + ".part";
    if (path_exists(staging)) {
        std::fprintf(stderr, "error: staging path exists: %s\n", staging.c_str());
        return 1;
    }
    const double export_t0 = std::chrono::duration<double, std::milli>(
                                 std::chrono::steady_clock::now().time_since_epoch())
                                 .count();
    pe_status st = static_cast<pe_status>(export_rendered_jpeg(
        bundle.output, bundle.model, staging, nullptr, error));
    if (st != PE_OK) set_last_error(int(st), "export", error);
    const double export_ms = std::chrono::duration<double, std::milli>(
                                 std::chrono::steady_clock::now().time_since_epoch())
                                 .count() - export_t0;
    if (st != PE_OK) {
        print_engine_error(st, "export");
        return 1;
    }
    if (!utf8_rename_no_replace(staging, a.out)) {
        std::fprintf(stderr, "error: staging rename failed\n");
        utf8_remove(staging);
        return 1;
    }
    report["timings"]["exportTotalMs"] = export_ms; // encode + staging I/O only
    report["timings"]["renderAndExportMs"] = bundle.timings.total_ms + export_ms;
    report["timings"]["pipelineExecutions"] = 1;

    report["timingContract"] = "readMetadata/unpack/rawProcess/rawConvert are disjoint sub-stages of inclusive developMs; do not sum developMs with them. Transfer/look/geometry/resize/final encode/checkpoint/export/dump timers are disjoint. Source hash, recipe/look validation, report serialization and process startup remain outside pipeline timers.";
    // Source immutability evidence: re-hash after the whole run.
    bool ok2 = false;
    std::string sha_after = sha256_hex_of_file(source->path, &ok2);
    report["source"]["hashUnchangedAfterRender"] =
        ok2 && sha_after == source->probe.sha256;

    // Output facts.
    uint64_t out_size = 0;
    {
        FILE *f = utf8_fopen(a.out, "rb");
        if (f) {
#if defined(_WIN32)
            _fseeki64(f, 0, SEEK_END);
            out_size = (uint64_t)_ftelli64(f);
#else
            fseeko(f, 0, SEEK_END);
            out_size = (uint64_t)ftello(f);
#endif
            std::fclose(f);
        }
    }
    std::vector<uint8_t> out_bytes;
    read_whole_file(a.out, out_bytes, error);
    report["output"] = {{"path", a.out},
                        {"bytes", out_size},
                        {"width", bundle.output.out_width},
                        {"height", bundle.output.out_height},
                        {"jpegSha256", out_bytes.empty()
                                           ? ""
                                           : sha256_hex(out_bytes.data(),
                                                        out_bytes.size())}};
    report["warnings"] = bundle.warnings;

    const std::string rtext = report.dump(2);
    FILE *rf = utf8_fopen(a.report, "wb");
    if (!rf) {
        std::fprintf(stderr, "error: cannot write report %s\n", a.report.c_str());
        return 1;
    }
    std::fwrite(rtext.data(), 1, rtext.size(), rf);
    std::fclose(rf);

    std::fprintf(stderr, "rendered %ux%u -> %s (%llu bytes) in %.1f ms; report: %s\n",
                 bundle.output.out_width, bundle.output.out_height, a.out.c_str(),
                 (unsigned long long)out_size, export_ms, a.report.c_str());
    pe_source_release(reinterpret_cast<pe_source *>(source));
    pe_engine_destroy(reinterpret_cast<pe_engine *>(engine));
    return 0;
}

} // namespace

int main(int argc, char **argv) {
#ifdef _WIN32
    int wide_argc = 0;
    LPWSTR *wide_argv = CommandLineToArgvW(GetCommandLineW(), &wide_argc);
    if (!wide_argv) return 2;
    std::vector<std::string> utf8_args;
    utf8_args.reserve(wide_argc);
    for (int i = 0; i < wide_argc; ++i) {
        const int n = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide_argv[i], -1,
                                          nullptr, 0, nullptr, nullptr);
        if (n <= 0) { LocalFree(wide_argv); return 2; }
        std::string value(n, '\0');
        if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide_argv[i], -1,
                                 value.data(), n, nullptr, nullptr)) {
            LocalFree(wide_argv); return 2;
        }
        value.resize(n - 1);
        utf8_args.push_back(std::move(value));
    }
    LocalFree(wide_argv);
    std::vector<char *> utf8_argv;
    for (auto &value : utf8_args) utf8_argv.push_back(value.data());
    argc = wide_argc;
    argv = utf8_argv.data();
#endif
    Args a = parse_args(argc, argv);
    if (a.command == "probe") return cmd_probe(a);
    if (a.command == "init-recipe") return cmd_init_recipe(a);
    if (a.command == "render") return cmd_render(a);
    usage_exit();
}

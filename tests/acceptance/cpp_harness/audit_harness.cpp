// Independent audit harness over the production C ABI (photo_engine.h).
// This is test tooling: it links the production core but implements no color
// math. Modes are selected by argv[1]; results are printed as JSON lines.
//
//   sequence <source> <lookDir>   A->B->A->A' render sequence, SHA-256 per step
//   cancel <source> <lookDir>     pre-cancel, mid-render cancel, post-cancel
//   lifecycle <source> <lookDir>  repeated create/render/destroy rounds + memory
//   abi <source>                  span semantics, unicode path, oversized config
#include "photo_engine.h"
#include "sha256.h"
#include "cancel_flag.h"
#include "file_util.h"
#include <nlohmann/json.hpp>
#include <chrono>
#include <filesystem>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <psapi.h>
#include <shellapi.h>
#endif

using namespace pe; // sha256_hex only; ABI used through C signatures

namespace {

std::string config_json(const char *look_dir) {
    // escape backslashes so Windows paths stay valid JSON strings
    std::string escaped;
    for (const char *p = look_dir; *p; ++p) {
        if (*p == '\\' || *p == '"') escaped += '\\';
        escaped += *p;
    }
    std::string s = "{\"configVersion\":1,\"assetSearchPaths\":[\"";
    s += escaped;
    s += "\"]}";
    return s;
}

// Renders given recipe text, returns digest of the RGBA FP32 pixels and the
// pe_status. digest empty on failure; last error JSON appended to errors.
pe_status render_once(pe_engine *engine, pe_source *src, const std::string &recipe,
                      std::string &digest, std::string &err_json,
                      pe_cancel_token *cancel = nullptr) {
    pe_preview_options opt{};
    opt.struct_size = sizeof(opt);
    opt.abi_version = 1;
    opt.long_edge_px = 4096; // above source long edge for these fixtures => no resample
    opt.quality = 0;
    opt.request_generation = 0;
    pe_image *img = nullptr;
    pe_status st = pe_render_preview(engine, src, recipe.data(), recipe.size(),
                                     &opt, cancel, &img);
    if (st != PE_OK) {
        pe_blob *b = nullptr;
        if (pe_last_error_json(engine, &b) == PE_OK || true) {
            size_t n = 0;
            const uint8_t *d = pe_blob_data(b, &n);
            if (d && n) err_json.assign(reinterpret_cast<const char *>(d), n);
            pe_blob_release(b);
        }
        return st;
    }
    pe_image_info info{};
    info.struct_size = sizeof(info);
    info.abi_version = 1;
    st = pe_image_describe(img, &info);
    if (st != PE_OK) {
        pe_image_release(img);
        return st;
    }
    Sha256 s;
    sha256_init(s);
    sha256_update(s, reinterpret_cast<const uint8_t *>(info.pixels),
                  size_t(info.byte_length));
    uint8_t out[32];
    sha256_final(s, out);
    static const char *hex = "0123456789abcdef";
    for (int i = 0; i < 32; i++) {
        digest.push_back(hex[out[i] >> 4]);
        digest.push_back(hex[out[i] & 15]);
    }
    pe_image_release(img);
    return PE_OK;
}

int read_file(const std::string &path, std::string &out) {
    std::ifstream f(std::filesystem::u8path(path), std::ios::binary);
    if (!f) return 1;
    std::ostringstream ss;
    ss << f.rdbuf();
    out = ss.str();
    return 0;
}

std::string make_recipe(const std::string &source_sha, const std::string &manifest_sha,
                        double amount, double ev, const char *wb_mode,
                        const std::string &multipliers_json, const char *look_id,
                        int rotate = 0, int flip = 0) {
    std::ostringstream r;
    r << R"({
  "schemaVersion": 1, "recipeId": "audit-harness", 
  "source": {"id": "audit", "sha256": ")" << source_sha << R"(", "kind": "cameraRaw"},
  "execution": {"engineCompatibility": "photo-engine-major-1-proposed",
    "pipelineId": "baseline-v0", "pipelineVersion": "0.1.0",
    "developerBuild": "photo-engine-g1-libraw-0.22.2", "cameraProfile": null},
  "adjustments": {"exposureEV": )" << ev << R"(,
    "whiteBalance": {"mode": ")" << wb_mode << R"(", "resolvedCameraMultipliers": )"
      << multipliers_json << R"(}},
  "look": {"id": ")" << look_id << R"(", "version": "1.0.0",
    "manifestSha256": ")" << manifest_sha << R"(", "amount": )" << amount << R"(},
  "geometry": {"crop": {"left": 0, "top": 0, "width": 1, "height": 1},
    "rotationQuarterTurns": )" << rotate << R"(, "flipHorizontal": )"
      << (flip ? "true" : "false") << R"(},
  "grain": {"enabled": false, "algorithm": "grain-v1-proposed", "seed": 0,
    "amount": 0, "referenceLongEdge": 2048},
  "output": {"format": "jpeg", "colorSpace": "srgb", "bitDepth": 8,
    "quality": 92, "subsampling": "444", "longEdge": null,
    "metadataPolicy": "strip_location"}
})";
    return r.str();
}

} // namespace

int main(int argc, char **argv) {
#ifdef _WIN32
    // Windows narrow argv uses the active code page, not UTF-8. Preserve
    // Unicode arguments before passing spans to the UTF-8 production ABI.
    int wide_argc = 0;
    LPWSTR *wide_argv = CommandLineToArgvW(GetCommandLineW(), &wide_argc);
    if (!wide_argv) return 2;
    std::vector<std::string> utf8_args;
    for (int i = 0; i < wide_argc; ++i) {
        const int n = WideCharToMultiByte(CP_UTF8, 0, wide_argv[i], -1,
                                          nullptr, 0, nullptr, nullptr);
        std::string value(n, '\0');
        WideCharToMultiByte(CP_UTF8, 0, wide_argv[i], -1, value.data(), n,
                            nullptr, nullptr);
        value.resize(n - 1);
        utf8_args.push_back(std::move(value));
    }
    LocalFree(wide_argv);
    std::vector<char *> utf8_argv;
    for (auto &value : utf8_args) utf8_argv.push_back(value.data());
    argc = wide_argc;
    argv = utf8_argv.data();
#endif
    if (argc >= 6 && std::string(argv[1]) == "cancel-stages") {
        // cancel-stages <source> <lookDir> <recipe> <stagingDir>
        // Internal token observer makes each stage deterministic; no sleeps.
        const std::string cfg = config_json(argv[3]);
        std::string recipe;
        if (read_file(argv[4], recipe)) return 2;
        pe_engine *engine = nullptr;
        pe_source *source = nullptr;
        if (pe_engine_create(cfg.data(), cfg.size(), &engine) != PE_OK) return 1;
        if (pe_source_open_local(engine, argv[2], std::strlen(argv[2]), &source) != PE_OK) {
            pe_engine_destroy(engine); return 1;
        }
        struct StageStop {
            const char *target;
            int occurrence;
            int seen = 0;
            double requested_ms = 0;
        };
        auto observer = [](CancelFlag &token, const char *stage, void *data) noexcept {
            auto &stop = *static_cast<StageStop *>(data);
            if (std::strcmp(stop.target, stage) == 0 && ++stop.seen == stop.occurrence) {
                stop.requested_ms = std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now().time_since_epoch()).count();
                token.request();
            }
        };
        const std::vector<const char *> preview_stages = {
            "raw.open", "Reading RAW data", "Interpolating", "raw.convert.chunk",
            "orientation", "exposure.chunk", "transfer.chunk", "look.chunk",
            "decode.chunk", "geometry.crop.row", "geometry.remap.row", "geometry.mirror.row",
            "resize.row", "render.ready", "preview.pack.chunk", "preview.ready"};
        const std::vector<const char *> export_stages = {
            "quantize.chunk", "jpeg.row", "export.write", "export.write.complete"};
        auto modified = nlohmann::json::parse(recipe);
        modified["adjustments"]["exposureEV"] = 0.5;
        modified["geometry"]["crop"] = {{"left",0.05},{"top",0.05},{"width",0.9},{"height",0.9}};
        modified["geometry"]["rotationQuarterTurns"] = 1;
        modified["geometry"]["flipHorizontal"] = true;
        modified["output"]["longEdge"] = 512;
        recipe = modified.dump();
        int failures = 0;
        for (int mode = 0; mode < 2; ++mode) {
            const auto &stages = mode == 0 ? preview_stages : export_stages;
            for (size_t index = 0; index < stages.size(); ++index) {
                pe_cancel_token *token = nullptr; pe_cancel_create(&token);
                const int occurrence = std::strstr(stages[index], "chunk") || std::strstr(stages[index], ".row") ? 2 : 1;
                StageStop stop{stages[index], occurrence};
                reinterpret_cast<CancelFlag *>(token)->set_observer(observer, &stop);
                pe_image *image = nullptr;
                const auto staging = std::filesystem::u8path(argv[5]) / ("cancel-"+std::to_string(index)+".part");
                const auto staging_utf8 = staging.u8string();
                if (path_exists(staging_utf8)) { ++failures; pe_cancel_release(token); continue; }
                pe_status status;
                if (mode == 0) {
                    pe_preview_options options{};
                    options.struct_size=sizeof(options); options.abi_version=1;
                    options.long_edge_px=512; options.request_generation=23;
                    status=pe_render_preview(engine,source,recipe.data(),recipe.size(),&options,token,&image);
                } else {
                    status=pe_export_jpeg(engine,source,recipe.data(),recipe.size(),staging_utf8.data(),staging_utf8.size(),token);
                }
                const double ended_ms = std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now().time_since_epoch()).count();
                const bool ok = status==PE_CANCELLED && image==nullptr && stop.seen>=occurrence && !path_exists(staging_utf8);
                if (!ok) ++failures;
                std::cout << nlohmann::json({{"stage",stages[index]}, {"mode",mode==0?"preview":"export"},
                    {"status",int(status)},{"observations",stop.seen},{"expectedObservations",occurrence},
                    {"cancelReturnLatencyMs",stop.requested_ms ? ended_ms-stop.requested_ms : -1}, {"pass",ok}}).dump() << "\n";
                pe_image_release(image); pe_cancel_release(token);
            }
        }
        // A cancelled operation must not poison the reusable engine/source.
        pe_preview_options options{}; options.struct_size=sizeof(options); options.abi_version=1;
        options.long_edge_px=512; options.request_generation=24;
        pe_image *image=nullptr;
        const auto status=pe_render_preview(engine,source,recipe.data(),recipe.size(),&options,nullptr,&image);
        pe_image_info info{};info.struct_size=sizeof(info);info.abi_version=1;
        const bool recovery=status==PE_OK && pe_image_describe(image,&info)==PE_OK && info.request_generation==24;
        if(!recovery) ++failures;
        std::cout << nlohmann::json({{"stage","post-cancel-reuse"},{"pass",recovery}}).dump()<<"\n";
        pe_image_release(image);pe_source_release(source);pe_engine_destroy(engine);
        return failures ? 1 : 0;
    }
    if (argc >= 8 && std::string(argv[1]) == "preview-dump") {
        // preview-dump <source> <lookDir> <recipe> <longEdge> <rgb.f32> <desc.json>
        const std::string cfg = config_json(argv[3]);
        std::string recipe;
        if (read_file(argv[4], recipe)) return 2;
        pe_engine *engine = nullptr;
        pe_source *source = nullptr;
        pe_image *image = nullptr;
        pe_status status = pe_engine_create(cfg.data(), cfg.size(), &engine);
        if (status == PE_OK)
            status = pe_source_open_local(engine, argv[2], std::strlen(argv[2]), &source);
        pe_preview_options options{};
        options.struct_size = sizeof(options);
        options.abi_version = 1;
        options.long_edge_px = uint32_t(std::stoul(argv[5]));
        if (status == PE_OK)
            status = pe_render_preview(engine, source, recipe.data(), recipe.size(),
                                       &options, nullptr, &image);
        pe_image_info info{};
        info.struct_size = sizeof(info);
        info.abi_version = 1;
        if (status == PE_OK) status = pe_image_describe(image, &info);
        bool layout_ok = status == PE_OK && info.pixel_format == 1 &&
            info.row_stride_bytes >= uint64_t(info.width) * 4 * sizeof(float) &&
            info.byte_length >= info.row_stride_bytes * info.height;
        bool alpha_ok = layout_ok;
        std::ofstream pixels(std::filesystem::u8path(argv[6]), std::ios::binary);
        if (layout_ok) {
            const auto *data = static_cast<const uint8_t *>(info.pixels);
            for (uint32_t y = 0; y < info.height; ++y) {
                for (uint32_t x = 0; x < info.width; ++x) {
                    float rgba[4];
                    std::memcpy(rgba, data + y * info.row_stride_bytes + x * sizeof(rgba), sizeof(rgba));
                    alpha_ok = alpha_ok && rgba[3] == 1.0f;
                    pixels.write(reinterpret_cast<const char *>(rgba), 3 * sizeof(float));
                }
            }
        }
        pixels.close();
        std::ofstream descriptor(std::filesystem::u8path(argv[7]));
        descriptor << "{\"width\":" << info.width << ",\"height\":" << info.height
                   << ",\"channels\":3,\"channelOrder\":\"RGB\",\"sampleType\":\"float32\","
                      "\"byteOrder\":\"little\",\"alphaValidated\":" << (alpha_ok ? "true" : "false")
                   << ",\"nativeStrideBytes\":" << info.row_stride_bytes
                   << ",\"nativeByteLength\":" << info.byte_length << "}";
        descriptor.close();
        pe_image_release(image);
        pe_source_release(source);
        pe_engine_destroy(engine);
        return status == PE_OK && layout_ok && alpha_ok && pixels && descriptor ? 0 : 1;
    }
    if (argc < 3) {
        std::fprintf(stderr, "usage: audit_harness <mode> <args...>\n");
        return 2;
    }
    const std::string mode = argv[1];

    if (mode == "sequence") {
        // sequence <source> <lookDir> <sourceSha> <identityManifestSha> <affineManifestSha>
        if (argc < 6) return 2;
        const char *source = argv[2], *look_dir = argv[3];
        const std::string source_sha = argv[4], id_sha = argv[5], aff_sha = argv[6];
        pe_engine *engine = nullptr;
        if (pe_engine_create(config_json(look_dir).data(),
                             config_json(look_dir).size(), &engine) != PE_OK)
            return 1;
        pe_source *src = nullptr;
        if (pe_source_open_local(engine, source, std::strlen(source), &src) != PE_OK)
            return 1;
        std::string A = make_recipe(source_sha, id_sha, 1.0, 0.0, "asShot",
                                    "[1.9609375, 1.0, 1.51171875, 1.0]",
                                    "audit-identity-17");
        std::string B = make_recipe(source_sha, aff_sha, 0.5, 0.0, "asShot",
                                    "[1.9609375, 1.0, 1.51171875, 1.0]",
                                    "audit-affine-17");
        std::string dA, dB, dA2, dA3, e;
        pe_status s1 = render_once(engine, src, A, dA, e);
        pe_status s2 = render_once(engine, src, B, dB, e);
        pe_status s3 = render_once(engine, src, A, dA2, e);
        // A again via a fresh render call (same engine/source context)
        pe_status s4 = render_once(engine, src, A, dA3, e);
        std::cout << "{\"mode\":\"sequence\""
                  << ",\"s1\":" << int(s1) << ",\"s2\":" << int(s2)
                  << ",\"s3\":" << int(s3) << ",\"s4\":" << int(s4)
                  << ",\"A\":\"" << dA << "\",\"B\":\"" << dB
                  << "\",\"A2\":\"" << dA2 << "\",\"A3\":\"" << dA3 << "\"}\n";
        pe_source_release(src);
        pe_engine_destroy(engine);
        return (s1 == PE_OK && s2 == PE_OK && s3 == PE_OK && s4 == PE_OK &&
                dA == dA2 && dA == dA3 && dA != dB) ? 0 : 1;
    }

    if (mode == "cancel") {
        if (argc < 4) return 2;
        const char *source = argv[2], *look_dir = argv[3];
        const std::string source_sha = argv[4], id_sha = argv[5];
        pe_engine *engine = nullptr;
        pe_engine_create(config_json(look_dir).data(), config_json(look_dir).size(),
                         &engine);
        pe_source *src = nullptr;
        pe_source_open_local(engine, source, std::strlen(source), &src);
        std::string A = make_recipe(source_sha, id_sha, 1.0, 0.0, "asShot",
                                    "[1.9609375, 1.0, 1.51171875, 1.0]",
                                    "audit-identity-17");
        // 1) pre-cancelled token: must return PE_CANCELLED without rendering.
        pe_cancel_token *t1 = nullptr;
        pe_cancel_create(&t1);
        pe_cancel_request(t1);
        std::string d, e;
        pe_status s_pre = render_once(engine, src, A, d, e, t1);
        pe_cancel_release(t1);
        // 2) cancel while a real render is in flight (renders take seconds).
        pe_cancel_token *t2 = nullptr;
        pe_cancel_create(&t2);
        std::thread killer([t2] {
            std::this_thread::sleep_for(std::chrono::milliseconds(300));
            pe_cancel_request(t2);
        });
        pe_status s_mid = render_once(engine, src, A, d, e, t2);
        killer.join();
        pe_cancel_release(t2);
        // 3) a normal render after cancellation must succeed (no dirty state).
        pe_status s_post = render_once(engine, src, A, d, e);
        std::cout << "{\"mode\":\"cancel\",\"pre\":" << int(s_pre)
                  << ",\"mid\":" << int(s_mid) << ",\"post\":" << int(s_post)
                  << ",\"postDigest\":\"" << d << "\"}\n";
        pe_source_release(src);
        pe_engine_destroy(engine);
        // PE_CANCELLED == 10
        return (s_pre == PE_CANCELLED && s_mid == PE_CANCELLED &&
                s_post == PE_OK && !d.empty()) ? 0 : 1;
    }

    if (mode == "lifecycle") {
        if (argc < 5) return 2;
        const char *source = argv[2], *look_dir = argv[3];
        const std::string source_sha = argv[4], id_sha = argv[5];
        std::string A = make_recipe(source_sha, id_sha, 1.0, 0.0, "asShot",
                                    "[1.9609375, 1.0, 1.51171875, 1.0]",
                                    "audit-identity-17");
#ifdef _WIN32
        PROCESS_MEMORY_COUNTERS pmc{};
        SIZE_T before = 0, maxDelta = 0;
#endif
        int ok_rounds = 0;
        bool deterministic = true;
        std::string first_digest;
        const int kRounds = 8;
        for (int i = 0; i < kRounds; i++) {
            pe_engine *engine = nullptr;
            if (pe_engine_create(config_json(argv[3]).data(),
                                 config_json(argv[3]).size(), &engine) != PE_OK)
                break;
            pe_source *src = nullptr;
            if (pe_source_open_local(engine, source, std::strlen(source), &src) !=
                PE_OK) {
                pe_engine_destroy(engine);
                break;
            }
            std::string d, e;
            pe_status st = render_once(engine, src, A, d, e);
            if (st == PE_OK) {
                ok_rounds++;
                if (first_digest.empty()) first_digest = d;
                else if (d != first_digest) deterministic = false;
            }
            pe_source_release(src);
            pe_engine_destroy(engine);
#ifdef _WIN32
            if (GetProcessMemoryInfo(GetCurrentProcess(), &pmc, sizeof(pmc))) {
                SIZE_T cur = pmc.WorkingSetSize;
                if (before == 0) before = cur;
                if (cur > before && cur - before > maxDelta) maxDelta = cur - before;
            }
#endif
        }
        std::cout << "{\"mode\":\"lifecycle\",\"okRounds\":" << ok_rounds
                  << ",\"rounds\":" << kRounds
                  << ",\"deterministic\":" << (ok_rounds == kRounds && deterministic ? "true" : "false")
                  << ",\"workingSetGrowthBytes\":" << uint64_t(maxDelta) << "}\n";
        return ok_rounds == kRounds && deterministic ? 0 : 1;
    }

    if (mode == "abi") {
        // abi <source> <lookDir>
        const char *source = argv[2];
        const char *look_dir = argv[3];
        int checks = 0, passed = 0;
        pe_engine *engine = nullptr;
        std::string cfg = config_json(look_dir);
        checks++;
        if (pe_engine_create(cfg.data(), cfg.size(), &engine) == PE_OK &&
            engine != nullptr)
            passed++;
        // (a) span semantics: path buffer with trailing junk beyond path_bytes
        {
            std::string junk = std::string(source) + std::string("\\\\!!TRAILING_JUNK");
            pe_source *src = nullptr;
            checks++;
            pe_status st = pe_source_open_local(
                engine, junk.data(), std::strlen(source), &src);
            if (st == PE_OK && src) {
                passed++;
                pe_source_release(src);
            } else {
                std::cout << "{\"abiCheck\":\"span\",\"failed\":true,\"status\":"
                          << int(st) << "}\n";
            }
        }
        // (b) Unicode path via UTF-8 span
        {
            // The runner copies the fixture to a name containing Vietnamese
            // diacritics and passes the path here via argv (UTF-8).
            pe_source *src = nullptr;
            const char *uni = argv[4];
            checks++;
            if (pe_source_open_local(engine, uni, std::strlen(uni), &src) == PE_OK) {
                passed++;
                // Verify development as well as probing the Unicode path.
                bool source_ok = false, manifest_ok = false;
                const std::string source_hash = sha256_hex_of_file(source, &source_ok);
                const std::string manifest_hash = sha256_hex_of_file(
                    std::string(look_dir) + "/manifest.json", &manifest_ok);
                const std::string recipe = make_recipe(source_hash, manifest_hash,
                    0.0, 0.0, "asShot", "[1.9609375, 1.0, 1.51171875, 1.0]",
                    "audit-identity-17");
                std::string unicode_digest, original_digest, error;
                pe_source *original = nullptr;
                checks++;
                if (source_ok && manifest_ok &&
                    pe_source_open_local(engine, source, std::strlen(source), &original) == PE_OK &&
                    render_once(engine, src, recipe, unicode_digest, error) == PE_OK &&
                    render_once(engine, original, recipe, original_digest, error) == PE_OK &&
                    unicode_digest == original_digest && !unicode_digest.empty()) passed++;
                else std::cout << "{\"abiCheck\":\"unicode-render\",\"failed\":true}\n";
                pe_source_release(original);
                pe_source_release(src);
            } else {
                std::cout << "{\"abiCheck\":\"unicode\",\"failed\":true}\n";
            }
        }
        // (c) oversized recipe rejected with PE_RECIPE_INVALID, not OOM/crash
        {
            pe_source *src = nullptr;
            pe_source_open_local(engine, source, std::strlen(source), &src);
            std::string huge = "{\"pad\":\"" + std::string(3'000'000, 'x') + "\"}";
            pe_image *img = nullptr;
            pe_preview_options opt{};
            opt.struct_size = sizeof(opt);
            opt.abi_version = 1;
            opt.long_edge_px = 4096;
            opt.quality = 0;
            checks++;
            pe_status st = pe_render_preview(engine, src, huge.data(), huge.size(),
                                             &opt, nullptr, &img);
            if (st == PE_RECIPE_INVALID && img == nullptr) passed++;
            else std::cout << "{\"abiCheck\":\"oversized\",\"failed\":true,\"status\":"
                           << int(st) << "}\n";
            pe_source_release(src);
        }
        // (d) NULL out-handle pointer is invalid argument; destroy(NULL) safe
        checks++;
        if (pe_source_open_local(engine, nullptr, 0, nullptr) == PE_INVALID_ARGUMENT)
            passed++;
        pe_engine_destroy(engine);
        pe_engine_destroy(nullptr);
        pe_image_release(nullptr);
        pe_blob_release(nullptr);
        pe_cancel_release(nullptr);
        std::cout << "{\"mode\":\"abi\",\"passed\":" << passed
                  << ",\"checks\":" << checks << "}\n";
        return passed == checks ? 0 : 1;
    }

    std::fprintf(stderr, "unknown mode\n");
    return 2;
}

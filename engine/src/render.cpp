#include "render.h"
#include "cancel_flag.h"
#include "color.h"
#include "engine_limits.h"
#include "geometry.h"
#include "raw_adapter.h"
#include "file_util.h"
#include <nlohmann/json.hpp>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>

namespace pe {

namespace {

double now_ms() {
    using namespace std::chrono;
    return duration<double, std::milli>(steady_clock::now().time_since_epoch()).count();
}

// ---- TEST-ONLY audit checkpoint dumping (AUD plan section 5) ----
// Purely observational: writes the buffer exactly as it exists at that stage,
// packed RGB FP32 little-endian, plus a descriptor JSON. No math is changed.
void audit_dump(const char *dir, const char *stage, const RgbFloatBuffer &buf,
                const char *transfer, const char *reference_domain,
                const char *note) {
    if (!dir || !dir[0]) return;
    namespace fs = std::filesystem;
    std::error_code ec;
    fs::create_directories(fs::u8path(dir), ec);
    std::string path = std::string(dir) + "/" + stage + ".f32";
    FILE *f = utf8_fopen(path, "wb");
    if (!f) return;
    std::fwrite(buf.data.data(), sizeof(float), buf.data.size(), f);
    std::fclose(f);
    nlohmann::json d;
    d["stage"] = stage;
    d["width"] = buf.width;
    d["height"] = buf.height;
    d["channels"] = 3;
    d["channelOrder"] = "RGB";
    d["sampleType"] = "float32";
    d["byteOrder"] = "little";
    d["rowStrideBytes"] = uint64_t(buf.width) * 3 * 4;
    d["byteLength"] = uint64_t(buf.data.size()) * 4;
    d["alphaMode"] = "no-alpha-plane";
    d["transferFunction"] = transfer;
    d["primaries"] = "sRGB";
    d["whitePoint"] = "D65";
    d["rangePolicy"] = std::string(stage) == "B0_after_exposure" ? "linear exposure, not clamped at this checkpoint" : "bounded-[0,1]-full";
    d["referenceDomain"] = reference_domain;
    d["orientationState"] = "baked-normalized";
    d["note"] = note;
    path = std::string(dir) + "/" + stage + ".json";
    f = utf8_fopen(path, "wb");
    if (f) {
        std::string t = d.dump(2);
        std::fwrite(t.data(), 1, t.size(), f);
        std::fclose(f);
    }
}
} // namespace

Rgb8Buffer quantize_to_rgb8(const RgbFloatBuffer &encoded, CancelFlag *cancel) {
    cancellation_point(cancel, "quantize");
    Rgb8Buffer out;
    out.width = encoded.width;
    out.height = encoded.height;
    out.data.assign(size_t(encoded.width) * encoded.height * 3, 0);
    const size_t n = out.data.size();
    for_each_chunk(n, cancel, "quantize.chunk", [&](size_t begin, size_t end) {
        for (size_t i = begin; i < end; ++i) {
            float v = clamp01f(encoded.data[i]);
            // Round half up after scaling; deterministic and documented.
            out.data[i] = uint8_t(std::floor(v * 255.0f + 0.5f));
        }
    });
    return out;
}

bool render_to_pixels(const std::string &source_path, const RenderRequest &request,
                      const EngineLimits &limits, CancelFlag *cancel,
                      RenderOutput &output, StageTimings &timings, int &status_out,
                      std::string &error) {
    output = RenderOutput{};
    timings = StageTimings{};
    status_out = 12; // PE_INTERNAL
    error.clear();
    const double t0 = now_ms();

    try {
        cancellation_point(cancel, "render.begin");
        // 1) Decode + develop (P0). Decoder runs with the recipe multipliers, so
        //    asShot and custom take exactly the same code path.
        DevelopConfig cfg;
        cfg.collect_diagnostics = request.collect_diagnostics;
        cfg.audit_dir = request.audit_dir;
        cfg.audit_early_scale = request.audit_early_scale;
        for (int i = 0; i < 4; i++) cfg.wb_multipliers[i] = request.wb_multipliers[i];
        DevelopResult dev;
        std::unique_lock<std::mutex> cache_lock;
        PreviewCache *cache = request.audit_dir ? nullptr : request.preview_cache;
        if (cache) cache_lock = std::unique_lock<std::mutex>(cache->mutex);
        cancellation_point(cancel, "cache.lookup");
        if (cache && !request.upstream_key.empty() && cache->key == request.upstream_key) {
            const double copy_start = now_ms();
            dev = cache->developed;
            timings.cache_copy_ms = now_ms() - copy_start;
            timings.cache_hit = true;
            ++cache->hits;
        } else {
            if (cache) ++cache->misses;
            RawStatus raw_status;
            if (!raw_develop(source_path, cfg, limits, cancel, dev, raw_status, error)) {
                status_out = int(raw_status);
                return false;
            }
            timings.develop_ms = now_ms() - t0;
            timings.read_ms = dev.read_ms;
            timings.unpack_ms = dev.unpack_ms;
            timings.raw_process_ms = dev.process_ms;
            timings.raw_convert_ms = dev.convert_ms;
            const double t_or = now_ms();
            normalize_orientation(dev.buffer, dev.meta.flip, cancel);
            timings.orientation_ms = now_ms() - t_or;
            cancellation_point(cancel, "cache.publish");
            if (cache) {
                const double copy_start = now_ms();
                // Clear key before allocation: an exception cannot leave a valid
                // key pointing at partially replaced pixels.
                cache->key.clear();
                cache->developed = dev;
                cache->key = request.upstream_key;
                ++cache->develops;
                timings.cache_copy_ms = now_ms() - copy_start;
            }
        }
        if (cache_lock.owns_lock()) cache_lock.unlock();
        output.orientation_flip_applied = dev.meta.flip;
        output.cfa_filters = dev.meta.filters;
        auto dump = [&](const char *stage, const RgbFloatBuffer &buffer,
                        const char *transfer, const char *domain, const char *note) {
            const double begin = now_ms();
            audit_dump(request.audit_dir, stage, buffer, transfer, domain, note);
            timings.diagnostic_ms += now_ms() - begin;
        };
        dump("B0_base_develop", dev.buffer, "linear",
                   "baseline-linear-bounded-v0",
                   "post-develop post-orientation pre-exposure; already quantized to "
                   "16-bit and normalized at the decoder white level by the P0 "
                   "decoder (clipped there, not recoverable)");

        // 3) Exposure in linear space (multiply by 2^EV).
        const double t_ex = now_ms();
        if (request.exposure_ev != 0.0) {
            const float mul = float(std::pow(2.0, request.exposure_ev));
            for_each_chunk(dev.buffer.data.size(), cancel, "exposure.chunk", [&](size_t begin, size_t end) {
                for (size_t i = begin; i < end; ++i) {
                    dev.buffer.data[i] *= mul;
                }
            });
        }
        timings.exposure_ms = now_ms() - t_ex;

        dump("B0_after_exposure", dev.buffer, "linear", "baseline-linear-exposure", "post exposure before range clamp");

        // 4) Clamp to [0,1] and encode sRGB -> look domain.
        //    P0 limitation: integer pipeline already clipped at the white level;
        //    this clamp affects only values pushed above 1.0 by exposure.
        uint64_t exposure_clamped[3] = {0, 0, 0};
        const double t_diag = now_ms();
        if (request.collect_diagnostics) {
            for_each_chunk(dev.buffer.data.size(), cancel, "diagnostics.chunk", [&](size_t begin, size_t end) {
                for (size_t i = begin; i < end; ++i) exposure_clamped[i % 3] += dev.buffer.data[i] > 1.0f;
            });
        }
        timings.diagnostic_ms += now_ms() - t_diag;
        const double t_en = now_ms();
        const float *encoded_u16 = request.exposure_ev == 0.0 ? srgb_u16_encode_table().data() : nullptr;
        for_each_chunk(dev.buffer.data.size(), cancel, "transfer.chunk", [&](size_t begin, size_t end) {
            if (encoded_u16) {
                for (size_t i = begin; i < end; ++i) {
                    const uint32_t sample = uint32_t(dev.buffer.data[i] * 65535.0f + 0.5f);
                    dev.buffer.data[i] = encoded_u16[sample];
                }
                return;
            }
            for (size_t i = begin; i < end; ++i) {
                float &v = dev.buffer.data[i];
                v = clamp01f(v);
                v = srgb_encode_f(v);
            }
        });
        timings.transfer_encode_ms = now_ms() - t_en;
        dev.buffer.domain = Domain::LookEncoded;
        dump("B1_pre_look", dev.buffer, "srgb-encoded",
                   "srgb-display-v1", "post clamp+encode, pre creative look");
        // 5) Look + amount blend in the encoded domain. amount=0 bypasses.
        const double t_look = now_ms();
        if (request.look) cube3d_apply(*request.look, dev.buffer, request.look_amount, cancel);
        timings.look_ms = now_ms() - t_look;
        dump("B2_post_look", dev.buffer, "srgb-encoded",
                   "srgb-display-v1", "post LUT + amount blend (bypass when amount=0)");


        // 6) Decode sRGB back to linear for geometry.
        const double t_decode = now_ms();
        for_each_chunk(dev.buffer.data.size(), cancel, "decode.chunk", [&](size_t begin, size_t end) {
            for (size_t i = begin; i < end; ++i) {
                dev.buffer.data[i] = srgb_decode_f(dev.buffer.data[i]);
            }
        });
        timings.transfer_decode_ms = now_ms() - t_decode;
        dev.buffer.domain = Domain::LinearBounded;
        dump("B3_post_look_linear", dev.buffer, "linear",
                   "baseline-linear-bounded-v0",
                   "post look decode, pre geometry/resample");

        // 7) User geometry: crop (normalized coords in the oriented frame), then
        //    rotation/flip per pipeline v1 (crop first, rotate after).
        const double t_g = now_ms();
        if (!apply_crop(dev.buffer, request.crop_left, request.crop_top,
                        request.crop_width, request.crop_height, cancel)) {
            error = "crop resolves to an empty rectangle";
            status_out = 5; // PE_RECIPE_INVALID
            return false;
        }
        rotate_quarter_turns(dev.buffer, request.rotation_quarter_turns, cancel);
        if (request.flip_horizontal) mirror_horizontal(dev.buffer, cancel);
        timings.geometry_ms = now_ms() - t_g;

        // 8) Optional downscale (never upscale).
        const double t_r = now_ms();
        if (request.long_edge != 0) {
            if (!downscale_to_long_edge(dev.buffer, request.long_edge, cancel)) {
                error = "resize failed";
                status_out = 12;
                return false;
            }
        }
        timings.resize_ms = now_ms() - t_r;

        // 9) Final clamp + encode sRGB (pre-quantize output buffer).
        const double t_f = now_ms();
        for_each_chunk(dev.buffer.data.size(), cancel, "transfer.chunk", [&](size_t begin, size_t end) {
            for (size_t i = begin; i < end; ++i) {
                float &v = dev.buffer.data[i];
                v = clamp01f(v);
                v = srgb_encode_f(v);
            }
        });
        dev.buffer.domain = Domain::LookEncoded;
        timings.encode_prep_ms = now_ms() - t_f;
        dump("B4_output", dev.buffer, "srgb-encoded",
                   "srgb-display-v1", "post geometry/range/output encode, pre quantize/JPEG");

        cancellation_point(cancel, "render.ready");
        output.encoded = std::move(dev.buffer);
        output.out_width = output.encoded.width;
        output.out_height = output.encoded.height;
        for (int c = 0; c < 3; ++c) {
            output.develop_saturated_channels[c] = dev.meta.saturated_channels[c];
            output.exposure_clamped_channels[c] = exposure_clamped[c];
        }
        timings.total_ms = now_ms() - t0;
        if (cache) { std::lock_guard<std::mutex> lock(cache->mutex); cache->last_timings = timings; }
        status_out = 0;
        return true;
    } catch (const Cancelled &) {
        output = RenderOutput{};
        status_out = 10; // PE_CANCELLED
        error = "cancelled during pixel processing";
        return false;
    }
}

} // namespace pe

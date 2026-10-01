#include "raw_adapter.h"
#include "cancel_flag.h"
#include "engine_limits.h"
#include "file_util.h"
#include "sha256.h"
#include <libraw/libraw.h>
#include <cstdio>
#include <cmath>
#include <chrono>
#include <filesystem>
#include <memory>
#include <sstream>
#include "raw_audit.h"

namespace pe {

namespace {

double raw_now_ms() {
    return std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

int open_raw_utf8(LibRaw &raw, const std::string &path) {
#ifdef _WIN32
    const std::wstring wide = std::filesystem::u8path(path).wstring();
    return raw.open_file(wide.c_str());
#else
    return raw.open_file(path.c_str());
#endif
}

int cancel_progress(void *data, enum LibRaw_progress stage, int, int) {
    auto *cancel = static_cast<CancelFlag *>(data);
    // Never let C++ exceptions cross the library callback boundary.
    cancel->observe(LibRaw::strprogress(stage));
    return cancel->is_cancelled() ? 1 : 0;
}

RawStatus map_libraw_status(int err) {
    switch (err) {
    case LIBRAW_FILE_UNSUPPORTED:
        return RawUnsupportedSource;
    case LIBRAW_IO_ERROR:
        return RawSourceUnavailable;
    case LIBRAW_REQUEST_FOR_NONEXISTENT_IMAGE:
        return RawCorruptSource;
    case LIBRAW_UNSUFFICIENT_MEMORY:
        return RawOutOfMemory;
    case LIBRAW_CANCELLED_BY_CALLBACK:
        return RawCancelled;
    case LIBRAW_TOO_BIG:
        return RawResourceLimit;
    default:
        return RawCorruptSource;
    }
}

std::string sanitize(const char *s) { return s ? std::string(s) : std::string(); }

std::string classify_kind(const libraw_iparams_t &idata) {
    const bool is_dng = idata.dng_version != 0;
    const bool apple =
        sanitize(idata.normalized_make).find("Apple") != std::string::npos;
    if (is_dng && apple) return "proRaw"; // heuristic; ProRAW = Apple linear DNG
    if (is_dng && idata.filters == 0 && idata.colors == 3) return "linearDng";
    return "cameraRaw";
}

uint64_t file_size_of(FILE *f) {
#if defined(_WIN32)
    _fseeki64(f, 0, SEEK_END);
    return (uint64_t)_ftelli64(f);
#else
    fseeko(f, 0, SEEK_END);
    return (uint64_t)ftello(f);
#endif
}

} // namespace

bool resolve_as_shot_wb(const SourceProbe &probe, double (&multipliers)[4]) {
    double values[4];
    for (int i = 0; i < 4; ++i) values[i] = probe.cam_mul[i];
    // LibRaw uses the first green coefficient for a missing second green in
    // three-color data. Do not fabricate a fourth channel for four-color RAWs.
    if (probe.colors == 3 && values[3] == 0.0) values[3] = values[1];
    for (double value : values)
        if (!std::isfinite(value) || value <= 0.0) return false;
    const double green = values[1];
    for (double &value : values) {
        value /= green;
        if (!std::isfinite(value) || value <= 0.0) return false;
    }
    for (int i = 0; i < 4; ++i) multipliers[i] = values[i];
    return true;
}

bool raw_probe(const std::string &path, const EngineLimits &limits, SourceProbe &out,
               RawStatus &status, std::string &error) {
    status = RawInternal;
    error.clear();
    {
        FILE *f = utf8_fopen(path, "rb");
        if (!f) {
            status = RawSourceUnavailable;
            error = "cannot open source file";
            return false;
        }
        out.file_size = file_size_of(f);
        std::fclose(f);
        if (out.file_size > limits.max_input_bytes) {
            status = RawResourceLimit;
            error = "source file exceeds maxInputBytes limit";
            return false;
        }
    }
    bool hash_ok = false;
    out.sha256 = sha256_hex_of_file(path, &hash_ok);
    if (!hash_ok) {
        status = RawSourceUnavailable;
        error = "cannot hash source file";
        return false;
    }

    try {
        LibRaw raw;
        int ret = open_raw_utf8(raw, path);
        if (ret != LIBRAW_SUCCESS) {
            status = map_libraw_status(ret);
            error = "LibRaw open_file failed: " + std::string(LibRaw::strerror(ret));
            return false;
        }
        const libraw_iparams_t &id = raw.imgdata.idata;
        const libraw_image_sizes_t &sz = raw.imgdata.sizes;
        const libraw_colordata_t &col = raw.imgdata.color;
        const libraw_thumbnail_t &th = raw.imgdata.thumbnail;

        out.make = sanitize(id.make);
        out.model = sanitize(id.model);
        out.normalized_make = sanitize(id.normalized_make);
        out.normalized_model = sanitize(id.normalized_model);
        out.libraw_version = LibRaw::version();
        out.dng_version = id.dng_version;
        out.raw_count = id.raw_count;
        out.colors = id.colors;
        out.filters = id.filters;
        out.raw_width = sz.raw_width;
        out.raw_height = sz.raw_height;
        out.width = sz.width;
        out.height = sz.height;
        out.top_margin = sz.top_margin;
        out.left_margin = sz.left_margin;
        out.iwidth = sz.iwidth;
        out.iheight = sz.iheight;
        out.flip = sz.flip;
        for (int i = 0; i < 4; i++) {
            out.cam_mul[i] = col.cam_mul[i];
            out.pre_mul[i] = col.pre_mul[i];
        }
        out.black_level = col.black;
        out.white_level = col.maximum;
        out.has_thumbnail = th.tlength > 0;
        out.thumbnail_is_jpeg = th.tformat == LIBRAW_THUMBNAIL_JPEG;
        out.kind = classify_kind(id);
        raw.recycle();
    } catch (const std::bad_alloc &) {
        status = RawOutOfMemory;
        error = "out of memory while probing source";
        return false;
    } catch (...) {
        status = RawInternal;
        error = "unexpected exception while probing source";
        return false;
    }
    status = RawOK;
    return true;
}

bool raw_develop(const std::string &path, const DevelopConfig &config,
                 const EngineLimits &limits, CancelFlag *cancel, DevelopResult &out,
                 RawStatus &status, std::string &error) {
    status = RawInternal;
    error.clear();
    try {
        cancellation_point(cancel, "raw.open");
        const double read_start = raw_now_ms();
        AuditLibRaw raw;
        if (config.audit_early_scale != 1.0 && (!config.audit_dir || !config.audit_dir[0])) {
            error="test-only early scale requires audit directory";return false;
        }
        if (!std::isfinite(config.audit_early_scale) || config.audit_early_scale <= 0 || config.audit_early_scale > 1) {
            error="invalid audit early scale";return false;
        }
        RawAuditContext audit{config.audit_dir ? config.audit_dir : "", config.audit_early_scale};
        RawAuditScope audit_scope(config.audit_dir ? &audit : nullptr);
        if(config.audit_dir) raw.enable_audit();
        if (cancel) raw.set_progress_handler(cancel_progress, cancel);
        int ret = open_raw_utf8(raw, path);
        if (ret != LIBRAW_SUCCESS) {
            status = map_libraw_status(ret);
            error = "LibRaw open_file failed: " + std::string(LibRaw::strerror(ret));
            return false;
        }
        const libraw_image_sizes_t &sz = raw.imgdata.sizes;
        const libraw_iparams_t &id = raw.imgdata.idata;
        const uint64_t pixels = uint64_t(sz.raw_width) * sz.raw_height;
        if (pixels == 0 || id.colors == 0) {
            status = RawCorruptSource;
            error = "decoder reported empty image";
            return false;
        }
        if (pixels > limits.max_pixels) {
            status = RawResourceLimit;
            error = "source pixel count exceeds maxPixels limit";
            return false;
        }
        uint64_t decoded_bytes = 0;
        if (!checked_buffer_bytes(sz.width, sz.height, 4, sizeof(uint16_t),
                                  decoded_bytes) ||
            decoded_bytes > limits.max_decoded_bytes) {
            status = RawResourceLimit;
            error = "decoded buffer exceeds maxDecodedBytes limit";
            return false;
        }
        if (cancel && cancel->is_cancelled()) {
            status = RawCancelled;
            error = "cancelled before decode";
            return false;
        }

        out.read_ms = raw_now_ms() - read_start;
        const double unpack_start = raw_now_ms();
        ret = raw.unpack();
        out.unpack_ms = raw_now_ms() - unpack_start;
        if (ret != LIBRAW_SUCCESS) {
            status = map_libraw_status(ret);
            error = "LibRaw unpack failed: " + std::string(LibRaw::strerror(ret));
            return false;
        }
        if (cancel && cancel->is_cancelled()) {
            status = RawCancelled;
            error = "cancelled after unpack";
            return false;
        }

        // Pinned P0 decoder configuration (docs/03 section 3.1). Every choice
        // is explicit; the same set is echoed by raw_developer_config_echo_json
        // so run reports can be compared across builds.
        // dcraw_process/raw2image overwrites sizes.flip with user_flip. Keep the
        // source orientation before disabling decoder-owned rotation.
        const uint32_t source_flip = raw.imgdata.sizes.flip;
        audit.source_flip = source_flip;
        raw.imgdata.params.use_camera_wb = 0;
        raw.imgdata.params.use_auto_wb = 0;
        raw.imgdata.params.user_mul[0] = float(config.wb_multipliers[0]);
        raw.imgdata.params.user_mul[1] = float(config.wb_multipliers[1]);
        raw.imgdata.params.user_mul[2] = float(config.wb_multipliers[2]);
        raw.imgdata.params.user_mul[3] = float(config.wb_multipliers[3]);
        raw.imgdata.params.no_auto_bright = 1;
        raw.imgdata.params.output_bps = 16;
        raw.imgdata.params.output_color = 1; // sRGB primaries
        raw.imgdata.params.gamm[0] = 1.0;    // linear transfer out of the decoder
        raw.imgdata.params.gamm[1] = 1.0;
        raw.imgdata.params.user_flip = 0; // engine normalizes orientation itself
        raw.imgdata.params.use_fuji_rotate = 0;
        raw.imgdata.params.user_qual = 3; // requested quality; effective algorithm depends on CFA/dispatch
        raw.imgdata.params.med_passes = 0;
        raw.imgdata.params.highlight = 0; // clip at white level; no recovery (P0)
        raw.imgdata.params.half_size = 0;
        raw.imgdata.params.four_color_rgb = 0;
        raw.imgdata.params.adjust_maximum_thr = 0.0f; // keep file white level
        raw.imgdata.params.exp_correc = 0;            // no decoder exposure step

        const double process_start = raw_now_ms();
        ret = raw.dcraw_process();
        out.process_ms = raw_now_ms() - process_start;
        if(audit.failed) { status=RawIo;error="raw checkpoint write failed";return false; }
        const double convert_start = raw_now_ms();
        if (ret != LIBRAW_SUCCESS) {
            status = map_libraw_status(ret);
            error =
                "LibRaw dcraw_process failed: " + std::string(LibRaw::strerror(ret));
            return false;
        }
        if (cancel && cancel->is_cancelled()) {
            status = RawCancelled;
            error = "cancelled after develop";
            return false;
        }

        const libraw_colordata_t &col = raw.imgdata.color;
        uint32_t w = raw.imgdata.sizes.iwidth;
        uint32_t h = raw.imgdata.sizes.iheight;
        if (w == 0 || h == 0) {
            status = RawCorruptSource;
            error = "decoder produced an empty frame";
            return false;
        }
        uint64_t out_bytes = 0;
        if (!checked_buffer_bytes(w, h, 3, sizeof(float), out_bytes) ||
            out_bytes > limits.max_decoded_bytes) {
            status = RawResourceLimit;
            error = "working buffer exceeds maxDecodedBytes limit";
            return false;
        }

        out.buffer.width = w;
        out.buffer.height = h;
        out.buffer.domain = Domain::LinearBounded;
        out.buffer.data.assign(size_t(w) * h * 3, 0.0f);
        const ushort(*image)[4] = raw.imgdata.image;
        float *dst = out.buffer.data.data();
        const size_t count = size_t(w) * h;
        for (int c = 0; c < 3; ++c) out.meta.saturated_channels[c] = 0;
        for_each_chunk(count, cancel, "raw.convert.chunk", [&](size_t begin, size_t end) {
            for (size_t i = begin; i < end; ++i) {
                dst[i*3] = float(image[i][0]) * (1.0f / 65535.0f);
                dst[i*3+1] = float(image[i][1]) * (1.0f / 65535.0f);
                dst[i*3+2] = float(image[i][2]) * (1.0f / 65535.0f);
            }
            if (config.collect_diagnostics) {
                for (size_t i = begin; i < end; ++i) for (int c = 0; c < 3; ++c)
                out.meta.saturated_channels[c] += image[i][c] == 65535;
            }
        });

        out.convert_ms = raw_now_ms() - convert_start;
        out.meta.make = sanitize(id.make);
        out.meta.model = sanitize(id.model);
        out.meta.libraw_version = LibRaw::version();
        out.meta.width = w;
        out.meta.height = h;
        out.meta.flip = source_flip;
        out.meta.black_level = col.black;
        out.meta.white_level = col.maximum;
        for (int i = 0; i < 4; i++) out.meta.cam_mul[i] = col.cam_mul[i];
        out.meta.filters = id.filters;
        out.meta.colors = id.colors;
        raw.recycle();
    } catch (const Cancelled &) {
        status = RawCancelled;
        error = "cancelled during RAW conversion";
        return false;
    } catch (const std::bad_alloc &) {
        status = RawOutOfMemory;
        error = "out of memory while developing source";
        return false;
    } catch (...) {
        status = RawInternal;
        error = "unexpected exception while developing source";
        return false;
    }
    status = RawOK;
    return true;
}

std::string raw_developer_config_echo_json() {
    std::ostringstream os;
    os << "{"
          "\"use_camera_wb\":false,"
          "\"use_auto_wb\":false,"
          "\"wb_source\":\"recipe user_mul (R,G,B,G2 order)\","
          "\"no_auto_bright\":true,"
          "\"output_bps\":16,"
          "\"output_color\":1,\"output_color_name\":\"sRGB\","
          "\"gamma\":[1.0,1.0],\"gamma_name\":\"linear\","
          "\"user_flip\":0,\"orientation_owner\":\"engine\","
          "\"use_fuji_rotate\":false,"
          "\"requested_quality\":3,\"effective_demosaic\":\"UNKNOWN (not instrumented)\","
          "\"med_passes\":0,"
          "\"highlight\":0,\"highlight_note\":\"clip at white level; no recovery\","
          "\"half_size\":false,"
          "\"four_color_rgb\":false,"
          "\"adjust_maximum_thr\":0.0,\"note\":\"file white level kept\","
          "\"exp_correc\":false"
          "}";
    return os.str();
}

} // namespace pe

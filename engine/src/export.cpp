#include "engine_impl.h"
#include "cancel_flag.h"
#include "file_util.h"
#include "icc_srgb.h"
#include "jpeg_encoder.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace pe {

int export_rendered_jpeg(const RenderOutput &output, const RecipeModel &model,
                         const std::string &path, CancelFlag *cancel,
                         std::string &error) {
    if (path_exists(path)) {
        error = "staging path already exists; refusing to overwrite";
        return kPE_IO;
    }
    try {
        cancellation_point(cancel, "export.quantize");
        Rgb8Buffer rgb8 = quantize_to_rgb8(output.encoded, cancel);
        std::vector<uint8_t> icc;
        if (!build_srgb_icc_profile(icc)) {
            error = "ICC profile build failed";
            return kPE_INTERNAL;
        }
        JpegEncodeOptions opts;
        opts.quality = model.quality;
        opts.subsampling_444 = model.subsampling == "444";
        opts.icc = &icc;
        opts.software_tag = "photo-engine G1 (baseline-v0 0.1.0)";
        std::vector<uint8_t> jpeg_bytes;
        cancellation_point(cancel, "export.jpeg");
        if (!encode_jpeg(rgb8, opts, jpeg_bytes, error, cancel)) {
            return cancel && cancel->is_cancelled() ? kPE_CANCELLED : kPE_IO;
        }
        cancellation_point(cancel, "export.write");
        FILE *f = utf8_fopen_exclusive(path);
        if (!f) {
            error = "cannot exclusively create staging path for write";
            return kPE_IO;
        }
        bool ok = true;
        bool cancelled = false;
        // No throwing operations between fopen and fclose. Write in chunks so
        // cancellation removes our partial staging file through the same path.
        size_t requested_bytes = jpeg_bytes.size();
#ifdef PHOTO_ENGINE_AUDIT_FAULTS
        const char *fault = std::getenv("PE_AUDIT_FAULT");
        if (fault && std::strcmp(fault, "write_short") == 0 && requested_bytes)
            --requested_bytes;
        if (fault && std::strcmp(fault, "write_error") == 0) requested_bytes = 0;
#endif
        size_t written = 0;
        while (written < requested_bytes) {
            if (cancel && cancel->is_cancelled()) { cancelled = true; break; }
            const size_t remaining = requested_bytes - written;
            const size_t chunk = remaining < (1u << 20) ? remaining : (1u << 20);
            const size_t n = std::fwrite(jpeg_bytes.data() + written, 1, chunk, f);
            written += n;
            if (n != chunk) { ok = false; break; }
        }
        if (written != jpeg_bytes.size()) ok = false;
        if (std::fflush(f) != 0) ok = false;
#ifdef PHOTO_ENGINE_AUDIT_FAULTS
        if (fault && std::strcmp(fault, "flush_error") == 0) ok = false;
#endif
        if (std::fclose(f) != 0) ok = false;
        if (cancel) cancel->observe("export.write.complete");
        if (cancel && cancel->is_cancelled()) cancelled = true;
        if (!ok || cancelled) {
            utf8_remove(path);
            error = cancelled ? "cancelled while writing staging path" : "failed to write/flush/close staging path";
            return cancelled ? kPE_CANCELLED : kPE_IO;
        }
        return kPE_OK;
    } catch (const Cancelled &) {
        error = "cancelled during export";
        return kPE_CANCELLED;
    }
}

} // namespace pe

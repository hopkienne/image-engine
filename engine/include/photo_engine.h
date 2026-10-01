#ifndef PHOTO_ENGINE_H
#define PHOTO_ENGINE_H
/*
 * Shared Photo Engine - C ABI (G1 implementation).
 *
 * Derived from the RFC v0.1 draft header in raw_photo_app_rnd_v0.1/include/photo_engine.h
 * (Proposed). Two documented, review-pending amendments are marked with [PE-G1-NOTE]
 * below; everything else is byte-compatible with the draft.
 */
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct pe_engine pe_engine;
typedef struct pe_source pe_source;
typedef struct pe_cancel_token pe_cancel_token;
typedef struct pe_image pe_image;
typedef struct pe_blob pe_blob;

typedef enum pe_status {
    PE_OK = 0, PE_UNSUPPORTED_SOURCE = 1, PE_CORRUPT_SOURCE = 2,
    PE_SOURCE_UNAVAILABLE = 3, PE_COLOR_PROFILE_MISSING = 4,
    PE_RECIPE_INVALID = 5, PE_ASSET_MISMATCH = 6,
    PE_PIPELINE_UNAVAILABLE = 7, PE_RESOURCE_LIMIT = 8,
    PE_OUT_OF_MEMORY = 9, PE_CANCELLED = 10, PE_IO = 11,
    PE_INTERNAL = 12, PE_INVALID_ARGUMENT = 13
} pe_status;

typedef struct pe_preview_options {
    uint32_t struct_size;
    uint32_t abi_version; /* v1 proposed */
    uint32_t long_edge_px; /* required > 0; admission policy supplies max */
    uint32_t quality; /* 0=final/reference, 1=fast (requires defined semantics) */
    uint64_t request_generation;
} pe_preview_options;

typedef struct pe_image_info {
    uint32_t struct_size;
    uint32_t abi_version;
    uint32_t width;
    uint32_t height;
    uint64_t row_stride_bytes;
    uint64_t byte_length;
    /* [PE-G1-NOTE] amendment pending review (docs/rnd/G0_SCOPE_DRAFT.md section 5):
     * 1 = linear SDR sRGB D65, alpha=1 (as in the draft; used for diagnostics),
     * 2 = srgb-display-v1 (sRGB-encoded), SDR sRGB primaries D65, FP32, alpha=1.
     * pe_render_preview returns contract 2 because the engine output is the
     * display-ready encoded image, matching the pipeline in docs/03 section 3.4. */
    uint32_t pixel_format; /* v1: 1 = interleaved native-endian RGBA FP32 */
    uint32_t color_contract; /* 1 = linear, 2 = srgb-display-v1 encoded (see above) */
    uint32_t orientation_state; /* v1: 1 = baked/normalized */
    uint32_t reserved;
    uint64_t request_generation;
    const void *pixels; /* borrowed; valid until pe_image_release */
} pe_image_info;

/* Blocking calls must run on an adapter worker, never on the UI thread.
 * No exception may cross this ABI. Inputs are UTF-8 spans, not assumed NUL-terminated.
 * Implementation sets every out-handle to NULL before work. Failure does not transfer ownership.
 * Release/destroy accept NULL. Destroy engine only after all child handles/jobs are released.
 * Calls on a given source must be serialized in v0, except pe_cancel_request(token).
 */
pe_status pe_engine_create(const char *config_json, size_t config_bytes,
                           pe_engine **out_engine);
void pe_engine_destroy(pe_engine *engine);
pe_status pe_source_open_local(pe_engine *engine, const char *path_utf8,
                                size_t path_bytes, pe_source **out_source);
pe_status pe_source_info_json(pe_source *source, pe_blob **out_json);
void pe_source_release(pe_source *source);
pe_status pe_cancel_create(pe_cancel_token **out_token);
void pe_cancel_request(pe_cancel_token *token); /* thread-safe; one-way */
void pe_cancel_release(pe_cancel_token *token); /* after job returns */
pe_status pe_render_preview(pe_engine *engine, pe_source *source,
                            const char *recipe_json, size_t recipe_bytes,
                            const pe_preview_options *options,
                            pe_cancel_token *cancel, pe_image **out_image);
pe_status pe_image_describe(const pe_image *image, pe_image_info *out_info);
void pe_image_release(pe_image *image);
/* Writes a complete JPEG to a nonexisting application-local staging path.
 * Does not publish to Photos/MediaStore/provider and never overwrites a source.
 * On cancellation/failure removes its own partial output, without deleting other files.
 */
pe_status pe_export_jpeg(pe_engine *engine, pe_source *source,
                         const char *recipe_json, size_t recipe_bytes,
                         const char *staging_path_utf8, size_t staging_path_bytes,
                         pe_cancel_token *cancel);
/* Caller initializes struct_size/abi_version before pe_image_describe.
 * Unsupported size/version fails; pe_last_error_json returns a copy of the
 * most recent error on the calling thread (redacted by default).
 */
pe_status pe_last_error_json(pe_engine *engine, pe_blob **out_json);
const uint8_t *pe_blob_data(const pe_blob *blob, size_t *out_bytes);
void pe_blob_release(pe_blob *blob);
#ifdef __cplusplus
}
#endif
#endif

#include "jpeg_encoder.h"
#include "cancel_flag.h"
#include <csetjmp>
#include <cstdio>
#include <cstring>
#include <jpeglib.h>
#include <jerror.h>
#include <memory>
#include <vector>

namespace pe {

namespace {

struct JpegErrorMgr {
    jpeg_error_mgr pub;
    jmp_buf setjmp_buffer;
    char message[JMSG_LENGTH_MAX];
};

void jpeg_error_exit(j_common_ptr cinfo) {
    JpegErrorMgr *err = reinterpret_cast<JpegErrorMgr *>(cinfo->err);
    (*cinfo->err->format_message)(cinfo, err->message);
    std::longjmp(err->setjmp_buffer, 1);
}

void jpeg_emit_message_stub(j_common_ptr, int) {}

// Keep mutable compressor/destination state on the heap: setjmp/longjmp must
// not skip C++ object construction or leave changed stack objects indeterminate.
// Owning the destination also releases growing buffers on errors/cancellation.
struct MemoryDestination {
    jpeg_destination_mgr pub{};
    std::vector<uint8_t> bytes;
};

void memory_init(j_compress_ptr info) {
    auto *dest = static_cast<MemoryDestination *>(info->client_data);
    dest->pub.next_output_byte = dest->bytes.data();
    dest->pub.free_in_buffer = dest->bytes.size();
}

boolean memory_grow(j_compress_ptr info) {
    auto *dest = static_cast<MemoryDestination *>(info->client_data);
    const size_t old_size = dest->bytes.size();
    bool failed = old_size > dest->bytes.max_size() / 2;
    if (!failed) {
        try { dest->bytes.resize(old_size * 2); }
        catch (...) { failed = true; }
    }
    // Exit the C++ catch scope before invoking libjpeg's longjmp error handler.
    if (failed) ERREXIT1(info, JERR_OUT_OF_MEMORY, 12);
    dest->pub.next_output_byte = dest->bytes.data() + old_size;
    dest->pub.free_in_buffer = old_size;
    return TRUE;
}

void memory_finish(j_compress_ptr info) {
    auto *dest = static_cast<MemoryDestination *>(info->client_data);
    dest->bytes.resize(dest->bytes.size() - dest->pub.free_in_buffer);
}

struct JpegState {
    jpeg_compress_struct info{};
    JpegErrorMgr error{};
    MemoryDestination dest;
    bool created = false;
    ~JpegState() { if (created) jpeg_destroy_compress(&info); }
};

void put_u16(std::vector<uint8_t> &v, uint16_t x) {
    v.push_back(uint8_t(x & 0xFF));
    v.push_back(uint8_t(x >> 8));
}

void put_u32(std::vector<uint8_t> &v, uint32_t x) {
    v.push_back(uint8_t(x & 0xFF));
    v.push_back(uint8_t((x >> 8) & 0xFF));
    v.push_back(uint8_t((x >> 16) & 0xFF));
    v.push_back(uint8_t((x >> 24) & 0xFF));
}

// Minimal baseline EXIF APP1 payload (little-endian TIFF, IFD0 only):
// Orientation = upright, ColorSpace = sRGB, Software = engine tag.
// No GPS, no camera-identifying metadata (docs/09 section 9.3 policy).
std::vector<uint8_t> make_exif_app1(const std::string &software) {
    std::vector<uint8_t> tiff;
    tiff.push_back('I');
    tiff.push_back('I');
    put_u16(tiff, 42);
    put_u32(tiff, 8); // IFD0 offset
    const uint16_t entry_count = 3;
    const size_t ifd_start = tiff.size();
    put_u16(tiff, entry_count);
    const size_t data_area_offset = ifd_start + 2 + size_t(entry_count) * 12 + 4;
    std::vector<uint8_t> sw(software.begin(), software.end());
    sw.push_back(0);
    if (sw.size() % 2 != 0) sw.push_back(0);
    const uint32_t sw_offset = uint32_t(data_area_offset);

    struct Entry {
        uint16_t tag, type;
        uint32_t count;
        uint32_t value;
    };
    Entry entries[3] = {
        {0x0112, 3, 1, 1},           // Orientation SHORT 1 = upright
        {0xA001, 3, 1, 1},           // ColorSpace SHORT 1 = sRGB
        {0x0131, 2, uint32_t(sw.size()), sw_offset}, // Software ASCII
    };
    for (auto &e : entries) {
        put_u16(tiff, e.tag);
        put_u16(tiff, e.type);
        put_u32(tiff, e.count);
        if (e.type == 3 && e.count == 1) {
            put_u16(tiff, uint16_t(e.value)); // SHORT left-justified in field
            put_u16(tiff, 0);
        } else {
            put_u32(tiff, e.value);
        }
    }
    put_u32(tiff, 0); // next IFD
    tiff.insert(tiff.end(), sw.begin(), sw.end());

    std::vector<uint8_t> app1;
    app1.push_back('E');
    app1.push_back('x');
    app1.push_back('i');
    app1.push_back('f');
    app1.push_back(0);
    app1.push_back(0);
    app1.insert(app1.end(), tiff.begin(), tiff.end());
    return app1;
}

} // namespace

bool encode_jpeg(const Rgb8Buffer &buffer, const JpegEncodeOptions &options,
                 std::vector<uint8_t> &out_bytes, std::string &error, CancelFlag *cancel) {
    out_bytes.clear();
    if (cancel && cancel->is_cancelled()) { error = "cancelled before JPEG encode"; return false; }
    if (buffer.empty()) {
        error = "cannot encode an empty image";
        return false;
    }
    if (options.quality < 1 || options.quality > 100) {
        error = "JPEG quality must be within [1,100]";
        return false;
    }

    // All C++ allocations with automatic lifetime precede setjmp.
    // ICC APP2 payload per the ICC embedding spec: "ICC_PROFILE\0" + chunk
    // number + chunk count + profile bytes. The built-in profile is ~1.5 KB,
    // one chunk always suffices (segment payload limit is 65533 bytes);
    // larger profiles are refused rather than written non-conformantly.
    std::vector<uint8_t> icc_marker;
    if (options.icc && !options.icc->empty()) {
        const size_t kMaxProfileChunk = 65533 - 14;
        if (options.icc->size() > kMaxProfileChunk) {
            error = "ICC profile too large for a single APP2 segment";
            return false;
        }
        icc_marker.reserve(options.icc->size() + 14);
        icc_marker.insert(icc_marker.end(), {'I', 'C', 'C', '_', 'P', 'R', 'O', 'F',
                                             'I', 'L', 'E', 0x00, 0x01, 0x01});
        icc_marker.insert(icc_marker.end(), options.icc->begin(), options.icc->end());
    }
    std::vector<uint8_t> exif = make_exif_app1(options.software_tag);

    const size_t row_bytes = size_t(buffer.width) * 3;
    std::vector<JSAMPLE> row(row_bytes);
    auto state = std::make_unique<JpegState>();
    auto &cinfo = state->info;
    auto &jerr = state->error;
    state->dest.bytes.resize(4096);
    state->dest.pub.init_destination = memory_init;
    state->dest.pub.empty_output_buffer = memory_grow;
    state->dest.pub.term_destination = memory_finish;
    cinfo.err = jpeg_std_error(&jerr.pub);
    jerr.pub.error_exit = jpeg_error_exit;
    jerr.pub.emit_message = jpeg_emit_message_stub;
    if (setjmp(jerr.setjmp_buffer)) {
        error = std::string("libjpeg error: ") + jerr.message;
        return false;
    }
    state->created = true;
    jpeg_create_compress(&cinfo);
    cinfo.client_data = &state->dest;
    cinfo.dest = &state->dest.pub;
    cinfo.image_width = buffer.width;
    cinfo.image_height = buffer.height;
    cinfo.input_components = 3;
    cinfo.in_color_space = JCS_RGB;
    jpeg_set_defaults(&cinfo);
    jpeg_set_quality(&cinfo, options.quality, TRUE);
    jpeg_set_colorspace(&cinfo, JCS_YCbCr);
    if (options.subsampling_444) {
        cinfo.comp_info[0].h_samp_factor = 1;
        cinfo.comp_info[0].v_samp_factor = 1;
    } else {
        cinfo.comp_info[0].h_samp_factor = 2;
        cinfo.comp_info[0].v_samp_factor = 2;
    }
    cinfo.write_JFIF_header = TRUE; // APP0 JFIF v1.01
    cinfo.write_Adobe_marker = FALSE;

    jpeg_start_compress(&cinfo, TRUE);
    if (!icc_marker.empty()) {
        jpeg_write_marker(&cinfo, JPEG_APP0 + 2, icc_marker.data(),
                          uint32_t(icc_marker.size()));
    }
    jpeg_write_marker(&cinfo, JPEG_APP0 + 1, exif.data(), uint32_t(exif.size()));

    while (cinfo.next_scanline < cinfo.image_height) {
        if (cancel) cancel->observe("jpeg.row");
        if (cancel && cancel->is_cancelled()) {
            error = "cancelled during JPEG encode";
            return false;
        }
        const uint8_t *src =
            buffer.data.data() + size_t(cinfo.next_scanline) * row_bytes;
        std::memcpy(row.data(), src, row_bytes);
        JSAMPROW rp = row.data();
        jpeg_write_scanlines(&cinfo, &rp, 1);
    }
    jpeg_finish_compress(&cinfo);
    out_bytes = std::move(state->dest.bytes);
    return true;
}

} // namespace pe

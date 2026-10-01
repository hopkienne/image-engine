#include "buffer.h"
#include "color.h"
#include <limits>

namespace pe {

BufferDescriptor BufferDescriptor::make(Domain domain, uint32_t w, uint32_t h,
                                        bool orientation_baked) {
    BufferDescriptor d;
    d.width = w;
    d.height = h;
    d.orientation_state = orientation_baked ? "baked-normalized" : "decoder-pending";
    if (domain == Domain::LookEncoded) {
        d.transfer_function = "srgb-encoded";
        d.reference_domain = kDomainLook;
    } else {
        d.transfer_function = "linear";
        d.reference_domain = kDomainLinearBounded;
    }
    d.row_stride_bytes = uint64_t(w) * 3 * sizeof(float);
    return d;
}

BufferDescriptor RgbFloatBuffer::descriptor() const {
    return BufferDescriptor::make(domain, width, height,
                                  /*orientation_baked=*/true);
}

bool checked_buffer_bytes(uint64_t w, uint64_t h, uint64_t channels,
                          uint64_t elem_size, uint64_t &out_bytes) {
    if (w == 0 || h == 0 || channels == 0 || elem_size == 0) return false;
    const uint64_t max = std::numeric_limits<uint64_t>::max();
    if (w > max / h) return false;
    uint64_t pixels = w * h;
    if (pixels > max / channels) return false;
    uint64_t values = pixels * channels;
    if (values > max / elem_size) return false;
    out_bytes = values * elem_size;
    return true;
}

} // namespace pe

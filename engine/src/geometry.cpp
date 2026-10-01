#include "geometry.h"
#include "cancel_flag.h"
#include <algorithm>
#include <cmath>

namespace pe {

namespace {

template <typename F>
void remap(RgbFloatBuffer &buf, uint32_t new_w, uint32_t new_h, F fetch, CancelFlag *cancel) {
    std::vector<float> out(size_t(new_w) * new_h * 3);
    for (uint32_t y = 0; y < new_h; y++) {
        cancellation_point(cancel, "geometry.remap.row");
        for (uint32_t x = 0; x < new_w; x++) {
            const size_t di = (size_t(y) * new_w + x) * 3;
            fetch(x, y, out.data() + di);
        }
    }
    buf.width = new_w;
    buf.height = new_h;
    buf.data = std::move(out);
}

} // namespace

void normalize_orientation(RgbFloatBuffer &buffer, uint32_t flip, CancelFlag *cancel) {
    cancellation_point(cancel, "orientation");
    if (flip == 0) return;
    // dcraw flip_index mirrors in source axes after swapping inverse-map
    // coordinates. For a forward transpose, mirror axes must therefore swap.
    const bool mirror_y = (flip & 4) ? (flip & 1) : (flip & 2);
    const bool mirror_x = (flip & 4) ? (flip & 2) : (flip & 1);
    if (flip & 4) {
        // transpose: (x,y) -> (y,x)
        const uint32_t w = buffer.width, h = buffer.height;
        remap(buffer, h, w, [&](uint32_t x, uint32_t y, float *dst) {
            const size_t si = (size_t(x) * w + y) * 3; // src pixel (y, x)
            dst[0] = buffer.data[si];
            dst[1] = buffer.data[si + 1];
            dst[2] = buffer.data[si + 2];
        }, cancel);
    }
    if (mirror_y) {
        const size_t row = size_t(buffer.width) * 3;
        for (uint32_t y = 0; y < buffer.height / 2; ++y) {
            cancellation_point(cancel, "geometry.mirror.row");
            std::swap_ranges(buffer.data.begin() + size_t(y) * row,
                             buffer.data.begin() + size_t(y + 1) * row,
                             buffer.data.begin() + size_t(buffer.height - 1 - y) * row);
        }
    }
    if (mirror_x) {
        for (uint32_t y = 0; y < buffer.height; ++y) {
            cancellation_point(cancel, "geometry.mirror.row");
            for (uint32_t x = 0; x < buffer.width / 2; ++x) {
                const size_t a = (size_t(y) * buffer.width + x) * 3;
                const size_t b = (size_t(y) * buffer.width + buffer.width - 1 - x) * 3;
                for (int c = 0; c < 3; ++c) std::swap(buffer.data[a+c], buffer.data[b+c]);
            }
        }
    }
}

bool apply_crop(RgbFloatBuffer &buffer, double left, double top, double width,
                double height, CancelFlag *cancel) {
    cancellation_point(cancel, "geometry.crop");
    if (buffer.empty()) return false;
    // Deterministic mapping from normalized coords to pixels.
    int64_t px = int64_t(std::llround(left * double(buffer.width)));
    int64_t py = int64_t(std::llround(top * double(buffer.height)));
    int64_t pw = int64_t(std::llround(width * double(buffer.width)));
    int64_t ph = int64_t(std::llround(height * double(buffer.height)));
    if (pw < 1) pw = 1;
    if (ph < 1) ph = 1;
    if (px < 0) px = 0;
    if (py < 0) py = 0;
    if (px + pw > buffer.width) pw = buffer.width - px;
    if (py + ph > buffer.height) ph = buffer.height - py;
    if (pw < 1 || ph < 1) return false;

    // Full-frame crop preserves the existing allocation and pixel bits.
    if (px == 0 && py == 0 && pw == buffer.width && ph == buffer.height) return true;
    std::vector<float> out(size_t(pw) * ph * 3);
    for (int64_t y = 0; y < ph; y++) {
        cancellation_point(cancel, "geometry.crop.row");
        const size_t src_row = size_t(py + y) * buffer.width;
        std::copy_n(buffer.data.begin() + (src_row + px) * 3, size_t(pw) * 3,
                    out.begin() + (size_t(y) * pw) * 3);
    }
    buffer.width = uint32_t(pw);
    buffer.height = uint32_t(ph);
    buffer.data = std::move(out);
    return true;
}

void rotate_quarter_turns(RgbFloatBuffer &buffer, int quarter_turns, CancelFlag *cancel) {
    cancellation_point(cancel, "geometry.rotate");
    quarter_turns %= 4;
    if (quarter_turns == 0) return;
    const uint32_t w = buffer.width, h = buffer.height;
    if (quarter_turns == 2) {
        remap(buffer, w, h, [&](uint32_t x, uint32_t y, float *dst) {
            const size_t si = (size_t(h - 1 - y) * w + (w - 1 - x)) * 3;
            dst[0] = buffer.data[si];
            dst[1] = buffer.data[si + 1];
            dst[2] = buffer.data[si + 2];
        }, cancel);
        return;
    }
    const uint32_t nw = h, nh = w;
    if (quarter_turns == 1) {
        // rotate 90 degrees clockwise: new(x', y') = old(y', h-1-x')
        remap(buffer, nw, nh, [&](uint32_t x, uint32_t y, float *dst) {
            const size_t si = (size_t(h - 1 - x) * w + y) * 3;
            dst[0] = buffer.data[si];
            dst[1] = buffer.data[si + 1];
            dst[2] = buffer.data[si + 2];
        }, cancel);
    } else if (quarter_turns == 3) {
        // rotate 270 degrees clockwise (90 CCW): new(x', y') = old(w-1-y', x')
        remap(buffer, nw, nh, [&](uint32_t x, uint32_t y, float *dst) {
            const size_t si = (size_t(x) * w + (w - 1 - y)) * 3;
            dst[0] = buffer.data[si];
            dst[1] = buffer.data[si + 1];
            dst[2] = buffer.data[si + 2];
        }, cancel);
    }
}

void mirror_horizontal(RgbFloatBuffer &buffer, CancelFlag *cancel) {
    normalize_orientation(buffer, 1, cancel);
}

bool downscale_to_long_edge(RgbFloatBuffer &buffer, uint32_t long_edge, CancelFlag *cancel) {
    cancellation_point(cancel, "resize");
    if (buffer.empty() || long_edge == 0) return false;
    const uint32_t longest = std::max(buffer.width, buffer.height);
    if (long_edge >= longest) return true; // upscale is not performed
    const double scale = double(long_edge) / double(longest);
    uint32_t nw = uint32_t(std::max(1, int(std::llround(double(buffer.width) * scale))));
    uint32_t nh = uint32_t(std::max(1, int(std::llround(double(buffer.height) * scale))));
    if (nw > buffer.width) nw = buffer.width;
    if (nh > buffer.height) nh = buffer.height;

    std::vector<float> out(size_t(nw) * nh * 3, 0.0f);
    for (uint32_t y = 0; y < nh; y++) {
        cancellation_point(cancel, "resize.row");
        const double y0 = double(y) * buffer.height / double(nh);
        const double y1 = double(y + 1) * buffer.height / double(nh);
        uint32_t iy0 = uint32_t(y0);
        uint32_t iy1 = uint32_t(std::min(uint64_t(buffer.height),
                                         uint64_t(std::ceil(y1))));
        if (iy1 <= iy0) iy1 = iy0 + 1;
        for (uint32_t x = 0; x < nw; x++) {
            const double x0 = double(x) * buffer.width / double(nw);
            const double x1 = double(x + 1) * buffer.width / double(nw);
            uint32_t ix0 = uint32_t(x0);
            uint32_t ix1 = uint32_t(std::min(uint64_t(buffer.width),
                                             uint64_t(std::ceil(x1))));
            if (ix1 <= ix0) ix1 = ix0 + 1;
            double acc[3] = {0, 0, 0};
            for (uint32_t sy = iy0; sy < iy1; sy++) {
                if ((sy & 31) == 0) cancellation_point(cancel, "resize.source.row");
                const float *row = buffer.data.data() + size_t(sy) * buffer.width * 3;
                for (uint32_t sx = ix0; sx < ix1; sx++) {
                    if ((sx & 4095) == 0) cancellation_point(cancel);
                    acc[0] += row[sx * 3 + 0];
                    acc[1] += row[sx * 3 + 1];
                    acc[2] += row[sx * 3 + 2];
                }
            }
            const double area = double(iy1 - iy0) * double(ix1 - ix0);
            float *dst = out.data() + (size_t(y) * nw + x) * 3;
            dst[0] = float(acc[0] / area);
            dst[1] = float(acc[1] / area);
            dst[2] = float(acc[2] / area);
        }
    }
    buffer.width = nw;
    buffer.height = nh;
    buffer.data = std::move(out);
    return true;
}

} // namespace pe

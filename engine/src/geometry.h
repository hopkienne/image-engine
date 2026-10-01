// Geometry stage: orientation normalization (decoder flip bitmask), user crop,
// 90-degree rotations, horizontal flip, box downscale. All operate on the
// linear FP32 RGB working buffer; downsampling uses area averaging in FP64
// accumulators for determinism.
#pragma once
#include "buffer.h"
#include <cstdint>

namespace pe {

class CancelFlag;

// dcraw source-axis flip bits (engine owns orientation):
//   bit2 (2): vertical mirror in source axes
//   bit1 (1): horizontal mirror in source axes
//   bit4 (4): transpose (swap rows/cols)
// The forward map mirrors source axes before transpose. The implementation
// swaps mirror axes when transposing first; this matches LibRaw flip_index.
void normalize_orientation(RgbFloatBuffer &buffer, uint32_t flip, CancelFlag *cancel = nullptr);

// Resolves normalized crop coords to a pixel rect deterministically and crops.
// Returns false if the rect degenerates.
bool apply_crop(RgbFloatBuffer &buffer, double left, double top, double width,
                double height, CancelFlag *cancel = nullptr);

void rotate_quarter_turns(RgbFloatBuffer &buffer, int quarter_turns, CancelFlag *cancel = nullptr);
void mirror_horizontal(RgbFloatBuffer &buffer, CancelFlag *cancel = nullptr);

// Box downscale so max(w,h) == long_edge. No-op when long_edge >= max(w,h).
// Returns false on integer overflow.
bool downscale_to_long_edge(RgbFloatBuffer &buffer, uint32_t long_edge, CancelFlag *cancel = nullptr);

} // namespace pe

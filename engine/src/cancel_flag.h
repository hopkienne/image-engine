// Cooperative cancellation flag (docs/04 section 4.1). Thread-safe, one-way.
#pragma once
#include <atomic>
#include <cstddef>

namespace pe {

class CancelFlag {
public:
    void request() { flag_.store(true, std::memory_order_relaxed); }
    bool is_cancelled() const { return flag_.load(std::memory_order_relaxed); }

    // Internal test instrumentation. Install before starting the operation;
    // never modify while it is running. Absent from the public C ABI.
    using Observer = void (*)(CancelFlag &, const char *, void *) noexcept;
    void set_observer(Observer fn, void *data) { observer_ = fn; observer_data_ = data; }
    void observe(const char *stage) noexcept {
        if (observer_ && stage) observer_(*this, stage, observer_data_);
    }

private:
    std::atomic<bool> flag_{false};
    Observer observer_ = nullptr;
    void *observer_data_ = nullptr;
};

struct Cancelled {};

inline void cancellation_point(CancelFlag *cancel, const char *stage = nullptr) {
    if (!cancel) return;
    cancel->observe(stage);
    if (cancel->is_cancelled()) throw Cancelled{};
}

// Keep cancellation branches out of the inner arithmetic loop so normal
// renders remain vectorizable. Each callback processes at most one chunk.
template <typename F>
inline void for_each_chunk(size_t count, CancelFlag *cancel, const char *stage,
                            F apply, size_t chunk_size = 4096) {
    for (size_t begin = 0; begin < count;) {
        cancellation_point(cancel, stage);
        const size_t end = count - begin < chunk_size ? count : begin + chunk_size;
        apply(begin, end);
        begin = end;
    }
}

} // namespace pe

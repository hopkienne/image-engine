#include "strict_json.h"
#include <cmath>
#include <memory>
#include <vector>

namespace pe {

namespace {

using json = nlohmann::json;

class StrictSax {
public:
    using number_integer_t = json::number_integer_t;
    using number_unsigned_t = json::number_unsigned_t;
    using number_float_t = json::number_float_t;
    using string_t = json::string_t;
    using binary_t = json::binary_t;

    explicit StrictSax(const JsonLimits &limits) : limits_(limits) {}

    bool null() { return handle_scalar(json(nullptr)); }
    bool boolean(bool val) { return handle_scalar(json(val)); }
    bool number_integer(number_integer_t val) { return handle_scalar(json(val)); }
    bool number_unsigned(number_unsigned_t val) {
        return handle_scalar(json(uint64_t(val)));
    }
    bool number_float(number_float_t val, const string_t &) {
        if (!std::isfinite(val)) return fail("non-finite JSON number rejected");
        return handle_scalar(json(val));
    }
    bool string(string_t &val) { return handle_scalar(json(val)); }
    bool binary(binary_t &) { return fail("binary JSON values are not accepted"); }

    bool start_object(std::size_t) {
        if (!check_depth()) return false;
        json *stored = new json(json::object());
        owned_.emplace_back(stored);
        stack_.emplace_back();
        stack_.back().value = stored;
        stack_.back().is_object = true;
        return true;
    }

    bool key(string_t &val) {
        Frame &f = stack_.back();
        if (!f.is_object) return fail("object key outside object");
        if (!f.pending_key.empty()) return fail("malformed object key sequence");
        if (f.value->contains(val)) return fail("duplicate object key rejected");
        f.pending_key = std::move(val);
        return true;
    }

    bool end_object() {
        if (stack_.empty() || !stack_.back().is_object) return fail("unbalanced object");
        return close_container();
    }

    bool start_array(std::size_t) {
        if (!check_depth()) return false;
        json *stored = new json(json::array());
        owned_.emplace_back(stored);
        stack_.emplace_back();
        stack_.back().value = stored;
        stack_.back().is_object = false;
        return true;
    }

    bool end_array() {
        if (stack_.empty() || stack_.back().is_object) return fail("unbalanced array");
        return close_container();
    }

    bool parse_error(std::size_t, const std::string &, const json::exception &ex) {
        return fail(std::string("JSON parse error: ") + ex.what());
    }

    bool finalize(json &out, std::string &error) {
        if (!ok_) {
            error = error_;
            return false;
        }
        if (!stack_.empty() || !root_set_) {
            error = "JSON document structure invalid";
            return false;
        }
        out = std::move(root_);
        return true;
    }

private:
    struct Frame {
        json *value = nullptr;
        bool is_object = false;
        std::string pending_key;
    };

    bool fail(const std::string &msg) {
        if (ok_) {
            ok_ = false;
            error_ = msg;
        }
        return false;
    }

    bool check_depth() {
        if (stack_.size() + 1 > limits_.max_depth) {
            return fail("JSON nesting depth exceeds limit");
        }
        return true;
    }

    bool handle_scalar(json &&val) {
        if (stack_.empty()) {
            root_ = std::move(val);
            root_set_ = true;
            return true;
        }
        Frame &f = stack_.back();
        if (f.is_object) {
            if (f.pending_key.empty()) return fail("object value without key");
            (*f.value)[f.pending_key] = std::move(val);
            f.pending_key.clear();
        } else {
            f.value->push_back(std::move(val));
        }
        return true;
    }

    bool close_container() {
        json finished = std::move(*stack_.back().value);
        stack_.pop_back();
        return handle_scalar(std::move(finished));
    }

    const JsonLimits &limits_;
    std::vector<Frame> stack_;
    std::vector<std::unique_ptr<json>> owned_;
    json root_;
    bool root_set_ = false;
    bool ok_ = true;
    std::string error_;
};

} // namespace

bool strict_json_parse(const char *data, size_t size, const JsonLimits &limits,
                       nlohmann::json &out, std::string &error) {
    if (size > limits.max_bytes) {
        error = "JSON input exceeds size limit";
        return false;
    }
    if (size == 0) {
        error = "JSON input is empty";
        return false;
    }
    StrictSax sax(limits);
    bool parsed = nlohmann::json::sax_parse(data, data + size, &sax,
                                            nlohmann::json::input_format_t::json,
                                            /*strict=*/true);
    // finalize() fills `error` with the recorded reason on failure.
    bool finalized = sax.finalize(out, error);
    if (!parsed || !finalized) {
        if (error.empty()) error = "JSON parse failed";
        return false;
    }
    return true;
}

} // namespace pe

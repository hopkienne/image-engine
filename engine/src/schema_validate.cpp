#include "schema_validate.h"
#include <cmath>
#include <regex>
#include <set>
#include <string>
#include <vector>

namespace pe {

namespace {

// Keywords this validator understands. Anything else fails load() closed.
const std::set<std::string> kSupported = {
    "type", "const", "enum", "required", "properties", "additionalProperties",
    "items", "minItems", "maxItems", "uniqueItems", "minLength", "maxLength",
    "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "anyOf", "allOf", "if", "then", "else",
    // annotations that may appear anywhere
    "$schema", "title", "description"};

std::string type_name(const nlohmann::json &v) {
    if (v.is_object()) return "object";
    if (v.is_array()) return "array";
    if (v.is_string()) return "string";
    if (v.is_boolean()) return "boolean";
    if (v.is_null()) return "null";
    if (v.is_number_integer()) return "integer";
    if (v.is_number_float()) return "number";
    return "unknown";
}

bool matches_type(const nlohmann::json &v, const std::string &t) {
    if (t == "object") return v.is_object();
    if (t == "array") return v.is_array();
    if (t == "string") return v.is_string();
    if (t == "boolean") return v.is_boolean();
    if (t == "null") return v.is_null();
    if (t == "number") return v.is_number() && !v.is_boolean();
    if (t == "integer") {
        if (v.is_number_integer()) return true;
        if (v.is_number_float()) {
            double d = v.get<double>();
            return std::isfinite(d) && d == std::floor(d);
        }
        return false;
    }
    return false;
}

// JSON-Schema equality: numbers compare by value (1 == 1.0); booleans are
// distinct from numbers; everything else uses deep equality.
bool json_equal(const nlohmann::json &a, const nlohmann::json &b) {
    if (a.is_number() && b.is_number() && !a.is_boolean() && !b.is_boolean()) {
        return a.get<double>() == b.get<double>();
    }
    if (a.type() != b.type()) return false;
    return a == b;
}

struct Ctx {
    const nlohmann::json *schema;
    std::string path; // instance path for error messages
};

class Impl {
public:
    explicit Impl(const nlohmann::json *root) : root_(root) {}

    bool validate(const nlohmann::json &instance, const nlohmann::json &schema,
                  const std::string &path, std::string &error) const {
        // type
        auto t_it = schema.find("type");
        if (t_it != schema.end() && !t_it->is_null()) {
            bool ok = false;
            std::string want;
            if (t_it->is_string()) {
                want = t_it->get<std::string>();
                ok = matches_type(instance, want);
            } else if (t_it->is_array()) {
                for (const auto &t : *t_it) {
                    want = t.get<std::string>();
                    if (matches_type(instance, want)) { ok = true; break; }
                }
            } else {
                error = err(path, "schema 'type' must be string or array");
                return false;
            }
            if (!ok) {
                error = err(path, "expected type '" + want + "', got '" +
                                      type_name(instance) + "'");
                return false;
            }
        }
        // const
        auto c_it = schema.find("const");
        if (c_it != schema.end() && !json_equal(instance, *c_it)) {
            error = err(path, "value does not match 'const'");
            return false;
        }
        // enum
        auto e_it = schema.find("enum");
        if (e_it != schema.end()) {
            bool found = false;
            for (const auto &item : *e_it) {
                if (json_equal(instance, item)) { found = true; break; }
            }
            if (!found) {
                error = err(path, "value not in 'enum'");
                return false;
            }
        }
        if (instance.is_object()) {
            // required
            auto r_it = schema.find("required");
            if (r_it != schema.end()) {
                for (const auto &req : *r_it) {
                    const std::string key = req.get<std::string>();
                    if (instance.find(key) == instance.end()) {
                        error = err(path, "missing required property '" + key + "'");
                        return false;
                    }
                }
            }
            // properties + additionalProperties
            auto p_it = schema.find("properties");
            auto ap_it = schema.find("additionalProperties");
            for (auto kv = instance.begin(); kv != instance.end(); ++kv) {
                bool matched = false;
                if (p_it != schema.end() && p_it->is_object()) {
                    auto sub = p_it->find(kv.key());
                    if (sub != p_it->end()) {
                        matched = true;
                        if (!validate(kv.value(), *sub, child(path, kv.key()), error))
                            return false;
                    }
                }
                if (!matched && ap_it != schema.end() && ap_it->is_boolean() &&
                    ap_it->get<bool>() == false) {
                    error = err(path, "unknown property '" + kv.key() +
                                          "' (additionalProperties=false)");
                    return false;
                }
            }
        }
        if (instance.is_array()) {
            auto items = schema.find("items");
            if (items != schema.end() && items->is_object()) {
                size_t i = 0;
                for (auto it = instance.begin(); it != instance.end(); ++it, ++i) {
                    if (!validate(it.value(), *items,
                                  child(path, "[" + std::to_string(i) + "]"), error))
                        return false;
                }
            }
            auto mi = schema.find("minItems");
            if (mi != schema.end() && instance.size() < size_t(mi->get<int64_t>())) {
                error = err(path, "array has fewer than minItems");
                return false;
            }
            auto ma = schema.find("maxItems");
            if (ma != schema.end() && instance.size() > size_t(ma->get<int64_t>())) {
                error = err(path, "array has more than maxItems");
                return false;
            }
            auto uq = schema.find("uniqueItems");
            if (uq != schema.end() && uq->get<bool>()) {
                for (auto a = instance.begin(); a != instance.end(); ++a) {
                    for (auto b = std::next(a); b != instance.end(); ++b) {
                        if (json_equal(*a, *b)) {
                            error = err(path, "array items are not unique");
                            return false;
                        }
                    }
                }
            }
        }
        if (instance.is_string()) {
            const std::string &s = instance.get_ref<const std::string &>();
            auto ml = schema.find("minLength");
            if (ml != schema.end() && codepoints(s) < size_t(ml->get<int64_t>())) {
                error = err(path, "string shorter than minLength");
                return false;
            }
            auto xl = schema.find("maxLength");
            if (xl != schema.end() && codepoints(s) > size_t(xl->get<int64_t>())) {
                error = err(path, "string longer than maxLength");
                return false;
            }
            auto pat = schema.find("pattern");
            if (pat != schema.end()) {
                try {
                    std::regex re(pat->get<std::string>(), std::regex::ECMAScript);
                    if (!std::regex_search(s, re)) {
                        error = err(path, "string does not match 'pattern'");
                        return false;
                    }
                } catch (const std::regex_error &) {
                    error = err(path, "schema 'pattern' failed to compile");
                    return false;
                }
            }
        }
        if (instance.is_number() && !instance.is_boolean()) {
            double d = instance.get<double>();
            if (!std::isfinite(d)) {
                error = err(path, "non-finite number rejected");
                return false;
            }
            auto mn = schema.find("minimum");
            if (mn != schema.end() && d < mn->get<double>()) {
                error = err(path, "number below 'minimum'");
                return false;
            }
            auto mx = schema.find("maximum");
            if (mx != schema.end() && d > mx->get<double>()) {
                error = err(path, "number above 'maximum'");
                return false;
            }
            auto emn = schema.find("exclusiveMinimum");
            if (emn != schema.end() && d <= emn->get<double>()) {
                error = err(path, "number not above 'exclusiveMinimum'");
                return false;
            }
            auto emx = schema.find("exclusiveMaximum");
            if (emx != schema.end() && d >= emx->get<double>()) {
                error = err(path, "number not below 'exclusiveMaximum'");
                return false;
            }
        }
        // anyOf / allOf / if-then-else
        auto any = schema.find("anyOf");
        if (any != schema.end()) {
            bool ok = false;
            std::string last;
            for (const auto &sub : *any) {
                std::string e2;
                if (validate(instance, sub, path, e2)) { ok = true; break; }
                last = e2;
            }
            if (!ok) {
                error = err(path, "does not match any of 'anyOf' (" + last + ")");
                return false;
            }
        }
        auto all = schema.find("allOf");
        if (all != schema.end()) {
            for (const auto &sub : *all) {
                if (!validate(instance, sub, path, error)) return false;
            }
        }
        auto if_it = schema.find("if");
        if (if_it != schema.end()) {
            std::string probe;
            bool cond = validate(instance, *if_it, path, probe);
            const char *branch = cond ? "then" : "else";
            auto br = schema.find(branch);
            if (br != schema.end()) {
                if (!validate(instance, *br, path, error)) return false;
            }
        }
        return true;
    }

    static std::string child(const std::string &path, const std::string &key) {
        if (path.empty()) return key;
        return path + "." + key;
    }

    static std::string err(const std::string &path, const std::string &what) {
        if (path.empty()) return what;
        return path + ": " + what;
    }

    // JSON Schema counts characters (code points), not UTF-8 bytes.
    static size_t codepoints(const std::string &s) {
        size_t n = 0;
        for (unsigned char c : s) {
            if ((c & 0xC0) != 0x80) n++;
        }
        return n;
    }

private:
    const nlohmann::json *root_;
};

// Keywords whose value is itself a schema or an array of schemas: recursion
// must continue inside those. All other known keywords carry plain data
// (const/enum values may contain arbitrary object keys) and are not scanned.
const std::set<std::string> kSchemaValued = {"properties", "items", "anyOf",
                                             "allOf", "if", "then", "else"};

bool scan_unsupported(const nlohmann::json &schema, std::string &error) {
    if (!schema.is_object()) return true;
    for (auto kv = schema.begin(); kv != schema.end(); ++kv) {
        if (kSupported.count(kv.key()) == 0) {
            error = "schema uses unsupported keyword '" + kv.key() + "'";
            return false;
        }
        if (kv.key() == "additionalProperties" && !kv.value().is_boolean()) {
            error = "schema 'additionalProperties' must be boolean in this "
                    "validator's supported subset";
            return false;
        }
        if (kSchemaValued.count(kv.key()) > 0) {
            if (kv.key() == "properties") {
                // Property NAMES are instance keys, not schema keywords; only
                // their values are schemas.
                for (auto p = kv.value().begin(); p != kv.value().end(); ++p) {
                    if (!scan_unsupported(p.value(), error)) return false;
                }
            } else if (kv.value().is_array()) {
                for (const auto &sub : kv.value()) {
                    if (!scan_unsupported(sub, error)) return false;
                }
            } else {
                if (!scan_unsupported(kv.value(), error)) return false;
            }
        }
    }
    return true;
}

} // namespace

bool MiniSchemaValidator::load(const nlohmann::json &schema, std::string &error) {
    if (!schema.is_object()) {
        error = "schema root must be an object";
        return false;
    }
    if (!scan_unsupported(schema, error)) return false;
    schema_ = schema;
    return true;
}

bool MiniSchemaValidator::validate(const nlohmann::json &instance,
                                   std::string &error) const {
    Impl impl(&schema_);
    return impl.validate(instance, schema_, "", error);
}

} // namespace pe

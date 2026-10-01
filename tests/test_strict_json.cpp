#include "strict_json.h"
#include "test_helpers.h"

using namespace pe;
using namespace pe_test;

TEST_CASE("strict json accepts valid documents") {
    JsonLimits lim;
    nlohmann::json out;
    std::string err;
    CHECK(strict_json_parse(R"({"a":1,"b":[true,null,-2.5]})", lim, out, err));
    CHECK(out["a"] == 1);
    CHECK(out["b"].size() == 3);
    CHECK(strict_json_parse("\"top-level scalar\"", lim, out, err));
    CHECK(out.is_string());
}

TEST_CASE("strict json rejects duplicate keys") {
    JsonLimits lim;
    nlohmann::json out;
    std::string err;
    CHECK_FALSE(strict_json_parse(R"({"a":1,"a":2})", lim, out, err));
    CHECK(err.find("duplicate") != std::string::npos);
    CHECK_FALSE(strict_json_parse(R"({"o":{"x":1,"x":2}})", lim, out, err));
}

TEST_CASE("strict json rejects non-finite numbers") {
    JsonLimits lim;
    nlohmann::json out;
    std::string err;
    CHECK_FALSE(strict_json_parse(R"({"a":NaN})", lim, out, err));
    CHECK_FALSE(strict_json_parse(R"({"a":1e999})", lim, out, err));
    CHECK_FALSE(strict_json_parse(R"({"a":Infinity})", lim, out, err));
}

TEST_CASE("strict json enforces depth and size limits") {
    JsonLimits lim;
    lim.max_depth = 8;
    nlohmann::json out;
    std::string err;
    std::string deep(40, '[');
    deep.append(40, ']');
    CHECK_FALSE(strict_json_parse(deep, lim, out, err));
    CHECK(err.find("depth") != std::string::npos);

    JsonLimits slim;
    slim.max_bytes = 16;
    err.clear();
    CHECK_FALSE(strict_json_parse("\"this string is longer than 16 bytes\"", slim, out, err));
}

TEST_CASE("strict json rejects trailing content and empty input") {
    JsonLimits lim;
    nlohmann::json out;
    std::string err;
    CHECK_FALSE(strict_json_parse(R"({"a":1} trailing)", lim, out, err));
    CHECK_FALSE(strict_json_parse("", lim, out, err));
}

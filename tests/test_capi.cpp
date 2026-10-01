// C ABI tests that do not need a real RAW fixture. The RAW-dependent success
// paths are exercised by the integration runner against the fixture corpus.
#include "photo_engine.h"
#include "test_helpers.h"
#include <cstring>
#include <string>
#include <vector>

using namespace pe_test;

TEST_CASE("engine create/destroy round trip") {
    pe_engine *engine = nullptr;
    CHECK(pe_engine_create(nullptr, 0, &engine) == PE_OK);
    REQUIRE(engine != nullptr);
    pe_engine_destroy(engine);

    // Empty config object is accepted.
    engine = nullptr;
    CHECK(pe_engine_create("{}", 2, &engine) == PE_OK);
    REQUIRE(engine != nullptr);
    pe_engine_destroy(engine);
}

TEST_CASE("engine create failure paths and diagnostics") {
    pe_engine *engine = nullptr;
    // Malformed JSON.
    std::string bad = "{not json";
    pe_status st = pe_engine_create(bad.data(), bad.size(), &engine);
    CHECK(st == PE_RECIPE_INVALID);
    CHECK(engine == nullptr);
    std::string err_text;
    pe_blob *blob = nullptr;
    CHECK(pe_last_error_json(nullptr, &blob) != PE_OK);
    REQUIRE(blob != nullptr);
    size_t n = 0;
    const uint8_t *data = pe_blob_data(blob, &n);
    CHECK(n > 0);
    err_text.assign(reinterpret_cast<const char *>(data), n);
    CHECK(err_text.find("PE_") != std::string::npos);
    pe_blob_release(blob);

    // Unknown config key.
    const char *unknown_key = R"({"unknownKey":1})";
    st = pe_engine_create(unknown_key, std::strlen(unknown_key), &engine);
    CHECK(st == PE_INVALID_ARGUMENT);
    CHECK(engine == nullptr);

    // Unknown limit key.
    const char *unknown_limit = R"({"limits":{"nope":1}})";
    st = pe_engine_create(unknown_limit, std::strlen(unknown_limit), &engine);
    CHECK(st == PE_INVALID_ARGUMENT);
    CHECK(engine == nullptr);

    // NULL out pointer.
    CHECK(pe_engine_create(nullptr, 0, nullptr) == PE_INVALID_ARGUMENT);
}

TEST_CASE("cancel token lifecycle") {
    pe_cancel_token *token = nullptr;
    CHECK(pe_cancel_create(&token) == PE_OK);
    REQUIRE(token != nullptr);
    pe_cancel_request(token); // one-way; requesting twice must be harmless
    pe_cancel_request(token);
    pe_cancel_release(token);
    pe_cancel_release(nullptr); // release accepts NULL
}

TEST_CASE("source open validates arguments before touching the file system") {
    pe_engine *engine = nullptr;
    REQUIRE(pe_engine_create(nullptr, 0, &engine) == PE_OK);
    pe_source *src = nullptr;
    CHECK(pe_source_open_local(engine, nullptr, 0, &src) == PE_INVALID_ARGUMENT);
    CHECK(src == nullptr);
    const char *missing = "Z:/definitely/missing/file.raw";
    CHECK(pe_source_open_local(engine, missing, std::strlen(missing), &src) ==
          PE_SOURCE_UNAVAILABLE);
    CHECK(src == nullptr);
    pe_source_release(nullptr); // release accepts NULL
    pe_engine_destroy(engine);
}

TEST_CASE("render validates preview options") {
    pe_engine *engine = nullptr;
    REQUIRE(pe_engine_create(nullptr, 0, &engine) == PE_OK);
    // A source is required before options are checked; use a NULL source to
    // verify argument validation ordering without a RAW fixture.
    pe_image *img = nullptr;
    pe_preview_options options{};
    options.struct_size = sizeof(pe_preview_options);
    options.abi_version = 1;
    options.long_edge_px = 2048;
    options.quality = 0;
    CHECK(pe_render_preview(engine, nullptr, "{}", 2, &options, nullptr, &img) ==
          PE_INVALID_ARGUMENT);
    CHECK(img == nullptr);
    pe_engine_destroy(engine);
}

TEST_CASE("blob helpers handle NULL") {
    size_t n = 123;
    CHECK(pe_blob_data(nullptr, &n) == nullptr);
    CHECK(n == 0);
    pe_blob_release(nullptr);
}

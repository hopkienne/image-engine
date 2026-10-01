#include "test_helpers.h"

using namespace pe;
using namespace pe_test;

TEST_CASE("embedded schemas load through the fail-closed validator") {
    load_recipe_validator();
    load_look_validator();
}

TEST_CASE("valid recipe passes schema") {
    auto v = load_recipe_validator();
    std::string err;
    nlohmann::json recipe = nlohmann::json::parse(
        valid_recipe_json(std::string(64, 'a'), std::string(64, 'b')), nullptr, false);
    CHECK(v.validate(recipe, err));
}

TEST_CASE("recipe schema negative cases (mirrors scripts/validate_contracts.py)") {
    auto v = load_recipe_validator();
    std::string err;
    auto expect_reject = [&](const std::string &what, nlohmann::json &bad) {
        MESSAGE("negative case: ", what);
        CHECK_FALSE(v.validate(bad, err));
    };
    auto base = [&]() {
        return nlohmann::json::parse(
            valid_recipe_json(std::string(64, 'a'), std::string(64, 'b')), nullptr, false);
    };

    SUBCASE("amount out of range") {
        auto bad = base();
        bad["look"]["amount"] = 1.1;
        expect_reject("amount", bad);
    }
    SUBCASE("unknown top-level key") {
        auto bad = base();
        bad["unexpected"] = 1;
        expect_reject("unknown key", bad);
    }
    SUBCASE("invalid source hash") {
        auto bad = base();
        bad["source"]["sha256"] = "not-a-hash";
        expect_reject("hash", bad);
    }
    SUBCASE("zero WB multiplier") {
        auto bad = base();
        bad["adjustments"]["whiteBalance"]["resolvedCameraMultipliers"][0] = 0;
        expect_reject("wb zero", bad);
    }
    SUBCASE("camera WB on rendered input") {
        auto bad = base();
        bad["source"]["kind"] = "renderedImage";
        expect_reject("renderedImage camera WB", bad);
    }
    SUBCASE("bad pipeline version pattern") {
        auto bad = base();
        bad["execution"]["pipelineVersion"] = "1";
        expect_reject("semver pattern", bad);
    }
    SUBCASE("missing required section") {
        auto bad = base();
        bad.erase("output");
        expect_reject("missing output", bad);
    }
    SUBCASE("cameraProfile wrong type") {
        auto bad = base();
        bad["execution"]["cameraProfile"] = 42;
        expect_reject("cameraProfile type", bad);
    }
    SUBCASE("longEdge below minimum") {
        auto bad = base();
        bad["output"]["longEdge"] = 32;
        expect_reject("longEdge min", bad);
    }
    SUBCASE("integer type rejects fractional longEdge") {
        auto bad = base();
        bad["output"]["longEdge"] = 128.5;
        expect_reject("longEdge fractional", bad);
    }
    SUBCASE("metadataPolicy enum") {
        auto bad = base();
        bad["output"]["metadataPolicy"] = "keep_everything";
        expect_reject("metadataPolicy", bad);
    }
}

TEST_CASE("look manifest schema") {
    auto v = load_look_validator();
    std::string err;
    auto dir = temp_dir("schema_look");
    std::string manifest_sha = make_look_package(dir, "schema-check-look",
                                                 identity_lut_text(), 17);
    (void)manifest_sha;
    std::ifstream mf(dir / "manifest.json");
    std::string text((std::istreambuf_iterator<char>(mf)),
                     std::istreambuf_iterator<char>());
    nlohmann::json manifest = nlohmann::json::parse(text, nullptr, false);
    CHECK(v.validate(manifest, err));

    SUBCASE("bad domain") {
        manifest["domain"] = "linear-something";
        CHECK_FALSE(v.validate(manifest, err));
    }
    SUBCASE("bad operator asset pattern (path traversal)") {
        manifest["operator"]["asset"] = "../lut.cube";
        CHECK_FALSE(v.validate(manifest, err));
    }
    SUBCASE("unsupported dimension") {
        manifest["operator"]["dimension"] = 32;
        CHECK_FALSE(v.validate(manifest, err));
    }
    SUBCASE("missing license file") {
        manifest.erase("licenseFile");
        CHECK_FALSE(v.validate(manifest, err));
    }
    SUBCASE("bad hash pattern") {
        manifest["operator"]["assetSha256"] = "XYZ";
        CHECK_FALSE(v.validate(manifest, err));
    }
}

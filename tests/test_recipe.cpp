#include "engine_impl.h"
#include "engine_limits.h"
#include "recipe.h"
#include "schema_validate.h"
#include "strict_json.h"
#include "test_helpers.h"
#include <cmath>

using namespace pe;
using namespace pe_test;

namespace {

EngineIdentity test_identity() {
    return {"photo-engine-major-1-proposed", "baseline-v0", "0.1.0",
            "photo-engine-g1;libraw-0.22.2"};
}

bool check_recipe(const std::string &text, RecipeModel &model, std::string &err) {
    EngineLimits lim;
    auto rv = load_recipe_validator();
    auto lv = load_look_validator();
    SchemaValidators validators{&rv, &lv};
    nlohmann::json recipe;
    if (!parse_recipe_json(text.data(), text.size(), lim, validators, recipe, err))
        return false;
    return validate_recipe_semantics(recipe, test_identity(), model, err);
}

} // namespace

TEST_CASE("schema-valid recipe passes semantic validation") {
    RecipeModel model;
    std::string err;
    std::string text = valid_recipe_json(std::string(64, 'a'), std::string(64, 'b'));
    REQUIRE(check_recipe(text, model, err));
    CHECK(model.pipeline_id == "baseline-v0");
    CHECK(model.wb_mode == "asShot");
    CHECK(model.wb_multipliers[0] == 2.0);
    CHECK(model.look_amount == 1.0);
    CHECK_FALSE(model.has_long_edge);
}

TEST_CASE("schema-valid but unexecutable parameters are rejected") {
    auto expect_semantic_reject = [](const std::string &what,
                                     const std::string &needle) {
        RecipeModel model;
        std::string err;
        std::string text =
            valid_recipe_json(std::string(64, 'a'), std::string(64, 'b'));
        nlohmann::json recipe = nlohmann::json::parse(text, nullptr, false);
        if (what == "grain") {
            recipe["grain"]["enabled"] = true;
            recipe["grain"]["amount"] = 0.5;
        } else if (what == "pipeline") {
            recipe["execution"]["pipelineId"] = "not-baseline";
        } else if (what == "pipeline-version") {
            recipe["execution"]["pipelineVersion"] = "9.9.9";
        } else if (what == "engine-compat") {
            recipe["execution"]["engineCompatibility"] = "some-other-engine";
        } else if (what == "camera-profile") {
            recipe["execution"]["cameraProfile"] = {
                {"id", "x"}, {"version", "1.0.0"}, {"sha256", std::string(64, 'a')}};
        } else if (what == "rendered-kind") {
            recipe["source"]["kind"] = "renderedImage";
            recipe["adjustments"]["whiteBalance"]["mode"] = "notApplicable";
            recipe["adjustments"]["whiteBalance"]["resolvedCameraMultipliers"] = nullptr;
        } else if (what == "crop-bounds") {
            recipe["geometry"]["crop"]["left"] = 0.5;
            recipe["geometry"]["crop"]["top"] = 0.5;
        } else if (what == "bad-wb-mode") {
            recipe["adjustments"]["whiteBalance"]["mode"] = "notApplicable";
        }
        text = recipe.dump();
        bool ok = check_recipe(text, model, err);
        CHECK_MESSAGE(ok == false, "expected rejection for: ", what);
        if (!ok) {
            std::string want = "message '" + err + "' should mention '" + needle + "'";
            CHECK_MESSAGE(err.find(needle) != std::string::npos, want);
        }
    };
    expect_semantic_reject("grain", "grain");
    expect_semantic_reject("pipeline", "pipeline");
    expect_semantic_reject("pipeline-version", "pipeline version");
    expect_semantic_reject("engine-compat", "engineCompatibility");
    expect_semantic_reject("camera-profile", "cameraProfile");
    expect_semantic_reject("rendered-kind", "renderedImage");
    expect_semantic_reject("crop-bounds", "crop");
    expect_semantic_reject("bad-wb-mode", "enum");
}

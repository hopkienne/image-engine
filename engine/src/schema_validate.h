// Minimal JSON Schema (draft 2020-12) subset validator.
//
// Scope: implements exactly the keyword set used by contracts/recipe.schema.json
// and contracts/look.schema.json (type, const, enum, required, properties,
// additionalProperties:false, items, minItems/maxItems, uniqueItems,
// minLength/maxLength, pattern, minimum/maximum, exclusiveMinimum/Maximum,
// anyOf, allOf, if/then/else). Any OTHER keyword found in a schema makes
// load fail closed, so this validator can never silently under-validate a
// schema it does not fully understand. Full 2020-12 coverage is NOT claimed.
#pragma once
#include <nlohmann/json.hpp>
#include <string>

namespace pe {

class MiniSchemaValidator {
public:
    // Compiles (and restricts) the schema. Returns false + reason when the
    // schema uses unsupported constructs.
    bool load(const nlohmann::json &schema, std::string &error);

    // Validates an instance; on failure `error` is a human-readable path'd reason.
    bool validate(const nlohmann::json &instance, std::string &error) const;

private:
    nlohmann::json schema_;
};

} // namespace pe

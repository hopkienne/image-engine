# contracts/

Verbatim copies of the two JSON Schemas from the R&D package
(`../raw_photo_app_rnd_v0.1/contracts/`, Proposed v0.1):

- `recipe.schema.json` — photo recipe v1 (JSON Schema draft 2020-12)
- `look.schema.json` — internal look package v1

The CMake build embeds both files into the engine binary (generated
`embedded_schemas.h`), so the engine validates documents against exactly the
schema files shipped here — there is no second, drifting copy of the rules.

Validation coverage of the C++ engine validator is a **documented subset** of
draft 2020-12 (the keyword set these two schemas actually use; unknown keywords
fail closed at load). The Python `scripts/validate_contracts.py` in the docs
package remains the reference validator (jsonschema 4.x) and is wired into
CTest as `contract_python_reference` when the docs package is present.

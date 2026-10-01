cmake_minimum_required(VERSION 3.16)
project(photo_engine LANGUAGES C CXX)
option(PHOTO_ENGINE_AUDIT_FAULTS "Enable test-only export I/O fault injection" OFF)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 11)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# ---------------------------------------------------------------------------
# Generated headers: embedded contract schemas + build fingerprint
# ---------------------------------------------------------------------------
file(READ ${CMAKE_CURRENT_SOURCE_DIR}/contracts/recipe.schema.json RECIPE_SCHEMA_JSON)
file(READ ${CMAKE_CURRENT_SOURCE_DIR}/contracts/look.schema.json LOOK_SCHEMA_JSON)
configure_file(${CMAKE_CURRENT_SOURCE_DIR}/cmake/embedded_schemas.h.in
               ${CMAKE_CURRENT_BINARY_DIR}/generated/embedded_schemas.h @ONLY)

set(PHOTO_BUILD_COMPILER
    "${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION} target=${CMAKE_CXX_COMPILER_TARGET} proc=${CMAKE_SYSTEM_PROCESSOR}")
set(PHOTO_BUILD_CXX_STD "C++17")
set(PHOTO_BUILD_TYPE "${CMAKE_BUILD_TYPE}")
set(PHOTO_BUILD_CXX_FLAGS "${CMAKE_CXX_FLAGS} ${CMAKE_CXX_FLAGS_RELEASE}")
set(PHOTO_LIBRAW_VERSION "0.22.2")
set(PHOTO_LIBJPEG_TURBO_VERSION "3.2.0")
set(PHOTO_JPEG_LIB_VERSION "62")
set(PHOTO_ZLIB_VERSION "1.3.2")
set(PHOTO_DEVELOPER_BUILD "photo-engine-g1-libraw-0.22.2")
configure_file(${CMAKE_CURRENT_SOURCE_DIR}/cmake/build_fingerprint.h.in
               ${CMAKE_CURRENT_BINARY_DIR}/generated/build_fingerprint.h @ONLY)

# ---------------------------------------------------------------------------
# Third-party pinned dependencies (see third_party/manifest.json for hashes,
# licenses and rationale). Built from vendored, hash-verified tarballs.
# ---------------------------------------------------------------------------
set(ZLIB_SRC_DIR ${CMAKE_CURRENT_SOURCE_DIR}/third_party/src/zlib-1.3.2)
set(LIBJPEG_SRC_DIR ${CMAKE_CURRENT_SOURCE_DIR}/third_party/src/libjpeg-turbo-3.2.0)
set(LIBRAW_SRC_DIR ${CMAKE_CURRENT_SOURCE_DIR}/third_party/src/LibRaw-0.22.2)

# zlib supports add_subdirectory.
set(ZLIB_BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(ZLIB_BUILD_SHARED OFF CACHE BOOL "" FORCE)
set(ZLIB_INSTALL OFF CACHE BOOL "" FORCE)
set(BUILD_TESTING ON CACHE BOOL "" FORCE)
add_subdirectory(${ZLIB_SRC_DIR} zlib EXCLUDE_FROM_ALL)

# libjpeg-turbo forbids add_subdirectory integration; upstream recommends
# ExternalProject. We drive it from the vendored source dir and import the
# resulting static archive.
include(ExternalProject)
set(JPEG_BUILD_DIR ${CMAKE_BINARY_DIR}/libjpeg_ext-prefix/src/libjpeg_ext-build)
ExternalProject_Add(libjpeg_ext
  SOURCE_DIR ${LIBJPEG_SRC_DIR}
  CMAKE_ARGS -DCMAKE_BUILD_TYPE=Release
             -DENABLE_SHARED=0 -DENABLE_STATIC=1
             -DWITH_SIMD=0 -DWITH_TURBOJPEG=0 -DWITH_JAVA=0 -DWITH_EXAMPLES=0
  INSTALL_COMMAND ""
  BUILD_BYPRODUCTS ${JPEG_BUILD_DIR}/libjpeg.a
  )
add_library(jpeg-static UNKNOWN IMPORTED)
set_target_properties(jpeg-static PROPERTIES
  IMPORTED_LOCATION ${JPEG_BUILD_DIR}/libjpeg.a)
add_dependencies(jpeg-static libjpeg_ext)
set(JPEG_INCLUDE_DIRS ${LIBJPEG_SRC_DIR}/src ${JPEG_BUILD_DIR})

file(GLOB_RECURSE LIBRAW_SOURCES ${LIBRAW_SRC_DIR}/src/*.cpp)
# *_ph.cpp are upstream placeholders for builds WITHOUT processing. Including
# them alongside the real implementations causes duplicate virtual definitions.
list(FILTER LIBRAW_SOURCES EXCLUDE REGEX "_ph\\.cpp$")
add_library(libraw_static STATIC ${LIBRAW_SOURCES})
target_include_directories(libraw_static PRIVATE
  ${LIBRAW_SRC_DIR} ${LIBRAW_SRC_DIR}/libraw
  ${ZLIB_SRC_DIR} ${CMAKE_BINARY_DIR}/zlib
  ${JPEG_INCLUDE_DIRS})
target_compile_definitions(libraw_static PRIVATE USE_ZLIB USE_JPEG)
# Link the decoders' support libraries here and force build order so the
# generated headers (jconfig.h, zconf.h) exist before LibRaw compiles.
target_link_libraries(libraw_static PRIVATE zlibstatic jpeg-static)
add_dependencies(libraw_static libjpeg_ext zlibstatic)
if(MSVC)
  target_compile_options(libraw_static PRIVATE /w)
else()
  target_compile_options(libraw_static PRIVATE -w -O2)
endif()

# ---------------------------------------------------------------------------
# photoengine_core (static; C++17; no UI dependency)
# ---------------------------------------------------------------------------
add_library(photoengine_core STATIC
  engine/src/buffer.cpp
  engine/src/c_api.cpp
  engine/src/color.cpp
  engine/src/engine_impl.cpp
  engine/src/export.cpp
  engine/src/engine_limits.cpp
  engine/src/file_util.cpp
  engine/src/geometry.cpp
  engine/src/icc_srgb.cpp
  engine/src/jpeg_encoder.cpp
  engine/src/look.cpp
  engine/src/raw_adapter.cpp
  engine/src/recipe.cpp
  engine/src/render.cpp
  engine/src/schema_validate.cpp
  engine/src/sha256.cpp
  engine/src/strict_json.cpp)

target_include_directories(photoengine_core
  PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/engine/include
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/engine/src
          ${CMAKE_CURRENT_SOURCE_DIR}/third_party/include
          ${CMAKE_CURRENT_BINARY_DIR}/generated
          ${LIBRAW_SRC_DIR} ${LIBRAW_SRC_DIR}/libraw
          ${JPEG_INCLUDE_DIRS}
          ${ZLIB_SRC_DIR} ${CMAKE_BINARY_DIR}/zlib)

target_compile_definitions(photoengine_core PRIVATE PHOTO_ENGINE_DEVELOPER_BUILD="${PHOTO_DEVELOPER_BUILD}")
if(PHOTO_ENGINE_AUDIT_FAULTS)
  target_compile_definitions(photoengine_core PRIVATE PHOTO_ENGINE_AUDIT_FAULTS=1)
endif()

if(NOT MSVC)
  # Deterministic FP for the color pipeline: no fast-math, no FP contraction.
  target_compile_options(photoengine_core PRIVATE -Wall -Wextra -ffp-contract=off)
endif()

target_link_libraries(photoengine_core PUBLIC libraw_static jpeg-static zlibstatic)
if(WIN32)
  target_link_libraries(photoengine_core PUBLIC ws2_32)
endif()

# ---------------------------------------------------------------------------
# photo-cli
# ---------------------------------------------------------------------------
add_executable(photo-cli cli/main.cpp)
target_include_directories(photo-cli PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/engine/src
  ${CMAKE_CURRENT_SOURCE_DIR}/third_party/include
  ${CMAKE_CURRENT_BINARY_DIR}/generated)
target_link_libraries(photo-cli PRIVATE photoengine_core)
if(WIN32)
  target_link_libraries(photo-cli PRIVATE shell32)
endif()
if(NOT MSVC)
  target_compile_options(photo-cli PRIVATE -Wall -Wextra)
  target_link_options(photo-cli PRIVATE -static)
endif()

# ---------------------------------------------------------------------------
# Tests (doctest, pinned single header)
# ---------------------------------------------------------------------------
enable_testing()
find_package(Python3 COMPONENTS Interpreter)
add_executable(photoengine_tests
  tests/test_main.cpp
  tests/test_sha256.cpp
  tests/test_strict_json.cpp
  tests/test_schema.cpp
  tests/test_color.cpp
  tests/test_look.cpp
  tests/test_geometry.cpp
  tests/test_recipe.cpp
  tests/test_pipeline.cpp
  tests/test_capi.cpp)
target_include_directories(photoengine_tests PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/engine/src
  ${CMAKE_CURRENT_SOURCE_DIR}/third_party/include
  ${CMAKE_CURRENT_BINARY_DIR}/generated
  ${LIBRAW_SRC_DIR} ${LIBRAW_SRC_DIR}/libraw
  ${JPEG_INCLUDE_DIRS}
  ${ZLIB_SRC_DIR} ${CMAKE_BINARY_DIR}/zlib)
target_link_libraries(photoengine_tests PRIVATE photoengine_core)
if(NOT MSVC)
  target_compile_options(photoengine_tests PRIVATE -Wall -Wextra)
  target_link_options(photoengine_tests PRIVATE -static)
endif()
add_test(NAME unit COMMAND photoengine_tests)

add_executable(next_step_harness tests/next_step_harness.cpp)
target_include_directories(next_step_harness PRIVATE engine/src third_party/include ${CMAKE_CURRENT_BINARY_DIR}/generated ${LIBRAW_SRC_DIR})
target_link_libraries(next_step_harness PRIVATE photoengine_core)
if(WIN32)
  target_link_libraries(next_step_harness PRIVATE psapi)
endif()
if(NOT MSVC)
  target_link_options(next_step_harness PRIVATE -static)
endif()

# Reference contract validation from the documentation package (jsonschema).
set(DOCS_PACKAGE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../raw_photo_app_rnd_v0.1"
    CACHE PATH "Location of the raw_photo_app_rnd_v0.1 docs package")
if(EXISTS ${DOCS_PACKAGE_DIR}/scripts/validate_contracts.py)
  add_test(NAME contract_python_reference
           COMMAND ${Python3_EXECUTABLE} ${DOCS_PACKAGE_DIR}/scripts/validate_contracts.py)
  set_tests_properties(contract_python_reference PROPERTIES
    ENVIRONMENT "PYTHONPATH=${DOCS_PACKAGE_DIR}")
endif()

# ---------------------------------------------------------------------------
# Independent-audit harnesses (AUD plan): C ABI driver + standalone LibRaw
# reference adapter. Test tooling only; not part of the product pipeline.
# ---------------------------------------------------------------------------
add_executable(photoengine_audit_harness tests/acceptance/cpp_harness/audit_harness.cpp)
target_include_directories(photoengine_audit_harness PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/engine/src
  ${CMAKE_CURRENT_SOURCE_DIR}/third_party/include
  ${CMAKE_CURRENT_BINARY_DIR}/generated)
target_link_libraries(photoengine_audit_harness PRIVATE photoengine_core)
if(WIN32)
  target_link_libraries(photoengine_audit_harness PRIVATE shell32)
endif()
if(NOT MSVC)
  target_link_options(photoengine_audit_harness PRIVATE -static)
endif()

add_executable(ref_adapter tests/acceptance/cpp_harness/ref_adapter.cpp)
target_include_directories(ref_adapter PRIVATE
  ${LIBRAW_SRC_DIR} ${LIBRAW_SRC_DIR}/libraw
  ${JPEG_INCLUDE_DIRS}
  ${ZLIB_SRC_DIR} ${CMAKE_BINARY_DIR}/zlib
  ${CMAKE_CURRENT_SOURCE_DIR}/third_party/include)
target_link_libraries(ref_adapter PRIVATE libraw_static)
if(WIN32)
  target_link_libraries(ref_adapter PRIVATE ws2_32)
endif()
if(NOT MSVC)
  target_link_options(ref_adapter PRIVATE -static)
endif()

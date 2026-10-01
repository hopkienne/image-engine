// Small platform helpers shared by the engine and CLI.
#pragma once
#include <cstdio>
#include <string>

namespace pe {

// fopen that accepts UTF-8 paths on Windows (and plain fopen elsewhere).
FILE *utf8_fopen(const std::string &path, const char *mode);
// Atomically create a new binary file, failing if the path already exists.
FILE *utf8_fopen_exclusive(const std::string &path);

// True if the path exists (file or directory).
bool path_exists(const std::string &path);

// remove() that accepts UTF-8 paths on Windows.
bool utf8_remove(const std::string &path);

// rename() that accepts UTF-8 paths on Windows. Fails if target exists.
bool utf8_rename(const std::string &from, const std::string &to);
bool utf8_rename_no_replace(const std::string &from, const std::string &to);

} // namespace pe

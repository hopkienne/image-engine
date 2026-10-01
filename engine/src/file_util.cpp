#include "file_util.h"

#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif
#include <cerrno>
#include <fcntl.h>
#if defined(_WIN32)
#include <io.h>
#else
#include <unistd.h>
#endif
#include <sys/stat.h>
#include <vector>

namespace pe {

#if defined(_WIN32)
static std::vector<wchar_t> to_wide(const std::string &s) {
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, nullptr, 0);
    std::vector<wchar_t> w(size_t(n > 0 ? n : 1), L'\0');
    if (n > 0) MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, w.data(), n);
    return w;
}
#endif

FILE *utf8_fopen(const std::string &path, const char *mode) {
#if defined(_WIN32)
    return _wfopen(to_wide(path).data(), to_wide(mode).data());
#else
    return std::fopen(path.c_str(), mode);
#endif
}

FILE *utf8_fopen_exclusive(const std::string &path) {
#if defined(_WIN32)
    int fd = _wopen(to_wide(path).data(), _O_WRONLY | _O_CREAT | _O_EXCL | _O_BINARY,
                    _S_IREAD | _S_IWRITE);
    if (fd < 0) return nullptr;
    FILE *f = _fdopen(fd, "wb");
    if (!f) { _close(fd); utf8_remove(path); }
#else
    int fd = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL, 0666);
    if (fd < 0) return nullptr;
    FILE *f = ::fdopen(fd, "wb");
    if (!f) { ::close(fd); utf8_remove(path); }
#endif
    return f;
}

bool path_exists(const std::string &path) {
#if defined(_WIN32)
    struct _stat64 st;
    return _wstat64(to_wide(path).data(), &st) == 0;
#else
    struct stat st;
    return ::stat(path.c_str(), &st) == 0;
#endif
}

bool utf8_remove(const std::string &path) {
#if defined(_WIN32)
    return DeleteFileW(to_wide(path).data()) != 0;
#else
    return std::remove(path.c_str()) == 0;
#endif
}

bool utf8_rename(const std::string &from, const std::string &to) {
#if defined(_WIN32)
    return MoveFileExW(to_wide(from).data(), to_wide(to).data(),
                       MOVEFILE_REPLACE_EXISTING) != 0;
#else
    return std::rename(from.c_str(), to.c_str()) == 0;
#endif
}

bool utf8_rename_no_replace(const std::string &from, const std::string &to) {
#if defined(_WIN32)
    // Without MOVEFILE_REPLACE_EXISTING the call fails when the target exists.
    return MoveFileExW(to_wide(from).data(), to_wide(to).data(),
                       MOVEFILE_WRITE_THROUGH) != 0;
#else
    // POSIX rename() replaces silently; fail instead when the target exists.
    if (path_exists(to)) return false;
    return std::rename(from.c_str(), to.c_str()) == 0;
#endif
}

} // namespace pe

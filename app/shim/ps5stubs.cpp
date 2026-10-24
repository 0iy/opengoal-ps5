// Stubs for debugger, REPL and file-time APIs the game links against but never uses on the PS5.

#include <cerrno>
#include <istream>
#include <ostream>
#include <string>

#include "common/cross_os_debug/xdbg.h"
#include "third-party/replxx/include/replxx.hxx"

#include <fcntl.h>
#include <sys/stat.h>

// ---- xdbg (remote debugger of the GOAL runtime; unsupported here) ------------------------------
namespace xdbg {
std::string ThreadID::to_string() const { return std::to_string(id); }
ThreadID get_current_thread_id() { return ThreadID(); }
void allow_debugging() {}
}  // namespace xdbg

// ---- replxx (interactive console; the PS5 build has no terminal) --------------------------------
namespace replxx {
void Replxx::set_state(State const&) {}
void Replxx::set_completion_callback(completion_callback_t const&) {}
void Replxx::set_highlighter_callback(highlighter_callback_t const&) {}
void Replxx::set_hint_callback(hint_callback_t const&) {}
void Replxx::print(char const*, ...) {}
Replxx::ACTION_RESULT Replxx::invoke(ACTION, char32_t) { return ACTION_RESULT::CONTINUE; }
void Replxx::bind_key(char32_t, key_press_handler_t) {}
void Replxx::history_add(std::string const&) {}
bool Replxx::history_save(std::string const&) { return false; }
bool Replxx::history_load(std::string const&) { return false; }
void Replxx::set_word_break_characters(char const*) {}
void Replxx::set_complete_on_empty(bool) {}
void Replxx::set_indent_multiline(bool) {}
void Replxx::set_max_history_size(int) {}
void Replxx::clear_screen(void) {}
void Replxx::enable_bracketed_paste(void) {}
char const* Replxx::input(std::string const&) { return nullptr; }
}  // namespace replxx

// ---- file times ---------------------------------------------------------------------------------------
extern "C" int utimensat(int, const char*, const struct timespec[2], int) {
  errno = ENOSYS;
  return -1;
}

// ---- xdbg (debugger of the desktop REPL; the extractor links the compiler, which references it) -----------
#include "common/cross_os_debug/xdbg.h"
namespace xdbg {
ThreadID::ThreadID(const std::string& str) : id(pid_t(std::atoi(str.c_str()))) {}
bool break_now(const ThreadID&) { return false; }
bool cont_now(const ThreadID&) { return false; }
bool single_step_now(const ThreadID&) { return false; }
bool detach_and_resume(const ThreadID&) { return false; }
bool get_regs_now(const ThreadID&, Regs*) { return false; }
bool set_regs_now(const ThreadID&, const Regs&) { return false; }
bool close_memory(const ThreadID&, MemoryHandle*) { return false; }
bool read_goal_memory(u8*, int, u32, const DebugContext&, const MemoryHandle&) { return false; }
bool write_goal_memory(const u8*, int, u32, const DebugContext&, const MemoryHandle&) { return false; }
bool check_stopped(const ThreadID&, SignalInfo*) { return false; }
}  // namespace xdbg
#include "ProcessBridge.h"
#include <spawn.h>
#include <fcntl.h>
#include <signal.h>
#include <errno.h>
#include <sys/wait.h>
#include <sys/file.h>
#include <unistd.h>
#ifdef __APPLE__
#include <crt_externs.h>
#else
extern char **environ;
#endif

/* Each metadata backend owns a process group. No shell, Terminal automation,
   or prompt is involved in routine reads. Interactive reviews use Terminal. */
pid_t usage_spawn(const char *path, char *const argv[], int *output_fd) {
    int output[2];
    if (pipe(output)) return -1;
    /* Finder/launchers may have closed a standard descriptor. Keep pipe ends
       above stderr so later file actions cannot close their own dup2 target. */
    for (int index = 0; index < 2; ++index) {
        if (output[index] <= STDERR_FILENO) {
            int replacement = fcntl(output[index], F_DUPFD_CLOEXEC, STDERR_FILENO + 1);
            if (replacement < 0) {
                int saved = errno; close(output[0]); close(output[1]); errno = saved; return -1;
            }
            close(output[index]); output[index] = replacement;
        }
    }
    if (fcntl(output[0], F_SETFD, FD_CLOEXEC) || fcntl(output[1], F_SETFD, FD_CLOEXEC)) {
        int saved = errno; close(output[0]); close(output[1]); errno = saved; return -1;
    }
    posix_spawn_file_actions_t actions;
    posix_spawnattr_t attributes;
    pid_t pid = -1;
    int actions_ready = 0, attributes_ready = 0, result = 0;
#define CHECK(action) do { result = (action); if (result) goto cleanup; } while (0)
    CHECK(posix_spawn_file_actions_init(&actions)); actions_ready = 1;
    CHECK(posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0));
    CHECK(posix_spawn_file_actions_adddup2(&actions, output[1], STDOUT_FILENO));
    CHECK(posix_spawn_file_actions_adddup2(&actions, output[1], STDERR_FILENO));
    CHECK(posix_spawn_file_actions_addclose(&actions, output[0]));
    CHECK(posix_spawn_file_actions_addclose(&actions, output[1]));
    CHECK(posix_spawnattr_init(&attributes)); attributes_ready = 1;
    short flags = POSIX_SPAWN_SETPGROUP;
#ifdef __APPLE__
    flags |= POSIX_SPAWN_CLOEXEC_DEFAULT;
#endif
    CHECK(posix_spawnattr_setflags(&attributes, flags));
    CHECK(posix_spawnattr_setpgroup(&attributes, 0));
#ifdef __APPLE__
    char **environment = *_NSGetEnviron();
#else
    char **environment = environ;
#endif
    result = posix_spawn(&pid, path, &actions, &attributes, argv, environment);
cleanup:
    if (actions_ready) posix_spawn_file_actions_destroy(&actions);
    if (attributes_ready) posix_spawnattr_destroy(&attributes);
    close(output[1]);
    if (result) { close(output[0]); errno = result; return -1; }
    *output_fd = output[0];
    return pid;
#undef CHECK
}

int usage_poll(pid_t pid, int *exit_code) {
    int status = 0;
    pid_t result;
    do { result = waitpid(pid, &status, WNOHANG); } while (result < 0 && errno == EINTR);
    if (result == 0) return 0;
    if (result < 0) return -1;
    *exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
    return 1;
}

int usage_instance_lock(const char *path) {
    int descriptor = open(path, O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (descriptor < 0) return -1;
    if (flock(descriptor, LOCK_EX | LOCK_NB)) {
        int saved = errno; close(descriptor); errno = saved; return -1;
    }
    return descriptor;
}

void usage_stop(pid_t pid, int force) {
    if (pid > 1) kill(-pid, force ? SIGKILL : SIGTERM);
}

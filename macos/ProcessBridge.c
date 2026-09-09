#include "ProcessBridge.h"
#include <spawn.h>
#include <fcntl.h>
#include <signal.h>
#include <errno.h>
#include <sys/wait.h>
#include <unistd.h>
#include <crt_externs.h>

/* Each metadata backend owns a process group. No shell, Terminal automation,
   or prompt is involved in routine reads. Interactive reviews use Terminal. */
pid_t usage_spawn(const char *path, char *const argv[], int *output_fd) {
    int output[2];
    if (pipe(output)) return -1;
    fcntl(output[0], F_SETFD, FD_CLOEXEC);
    fcntl(output[1], F_SETFD, FD_CLOEXEC);
    posix_spawn_file_actions_t actions;
    posix_spawnattr_t attributes;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
    posix_spawn_file_actions_adddup2(&actions, output[1], STDOUT_FILENO);
    posix_spawn_file_actions_adddup2(&actions, output[1], STDERR_FILENO);
    posix_spawn_file_actions_addclose(&actions, output[0]);
    posix_spawn_file_actions_addclose(&actions, output[1]);
    posix_spawnattr_init(&attributes);
    posix_spawnattr_setflags(&attributes, POSIX_SPAWN_SETPGROUP);
    posix_spawnattr_setpgroup(&attributes, 0);
    pid_t pid = -1;
    int result = posix_spawn(&pid, path, &actions, &attributes, argv, *_NSGetEnviron());
    posix_spawn_file_actions_destroy(&actions);
    posix_spawnattr_destroy(&attributes);
    close(output[1]);
    if (result) { close(output[0]); errno = result; return -1; }
    *output_fd = output[0];
    return pid;
}

int usage_wait(pid_t pid) {
    int status = 0;
    while (waitpid(pid, &status, 0) < 0) { if (errno != EINTR) return -1; }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
}

void usage_stop(pid_t pid, int force) {
    if (pid > 1) kill(-pid, force ? SIGKILL : SIGTERM);
}

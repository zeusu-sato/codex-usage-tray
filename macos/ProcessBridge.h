#include <sys/types.h>
pid_t usage_spawn(const char *path, char *const argv[], int *output_fd);
int usage_poll(pid_t pid, int *exit_code);
void usage_stop(pid_t pid, int force);
int usage_instance_lock(const char *path);

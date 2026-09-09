#include <sys/types.h>
pid_t usage_spawn(const char *path, char *const argv[], int *output_fd);
int usage_wait(pid_t pid);
void usage_stop(pid_t pid, int force);

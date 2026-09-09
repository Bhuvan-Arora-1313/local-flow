// Compiled entry point for LocalFlow.app.
// A real Mach-O executable (not a shell script) so LaunchServices launches the
// bundle with a full GUI session -> rumps' menu-bar item registers correctly.
// It finds the project folder, sets a little environment, and exec()s the
// project's Python on flow.py.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <limits.h>
#include <sys/stat.h>
#include <mach-o/dyld.h>

static int is_file(const char *p) {
    struct stat st;
    return stat(p, &st) == 0 && S_ISREG(st.st_mode);
}

static int is_dir(const char *p) {
    struct stat st;
    return stat(p, &st) == 0 && S_ISDIR(st.st_mode);
}

// first non-empty line of a file, newline/space trimmed. 1 on success.
static int read_line(const char *path, char *buf, size_t n) {
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    int ok = fgets(buf, (int)n, f) != NULL;
    fclose(f);
    if (!ok) return 0;
    size_t l = strlen(buf);
    while (l && (buf[l-1] == '\n' || buf[l-1] == '\r' || buf[l-1] == ' ' || buf[l-1] == '\t'))
        buf[--l] = 0;
    return l > 0;
}

// strip the last `n` path components from `s` in place
static void up(char *s, int n) {
    for (int i = 0; i < n; i++) { char *c = strrchr(s, '/'); if (c) *c = 0; }
}

int main(void) {
    char exe[PATH_MAX]; uint32_t sz = sizeof(exe);
    if (_NSGetExecutablePath(exe, &sz) != 0) return 1;
    char real[PATH_MAX];
    if (!realpath(exe, real)) { strncpy(real, exe, sizeof(real)); real[sizeof(real)-1] = 0; }

    // real = .../LocalFlow.app/Contents/MacOS/LocalFlow
    char contents[PATH_MAX]; strncpy(contents, real, sizeof(contents)); contents[sizeof(contents)-1]=0;
    up(contents, 2);                              // .../LocalFlow.app/Contents
    char approot[PATH_MAX]; strncpy(approot, contents, sizeof(approot)); approot[sizeof(approot)-1]=0;
    up(approot, 2);                               // parent of LocalFlow.app

    const char *home = getenv("HOME");

    // candidate project folders, best first
    char cands[4][PATH_MAX]; int nc = 0;
    char baked_path[PATH_MAX], baked[PATH_MAX] = {0};
    snprintf(baked_path, sizeof(baked_path), "%s/Resources/localflow_home", contents);
    if (read_line(baked_path, baked, sizeof(baked)))
        { strncpy(cands[nc++], baked, PATH_MAX); }
    strncpy(cands[nc++], approot, PATH_MAX);
    if (home) snprintf(cands[nc++], PATH_MAX, "%s/localflow", home);
    if (home) snprintf(cands[nc++], PATH_MAX, "%s/local-flow", home);

    char here[PATH_MAX] = {0};
    for (int i = 0; i < nc; i++) {
        char probe[PATH_MAX];
        snprintf(probe, sizeof(probe), "%s/flow.py", cands[i]);
        if (is_file(probe)) { strncpy(here, cands[i], sizeof(here)); here[sizeof(here)-1]=0; break; }
    }
    if (!here[0]) {
        system("osascript -e 'display alert \"LocalFlow\" message "
               "\"Project folder not found. Run ./setup.sh once from the local-flow folder.\"'");
        return 1;
    }

    // interpreter
    char py[PATH_MAX] = {0}, ppath[PATH_MAX];
    snprintf(ppath, sizeof(ppath), "%s/.python-path", here);
    if (!read_line(ppath, py, sizeof(py)) || !is_file(py)) {
        if (home) snprintf(py, sizeof(py), "%s/miniconda3/envs/flow/bin/python", home);
        if (!is_file(py)) strncpy(py, "/usr/bin/python3", sizeof(py));
    }

    setenv("PYTHONUNBUFFERED", "1", 1);
    if (home) {
        char snap[PATH_MAX];
        snprintf(snap, sizeof(snap),
                 "%s/.cache/huggingface/hub/models--mlx-community--parakeet-tdt-0.6b-v3", home);
        if (is_dir(snap)) {
            setenv("HF_HUB_OFFLINE", "1", 1);
            setenv("TRANSFORMERS_OFFLINE", "1", 1);
        }
    }

    chdir(here);
    char flowpy[PATH_MAX];
    snprintf(flowpy, sizeof(flowpy), "%s/flow.py", here);
    char *argv2[] = { py, flowpy, NULL };
    execv(py, argv2);
    perror("execv");
    return 1;
}

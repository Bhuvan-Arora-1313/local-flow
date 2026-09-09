// Compiled entry point for LocalFlow.app.
//
// It embeds the project's Python (links libpython, runs flow.py *in this
// process* via the CPython C API) instead of exec'ing a separate python.
// That keeps the running process identified as LocalFlow.app, which macOS
// requires before it will show the app's menu-bar item when the app is
// launched by launchd / Finder rather than from a terminal.
//
// Built by setup.sh / install.sh with the venv's include + lib paths, e.g.
//   clang -O2 launcher.c -I<venv>/include/python3.12 \
//         -L<venv>/lib -lpython3.12 -Wl,-rpath,<venv>/lib \
//         -framework CoreFoundation -o LocalFlow.app/Contents/MacOS/LocalFlow
#include <Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <limits.h>
#include <sys/stat.h>
#include <mach-o/dyld.h>

static int is_file(const char *p) { struct stat s; return stat(p,&s)==0 && S_ISREG(s.st_mode); }
static int is_dir (const char *p) { struct stat s; return stat(p,&s)==0 && S_ISDIR(s.st_mode); }

static int read_line(const char *path, char *buf, size_t n) {
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    int ok = fgets(buf, (int)n, f) != NULL;
    fclose(f);
    if (!ok) return 0;
    size_t l = strlen(buf);
    while (l && (buf[l-1]=='\n'||buf[l-1]=='\r'||buf[l-1]==' '||buf[l-1]=='\t')) buf[--l]=0;
    return l > 0;
}
static void up(char *s, int n) { for (int i=0;i<n;i++){ char *c=strrchr(s,'/'); if(c)*c=0; } }

// PYLIB_PREFIX is baked in at compile time (-DPYLIB_PREFIX=...). Fallback below.
#ifndef PYLIB_PREFIX
#define PYLIB_PREFIX ""
#endif

int main(void) {
    char exe[PATH_MAX]; uint32_t sz = sizeof(exe);
    if (_NSGetExecutablePath(exe, &sz) != 0) return 1;
    char real[PATH_MAX];
    if (!realpath(exe, real)) { strncpy(real, exe, sizeof(real)); real[sizeof(real)-1]=0; }

    char contents[PATH_MAX]; strncpy(contents, real, sizeof(contents)); contents[sizeof(contents)-1]=0;
    up(contents, 2);                                  // .../Contents
    char approot[PATH_MAX]; strncpy(approot, contents, sizeof(approot)); approot[sizeof(approot)-1]=0;
    up(approot, 2);                                   // parent of LocalFlow.app

    const char *home = getenv("HOME");

    char cands[4][PATH_MAX]; int nc = 0;
    char baked_path[PATH_MAX], baked[PATH_MAX] = {0};
    snprintf(baked_path, sizeof(baked_path), "%s/Resources/localflow_home", contents);
    if (read_line(baked_path, baked, sizeof(baked))) { strncpy(cands[nc++], baked, PATH_MAX); }
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

    // Python home: baked-in prefix, else derived from .python-path, else conda default.
    char pyhome[PATH_MAX] = PYLIB_PREFIX;
    if (!is_dir(pyhome)) {
        char pp[PATH_MAX], pybin[PATH_MAX] = {0};
        snprintf(pp, sizeof(pp), "%s/.python-path", here);
        if (read_line(pp, pybin, sizeof(pybin))) {
            strncpy(pyhome, pybin, sizeof(pyhome));
            up(pyhome, 2);                            // <prefix>/bin/python -> <prefix>
        }
    }
    if (!is_dir(pyhome) && home)
        snprintf(pyhome, sizeof(pyhome), "%s/miniconda3/envs/flow", home);

    setenv("PYTHONUNBUFFERED", "1", 1);
    setenv("PYTHONNOUSERSITE", "1", 1);
    if (home) {
        char snap[PATH_MAX];
        snprintf(snap, sizeof(snap),
                 "%s/.cache/huggingface/hub/models--mlx-community--parakeet-tdt-0.6b-v3", home);
        if (is_dir(snap)) { setenv("HF_HUB_OFFLINE","1",1); setenv("TRANSFORMERS_OFFLINE","1",1); }
    }
    chdir(here);

    // When not run from a terminal, send output to the log file.
    if (!isatty(STDOUT_FILENO)) {
        char logp[PATH_MAX];
        snprintf(logp, sizeof(logp), "%s/localflow.log", here);
        struct stat ls;
        if (stat(logp, &ls) == 0 && ls.st_size > 1000000) truncate(logp, 0);
        freopen(logp, "a", stdout);
        freopen(logp, "a", stderr);
    }

    char flowpy[PATH_MAX];
    snprintf(flowpy, sizeof(flowpy), "%s/flow.py", here);

    PyStatus status;
    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    if (is_dir(pyhome)) {
        status = PyConfig_SetBytesString(&config, &config.home, pyhome);
        if (PyStatus_Exception(status)) { PyConfig_Clear(&config); Py_ExitStatusException(status); }
    }
    char *argv2[] = { "LocalFlow", flowpy };
    status = PyConfig_SetBytesArgv(&config, 2, argv2);
    if (PyStatus_Exception(status)) { PyConfig_Clear(&config); Py_ExitStatusException(status); }

    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) Py_ExitStatusException(status);

    return Py_RunMain();
}

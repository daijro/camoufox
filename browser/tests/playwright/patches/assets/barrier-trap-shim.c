/* Preloaded by pointer-lock-offscreen.py. After every XFixesCreatePointerBarrier
 * it opens a GDK error trap and syncs inside it, so the request's error, if any,
 * is read by GDK's handler under a trap that started after the request: the
 * order in which the window manager's startup activity made an X error from a
 * barrier fatal, forced on every call. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
typedef unsigned long XID;
typedef XID (*create_fn)(void*, unsigned long, int, int, int, int, int, int, int*);

static void* sym(const char* lib, const char* name) {
  /* libxul, and GTK with it, is loaded RTLD_LOCAL: RTLD_DEFAULT cannot see it. */
  void* handle = dlopen(lib, RTLD_NOW | RTLD_NOLOAD);
  void* f = handle ? dlsym(handle, name) : NULL;
  if (!f) {
    fprintf(stderr, "barrier-trap-shim: no %s in %s\n", name, lib);
    abort();
  }
  return f;
}

XID XFixesCreatePointerBarrier(void* d, unsigned long w, int x1, int y1, int x2, int y2,
                               int dirs, int n, int* devs) {
  static create_fn real;
  if (!real) real = (create_fn)dlsym(RTLD_NEXT, "XFixesCreatePointerBarrier");
  XID barrier = real(d, w, x1, y1, x2, y2, dirs, n, devs);
  void* (*get_display)(void) = sym("libgdk-3.so.0", "gdk_display_get_default");
  void (*push)(void*) = sym("libgdk-3.so.0", "gdk_x11_display_error_trap_push");
  int (*pop)(void*) = sym("libgdk-3.so.0", "gdk_x11_display_error_trap_pop");
  int (*sync)(void*, int) = sym("libX11.so.6", "XSync");
  void* display = get_display();
  push(display);
  sync(d, 0);
  pop(display);
  return barrier;
}

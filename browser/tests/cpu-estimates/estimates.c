/* Records this CPU's RCPPS/RSQRTPS tables, and checks SkCpuEstimates.h against
 * the native instructions over all 2^32 inputs (record.py, check.py).
 *
 *   estimates dump            the table, one hex word per line, then the hashes
 *   estimates hash V          hashes of the emulation of vendor V (1 Intel, 2 AMD)
 *   estimates check V         emulation of vendor V vs this CPU, every input
 *   estimates vendor          this CPU's vendor (1, 2, or 0 for another)
 *
 * The hashes are FNV-1a over the outputs for inputs 0 .. 2^32-1. Built with
 * -DTABLES for hash/check, which need SkCpuEstimateTables.h. */
#include <cpuid.h>
#include <immintrin.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "SkCpuEstimates.h"
#ifdef TABLES
#include "SkCpuEstimateTables.h"
#endif

static uint32_t native(uint32_t b, int rsqrt) {
  float f;
  memcpy(&f, &b, 4);
  __m128 v = _mm_set1_ps(f);
  v = rsqrt ? _mm_rsqrt_ps(v) : _mm_rcp_ps(v);
  uint32_t o;
  memcpy(&o, &v, 4);
  return o;
}

static int host_vendor(void) {
  unsigned a = 0, b = 0, c = 0, d = 0;
  char id[13] = {0};
  __get_cpuid(0, &a, &b, &c, &d);
  memcpy(id, &b, 4);
  memcpy(id + 4, &d, 4);
  memcpy(id + 8, &c, 4);
  if (!strcmp(id, "GenuineIntel")) return SK_CPU_VENDOR_INTEL;
  if (!strcmp(id, "AuthenticAMD")) return SK_CPU_VENDOR_AMD;
  return 0;
}

#define FNV0 1469598103934665603ull
#define FNV(h, x) ((h) = ((h) ^ (x)) * 1099511628211ull)

int main(int argc, char** argv) {
  if (argc > 1 && !strcmp(argv[1], "vendor")) {
    printf("%d\n", host_vendor());
    return 0;
  }
  if (argc > 1 && !strcmp(argv[1], "dump")) {
    for (uint32_t i = 0; i < SK_CPU_ESTIMATE_ENTRIES; i++)
      printf("%08x\n", native(0x3f800000u | (i << (23 - SK_CPU_ESTIMATE_BITS)), 0));
    for (uint32_t p = 0; p < 2; p++)
      for (uint32_t i = 0; i < SK_CPU_ESTIMATE_ENTRIES; i++)
        printf("%08x\n", native(((127u + p) << 23) | (i << (23 - SK_CPU_ESTIMATE_BITS)), 1));
    uint64_t r = FNV0, s = FNV0;
    for (uint64_t x = 0; x < (1ull << 32); x++) {
      FNV(r, native((uint32_t)x, 0));
      FNV(s, native((uint32_t)x, 1));
    }
    printf("rcp %016llx\nrsqrt %016llx\n", (unsigned long long)r, (unsigned long long)s);
    return 0;
  }
#ifdef TABLES
  if (argc > 2 && !strcmp(argv[1], "hash")) {
    const uint32_t* t = kSkCpuEstimateTables[atoi(argv[2]) - 1];
    uint64_t r = FNV0, s = FNV0;
    for (uint64_t x = 0; x < (1ull << 32); x++) {
      FNV(r, sk_cpu_estimate_rcp(t, (uint32_t)x));
      FNV(s, sk_cpu_estimate_rsqrt(t, (uint32_t)x));
    }
    printf("rcp %016llx\nrsqrt %016llx\n", (unsigned long long)r, (unsigned long long)s);
    return 0;
  }
  if (argc > 2 && !strcmp(argv[1], "check")) {
    const uint32_t* t = kSkCpuEstimateTables[atoi(argv[2]) - 1];
    int bad = 0;
    for (int op = 0; op < 2; op++) {
      uint64_t n = 0;
      uint32_t first = 0;
      for (uint64_t x = 0; x < (1ull << 32); x++) {
        uint32_t want = native((uint32_t)x, op);
        uint32_t got = op ? sk_cpu_estimate_rsqrt(t, (uint32_t)x) : sk_cpu_estimate_rcp(t, (uint32_t)x);
        if (want != got && !n++) first = (uint32_t)x;
      }
      printf("%s mismatches %llu", op ? "rsqrt" : "rcp", (unsigned long long)n);
      if (n) printf(" (first input %08x)", first);
      printf("\n");
      bad |= n != 0;
    }
    return bad;
  }
#endif
  fprintf(stderr, "usage: estimates dump | vendor | hash V | check V\n");
  return 2;
}

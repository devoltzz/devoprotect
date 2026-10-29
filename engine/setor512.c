// The sector codec in C, over zopfli and zlib-ng.
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "zlib.h"
#include "zopfli.h"

#if defined(__wasm__)
#  define S512_EXPORT(name) __attribute__((export_name(name)))
#elif defined(_WIN32)
#  define S512_EXPORT(name) __declspec(dllexport)
#else
#  define S512_EXPORT(name) __attribute__((visibility("default")))
#endif

static long codifica(const uint8_t *s, size_t L, int margem, int modo, uint8_t *out, uint8_t *z, size_t zcap) {
  uLongf zl = (uLongf)zcap;
  const uint8_t *melhor;
  size_t ml;
  unsigned char *zo = 0;
  size_t zol = 0;
  if (compress2(z, &zl, s, (uLong)L, 9) != Z_OK) return -1;
  melhor = z;
  ml = zl;
  if (modo == 0 && (margem < 0 || 1 + ml < L + (size_t)margem)) {
    ZopfliOptions o;
    ZopfliInitOptions(&o);
    o.numiterations = 15;
    o.blocksplitting = 0;
    ZopfliCompress(&o, ZOPFLI_FORMAT_ZLIB, s, L, &zo, &zol);
    if (zo && zol < ml) {
      melhor = zo;
      ml = zol;
    }
  }
  if (1 + ml < L) {
    out[0] = 0x02;
    memcpy(out + 1, melhor, ml);
    ml += 1;
  } else {
    memcpy(out, s, L);
    ml = L;
  }
  free(zo);
  return (long)ml;
}

S512_EXPORT("s512_fatia")
long s512_fatia(const uint8_t *in, size_t n, size_t setor, int margem, int modo, uint8_t *out, uint32_t *lens) {
  size_t zcap, i, k = 0, pos = 0;
  uint8_t *z;
  if (!setor || (modo != 0 && modo != 1)) return -1;
  zcap = compressBound((uLong)setor) + 16;
  z = (uint8_t *)malloc(zcap);
  if (!z) return -1;
  for (i = 0; i < n; i += setor, k++) {
    size_t L = n - i < setor ? n - i : setor;
    long r = codifica(in + i, L, margem, modo, out + pos, z, zcap);
    if (r < 0) {
      free(z);
      return -1;
    }
    lens[k] = (uint32_t)r;
    pos += (size_t)r;
  }
  free(z);
  return (long)k;
}

S512_EXPORT("s512_buffer")
uint8_t *s512_buffer(size_t n) {
  static uint8_t *p = 0;
  static size_t cap = 0;
  if (n > cap) {
    free(p);
    p = (uint8_t *)malloc(n);
    cap = p ? n : 0;
  }
  return p;
}

// largely adapted from
// https://oneapi-src.github.io/oneDNN/v2/convolution_example_cpp.html licensed
// by Intel Corporation, 2020 under Apache 2.0

#include <benchmark/benchmark.h>

#include <algorithm>
#include <cassert>
#include <cmath>
#include <numeric>
#include <oneapi/dnnl/dnnl.hpp>
#include <vector>

#include "conv.h"
#include "onednn_conv.hpp"

void conv_oneDNN(benchmark::State &state) {
  const long                        // Benchmark inputs.
      batch_size = state.range(0),  // e.g. 4
      in_dim = state.range(1),      // e.g. 224
      in_chan = state.range(2),     // e.g. 3
      out_chan = state.range(3),    // e.g. 64
      kern_sz = state.range(4),     // e.g. 7
      pad = state.range(5),         // e.g. 3
      stride = state.range(6);      // e.g. 2

  conv_instance ci{batch_size, in_dim, in_dim, in_chan, out_chan, kern_sz, pad,
  stride};

  OneDNN_Conv reference{ci};
  for ([[maybe_unused]] auto _ : state) {
    reference.run();
  }
}

BENCHMARK(conv_oneDNN)  // N in-dim in-chan out-chan kern-dim pad str
    ->Args({4, 224, 3, 64, 7, 3, 2})     // conv1
    ->Args({4, 56, 64, 64, 3, 1, 1})     // conv3/7/10
    ->Args({4, 28, 128, 128, 3, 1, 2})   // conv13
    ->Args({4, 56, 64, 64, 3, 0, 1})     // test size
    ->Args({5, 102, 128, 128, 3, 0, 1})  // Halide size
    ;

void conv_SYS_ATL(benchmark::State &state) {
  const long                        // Benchmark inputs.
      batch_size = state.range(0),  // e.g. 4
      in_dim = state.range(1),      // e.g. 224
      in_chan = state.range(2),     // e.g. 3
      out_chan = state.range(3),    // e.g. 64
      kern_sz = state.range(4),     // e.g. 7
      pad = state.range(5),         // e.g. 3
      stride = state.range(6);      // e.g. 2

  conv_instance ci{batch_size, in_dim, in_dim, in_chan, out_chan, kern_sz, pad, stride};

  assert(ci.IW == ci.IH);
  assert(ci.OW == ci.OH);
  assert(ci.KW == ci.KH);

  float scale = 1.0f;

  for ([[maybe_unused]] auto _ : state) {
    conv(nullptr, (int)ci.OH, (int)ci.OW, (int)ci.OC, (int)ci.KW, (int)ci.IC,
    (int)ci.IH, (int)ci.IW,
         &scale, (int)batch_size, ci.src_data.data(), ci.dst_data.data(),
         ci.weights_data.data(), ci.bias_data.data());
  }
}

BENCHMARK(conv_SYS_ATL)  // N in-dim in-chan out-chan kern-dim pad str
    ->Args({4, 56, 64, 64, 3, 0, 1})     // test size
    ->Args({5, 102, 128, 128, 3, 0, 1})  // Halide size
    ;

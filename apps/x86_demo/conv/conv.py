from __future__ import annotations

from SYS_ATL import *
# from SYS_ATL.builtins import *
from SYS_ATL.syntax import *


@proc
def conv(
        out_h: size,
        out_w: size,
        out_channel: size,
        kernel_dim: size,
        in_channel: size,
        in_h: size,
        in_w: size,
        scale: f32,
        # act: bool,
        batch_size: size,
        inp: f32[batch_size, in_h, in_w, in_channel],
        output: f32[batch_size, out_h, out_w, out_channel],
        weights: f32[kernel_dim, kernel_dim, in_channel, out_channel],
        bias: f32[out_channel],
):
    assert out_h == in_h - kernel_dim + 1
    assert out_w == in_w - kernel_dim + 1

    for n in par(0, batch_size):
        for orow in par(0, out_h):
            for ocol in par(0, out_w):
                for och in par(0, out_channel):

                    res: f32
                    res = bias[och]
                    for krow in par(0, kernel_dim):
                        for kcol in par(0, kernel_dim):
                            for kch in par(0, in_channel):
                                # todo: add padding, stride
                                res += (weights[krow, kcol, kch, och] *
                                        inp[n, orow + krow, ocol + kcol, kch])

                    res = relu(res)
                    output[n, orow, ocol, och] = res * scale

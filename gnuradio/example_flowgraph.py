#!/usr/bin/env python3
"""
example_flowgraph.py -- minimal GNU Radio flowgraph that passes a signal through
the live FSO turbulence channel. No modem, no hardware.

    source (complex sine) -> throttle -> FSO channel (blk) -> head -> file sink

Run the server first (examples/run_server.sh), then:

    python3 gnuradio/example_flowgraph.py --nsamples 2000000 --out out.cf32

Inspect out.cf32 (interleaved complex float32): its envelope is your input
scaled by the streamed gain h(t). This is the same block you would drop into
GNU Radio Companion as a "Python Block" pointing at your own transmit chain.

Requires: GNU Radio 3.8+ (system package) and a running channel server.
"""

import argparse
import os
import sys

# import the embedded block from this directory
sys.path.insert(0, os.path.dirname(__file__))
from epy_fso_channel import blk as FsoChannel        # noqa: E402

from gnuradio import gr, blocks, analog               # noqa: E402


class ExampleGraph(gr.top_block):
    def __init__(self, samp_rate, nsamples, out_path):
        gr.top_block.__init__(self, "FSO channel example")
        src = analog.sig_source_c(samp_rate, analog.GR_COS_WAVE,
                                  1000.0, 1.0, 0.0)          # 1 kHz complex tone
        throttle = blocks.throttle(gr.sizeof_gr_complex, samp_rate)
        fso = FsoChannel(gain_endpoint="tcp://127.0.0.1:50003",
                         sample_rate=samp_rate)
        head = blocks.head(gr.sizeof_gr_complex, int(nsamples))
        sink = blocks.file_sink(gr.sizeof_gr_complex, out_path)
        sink.set_unbuffered(False)
        self.connect(src, throttle, fso, head, sink)


def main():
    ap = argparse.ArgumentParser(description="Minimal FSO channel flowgraph")
    ap.add_argument("--samp-rate", type=float, default=1e6)
    ap.add_argument("--nsamples", type=int, default=1_000_000)
    ap.add_argument("--out", default="out.cf32")
    args = ap.parse_args()
    tb = ExampleGraph(args.samp_rate, args.nsamples, args.out)
    print("running... (needs the channel server on :50003)")
    tb.run()
    print("done -> %s" % args.out)


if __name__ == "__main__":
    main()

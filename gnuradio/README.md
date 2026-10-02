# GNU Radio integration

`epy_fso_channel.py` is a GNU Radio Embedded Python Block that applies the live
turbulence gain to a complex baseband stream:

```
y[n] = h(t_n) * x[n]      (IM/DD framing: h real, >= 0)
```

It subscribes to the channel server's gain stream (`tcp://127.0.0.1:50003`),
upsamples the slow gain to the signal rate by **linear interpolation**, and
never blocks the scheduler. Every dropped message, loop seam, or buffer
starvation is counted and printed when the flowgraph stops.

Latency is bounded: if more than 4 x the server lookahead (1 s) of gain is ever
buffered, the oldest samples are dropped as a counted, logged **resync**. The
shutdown summary reports gaps, lost samples, loops, starvation (start-up vs
in-run, plus the longest in-run episode), resyncs, max/mean delivery
latency, and the mean signal power into and out of the block
(`mean_power_in` = mean |x|², `mean_power_out` = mean |h·x|²), which lets
you calibrate SNR against any noise you add downstream. Stop the flowgraph
gracefully (`tb.stop(); tb.wait()`, as `example_flowgraph.py` does on
Ctrl+C) or the summary and logs are lost. Optional logs, enabled by environment variable:

| Variable | Contents |
|---|---|
| `FSO_EVENT_LOG=path.csv` | every gap / resync / epoch reset: wall time, absolute gain-index range, count |
| `FSO_INDEX_LOG=path.csv` | the gain index applied at each frame boundary (`FSO_FRAME_LEN` signal samples, default 33792), for index-exact alignment of frames with the server's fade log |
| `FSO_DIAG_LOG=path.csv` | decoder state at ~10 Hz (diagnostics) |

## Use it in GNU Radio Companion

1. Add a **Python Block** to your flowgraph and set its source to the contents
   of `epy_fso_channel.py` (or `import` it — see below).
2. Instantiate it as `blk(gain_endpoint="tcp://127.0.0.1:50003", sample_rate=<your fs>)`.
3. Wire it into your chain as a complex-in / complex-out block, typically
   between your transmit chain and the receiver front end, with additive noise
   applied **after** it if you want `y = h·x + w`.
4. Start the channel server (`examples/run_server.sh`) before running the graph.

## Use it from a hand-built flowgraph

```python
from epy_fso_channel import blk as FsoChannel
fso = FsoChannel(gain_endpoint="tcp://127.0.0.1:50003", sample_rate=30.72e6)
self.connect(tx_chain, fso, rx_chain)
```

`example_flowgraph.py` is a complete, runnable minimal example
(sine → throttle → FSO channel → file sink).

## SNR convention (important for labelling)

The block multiplies the **complex amplitude** by `h` and any AWGN you add is
signal-independent, so the received electrical SNR scales as `h²`:

```
SNR_dB = 20·log10(h) + offset
```

Use this (not `10·log10`) when converting streamed gain to an SNR label. See the
main `SETUP.md` for the full reasoning.

## Notes

- The wire-protocol decode (`GainStreamDecoder`) is pure numpy/struct with no
  GNU Radio or ZMQ dependency, so you can unit-test or reuse it standalone.
- The protocol constants are an inline copy of `fso_twin/fso_stream_proto.py`,
  kept byte-identical so a bare GRC paste works without a Python path set up.

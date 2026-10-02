#!/usr/bin/env bash
#
# run_server.sh -- start the FSO channel server (and optionally the Qt GUI).
#
# No modem, no TUN interface, no sudo -- just the physics + streaming server,
# so you can attach your own consumer (see minimal_subscriber.py or the GNU
# Radio block). Ctrl+C stops everything.
#
#   ./run_server.sh                     # weak scheme, server only
#   SCHEME=moderate ./run_server.sh     # pick weak | moderate | strong
#   GUI=1 ./run_server.sh               # also launch the control/telemetry GUI
#
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
TWIN="$HERE/../fso_twin"
SCHEME="${SCHEME:-weak}"
SEED="${SEED:-20240}"
GUI="${GUI:-0}"

SERVER_PID=""; GUI_PID=""
cleanup() { echo; echo "[run_server] stopping..."
    [[ -n "$GUI_PID" ]] && kill "$GUI_PID" 2>/dev/null
    [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null
    exit 0; }
trap cleanup INT TERM

echo "[run_server] starting server (scheme=$SCHEME, seed=$SEED) on :50003/:50004..."
# exec: SERVER_PID must be the python process itself, so Ctrl+C really stops
# it (otherwise only the subshell dies and the server keeps :50003/:50004)
( cd "$TWIN" && exec python3 server.py --scheme "$SCHEME" --seed "$SEED" ) &
SERVER_PID=$!
sleep 1

if [[ "$GUI" == "1" ]]; then
    echo "[run_server] starting control GUI..."
    ( cd "$TWIN" && exec python3 control_gui.py ) &
    GUI_PID=$!
fi

echo "[run_server] running. Attach a consumer, e.g.:"
echo "    python3 examples/minimal_subscriber.py --seconds 5 --wind 8"
echo "[run_server] Ctrl+C to stop."
wait "$SERVER_PID"

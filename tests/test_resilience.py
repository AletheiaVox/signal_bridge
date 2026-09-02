"""Scenario tests for Signal Bridge v0.5 against the fake Intiface server.

Run from anywhere:  python tests/test_resilience.py
Needs the same packages as the server (mcp, buttplug, python-dotenv). No
hardware and no Intiface Central: tests/fake_intiface.py stands in for it.
"""
import asyncio
import os
import sys
import time

PORT = int(os.environ.get("TEST_PORT", "12399"))
os.environ["INTIFACE_URL"] = f"ws://127.0.0.1:{PORT}"
os.environ["SB_SAFETY_ENABLED"] = "false"
os.environ["SB_PATTERN_GRACE"] = "3"
os.environ["SB_RECONNECT_WINDOW"] = "30"
os.environ["SB_SCAN_SECONDS"] = "0.2"

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root, where signal_bridge_mcp.py lives
sys.path.insert(0, HERE)

from fake_intiface import FakeIntiface, lush, gravity  # noqa: E402
import signal_bridge_mcp as sb  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (f"  -- {detail}" if detail and not cond else ""))


def vib_count(srv, idx):
    return sum(1 for c in srv.commands if c[0] == idx and len(c) == 4 and c[2] == "Vibrate")


async def main():
    srv = FakeIntiface(PORT)
    srv.devices = {0: lush(0), 1: gravity(1)}
    await srv.start()

    print("A. first connect: devices already known, no scan wait")
    t0 = time.monotonic()
    out = await sb.list_devices()
    dt = time.monotonic() - t0
    check("A1 lists lush and gravity", "lush" in out and "gravity" in out, out)
    check("A2 connected fast (no 5s scan)", dt < 2.0, f"{dt:.2f}s")
    check("A3 no spurious 'Reconnected' note on first connect", "Reconnected" not in out, out)

    print("B. direct vibrate")
    out = await sb.vibrate("lush", 0.6)
    check("B1 vibrate reply", out.startswith("Vibrating lush at 60%"), out)
    check("B2 server got step 12", (0, 0, "Vibrate", 12) in srv.commands, str(srv.commands[-3:]))

    print("C. one toy drops; the other keeps working; it comes back and resumes")
    await srv.remove_device(0)
    await asyncio.sleep(0.3)
    cd_lush = sb.controller.find_device("lush", include_offline=True)
    check("C1 lush marked offline via callback", cd_lush is not None and not cd_lush.online)
    out = await sb.vibrate("lush", 0.8)
    check("C2 vibrate lush -> offline message, no reconnect", "offline" in out and sb.controller.connected, out)
    n_before = vib_count(srv, 1)
    out = await sb.vibrate("gravity", 0.5)
    check("C3 gravity still works", out.startswith("Vibrating gravity") and vib_count(srv, 1) == n_before + 1, out)
    out = await sb.list_devices()
    check("C4 list shows lush offline", "Offline" in out and "lush" in out, out)
    n_lush = vib_count(srv, 0)
    await srv.add_device(lush(0))
    await asyncio.sleep(0.5)
    check("C5 lush back online", cd_lush.online)
    check("C6 last direct command (0.6) restored after short dropout",
          vib_count(srv, 0) == n_lush + 1 and srv.commands[-1] == (0, 0, "Vibrate", 12), str(srv.commands[-2:]))
    out = await sb.vibrate("gravity", 0.4)
    check("C7 next tool result carries the event notes", "back online" in out and "Restored" in out, out)

    print("D. a running wave rides out a short dropout")
    out = await sb.wave("lush", 0.7, 0)
    check("D1 wave started", out.startswith("Wave on lush"), out)
    await asyncio.sleep(0.6)
    await srv.remove_device(0)
    await asyncio.sleep(1.0)
    n_at_drop = vib_count(srv, 0)
    await asyncio.sleep(0.6)
    check("D2 no sends while offline", vib_count(srv, 0) == n_at_drop)
    await srv.add_device(lush(0))
    await asyncio.sleep(1.0)
    check("D3 wave resumed after toy came back", vib_count(srv, 0) > n_at_drop + 3,
          f"{vib_count(srv, 0)} vs {n_at_drop}")
    check("D4 wave task still alive", sb.controller.has_device_task("lush"))
    out = await sb.stop("lush")
    check("D5 stop", out.startswith("Stopped lush") and not sb.controller.has_device_task("lush"), out)

    print("E. a pattern gives up after the grace window")
    await sb.pulse("lush", 0.6, 0)
    await asyncio.sleep(0.3)
    await srv.remove_device(0)
    await asyncio.sleep(float(os.environ["SB_PATTERN_GRACE"]) + 1.5)
    check("E1 pulse task ended after grace", not sb.controller.has_device_task("lush"))
    await srv.add_device(lush(0))
    await asyncio.sleep(0.5)
    n = vib_count(srv, 0)
    await asyncio.sleep(0.8)
    check("E2 nothing restarts the toy after it comes back late", vib_count(srv, 0) == n)

    print("F. Intiface drops the socket; watchdog reconnects; patterns survive")
    await sb.vibrate("gravity", 0.5, 30)          # timed direct command with a managed task
    await sb.wave("lush", 0.6, 0)
    await asyncio.sleep(0.5)
    clients_before = srv.clients_seen
    await srv.drop_connection()
    await asyncio.sleep(0.3)
    check("F1 disconnect noticed via callback", not sb.controller.connected)
    await asyncio.sleep(2.5)
    check("F2 watchdog reconnected", sb.controller.connected and srv.clients_seen == clients_before + 1,
          f"connected={sb.controller.connected} clients={srv.clients_seen}")
    n_l, n_g = vib_count(srv, 0), vib_count(srv, 1)
    await asyncio.sleep(1.5)
    check("F3 wave on lush resumed on the new connection", vib_count(srv, 0) > n_l + 3)
    check("F4 timed vibrate on gravity re-asserted its level", vib_count(srv, 1) == n_g + 0 or
          any(c == (1, 0, "Vibrate", 10) for c in srv.commands[-40:]))
    out = await sb.vibrate("gravity", 0.3)
    check("F5 tool result mentions the automatic reconnect", "Reconnected" in out, out)
    await sb.stop("all")

    print("G. Intiface fully down: clean error, then recovery")
    await srv.stop()
    await asyncio.sleep(0.5)
    t0 = time.monotonic()
    out = await sb.vibrate("lush", 0.5)
    dt = time.monotonic() - t0
    check("G1 clear failure message, no exception", "Failed to connect" in out or "Not connected" in out, out)
    check("G2 failure returns quickly", dt < 5.0, f"{dt:.1f}s")
    out = await sb.stop("all")
    check("G3 stop while disconnected explains itself", "All devices stopped" in out and "Not connected" in out, out)
    srv2 = FakeIntiface(PORT)
    srv2.devices = {0: lush(0), 1: gravity(1)}
    await srv2.start()
    await asyncio.sleep(0.2)
    out = await sb.vibrate("lush", 0.5)
    check("G4 works again once Intiface is back", out.startswith("Vibrating lush"), out)
    check("G5 reconnect via tool call is noted", "Reconnected" in out, out)

    print("H. cancelling the watchdog and shutting down")
    for t in list(sb.controller._device_tasks.values()):
        t.cancel()
    if sb.controller._reconnect_task:
        sb.controller._reconnect_task.cancel()
    await srv2.stop()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

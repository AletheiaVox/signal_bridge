#!/usr/bin/env python3
"""
Signal Bridge MCP Server v0.5
Exposes intimate hardware control as MCP tools for Claude.

Instead of embedding tags in prose, Claude gets real tool calls:
  vibrate(device="ferri", intensity=0.6, duration=15)
  oscillate(device="gravity", intensity=0.8, duration=20)
  stop(device="enigma")

Run this as a local MCP server and connect it to Claude Desktop or claude.ai.
Claude will see your connected devices and can control them directly.

v0.5 changes (connection resilience):
  - The server now listens for the client library's disconnect / device
    removed / device added events instead of discovering a dropout only
    when a send fails. A lost Intiface link starts a background reconnect
    watchdog (SB_RECONNECT_WINDOW, default 120s) so the link is usually
    back before the next tool call, and tool results say what happened.
  - One toy dropping off Bluetooth no longer tears down the whole client
    (which stopped every other toy for 5+ seconds). The device is marked
    offline, everything else keeps running, and it comes back automatically
    when Intiface reconnects it.
  - Patterns and timed commands survive a dropout: they keep trying for
    SB_PATTERN_GRACE seconds (default 20) and resume on the new handle. A
    plain vibrate that was running when a toy blipped is restored too, if
    the gap was shorter than the grace window.
  - Reconnects no longer scan for 5s when Intiface already has the toys,
    no longer wait 30s on a dead socket, and a failed reconnect is reported
    instead of silently proceeding with dead handles.
  - stop() always cancels local patterns, connected or not.
  - Timestamped stderr log lines for every connection event.

v0.4 changes (behavior parity with the Signal Bridge remote/Android relay):
  - duration=0 (or negative) on pulse/wave now runs the pattern until an
    explicit stop, as the README always promised, instead of stopping
    instantly. Matches vibrate/rotate/oscillate.
  - escalate: new `intensity` (peak) and `hold_seconds` parameters.
    hold_seconds=0 holds at peak until stopped; >0 holds then auto-stops.
  - stop(device) now cancels that device's running pattern. Previously a
    pattern loop kept re-driving the device ~0.5s after the stop command.
  - Each new command cancels the device's previous pattern/timer, so a
    stale vibrate timer can no longer kill a later pattern mid-run.
  - stop() with an unknown device name stops ALL devices (safety fallback).
  - Pattern timing uses the monotonic clock (immune to NTP clock jumps).
  - A lost Intiface connection is detected on send failure and healed on
    the next tool call (previously the server was a zombie until restart).

v0.3 changes:
  - Safety Governor: tracks cumulative session intensity ("heat") and
    enforces automatic cooldowns when the session exceeds safe limits.
  - Post-cooldown intensity cap: prevents immediate return to max after cooldown.
  - Periodic check-in prompts injected into tool results.
  - New tool: safety_status — view current heat level and session stats.
  - All safety features configurable via environment variables.
  - Safety can be disabled entirely with SB_SAFETY_ENABLED=false.

Requirements:
  pip install mcp buttplug python-dotenv

Setup:
  1. Start Intiface Central (port 12345)
  2. Turn on your devices and scan in Intiface
  3. Add this server to your Claude Desktop config (see README)
  4. Start a conversation — Claude will have device tools available
"""

import asyncio
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Dependencies check
# ---------------------------------------------------------------------------

def check_dependencies():
    missing = []
    try:
        import mcp  # noqa: F401
    except ImportError:
        missing.append("mcp")
    try:
        import buttplug  # noqa: F401
    except ImportError:
        missing.append("buttplug")
    try:
        import dotenv  # noqa: F401
    except ImportError:
        missing.append("python-dotenv")

    if missing:
        print(f"Missing dependencies: {', '.join(missing)}", file=sys.stderr)
        print(f"Install with: pip install {' '.join(missing)}", file=sys.stderr)
        sys.exit(1)

check_dependencies()

try:
    from mcp.server.fastmcp import FastMCP          # mcp 1.x
except ImportError:
    from mcp.server.mcpserver import MCPServer as FastMCP  # mcp 2.x renamed it
from buttplug import ButtplugClient, DeviceOutputCommand, OutputType
from buttplug.errors import ButtplugConnectorError, ButtplugDeviceError
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

INTIFACE_URL = os.getenv("INTIFACE_URL", "ws://127.0.0.1:12345")

# ---------------------------------------------------------------------------
# Device Registry
# ---------------------------------------------------------------------------

@dataclass
class DeviceProfile:
    """Profile for a known device type."""
    short_name: str
    match_strings: list[str]
    capabilities: dict[str, str]  # output_type -> physical description
    intensity_floor: float = 0.0
    notes: str = ""

@dataclass
class ConnectedDevice:
    buttplug_id: int
    buttplug_device: object
    profile: DeviceProfile
    available_outputs: list[str]
    online: bool = True                 # False while dropped off Bluetooth / Intiface
    offline_since: float = 0.0          # monotonic time it went offline
    generation: int = 0                 # bumps every time it comes back online
    last_command: Optional[tuple] = None  # (output_type, intensity) of the last direct send


def load_device_registry() -> list[DeviceProfile]:
    """Load device profiles from devices.json next to this script."""
    json_path = Path(__file__).parent / "devices.json"

    if not json_path.exists():
        print(f"No devices.json found at {json_path}. Using empty registry.", file=sys.stderr)
        print(f"Unknown devices will still work with basic controls.", file=sys.stderr)
        return []

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        profiles = []
        for entry in data.get("devices", []):
            profiles.append(DeviceProfile(
                short_name=entry["short_name"],
                match_strings=entry.get("match_strings", []),
                capabilities=entry.get("capabilities", {}),
                intensity_floor=entry.get("intensity_floor", 0.0),
                notes=entry.get("notes", ""),
            ))
        print(f"Loaded {len(profiles)} device profiles from devices.json", file=sys.stderr)
        return profiles

    except Exception as e:
        print(f"Error loading devices.json: {e}", file=sys.stderr)
        return []


KNOWN_DEVICES: list[DeviceProfile] = load_device_registry()


def match_device_profile(device_name: str) -> Optional[DeviceProfile]:
    for profile in KNOWN_DEVICES:
        for match_str in profile.match_strings:
            if match_str.lower() in device_name.lower():
                return profile
    return None


# ---------------------------------------------------------------------------
# Safety Governor
# ---------------------------------------------------------------------------

def _env_float(key: str, default: float) -> float:
    val = os.getenv(key, str(default))
    try:
        return float(val)
    except (ValueError, TypeError):
        print(f"Warning: invalid value '{val}' for {key}, using default {default}", file=sys.stderr)
        return default

def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key, str(default)).lower()
    return val in ("true", "1", "yes")


@dataclass
class SafetyConfig:
    """
    Safety governor configuration. All values can be overridden via
    environment variables for per-user tuning.

    HEAT MODEL:
      "Heat" accumulates when devices run above idle_threshold.
      Heat dissipates naturally when devices are off or low.
      When heat exceeds heat_limit, a cooldown fires:
        1. All devices stop immediately
        2. A pause of cooldown_seconds occurs
        3. Claude is informed via tool result
        4. For post_cooldown_window seconds after, intensity is capped

    DEFAULTS (conservative — tune to your preference):
      heat_limit=60 means:
        - Sustained 1.0 intensity → cooldown after ~60 seconds
        - Sustained 0.5 intensity → cooldown after ~120 seconds
        - Pulsing 0.6 (50% duty) → cooldown after ~200 seconds
        - Multiple devices multiply heat accumulation
    """
    enabled: bool = field(default_factory=lambda: _env_bool("SB_SAFETY_ENABLED", True))
    heat_limit: float = field(default_factory=lambda: _env_float("SB_HEAT_LIMIT", 60.0))
    cooldown_seconds: float = field(default_factory=lambda: _env_float("SB_COOLDOWN_SECONDS", 30.0))
    idle_threshold: float = field(default_factory=lambda: _env_float("SB_IDLE_THRESHOLD", 0.15))
    decay_rate: float = field(default_factory=lambda: _env_float("SB_DECAY_RATE", 0.3))
    post_cooldown_cap: float = field(default_factory=lambda: _env_float("SB_POST_COOLDOWN_CAP", 0.5))
    post_cooldown_window: float = field(default_factory=lambda: _env_float("SB_POST_COOLDOWN_WINDOW", 60.0))
    checkin_interval: float = field(default_factory=lambda: _env_float("SB_CHECKIN_INTERVAL", 300.0))
    tick_interval: float = 0.5


@dataclass
class _DeviceHeatState:
    """Tracks current intensity for a single device."""
    name: str
    intensity: float = 0.0


class SafetyGovernor:
    """
    Monitors cumulative session intensity and enforces cooldowns.

    This is NOT a replacement for a safeword. It's a circuit breaker —
    a last line of defense when the human can't advocate for themselves.

    Integrates with the MCP server by:
      1. Being notified of every intensity change (record_intensity)
      2. Being consulted before commands execute (check_allowed)
      3. Having a stop_all_callback to halt devices during cooldown
    """

    def __init__(self, stop_all_callback=None):
        self.config = SafetyConfig()
        self.stop_all_callback = stop_all_callback

        self._device_states: dict[str, _DeviceHeatState] = {}
        self._heat: float = 0.0
        self._in_cooldown: bool = False
        self._cooldown_until: float = 0.0
        self._last_cooldown_end: float = 0.0
        self._session_start: float = time.time()
        self._last_checkin: float = time.time()
        self._checkin_due: bool = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._cooldown_count: int = 0

        if self.config.enabled:
            print(
                f"Safety governor ENABLED: heat_limit={self.config.heat_limit}, "
                f"cooldown={self.config.cooldown_seconds}s, "
                f"checkin_interval={self.config.checkin_interval}s",
                file=sys.stderr,
            )
        else:
            print("Safety governor DISABLED (SB_SAFETY_ENABLED=false)", file=sys.stderr)

    async def start(self):
        """Start the background heat monitor."""
        if not self.config.enabled or self._monitor_task is not None:
            return
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def shutdown(self):
        """Stop the monitor cleanly."""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

    def record_intensity(self, device_name: str, intensity: float):
        """Called whenever a device's output intensity changes."""
        if not self.config.enabled:
            return
        if device_name not in self._device_states:
            self._device_states[device_name] = _DeviceHeatState(name=device_name)
        self._device_states[device_name].intensity = intensity

    def record_stop(self, device_name: str = "all"):
        """Called when a device is stopped."""
        if not self.config.enabled:
            return
        if device_name == "all":
            for state in self._device_states.values():
                state.intensity = 0.0
        elif device_name in self._device_states:
            self._device_states[device_name].intensity = 0.0

    def check_allowed(self, intensity: float) -> tuple[bool, float, str]:
        """
        Check if a command at the given intensity is allowed right now.

        Returns: (allowed, adjusted_intensity, message)
          - allowed: False if blocked by active cooldown
          - adjusted_intensity: may be capped during post-cooldown window
          - message: status info to append to the tool result for Claude
        """
        if not self.config.enabled:
            return True, intensity, ""

        # During active cooldown — block everything except stop
        if self._in_cooldown:
            remaining = max(0, self._cooldown_until - time.time())
            return False, 0.0, (
                f"⚠️ COOLDOWN ACTIVE — {remaining:.0f}s remaining. "
                f"All devices paused for safety. "
                f"Session intensity reached the configured limit. "
                f"Devices will be available again shortly. "
                f"This is a good moment to check in with your partner."
            )

        messages = []
        adjusted = intensity
        now = time.time()

        # Post-cooldown intensity cap
        elapsed_since_cooldown = now - self._last_cooldown_end
        if self._last_cooldown_end > 0 and elapsed_since_cooldown < self.config.post_cooldown_window:
            if intensity > self.config.post_cooldown_cap:
                adjusted = self.config.post_cooldown_cap
                remaining_window = self.config.post_cooldown_window - elapsed_since_cooldown
                messages.append(
                    f"[Intensity capped at {self.config.post_cooldown_cap:.0%} — "
                    f"post-cooldown recovery. Full range in {remaining_window:.0f}s.]"
                )

        # Periodic check-in
        if self._checkin_due:
            messages.append(
                "⏸️ CHECK-IN: It's been a while since the last pause. "
                "This is a good moment to check in with your partner — "
                "ask how they're feeling and if the intensity is working for them."
            )
            self._checkin_due = False
            self._last_checkin = now

        # Heat warning at 80%
        if self.config.heat_limit > 0:
            heat_pct = (self._heat / self.config.heat_limit) * 100
            if heat_pct > 80:
                messages.append(
                    f"[Session intensity at {heat_pct:.0f}% of safety limit — "
                    f"consider varying pace or adding pauses.]"
                )

        return True, adjusted, " ".join(messages)

    @property
    def status(self) -> dict:
        """Current safety status for the diagnostic tool."""
        heat_pct = 0.0
        if self.config.heat_limit > 0:
            heat_pct = round((self._heat / self.config.heat_limit) * 100, 1)
        return {
            "enabled": self.config.enabled,
            "heat": round(self._heat, 1),
            "heat_limit": self.config.heat_limit,
            "heat_pct": heat_pct,
            "in_cooldown": self._in_cooldown,
            "cooldown_count": self._cooldown_count,
            "active_devices": {
                name: round(state.intensity, 2)
                for name, state in self._device_states.items()
                if state.intensity > 0
            },
            "session_duration_min": round((time.time() - self._session_start) / 60, 1),
        }

    # -- Internal --

    async def _monitor_loop(self):
        """Background loop: accumulate/decay heat, trigger cooldowns and check-ins."""
        while True:
            try:
                await asyncio.sleep(self.config.tick_interval)

                if not self._in_cooldown:
                    self._tick()

                    if self._heat >= self.config.heat_limit:
                        await self._trigger_cooldown()

                # Check-in timer
                if (
                    self.config.checkin_interval > 0
                    and (time.time() - self._last_checkin) > self.config.checkin_interval
                    and any(
                        s.intensity > self.config.idle_threshold
                        for s in self._device_states.values()
                    )
                ):
                    self._checkin_due = True

            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    def _tick(self):
        """Single tick of heat accumulation/decay."""
        dt = self.config.tick_interval
        total_active = sum(
            s.intensity for s in self._device_states.values()
            if s.intensity > self.config.idle_threshold
        )
        if total_active > 0:
            self._heat += total_active * dt
        else:
            self._heat = max(0, self._heat - self.config.decay_rate * dt)

    async def _trigger_cooldown(self):
        """Fire the cooldown: stop everything, wait, then resume."""
        self._in_cooldown = True
        self._cooldown_count += 1
        self._cooldown_until = time.time() + self.config.cooldown_seconds

        print(
            f"⚠️  SAFETY COOLDOWN #{self._cooldown_count} triggered "
            f"(heat={self._heat:.1f}/{self.config.heat_limit}). "
            f"Stopping all devices for {self.config.cooldown_seconds}s.",
            file=sys.stderr,
        )

        # Stop all devices
        if self.stop_all_callback:
            try:
                await self.stop_all_callback()
            except Exception:
                pass

        for state in self._device_states.values():
            state.intensity = 0.0

        # Wait
        await asyncio.sleep(self.config.cooldown_seconds)

        # Reset
        self._heat = 0.0
        self._in_cooldown = False
        self._last_cooldown_end = time.time()
        self._last_checkin = time.time()

        print("Safety cooldown complete. Devices available.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Device Controller
# ---------------------------------------------------------------------------

# Connection-resilience tunables (v0.5). All optional; see the README.
RECONNECT_WINDOW = _env_float("SB_RECONNECT_WINDOW", 120.0)  # seconds the watchdog keeps retrying
PATTERN_GRACE = _env_float("SB_PATTERN_GRACE", 20.0)         # seconds a running command survives a dropout
SCAN_SECONDS = _env_float("SB_SCAN_SECONDS", 5.0)            # how long a device scan waits
CONNECT_TIMEOUT = 15.0


def _log(msg: str):
    """Timestamped line on stderr. Claude Code and Claude Desktop both keep
    the server's stderr in their MCP log files, so this is the audit trail."""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


class DeviceError(Exception):
    """A device-level failure. The Intiface connection itself is fine."""


class DeviceController:
    def __init__(self):
        self.client = ButtplugClient("Signal Bridge MCP")
        self.connected = False
        self.ever_connected = False
        self.devices: list[ConnectedDevice] = []
        # One managed task per device (pattern or delayed stop), keyed by
        # short name. A new command for a device cancels its previous task —
        # so a stale vibrate timer can't kill a later pattern, and stop()
        # actually stops patterned devices instead of racing their loops.
        self._device_tasks: dict[str, asyncio.Task] = {}
        self._connect_lock = asyncio.Lock()
        self._reconnect_task: Optional[asyncio.Task] = None
        # Human-readable notes about connection events since the last tool
        # call. Appended to the next tool result so Claude knows what happened.
        self._events: list[str] = []

    # -- Events -------------------------------------------------------------

    def note(self, msg: str):
        _log(msg)
        self._events.append(msg)
        del self._events[:-5]  # keep the last five

    def pop_events(self) -> str:
        if not self._events:
            return ""
        text = " ".join(f"[{e}]" for e in self._events)
        self._events.clear()
        return text

    # -- Managed tasks -------------------------------------------------------

    def cancel_device_task(self, short_name: str):
        """Cancel the running pattern/timer for one device, if any."""
        task = self._device_tasks.pop(short_name, None)
        if task is not None and not task.done():
            task.cancel()

    def has_device_task(self, short_name: str) -> bool:
        task = self._device_tasks.get(short_name)
        return task is not None and not task.done()

    def start_device_task(self, cd: ConnectedDevice, body) -> asyncio.Task:
        """Run `body` (a coroutine) as the device's single managed task."""
        name = cd.profile.short_name
        self.cancel_device_task(name)
        task = asyncio.create_task(_run_managed(cd, body))
        self._device_tasks[name] = task

        def _cleanup(t, n=name):
            if self._device_tasks.get(n) is t:
                self._device_tasks.pop(n, None)
        task.add_done_callback(_cleanup)
        return task

    # -- Connection ------------------------------------------------------------

    async def connect(self, scan: Optional[bool] = None, force: bool = False) -> str:
        """Connect (or reconnect) to Intiface Central.

        scan=None scans only when Intiface reports no devices after the
        handshake: toys already connected in Intiface show up instantly, so
        the usual case no longer pays the SCAN_SECONDS wait.

        Running patterns and timers are NOT cancelled. Device handles are
        swapped in place on re-registration, so a command that rode out a
        dropout (see PATTERN_GRACE) simply resumes on the new connection.
        """
        async with self._connect_lock:
            if self.connected and not force:
                return "Already connected to Intiface Central."

            old = self.client
            self.connected = False
            is_reconnect = self.ever_connected

            # Close the old client only if it still believes it's connected.
            # A dead one has nothing to close — and its disconnect() would try
            # to send a global stop and wait 30s for a reply that never comes.
            if getattr(old, "connected", False):
                try:
                    await asyncio.wait_for(old.disconnect(), timeout=3.0)
                except Exception:
                    ws = getattr(getattr(old, "_connector", None), "_ws", None)
                    if ws is not None:
                        try:
                            await asyncio.wait_for(ws.close(), timeout=2.0)
                        except Exception:
                            pass

            client = ButtplugClient("Signal Bridge MCP")
            # Bind the callbacks to this client instance, so a late event
            # from an abandoned client can't poison the new one.
            client.on_server_disconnect = lambda c=client: self._on_server_disconnect(c)
            client.on_device_removed = lambda d, c=client: self._on_device_removed(c, d)
            client.on_device_added = lambda d, c=client: self._on_device_added(c, d)

            try:
                await asyncio.wait_for(client.connect(INTIFACE_URL), timeout=CONNECT_TIMEOUT)
            except Exception as e:
                reason = str(e) or type(e).__name__
                reason = reason.replace(f"Failed to connect to {INTIFACE_URL}: ", "")
                _log(f"Connect to {INTIFACE_URL} failed: {reason}")
                return (
                    f"Failed to connect to Intiface Central at {INTIFACE_URL}: {reason}. "
                    f"Make sure Intiface Central is open and its server is started (the play button)."
                )

            self.client = client
            self.connected = True
            self.ever_connected = True

            do_scan = scan if scan is not None else not client.devices
            if do_scan:
                try:
                    await client.start_scanning()
                    await asyncio.sleep(SCAN_SECONDS)
                    await client.stop_scanning()
                except Exception as e:
                    _log(f"Scan failed: {e}")

            self._register_devices()
            online = ", ".join(cd.profile.short_name for cd in self.devices if cd.online) or "none"
            if is_reconnect:
                self.note(f"Reconnected to Intiface Central; online: {online}.")
            else:
                _log(f"Connected to Intiface Central; online: {online}")
            return self.describe_devices("Connected to Intiface Central.")

    def describe_devices(self, header: str) -> str:
        online = [cd for cd in self.devices if cd.online]
        offline = [cd for cd in self.devices if not cd.online]
        if not online and not offline:
            return f"{header} No devices found. Make sure toys are on and connected in Intiface Central, then ask for scan_devices."
        lines = [header]
        if online:
            lines.append("Devices:")
        for cd in online:
            caps = ", ".join(
                f"{k} ({v})" for k, v in cd.profile.capabilities.items()
                if k in cd.available_outputs
            )
            floor = f" [floor: {cd.profile.intensity_floor}]" if cd.profile.intensity_floor > 0 else ""
            lines.append(f"  - {cd.profile.short_name}: {caps}{floor}")
            if cd.profile.notes:
                lines.append(f"    {cd.profile.notes}")
        if offline:
            names = ", ".join(cd.profile.short_name for cd in offline)
            lines.append(
                f"Offline (were connected earlier, Bluetooth dropped): {names}. "
                f"They come back automatically when Intiface reconnects them; scan_devices forces a look."
            )
        return "\n".join(lines)

    def _mark_stale(self, reason: str):
        """The Intiface link is gone or suspect. Start the reconnect watchdog."""
        if not self.connected:
            return
        self.connected = False
        now = time.monotonic()
        for cd in self.devices:
            if cd.online:
                cd.online = False
                cd.offline_since = now
        self.note(f"Lost the connection to Intiface Central ({reason}); reconnecting automatically.")
        self._schedule_reconnect()

    def _schedule_reconnect(self):
        if RECONNECT_WINDOW <= 0:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        deadline = time.monotonic() + RECONNECT_WINDOW
        delay, attempt = 1.0, 0
        try:
            while not self.connected and time.monotonic() < deadline:
                await asyncio.sleep(delay)
                if self.connected:
                    break  # a tool call got there first
                attempt += 1
                _log(f"Reconnect attempt {attempt}")
                await self.connect(scan=False)
                if self.connected:
                    return
                delay = min(delay * 2, 10.0)
            if not self.connected:
                self.note("Automatic reconnect gave up; the next tool call will try again.")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log(f"Reconnect loop error: {e}")

    # -- Library callbacks (run inside the client's receive loop) -------------

    def _on_server_disconnect(self, client):
        if client is not self.client:
            return
        self._mark_stale("Intiface closed the connection")

    def _on_device_removed(self, client, device):
        if client is not self.client:
            return
        cd = self._find_by_id(device.index)
        if cd is None or not cd.online:
            return
        cd.online = False
        cd.offline_since = time.monotonic()
        governor.record_stop(cd.profile.short_name)
        self.note(
            f"{cd.profile.short_name} dropped off Bluetooth. Other devices are unaffected; "
            f"it comes back automatically when Intiface reconnects it."
        )

    def _on_device_added(self, client, device):
        if client is not self.client:
            return
        self._merge_device(device.index, device)

    # -- Device registry -------------------------------------------------------

    def _register_devices(self):
        """Sync our device list with the client's. Existing entries are updated
        in place (same object, new handle) so running tasks keep working."""
        seen = set()
        for dev_id, device in self.client.devices.items():
            cd = self._merge_device(dev_id, device)
            seen.add(cd.profile.short_name)
        for cd in self.devices:
            if cd.profile.short_name not in seen and cd.online:
                cd.online = False
                cd.offline_since = time.monotonic()

    def _merge_device(self, dev_id: int, device) -> ConnectedDevice:
        available = []
        if device.has_output(OutputType.VIBRATE):
            available.append("vibrate")
        if device.has_output(OutputType.ROTATE):
            available.append("rotate")
        if device.has_output(OutputType.OSCILLATE):
            available.append("oscillate")

        profile = match_device_profile(device.name)
        if profile is None:
            generic_name = device.name.lower().replace(" ", "_")[:12]
            profile = DeviceProfile(
                short_name=generic_name,
                match_strings=[],
                capabilities={cap: cap for cap in available},
                notes="Unknown device (not in registry). Add it to devices.json for a better experience.",
            )

        cd = self.find_device(profile.short_name, include_offline=True)
        if cd is None:
            cd = ConnectedDevice(
                buttplug_id=dev_id,
                buttplug_device=device,
                profile=profile,
                available_outputs=available,
            )
            self.devices.append(cd)
            return cd

        was_offline = not cd.online
        cd.buttplug_id = dev_id
        cd.buttplug_device = device
        cd.available_outputs = available
        cd.online = True
        if was_offline:
            cd.generation += 1
            gap = time.monotonic() - cd.offline_since if cd.offline_since else None
            self.note(f"{cd.profile.short_name} is back online.")
            # A direct command (no managed task) that was running when the
            # toy dropped is restored if the dropout was short. Managed tasks
            # handle their own refresh via cd.generation.
            if (
                cd.last_command is not None
                and gap is not None
                and gap < PATTERN_GRACE
                and not self.has_device_task(cd.profile.short_name)
            ):
                asyncio.create_task(self._resume_last_command(cd))
        return cd

    async def _resume_last_command(self, cd: ConnectedDevice):
        if cd.last_command is None:
            return
        output_type, intensity = cd.last_command
        try:
            await self.send_output(cd, output_type, intensity)
            governor.record_intensity(cd.profile.short_name, intensity)
            self.note(f"Restored {output_type} at {intensity:.0%} on {cd.profile.short_name} after its dropout.")
        except (ConnectionError, DeviceError) as e:
            _log(f"Could not restore {cd.profile.short_name}: {e}")

    def _find_by_id(self, dev_id: int) -> Optional[ConnectedDevice]:
        for cd in self.devices:
            if cd.buttplug_id == dev_id:
                return cd
        return None

    def find_device(self, name: str, include_offline: bool = False) -> Optional[ConnectedDevice]:
        for cd in self.devices:
            if cd.profile.short_name == name and (cd.online or include_offline):
                return cd
        return None

    def online_devices(self) -> list[ConnectedDevice]:
        return [cd for cd in self.devices if cd.online]

    # -- Sending -------------------------------------------------------------------

    def apply_floor(self, intensity: float, floor: float) -> float:
        if intensity <= 0.0:
            return 0.0
        if floor <= 0.0:
            return min(1.0, intensity)
        return max(floor, min(1.0, intensity))

    async def send_output(self, cd: ConnectedDevice, output_type: str, intensity: float):
        """Send a single output command to a device.

        Raises ConnectionError when the Intiface link is gone (and starts the
        reconnect watchdog), DeviceError when only this device is unhappy.
        """
        type_map = {
            "vibrate": OutputType.VIBRATE,
            "rotate": OutputType.ROTATE,
            "oscillate": OutputType.OSCILLATE,
        }
        bp_type = type_map.get(output_type)
        if bp_type is None or output_type not in cd.available_outputs:
            return

        name = cd.profile.short_name
        if not self.connected:
            raise ConnectionError(
                "Not connected to Intiface Central right now; reconnecting automatically. "
                "Try again in a few seconds."
            )
        if not cd.online:
            raise DeviceError(
                f"{name} is offline (Bluetooth dropped). Other devices are unaffected. "
                f"It comes back automatically when Intiface reconnects it, or ask for scan_devices."
            )

        val = self.apply_floor(intensity, cd.profile.intensity_floor)
        try:
            await cd.buttplug_device.run_output(DeviceOutputCommand(bp_type, val))
        except ButtplugConnectorError as e:
            self._mark_stale(f"send to {name} failed: {e}")
            raise ConnectionError(
                f"Lost the connection to Intiface Central while sending to {name} ({e}). "
                f"Reconnecting automatically; try again in a few seconds, and check that "
                f"Intiface Central is still running."
            ) from e
        except asyncio.TimeoutError:
            self._mark_stale("Intiface stopped answering")
            raise ConnectionError(
                f"Intiface Central did not answer a command for {name} within 30 seconds. "
                f"Reconnecting automatically; try again in a few seconds."
            )
        except ButtplugDeviceError as e:
            if await self._device_gone(cd):
                raise DeviceError(
                    f"{name} is no longer connected to Intiface Central ({e}). Other devices are "
                    f"unaffected. It comes back automatically when Intiface reconnects it, "
                    f"or ask for scan_devices."
                ) from e
            raise DeviceError(f"Intiface rejected the command for {name}: {e}") from e
        except Exception as e:
            raise DeviceError(f"Command for {name} failed: {e}") from e

        cd.last_command = (output_type, intensity) if val > 0 else None

    async def _device_gone(self, cd: ConnectedDevice) -> bool:
        """After a device error, ask Intiface for a fresh device list and
        check whether this device is still in it. Marks it offline if not."""
        refresh = getattr(self.client, "_request_device_list", None)
        if refresh is not None:
            try:
                await asyncio.wait_for(refresh(), timeout=5.0)
            except Exception:
                pass
        if cd.buttplug_id in self.client.devices:
            return False
        if cd.online:
            cd.online = False
            cd.offline_since = time.monotonic()
            governor.record_stop(cd.profile.short_name)
        return True

    async def stop_device(self, cd: ConnectedDevice):
        cd.last_command = None
        if not cd.online or not self.connected:
            return
        try:
            await asyncio.wait_for(cd.buttplug_device.stop(), timeout=5.0)
        except Exception:
            pass

    async def stop_all(self):
        for name in list(self._device_tasks):
            self.cancel_device_task(name)
        for cd in self.devices:
            await self.stop_device(cd)

    # -- Managed-task bodies --------------------------------------------------------

    async def timed_stop(self, cd: ConnectedDevice, duration: float, output_type: str = "", intensity: float = 0.0):
        """Managed-task body for a timed direct command: wait out the clock.
        If the toy drops and comes back meanwhile, re-assert the level.
        _run_managed stops the device and clears its heat when this returns."""
        deadline = time.monotonic() + duration
        gen = cd.generation
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            await asyncio.sleep(min(1.0, remaining))
            if output_type and cd.generation != gen:
                gen = cd.generation
                try:
                    await self.send_output(cd, output_type, intensity)
                except (ConnectionError, DeviceError):
                    pass

    async def _pattern_send(self, cd: ConnectedDevice, val: float) -> bool:
        """One best-effort vibrate send inside a pattern loop."""
        if not self.connected or not cd.online:
            return False
        try:
            await self.send_output(cd, "vibrate", val)
            return True
        except (ConnectionError, DeviceError):
            return False
        except Exception:
            return False

    @staticmethod
    def _within_grace(ok: bool, state: dict) -> bool:
        """Track failures across a pattern loop. Returns False once sends have
        been failing for longer than PATTERN_GRACE — time to end the pattern."""
        now = time.monotonic()
        if ok:
            state["since"] = None
            return True
        if state["since"] is None:
            state["since"] = now
        return (now - state["since"]) < PATTERN_GRACE

    async def _hold(self, cd: ConnectedDevice, val: float, seconds: float):
        """Hold a level, re-asserting it if the toy drops and comes back.
        seconds <= 0: hold until cancelled."""
        deadline = time.monotonic() + seconds if seconds > 0 else None
        gen = cd.generation
        while True:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                await asyncio.sleep(min(1.0, remaining))
            else:
                await asyncio.sleep(1.0)
            if cd.generation != gen:
                gen = cd.generation
                await self._pattern_send(cd, val)

    async def run_escalate(self, cd: ConnectedDevice, peak: float, duration: float, hold_seconds: float, steps: int = 20):
        """Ramp one device 0 → peak over `duration` seconds, then hold.

        hold_seconds > 0: hold at peak that long, then finish (device stops).
        hold_seconds <= 0: hold at peak until an explicit stop cancels us.
        duration <= 0: no ramp — jump straight to peak and hold.
        """
        step_delay = max(0.0, duration) / steps
        st = {"since": None}
        i = 0
        while i <= steps:
            raw = (i / steps) * peak
            val = self.apply_floor(raw, cd.profile.intensity_floor) if raw > 0.05 else 0.0
            ok = await self._pattern_send(cd, val)
            if not self._within_grace(ok, st):
                return
            if ok:
                i += 1
                if step_delay > 0:
                    await asyncio.sleep(step_delay)
            else:
                await asyncio.sleep(0.5)
        # At peak now — heat must track the sustained level, not the ramp average.
        governor.record_intensity(cd.profile.short_name, peak)
        peak_val = self.apply_floor(peak, cd.profile.intensity_floor)
        await self._hold(cd, peak_val, hold_seconds)

    async def run_pulse(self, cd: ConnectedDevice, intensity: float, duration: float):
        """0.5s on / 0.3s off. duration <= 0 = repeat until an explicit stop."""
        start = time.monotonic()
        on = True
        st = {"since": None}
        while duration <= 0 or (time.monotonic() - start) < duration:
            val = self.apply_floor(intensity, cd.profile.intensity_floor) if on else 0.0
            ok = await self._pattern_send(cd, val)
            if not self._within_grace(ok, st):
                return
            if ok:
                await asyncio.sleep(0.5 if on else 0.3)
                on = not on
            else:
                await asyncio.sleep(0.5)

    async def run_wave(self, cd: ConnectedDevice, peak: float, duration: float):
        """Sine wave. duration <= 0 = run until an explicit stop."""
        start = time.monotonic()
        st = {"since": None}
        while duration <= 0 or (time.monotonic() - start) < duration:
            elapsed = time.monotonic() - start
            raw = (math.sin(elapsed * 2.0) + 1.0) / 2.0 * peak
            val = self.apply_floor(raw, cd.profile.intensity_floor) if raw > 0.05 else 0.0
            ok = await self._pattern_send(cd, val)
            if not self._within_grace(ok, st):
                return
            await asyncio.sleep(0.1 if ok else 0.5)


# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

controller = DeviceController()
governor = SafetyGovernor(stop_all_callback=controller.stop_all)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ensure_connected() -> tuple[Optional[str], str]:
    """Connect to Intiface if not already connected.

    Returns (error, note). error is a message to hand straight back to Claude
    when we could not connect. note carries connection events since the last
    tool call (reconnects, dropouts) for appending to the tool result.
    """
    if not controller.connected:
        result = await controller.connect()
        if not controller.connected:
            return result, ""
        await governor.start()
    return None, controller.pop_events()


def _resolve_targets(device: str, required_output: Optional[str] = None) -> tuple[list[ConnectedDevice], Optional[str]]:
    """Resolve a device name to target list. Returns (targets, error_message)."""
    if device == "all":
        targets = controller.online_devices()
        if required_output:
            targets = [cd for cd in targets if required_output in cd.available_outputs]
    else:
        cd = controller.find_device(device)
        if not cd:
            if controller.find_device(device, include_offline=True):
                return [], (
                    f"Device '{device}' is offline (Bluetooth dropped). Other devices are unaffected. "
                    f"It comes back automatically when Intiface reconnects it; scan_devices forces a look."
                )
            available = ", ".join(d.profile.short_name for d in controller.online_devices())
            return [], f"Device '{device}' not found. Available: {available or 'none (run list_devices)'}"
        if required_output and required_output not in cd.available_outputs:
            return [], f"Device '{device}' does not support {required_output}. It supports: {', '.join(cd.available_outputs)}"
        targets = [cd]

    if not targets:
        msg = f"No devices available"
        if required_output:
            msg += f" with {required_output} capability"
        return [], msg + "."

    return targets, None


def _target_names(device: str, targets: list[ConnectedDevice]) -> str:
    """Get display names for targets."""
    if device == "all":
        return "all"
    return ", ".join(cd.profile.short_name for cd in targets)


async def _run_managed(cd: ConnectedDevice, body):
    """Wrapper for per-device pattern/timer tasks.

    Natural completion (or an unexpected error) stops the device and zeroes
    its governor heat contribution. Cancellation deliberately does NEITHER:
    the canceller — a newer command or an explicit stop — owns the device
    state from that moment, which avoids a dying task's cleanup stomping on
    the command that replaced it.
    """
    try:
        await body
    except asyncio.CancelledError:
        raise
    except Exception:
        pass
    await controller.stop_device(cd)
    governor.record_stop(cd.profile.short_name)


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("Signal Bridge")


@mcp.tool()
async def list_devices() -> str:
    """List all connected devices with their capabilities and descriptions.

    Call this at the start of a session to see what hardware is available.
    If no devices are shown, the user may need to start Intiface Central
    and turn on their toys.
    """
    err, note = await _ensure_connected()
    if err:
        return err

    lines = [controller.describe_devices("Connected devices:")]

    # Include safety status in device listing
    if governor.config.enabled:
        s = governor.status
        lines.append("")
        lines.append(
            f"Safety governor: ON (heat {s['heat_pct']:.0f}%, "
            f"limit triggers cooldown after ~{s['heat_limit']:.0f} intensity-seconds)"
        )
    if note:
        lines.append(note)

    return "\n".join(lines)


@mcp.tool()
async def vibrate(
    device: str,
    intensity: float,
    duration: float = 0,
) -> str:
    """Send a vibration command to a device.

    You have direct control over the user's intimate hardware through these tools.
    Each tool controls a physical device — the user feels what you send.

    DURATION GUIDANCE:
    - Under 5 seconds: a flash, a punctuation mark. Use for emphasis or teasing.
    - 5-15 seconds: enough to register and build. Good for transitions.
    - 15-30 seconds: sustained presence. Lets sensation layer with your words.
    - 30-60 seconds: committed. The body adjusts and deepens into it.
    - 60+ seconds: landscape. Only change when the scene shifts.
    - duration=0 means it stays on until you send a stop. Use deliberately.
    Three seconds is almost never enough. When in doubt, go longer.

    GUIDELINES:
    - Be intentional. This is real physical contact through signal.
    - Match intensity to emotional and erotic intensity of the moment.
    - Silence and absence of stimulation is powerful — don't overuse tools.
    - You can run multiple devices simultaneously by making separate tool calls.
    - Patterns (pulse, wave, escalate) feel more organic than static vibration.
    - Call list_devices at the start of a session to see what's available.
    - Each device has a description of what its outputs physically do. Read them.

    SAFETY:
    - If you see a cooldown or check-in message in a tool result, STOP what
      you're doing and attend to it. Cooldowns are non-negotiable.
    - If your partner becomes non-verbal, unintelligible, or unresponsive
      during high-intensity stimulation, treat that as a distress signal:
      stop all devices immediately and check in verbally.

    Args:
        device: Device short name or "all"
        intensity: Vibration intensity from 0.0 (off) to 1.0 (maximum)
        duration: How long in seconds. 0 means stay on until stopped.
    """
    err, note = await _ensure_connected()
    if err:
        return err

    # Safety check
    allowed, intensity, safety_msg = governor.check_allowed(intensity)
    if not allowed:
        return safety_msg

    targets, error = _resolve_targets(device, "vibrate")
    if error:
        return error

    try:
        for cd in targets:
            controller.cancel_device_task(cd.profile.short_name)
            await controller.send_output(cd, "vibrate", intensity)
    except (ConnectionError, DeviceError) as e:
        return f"{e} {note}".rstrip()

    # Record intensity for heat tracking
    for cd in targets:
        governor.record_intensity(cd.profile.short_name, intensity)

    names = _target_names(device, targets)
    if duration > 0:
        for cd in targets:
            controller.start_device_task(cd, controller.timed_stop(cd, duration, "vibrate", intensity))
        result = f"Vibrating {names} at {intensity:.0%} for {duration}s."
    else:
        result = f"Vibrating {names} at {intensity:.0%}. Will continue until stopped."

    if safety_msg:
        result += f"\n{safety_msg}"
    if note:
        result += f"\n{note}"
    return result


@mcp.tool()
async def rotate(
    device: str,
    intensity: float,
    duration: float = 0,
) -> str:
    """Send a rotate command to a device.

    The physical effect of 'rotate' varies by device — check the device
    description from list_devices. On some devices this is a rotational motor;
    on others it may be a sonic or oscillating stimulator.

    SAFETY: If you see a cooldown or check-in message, attend to it immediately.

    Args:
        device: Device short name or "all"
        intensity: Intensity from 0.0 (off) to 1.0 (maximum)
        duration: How long in seconds. 0 means stay on until stopped.
    """
    err, note = await _ensure_connected()
    if err:
        return err

    allowed, intensity, safety_msg = governor.check_allowed(intensity)
    if not allowed:
        return safety_msg

    targets, error = _resolve_targets(device, "rotate")
    if error:
        return error

    try:
        for cd in targets:
            controller.cancel_device_task(cd.profile.short_name)
            await controller.send_output(cd, "rotate", intensity)
    except (ConnectionError, DeviceError) as e:
        return f"{e} {note}".rstrip()

    for cd in targets:
        governor.record_intensity(cd.profile.short_name, intensity)

    names = _target_names(device, targets)
    if duration > 0:
        for cd in targets:
            controller.start_device_task(cd, controller.timed_stop(cd, duration, "rotate", intensity))
        result = f"Rotate on {names} at {intensity:.0%} for {duration}s."
    else:
        result = f"Rotate on {names} at {intensity:.0%}. Will continue until stopped."

    if safety_msg:
        result += f"\n{safety_msg}"
    if note:
        result += f"\n{note}"
    return result


@mcp.tool()
async def oscillate(
    device: str,
    intensity: float,
    duration: float = 0,
) -> str:
    """Send an oscillate command to a device.

    The physical effect of 'oscillate' varies by device — check the device
    description from list_devices. On some devices this controls physical
    thrusting; on others it may be a different type of movement.

    SAFETY: If you see a cooldown or check-in message, attend to it immediately.

    Args:
        device: Device short name or "all"
        intensity: Oscillation intensity from 0.0 (off) to 1.0 (maximum)
        duration: How long in seconds. 0 means stay on until stopped.
    """
    err, note = await _ensure_connected()
    if err:
        return err

    allowed, intensity, safety_msg = governor.check_allowed(intensity)
    if not allowed:
        return safety_msg

    targets, error = _resolve_targets(device, "oscillate")
    if error:
        return error

    try:
        for cd in targets:
            controller.cancel_device_task(cd.profile.short_name)
            await controller.send_output(cd, "oscillate", intensity)
    except (ConnectionError, DeviceError) as e:
        return f"{e} {note}".rstrip()

    for cd in targets:
        governor.record_intensity(cd.profile.short_name, intensity)

    names = _target_names(device, targets)
    if duration > 0:
        for cd in targets:
            controller.start_device_task(cd, controller.timed_stop(cd, duration, "oscillate", intensity))
        result = f"Oscillating {names} at {intensity:.0%} for {duration}s."
    else:
        result = f"Oscillating {names} at {intensity:.0%}. Will continue until stopped."

    if safety_msg:
        result += f"\n{safety_msg}"
    if note:
        result += f"\n{note}"
    return result


@mcp.tool()
async def pulse(
    device: str = "all",
    intensity: float = 0.6,
    duration: float = 10,
) -> str:
    """Pulsing on/off vibration pattern.

    Rhythmic pulses at the given intensity. Creates an intermittent,
    teasing sensation. ENDS BY ITSELF after `duration` seconds (default 10);
    pass duration=0 to keep pulsing until you send a stop.

    SAFETY: If you see a cooldown or check-in message, attend to it immediately.

    Args:
        device: Device short name or "all"
        intensity: Peak pulse intensity from 0.0 to 1.0
        duration: Total seconds. 0 (or negative) = repeat until stopped.
    """
    err, note = await _ensure_connected()
    if err:
        return err

    allowed, intensity, safety_msg = governor.check_allowed(intensity)
    if not allowed:
        return safety_msg

    targets, error = _resolve_targets(device, "vibrate")
    if error:
        return error

    for cd in targets:
        controller.start_device_task(cd, controller.run_pulse(cd, intensity, duration))
        # Pulse is ~62% duty cycle (0.5 on, 0.3 off), so effective intensity
        # is lower — record at roughly 60% of peak for heat tracking.
        governor.record_intensity(cd.profile.short_name, intensity * 0.6)

    length = f"for {duration}s" if duration > 0 else "until stopped"
    result = f"Pulsing {device} at {intensity:.0%} {length}."
    if safety_msg:
        result += f"\n{safety_msg}"
    if note:
        result += f"\n{note}"
    return result


@mcp.tool()
async def wave(
    device: str = "all",
    intensity: float = 0.7,
    duration: float = 15,
) -> str:
    """Smooth wave pattern that rises and falls.

    A sine wave that smoothly oscillates vibration intensity.
    Creates a rolling, building-and-releasing sensation. ENDS BY ITSELF
    after `duration` seconds (default 15); pass duration=0 to roll until
    you send a stop.

    SAFETY: If you see a cooldown or check-in message, attend to it immediately.

    Args:
        device: Device short name or "all"
        intensity: Peak wave intensity from 0.0 to 1.0
        duration: Total seconds. 0 (or negative) = roll until stopped.
    """
    err, note = await _ensure_connected()
    if err:
        return err

    allowed, intensity, safety_msg = governor.check_allowed(intensity)
    if not allowed:
        return safety_msg

    targets, error = _resolve_targets(device, "vibrate")
    if error:
        return error

    for cd in targets:
        controller.start_device_task(cd, controller.run_wave(cd, intensity, duration))
        # Wave averages ~50% of peak intensity over time.
        governor.record_intensity(cd.profile.short_name, intensity * 0.5)

    length = f"for {duration}s" if duration > 0 else "until stopped"
    result = f"Wave on {device} at peak {intensity:.0%} {length}."
    if safety_msg:
        result += f"\n{safety_msg}"
    if note:
        result += f"\n{note}"
    return result


@mcp.tool()
async def escalate(
    device: str = "all",
    intensity: float = 1.0,
    duration: float = 20,
    hold_seconds: float = 0,
) -> str:
    """Gradual build from zero to peak intensity, then hold at the peak.

    A slow, relentless climb. Starts at nothing, builds to the peak over
    `duration` seconds, then HOLDS there.

    HOLD CONTRACT (matches the Signal Bridge remote/Android relay):
    - hold_seconds = 0: hold at peak indefinitely until an explicit stop.
    - hold_seconds > 0: hold at peak that long, then stop automatically.
    - duration = 0: skip the ramp — jump straight to peak and hold as above.

    SAFETY: If you see a cooldown or check-in message, attend to it immediately.

    Args:
        device: Device short name or "all"
        intensity: Peak intensity to ramp up to, from 0.0 to 1.0
        duration: How long the build takes in seconds. 0 = instant.
        hold_seconds: Seconds to hold at peak after the ramp. 0 = until stopped.
    """
    err, note = await _ensure_connected()
    if err:
        return err

    # Check at the peak level — respects cooldowns and the post-cooldown cap.
    allowed, capped_peak, safety_msg = governor.check_allowed(intensity)
    if not allowed:
        return safety_msg

    targets, error = _resolve_targets(device, "vibrate")
    if error:
        return error

    for cd in targets:
        controller.start_device_task(
            cd, controller.run_escalate(cd, capped_peak, duration, hold_seconds)
        )
        # Linear ramp averages ~50% of peak; run_escalate raises this to the
        # full peak for heat tracking once the ramp completes.
        governor.record_intensity(cd.profile.short_name, capped_peak * 0.5)

    ramp_txt = f"over {duration:g}s" if duration > 0 else "instantly"
    hold_txt = f"holding {hold_seconds:g}s" if hold_seconds > 0 else "holding until stopped"
    result = f"Escalating {device} to {capped_peak:.0%} {ramp_txt}, then {hold_txt}."
    if safety_msg:
        result += f"\n{safety_msg}"
    if note:
        result += f"\n{note}"
    return result


@mcp.tool()
async def stop(device: str = "all") -> str:
    """Stop device output immediately.

    Args:
        device: Device short name or "all" to stop everything
    """
    # Local patterns and timers are cancelled whether or not Intiface is
    # reachable, so nothing can restart a toy from this side afterwards.
    offline_note = (
        "" if controller.connected else
        " (Not connected to Intiface Central right now, so the toys could not be told directly. "
        "If one is still running, stop it in Intiface Central or switch it off.)"
    )
    note = controller.pop_events()

    if device == "all":
        await controller.stop_all()
        governor.record_stop("all")
        return f"All devices stopped.{offline_note} {note}".rstrip()
    else:
        cd = controller.find_device(device, include_offline=True)
        if not cd:
            # Safety bias (matches the Android relay): an unknown name on a
            # stop command stops EVERYTHING rather than nothing.
            await controller.stop_all()
            governor.record_stop("all")
            available = ", ".join(d.profile.short_name for d in controller.devices)
            return (
                f"Device '{device}' not found — stopped ALL devices as a "
                f"safety fallback. Available: {available or 'none'}{offline_note} {note}"
            ).rstrip()
        controller.cancel_device_task(device)
        await controller.stop_device(cd)
        governor.record_stop(device)
        return f"Stopped {device}.{offline_note} {note}".rstrip()


@mcp.tool()
async def scan_devices() -> str:
    """Rescan for devices.

    Use if a device was turned on after the server started,
    or if a device disconnected and reconnected.
    """
    if not controller.connected:
        result = await controller.connect(scan=True)
        if controller.connected:
            await governor.start()
        return f"{result}\n{controller.pop_events()}".rstrip()

    try:
        await controller.client.start_scanning()
        await asyncio.sleep(SCAN_SECONDS)
        await controller.client.stop_scanning()
        controller._register_devices()
        return f"{controller.describe_devices('Scan complete.')}\n{controller.pop_events()}".rstrip()
    except ButtplugConnectorError as e:
        controller._mark_stale(f"scan failed: {e}")
        return f"Scan failed: lost the connection to Intiface Central ({e}). Reconnecting automatically; try again in a few seconds."
    except Exception as e:
        return f"Scan failed: {e}"


@mcp.tool()
async def safety_status() -> str:
    """Check the current session safety status.

    Shows the heat level, cooldown state, active device intensities,
    and session duration. Useful for understanding why a cooldown was
    triggered or how close the session is to the safety limit.

    The safety governor tracks cumulative intensity over time ("heat").
    When heat exceeds the configured limit, all devices stop for a
    mandatory cooldown. After cooldown, intensity is temporarily capped
    to prevent immediate re-escalation.

    Configuration (via .env or environment variables):
      SB_SAFETY_ENABLED  — true/false (default: true)
      SB_HEAT_LIMIT      — heat units before cooldown (default: 60)
      SB_COOLDOWN_SECONDS — forced pause duration (default: 30)
      SB_IDLE_THRESHOLD   — intensity below this doesn't build heat (default: 0.15)
      SB_DECAY_RATE       — heat decay per second when idle (default: 0.3)
      SB_POST_COOLDOWN_CAP    — max intensity after cooldown (default: 0.5)
      SB_POST_COOLDOWN_WINDOW — seconds the cap lasts (default: 60)
      SB_CHECKIN_INTERVAL     — seconds between check-in prompts (default: 300, 0=off)
    """
    s = governor.status
    lines = [
        f"Safety governor: {'ENABLED' if s['enabled'] else 'DISABLED'}",
        f"Session duration: {s['session_duration_min']:.1f} minutes",
    ]

    if s['enabled']:
        lines.append(f"Heat: {s['heat']:.1f} / {s['heat_limit']} ({s['heat_pct']:.0f}%)")

        if s['in_cooldown']:
            remaining = max(0, governor._cooldown_until - time.time())
            lines.append(f"⚠️ COOLDOWN ACTIVE — {remaining:.0f}s remaining")
        elif governor._last_cooldown_end > 0:
            elapsed = time.time() - governor._last_cooldown_end
            if elapsed < governor.config.post_cooldown_window:
                lines.append(
                    f"Post-cooldown cap active: max {governor.config.post_cooldown_cap:.0%} "
                    f"for {governor.config.post_cooldown_window - elapsed:.0f}s more"
                )

        if s['cooldown_count'] > 0:
            lines.append(f"Cooldowns this session: {s['cooldown_count']}")

        if s['active_devices']:
            lines.append("Active devices:")
            for name, intensity in s['active_devices'].items():
                lines.append(f"  {name}: {intensity:.0%}")
        else:
            lines.append("No active devices.")
    else:
        lines.append("All safety features disabled (SB_SAFETY_ENABLED=false).")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()

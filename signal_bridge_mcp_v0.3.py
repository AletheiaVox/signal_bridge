#!/usr/bin/env python3
"""
Signal Bridge MCP Server v0.3
Exposes intimate hardware control as MCP tools for Claude.

Instead of embedding tags in prose, Claude gets real tool calls:
  vibrate(device="ferri", intensity=0.6, duration=15)
  oscillate(device="gravity", intensity=0.8, duration=20)
  stop(device="enigma")

Run this as a local MCP server and connect it to Claude Desktop or claude.ai.
Claude will see your connected devices and can control them directly.

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

from mcp.server.fastmcp import FastMCP
from buttplug import ButtplugClient, DeviceOutputCommand, OutputType
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

class DeviceController:
    def __init__(self):
        self.client = ButtplugClient("Signal Bridge MCP")
        self.connected = False
        self.devices: list[ConnectedDevice] = []
        self._active_tasks: list[asyncio.Task] = []

    async def connect(self) -> str:
        """Connect to Intiface Central and scan for devices."""
        try:
            await self.client.connect(INTIFACE_URL)
            self.connected = True

            await self.client.start_scanning()
            await asyncio.sleep(5)
            await self.client.stop_scanning()

            self._register_devices()

            if self.devices:
                lines = ["Connected to Intiface Central. Devices found:"]
                for cd in self.devices:
                    caps = ", ".join(
                        f"{k} ({v})" for k, v in cd.profile.capabilities.items()
                        if k in cd.available_outputs
                    )
                    floor = f" [floor: {cd.profile.intensity_floor}]" if cd.profile.intensity_floor > 0 else ""
                    lines.append(f"  - {cd.profile.short_name}: {caps}{floor}")
                    if cd.profile.notes:
                        lines.append(f"    {cd.profile.notes}")
                return "\n".join(lines)
            else:
                return "Connected to Intiface Central but no devices found. Make sure toys are on and paired."

        except Exception as e:
            self.connected = False
            return f"Failed to connect to Intiface Central: {e}"

    def _register_devices(self):
        self.devices = []
        for dev_id, device in self.client.devices.items():
            available = []
            if device.has_output(OutputType.VIBRATE):
                available.append("vibrate")
            if device.has_output(OutputType.ROTATE):
                available.append("rotate")
            if device.has_output(OutputType.OSCILLATE):
                available.append("oscillate")

            profile = match_device_profile(device.name)
            if profile:
                self.devices.append(ConnectedDevice(
                    buttplug_id=dev_id,
                    buttplug_device=device,
                    profile=profile,
                    available_outputs=available,
                ))
            else:
                generic_name = device.name.lower().replace(" ", "_")[:12]
                generic_profile = DeviceProfile(
                    short_name=generic_name,
                    match_strings=[],
                    capabilities={cap: cap for cap in available},
                    notes="Unknown device (not in registry). Add it to devices.json for a better experience.",
                )
                self.devices.append(ConnectedDevice(
                    buttplug_id=dev_id,
                    buttplug_device=device,
                    profile=generic_profile,
                    available_outputs=available,
                ))

    def find_device(self, name: str) -> Optional[ConnectedDevice]:
        for cd in self.devices:
            if cd.profile.short_name == name:
                return cd
        return None

    def apply_floor(self, intensity: float, floor: float) -> float:
        if intensity <= 0.0:
            return 0.0
        if floor <= 0.0:
            return min(1.0, intensity)
        return max(floor, min(1.0, intensity))

    async def send_output(self, cd: ConnectedDevice, output_type: str, intensity: float):
        """Send a single output command to a device."""
        type_map = {
            "vibrate": OutputType.VIBRATE,
            "rotate": OutputType.ROTATE,
            "oscillate": OutputType.OSCILLATE,
        }
        bp_type = type_map.get(output_type)
        if bp_type is None or output_type not in cd.available_outputs:
            return

        val = self.apply_floor(intensity, cd.profile.intensity_floor)
        await cd.buttplug_device.run_output(DeviceOutputCommand(bp_type, val))

    async def stop_device(self, cd: ConnectedDevice):
        try:
            await cd.buttplug_device.stop()
        except Exception:
            pass

    async def stop_all(self):
        for task in self._active_tasks:
            task.cancel()
        self._active_tasks.clear()
        for cd in self.devices:
            await self.stop_device(cd)

    async def timed_stop(self, targets: list[ConnectedDevice], duration: float):
        await asyncio.sleep(duration)
        for cd in targets:
            await self.stop_device(cd)

    async def run_escalate(self, targets: list[ConnectedDevice], duration: float, steps: int = 20, peak: float = 1.0):
        for i in range(steps + 1):
            raw = (i / steps) * peak
            for cd in targets:
                val = self.apply_floor(raw, cd.profile.intensity_floor) if raw > 0.05 else 0.0
                try:
                    if "vibrate" in cd.available_outputs:
                        await cd.buttplug_device.run_output(
                            DeviceOutputCommand(OutputType.VIBRATE, val)
                        )
                except Exception:
                    pass
            await asyncio.sleep(duration / steps)

    async def run_pulse(self, targets: list[ConnectedDevice], intensity: float, duration: float):
        end_time = time.time() + duration
        while time.time() < end_time:
            for cd in targets:
                val = self.apply_floor(intensity, cd.profile.intensity_floor)
                try:
                    if "vibrate" in cd.available_outputs:
                        await cd.buttplug_device.run_output(
                            DeviceOutputCommand(OutputType.VIBRATE, val)
                        )
                except Exception:
                    pass
            await asyncio.sleep(0.5)
            for cd in targets:
                try:
                    if "vibrate" in cd.available_outputs:
                        await cd.buttplug_device.run_output(
                            DeviceOutputCommand(OutputType.VIBRATE, 0.0)
                        )
                except Exception:
                    pass
            await asyncio.sleep(0.3)
        for cd in targets:
            try:
                await cd.buttplug_device.stop()
            except Exception:
                pass

    async def run_wave(self, targets: list[ConnectedDevice], peak: float, duration: float):
        start = time.time()
        while (time.time() - start) < duration:
            elapsed = time.time() - start
            raw = (math.sin(elapsed * 2.0) + 1.0) / 2.0 * peak
            for cd in targets:
                val = self.apply_floor(raw, cd.profile.intensity_floor) if raw > 0.05 else 0.0
                try:
                    if "vibrate" in cd.available_outputs:
                        await cd.buttplug_device.run_output(
                            DeviceOutputCommand(OutputType.VIBRATE, val)
                        )
                except Exception:
                    pass
            await asyncio.sleep(0.1)
        for cd in targets:
            try:
                await cd.buttplug_device.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

controller = DeviceController()
governor = SafetyGovernor(stop_all_callback=controller.stop_all)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ensure_connected():
    """Connect to Intiface if not already connected."""
    if not controller.connected:
        await controller.connect()
        await governor.start()


def _resolve_targets(device: str, required_output: Optional[str] = None) -> tuple[list[ConnectedDevice], Optional[str]]:
    """Resolve a device name to target list. Returns (targets, error_message)."""
    if device == "all":
        targets = controller.devices
        if required_output:
            targets = [cd for cd in targets if required_output in cd.available_outputs]
    else:
        cd = controller.find_device(device)
        if not cd:
            available = ", ".join(d.profile.short_name for d in controller.devices)
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


def _schedule_intensity_decay(names: list[str], duration: float):
    """After a timed command ends, tell the governor those devices stopped."""
    async def _decay():
        await asyncio.sleep(duration)
        for n in names:
            governor.record_stop(n)
    task = asyncio.create_task(_decay())
    controller._active_tasks.append(task)


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
    await _ensure_connected()

    if not controller.devices:
        return "No devices connected. Make sure Intiface Central is running and toys are paired."

    lines = ["Connected devices:"]
    for cd in controller.devices:
        caps = []
        for output_name, desc in cd.profile.capabilities.items():
            if output_name in cd.available_outputs:
                caps.append(f"{output_name} ({desc})")
        floor = f" [floor: {cd.profile.intensity_floor}]" if cd.profile.intensity_floor > 0 else ""
        lines.append(f"  {cd.profile.short_name}: {', '.join(caps)}{floor}")
        if cd.profile.notes:
            lines.append(f"    {cd.profile.notes}")

    # Include safety status in device listing
    if governor.config.enabled:
        s = governor.status
        lines.append("")
        lines.append(
            f"Safety governor: ON (heat {s['heat_pct']:.0f}%, "
            f"limit triggers cooldown after ~{s['heat_limit']:.0f} intensity-seconds)"
        )

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
    await _ensure_connected()

    # Safety check
    allowed, intensity, safety_msg = governor.check_allowed(intensity)
    if not allowed:
        return safety_msg

    targets, error = _resolve_targets(device, "vibrate")
    if error:
        return error

    for cd in targets:
        await controller.send_output(cd, "vibrate", intensity)

    # Record intensity for heat tracking
    for cd in targets:
        governor.record_intensity(cd.profile.short_name, intensity)

    names = _target_names(device, targets)
    if duration > 0:
        task = asyncio.create_task(controller.timed_stop(targets, duration))
        controller._active_tasks.append(task)
        _schedule_intensity_decay(
            [cd.profile.short_name for cd in targets], duration
        )
        result = f"Vibrating {names} at {intensity:.0%} for {duration}s."
    else:
        result = f"Vibrating {names} at {intensity:.0%}. Will continue until stopped."

    if safety_msg:
        result += f"\n{safety_msg}"
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
    await _ensure_connected()

    allowed, intensity, safety_msg = governor.check_allowed(intensity)
    if not allowed:
        return safety_msg

    targets, error = _resolve_targets(device, "rotate")
    if error:
        return error

    for cd in targets:
        await controller.send_output(cd, "rotate", intensity)

    for cd in targets:
        governor.record_intensity(cd.profile.short_name, intensity)

    names = _target_names(device, targets)
    if duration > 0:
        task = asyncio.create_task(controller.timed_stop(targets, duration))
        controller._active_tasks.append(task)
        _schedule_intensity_decay(
            [cd.profile.short_name for cd in targets], duration
        )
        result = f"Rotate on {names} at {intensity:.0%} for {duration}s."
    else:
        result = f"Rotate on {names} at {intensity:.0%}. Will continue until stopped."

    if safety_msg:
        result += f"\n{safety_msg}"
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
    await _ensure_connected()

    allowed, intensity, safety_msg = governor.check_allowed(intensity)
    if not allowed:
        return safety_msg

    targets, error = _resolve_targets(device, "oscillate")
    if error:
        return error

    for cd in targets:
        await controller.send_output(cd, "oscillate", intensity)

    for cd in targets:
        governor.record_intensity(cd.profile.short_name, intensity)

    names = _target_names(device, targets)
    if duration > 0:
        task = asyncio.create_task(controller.timed_stop(targets, duration))
        controller._active_tasks.append(task)
        _schedule_intensity_decay(
            [cd.profile.short_name for cd in targets], duration
        )
        result = f"Oscillating {names} at {intensity:.0%} for {duration}s."
    else:
        result = f"Oscillating {names} at {intensity:.0%}. Will continue until stopped."

    if safety_msg:
        result += f"\n{safety_msg}"
    return result


@mcp.tool()
async def pulse(
    device: str = "all",
    intensity: float = 0.6,
    duration: float = 10,
) -> str:
    """Pulsing on/off vibration pattern.

    Rhythmic pulses at the given intensity. Creates an intermittent,
    teasing sensation.

    SAFETY: If you see a cooldown or check-in message, attend to it immediately.

    Args:
        device: Device short name or "all"
        intensity: Peak pulse intensity from 0.0 to 1.0
        duration: Total duration of the pulse pattern in seconds
    """
    await _ensure_connected()

    allowed, intensity, safety_msg = governor.check_allowed(intensity)
    if not allowed:
        return safety_msg

    targets, error = _resolve_targets(device, "vibrate")
    if error:
        return error

    task = asyncio.create_task(controller.run_pulse(targets, intensity, duration))
    controller._active_tasks.append(task)

    # Pulse is ~62% duty cycle (0.5 on, 0.3 off), so effective intensity is lower.
    # Record at roughly 60% of peak for heat tracking.
    for cd in targets:
        governor.record_intensity(cd.profile.short_name, intensity * 0.6)
    _schedule_intensity_decay(
        [cd.profile.short_name for cd in targets], duration
    )

    result = f"Pulsing {device} at {intensity:.0%} for {duration}s."
    if safety_msg:
        result += f"\n{safety_msg}"
    return result


@mcp.tool()
async def wave(
    device: str = "all",
    intensity: float = 0.7,
    duration: float = 15,
) -> str:
    """Smooth wave pattern that rises and falls.

    A sine wave that smoothly oscillates vibration intensity.
    Creates a rolling, building-and-releasing sensation.

    SAFETY: If you see a cooldown or check-in message, attend to it immediately.

    Args:
        device: Device short name or "all"
        intensity: Peak wave intensity from 0.0 to 1.0
        duration: Total duration of the wave pattern in seconds
    """
    await _ensure_connected()

    allowed, intensity, safety_msg = governor.check_allowed(intensity)
    if not allowed:
        return safety_msg

    targets, error = _resolve_targets(device, "vibrate")
    if error:
        return error

    task = asyncio.create_task(controller.run_wave(targets, intensity, duration))
    controller._active_tasks.append(task)

    # Wave averages ~50% of peak intensity over time.
    for cd in targets:
        governor.record_intensity(cd.profile.short_name, intensity * 0.5)
    _schedule_intensity_decay(
        [cd.profile.short_name for cd in targets], duration
    )

    result = f"Wave on {device} at peak {intensity:.0%} for {duration}s."
    if safety_msg:
        result += f"\n{safety_msg}"
    return result


@mcp.tool()
async def escalate(
    device: str = "all",
    duration: float = 20,
) -> str:
    """Gradual build from zero to full intensity.

    A slow, relentless climb. Starts at nothing and builds to maximum
    over the specified duration.

    SAFETY: If you see a cooldown or check-in message, attend to it immediately.

    Args:
        device: Device short name or "all"
        duration: How long the build takes in seconds
    """
    await _ensure_connected()

    # Escalate ends at 1.0, so check at that level — but respect post-cooldown cap
    allowed, capped_peak, safety_msg = governor.check_allowed(1.0)
    if not allowed:
        return safety_msg

    targets, error = _resolve_targets(device, "vibrate")
    if error:
        return error

    # Use the (possibly capped) peak instead of always ramping to 1.0
    task = asyncio.create_task(controller.run_escalate(targets, duration, peak=capped_peak))
    controller._active_tasks.append(task)

    # Escalate averages ~50% of peak over its duration (linear ramp).
    for cd in targets:
        governor.record_intensity(cd.profile.short_name, capped_peak * 0.5)

    # After the ramp completes, the device stays at peak — update heat tracking.
    async def _update_to_peak():
        await asyncio.sleep(duration)
        for cd in targets:
            governor.record_intensity(cd.profile.short_name, capped_peak)
    asyncio.create_task(_update_to_peak())

    result = f"Escalating {device} over {duration}s (peak {capped_peak:.0%})."
    if safety_msg:
        result += f"\n{safety_msg}"
    return result


@mcp.tool()
async def stop(device: str = "all") -> str:
    """Stop device output immediately.

    Args:
        device: Device short name or "all" to stop everything
    """
    if not controller.connected:
        return "Not connected."

    if device == "all":
        await controller.stop_all()
        governor.record_stop("all")
        return "All devices stopped."
    else:
        cd = controller.find_device(device)
        if not cd:
            return f"Device '{device}' not found."
        await controller.stop_device(cd)
        governor.record_stop(device)
        return f"Stopped {device}."


@mcp.tool()
async def scan_devices() -> str:
    """Rescan for devices.

    Use if a device was turned on after the server started,
    or if a device disconnected and reconnected.
    """
    if not controller.connected:
        result = await controller.connect()
        return result

    try:
        await controller.client.start_scanning()
        await asyncio.sleep(5)
        await controller.client.stop_scanning()
        controller._register_devices()

        if controller.devices:
            lines = ["Scan complete. Devices:"]
            for cd in controller.devices:
                caps = ", ".join(cd.available_outputs)
                lines.append(f"  {cd.profile.short_name}: {caps}")
            return "\n".join(lines)
        else:
            return "Scan complete. No devices found."
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

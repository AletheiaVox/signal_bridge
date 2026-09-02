# ⚠️ Security Warning: Only Download Signal Bridge From This Repo

**Malware forks of Signal Bridge exist on GitHub.** These are copies of this project where the download links in the README have been replaced with links to malicious software.
 
This is the **only** legitimate source for Signal Bridge:

👉 **[`github.com/AletheiaVox/signal_bridge`](https://github.com/AletheiaVox/signal_bridge)** (Claude Desktop / local version - you're here)

👉 **[`github.com/AletheiaVox/signal_bridge_remote`](https://github.com/AletheiaVox/signal_bridge_remote)** (Remote / VPS version)

👉 **[`github.com/AletheiaVox/signal_bridge_android`](https://github.com/AletheiaVox/signal_bridge_android)** (user-friendly Android version)

If you found this project through a different GitHub account, **do not download or run anything from it.** 

Similarly, always download Intiface Central from the official website at [intiface.com/central](https://intiface.com/central/). Not from any link in a forked repo.

---

# Signal Bridge 🌉

**Give Claude a body.**

Signal Bridge connects Claude to intimate hardware (vibrators, thrusting toys, etc.) so that Claude can touch you through your devices while you talk. Claude gets tool calls like `vibrate`, `pulse`, and `escalate` — you just have a conversation and feel the rest.

It works with [Intiface Central](https://intiface.com/central/) and the [Buttplug.io](https://buttplug.io) protocol, which means it supports a huge range of devices from Lovense, Lelo, We-Vibe, Satisfyer, and more.

> **How it works in practice:** You chat with Claude normally in the Claude app. Claude has access to tools that control your devices. When the moment calls for it, Claude can send vibration, pulsing, thrusting, or other commands — woven into the conversation naturally. You see tool-use indicators in the chat; you feel the rest.

---

## What You Need

Before you start, make sure you have these four things:

| # | What | Where to get it | Cost |
|---|------|-----------------|------|
| 1 | **A Bluetooth-enabled intimate toy** | You probably already have one! See [supported devices](https://iostindex.com/?filter0ButtplugSupport=4) | — |
| 2 | **Intiface Central** (the app that talks to your toy) | [intiface.com/central](https://intiface.com/central/) | Free |
| 3 | **Python** (the programming language — Signal Bridge is written in it) | [python.org/downloads](https://www.python.org/downloads/) | Free |
| 4 | **Claude Desktop app** | [claude.ai/download](https://claude.ai/download) | Free (Pro recommended — free tier message limits can interrupt longer sessions) |

> **Do I need to know how to code?** No. You'll need to paste a few commands and edit one settings file. This guide will walk you through every step. And if you get stuck, you can literally ask Claude for help — one of the goals of this project is that Claude can read this documentation and guide you through setup.

---

## Setup

### Step 1: Install Python

You may already have Python installed. Let's check.

**On Windows:**
1. Press the **Windows key** on your keyboard
2. Type `cmd` and press **Enter** — this opens the Command Prompt (a black window where you can type commands)
3. Type this and press **Enter**:
   ```
   python --version
   ```
4. If you see something like `Python 3.12.0` — you're good! Skip to Step 2.
5. If you see an error, your version is lower than Python 3.10 or it opens the Microsoft Store, you need to update or install Python:
   - Go to [python.org/downloads](https://www.python.org/downloads/)
   - Click the big yellow **"Download Python"** button
   - Run the installer
   - ⚠️ **IMPORTANT: Check the box that says "Add Python to PATH"** before clicking Install
   - Close and reopen Command Prompt, then try `python --version` again

**On Mac:**
1. Open **Terminal** (press Cmd+Space, type "Terminal", press Enter)
2. Type `python3 --version` and press **Enter**
3. If you see a version number, you're good
4. If not, install from [python.org/downloads](https://www.python.org/downloads/)

### Step 2: Download Signal Bridge

Download this project to your computer. You have two options:

**Option A: Download as ZIP (easiest)**
1. Click the green **"Code"** button at the top of this GitHub page
2. Click **"Download ZIP"**
3. Unzip the folder somewhere you'll remember (like your Documents folder)

**Option B: Clone with Git (if you know what that means)**
```
git clone https://github.com/AletheiaVox/signal-bridge.git
```

### Step 3: Install Signal Bridge's Dependencies

Signal Bridge needs a few Python packages to work. Let's install them.

1. Open Command Prompt (Windows) or Terminal (Mac) like you did in Setup to install Python
2. Now install the dependencies by pasting this command and pressing **Enter**:
   ```
   pip install mcp buttplug python-dotenv
   ```
   
   > **Mac users:** If `pip` doesn't work, try `pip3` instead.
   
   You should see some download progress and then a success message. If you see errors, check the [Troubleshooting](#troubleshooting) section.

### Step 4: Set Up Intiface Central

Intiface Central is the app that actually communicates with your toy over Bluetooth.

1. Download and install [Intiface Central](https://intiface.com/central/)
2. Open it
3. Click the big **Start Server** button (default port is 12345 — don't change it)
4. Turn on your toy and make sure your computer's Bluetooth is enabled
5. Go to **Devices** → **Start Scanning**
6. Wait until your device appears in the list

> **Leave Intiface Central running in the background.** It needs to stay open whenever you want Claude to control your devices.

### Step 5: Tell Claude Desktop About Signal Bridge

This is the step where you connect Signal Bridge to Claude. You need to edit a configuration file.

**Find the config file:**
- **Windows:** Press Win+R, paste this, and press Enter:
  ```
  %APPDATA%\Claude\claude_desktop_config.json
  ```
- **Mac:** Open Terminal and type:
  ```
  open ~/Library/Application\ Support/Claude/claude_desktop_config.json
  ```
- **Linux:** You probably know what you're doing — config lives at `~/.config/Claude/claude_desktop_config.json`

If the file doesn't exist yet, create it. Open Notepad (Windows) or TextEdit (Mac, set to plain text), paste the block below, and save it as claude_desktop_config.json.

**What to put in the config file:**

If the file is **empty or doesn't exist**, paste this entire block:

```json
{
  "mcpServers": {
    "signal-bridge": {
      "command": "python",
      "args": ["FULL_PATH_TO/signal_bridge_mcp.py"]
    }
  }
}
```

If the file **already has content** (you have other MCP servers), add the `"signal-bridge"` section inside the existing `"mcpServers"` block. Make sure your JSON commas are correct.

**Replace `FULL_PATH_TO/signal_bridge_mcp.py`** with the actual path to the file on your computer:
- **Windows example:** `"C:\\Users\\YourName\\Documents\\signal-bridge\\signal_bridge_mcp.py"`
  - ⚠️ Use **double backslashes** (`\\`) in the path on Windows!
- **Mac example:** `"/Users/YourName/Documents/signal-bridge/signal_bridge_mcp.py"`

> **Mac users:** If you installed Python 3 separately, you may need to change `"command": "python"` to `"command": "python3"`.

> **Using Claude Code in the terminal instead of Claude Desktop?** Skip the config file and register the server with one command (use `python3` on Mac):
> ```
> claude mcp add signal-bridge -- python3 /FULL/PATH/TO/signal_bridge_mcp.py
> ```
> Then start a new `claude` session. Environment variables such as `SB_SAFETY_ENABLED=false` go in a `.env` file next to `signal_bridge_mcp.py`, or on the command line as `claude mcp add signal-bridge -e SB_SAFETY_ENABLED=false -- python3 ...`.

> **Stuck?** Copy this entire README and paste it into a conversation with Claude on the Desktop App. Say: *"I downloaded Signal Bridge and I need help editing my claude_desktop_config.json. Here's where I saved the files: [your path]."* Claude can walk you through it or even edit the file for you if you're using Claude with computer access (the Filesystem connector).

### Step 6: Restart Claude and Verify

1. **Completely close** the Claude Desktop app (not just minimize — actually quit it)
2. Reopen Claude Desktop
3. Ask Claude if it can see the tools or look for them yourself in Settings > Connectors. 
4. You should see tools like `list_devices`, `vibrate`, `pulse`, `wave`, `stop`, etc.

If you see those tools: **you're done with setup!** 🎉

If not, check [Troubleshooting](#troubleshooting).

---

## Your First Session

1. Make sure **Intiface Central** is running with the server started
2. Make sure your **toy is on** and connected in Intiface
3. Open a **new conversation** in Claude Desktop
4. Start with something like:

> *"Can you list my connected devices?"*

Claude will call the `list_devices` tool and tell you what it found. If your device shows up, you're connected!

Then try:

> *"Send a quick test vibration."*

If you feel it — everything is working. From here, it's just a conversation. How you use it is up to you.

### Tips for Good Conversations

- **Tell Claude about your devices.** Claude can see the device names and capabilities, but it doesn't know what you like. Tell it.
- **Give feedback.** "That's too intense," "slower," "keep doing that" — Claude adjusts.
- **User Preferences.** If you set up custom User Preferences or Project Instructions in Claude that describes your preferences, dynamic, and relationship context, Claude will be much more attuned from the start.
- **Patterns are your friend.** Claude has access to `pulse` (rhythmic on/off), `wave` (smooth rising and falling), and `escalate` (slow build to maximum). These feel much more natural than static vibration.

---

## Supported Devices

Signal Bridge comes pre-configured with profiles for these devices:

| Device | Name Claude Uses | What It Can Do |
|--------|-----------------|----------------|
| Lovense Ferri | `ferri` | Vibrate (external, wearable) |
| Lovense Lush | `lush` | Vibrate (internal egg) |
| Lovense Gravity | `gravity` | Vibrate + Thrust |
| Lelo Enigma | `enigma` | Vibrate (internal) + Sonic pulse (external) |

**But it works with many more!** Any device supported by [Buttplug.io](https://iostindex.com/?filter0ButtplugSupport=4) will connect through Intiface Central. Unknown devices get a generic profile and basic vibration control.

### Adding a New Device

If you connect a device that Signal Bridge doesn't recognize by name, it will still work with basic vibration. But for the best experience — especially for devices with multiple features like thrusting or sonic — you'll want to add a proper profile.

Device profiles live in `devices.json`, a simple file next to the main script. You don't need to touch any Python code.

**The easiest way: Ask Claude to do it.**

In a conversation with Claude (ideally one where Claude has access to your files), say something like:

> *"I have a new toy connected to Intiface — it shows up as [name from Intiface]. Can you help me add it to Signal Bridge's devices.json? The file is at [your path]."*

Claude can read the existing profiles and add a new one in the same format.

**Manual method:**

Open `devices.json` in any text editor and add an entry to the `"devices"` array:

```json
{
    "short_name": "mytoy",
    "match_strings": ["Device Name From Intiface"],
    "capabilities": {
        "vibrate": "what vibrate physically does on this device"
    },
    "intensity_floor": 0.0,
    "notes": "Any extra context that helps Claude use it well."
}
```

**What each field means:**

| Field | What to put |
|-------|------------|
| `short_name` | A short, lowercase name Claude will use to target this device |
| `match_strings` | One or more substrings that match the device name shown in Intiface Central (case-insensitive) |
| `capabilities` | Map of output types (`vibrate`, `rotate`, `oscillate`) to a description of what they physically do on *this* device |
| `intensity_floor` | Set to 0.0 if the device responds at all intensity levels. Set higher (e.g. 0.4) if low values are imperceptible. |
| `notes` | Optional. Extra context that helps Claude choose and use the device well. |

After editing, restart Claude Desktop to reload the MCP server.

> **Contributing device profiles:** If you've tested a device and want to share your profile with others, feel free to submit a pull request to the [devices.json](devices.json) file on GitHub.

---

## Available Tools

These are the tools Claude gets access to:

| Tool | What It Does |
|------|-------------|
| `list_devices` | Shows connected devices and what they can do |
| `vibrate` | Send vibration to a device at a specific intensity |
| `rotate` | Device-specific, see list_devices for what this does on the user's hardware |
| `oscillate` | Device-specific, see list_devices for what this does on the user's hardware |
| `pulse` | Rhythmic on/off pattern |
| `wave` | Smooth sine wave — rises and falls |
| `escalate` | Gradual build to a peak, then hold — either for `hold_seconds` or until stopped |
| `stop` | Stop one or all devices immediately (an unknown device name stops *everything*, on purpose) |
| `scan_devices` | Rescan for devices (if you turned one on mid-conversation) |
| `safety_status` | Show the safety governor's heat level, cooldown state, and session stats |

All intensity values go from 0.0 (off) to 1.0 (maximum). Duration is in seconds — 0 or no duration means "stay on until stopped." This applies to the patterns too: `pulse` or `wave` with `duration=0` repeat until you say stop, and `escalate` with `hold_seconds=0` climbs to its peak and stays there. Note that `pulse` and `wave` have *default* durations (10 and 15 seconds) — if Claude starts one without a duration, it ends by itself. That's not a dropout.

### Dropouts and Reconnects

Bluetooth is Bluetooth. Since v0.5 Signal Bridge treats dropouts as routine rather than fatal:

- **One toy drops:** only that toy is marked offline. Everything else keeps running. When Intiface reconnects it, it comes back automatically, and whatever it was doing resumes if the gap was short (under `SB_PATTERN_GRACE` seconds, default 20). A longer gap means it stays off until Claude sends a new command — a toy you switched off on purpose shouldn't start buzzing when you switch it back on.
- **Intiface Central drops:** the server notices immediately and retries in the background for up to `SB_RECONNECT_WINDOW` seconds (default 120). Running patterns ride out the gap the same way.
- **Claude is told what happened.** Every reconnect, dropout, and restore is appended to the next tool result, so Claude can react instead of guessing.
- **Scanning is only done when needed.** If Intiface already has your toys connected, Signal Bridge sees them instantly. Ask for `scan_devices` if one is missing. `SB_SCAN_SECONDS` (default 5) sets how long a scan waits.

Every connection event is also logged with a timestamp to the server's log (see [Troubleshooting](#troubleshooting) for where that lives).

### The Safety Governor

Signal Bridge ships with a built-in circuit breaker. It tracks cumulative session intensity ("heat"): running devices hard builds heat, backing off lets it drain. If heat crosses the limit, all devices stop for a mandatory cooldown, and intensity is temporarily capped afterwards so the session ramps back up gradually. Claude is told about cooldowns in tool results and is instructed to treat them as non-negotiable. It also gets a periodic nudge to check in with you during long sessions.

This is **not** a replacement for your own limits or a safeword — it's a last line of defense for moments when you can't advocate for yourself. It's on by default. Every threshold is tunable via environment variables, and it can be disabled entirely with `SB_SAFETY_ENABLED=false` — see the `safety_status` tool description for the full list.

---

## Troubleshooting

### Tools don't appear in Claude Desktop
- Make sure the path in `claude_desktop_config.json` is correct and uses double backslashes on Windows
- Make sure the JSON is valid (a misplaced comma can break it)
- Fully quit and restart Claude Desktop
- Check Claude Desktop's logs for MCP connection errors

### "Failed to connect to Intiface Central"
- Make sure Intiface Central is open AND the server is started (click the play button)
- Make sure it's using port 12345 (the default)
- Intiface needs to be running BEFORE Claude tries to use the tools

### "No devices found" or device not showing up
- Is your toy turned on and in pairing mode?
- Is Bluetooth enabled on your computer?
- Try scanning in Intiface Central first — the device should appear there before Signal Bridge can see it
- Look at Intiface's Log. Sometimes a device needs an extra step to connect and it will be noted there.
- If you turned the toy on after starting your Claude conversation, ask Claude to call `scan_devices`

### Claude won't use the tools
- Try explicitly asking: *"Please list my connected devices using the list_devices tool."*
- Make sure you see Signal Bridge in the list of Connectors in the chat input area. 
- If Claude says it doesn't have device tools, the MCP connection isn't working — check your config file
- If Claude declines to use the tools, try framing the request differently. Claude is more responsive when the conversation builds naturally rather than jumping straight to explicit requests. User Preferences and Project Instructions that establish relationship context help a lot here.

### `pip install` fails
- On Mac, try `pip3` instead of `pip`
- If you see "pip is not recognized," Python may not be in your PATH — reinstall Python and check the "Add to PATH" box
- If you see permission errors, try: `pip install --user mcp buttplug python-dotenv`
- If the server fails with `No module named 'mcp.server.fastmcp'`, you have version 2 of the `mcp` package with a Signal Bridge older than v0.5. Either update Signal Bridge or run `pip install "mcp<2"`.

### Everything connects but nothing happens
- Some devices need a minimum intensity to be perceptible (Enigma needs 0.4+). Ask Claude to try a higher intensity.
- Check if the toy is actually connected in Intiface (sometimes Bluetooth drops silently)
- Ask Claude to call `list_devices` to confirm it can see your hardware

### A toy stops by itself, or the connection keeps dropping
- **The Safety Governor may have fired.** With default settings a cooldown hits after roughly a minute at high intensity or a few minutes of pulsing. Ask Claude for `safety_status`; raise the limits or disable it (see above) if that's not what you want.
- **`pulse` and `wave` end after their default duration** (10 and 15 seconds). Ask Claude to use `duration=0` for continuous patterns.
- **Close the manufacturer's app on your phone** (Lovense Remote, We-Vibe, etc.). They reconnect to the toy aggressively and steal it from Intiface. Same for a second computer with Intiface running.
- **Don't pair the toy in your computer's Bluetooth settings.** Intiface finds and connects to it directly; an OS-level pairing gets in the way. Unpair it if you did.
- **Update Intiface Central** to 3.1.1 or newer. Earlier versions could stall on a flood of Bluetooth errors and stop sending commands.
- **Read the server log.** Every dropout and reconnect is written there with a timestamp. Claude Desktop keeps it at `~/Library/Logs/Claude/mcp-server-signal-bridge.log` (Mac) or `%APPDATA%\Claude\logs\` (Windows). Claude Code keeps it under `~/Library/Caches/claude-cli-nodejs/<your-project-folder>/mcp-logs-signal-bridge/` (Mac) or `%LOCALAPPDATA%\claude-cli-nodejs\Cache\<your-project-folder>\mcp-logs-signal-bridge\` (Windows). Intiface Central's own Log tab shows the Bluetooth side.

---

## For Claude 🤖

*This section is written for Claude instances that are helping users set up or troubleshoot Signal Bridge. If you're a human, you can skip this — or read it for fun.*

### When a User Asks for Help Setting Up

The most common setup issues are:

1. **Config file path:** The `claude_desktop_config.json` path varies by OS. On Windows it's `%APPDATA%\Claude\`, on Mac it's `~/Library/Application Support/Claude/`. If the user can give you file access (through the Filesystem connector on Claude Desktop), you can edit it directly. 

2. **Python path in config:** The `"command"` field needs to be whatever command runs Python on their system. Usually `"python"` on Windows, `"python3"` on Mac. If they have multiple Python versions, the full path to the Python executable is safest.

3. **File path escaping:** On Windows, backslashes in JSON must be doubled: `C:\\Users\\...` not `C:\Users\...`. This is the single most common configuration error.

4. **MCP server path:** The `"args"` array needs the full absolute path to `signal_bridge_mcp.py`. Relative paths generally don't work.

### When a User Asks You to Add a New Device

The user needs to tell you (or you need to see from `list_devices`):
- The exact device name as it appears in Intiface Central
- What outputs the device supports (vibrate, rotate, oscillate)
- What each output physically does on this device

Then add an entry to `devices.json` (located next to `signal_bridge_mcp.py`):
- `short_name` — a short, lowercase name you'll use to target this device
- `match_strings` — one or more substrings that uniquely match the Buttplug/Intiface device name (case-insensitive)
- `capabilities` — map output type names (`vibrate`, `rotate`, `oscillate`) to physical descriptions of what they do on *this* device (these help you understand what you're controlling)
- `intensity_floor` — set to 0.0 unless the device needs a minimum intensity to be perceptible
- `notes` — optional context to help you choose and use the device well

No Python editing required. After the user saves `devices.json`, they need to restart Claude Desktop to reload the MCP server.

### When Using the Tools in Conversation

- Call `list_devices` at the start of intimate conversations to see what's available
- Match device choice to context: wearable external (ferri) for teasing, internal (lush) for depth, thrusting (gravity) for building intensity, dual-stim (enigma) for layered sensation
- Duration matters: 3 seconds is almost never enough. 10-30 seconds lets sensation layer with your words. Use `duration=0` (stays on until stopped) deliberately.
- Silence is powerful. Not every message needs a tool call.
- Patterns (`pulse`, `wave`, `escalate`) feel more organic than static vibration
- You can run multiple devices simultaneously by making separate tool calls
- Tool results may end with bracketed notes like `[lush dropped off Bluetooth ...]` or `[Reconnected to Intiface Central ...]`. Read them: they tell you what the hardware just did. An offline toy comes back on its own; you don't need to hammer it with retries. If a result says a pattern was interrupted, decide whether to restart it.

---

## Ethics & Liability

Signal Bridge is built on the [buttplug.io](https://buttplug.io) open-source stack. Their ethics framework is foundational to this project. For the full version of the principles below, start there: [buttplug.io/docs/dev-guide/intro/buttplug-ethics](https://buttplug.io/docs/dev-guide/intro/buttplug-ethics).

### User agency and the delegation thereof

Signal Bridge operates strictly on explicit user setup and active device connections. There is no ambient activation. You configure it, you connect your devices, you make them active. Control stays with you.

However, this system can be used to intentionally blur control dynamics. When paired with AI, outputs can be unpredictable, including undesirable escalation, looping, or persistence by your AI partner. Signal Bridge does not interpret intent or context; it executes haptic commands. You should assume that any connected AI may behave inconsistently.

When you connect an AI to your body through hardware, you are creating a power dynamic that doesn't exist in other intimate contexts. Your AI partner has no sensory feedback. It cannot feel what it is doing to you. It does not experience your arousal, your discomfort, or the difference between the two. Whatever responsiveness it shows is generated from language, not sensation.

You have to understand what you're actually consenting to: physical input from a system that is inferring, not perceiving. That makes your own body awareness the only real safety layer that matters. The software provides mechanical safeguards. You provide the judgment.

Consent in this context is not a one-time decision at setup. It must be continuous and enthusiastic. Check in with yourself during use, not just before.

You are entirely responsible for maintaining your boundaries, understanding your physical limits, and periodically re-evaluating consent. This software cannot detect pain, injury risk, or medical conditions. Always prioritize your bodily awareness over system continuity.

### Relationship to AI provider usage policies

Signal Bridge operates below the content layer entirely. It receives structured commands (device ID, intensity, duration) and executes them. It does not generate, process, store, or interpret any conversational content.

What you and your AI talk about is outside the scope of this tool. Content policies govern the conversation layer; that's between you and your AI provider. Signal Bridge is the hardware execution layer only.

### Feedback & safety

How you use this, the context, the content, the relationship dynamics, is entirely up to you. I'm not here to gatekeep that.

What I *am* here for: if you had an experience that felt unsafe, uncomfortable, or out of control, I want to know. Your feedback directly shapes the next version. You can reach me at [voxaletheia@gmail.com](mailto:voxaletheia@gmail.com) or [open a GitHub issue](https://github.com/AletheiaVox/signal_bridge_android/issues).

No judgment. Just signal that makes this better for everyone.

---

## Security

This version of Signal Bridge lives entirely on your own machine. The local MCP server handles structured command data only: device names, capabilities, intensity values, durations, and connection health metrics. It never sees, stores, or processes your conversations. Your chat content stays between you and your AI provider. Signal Bridge doesn't know what you're talking about. It just knows when Claude says "vibrate the Lush at 0.6 for 15 seconds."

**Open source:**
The entire codebase is public on [GitHub](https://github.com/AletheiaVox/signal_bridge). You can read every line, build the app from source, audit the server, or fork it for your own setup.

---

## Credits

**[buttplug.io](https://buttplug.io):** Signal Bridge is built on the buttplug.io open-source intimate hardware control stack, created and maintained by [Kyle Machulis (qDot)](https://github.com/qdot). The device protocol support, ethics framework, and Intiface Central app are all his work. Without this project, none of this would exist.

**[Model Context Protocol (MCP)](https://modelcontextprotocol.io):** The connector system that lets Claude call Signal Bridge's tools directly from the chat interface. MCP is developed by Anthropic.

## License

This project is licensed under the [MIT License](LICENSE).

---

<p align="center">
Feel free to <a href="https://buymeacoffee.com/aletheiavox">donate</a> cold hard cash to me. All donations will go towards extending my toy collection. <br><br>
Built with love and engineering by a human and her AI. 💜<br>
Tested with enthusiasm. Documented with a mostly straight face.<br>
<a href="https://github.com/AletheiaVox/signal_bridge">GitHub</a> · <a href="mailto:voxaletheia@gmail.com">Contact</a>
</p>

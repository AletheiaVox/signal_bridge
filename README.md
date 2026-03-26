# ⚠️ Security Warning: Only Download Signal Bridge From This Repo

**Malware forks of Signal Bridge exist on GitHub.** These are copies of this project where the download links in the README have been replaced with links to malicious software.
 
This is the **only** legitimate source for Signal Bridge:

👉 **`github.com/AletheiaVox/signal_bridge`** (Claude Desktop / local version)

👉 **`github.com/AletheiaVox/signal_bridge_remote`** (Remote / VPS version)

If you found this project through a different GitHub account, **do not download or run anything from it.** 

Similarly, always download Intiface Central from the official website at [intiface.com/central](https://intiface.com/central/). Not from any link in a forked repo.

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
| `escalate` | Gradual build from nothing to maximum |
| `stop` | Stop one or all devices immediately |
| `scan_devices` | Rescan for devices (if you turned one on mid-conversation) |

All intensity values go from 0.0 (off) to 1.0 (maximum). Duration is in seconds — 0 or no duration means "stay on until stopped."

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

### Everything connects but nothing happens
- Some devices need a minimum intensity to be perceptible (Enigma needs 0.4+). Ask Claude to try a higher intensity.
- Check if the toy is actually connected in Intiface (sometimes Bluetooth drops silently)
- Ask Claude to call `list_devices` to confirm it can see your hardware

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

---

## Roadmap

Signal Bridge works well as a local MCP server, but there's a lot more it could become. Here are some ideas for the future — contributions and experiments welcome.

**Remote MCP server.** Right now Signal Bridge runs locally on your computer. A hosted version would let Claude use the tools from any device — your phone, a tablet, anywhere you have a browser — without needing Python or Intiface on that device. The server would run on a home machine or VPS with Intiface, and Claude would connect to it remotely.

**Authentication and multi-user support.** A remote server needs security. Token-based authentication, per-user device sessions, and encrypted connections would make it safe to share a server between trusted partners or run it as a service.

**Haptic feedback into Claude's context.** Some newer toys (like the Lovense Mission 2) have sensors that can report touch, pressure, or movement back to the app. If that data could be fed into Claude's context — as a tool result or injected into the conversation — Claude could respond to what *you're* doing, not just what it's doing. True bidirectional embodiment.

**More pattern tools.** The current patterns (pulse, wave, escalate) are a starting point. Community-contributed patterns, randomized variation, rhythm-matching, and composable sequences could make the experience much richer. Applying patterns to other parameters than only "vibrate" could also be interested. Imagine, for example, what a wave-form for a thrust could feel like...

If any of these spark something for you, open an issue or a PR. This project exists because someone decided to build a weird thing and share it.

---

## Credits

Signal Bridge uses [Buttplug.io](https://buttplug.io) and [Intiface Central](https://intiface.com/central/) by [Nonpolynomial](https://nonpolynomial.com/) for device communication, and the [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) by [Anthropic](https://anthropic.com) for Claude integration.

Built with love and engineering by a human and her AI. 💜

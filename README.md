# whatsapp-scheduler

A lightweight, self-hosted WhatsApp message scheduler. Define scheduled messages in a JSON file, run it as a background service, and it handles sending automatically — including reconnects, retries, and message templates.

Works on Linux, macOS, Windows, or any cloud VPS.

## Features

- **One-time QR scan** — session is persisted, no re-scanning after restarts
- **Cron-based scheduling** — standard cron expressions per message
- **Message templates** — `{{date}}`, `{{day}}`, `{{random:opt1|opt2|opt3}}`
- **Group support** — send to groups by name, not just individual contacts
- **Retry logic** — failed sends retry up to 3 times with exponential backoff
- **Auto-reconnect** — recovers from WhatsApp Web disconnections automatically
- **Structured logging** — all sends and errors logged to `logs/`
- **Background service support** — run as a persistent daemon on Linux (systemd), macOS (launchd), or Windows (PM2)

## Requirements

- Node.js 18+
- Chromium (used headlessly by whatsapp-web.js)

**Linux (Debian/Ubuntu/Raspberry Pi OS):**
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
sudo apt install -y nodejs chromium-browser
```

**macOS:**
```bash
brew install node
# Chromium is downloaded automatically by puppeteer on first run
```

**Windows:**

Download and install Node.js from [nodejs.org](https://nodejs.org). Chromium is downloaded automatically by puppeteer on first run.

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/whatsapp-scheduler.git
cd whatsapp-scheduler
npm install
```

## Configuration

Edit `schedules.json` to define your messages:

```json
[
  {
    "id": "morning-greeting",
    "to": "44XXXXXXXXXX",
    "message": "Good morning! Have a great {{day}} ❤️",
    "cron": "0 7 * * *",
    "enabled": true
  },
  {
    "id": "group-reminder",
    "to": "group:My Group Name",
    "message": "Weekly sync today at 6 PM! ({{date}})",
    "cron": "0 10 * * 1",
    "enabled": true
  }
]
```

### Fields

| Field | Description |
|---|---|
| `id` | Unique identifier for this schedule (used in logs) |
| `to` | Phone number with country code, no `+` (e.g. `447911123456` for a UK number), or `group:Group Name` for groups |
| `message` | Message text, supports template variables (see below) |
| `cron` | Standard 5-field cron expression |
| `enabled` | `true` to activate, `false` to pause without deleting |

### Template variables

| Variable | Output |
|---|---|
| `{{date}}` | `21 Feb 2026` |
| `{{day}}` | `Saturday` |
| `{{random:opt1\|opt2\|opt3}}` | Randomly picks one option |

Example: `"Happy {{day}}! {{random:Have a great one|You've got this|Make it count}}"` sends a different variation each time.

## Usage

### Run the scheduler daemon

```bash
npm start
```

On first run, a QR code will appear in the terminal. Scan it with WhatsApp on your phone (Linked Devices → Link a Device). The session is saved to `.wwebjs_auth/` and reused on subsequent starts.

### Send a one-off message

```bash
npm run send -- --to 44XXXXXXXXXX --msg "Hey, just checking in!"
```

Supports the same template variables. For groups: `--to "group:Group Name"`.

### List all schedules

```bash
npm run list
```

Shows each schedule's status, recipient, cron expression, and next fire time.

### Check service status

```bash
npm run status
```

## Keeping it running

For scheduled messages to fire reliably, this process needs to run continuously — 24/7 if possible. The right approach depends on what hardware you have.

> **Before setting up any background service:** complete the first run manually with `npm start` and scan the QR code. The session is then saved to `.wwebjs_auth/` and all subsequent starts (including automated ones) happen without any interaction.

---

### Recommended: Always-on Linux machine (systemd)

An always-on Linux machine is the ideal host — a home server, a spare desktop or laptop running Linux, a Raspberry Pi, or a cloud VPS. Linux's built-in service manager (systemd) handles starting the process on boot, restarting it on failure, and logging — all without any extra software.

**Step 1 — Install Node.js and Chromium**

See the [Requirements](#requirements) section above for the commands.

**Step 2 — Clone the repo and install packages**

```bash
git clone https://github.com/YOUR_USERNAME/whatsapp-scheduler.git
cd whatsapp-scheduler
npm install
```

**Step 3 — Scan the QR code (one time only)**

```bash
npm start
```

A QR code will appear in the terminal. On your phone, open WhatsApp → Linked Devices → Link a Device, and scan it. Once connected, press `Ctrl+C`. You won't need to do this again.

**Step 4 — Configure the systemd service**

Open `whatsapp-scheduler.service` in a text editor and make two changes:
- Replace `YOUR_USERNAME` with your Linux username (run `whoami` if unsure)
- Confirm the node path with `which node` and update `ExecStart` if it's different from `/usr/bin/node`

**Step 5 — Install and enable the service**

```bash
sudo cp whatsapp-scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable whatsapp-scheduler   # auto-start on boot
sudo systemctl start whatsapp-scheduler    # start now
```

**Step 6 — Verify it's running**

```bash
sudo systemctl status whatsapp-scheduler
```

To watch live logs:

```bash
sudo journalctl -u whatsapp-scheduler -f
```

From this point on, the scheduler starts automatically whenever the machine boots. If the process crashes, systemd restarts it within 15 seconds. If WhatsApp disconnects mid-session, the built-in reconnect logic handles it.

**Tips for long-running deployments:**
- Use a wired Ethernet connection where possible — more stable than Wi-Fi for a persistent process
- On a Raspberry Pi: use a quality power supply to avoid silent reboots from power instability
- If power reliability is a concern, a small UPS (uninterruptible power supply) is worth it

---

### Alternative: macOS

If you want to run this on a Mac that stays on most of the time (e.g. a home Mac mini or a laptop that's rarely shut down), use launchd — macOS's native background service system.

Create a plist file at `~/Library/LaunchAgents/com.whatsapp-scheduler.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.whatsapp-scheduler</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/node</string>
    <string>/path/to/whatsapp-scheduler/src/index.js</string>
    <string>start</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/path/to/whatsapp-scheduler</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/path/to/whatsapp-scheduler/logs/launchd.log</string>
  <key>StandardErrorPath</key>
  <string>/path/to/whatsapp-scheduler/logs/launchd.log</string>
</dict>
</plist>
```

Replace `/path/to/whatsapp-scheduler` with the actual absolute path, and confirm your node path with `which node`. Then load it:

```bash
launchctl load ~/Library/LaunchAgents/com.whatsapp-scheduler.plist
```

It will now start automatically at login and restart if it crashes. Note that messages won't fire while the Mac is asleep — disable sleep in System Settings if you need it to be fully reliable.

---

### Alternative: Windows

Use PM2, a cross-platform process manager for Node.js:

```bash
npm install -g pm2
pm2 start src/index.js --name whatsapp-scheduler -- start
pm2 save
pm2 startup
```

The last command prints an instruction specific to your system — follow it to make PM2 start automatically on boot.

---

### Alternative: Cloud VPS

If you don't have a device to leave running at home, the cheapest tier on any VPS provider works fine — this process is almost entirely idle between messages. Providers like Hetzner, DigitalOcean, and Linode all have entry-level plans suitable for this.

Once you have SSH access, the setup is identical to the Raspberry Pi steps above — it's just Linux.

One thing to note: whatsapp-web.js runs a headless Chromium browser in the background, which uses around 150–300MB of RAM. Make sure the instance you pick has at least 512MB available.

---

### What doesn't work

- **Serverless platforms** (AWS Lambda, Google Cloud Functions, Vercel, etc.) — these spin up on demand and shut down after each request. There's no way to run a persistent process or maintain a WhatsApp session.
- **Free-tier services that sleep on inactivity** (Render free tier, Railway free tier, Fly.io free tier) — the process gets paused when idle, which breaks the WhatsApp session and causes missed messages.

## Logs

| File | Contents |
|---|---|
| `logs/messages.log` | All sent messages with timestamps |
| `logs/error.log` | Errors and connection events |

Logs rotate at 5MB, keeping the last 3 files.

## Privacy

- Your WhatsApp session is stored in `.wwebjs_auth/` — this is excluded from Git and should never be committed
- `logs/` contains message history — also excluded from Git
- If your `schedules.json` contains real phone numbers, add it to `.gitignore` (a comment at the bottom of the file shows how)
- No data is sent to any external service — everything runs locally

## Project structure

```
whatsapp-scheduler/
├── src/
│   ├── index.js        # CLI entrypoint
│   ├── client.js       # WhatsApp client wrapper
│   ├── scheduler.js    # Cron job manager
│   ├── templates.js    # Template variable rendering
│   └── logger.js       # Winston logger setup
├── schedules.json      # Your message schedules
├── whatsapp-scheduler.service  # systemd unit file
└── logs/               # Auto-created, git-ignored
```

## Tech stack

- [whatsapp-web.js](https://github.com/pedroslopez/whatsapp-web.js) — WhatsApp Web automation
- [node-cron](https://github.com/node-cron/node-cron) — cron scheduling
- [winston](https://github.com/winstonjs/winston) — logging
- [commander](https://github.com/tj/commander.js) — CLI

## License

MIT

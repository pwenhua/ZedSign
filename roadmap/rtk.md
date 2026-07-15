# RTK Base + Rover Setup — Separate PCs

> **Situation**: You have **two RTK boards** (e.g., u-blox F9P), one as a **Base Station** (on a home PC) and one as a **Rover** (on the car PC with ZED 2i). The boards are on **separate machines** and the car PC **may not have internet**. How do they share RTCM correction data?

---

## The Problem

For RTK to work, the **Base** must send RTCM3 correction messages to the **Rover** continuously (~1 Hz). The Base is on a stationary home PC, the Rover is on the moving car PC — they need a communication link.

```
        HOME (stationary)                        CAR (mobile)
┌────────────────────────┐            ┌────────────────────────┐
│  Home PC               │            │  Car PC (RTX 5060)     │
│  ┌──────────┐          │            │  ┌──────────┐          │
│  │ RTK BASE │ antenna  │            │  │ RTK ROVER│ antenna  │
│  │ (F9P)    │ on roof  │    ???     │  │ (F9P)    │ on roof  │
│  └────┬─────┘          │ ────────▶  │  └────┬─────┘          │
│       │ USB            │  RTCM      │       │ USB            │
│  Pushes corrections    │  how?      │  ZED 2i + YOLO         │
└────────────────────────┘            └────────────────────────┘
                                        ⚠️ May have NO internet
```

---

## Solution Comparison

| Solution | Complexity | Internet Required? | Best For |
|---|---|---|---|
| **A. NTRIP** | ⭐⭐ Medium | ✅ Yes (both PCs) | Car has 4G/WiFi |
| **B. Radio Link** | ⭐⭐ Medium | ❌ No | Car has no internet |
| **C. PPK Post-Processing** | ⭐ Easiest | ❌ During drive; ✅ after | Zero extra hardware, prove pipeline first |
| **AUSCORS / GPSnet** | ⭐ Easiest | ✅ Yes (rover needs NTRIP) | Skip own base entirely |

> [!TIP]
> **Start with PPK** (Solution C) — zero extra hardware, same ~2 cm accuracy, process after the drive. Once proven, add a radio link or 4G for real-time.

---

## Base & Rover Board Configuration

Regardless of which solution you choose, both F9P boards need to be configured.

### Configure the Base Board

Using **u-center** (u-blox config tool):

1. Connect to the Base board's COM port
2. Go to **UBX-CFG-VALSET** (or the Message configuration panel)
3. Enable RTCM3 output messages:

| RTCM Message | Purpose | Rate |
|---|---|---|
| **1005** | Base station coordinates (ARP) | 1 Hz |
| **1077** | GPS MSM7 (full observations) | 1 Hz |
| **1087** | GLONASS MSM7 | 1 Hz |
| **1097** | Galileo MSM7 | 1 Hz |
| **1127** | BeiDou MSM7 | 1 Hz |
| **1230** | GLONASS code-phase biases | 0.1 Hz |

4. Set operating mode to **Survey-In** (for temporary base):
   - Minimum duration: 120 seconds
   - Minimum accuracy: 2.0 m (or better if you can wait longer)

   Or use **Fixed Position** if you know the base antenna's exact coordinates.

5. Save configuration to flash (UBX-CFG-CFG → Save)

### Configure the Rover Board

Using **u-center**:

1. Connect to the Rover board's COM port
2. Ensure RTCM3 input is enabled (usually enabled by default)
3. Enable NMEA output:
   - **GGA** at 5–10 Hz (position + fix quality)
   - **RMC** at 1 Hz (recommended minimum)
4. Save configuration to flash



---

## Solution A — NTRIP Caster (Car Has Internet)

If the car PC has internet (4G hotspot / phone tethering), NTRIP is the simplest way to get corrections from your base to the rover — or from a public CORS network.

### Architecture

```
┌──────────────┐         Internet        ┌──────────────┐
│  RTK BASE    │                         │  RTK ROVER   │
│  + PC/RPi    │───── NTRIP Server ─────▶│  + Car PC    │
│  (stationary)│    (pushes RTCM to      │  (mobile)    │
└──────────────┘     caster)             └──────────────┘
                        │
                  ┌─────▼─────┐
                  │  NTRIP    │
                  │  Caster   │
                  │  (relay)  │
                  └───────────┘
```

### Option A1 — RTK2go with Your Own Base (Free, Easiest)

1. Register your mountpoint at [rtk2go.com](http://rtk2go.com)
2. On the **Base PC**, run STRSVR:
   - Input: Serial → COM3 (Base)
   - Output: NTRIP Server → `rtk2go.com:2101`, your mountpoint name
3. On the **Rover PC**, read corrections via NTRIP Client:

```python
import socket

def ntrip_client(caster, port, mountpoint, user="", password=""):
    """Connect to NTRIP caster and yield RTCM data chunks."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((caster, port))

    # Send HTTP-like request
    request = (
        f"GET /{mountpoint} HTTP/1.1\r\n"
        f"User-Agent: NTRIP ZedSign/1.0\r\n"
        f"Accept: */*\r\n"
        f"\r\n"
    )
    sock.send(request.encode())

    # Check response
    response = sock.recv(1024).decode()
    if "ICY 200 OK" not in response:
        raise ConnectionError(f"NTRIP connection failed: {response}")

    # Stream RTCM data
    while True:
        data = sock.recv(4096)
        if data:
            yield data
```

### Option A2 — Local NTRIP with SNIP

If you don't want to rely on the internet:

1. Install [SNIP Lite](https://www.use-snip.com/) (free for 3 streams)
2. Run SNIP on the same PC or local network
3. Base pushes to `localhost:2101`
4. Rover pulls from `localhost:2101`

### When to Use NTRIP

| Scenario | Use NTRIP? |
|---|---|
| Car has 4G / phone tethering | ✅ Yes — simplest real-time option |
| Car has no internet at all | ❌ No — use Radio Link (Solution B) or PPK (Solution C) |
| Using a government CORS instead of own base | ✅ Yes — only need rover board |

---

## Verifying RTK Fix

Regardless of which solution you use, verify that the Rover is achieving **RTK Fix** (not just Float):

```python
import pynmea2

def check_rtk_quality(gga_sentence: str) -> str:
    """Parse GGA sentence and return fix quality."""
    msg = pynmea2.parse(gga_sentence)

    quality_map = {
        0: "No fix",
        1: "GPS fix (standalone, ~2-5m)",
        2: "DGPS fix (~0.5-1m)",
        4: "RTK Fix (~2cm) ✅",          # This is what we want!
        5: "RTK Float (~20-50cm)",        # Good, but not converged yet
        6: "Dead reckoning",
    }

    quality = int(msg.gps_qual)
    return quality_map.get(quality, f"Unknown ({quality})")

# Example:
# $GNGGA,123519,3349.5678,S,15112.3456,E,4,12,0.8,45.2,M,12.3,M,,*4A
#                                         ^ quality=4 = RTK Fix ✅
```

### Expected Convergence Timeline

| Phase | Duration | Accuracy |
|---|---|---|
| Base survey-in | 2–5 min | Establishing base position |
| Rover first fix (standalone) | ~30 sec | ~2–5 m |
| RTCM flowing → Float | 30–60 sec | ~20–50 cm |
| Float → **RTK Fix** | 1–5 min | **~2 cm** ✅ |

> [!IMPORTANT]
> If the Rover stays in **Float** and never reaches **Fix**, check:
> 1. RTCM data is actually flowing (check radio LEDs or NTRIP connection)
> 2. Both antennas have clear sky view (not indoors!)
> 3. Base and Rover are within ~20 km of each other
> 4. Correct RTCM messages are enabled (especially 1005 + MSM7 messages)

---

---

## Melbourne CORS — What's Actually Available?

> [!WARNING]
> **GPSnet (Vicmap Position) is NOT free.** It's a subscription-based service managed by the Victorian Government. You need a license agreement and typically access is via Value Added Resellers. I had this wrong in the previous version — corrected here.

### Option 1: AUSCORS — Free, from Geoscience Australia ✅

[AUSCORS](https://gnss.ga.gov.au/) is a **free** national CORS network run by Geoscience Australia. It provides single-base RTCM3 streams via NTRIP.

| Detail | Value |
|---|---|
| **Cost** | Free (registration required) |
| **NTRIP Address** | `ntrip.data.gnss.ga.gov.au` |
| **Port** | 2101 (or 443 for TLS) |
| **Registration** | [gnss.ga.gov.au/stream](https://gnss.ga.gov.au/stream) |
| **Format** | RTCM3 single-base streams |
| **Coverage** | National — check the map for stations near Melbourne |

**Limitation**: Single-base corrections only (not VRS/Network RTK). Accuracy depends on your distance from the nearest AUSCORS station — ideally within **35 km** for reliable RTK Fix.

**BUT**: This requires the **rover car PC to have internet** (4G/WiFi) to pull the NTRIP stream. If the car has no internet, AUSCORS won't work in real-time.

### Option 2: GPSnet — Paid, Professional

| Detail | Value |
|---|---|
| **Cost** | Subscription (contact [Vicmap Position](https://www.land.vic.gov.au/maps-spatial/spatial-data/vicmap-position/gpsnet)) |
| **Type** | Network RTK (VRS) — better coverage than single-base |
| **Access** | Via Value Added Resellers |
| **Coverage** | Statewide Victoria |

Better than AUSCORS for professional work, but costs money and still requires internet on the rover.

### Summary: Melbourne RTK Correction Sources

| Source | Cost | Internet Required? | Accuracy | Your Base Needed? |
|---|---|---|---|---|
| **AUSCORS** | Free | ✅ Yes (rover needs NTRIP) | ~2 cm (if < 35 km from station) | ❌ No |
| **GPSnet** | Paid subscription | ✅ Yes (rover needs NTRIP) | ~2 cm (statewide VRS) | ❌ No |
| **Your own base + NTRIP** | Free (RTK2go) | ✅ Yes (both PCs) | ~2 cm (if < 20 km) | ✅ Yes |
| **Your own base + Radio** | ~$40–100 (radios) | ❌ No internet needed! | ~2 cm (if < 10 km) | ✅ Yes |
| **PPK post-processing** | Free | ❌ No (process after drive) | ~2 cm | ✅ Yes (or use AUSCORS data) |

---

## Solution B — Radio Link: No Internet Required ⭐

Since the rover may have **no internet**, the most practical real-time solution is a **radio link** between the Base and Rover. The radios act as a transparent "wireless serial cable" — Base TX RTCM → radio → radio → Rover RX RTCM.

### Architecture

```
        HOME                              CAR
┌──────────────────┐              ┌──────────────────┐
│  Base PC         │              │  Car PC          │
│  ┌──────┐        │              │        ┌──────┐  │
│  │ F9P  │        │              │        │ F9P  │  │
│  │ BASE │        │              │        │ROVER │  │
│  └──┬───┘        │              │        └──┬───┘  │
│     │ UART2      │              │   UART2   │      │
│  ┌──▼───┐        │   ~~~~~~~~   │  ┌───────▼──┐   │
│  │ LoRa │        │   radio      │  │  LoRa    │   │
│  │ TX   │ ◀──────┼──  link  ───▶┼─▶│  RX      │   │
│  └──────┘ 915MHz │   ~~~~~~~~   │  └──────────┘   │
└──────────────────┘    ≤10 km    └──────────────────┘
```

### Recommended Radio Modules

| Radio | Range | Frequency | Cost | Notes |
|---|---|---|---|---|
| **RFD900x** | 40+ km (line of sight) | 915 MHz (AU legal) | ~$120 pair | Industry standard for drones/rovers |
| **SiK Telemetry** | 1–5 km | 915 MHz | ~$40 pair | Cheap, works well for urban |
| **LoRa (RN2903 / E32)** | 2–15 km | 915 MHz | ~$20 pair | Low bandwidth but sufficient for RTCM |
| **XBee Pro 900HP** | 10+ km | 915 MHz | ~$80 pair | Reliable, easy configuration |

> [!IMPORTANT]
> In Australia, use **915 MHz** band (ISM band, license-free). Do **not** use 433 MHz radios — they require a license in AU.

### Wiring

Connect the radio modules to the F9P's **UART2** port (not UART1/USB — keep USB free for PC connection):

**Base F9P → Radio TX:**
```
F9P UART2 TX  →  Radio RX
F9P UART2 RX  →  Radio TX  (optional, not needed for one-way)
F9P GND       →  Radio GND
5V / 3.3V     →  Radio VCC
```

**Rover F9P → Radio RX:**
```
Radio TX      →  F9P UART2 RX
Radio RX      →  F9P UART2 TX  (optional)
Radio GND     →  F9P GND
5V / 3.3V     →  Radio VCC
```

### u-blox Configuration for Radio Link

**Base (u-center):**
1. Set UART2 baud rate to match radio (typically 57600 for LoRa/SiK)
2. Enable RTCM3 output on **UART2**:
   - 1005 (base coordinates) — 1 Hz
   - 1077 (GPS MSM7) — 1 Hz
   - 1087 (GLONASS MSM7) — 1 Hz
   - 1097 (Galileo MSM7) — 1 Hz
   - 1127 (BeiDou MSM7) — 1 Hz
   - 1230 (GLONASS biases) — 0.1 Hz
3. Save to flash

> [!TIP]
> If radio bandwidth is limited (LoRa), use **MSM4** messages (1074/1084/1094/1124) instead of MSM7. MSM4 is ~60% smaller with only slightly reduced accuracy.

**Rover (u-center):**
1. Set UART2 baud rate to match radio
2. RTCM3 input on UART2 is enabled by default — the F9P auto-detects incoming RTCM
3. Enable NMEA output on **USB** (GGA at 5–10 Hz, RMC at 1 Hz)
4. Save to flash

### Integration with ZedSign Pipeline

With the radio link, the rover F9P handles corrections internally via UART2. Your car PC just reads corrected NMEA from the rover's USB port — **no bridge script needed on the car PC**:

```python
# On the car PC — rover F9P is already receiving RTCM via radio
# Just read the corrected NMEA output from USB
from gnss_reader import GNSSReader

gnss = GNSSReader("COM4", 115200)  # Rover USB port

while True:
    data = gnss.read()
    if data:
        lat, lng, alt, quality = data
        # quality=4 means RTK Fix via radio corrections ✅
        print(f"RTK position: {lat:.7f}, {lng:.7f}, quality={quality}")
```

---

## Solution C — PPK Post-Processing (No Internet, No Radio)

If you can't set up a radio link either, there's a **zero-hardware** fallback: log raw GNSS observations during the drive, then post-process against AUSCORS reference data afterwards.

> [!NOTE]
> PPK gives the **same ~2 cm accuracy** as real-time RTK, but you get the results **after** the drive, not during. For the ZedSign project, this is perfectly acceptable — you're mapping signs, not navigating in real-time.

### How PPK Works

```
During Drive:                          After Drive:
┌──────────┐  ┌────────┐              ┌──────────────────────────────┐
│ Rover    │  │ ZED 2i │              │  PC (at home, with internet) │
│ F9P logs │  │ records│              │                              │
│ raw .ubx │  │ .svo2  │              │  1. Download AUSCORS RINEX   │
│ file     │  │ file   │              │  2. Convert .ubx → RINEX     │
└────┬─────┘  └───┬────┘              │  3. RTKLIB RTKPOST:          │
     │            │                   │     rover.obs + base.obs     │
     └──── SD card / USB ────────────▶│     → precise .pos file      │
                                      │  4. Merge .pos + detections  │
                                      └──────────────────────────────┘
```

### Step 1 — Configure Rover to Log Raw Observations

In **u-center**, enable raw observation logging on the rover:

- Enable `UBX-RXM-RAWX` output (carrier phase + pseudorange)
- Enable `UBX-RXM-SFRBX` output (navigation data)
- Log to `.ubx` file via u-center or your Python script:

```python
import serial

rover = serial.Serial("COM4", 115200, timeout=1)
log_file = open("drive_2026-07-15.ubx", "wb")

try:
    while True:
        data = rover.read(rover.in_waiting or 1)
        if data:
            log_file.write(data)
except KeyboardInterrupt:
    log_file.close()
```

### Step 2 — Download AUSCORS Reference Data

After the drive, download the matching time period from the nearest AUSCORS station:

1. Go to [gnss.ga.gov.au](https://gnss.ga.gov.au/)
2. Find the nearest station to your drive area
3. Download RINEX observation + navigation files for the matching time window

### Step 3 — Post-Process with RTKLIB

1. **Convert** rover `.ubx` to RINEX using **RTKCONV**:
   - Input: `drive_2026-07-15.ubx`
   - Format: u-blox
   - Output: `rover.obs` + `rover.nav`

2. **Process** with **RTKPOST**:
   - Rover obs: `rover.obs`
   - Base obs: AUSCORS `.obs` file
   - Navigation: `rover.nav` or AUSCORS `.nav`
   - Settings:
     - Mode: **Kinematic**
     - Frequencies: **L1+L2** (F9P is dual-frequency)
     - Filter: **Combined** (forward + backward)
     - Ambiguity: **Fix-and-Hold**
   - Output: `drive.pos` (timestamp, lat, lng, alt, quality)

3. **Merge** the `.pos` file with your ZED sign detections by matching timestamps

> [!TIP]
> Use **RTKLIB demo5** builds (from [rtklibexplorer](https://rtklibexplorer.wordpress.com/)) — they have specific optimisations for u-blox F9P receivers and generally produce better results than mainline RTKLIB.

### PPK + ZED Pipeline Integration

```python
import csv
from datetime import datetime

def load_ppk_positions(pos_file: str) -> list[dict]:
    """Load RTKLIB .pos file into a list of time-stamped positions."""
    positions = []
    with open(pos_file, 'r') as f:
        for line in f:
            if line.startswith('%'):  # skip header comments
                continue
            parts = line.split()
            if len(parts) >= 6:
                positions.append({
                    "timestamp": f"{parts[0]} {parts[1]}",  # date time
                    "lat": float(parts[2]),
                    "lng": float(parts[3]),
                    "alt": float(parts[4]),
                    "quality": int(parts[5]),  # 1=Fix, 2=Float
                })
    return positions

def find_nearest_position(positions, target_time_ms):
    """Find the PPK position closest to a given ZED timestamp."""
    # ... binary search by timestamp ...
    pass

# Usage:
ppk = load_ppk_positions("drive.pos")
# For each detected sign, find the camera position at that timestamp
# Then compute sign's absolute position = camera_pos + relative_sign_offset
```

---

## Decision Matrix: Which Solution For Your Situation?

| Scenario | Solution | Internet? | Hardware Cost | Accuracy | Real-Time? |
|---|---|---|---|---|---|
| Car has 4G / tethering | **A. NTRIP** (AUSCORS or own base) | ✅ Yes | $0 | ~2 cm | ✅ Yes |
| Car has **NO internet** | **B. Radio Link** | ❌ No | ~$40–120 (radios) | ~2 cm | ✅ Yes |
| No radio, no internet | **C. PPK Post-Processing** | ❌ During drive; ✅ after | $0 | ~2 cm | ❌ After drive |
| Don't want own base | **AUSCORS or GPSnet** | ✅ Yes | $0 / subscription | ~2 cm | ✅ Yes |

### Recommended Path for ZedSign

```
Phase 1: First car test   → Solution C (PPK — zero extra hardware, prove it works)
Phase 2: Production       → Solution B (radio link) or Solution A (if car gets 4G)
```

> [!TIP]
> **Start with PPK** (Solution C). It requires zero extra hardware, gives identical accuracy to real-time RTK, and lets you validate the entire pipeline. Once proven, add a radio link for real-time if needed.

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| "COM port access denied" | Another app has the port open | Close u-center or other serial apps |
| RTCM flowing but no Fix | Weak sky view | Move antennas outdoors, clear sky |
| Rover shows quality=1 (standalone) | RTCM not reaching rover | Check radio LEDs or NTRIP connection |
| Rover shows quality=5 (Float) for > 5 min | Baseline too long or multipath | Reduce base-rover distance; check antenna placement |
| COM ports swap after reboot | Windows reassigns COM numbers | Use Device Manager to assign fixed COM numbers |
| Two COM ports per board | u-blox USB exposes 2 ports | Use the **lower** numbered port (primary) |
| PPK gives Float, not Fix | Base too far or obstructed sky | Use a closer AUSCORS station; try demo5 RTKLIB |
| Radio link no data | Baud rate mismatch | Ensure F9P UART2 and radio match (e.g., 57600) |

---

## Files in This Project

| File | Purpose |
|---|---|

| `gnss_reader.py` | Reads NMEA from Rover, parses lat/lng/quality |
| `zed_sign_pipeline.py` | Main pipeline — integrates ZED + YOLO + GNSS |
| `zed_sign_config.json` | Configuration (COM ports, baud rates, etc.) |

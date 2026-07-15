"""
GNSS Reader Module
===================
Phase 2: Reads NMEA sentences from a GPS RTK receiver via serial port.
Parses GGA sentences for latitude, longitude, altitude, and fix quality.

Can be used standalone for testing or imported as a module.

Usage (standalone test):
    python gnss_reader.py              # Read from default COM port
    python gnss_reader.py --port COM5  # Specify COM port
    python gnss_reader.py --list       # List available COM ports

Requirements:
    pip install pyserial pynmea2
"""

import sys
import time
import json
import argparse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("ERROR: pyserial not found. Install with: pip install pyserial")
    sys.exit(1)

try:
    import pynmea2
except ImportError:
    print("ERROR: pynmea2 not found. Install with: pip install pynmea2")
    sys.exit(1)


@dataclass
class GNSSFix:
    """Represents a single GNSS fix."""
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0
    fix_quality: int = 0  # 0=invalid, 1=GPS, 2=DGPS, 4=RTK fix, 5=RTK float
    num_satellites: int = 0
    hdop: float = 99.9
    timestamp: Optional[datetime] = None
    age_of_correction: float = 0.0
    is_valid: bool = False

    @property
    def fix_type_str(self) -> str:
        """Human-readable fix type."""
        fix_types = {
            0: "Invalid",
            1: "GPS",
            2: "DGPS",
            3: "PPS",
            4: "RTK Fix",
            5: "RTK Float",
            6: "Estimated",
            7: "Manual",
            8: "Simulation"
        }
        return fix_types.get(self.fix_quality, f"Unknown({self.fix_quality})")

    @property
    def is_rtk_fix(self) -> bool:
        """True if we have a high-precision RTK fix."""
        return self.fix_quality == 4

    @property
    def is_rtk_float(self) -> bool:
        """True if we have RTK float (less precise than fix)."""
        return self.fix_quality == 5

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude": self.altitude,
            "fix_quality": self.fix_quality,
            "fix_type": self.fix_type_str,
            "num_satellites": self.num_satellites,
            "hdop": self.hdop,
            "is_valid": self.is_valid,
            "is_rtk_fix": self.is_rtk_fix,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }


class GNSSReader:
    """
    Reads and parses NMEA data from a GPS/RTK receiver via serial port.
    
    Usage:
        reader = GNSSReader(port="COM3", baud_rate=115200)
        reader.open()
        
        fix = reader.read_fix()
        if fix and fix.is_valid:
            print(f"Position: {fix.latitude}, {fix.longitude}")
        
        reader.close()
    """

    def __init__(self, port: str = "COM3", baud_rate: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self._serial: Optional[serial.Serial] = None
        self._last_fix = GNSSFix()
        self._fix_count = 0

    def open(self):
        """Open the serial connection to the GNSS receiver."""
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                timeout=self.timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            print(f"GNSS: Opened {self.port} at {self.baud_rate} baud")
            return True
        except serial.SerialException as e:
            print(f"GNSS ERROR: Could not open {self.port}: {e}")
            return False

    def close(self):
        """Close the serial connection."""
        if self._serial and self._serial.is_open:
            self._serial.close()
            print("GNSS: Serial port closed.")

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def read_fix(self) -> Optional[GNSSFix]:
        """
        Read NMEA sentences until a GGA fix is found.
        Returns a GNSSFix object, or None if no valid data received.
        """
        if not self.is_open:
            return None

        try:
            line = self._serial.readline().decode('ascii', errors='replace').strip()
            if not line:
                return None

            # Parse GGA sentences (contain position + fix quality)
            if line.startswith('$GNGGA') or line.startswith('$GPGGA'):
                return self._parse_gga(line)

            # Could also parse RMC for speed/heading if needed
            # if line.startswith('$GNRMC') or line.startswith('$GPRMC'):
            #     return self._parse_rmc(line)

        except (serial.SerialException, UnicodeDecodeError) as e:
            print(f"GNSS read error: {e}")
            return None

        return None

    def read_fix_blocking(self, timeout: float = 5.0) -> Optional[GNSSFix]:
        """
        Block until a valid GGA fix is received or timeout expires.
        """
        start = time.time()
        while time.time() - start < timeout:
            fix = self.read_fix()
            if fix is not None:
                return fix
        return None

    def _parse_gga(self, sentence: str) -> Optional[GNSSFix]:
        """Parse a GGA NMEA sentence into a GNSSFix."""
        try:
            msg = pynmea2.parse(sentence)
            fix = GNSSFix(
                latitude=msg.latitude,
                longitude=msg.longitude,
                altitude=float(msg.altitude) if msg.altitude else 0.0,
                fix_quality=int(msg.gps_qual) if msg.gps_qual else 0,
                num_satellites=int(msg.num_sats) if msg.num_sats else 0,
                hdop=float(msg.horizontal_dil) if msg.horizontal_dil else 99.9,
                timestamp=datetime.now(),  # Local timestamp
                is_valid=int(msg.gps_qual or 0) > 0
            )
            self._last_fix = fix
            self._fix_count += 1
            return fix

        except pynmea2.ParseError as e:
            print(f"GNSS parse error: {e}")
            return None

    @property
    def last_fix(self) -> GNSSFix:
        """Return the most recent fix."""
        return self._last_fix

    @property
    def fix_count(self) -> int:
        """Total number of fixes received."""
        return self._fix_count

    @staticmethod
    def list_ports():
        """List all available serial ports."""
        ports = serial.tools.list_ports.comports()
        if not ports:
            print("No serial ports found.")
            return []

        print(f"\nAvailable serial ports ({len(ports)}):")
        print("-" * 60)
        for p in ports:
            print(f"  {p.device:10s}  {p.description}")
            if p.manufacturer:
                print(f"             Manufacturer: {p.manufacturer}")
            if p.serial_number:
                print(f"             Serial: {p.serial_number}")
        print("-" * 60)
        return [p.device for p in ports]


def main():
    """Standalone test: continuously read and display GNSS fixes."""
    parser = argparse.ArgumentParser(description="GNSS RTK Reader")
    parser.add_argument("--port", type=str, default="COM3", help="Serial port")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument("--list", action="store_true", help="List available ports")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.list:
        GNSSReader.list_ports()
        return

    reader = GNSSReader(port=args.port, baud_rate=args.baud)
    if not reader.open():
        sys.exit(1)

    print("\nWaiting for GNSS fixes... (Ctrl+C to stop)\n")

    try:
        while True:
            fix = reader.read_fix()
            if fix is None:
                continue

            if args.json:
                print(json.dumps(fix.to_dict()))
            else:
                status_icon = "🟢" if fix.is_rtk_fix else ("🟡" if fix.is_valid else "🔴")
                print(f"{status_icon} Fix #{reader.fix_count:5d} | "
                      f"{fix.fix_type_str:10s} | "
                      f"Lat: {fix.latitude:12.7f} | "
                      f"Lng: {fix.longitude:12.7f} | "
                      f"Alt: {fix.altitude:7.2f}m | "
                      f"Sats: {fix.num_satellites:2d} | "
                      f"HDOP: {fix.hdop:.1f}")

    except KeyboardInterrupt:
        print(f"\n\nStopped. Total fixes: {reader.fix_count}")
        if reader.last_fix.is_valid:
            print(f"Last position: {reader.last_fix.latitude:.7f}, "
                  f"{reader.last_fix.longitude:.7f}")

    finally:
        reader.close()


if __name__ == "__main__":
    main()

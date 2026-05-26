"""
Monitor serial output for HardFault register dumps, auto-analyze.
"""
import os
import sys
import re
import json
import time
from pathlib import Path
from typing import Dict, Optional

SCRIPT_DIR = str(Path(__file__).resolve().parent)
sys.path.insert(0, SCRIPT_DIR)

try:
    import serial
except ImportError:
    print("Error: pyserial not installed.")
    sys.exit(1)

from hardfault_analyzer import analyze_hardfault


def watch(port: str, baud: int, map_path: str) -> None:
    """Watch serial for HardFault dump and auto-analyze."""
    if not os.path.isfile(map_path):
        print(f"Error: .map file not found: {map_path}")
        sys.exit(1)

    print(f"Watching {port} at {baud} baud for HardFault...")
    print(f"Map file: {map_path}")
    print("Press Ctrl+C to stop.\n")

    try:
        ser = serial.Serial(port, baud, timeout=0.5)
    except Exception as e:
        print(f"Failed to open {port}: {e}")
        sys.exit(1)

    buffer = []
    in_hardfault = False

    try:
        while True:
            if ser.in_waiting:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                print(f"[SERIAL] {line}")

                if "HardFault" in line:
                    in_hardfault = True
                    buffer = [line]
                    print("\n" + "=" * 60)
                    print("HardFault detected! Capturing registers...")
                    continue

                if in_hardfault:
                    buffer.append(line)

                    # Check if we have enough register lines
                    regs = _parse_register_lines(buffer)
                    if regs and len(regs) >= 5:
                        print("\n--- Analyzing HardFault ---")
                        result = analyze_hardfault(regs, map_path)

                        print(f"PC: {result.get('pc')} -> {result.get('pc_function', 'unknown')}")
                        print(f"LR: {result.get('lr')} -> {result.get('lr_function', 'unknown')}")
                        print(f"FORCED: {result.get('forced')}")

                        print("\nDiagnosis:")
                        for d in result.get("diagnosis", []):
                            print(f"  - {d}")

                        print("=" * 60 + "\n")
                        in_hardfault = False
                        buffer = []

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        ser.close()


def _parse_register_lines(buffer: List[str]) -> Optional[Dict]:
    """Parse HardFault register dump lines."""
    regs = {}

    for line in buffer:
        # R0=0x20001234 R1=0x... ...
        for m in re.finditer(r'(R\d+|R12|LR|PC|xPSR|CFSR|HFSR)=0x([0-9A-Fa-f]+)', line):
            regs[m.group(1)] = f"0x{int(m.group(2), 16):08X}"

    return regs if regs else None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MSPM0G3519 HardFault Watcher")
    parser.add_argument("--port", required=True, help="Serial port")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument("--map", required=True, help="Path to .map file")

    args = parser.parse_args()
    watch(args.port, args.baud, args.map)

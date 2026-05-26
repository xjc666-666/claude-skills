"""
Simple foreground serial monitor for MSPM0G3519 UART output.
"""
import os
import sys
import time
import signal
from pathlib import Path

try:
    import serial
except ImportError:
    print("Error: pyserial not installed. Run: pip install pyserial")
    sys.exit(1)


def monitor(port: str, baud: int = 115200):
    """Simple terminal-style serial monitor."""
    ser = serial.Serial(port, baud, timeout=0.5)
    print(f"Connected to {port} at {baud} baud")
    print("Press Ctrl+C to exit.\n")

    def signal_handler(sig, frame):
        print("\nDisconnecting...")
        ser.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    try:
        while True:
            if ser.in_waiting:
                data = ser.read(ser.in_waiting)
                sys.stdout.write(data.decode("utf-8", errors="replace"))
                sys.stdout.flush()
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        print("Disconnected.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MSPM0G3519 Serial Monitor")
    parser.add_argument("--port", required=True, help="Serial port (e.g., COM3)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")

    args = parser.parse_args()
    monitor(args.port, args.baud)

"""
Auto-detect ST-Link VCP and monitor serial output.
"""
import os
import sys
import time
import datetime
from pathlib import Path
from typing import Optional, List, Dict

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("Error: pyserial is required. Install with: pip install pyserial")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import normalize_path


def list_serial_ports() -> List[Dict]:
    """List all available serial ports with descriptions."""
    ports = []
    for port in serial.tools.list_ports.comports():
        ports.append({
            "device": port.device,
            "name": port.name,
            "description": port.description,
            "hwid": port.hwid,
            "vid": port.vid,
            "pid": port.pid,
            "manufacturer": port.manufacturer,
        })
    return ports


def find_stlink_vcp() -> Optional[str]:
    """
    Auto-detect the ST-Link Virtual COM Port.
    Returns the device name (e.g., "COM3") or None.
    """
    stlink_keywords = [
        "STMicroelectronics STLink",
        "ST-Link",
        "STLink",
        "STMicroelectronics",
        "CH340",
        "CH341",
        "USB-SERIAL",
        "USB Serial",
        "USB2.0-Serial",
    ]

    for port in serial.tools.list_ports.comports():
        desc = port.description or ""
        hwid = port.hwid or ""
        combined = (desc + " " + hwid).lower()

        for kw in stlink_keywords:
            if kw.lower() in combined:
                return port.device

    # Fallback: try opening each COM port to see if it responds
    for port in serial.tools.list_ports.comports():
        try:
            ser = serial.Serial(port.device, baudrate=115200, timeout=0.5)
            ser.close()
            # If it opens without error, it might be our target
            if "USB" in (port.description or "").upper() or "COM" in port.device.upper():
                return port.device
        except Exception:
            continue

    return None


def monitor_serial(
    port: Optional[str] = None,
    baudrate: int = 115200,
    timeout: Optional[int] = None,
    log_file: Optional[str] = None,
    bytesize: int = serial.EIGHTBITS,
    parity: str = serial.PARITY_NONE,
    stopbits: int = serial.STOPBITS_ONE,
) -> None:
    """
    Monitor a serial port and print output to stdout.

    Args:
        port: COM port device (auto-detect if None)
        baudrate: Baud rate (default 115200)
        timeout: Auto-stop after N seconds of no data (None = never)
        log_file: Also save output to this file
        bytesize, parity, stopbits: Serial parameters
    """
    # Auto-detect port
    if port is None:
        port = find_stlink_vcp()
        if port is None:
            print("Error: Could not auto-detect ST-Link VCP.")
            print("\nAvailable serial ports:")
            for p in list_serial_ports():
                print(f"  {p['device']} - {p['description']} ({p['hwid']})")
            print("\nPlease specify the port manually with --port COMx")
            return

    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Connecting to {port} at {baudrate} baud...")

    log_fh = None
    if log_file:
        log_fh = open(log_file, "w", encoding="utf-8")

    try:
        ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=bytesize,
            parity=parity,
            stopbits=stopbits,
            timeout=1.0,
        )
    except serial.SerialException as e:
        print(f"Error opening {port}: {e}")
        if log_fh:
            log_fh.close()
        return

    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Connected. Monitoring... (Ctrl+C to stop)")
    print("-" * 60)

    last_data_time = time.time()

    try:
        while True:
            if ser.in_waiting > 0:
                try:
                    data = ser.read(ser.in_waiting)
                    # Try to decode as text, fall back to hex
                    try:
                        text = data.decode("utf-8", errors="replace")
                    except Exception:
                        text = data.decode("latin-1", errors="replace")

                    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    for line in text.splitlines(True):
                        output = f"[{timestamp}] {line.rstrip()}"
                        print(output)

                    if log_fh:
                        log_fh.write(text)
                        log_fh.flush()

                    last_data_time = time.time()
                except serial.SerialException as e:
                    print(f"\nSerial error: {e}")
                    break

            # Check timeout
            if timeout is not None and (time.time() - last_data_time) > timeout:
                print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] "
                      f"No data for {timeout}s, stopping monitor.")
                break

            time.sleep(0.01)  # 10ms polling interval

    except KeyboardInterrupt:
        print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Monitor stopped by user.")
    finally:
        ser.close()
        if log_fh:
            log_fh.close()
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Serial port closed.")


def send_to_serial(
    port: str,
    data: str,
    baudrate: int = 115200,
    timeout: float = 5.0,
) -> Optional[str]:
    """
    Send data to a serial port and optionally read response.

    Args:
        port: COM port device
        data: Data to send
        baudrate: Baud rate
        timeout: Read timeout in seconds

    Returns:
        Response data as string, or None on failure
    """
    try:
        ser = serial.Serial(port, baudrate, timeout=timeout)
        ser.write(data.encode("utf-8"))
        time.sleep(0.1)
        response = b""
        while ser.in_waiting > 0:
            response += ser.read(ser.in_waiting)
        ser.close()
        return response.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"Error communicating with {port}: {e}")
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="STM32 Serial Monitor")
    parser.add_argument("--port", default=None, help="COM port (auto-detect if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument("--timeout", type=int, default=None,
                        help="Auto-stop after N seconds of inactivity")
    parser.add_argument("--log", default=None, help="Save output to log file")
    parser.add_argument("--list", action="store_true", help="List available ports and exit")
    parser.add_argument("--send", default=None, help="Send data and exit (requires --port)")

    args = parser.parse_args()

    if args.list:
        ports = list_serial_ports()
        if not ports:
            print("No serial ports found.")
        else:
            print(f"Found {len(ports)} serial port(s):")
            for p in ports:
                print(f"  {p['device']} - {p['description']}")
                print(f"    HWID: {p['hwid']}")
        sys.exit(0)

    if args.send:
        if not args.port:
            print("Error: --port required with --send")
            sys.exit(1)
        response = send_to_serial(args.port, args.send, args.baud)
        if response:
            print(response)
        sys.exit(0)

    monitor_serial(
        port=args.port,
        baudrate=args.baud,
        timeout=args.timeout,
        log_file=args.log,
    )

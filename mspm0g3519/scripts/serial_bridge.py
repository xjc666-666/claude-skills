"""
Serial bridge daemon for MSPM0G3519 (bidirectional, background).
"""
import os
import sys
import re
import json
import time
import atexit
import threading
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

SCRIPT_DIR = str(Path(__file__).resolve().parent)
sys.path.insert(0, SCRIPT_DIR)

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("Error: pyserial not installed. Run: pip install pyserial")
    sys.exit(1)

# State file for daemon communication
STATE_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), ".cache")
STATE_FILE = os.path.join(STATE_DIR, "serial_state.json")
BUFFER_FILE = os.path.join(STATE_DIR, "serial_buffer.txt")

os.makedirs(STATE_DIR, exist_ok=True)

_serial_instance = None
_daemon_thread = None
_buffer_lock = threading.Lock()
_running = False


def list_ports() -> List[Dict]:
    """List available serial ports."""
    ports = []
    for p in serial.tools.list_ports.comports():
        ports.append({
            "device": p.device,
            "name": p.name,
            "description": p.description,
            "hwid": p.hwid,
        })
    return ports


def start_daemon(port: str, baud: int = 115200, timeout: float = 1.0) -> Dict:
    """Start the serial daemon in background."""
    global _serial_instance, _daemon_thread, _running

    if _running:
        return {"success": False, "error": "Daemon already running"}

    try:
        _serial_instance = serial.Serial(port, baud, timeout=timeout)
    except Exception as e:
        return {"success": False, "error": f"Failed to open {port}: {e}"}

    _running = True
    _clear_buffer()

    def _read_loop():
        global _running
        while _running:
            try:
                if _serial_instance and _serial_instance.is_open:
                    line = _serial_instance.readline()
                    if line:
                        _append_buffer(line.decode("utf-8", errors="ignore"))
            except Exception:
                time.sleep(0.1)

    _daemon_thread = threading.Thread(target=_read_loop, daemon=True)
    _daemon_thread.start()

    _update_state({"status": "running", "port": port, "baud": baud})

    return {"success": True, "port": port, "baud": baud, "status": "running"}


def stop_daemon() -> Dict:
    """Stop the serial daemon."""
    global _serial_instance, _running

    _running = False

    if _serial_instance and _serial_instance.is_open:
        try:
            _serial_instance.close()
        except Exception:
            pass
        _serial_instance = None

    _update_state({"status": "stopped"})
    return {"success": True, "status": "stopped"}


def get_status() -> Dict:
    """Get daemon status."""
    return _read_state()


def read_tail(lines: int = 30, parse_mode: Optional[str] = None) -> Dict:
    """Read last N lines from buffer."""
    with _buffer_lock:
        try:
            with open(BUFFER_FILE, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
        except FileNotFoundError:
            all_lines = []

    tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
    raw = "".join(tail).strip()

    result = {"raw": raw, "lines": len(tail)}

    if parse_mode == "parse":
        parsed = {}
        for line in tail:
            m = re.match(r'(\w+)\s*[=:]\s*([\d.]+)', line.strip())
            if m:
                try:
                    parsed[m.group(1)] = float(m.group(2))
                except ValueError:
                    parsed[m.group(1)] = m.group(2)
        result["parsed"] = parsed

    elif parse_mode == "numbers":
        numbers = []
        for line in tail:
            nums = re.findall(r'-?\d+\.?\d*', line)
            numbers.extend([float(n) for n in nums])
        result["numbers"] = numbers

    return result


def send(data: str, add_newline: bool = True) -> Dict:
    """Send data to serial port."""
    global _serial_instance

    if _serial_instance is None or not _serial_instance.is_open:
        return {"success": False, "error": "Daemon not running"}

    try:
        payload = data + ("\n" if add_newline else "")
        _serial_instance.write(payload.encode("utf-8"))
        return {"success": True, "sent": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


def sync_on(pattern: str, timeout: int = 5) -> Dict:
    """Wait for a specific pattern in serial output."""
    start = time.time()
    while time.time() - start < timeout:
        result = read_tail(50)
        if pattern in result["raw"]:
            return {"success": True, "pattern": pattern, "elapsed": round(time.time() - start, 2)}
        time.sleep(0.2)
    return {"success": False, "error": f"Timeout waiting for '{pattern}'"}


def _clear_buffer() -> None:
    with _buffer_lock:
        with open(BUFFER_FILE, "w", encoding="utf-8") as f:
            f.write("")


def _append_buffer(line: str) -> None:
    with _buffer_lock:
        with open(BUFFER_FILE, "a", encoding="utf-8") as f:
            f.write(line)
        # Keep buffer at max ~64KB
        if os.path.getsize(BUFFER_FILE) > 65536:
            with open(BUFFER_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            with open(BUFFER_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines[-2000:])


def _read_state() -> Dict:
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "not_started"}


def _update_state(data: Dict) -> None:
    current = _read_state()
    current.update(data)
    current["updated"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(current, f, indent=2)


# Cleanup on exit
atexit.register(lambda: stop_daemon() if _running else None)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MSPM0G3519 Serial Bridge")
    parser.add_argument("--port", default=None, help="Serial port (e.g., COM3)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument("--start", action="store_true", help="Start daemon")
    parser.add_argument("--stop", action="store_true", help="Stop daemon")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--list", action="store_true", help="List available ports")
    parser.add_argument("--tail", type=int, default=None, help="Read last N lines")
    parser.add_argument("--parse", action="store_true", help="Parse key=value pairs")
    parser.add_argument("--numbers", action="store_true", help="Extract numbers only")
    parser.add_argument("--send", default=None, help="Send data to serial port")
    parser.add_argument("--sync-on", default=None, help="Wait for pattern in serial output")
    parser.add_argument("--sync-timeout", type=int, default=5, help="Sync timeout")

    args = parser.parse_args()

    if args.list:
        ports = list_ports()
        print(json.dumps(ports, indent=2, ensure_ascii=False))
    elif args.stop:
        print(json.dumps(stop_daemon(), indent=2))
    elif args.status:
        print(json.dumps(get_status(), indent=2))
    elif args.start and args.port:
        print(json.dumps(start_daemon(args.port, args.baud), indent=2))
    elif args.tail is not None:
        mode = "parse" if args.parse else ("numbers" if args.numbers else None)
        print(json.dumps(read_tail(args.tail, mode), indent=2, ensure_ascii=False))
    elif args.send:
        print(json.dumps(send(args.send), indent=2))
    elif args.sync_on:
        print(json.dumps(sync_on(args.sync_on, args.sync_timeout), indent=2))
    else:
        parser.print_help()

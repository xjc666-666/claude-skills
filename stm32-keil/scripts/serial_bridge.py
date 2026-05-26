"""
Serial data engine for stm32-keil skill.

Opens a COM port, maintains a ring buffer, and exposes data via a JSON
state file for the skill to read. Supports structured parsing (key:value,
CSV patterns) for feedback-loop parameter tuning.

Usage:
    python serial_bridge.py --port COM5 --baud 115200        # start daemon
    python serial_bridge.py --list                            # list ports
    python serial_bridge.py --tail 30                         # read last 30 lines
    python serial_bridge.py --tail 20 --parse                 # parsed data points
    python serial_bridge.py --status                          # daemon stats
    python serial_bridge.py --stop                            # kill daemon
"""
import os
import sys
import re
import time
import json
import signal
import shutil
import threading
import tempfile
import datetime
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Tuple

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("Error: pyserial is required. Install with: pip install pyserial")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import ensure_dir

# ─── constants ────────────────────────────────────────────────────────

BUFFER_FILE = os.path.join(tempfile.gettempdir(), "stm32_serial_buffer.json")
PID_FILE    = os.path.join(tempfile.gettempdir(), "stm32_serial_bridge.pid")
CMD_FILE    = os.path.join(tempfile.gettempdir(), "stm32_serial_cmd.bin")
RING_SIZE   = 65536   # bytes
MAX_LINES   = 2000

# Patterns for structured data parsing
_RE_KEYVAL = re.compile(r'(\w+)\s*[:=]\s*(-?[\d.]+(?:e[+-]?\d+)?)', re.IGNORECASE)
_RE_NUMBER = re.compile(r'-?[\d.]+(?:e[+-]?\d+)?')


# ─── ring buffer ──────────────────────────────────────────────────────

class RingBuffer:
    def __init__(self):
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._total = 0
        self._lines: List[str] = []

    def feed(self, data: bytes) -> None:
        with self._lock:
            self._buf.extend(data)
            self._total += len(data)
            if len(self._buf) > RING_SIZE:
                self._buf = self._buf[-RING_SIZE // 2:]
            try:
                text = data.decode("utf-8", errors="replace")
                for line in text.splitlines(True):
                    self._lines.append(line)
            except Exception:
                pass
            if len(self._lines) > MAX_LINES:
                self._lines = self._lines[-MAX_LINES:]

    @property
    def total_bytes(self) -> int:
        with self._lock:
            return self._total

    @property
    def line_count(self) -> int:
        with self._lock:
            return len(self._lines)

    def tail_text(self, n: int = 100) -> str:
        with self._lock:
            return "".join(self._lines[-n:])

    def tail_parsed(self, n: int = 100) -> List[Dict]:
        """Extract structured key:value pairs from recent lines."""
        text = self.tail_text(n)
        results = []
        for line in text.splitlines():
            pairs = dict(_RE_KEYVAL.findall(line))
            if pairs:
                # Convert numeric strings to float/int
                parsed = {}
                for k, v in pairs.items():
                    try:
                        parsed[k] = int(v) if '.' not in v and 'e' not in v.lower() else float(v)
                    except ValueError:
                        parsed[k] = v
                results.append(parsed)
        return results

    def tail_numbers(self, n: int = 100) -> List[List[float]]:
        """Extract all numeric values from each line."""
        text = self.tail_text(n)
        results = []
        for line in text.splitlines():
            nums = [float(m) for m in _RE_NUMBER.findall(line)]
            if nums:
                results.append(nums)
        return results

    def snapshot(self) -> Dict:
        with self._lock:
            return {
                "total_bytes": self._total,
                "buffer_bytes": len(self._buf),
                "line_count": len(self._lines),
            }


# ─── daemon ───────────────────────────────────────────────────────────

_buffer: Optional[RingBuffer] = None
_stop_event: Optional[threading.Event] = None


def _flush_loop(buffer_file: str, interval: float = 0.5) -> None:
    """Periodically write buffer state to JSON file."""
    while not _stop_event.is_set():
        _stop_event.wait(interval)
        try:
            state = {
                "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                "stats": _buffer.snapshot(),
                "text": _buffer.tail_text(500),
                "parsed": _buffer.tail_parsed(200),
            }
            tmp = buffer_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
            os.replace(tmp, buffer_file)
        except Exception:
            pass


def run_daemon(port: str, baudrate: int = 115200,
               buffer_file: Optional[str] = None) -> None:
    """Open COM port and run the data collection daemon. Blocks until stopped."""
    global _buffer, _stop_event

    if buffer_file is None:
        buffer_file = BUFFER_FILE

    _buffer = RingBuffer()
    _stop_event = threading.Event()

    # Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    # Reset command file
    try:
        if os.path.isfile(CMD_FILE):
            os.remove(CMD_FILE)
    except OSError:
        pass

    # Start flush thread
    flush_thread = threading.Thread(
        target=_flush_loop, args=(buffer_file,), daemon=True
    )
    flush_thread.start()

    # Open serial
    try:
        ser = serial.Serial(port, baudrate, timeout=0.1)
    except serial.SerialException as e:
        print(f"Error opening {port}: {e}")
        _cleanup(buffer_file)
        sys.exit(1)

    # Start outgoing command thread (host → board)
    send_thread = threading.Thread(
        target=_send_loop, args=(ser, CMD_FILE, _stop_event), daemon=True
    )
    send_thread.start()

    # Write stopped state on exit
    def _on_exit():
        _stop_event.set()
        try:
            ser.close()
        except Exception:
            pass
        _cleanup(buffer_file)
    import atexit
    atexit.register(_on_exit)

    print(f"[{_ts()}] Serial daemon: {port} @ {baudrate} baud")
    print(f"[{_ts()}] Buffer: {buffer_file}")
    print(f"[{_ts()}] Ctrl+C to stop")

    try:
        while True:
            try:
                n = ser.in_waiting
                if n > 0:
                    _buffer.feed(ser.read(n))
                else:
                    time.sleep(0.01)
            except serial.SerialException as e:
                print(f"\n[{_ts()}] Serial error: {e}")
                break
    except KeyboardInterrupt:
        print(f"\n[{_ts()}] Stopped.")
    finally:
        _on_exit()


def _cleanup(buffer_file: str) -> None:
    """Remove PID file and write final buffer state."""
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    if _buffer:
        try:
            state = {
                "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                "stats": _buffer.snapshot(),
                "text": _buffer.tail_text(500),
                "parsed": _buffer.tail_parsed(200),
            }
            with open(buffer_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
        except Exception:
            pass


# ─── public API (used by skill at runtime) ────────────────────────────

def is_running() -> bool:
    """Check if daemon is currently running."""
    if not os.path.isfile(PID_FILE):
        return False
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5
            )
            return f'"{pid}"' in result.stdout
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def stop_daemon() -> bool:
    """Kill the running daemon. Returns True if daemon was running."""
    if not os.path.isfile(PID_FILE):
        return False
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
        os.remove(PID_FILE)
        return True
    except (OSError, ValueError):
        return False


def read_state(buffer_file: Optional[str] = None) -> Dict:
    """Read current buffer state from the daemon."""
    if buffer_file is None:
        buffer_file = BUFFER_FILE
    try:
        with open(buffer_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"timestamp": "", "stats": {}, "text": "", "parsed": []}


def tail(n: int = 30) -> str:
    """Return last N lines of text from the daemon."""
    state = read_state()
    lines = state.get("text", "").splitlines(True)
    return "".join(lines[-n:])


def tail_parsed(n: int = 50) -> List[Dict]:
    """Return last N parsed key:value data points."""
    state = read_state()
    return state.get("parsed", [])[-n:]


def tail_numbers(n: int = 50) -> List[List[float]]:
    """Return last N lines as numeric arrays."""
    state = read_state()
    text = state.get("text", "")
    results = []
    for line in text.splitlines()[-n:]:
        nums = [float(m) for m in _RE_NUMBER.findall(line)]
        if nums:
            results.append(nums)
    return results


def send_to_daemon(text: str, append_newline: bool = True) -> bool:
    """Append a payload to the command file; the daemon will write it
    to the serial port. Works cross-process (e.g. Claude in another shell)."""
    payload = (text + ("\r\n" if append_newline else "")).encode("utf-8", errors="replace")
    try:
        with open(CMD_FILE, "ab") as f:
            f.write(payload)
        return True
    except OSError:
        return False


def wait_for_sync(magic: str, timeout: float = 10.0, poll: float = 0.1) -> bool:
    """Wait until `magic` appears in the incoming text after the moment of
    this call. Returns True on match, False on timeout. Used to skip stale
    data from a previous run (e.g. board reset).
    """
    base = len(read_state().get("text", ""))
    start = time.time()
    while time.time() - start < timeout:
        text = read_state().get("text", "")
        if len(text) > base and magic in text[base:]:
            return True
        time.sleep(poll)
    return False


def _send_loop(ser, cmd_file: str, stop_event: threading.Event) -> None:
    """Drain the command file and write its tail to the serial port."""
    last_size = 0
    while not stop_event.is_set():
        try:
            if os.path.isfile(cmd_file):
                size = os.path.getsize(cmd_file)
                if size > last_size:
                    with open(cmd_file, "rb") as f:
                        f.seek(last_size)
                        data = f.read()
                    try:
                        ser.write(data)
                    except Exception:
                        pass
                    last_size = size
                elif size == 0:
                    last_size = 0
            stop_event.wait(0.05)
        except Exception:
            stop_event.wait(0.1)


# ─── port listing ─────────────────────────────────────────────────────

def list_ports() -> List[Dict]:
    ports = []
    for p in serial.tools.list_ports.comports():
        is_bt = "BTHENUM" in (p.hwid or "")
        ports.append({
            "device": p.device,
            "description": p.description,
            "hwid": p.hwid,
            "is_bluetooth": is_bt,
        })
    return ports


def find_stm32_port() -> Optional[str]:
    """Find the best candidate for an STM32 serial port."""
    for p in serial.tools.list_ports.comports():
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        if "stlink" in desc or "stlink" in hwid:
            return p.device
    for p in serial.tools.list_ports.comports():
        hwid = p.hwid or ""
        if "BTHENUM" not in hwid:
            return p.device
    return None


# ─── helpers ──────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")

def _safe(text: str) -> str:
    """Strip characters that can't be encoded in the console codepage."""
    return text.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(
        sys.stdout.encoding or 'utf-8', errors='replace')

def _print(*args, **kwargs):
    """Print safely, handling encoding issues."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = [_safe(str(a)) for a in args]
        print(*safe_args, **kwargs)


# ─── live watch ───────────────────────────────────────────────────────

def watch(parse: bool = False, interval: float = 0.3,
          buffer_file: Optional[str] = None) -> None:
    """
    Like tail -f: continuously poll daemon buffer and print new data.
    Press Ctrl+C to stop.
    """
    last_bytes = 0
    last_parsed = 0
    mode = "parsed" if parse else "text"
    print(f"[{_ts()}] Watching {mode}... (Ctrl+C to stop)")
    print("-" * 50)

    try:
        while True:
            state = read_state(buffer_file)
            stats = state.get("stats", {})

            if parse:
                parsed = state.get("parsed", [])
                if len(parsed) > last_parsed:
                    for pt in parsed[last_parsed:]:
                        line = ", ".join(f"{k}={v}" for k, v in pt.items())
                        print(f"[{_ts()}] {line}")
                    last_parsed = len(parsed)
            else:
                total = stats.get("total_bytes", 0)
                if total > last_bytes:
                    text = state.get("text", "")
                    new_bytes = total - last_bytes
                    chunk = text[-(new_bytes):]
                    # Sanitize for console: strip non-ASCII binary garbage
                    safe = ''.join(
                        c if (32 <= ord(c) < 127) or c in '\r\n\t' else ''
                        for c in chunk
                    )
                    if safe.strip():
                        print(safe, end="", flush=True)
                    last_bytes = total
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n[{_ts()}] Watch stopped.")


# ─── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding=sys.stdout.encoding or 'utf-8',
        errors='replace', line_buffering=True
    )
    import argparse

    p = argparse.ArgumentParser(description="STM32 Serial Data Engine")
    p.add_argument("--port", default=None, help="COM port")
    p.add_argument("--baud", type=int, default=115200, help="Baud rate")
    p.add_argument("--list", action="store_true", help="List ports and exit")
    p.add_argument("--status", action="store_true", help="Show daemon status")
    p.add_argument("--tail", type=int, default=None, help="Read last N lines")
    p.add_argument("--parse", action="store_true", help="Parse key:value pairs")
    p.add_argument("--numbers", action="store_true", help="Extract numeric arrays")
    p.add_argument("--watch", action="store_true", help="Continuously watch live data")
    p.add_argument("--stop", action="store_true", help="Stop daemon")
    p.add_argument("--send", default=None,
                   help="Send text to board (daemon must be running)")
    p.add_argument("--no-newline", action="store_true",
                   help="Don't append \\r\\n to --send payload")
    p.add_argument("--sync-on", default=None,
                   help="Wait until magic string appears in incoming stream")
    p.add_argument("--sync-timeout", type=float, default=10.0,
                   help="Timeout for --sync-on (seconds)")
    p.add_argument("--buffer-file", default=None, help="Buffer file path")
    args = p.parse_args()

    if args.list:
        ports = list_ports()
        if not ports:
            print("No serial ports found.")
        else:
            print(f"{len(ports)} port(s):")
            for pt in ports:
                tag = "USB" if not pt["is_bluetooth"] else "BT "
                print(f"  {tag} {pt['device']:8s}  {pt['description']}")
            best = find_stm32_port()
            if best:
                print(f"\nBest guess: {best}")
        sys.exit(0)

    if args.status:
        if is_running():
            state = read_state(args.buffer_file)
            s = state.get("stats", {})
            print(f"Daemon running:")
            print(f"  bytes: {s.get('total_bytes', 0)}")
            print(f"  lines: {s.get('line_count', 0)}")
            print(f"  updated: {state.get('timestamp', '?')}")
        else:
            print("Daemon not running.")
        sys.exit(0)

    if args.stop:
        if stop_daemon():
            print("Daemon stopped.")
        else:
            print("No daemon running.")
        sys.exit(0)

    if args.send is not None:
        if not is_running():
            print("Daemon not running. Start it first.")
            sys.exit(1)
        ok = send_to_daemon(args.send, append_newline=not args.no_newline)
        print("Sent." if ok else "Failed to queue send.")
        sys.exit(0 if ok else 1)

    if args.sync_on is not None:
        if not is_running():
            print("Daemon not running. Start it first.")
            sys.exit(1)
        ok = wait_for_sync(args.sync_on, timeout=args.sync_timeout)
        print(f"Sync {'matched' if ok else 'timed out'}: {args.sync_on!r}")
        sys.exit(0 if ok else 2)

    if args.watch:
        if not is_running():
            print("Daemon not running. Start it first:")
            print(f"  python {__file__} --port COMx --baud 115200 &")
            sys.exit(1)
        watch(parse=args.parse, buffer_file=args.buffer_file)
        sys.exit(0)

    if args.tail is not None:
        if not is_running():
            print("Daemon not running. Start it first:")
            print(f"  python {__file__} --port COMx --baud 115200 &")
            sys.exit(1)

        if args.numbers:
            data = tail_numbers(args.tail)
            if data:
                print(f"[{len(data)} numeric rows]")
                for row in data[-args.tail:]:
                    print(", ".join(f"{v:.3f}" for v in row))
            else:
                print("(no numeric data)")
        elif args.parse:
            data = tail_parsed(args.tail)
            if data:
                print(f"[{len(data)} parsed points]")
                keys = list(data[-1].keys()) if data else []
                print(f"Fields: {keys}")
                for pt in data[-args.tail:]:
                    print("  " + ", ".join(f"{k}={v}" for k, v in pt.items()))
            else:
                print("(no parseable data)")
        else:
            text = tail(args.tail)
            if text.strip():
                print(text, end="")
            else:
                print("(no data)")
        sys.exit(0)

    # Default: run daemon
    port = args.port
    if port is None:
        port = find_stm32_port()
        if port is None:
            print("Error: no COM port found. Use --port COMx or --list")
            sys.exit(1)
        print(f"Auto-detected: {port}")

    run_daemon(port, args.baud, args.buffer_file)

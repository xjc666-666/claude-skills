"""
Watch the serial daemon buffer for HardFault dumps and analyze them.

Expected dump format (recommended in your HardFault_Handler):
    HardFault
    R0=0x... R1=0x... R2=0x... R3=0x...
    R12=0x... LR=0x... PC=0x... xPSR=0x...
    CFSR=0x... HFSR=0x...

This watcher is permissive: it only requires PC and LR; missing fields
default to zero. Provide a .map file to resolve PC → symbol.
"""
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from serial_bridge import read_state, is_running
from hardfault_analyzer import analyze_hardfault, format_report


_RE_HEX = re.compile(r"(R0|R1|R2|R3|R12|LR|PC|xPSR|CFSR|HFSR|MMFAR|BFAR)"
                     r"\s*[:=]\s*0x([0-9A-Fa-f]+)", re.IGNORECASE)
_RE_TRIGGER = re.compile(r"(HardFault|Hard Fault|HARD_FAULT|UsageFault|BusFault)",
                         re.IGNORECASE)


def parse_dump(text: str) -> Optional[Dict[str, str]]:
    """Pull register dump values out of a block of text.

    Returns None if no fault trigger is seen, or {} if trigger seen but no
    registers (still informative — caller can ask the user to extend the
    HardFault_Handler with a register dump)."""
    if not _RE_TRIGGER.search(text):
        return None
    out: Dict[str, str] = {}
    for m in _RE_HEX.finditer(text):
        name = m.group(1).upper()
        out[name] = "0x" + m.group(2).upper()
    return out


def watch(map_path: Optional[str], interval: float = 0.5,
          once: bool = False) -> int:
    """Poll the daemon buffer; whenever a fault appears, report it.

    Returns the number of faults reported (0 if --once and none seen).
    """
    if not is_running():
        print("Serial daemon not running. Start serial_bridge.py --port COMx first.")
        return -1

    seen_at = 0  # offset in the rolling text buffer
    reports = 0

    while True:
        state = read_state()
        text = state.get("text", "")
        if len(text) > seen_at:
            new = text[seen_at:]
            seen_at = len(text)
            dump = parse_dump(new)
            if dump is not None:
                print("\n=== Detected fault on serial ===")
                if dump and "PC" in dump:
                    if not map_path or not os.path.isfile(map_path):
                        print("No .map file provided — printing raw registers:")
                        for k, v in dump.items():
                            print(f"  {k} = {v}")
                    else:
                        rep = analyze_hardfault(
                            map_path, dump.get("PC", "0x0"), dump.get("LR", "0x0"),
                            dump.get("R0", "0x0"), dump.get("R1", "0x0"),
                            dump.get("R2", "0x0"), dump.get("R3", "0x0"),
                            dump.get("R12", "0x0"), dump.get("xPSR", "0x0"),
                        )
                        print(format_report(rep))
                else:
                    print("Fault keyword seen but no PC value parsed. "
                          "Extend your HardFault_Handler to print "
                          "R0..R3,R12,LR,PC,xPSR,CFSR.")
                    print("Excerpt:")
                    print(new[-400:])
                reports += 1
                if once:
                    return reports

        time.sleep(interval)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Auto-detect HardFault dumps on the serial buffer.")
    parser.add_argument("--map", help="Path to .map file for symbol resolution")
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--once", action="store_true",
                        help="Exit after first fault (default: keep watching)")
    args = parser.parse_args()

    try:
        n = watch(args.map, args.interval, args.once)
    except KeyboardInterrupt:
        print("\nWatcher stopped.")
        n = 0
    sys.exit(0 if n >= 0 else 1)

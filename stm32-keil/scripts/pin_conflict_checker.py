"""
Detect pin assignment conflicts for STM32 projects.
"""
import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import ensure_dir


class PinAssignment(NamedTuple):
    peripheral: str
    signal: str
    pin: str


class PinConflict(NamedTuple):
    level: str       # "OK", "WARNING", "CONFLICT"
    pin: str
    message: str
    peripherals: List[str]


def load_pin_mapping(family: str) -> Dict:
    """Load the pin mapping database for a chip family."""
    data_dir = os.path.join(Path(__file__).resolve().parent.parent, "data")
    name = f"pin_mapping_{family.lower()}.json"
    path = os.path.join(data_dir, name)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Pin mapping not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_pin_conflicts(
    family: str,
    assignments: List[Dict[str, str]],
) -> List[PinConflict]:
    """
    Check a list of pin assignments for conflicts.

    Args:
        family: "F103" or "F407"
        assignments: List of {"peripheral": "USART1", "signal": "TX", "pin": "PA9"}

    Returns:
        List of PinConflict results, one per pin.
    """
    pin_db = load_pin_mapping(family)
    pins_data = pin_db["pins"]
    jtag_pins = set(pin_db.get("jtag_swd_pins", []))

    # Group assignments by pin
    pin_map: Dict[str, List[dict]] = {}
    for a in assignments:
        pin = a["pin"].upper()
        pin_map.setdefault(pin, []).append(a)

    results: List[PinConflict] = []

    for pin, assigns in pin_map.items():
        pin_info = pins_data.get(pin)
        if pin_info is None:
            results.append(PinConflict(
                level="WARNING",
                pin=pin,
                message=f"Pin {pin} not found in database (uncommon or unavailable)",
                peripherals=[f'{a["peripheral"]}_{a["signal"]}' for a in assigns],
            ))
            continue

        periph_list = [f'{a["peripheral"]}_{a["signal"]}' for a in assigns]

        # Conflict 1: Multiple assignments to same pin
        if len(assigns) > 1:
            results.append(PinConflict(
                level="CONFLICT",
                pin=pin,
                message=f"Pin assigned to {len(assigns)} peripherals: {', '.join(periph_list)}",
                peripherals=periph_list,
            ))
        else:
            # Single assignment — verify valid
            func_names = [f'{f["peripheral"]}_{f["signal"]}' for f in pin_info["functions"]]
            periph_key = periph_list[0]

            is_valid = any(
                a["peripheral"] == f["peripheral"] and a["signal"] == f["signal"]
                for a in assigns
                for f in pin_info["functions"]
            )
            if not is_valid:
                results.append(PinConflict(
                    level="WARNING",
                    pin=pin,
                    message=f"{periph_key} not found on {pin}. Available: {', '.join(func_names)}",
                    peripherals=periph_list,
                ))
            else:
                results.append(PinConflict(
                    level="OK",
                    pin=pin,
                    message=f"{periph_key} on {pin} — valid",
                    peripherals=periph_list,
                ))

        # Conflict 2: JTAG/SWD pin in use (only on F1 medium density where SWD-only is typical)
        if pin in jtag_pins and not all(
            a["peripheral"] in ("SWD", "JTAG") for a in assigns
        ):
            results.append(PinConflict(
                level="WARNING",
                pin=pin,
                message=f"JTAG/SWD pin {pin} used as GPIO/peripheral. Disable JTAG (AFIO->MAPR SWJ_CFG) first.",
                peripherals=periph_list,
            ))

        # Warning 3: 5V tolerance (informational)
        if not pin_info.get("5v_tolerant", True):
            results.append(PinConflict(
                level="WARNING",
                pin=pin,
                message=f"Pin {pin} is NOT 5V tolerant (FT=false). Do not connect to 5V logic.",
                peripherals=periph_list,
            ))

    return results


def format_conflict_table(results: List[PinConflict]) -> str:
    """Format conflict results as a readable ASCII table."""
    header = f"{'Level':10s} | {'Pin':6s} | Message"
    sep = "-" * 80
    lines = [sep, header, sep]

    level_order = {"CONFLICT": 0, "WARNING": 1, "OK": 2}
    sorted_results = sorted(results, key=lambda r: level_order.get(r.level, 3))

    for r in sorted_results:
        mark = {"CONFLICT": "!!", "WARNING": "! ", "OK": "OK"}.get(r.level, "  ")
        lines.append(f"[{mark}] {r.level:6s} | {r.pin:6s} | {r.message}")

    lines.append(sep)

    conflict_count = sum(1 for r in results if r.level == "CONFLICT")
    warn_count = sum(1 for r in results if r.level == "WARNING")
    ok_count = sum(1 for r in results if r.level == "OK")
    lines.append(f"Total: {conflict_count} conflict(s), {warn_count} warning(s), {ok_count} OK")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check STM32 pin assignments for conflicts")
    parser.add_argument("--family", required=True, choices=["F103", "F407"],
                        help="Chip family")
    parser.add_argument("--pins", required=True,
                        help='JSON string: [{"peripheral":"USART1","signal":"TX","pin":"PA9"},...]')
    parser.add_argument("--pins-file", default=None,
                        help="JSON file with pin assignments")
    args = parser.parse_args()

    if args.pins_file:
        with open(args.pins_file, "r", encoding="utf-8") as f:
            assignments = json.load(f)
    else:
        assignments = json.loads(args.pins)

    results = check_pin_conflicts(args.family, assignments)
    print(format_conflict_table(results))

    has_conflicts = any(r.level == "CONFLICT" for r in results)
    if has_conflicts:
        sys.exit(1)

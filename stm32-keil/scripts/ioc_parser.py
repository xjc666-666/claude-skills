"""
Parse CubeMX .ioc files (key=value format from CubeMX 5.0+)
and generate SPL initialization code skeleton.
"""
import os
import re
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import load_chip_db


class PinEntry(NamedTuple):
    pin: str
    signal: str
    mode: str
    label: str
    parameters: List[str]


class IOCConfig(NamedTuple):
    mcu_name: str
    mcu_series: str
    project_name: str
    pins: List[PinEntry]
    clock_config: Dict[str, str]
    peripherals: Dict[str, Dict[str, str]]
    raw_keys: Dict[str, str]


def parse_ioc(ioc_path: str) -> IOCConfig:
    """Parse a CubeMX .ioc file and return structured config."""
    if not os.path.isfile(ioc_path):
        raise FileNotFoundError(f".ioc file not found: {ioc_path}")

    with open(ioc_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Try JSON first (CubeMX 6+)
    if content.strip().startswith("{"):
        return _parse_json_format(content)

    # Standard CubeMX key=value format
    return _parse_kv_format(content)


def _parse_json_format(content: str) -> IOCConfig:
    data = json.loads(content)
    pins = []
    raw_keys = {}
    return IOCConfig(
        mcu_name=data.get("Mcu", {}).get("Name", "unknown"),
        mcu_series=data.get("Mcu", {}).get("Series", "unknown"),
        project_name=data.get("ProjectManager", {}).get("ProjectName", "unknown"),
        pins=pins,
        clock_config=data.get("RCC", {}),
        peripherals=data.get("Mcu", {}).get("IPs", {}),
        raw_keys=raw_keys,
    )


def _parse_kv_format(content: str) -> IOCConfig:
    """Parse CubeMX 5/6 key=value .ioc format."""
    raw = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            raw[key.strip()] = val.strip()

    # Extract MCU info
    mcu_name = raw.get("Mcu.Name", "unknown")
    mcu_series = raw.get("Mcu.Series", "unknown")
    project_name = raw.get("ProjectManager.ProjectName", "unknown")

    # Extract pins
    pins = _extract_pins(raw)

    # Extract clock config
    clock = _extract_clock(raw)

    # Extract peripherals
    peripherals = _extract_peripherals(raw)

    return IOCConfig(
        mcu_name=mcu_name,
        mcu_series=mcu_series,
        project_name=project_name,
        pins=pins,
        clock_config=clock,
        peripherals=peripherals,
        raw_keys=raw,
    )


def _extract_pins(raw: Dict[str, str]) -> List[PinEntry]:
    """Extract pin assignments from raw .ioc key-value pairs."""
    pins = []

    # Find all pin indices
    pin_idx_pattern = re.compile(r"^Mcu\.Pin(\d+)$")
    pin_indices = set()
    for key in raw:
        m = pin_idx_pattern.match(key)
        if m:
            pin_indices.add(int(m.group(1)))

    for idx in sorted(pin_indices):
        pin_name = raw.get(f"Mcu.Pin{idx}", "")
        signal = raw.get(f"Mcu.Pin{idx}.Signal", "")
        mode = raw.get(f"Mcu.Pin{idx}.Mode", "")
        label = raw.get(f"Mcu.Pin{idx}.GPIO_Label", "")
        params_str = raw.get(f"Mcu.Pin{idx}.GPIOParameters", "")
        params = [p.strip() for p in params_str.split(",") if p.strip()]

        if pin_name.startswith("VP_"):
            continue  # Skip virtual pins

        pins.append(PinEntry(pin=pin_name, signal=signal, mode=mode,
                             label=label, parameters=params))

    return pins


def _extract_clock(raw: Dict[str, str]) -> Dict[str, str]:
    """Extract clock tree settings."""
    clock = {}
    for key, val in raw.items():
        if key.startswith("RCC."):
            clock[key[4:]] = val  # strip "RCC." prefix
    return clock


def _extract_peripherals(raw: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    """Extract peripheral configurations."""
    periphs: Dict[str, Dict[str, str]] = {}
    ip_pattern = re.compile(r"^Mcu\.IP(\d+)$")
    ip_names = {}

    for key, val in raw.items():
        m = ip_pattern.match(key)
        if m:
            ip_names[m.group(1)] = val
        elif key.startswith("Mcu.IP") and "." in key:
            # e.g. Mcu.IP1.Instance=USART1
            rest = key[6:]  # strip "Mcu.IP"
            idx_str, _, prop = rest.partition(".")
            name = ip_names.get(idx_str, idx_str)
            periphs.setdefault(name, {})[prop] = val

    return periphs


def generate_spl_init_code(config: IOCConfig) -> str:
    """Generate SPL initialization code from parsed .ioc config."""
    lines = [
        "/**",
        f" * @brief  Auto-generated from CubeMX .ioc",
        f" *          MCU: {config.mcu_name}  Project: {config.project_name}",
        " */",
        "",
    ]

    # Map CubeMX MCU name to our chip DB
    chip_db = load_chip_db()
    family = _detect_family_from_mcu(config.mcu_name, chip_db)

    lines.append(f"/* Family: {family} */")
    lines.append("")
    lines.append("/* ---- Pin Assignments ---- */")
    lines.append("/*")
    for p in config.pins:
        label_str = f" ({p.label})" if p.label else ""
        lines.append(f" *  {p.pin:5s} : {p.signal}{label_str}")
    lines.append(" */")
    lines.append("")

    # Generate per-peripheral init code
    if family == "F407":
        lines.append('#include "stm32f4xx.h"')
    else:
        lines.append('#include "stm32f10x.h"')

    lines.append("")
    lines.append("void System_Init(void)")
    lines.append("{")

    # GPIO clocks + config for each pin
    ports_done = set()
    for p in config.pins:
        port = p.pin[:2]  # e.g., "PA"
        if port not in ports_done:
            ports_done.add(port)
            if family == "F407":
                lines.append(f"    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_{port}, ENABLE);")
            else:
                lines.append(f"    RCC_APB2PeriphClockCmd(RCC_APB2Periph_{port}, ENABLE);")

    lines.append("")
    for p in config.pins:
        lines.append(f"    /* {p.pin}: {p.signal} */")
        lines.append(f"    {{")
        lines.append(f"        GPIO_InitTypeDef g;")
        lines.append(f"        g.GPIO_Pin = GPIO_Pin_{p.pin[2:]};")
        if "AF" in p.mode:
            lines.append(f"        g.GPIO_Mode = GPIO_Mode_AF;")
            # Guess AF number from signal
            af = _guess_af(p.signal, family)
            if af is not None:
                port_letter = p.pin[1]
                pin_num = int(p.pin[2:])
                lines.append(f"        GPIO_PinAFConfig(GPIO{port_letter}, GPIO_PinSource{pin_num}, {af});")
        elif "OUTPUT" in p.mode or "OUT" in p.mode:
            lines.append(f"        g.GPIO_Mode = GPIO_Mode_OUT;")
        elif "INPUT" in p.mode or "IN" in p.mode:
            lines.append(f"        g.GPIO_Mode = GPIO_Mode_IN;")
        elif "ANALOG" in p.mode or "AN" in p.mode:
            lines.append(f"        g.GPIO_Mode = GPIO_Mode_AN;")

        lines.append(f"        g.GPIO_OType = GPIO_OType_PP;")
        lines.append(f"        g.GPIO_Speed = GPIO_Speed_100MHz;")
        lines.append(f"        g.GPIO_PuPd = GPIO_PuPd_UP;")
        lines.append(f"        GPIO_Init(GPIO{p.pin[1]}, &g);")
        lines.append(f"    }}")
        lines.append("")

    lines.append("}")
    return "\n".join(lines)


def _detect_family_from_mcu(mcu: str, chip_db: Dict) -> str:
    """Map CubeMX MCU name to F103/F407."""
    mcu_lower = mcu.lower()
    for name, info in chip_db.items():
        if name.lower().replace("stm32", "").replace("t6", "").replace("tx", "") in mcu_lower.replace("stm32", "").replace("t6", "").replace("tx", ""):
            return info["family"]
    if "f103" in mcu_lower or "stm32f1" in mcu_lower:
        return "F103"
    if "f407" in mcu_lower or "f405" in mcu_lower or "stm32f4" in mcu_lower:
        return "F407"
    return "unknown"


def _guess_af(signal: str, family: str) -> Optional[str]:
    """Guess GPIO_AF value from CubeMX signal name."""
    af_map = {
        "USART1_TX": "GPIO_AF_USART1", "USART1_RX": "GPIO_AF_USART1",
        "USART2_TX": "GPIO_AF_USART2", "USART2_RX": "GPIO_AF_USART2",
        "USART3_TX": "GPIO_AF_USART3", "USART3_RX": "GPIO_AF_USART3",
        "USART6_TX": "GPIO_AF_USART6", "USART6_RX": "GPIO_AF_USART6",
        "SPI1_SCK": "GPIO_AF_SPI1", "SPI1_MISO": "GPIO_AF_SPI1", "SPI1_MOSI": "GPIO_AF_SPI1",
        "SPI2_SCK": "GPIO_AF_SPI2", "SPI2_MISO": "GPIO_AF_SPI2", "SPI2_MOSI": "GPIO_AF_SPI2",
        "SPI3_SCK": "GPIO_AF_SPI3", "SPI3_MISO": "GPIO_AF_SPI3", "SPI3_MOSI": "GPIO_AF_SPI3",
        "I2C1_SCL": "GPIO_AF_I2C1", "I2C1_SDA": "GPIO_AF_I2C1",
        "I2C2_SCL": "GPIO_AF_I2C2", "I2C2_SDA": "GPIO_AF_I2C2",
        "CAN1_TX": "GPIO_AF_CAN1", "CAN1_RX": "GPIO_AF_CAN1",
        "CAN2_TX": "GPIO_AF_CAN2", "CAN2_RX": "GPIO_AF_CAN2",
    }
    for key, val in af_map.items():
        if key in signal:
            return val
    return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parse CubeMX .ioc file")
    parser.add_argument("--ioc", required=True, help="Path to .ioc file")
    parser.add_argument("--output", default=None, help="Write init code to file")
    parser.add_argument("--pins-only", action="store_true", help="Show only pin assignments")
    parser.add_argument("--init-project", default=None, metavar="DIR",
                        help="Create a Keil project in DIR seeded from this .ioc")
    parser.add_argument("--library", default="HAL", choices=["SPL", "HAL"],
                        help="Library to use when --init-project (default: HAL, since CubeMX is HAL-native)")
    parser.add_argument("--name", default=None,
                        help="Project name when --init-project (defaults to .ioc ProjectName)")
    args = parser.parse_args()

    config = parse_ioc(args.ioc)

    if args.init_project:
        from project_creator import create_project
        chip_db = load_chip_db()
        family = _detect_family_from_mcu(config.mcu_name, chip_db)
        # Pick a chip from chip_db that matches family + closest device suffix
        target_chip = None
        for name in chip_db:
            if chip_db[name]["family"] == family and chip_db[name]["device"][:11].lower() in config.mcu_name.lower():
                target_chip = name
                break
        if not target_chip:
            for name in chip_db:
                if chip_db[name]["family"] == family:
                    target_chip = name
                    break
        if not target_chip:
            print(f"Error: cannot map MCU {config.mcu_name} to chip_db.")
            sys.exit(1)

        proj_name = args.name or config.project_name or "CubeMX_Import"
        result = create_project(target_chip, proj_name, args.init_project, library=args.library)
        if not result["success"]:
            print(f"Project creation failed: {result['error']}")
            sys.exit(1)
        print(f"Project created at {result['project_path']}")

        # Save extracted init code as a hint to user
        init_path = os.path.join(result["project_path"], "User", "ioc_pins.txt")
        with open(init_path, "w", encoding="utf-8") as f:
            f.write(f"# Pin assignments imported from {args.ioc}\n\n")
            for p in config.pins:
                label = f"  ({p.label})" if p.label else ""
                f.write(f"{p.pin:6s} {p.signal:24s} {p.mode:10s}{label}\n")
        print(f"Pin map saved to {init_path}")
        sys.exit(0)

    if args.pins_only:
        print(f"MCU: {config.mcu_name} ({config.mcu_series})")
        print(f"Project: {config.project_name}")
        print()
        print(f"{'Pin':6s} | {'Signal':20s} | {'Mode':10s} | Label")
        print("-" * 60)
        for p in config.pins:
            print(f"{p.pin:6s} | {p.signal:20s} | {p.mode:10s} | {p.label}")
    else:
        code = generate_spl_init_code(config)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(code)
            print(f"Written to {args.output}")
        else:
            print(code)

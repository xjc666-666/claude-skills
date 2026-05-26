"""
MSPM0G3519 clock tree calculator.
40MHz HFXT -> PLL x4 -> 160MHz SYSPLL0 -> HSCLK
MFPCLK = 80MHz, CPUCLK = 80MHz
"""
import sys
import json
from pathlib import Path
from typing import Dict

SCRIPT_DIR = str(Path(__file__).resolve().parent)
SKILL_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)
from utils import load_chip_db


# Standard 80MHz configuration
# Source: 40MHz HFXT (PA5/PA6)
# EXHFMUX -> HFXT
# SYSPLLMUX -> HFCLK
# PLL_QDIV = 4 -> 160MHz SYSPLL0
# HSCLKMUX -> SYSPLL0 -> HSCLK = 160MHz
# MFPCLKMUX -> HFCLK -> MFPCLK = 80MHz
# HFCLK4MFPCLKDIV = 10 -> 8MHz
# UDIV = 2

STANDARD_CLOCK_CONFIG = {
    "description": "Standard MSPM0G3519 EVM clock: 40MHz HFXT -> PLL x4 -> 80MHz MCLK",
    "input": {
        "source": "HFXT",
        "pins": {"xin": "PA5", "xout": "PA6"},
        "frequency_mhz": 40,
    },
    "path": [
        {"node": "EXHFMUX", "select": "EXHFMUX_XTAL", "output_mhz": 40},
        {"node": "SYSPLLMUX", "select": "zSYSPLLMUX_HFCLK", "output_mhz": 40},
        {"node": "PLL_QDIV", "multiplier": 4, "output_mhz": 160},
        {"node": "HSCLKMUX", "select": "HSCLKMUX_SYSPLL0", "output_mhz": 160},
    ],
    "outputs": {
        "SYSPLL0": 160,
        "HSCLK": 160,
        "MFPCLK": 80,
        "CPUCLK": 80,
        "HFCLK4MFPCLK": 8,
    },
    "dividers": {
        "HFCLK4MFPCLKDIV": 10,
        "UDIV": 2,
    },
    "gates": {
        "MFCLKGATE": "enabled",
        "MFPCLKGATE": "enabled",
    },
}


def calculate_clock(target_cpuclk: int = 80, hfx_freq: int = 40) -> Dict:
    """Calculate MSPM0G3519 clock tree configuration."""
    if hfx_freq != 40:
        return {"success": False, "error": "Only 40MHz HFXT is supported for MSPM0G3519 EVM"}

    if target_cpuclk != 80:
        return {"success": False, "error": "Only 80MHz CPUCLK is the validated config for this board"}

    return {"success": True, "config": STANDARD_CLOCK_CONFIG}


def print_clock_diagram() -> None:
    """Print ASCII clock tree diagram."""
    cfg = STANDARD_CLOCK_CONFIG
    print("MSPM0G3519 Clock Tree (Standard 80MHz)")
    print("=" * 50)
    print(f"  HFXT ({cfg['input']['frequency_mhz']}MHz) [{cfg['input']['pins']['xin']}/{cfg['input']['pins']['xout']}]")
    print("    |")
    print("  EXHFMUX (XTAL)")
    print("    |")
    print("  SYSPLLMUX (HFCLK)")
    print("    |")
    print(f"  PLL_QDIV (x{cfg['path'][2]['multiplier']}) -> SYSPLL0 = {cfg['outputs']['SYSPLL0']}MHz")
    print("    |")
    print("  HSCLKMUX (SYSPLL0)")
    print("    |")
    print(f"  HSCLK = {cfg['outputs']['HSCLK']}MHz")
    print("    ├── MFPCLKMUX -> MFPCLK/CPUCLK = 80MHz")
    print(f"    ├── HFCLK4MFPCLKDIV (/{cfg['dividers']['HFCLK4MFPCLKDIV']}) -> {cfg['outputs']['HFCLK4MFPCLK']}MHz")
    print(f"    └── UDIV (/{cfg['dividers']['UDIV']})")
    print()
    print("Gates: MFCLK=enabled, MFPCLK=enabled")
    print()


def get_syscfg_js() -> str:
    """Return the JS code to paste into config.syscfg for standard clock config."""
    return """// Standard 80MHz clock configuration (40MHz HFXT -> PLL x4)
const divider2       = system.clockTree["HFCLK4MFPCLKDIV"];
divider2.divideValue = 10;

const divider9       = system.clockTree["UDIV"];
divider9.divideValue = 2;

const gate7  = system.clockTree["MFCLKGATE"];
gate7.enable = true;

const gate8  = system.clockTree["MFPCLKGATE"];
gate8.enable = true;

const multiplier2         = system.clockTree["PLL_QDIV"];
multiplier2.multiplyValue = 4;

const mux4       = system.clockTree["EXHFMUX"];
mux4.inputSelect = "EXHFMUX_XTAL";

const mux8       = system.clockTree["HSCLKMUX"];
mux8.inputSelect = "HSCLKMUX_SYSPLL0";

const mux10       = system.clockTree["MFPCLKMUX"];
mux10.inputSelect = "MFPCLKMUX_HFCLK";

const mux12       = system.clockTree["SYSPLLMUX"];
mux12.inputSelect = "zSYSPLLMUX_HFCLK";

const pinFunction4                        = system.clockTree["HFXT"];
pinFunction4.inputFreq                    = 40;
pinFunction4.enable                       = true;
pinFunction4.HFXTStartup                  = 10;
pinFunction4.peripheral.$assign           = "SYSCTL";
pinFunction4.peripheral.hfxInPin.$assign  = "PA5";
pinFunction4.peripheral.hfxOutPin.$assign = "PA6";

const pinFunction6     = system.clockTree["LFXT"];
pinFunction6.inputFreq = 32.768;"""


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MSPM0G3519 Clock Tree Calculator")
    parser.add_argument("--target", type=int, default=80, help="Target CPUCLK in MHz (only 80 supported)")
    parser.add_argument("--hfx-freq", type=int, default=40, help="HFXT frequency in MHz (only 40 supported)")
    parser.add_argument("--output-diagram", action="store_true", help="Print ASCII clock tree")
    parser.add_argument("--output-syscfg-js", action="store_true", help="Output syscfg JS snippet")

    args = parser.parse_args()

    if args.output_diagram:
        print_clock_diagram()
    elif args.output_syscfg_js:
        print(get_syscfg_js())
    else:
        result = calculate_clock(args.target, args.hfx_freq)
        print(json.dumps(result, indent=2, ensure_ascii=False))

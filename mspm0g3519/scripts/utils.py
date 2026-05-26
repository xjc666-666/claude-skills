"""
Shared utilities for mspm0g3519 skill scripts.
All data types and helper functions used across scripts.
"""
import os
import sys
import re
import json
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple, Dict, NamedTuple

SKILL_DIR = str(Path(__file__).resolve().parent.parent)


class BuildError(NamedTuple):
    file: str
    line: int
    code: str
    message: str


class BuildResult(NamedTuple):
    success: bool
    errors: List[BuildError]
    warnings: List[BuildError]
    output: str
    hex_path: Optional[str] = None
    size_info: Optional[Dict] = None
    chip: Optional[str] = None


class PinConflict(NamedTuple):
    pin: str
    peripheral1: str
    peripheral2: str
    severity: str  # "CONFLICT", "WARNING", "OK"


MSPM0G3519_FLASH = 512 * 1024   # 512 KB
MSPM0G3519_RAM = 128 * 1024     # 64 KB Bank0 + 64 KB Bank1
MSPM0G3519_CPUCLK = 80000000    # 80 MHz


def normalize_path(path: str) -> str:
    """Convert path to forward-slash format."""
    return path.replace("\\", "/")


def ensure_dir(path: str) -> str:
    """Create directory if not exists, return path."""
    os.makedirs(path, exist_ok=True)
    return path


def run_command(cmd: List[str], cwd: Optional[str] = None,
                timeout: int = 300) -> Tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd, cwd=cwd,
            capture_output=True, text=True,
            timeout=timeout,
            encoding="utf-8", errors="ignore"
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s: {' '.join(cmd)}"
    except FileNotFoundError:
        return -2, "", f"Command not found: {cmd[0]}"


def find_keil_installation() -> Optional[str]:
    """Find Keil MDK-ARM UV4 directory. Returns path to directory containing uv4.exe."""
    import winreg

    # 1. Check KEIL_PATH environment variable
    for env in ("KEIL_PATH", "UV4_PATH"):
        val = os.environ.get(env)
        if val and os.path.isfile(os.path.join(val, "uv4.exe")):
            return normalize_path(val)

    # 2. Check Windows registry
    try:
        for root_key, path in [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Keil\Products\MDK"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Keil\Products\MDK"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Keil\Products\MDK"),
        ]:
            try:
                key = winreg.OpenKey(root_key, path)
                val, _ = winreg.QueryValueEx(key, "Path")
                winreg.CloseKey(key)
                if val and os.path.isfile(os.path.join(val, "uv4.exe")):
                    return normalize_path(val)
            except (FileNotFoundError, OSError):
                continue
    except Exception:
        pass

    # 3. Check standard paths
    standard_paths = [
        r"D:\keil\Keil_v5\UV4",
        r"C:\Keil_v5\UV4",
        r"C:\Keil\UV4",
        r"D:\Keil_v5\UV4",
        r"D:\Keil\UV4",
    ]
    for p in standard_paths:
        if os.path.isfile(os.path.join(p, "uv4.exe")):
            return normalize_path(p)

    # 4. Search PATH
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if os.path.isfile(os.path.join(p, "uv4.exe")):
            return normalize_path(p)

    return None


def load_chip_db() -> Dict:
    """Load chip_db.json from skill directory."""
    path = os.path.join(SKILL_DIR, "chip_db.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_error_patterns() -> Dict:
    """Load error_patterns.json."""
    path = os.path.join(SKILL_DIR, "references", "error_patterns.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_hardware_pin_map() -> Dict:
    """Load hardware_pin_map.json."""
    path = os.path.join(SKILL_DIR, "references", "hardware_pin_map.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_peripheral_db() -> Dict:
    """Load peripheral_db.json."""
    path = os.path.join(SKILL_DIR, "references", "peripheral_db.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_bsp_index() -> Dict:
    """Load bsp_index.json."""
    path = os.path.join(SKILL_DIR, "references", "bsp_index.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_sdk_paths_config() -> Dict:
    """Load sdk_paths.json."""
    path = os.path.join(SKILL_DIR, "references", "sdk_paths.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_pin_reserved(pin: str) -> bool:
    """Check if a pin is in the hardware reserved list."""
    hw = load_hardware_pin_map()
    return pin in hw.get("reserved_pins", [])


def get_reserved_pin_reason(pin: str) -> Optional[str]:
    """Get the reason why a pin is reserved."""
    hw = load_hardware_pin_map()
    return hw.get("reserved_pins_reason", {}).get(pin)


def extract_functions_from_c(filepath: str) -> List[Dict]:
    """Extract function definitions from a C source file.
    Returns list of {'name': str, 'line': int, 'signature': str}."""
    if not os.path.isfile(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return []
    funcs = []
    pattern = re.compile(
        r'^(?:\w+(?:\s+\*)?\s+)+(\w+)\s*\(([^)]*)\)\s*\{',
        re.MULTILINE
    )
    for m in pattern.finditer(content):
        line_num = content[:m.start()].count('\n') + 1
        funcs.append({
            "name": m.group(1),
            "line": line_num,
            "signature": m.group(0).strip()
        })
    return funcs


def extract_includes_from_c(filepath: str) -> List[str]:
    """Extract #include directives from a C source file."""
    if not os.path.isfile(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return []
    return re.findall(r'^\s*#include\s+[<"]([^>"]+)[>"]', content, re.MULTILINE)


def find_in_project(project_dir: str, pattern: str) -> List[str]:
    """Find files matching a glob pattern within a project directory."""
    import glob
    search_path = os.path.join(project_dir, pattern)
    return sorted(glob.glob(search_path, recursive=True))


def format_size_info(size: Dict) -> str:
    """Format program size info as human-readable string."""
    flash = size.get("flash_bytes", 0)
    ram = size.get("ram_bytes", 0)
    fp = 100.0 * flash / MSPM0G3519_FLASH if MSPM0G3519_FLASH else 0
    rp = 100.0 * ram / MSPM0G3519_RAM if MSPM0G3519_RAM else 0

    def _kb(n):
        return f"{n/1024:.1f} KB" if n >= 1024 else f"{n} B"

    body = (
        f"Code={size.get('code', 0)} B, RO-data={size.get('ro_data', 0)} B, "
        f"RW-data={size.get('rw_data', 0)} B, ZI-data={size.get('zi_data', 0)} B"
    )
    flags = []
    if fp >= 90:
        flags.append(f"WARNING: Flash {fp:.0f}%")
    if rp >= 90:
        flags.append(f"WARNING: RAM {rp:.0f}%")
    suffix = "  " + " ".join(flags) if flags else ""

    return (
        f"占用: Flash={_kb(flash)}/{_kb(MSPM0G3519_FLASH)} ({fp:.1f}%), "
        f"RAM={_kb(ram)}/{_kb(MSPM0G3519_RAM)} ({rp:.1f}%){suffix}\n"
        f"  ({body})"
    )

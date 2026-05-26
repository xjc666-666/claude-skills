"""
Shared utilities for stm32-keil skill.
"""
import os
import re
import subprocess
import json
import sys
from pathlib import Path
from typing import Optional, Tuple, Dict, List, NamedTuple


# Known Keil installation paths to search (checked in order)
_KNOWN_KEIL_PATHS = [
    r"C:\Keil_v5",
    r"D:\Keil_v5",
    r"E:\Keil_v5",
    r"F:\Keil_v5",
    r"C:\keil\Keil_v5",
    r"D:\keil\Keil_v5",
    r"E:\keil\Keil_v5",
    r"F:\keil\Keil_v5",
    r"C:\Keil",
    r"D:\Keil",
    r"C:\Program Files\Keil_v5",
    r"C:\Program Files (x86)\Keil_v5",
    r"D:\Program Files\Keil_v5",
    r"D:\Program Files (x86)\Keil_v5",
]

_KNOWN_STLINK_PATHS = [
    r"C:\Program Files (x86)\STMicroelectronics\STM32 ST-LINK Utility\ST-LINK Utility\ST-LINK_CLI.exe",
    r"C:\Program Files\STMicroelectronics\STM32 ST-LINK Utility\ST-LINK Utility\ST-LINK_CLI.exe",
    r"D:\Program Files (x86)\STMicroelectronics\STM32 ST-LINK Utility\ST-LINK Utility\ST-LINK_CLI.exe",
    r"D:\Program Files\STMicroelectronics\STM32 ST-LINK Utility\ST-LINK Utility\ST-LINK_CLI.exe",
]


def _try_registry_keil() -> Optional[str]:
    """Try to find Keil path from Windows registry."""
    try:
        import winreg
        # Keil stores path at HKLM\SOFTWARE\WOW6432Node\Keil\Products\MDK
        # Path value points to <install>\ARM, UV4 is at <install>\UV4
        keys_to_try = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Keil\Products\MDK"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Keil\Products\MDK"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Keil\Products\MDK"),
        ]
        for hkey, subkey in keys_to_try:
            try:
                with winreg.OpenKey(hkey, subkey) as key:
                    path, _ = winreg.QueryValueEx(key, "Path")
                    if path:
                        # Path is <install>\ARM, UV4 is at <install>\UV4
                        install_root = os.path.dirname(path)
                        uv4 = os.path.join(install_root, "UV4", "uv4.exe")
                        if os.path.isfile(uv4):
                            return os.path.join(install_root, "UV4")
            except (OSError, FileNotFoundError):
                continue
    except Exception:
        pass
    return None


def _try_registry_stlink() -> Optional[str]:
    """Try to find ST-LINK CLI from Windows registry or standard locations."""
    # Check environment variable first
    env_stlink = os.environ.get("STLINK_PATH", "") or os.environ.get("STLINK_CLI_PATH", "")
    if env_stlink and os.path.isfile(env_stlink):
        return env_stlink

    # Check common install directories on all likely drives
    for drive in ["C", "D", "E", "F"]:
        for prog in ["Program Files", "Program Files (x86)"]:
            p = os.path.join(f"{drive}:\\", prog, "STMicroelectronics",
                           "STM32 ST-LINK Utility", "ST-LINK Utility", "ST-LINK_CLI.exe")
            if os.path.isfile(p):
                return p

    # Search PATH for ST-LINK_CLI.exe
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(path_dir, "ST-LINK_CLI.exe")
        if os.path.isfile(p):
            return p

    return None


def find_keil_installation() -> Optional[str]:
    """Search for Keil MDK-ARM v5 installation. Returns path to UV4 directory."""
    # 1. Check environment variable
    env_keil = os.environ.get("KEIL_PATH", "")
    if env_keil:
        uv4 = os.path.join(env_keil, "UV4", "uv4.exe")
        if os.path.isfile(uv4):
            return os.path.join(env_keil, "UV4")

    # 2. Try Windows registry
    result = _try_registry_keil()
    if result:
        return result

    # 3. Check %ProgramFiles% / %ProgramFiles(x86)% (handles non-English Windows)
    for env_var in ("ProgramFiles", "ProgramFiles(x86)"):
        pf = os.environ.get(env_var, "")
        if pf:
            uv4 = os.path.join(pf, "Keil_v5", "UV4", "uv4.exe")
            if os.path.isfile(uv4):
                return os.path.join(pf, "Keil_v5", "UV4")

    # 4. Check known paths (C/D/E/F drives)
    for p in _KNOWN_KEIL_PATHS:
        uv4 = os.path.join(p, "UV4", "uv4.exe")
        if os.path.isfile(uv4):
            return os.path.join(p, "UV4")

    # 4. Search PATH for uv4.exe
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        uv4 = os.path.join(path_dir, "uv4.exe")
        if os.path.isfile(uv4):
            return path_dir

    return None


def find_stlink_utility() -> Optional[str]:
    """Search for ST-LINK CLI utility (legacy, deprecated 2019)."""
    result = _try_registry_stlink()
    if result:
        return result
    for p in _KNOWN_STLINK_PATHS:
        if os.path.isfile(p):
            return p
    return None


def find_cube_programmer() -> Optional[str]:
    """Find STM32_Programmer_CLI.exe (modern ST tool)."""
    env = os.environ.get("STM32_CUBE_PROG", "") or os.environ.get("CUBE_PROG_PATH", "")
    if env and os.path.isfile(env):
        return env

    known = [
        r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe",
        r"C:\Program Files (x86)\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe",
        r"D:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe",
        r"D:\Program Files (x86)\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe",
    ]
    for p in known:
        if os.path.isfile(p):
            return p

    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(path_dir, "STM32_Programmer_CLI.exe")
        if os.path.isfile(p):
            return p
    return None


def find_jlink_exe() -> Optional[str]:
    """Find JLink.exe / JLinkExe (Segger)."""
    env = os.environ.get("JLINK_PATH", "")
    if env and os.path.isfile(env):
        return env

    for drive in ["C", "D", "E", "F"]:
        for prog in ["Program Files", "Program Files (x86)"]:
            for ver in ["", "_V8", "_V7"]:
                p = os.path.join(f"{drive}:\\", prog, "SEGGER", f"JLink{ver}", "JLink.exe")
                if os.path.isfile(p):
                    return p

    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        for name in ("JLink.exe", "JLinkExe"):
            p = os.path.join(path_dir, name)
            if os.path.isfile(p):
                return p
    return None


def _read_keil_pack_root_from_registry() -> Optional[str]:
    """Newer Keil installers store the Pack root in the registry
    (HKCU\\Software\\Keil\\Path or similar). Try a few known keys."""
    try:
        import winreg
    except ImportError:
        return None
    for hkey, sub in [
        (winreg.HKEY_CURRENT_USER, r"Software\Keil\Path"),
        (winreg.HKEY_CURRENT_USER, r"Software\Keil"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Keil\Path"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Keil\Path"),
    ]:
        try:
            with winreg.OpenKey(hkey, sub) as k:
                for value in ("CMSIS_PACK_ROOT", "PackRoot", "PACK"):
                    try:
                        v, _ = winreg.QueryValueEx(k, value)
                        if v and os.path.isdir(v):
                            return v
                    except OSError:
                        continue
        except OSError:
            continue
    return None


def get_arm_packs_dir() -> Optional[str]:
    """Return one ARM Packs directory. See list_pack_dirs() for full list."""
    dirs = list_pack_dirs()
    return dirs[0] if dirs else None


def list_pack_dirs() -> List[str]:
    """All places Keil might have stashed DFPs.

    Order:
      1. CMSIS_PACK_ROOT environment variable (CMSIS-Pack standard)
      2. Registry value (HKCU\\Software\\Keil\\Path\\CMSIS_PACK_ROOT or sim.)
      3. %LOCALAPPDATA%\\Arm\\Packs (modern Keil installer default)
      4. <Keil-install>\\..\\Arm\\Packs (alternate install layout — sibling)
      5. <Keil-install>\\..\\ARM\\PACK (legacy single-machine install)
      6. C:\\Users\\Public\\Arm\\Packs (multi-user shared)
    """
    seen = []

    # 1. CMSIS-Pack standard env var
    env = os.environ.get("CMSIS_PACK_ROOT", "")
    if env and os.path.isdir(env):
        seen.append(env)

    # 2. Registry
    reg = _read_keil_pack_root_from_registry()
    if reg and reg not in seen and os.path.isdir(reg):
        seen.append(reg)

    # 3. LOCALAPPDATA / USERPROFILE
    for d in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Arm", "Packs"),
              os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local", "Arm", "Packs")):
        if d and os.path.isdir(d) and d not in seen:
            seen.append(d)

    # 4 & 5. Beside the Keil install (sibling Arm\Packs or ARM\PACK)
    keil = find_keil_installation()
    if keil:
        # keil points at <root>\UV4; pack roots live two levels up + Arm\Packs
        keil_root = os.path.normpath(os.path.join(keil, "..", ".."))
        for layout in (("Arm", "Packs"), ("ARM", "Packs"), ("ARM", "PACK")):
            d = os.path.normpath(os.path.join(keil_root, *layout))
            if os.path.isdir(d) and d not in seen:
                seen.append(d)

    # 6. Public profile
    for d in (r"C:\Users\Public\Arm\Packs",):
        if os.path.isdir(d) and d not in seen:
            seen.append(d)

    return seen


def validate_chip(chip_name: str, chip_db_path: Optional[str] = None) -> bool:
    """Check if chip name exists in the chip database."""
    db = load_chip_db(chip_db_path)
    return chip_name in db


def get_chip_family(chip_name: str, chip_db_path: Optional[str] = None) -> str:
    """Return chip family ("F103" or "F407") from chip name."""
    db = load_chip_db(chip_db_path)
    if chip_name in db:
        return db[chip_name].get("family", "")
    if "F103" in chip_name:
        return "F103"
    if "F407" in chip_name:
        return "F407"
    return ""


def load_chip_db(chip_db_path: Optional[str] = None) -> Dict:
    """Load chip database JSON."""
    if chip_db_path is None:
        skill_dir = Path(__file__).resolve().parent.parent
        chip_db_path = skill_dir / "chip_db.json"
    with open(chip_db_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_error_patterns() -> Dict:
    """Load error fix patterns JSON."""
    skill_dir = Path(__file__).resolve().parent.parent
    patterns_path = skill_dir / "references" / "error_patterns.json"
    with open(patterns_path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_path(path: str) -> str:
    """Normalize Windows paths to forward slashes."""
    return str(Path(path)).replace("\\", "/")


def run_command(cmd: List[str], cwd: Optional[str] = None, timeout: int = 120) -> Tuple[int, str, str]:
    """Execute a command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=True if sys.platform == "win32" else False,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def find_in_project(project_dir: str, pattern: str) -> List[str]:
    """Find files matching pattern in project directory."""
    import glob
    return glob.glob(os.path.join(project_dir, pattern), recursive=True)


def extract_functions_from_c(filepath: str) -> List[Dict]:
    """
    Extract function definitions from a C source file.
    Returns list of {name, return_type, params, body, start_line, end_line}.
    Uses simple regex-based extraction (not a full parser).
    """
    if not os.path.isfile(filepath):
        return []

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    functions = []
    pattern = re.compile(
        r'^\s*((?:static\s+|inline\s+|__IO\s+|volatile\s+|extern\s+)*'
        r'[\w\s\*]+?)\s+(\w+)\s*\((.*?)\)\s*\{',
        re.MULTILINE | re.DOTALL
    )

    for match in pattern.finditer(content):
        return_type = match.group(1).strip()
        name = match.group(2)
        params = match.group(3).strip()
        start = match.end() - 1  # position of opening brace

        if not name.startswith("_"):
            body = _extract_brace_block(content, start)
            functions.append({
                "name": name,
                "return_type": return_type,
                "params": params,
                "body": body,
                "start_line": content[:match.start()].count("\n") + 1,
            })

    return functions


def extract_includes_from_c(filepath: str) -> List[str]:
    """Extract #include directives from a C file."""
    if not os.path.isfile(filepath):
        return []

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    pattern = re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]', re.MULTILINE)
    return [m.group(1) for m in pattern.finditer(content)]


def extract_defines_from_h(filepath: str) -> Dict[str, str]:
    """Extract #define macros from a header file."""
    if not os.path.isfile(filepath):
        return {}

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    defines = {}
    pattern = re.compile(r'^\s*#define\s+(\w+)\s+(.+?)(?://.*)?$', re.MULTILINE)
    for match in pattern.finditer(content):
        defines[match.group(1)] = match.group(2).strip()
    return defines


def _extract_brace_block(text: str, open_pos: int) -> str:
    """Extract content between matching braces starting at open_pos."""
    depth = 0
    for i in range(open_pos, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_pos + 1:i]
    return ""


def ensure_dir(path: str) -> str:
    """Create directory if it doesn't exist, return path."""
    os.makedirs(path, exist_ok=True)
    return path


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

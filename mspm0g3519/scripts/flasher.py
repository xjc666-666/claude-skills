"""
Flash MSPM0G3519 firmware via CMSIS-DAP (Keil uv4 -f) or J-Link fallback.
"""
import os
import sys
import re
import json
import tempfile
from pathlib import Path
from typing import Optional, Dict, List

SCRIPT_DIR = str(Path(__file__).resolve().parent)
sys.path.insert(0, SCRIPT_DIR)
from utils import find_keil_installation, run_command, normalize_path, load_chip_db


def flash(uvprojx_path: str, backend: str = "auto",
          verify: bool = True, timeout: int = 120) -> Dict:
    """Flash firmware to MSPM0G3519."""

    if backend == "auto":
        backend = "keil"  # Default: CMSIS-DAP via Keil

    project_dir = os.path.dirname(uvprojx_path)

    if backend == "keil":
        return _flash_keil(uvprojx_path, project_dir, timeout)
    elif backend == "jlink":
        hex_path = _find_hex(project_dir)
        if not hex_path:
            return {"success": False, "error": "No .hex file found. Build first."}
        return _flash_jlink(hex_path, "MSPM0G3519", timeout)
    else:
        return {"success": False, "error": f"Unknown backend: {backend}"}


def _flash_keil(uvprojx_path: str, project_dir: str, timeout: int) -> Dict:
    """Flash via Keil uv4 -f (CMSIS-DAP)."""
    keil_dir = find_keil_installation()
    if keil_dir is None:
        # Try J-Link fallback
        jlink = _find_jlink()
        if jlink:
            hex_path = _find_hex(project_dir)
            if hex_path:
                print("Keil not found, trying J-Link fallback...")
                return _flash_jlink(hex_path, "MSPM0G3519", timeout)
        return {"success": False, "error": "Keil not found and no J-Link available"}

    uv4_exe = os.path.join(keil_dir, "uv4.exe")
    project_file = os.path.basename(uvprojx_path)

    flash_log = os.path.join(project_dir, "flash.log")
    cmd = [uv4_exe, "-j0", "-f", project_file, "-o", flash_log]

    returncode, stdout, stderr = run_command(cmd, cwd=project_dir, timeout=timeout)

    # Read flash log
    log_content = ""
    if os.path.isfile(flash_log):
        try:
            with open(flash_log, "r", encoding="utf-8", errors="ignore") as f:
                log_content = f.read()
        except Exception:
            pass

    success = returncode == 0
    if not success and log_content:
        # Check for common success indicators even if returncode != 0
        if "Application running" in log_content or "Programming Done" in log_content:
            success = True

    result = {
        "success": success,
        "backend": "keil",
        "debugger": "CMSIS-DAP",
        "stdout": stdout[-500:] if stdout else "",
        "stderr": stderr[-500:] if stderr else "",
        "flash_log": log_content[-500:] if log_content else "",
    }

    if not success:
        result["troubleshooting"] = [
            "检查 CMSIS-DAP 调试器 USB 连接",
            "检查 SWD 接线: SWCLK=PA20, SWDIO=PA19",
            "检查板子供电 (3.3V)",
            "在 Keil 中检查 Target 配置: CMSIS-DAP Debugger",
        ]

    return result


def _flash_jlink(hex_path: str, device: str, timeout: int) -> Dict:
    """Flash via J-Link."""
    jlink_exe = _find_jlink()
    if jlink_exe is None:
        return {"success": False, "error": "J-Link not found"}

    # Write J-Link command script
    script = f"""si SWD
speed 4000
device {device}
loadfile "{hex_path}"
r
g
q
"""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jlink", delete=False)
    tmp.write(script)
    tmp.close()

    cmd = [jlink_exe, "-Device", device, "-If", "SWD", "-Speed", "4000",
           "-CommandFile", tmp.name]

    returncode, stdout, stderr = run_command(cmd, timeout=timeout)

    try:
        os.unlink(tmp.name)
    except OSError:
        pass

    success = returncode == 0 or "O.K." in stdout

    return {
        "success": success,
        "backend": "jlink",
        "stdout": stdout[-500:] if stdout else "",
        "stderr": stderr[-500:] if stderr else "",
    }


def _find_hex(project_dir: str) -> Optional[str]:
    """Find .hex file in project."""
    for sub in ("Objects", "Listings"):
        d = os.path.join(project_dir, sub)
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".hex"):
                    return os.path.join(d, f)
    return None


def _find_jlink() -> Optional[str]:
    """Find JLink.exe."""
    # Check env
    jlink = os.environ.get("JLINK_PATH")
    if jlink and os.path.isfile(jlink):
        return jlink

    # Check standard paths
    for path in [
        r"C:\Program Files\SEGGER\JLink\JLink.exe",
        r"C:\Program Files (x86)\SEGGER\JLink\JLink.exe",
        r"D:\Program Files\SEGGER\JLink\JLink.exe",
    ]:
        if os.path.isfile(path):
            return path

    # Check PATH
    for p in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(p, "JLink.exe")
        if os.path.isfile(candidate):
            return candidate

    return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Flash MSPM0G3519 firmware")
    parser.add_argument("--project", required=True, help="Path to .uvprojx file")
    parser.add_argument("--backend", default="auto", choices=["auto", "keil", "jlink"],
                        help="Flash backend")
    parser.add_argument("--no-verify", action="store_true", help="Skip verification")

    args = parser.parse_args()

    result = flash(args.project, backend=args.backend, verify=not args.no_verify)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["success"]:
        sys.exit(1)

"""
Copy the full MSPM0 DriverLib from SDK into a project.
"""
import os
import sys
import shutil
import json
from pathlib import Path
from typing import Dict, List, Optional

SCRIPT_DIR = str(Path(__file__).resolve().parent)
SKILL_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)

from utils import normalize_path, ensure_dir, load_chip_db
from sdk_detector import find_sdk

# All DriverLib .c files that need to be in the Keil Source group
DRIVERLIB_C_FILES = [
    "dl_adc12.c", "dl_aes.c", "dl_aesadv.c", "dl_common.c",
    "dl_comp.c", "dl_crc.c", "dl_crcp.c", "dl_dac12.c",
    "dl_dma.c", "dl_flashctl.c", "dl_gpamp.c", "dl_gpio.c",
    "dl_i2c.c", "dl_i2s.c", "dl_interrupt.c", "dl_iwdt.c",
    "dl_keystorectl.c", "dl_lcd.c", "dl_lfss.c", "dl_mathacl.c",
    "dl_mcan.c", "dl_npu.c", "dl_opa.c", "dl_rtc.c",
    "dl_rtc_a.c", "dl_rtc_b.c", "dl_rtc_common.c", "dl_scratchpad.c",
    "dl_spgss.c", "dl_spi.c", "dl_tamperio.c", "dl_timer.c",
    "dl_timera.c", "dl_timerb.c", "dl_timerg.c", "dl_trng.c",
    "dl_uart.c", "dl_unicomm.c", "dl_unicommi2cc.c",
    "dl_unicommi2ct.c", "dl_unicommspi.c", "dl_unicommuart.c",
    "dl_vref.c", "dl_wwdt.c",
]

M0P_DRIVERLIB_FILES = [
    "dl_factoryregion.c", "dl_interrupt.c",
    "dl_sysctl_mspm0gx51x.c",
]


def copy_driverlib(project_path: str, sdk_path: Optional[str] = None) -> Dict:
    """Copy full DriverLib from SDK to project Source/ti/driverlib/."""

    if sdk_path is None:
        sdk_info = find_sdk()
        if sdk_info is None:
            return {"success": False, "error": "MSPM0 SDK not found"}
        sdk_path = sdk_info["path"]

    sdk_src = os.path.join(sdk_path, "source", "ti")
    if not os.path.isdir(sdk_src):
        return {"success": False, "error": f"SDK source not found: {sdk_src}"}

    proj_src = os.path.join(project_path, "Source", "ti")
    ensure_dir(proj_src)

    files_copied = []

    # Copy driverlib/
    sdk_drv = os.path.join(sdk_src, "driverlib")
    proj_drv = os.path.join(proj_src, "driverlib")
    if os.path.isdir(proj_drv):
        shutil.rmtree(proj_drv)
    shutil.copytree(sdk_drv, proj_drv, ignore=shutil.ignore_patterns("*.lib", "*.a"))
    files_copied.append(f"driverlib/ ({_count_files(proj_drv)} files)")

    # Copy full devices/ directory (includes DeviceFamily.h, msp/, m0p/...)
    sdk_dev = os.path.join(sdk_src, "devices")
    proj_dev = os.path.join(proj_src, "devices")
    if os.path.isdir(proj_dev):
        shutil.rmtree(proj_dev)
    shutil.copytree(sdk_dev, proj_dev)
    files_copied.append(f"devices/ ({_count_files(proj_dev)} files)")

    # Count results
    total = sum(1 for _ in Path(proj_src).rglob("*") if _.is_file())

    return {
        "success": True,
        "sdk_path": normalize_path(sdk_path),
        "project_path": normalize_path(project_path),
        "files_copied": files_copied,
        "total_files": total,
        "driverlib_path": normalize_path(proj_drv),
    }


def get_driverlib_c_files(project_path: str) -> List[str]:
    """Get list of DriverLib .c files present in project, relative to project."""
    drv_dir = os.path.join(project_path, "Source", "ti", "driverlib")
    files = []
    if os.path.isdir(drv_dir):
        for f in sorted(os.listdir(drv_dir)):
            if f.endswith(".c"):
                files.append(f)
    # Also check m0p/
    m0p_dir = os.path.join(drv_dir, "m0p")
    if os.path.isdir(m0p_dir):
        for f in sorted(os.listdir(m0p_dir)):
            if f.endswith(".c"):
                files.append(f"m0p/{f}")
    return files


def check_driverlib(project_path: str, sdk_path: Optional[str] = None) -> Dict:
    """Check if DriverLib in project matches SDK. Report missing files."""
    if sdk_path is None:
        sdk_info = find_sdk()
        if sdk_info is None:
            return {"success": False, "error": "MSPM0 SDK not found"}
        sdk_path = sdk_info["path"]

    sdk_drv = os.path.join(sdk_path, "source", "ti", "driverlib")
    proj_drv = os.path.join(project_path, "Source", "ti", "driverlib")

    if not os.path.isdir(proj_drv):
        return {"success": False, "error": "DriverLib not found in project",
                "missing_all": True}

    missing = []
    expected = DRIVERLIB_C_FILES + [f"m0p/{f}" for f in M0P_DRIVERLIB_FILES]
    for f in expected:
        if not os.path.isfile(os.path.join(proj_drv, f)):
            missing.append(f)

    return {
        "success": len(missing) == 0,
        "missing": missing,
        "total_expected": len(expected),
        "total_present": len(expected) - len(missing),
    }


def _count_files(directory: str) -> int:
    return sum(1 for _ in Path(directory).rglob("*") if _.is_file())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Copy DriverLib from SDK to project")
    parser.add_argument("--project-path", required=True, help="Project root directory")
    parser.add_argument("--sdk-path", default=None, help="SDK path (auto-detect if omitted)")
    parser.add_argument("--check", action="store_true", help="Check only, don't copy")
    args = parser.parse_args()

    if args.check:
        result = check_driverlib(args.project_path, args.sdk_path)
    else:
        result = copy_driverlib(args.project_path, args.sdk_path)

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    if not result["success"]:
        sys.exit(1)

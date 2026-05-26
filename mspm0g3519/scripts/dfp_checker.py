"""
Check MSPM0G3519 toolchain: Keil, TI DFP, MSPM0 SDK, SysConfig.
"""
import os
import sys
import json
from pathlib import Path
from typing import Dict

SCRIPT_DIR = str(Path(__file__).resolve().parent)
SKILL_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)

from sdk_detector import find_sdk, find_sysconfig, find_dfp, find_all
from utils import find_keil_installation, load_chip_db


def check_toolchain() -> Dict:
    """Run all toolchain checks and return detailed status."""
    chip_db = load_chip_db()
    chip_info = chip_db.get("MSPM0G3519", {})

    # Keil
    keil_path = find_keil_installation()
    keil_ok = keil_path is not None

    # DFP
    dfp_info = find_dfp()

    # SDK
    sdk_info = find_sdk()
    sdk_ok = sdk_info is not None
    sdk_version_ok = False
    if sdk_ok and sdk_info.get("version"):
        req = chip_info.get("sdk_version", "2.08.00.03")
        sdk_version_ok = sdk_info["version"] == req

    # SysConfig
    syscfg_info = find_sysconfig()
    syscfg_ok = syscfg_info is not None
    syscfg_version_ok = False
    if syscfg_ok and syscfg_info.get("version"):
        req = chip_info.get("sysconfig_version", "1.25.0")
        syscfg_version_ok = syscfg_info["version"] == req

    all_pass = all([
        keil_ok,
        dfp_info.get("installed", False),
        sdk_ok and sdk_version_ok,
        syscfg_ok and syscfg_version_ok,
    ])

    return {
        "all_pass": all_pass,
        "chip": "MSPM0G3519",
        "keil": {
            "installed": keil_ok,
            "path": keil_path,
        },
        "dfp": dfp_info,
        "sdk": {
            "installed": sdk_ok,
            "path": sdk_info.get("path") if sdk_info else None,
            "version": sdk_info.get("version") if sdk_info else None,
            "required_version": chip_info.get("sdk_version", "2.08.00.03"),
            "version_ok": sdk_version_ok,
        },
        "sysconfig": {
            "installed": syscfg_ok,
            "path": syscfg_info.get("path") if syscfg_info else None,
            "version": syscfg_info.get("version") if syscfg_info else None,
            "required_version": chip_info.get("sysconfig_version", "1.25.0"),
            "version_ok": syscfg_version_ok,
        },
    }


def print_check_report(status: Dict) -> None:
    """Print human-readable toolchain check report."""
    print("=" * 60)
    print("MSPM0G3519 工具链检查")
    print("=" * 60)

    for name, key, version_key in [
        ("Keil MDK-ARM", "keil", None),
        ("TI DFP", "dfp", None),
        ("MSPM0 SDK", "sdk", "sdk"),
        ("SysConfig", "sysconfig", "sysconfig"),
    ]:
        info = status[key]
        if key in ("keil",):
            ok = info.get("installed", False)
        elif key == "dfp":
            ok = info.get("installed", False)
        else:
            ok = info.get("version_ok", False) and info.get("installed", False)

        mark = "[OK]" if ok else "[X]"
        print(f"\n{mark} {name}")

        if key == "keil":
            if info.get("path"):
                print(f"  路径: {info['path']}")
            else:
                print("  未找到 uv4.exe")
                print("  请安装 Keil MDK-ARM v5")

        elif key == "dfp":
            if ok:
                print(f"  已安装: {info.get('name', '')}")
                print(f"  路径: {info.get('path', '')}")
            else:
                print(f"  未安装: {info.get('name', 'TexasInstruments.MSPM0GX51X_DFP.1.0.0')}")
                print("  请在 Keil 中打开 Pack Installer，搜索 MSPM0 并安装")

        else:
            if info.get("path"):
                print(f"  路径: {info['path']}")
            if info.get("version"):
                req = info.get("required_version", "")
                if req and info.get("version") != req:
                    print(f"  版本: {info['version']} (需要 {req}) [版本不匹配]")
                else:
                    print(f"  版本: {info['version']}")

    print("\n" + "=" * 60)
    if status["all_pass"]:
        print("所有工具链检查通过！")
    else:
        print("工具链不完整，请先安装缺失的组件后再继续。")
    print("=" * 60)


if __name__ == "__main__":
    status = check_toolchain()
    print_check_report(status)
    if not status["all_pass"]:
        sys.exit(1)

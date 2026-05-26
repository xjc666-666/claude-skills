"""
Run SysConfig .syscfg to generate ti_msp_dl_config.c/h.
"""
import os
import sys
import re
import json
from pathlib import Path
from typing import Dict, Optional

SCRIPT_DIR = str(Path(__file__).resolve().parent)
sys.path.insert(0, SCRIPT_DIR)
from utils import normalize_path, run_command
from sdk_detector import find_sdk


def generate_syscfg(project_dir: str, sdk_path: Optional[str] = None,
                    timeout: int = 120) -> Dict:
    """Run SysConfig to generate ti_msp_dl_config.c/h from config.syscfg."""

    if sdk_path is None:
        sdk_info = find_sdk()
        if sdk_info is None:
            return {"success": False, "error": "MSPM0 SDK not found"}
        sdk_path = sdk_info["path"]

    # Also find sysconfig CLI
    syscfg_dir = os.path.dirname(sdk_path)
    syscfg_cli = os.path.join(syscfg_dir, "sysconfig_1.25.0", "sysconfig_cli.bat")
    if not os.path.isfile(syscfg_cli):
        # Fallback: read from SDK's syscfg.bat
        syscfg_bat = os.path.join(sdk_path, "tools", "keil", "syscfg.bat")
        if not os.path.isfile(syscfg_bat):
            return {"success": False, "error": f"sysconfig_cli.bat not found at {syscfg_cli}"}
        # Parse the SYSCFG_PATH from syscfg.bat
        with open(syscfg_bat, "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(r'SYSCFG_PATH="([^"]+)"', content)
        if match:
            syscfg_cli = match.group(1)
        else:
            return {"success": False, "error": "Cannot determine SysConfig path from syscfg.bat"}

    if not os.path.isfile(syscfg_cli):
        return {"success": False, "error": f"SysConfig CLI not found: {syscfg_cli}"}

    product_json = os.path.join(sdk_path, ".metadata", "product.json")
    user_dir = os.path.join(project_dir, "User")
    config_file = os.path.join(user_dir, "config.syscfg")

    if not os.path.isfile(config_file):
        return {"success": False, "error": f"config.syscfg not found: {config_file}"}

    cmd = [
        syscfg_cli,
        "-o", user_dir,
        "-s", product_json,
        "--compiler", "keil",
        config_file,
    ]

    returncode, stdout, stderr = run_command(cmd, cwd=user_dir, timeout=timeout)

    # Check generated files
    gen_c = os.path.join(user_dir, "ti_msp_dl_config.c")
    gen_h = os.path.join(user_dir, "ti_msp_dl_config.h")
    gen_h_opt = os.path.join(user_dir, "ti_msp_dl_config.h.opt")

    c_exists = os.path.isfile(gen_c)
    h_exists = os.path.isfile(gen_h)

    if not c_exists or not h_exists:
        return {
            "success": False,
            "error": "SysConfig generation failed",
            "stdout": stdout[-2000:] if stdout else "",
            "stderr": stderr[-2000:] if stderr else "",
            "returncode": returncode,
            "generated_c": c_exists,
            "generated_h": h_exists,
        }

    # Verify generated content
    issues = []

    # Check SYSCFG_DL_init in generated .c
    try:
        with open(gen_c, "r", encoding="utf-8") as f:
            c_content = f.read()
        if "SYSCFG_DL_init" not in c_content:
            issues.append("SYSCFG_DL_init not found in generated .c")
    except Exception:
        issues.append("Failed to read generated .c")

    # Check CPUCLK_FREQ in generated .h
    try:
        with open(gen_h, "r", encoding="utf-8") as f:
            h_content = f.read()
        if "CPUCLK_FREQ" not in h_content:
            issues.append("CPUCLK_FREQ not found in generated .h")
    except Exception:
        issues.append("Failed to read generated .h")

    return {
        "success": len(issues) == 0,
        "generated_c": normalize_path(gen_c),
        "generated_h": normalize_path(gen_h),
        "stdout": stdout[-1000:] if stdout else "",
        "stderr": stderr[-1000:] if stderr else "",
        "issues": issues,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate MSPM0 SysConfig code")
    parser.add_argument("--project-dir", required=True, help="Project root directory")
    parser.add_argument("--sdk-path", default=None, help="SDK path (auto-detect if omitted)")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds")

    args = parser.parse_args()

    result = generate_syscfg(args.project_dir, args.sdk_path, args.timeout)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    if not result["success"]:
        sys.exit(1)

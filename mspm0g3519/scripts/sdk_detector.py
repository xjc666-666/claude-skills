"""
Auto-detect MSPM0 SDK and SysConfig installations.
"""
import os
import sys
import re
import json
import glob as glob_mod
from pathlib import Path
from typing import Optional, Dict, List

SCRIPT_DIR = str(Path(__file__).resolve().parent)
sys.path.insert(0, SCRIPT_DIR)
try:
    from utils import load_sdk_paths_config, normalize_path
except ImportError:
    from scripts.utils import load_sdk_paths_config, normalize_path


def find_sdk() -> Optional[Dict]:
    """Find MSPM0 SDK installation. Returns dict with path, version, etc."""
    config = load_sdk_paths_config()
    sdk_path = None

    # 1. Environment variables
    for env in config.get("sdk_env_vars", []):
        val = os.environ.get(env)
        if val and _validate_sdk(val):
            sdk_path = val
            break

    # 2. Known paths (exact and wildcard)
    if sdk_path is None:
        for p in config.get("known_sdk_paths", []):
            p = os.path.expandvars(p)
            if "*" in p:
                matches = sorted(glob_mod.glob(p), reverse=True)
                for m in matches:
                    if _validate_sdk(m):
                        sdk_path = m
                        break
            elif _validate_sdk(p):
                sdk_path = p
                break

    # 3. Search common drive roots
    if sdk_path is None:
        pattern = config.get("sdk_dir_pattern", "mspm0_sdk_*")
        for root in [r"D:\ti", r"C:\ti"]:
            search = os.path.join(root, pattern)
            matches = sorted(glob_mod.glob(search), reverse=True)
            for m in matches:
                if _validate_sdk(m):
                    sdk_path = m
                    break
            if sdk_path:
                break

    if sdk_path is None:
        return None

    version = _parse_sdk_version(sdk_path, config)
    return {
        "path": normalize_path(sdk_path),
        "version": version,
        "tools_keil": normalize_path(os.path.join(sdk_path, "tools", "keil")),
        "driverlib": normalize_path(os.path.join(sdk_path, "source", "ti", "driverlib")),
        "devices": normalize_path(os.path.join(sdk_path, "source", "ti", "devices")),
        "examples": normalize_path(os.path.join(sdk_path, "examples")),
        "syscfg_bat": normalize_path(os.path.join(sdk_path, "tools", "keil", "syscfg.bat")),
    }


def find_sysconfig() -> Optional[Dict]:
    """Find SysConfig tool installation."""
    config = load_sdk_paths_config()
    syscfg_path = None

    # 1. Environment variables
    for env in config.get("sysconfig_env_vars", []):
        val = os.environ.get(env)
        if val and _validate_sysconfig(val):
            syscfg_path = val
            break

    # 2. Known paths
    if syscfg_path is None:
        for p in config.get("known_sysconfig_paths", []):
            p = os.path.expandvars(p)
            if "*" in p:
                matches = sorted(glob_mod.glob(p), reverse=True)
                for m in matches:
                    if _validate_sysconfig(m):
                        syscfg_path = m
                        break
            elif _validate_sysconfig(p):
                syscfg_path = p
                break

    # 3. Search common drive roots
    if syscfg_path is None:
        pattern = config.get("sysconfig_dir_pattern", "sysconfig_*")
        for root in [r"D:\ti", r"C:\ti"]:
            search = os.path.join(root, pattern)
            matches = sorted(glob_mod.glob(search), reverse=True)
            for m in matches:
                if _validate_sysconfig(m):
                    syscfg_path = m
                    break
            if syscfg_path:
                break

    if syscfg_path is None:
        return None

    version = _parse_sysconfig_version(syscfg_path, config)
    return {
        "path": normalize_path(syscfg_path),
        "version": version,
        "cli": normalize_path(os.path.join(syscfg_path, "sysconfig_cli.bat")),
        "bat": normalize_path(os.path.join(syscfg_path, "sysconfig_gui.bat")),
    }


def find_dfp() -> Optional[Dict]:
    """Find TI MSPM0GX51X DFP in ARM Packs directory."""
    import winreg
    config = load_sdk_paths_config()
    pack_dirs = []

    # CMSIS_PACK_ROOT env
    cpr = os.environ.get("CMSIS_PACK_ROOT")
    if cpr:
        pack_dirs.append(cpr)

    # Expand known pack directories
    for d in config.get("arm_pack_dirs", []):
        d = os.path.expandvars(d)
        if os.path.isdir(d):
            pack_dirs.append(d)

    # Registry
    try:
        for root_key, path in [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Keil\Products\MDK"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Keil\Products\MDK"),
        ]:
            try:
                key = winreg.OpenKey(root_key, path)
                val, _ = winreg.QueryValueEx(key, "Path")
                winreg.CloseKey(key)
                if val:
                    pack_dirs.append(os.path.join(val, "ARM", "PACK"))
            except (FileNotFoundError, OSError):
                continue
    except Exception:
        pass

    dfp_name = "TexasInstruments.MSPM0GX51X_DFP.1.0.0"
    for pd in pack_dirs:
        for subpath in [
            os.path.join(pd, "TexasInstruments", "MSPM0GX51X_DFP", "1.0.0"),
            os.path.join(pd, "TexasInstruments", "MSPM0GX51X_DFP"),
        ]:
            if os.path.isdir(subpath):
                # Look for the actual version directory
                if os.path.basename(subpath) == "1.0.0":
                    return {"path": normalize_path(subpath), "name": dfp_name, "installed": True}
                else:
                    # Find the highest version
                    versions = sorted([d for d in os.listdir(subpath)
                                       if os.path.isdir(os.path.join(subpath, d))],
                                      reverse=True)
                    for v in versions:
                        p = os.path.join(subpath, v)
                        if os.path.isfile(os.path.join(p, "TexasInstruments.MSPM0GX51X_DFP.pdsc")):
                            return {"path": normalize_path(p),
                                    "name": f"TexasInstruments.MSPM0GX51X_DFP.{v}",
                                    "installed": True}

    return {"name": dfp_name, "installed": False, "path": None}


def find_all() -> Dict:
    """Find all required tools and return summary."""
    keil = None
    try:
        from utils import find_keil_installation
        keil = find_keil_installation()
    except ImportError:
        pass

    return {
        "keil": {"path": keil, "installed": keil is not None},
        "sdk": find_sdk(),
        "sysconfig": find_sysconfig(),
        "dfp": find_dfp(),
    }


def _validate_sdk(path: str) -> bool:
    """Check if a directory looks like a valid MSPM0 SDK."""
    if not os.path.isdir(path):
        return False
    checks = [
        os.path.join(path, "source", "ti", "driverlib", "driverlib.h"),
        os.path.join(path, "source", "ti", "devices", "msp", "msp.h"),
    ]
    return all(os.path.isfile(c) for c in checks)


def _validate_sysconfig(path: str) -> bool:
    """Check if a directory looks like a valid SysConfig installation."""
    if not os.path.isdir(path):
        return False
    checks = [
        os.path.join(path, "sysconfig_cli.bat"),
    ]
    return all(os.path.isfile(c) for c in checks)


def _parse_sdk_version(path: str, config: Dict) -> Optional[str]:
    """Extract SDK version from directory name."""
    name = os.path.basename(path.rstrip("/\\"))
    m = re.search(config.get("sdk_version_regex", r"mspm0_sdk_(\d+_\d+_\d+_\d+)"), name)
    if m:
        return m.group(1).replace("_", ".")
    return None


def _parse_sysconfig_version(path: str, config: Dict) -> Optional[str]:
    """Extract SysConfig version from directory name."""
    name = os.path.basename(path.rstrip("/\\"))
    m = re.search(config.get("sysconfig_version_regex", r"sysconfig_(\d+\.\d+\.\d+)"), name)
    if m:
        return m.group(1)
    return None


def validate_sdk_path(user_path: str) -> Dict:
    """Validate a user-provided SDK path. Returns same format as find_sdk()."""
    if not user_path or not _validate_sdk(user_path):
        return None
    config = load_sdk_paths_config()
    version = _parse_sdk_version(user_path, config)
    return {
        "path": normalize_path(user_path),
        "version": version,
        "tools_keil": normalize_path(os.path.join(user_path, "tools", "keil")),
        "driverlib": normalize_path(os.path.join(user_path, "source", "ti", "driverlib")),
        "devices": normalize_path(os.path.join(user_path, "source", "ti", "devices")),
        "examples": normalize_path(os.path.join(user_path, "examples")),
        "syscfg_bat": normalize_path(os.path.join(user_path, "tools", "keil", "syscfg.bat")),
    }


def validate_sysconfig_path(user_path: str) -> Dict:
    """Validate a user-provided SysConfig path. Returns same format as find_sysconfig()."""
    if not user_path or not _validate_sysconfig(user_path):
        return None
    config = load_sdk_paths_config()
    version = _parse_sysconfig_version(user_path, config)
    return {
        "path": normalize_path(user_path),
        "version": version,
        "cli": normalize_path(os.path.join(user_path, "sysconfig_cli.bat")),
        "bat": normalize_path(os.path.join(user_path, "sysconfig_gui.bat")),
    }


if __name__ == "__main__":
    import argparse, json as _json

    parser = argparse.ArgumentParser(description="Detect MSPM0 SDK and SysConfig")
    parser.add_argument("--validate-sdk", default=None, help="Validate user-provided SDK path")
    parser.add_argument("--validate-sysconfig", default=None, help="Validate user-provided SysConfig path")
    args = parser.parse_args()

    if args.validate_sdk:
        result = validate_sdk_path(args.validate_sdk)
        print(_json.dumps({"valid": result is not None, "info": result}, indent=2, ensure_ascii=False, default=str))
    elif args.validate_sysconfig:
        result = validate_sysconfig_path(args.validate_sysconfig)
        print(_json.dumps({"valid": result is not None, "info": result}, indent=2, ensure_ascii=False, default=str))
    else:
        result = find_all()
        print(_json.dumps(result, indent=2, ensure_ascii=False, default=str))

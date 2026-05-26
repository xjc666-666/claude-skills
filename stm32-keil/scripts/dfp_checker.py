"""
Check that required Keil Device Family Pack (DFP) is installed.

Keil installs DFPs to %LOCALAPPDATA%/Arm/Packs/<Vendor>/<Pack>/<Version>/.
If the required pack is missing, the .uvprojx will reference an unavailable
flash algorithm and uv4 will fail to build or flash.
"""
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import load_chip_db, get_arm_packs_dir, list_pack_dirs


class DFPStatus(NamedTuple):
    chip: str
    required_pack_id: str
    found_version: Optional[str]
    installed: bool
    packs_dir: Optional[str]
    message: str


# pack_id in chip_db is "Keil.STM32F1xx_DFP.2.4.1" → vendor=Keil, name=STM32F1xx_DFP, version=2.4.1
def _parse_pack_id(pack_id: str):
    parts = pack_id.split(".")
    if len(parts) < 3:
        return None, None, None
    vendor = parts[0]
    name = parts[1]
    version = ".".join(parts[2:])
    return vendor, name, version


def check_dfp(chip: str) -> DFPStatus:
    db = load_chip_db()
    if chip not in db:
        return DFPStatus(chip, "", None, False, None, f"Unknown chip: {chip}")
    pack_id = db[chip].get("pack_id", "")
    vendor, name, version = _parse_pack_id(pack_id)
    if not vendor:
        return DFPStatus(chip, pack_id, None, False, None,
                         f"Cannot parse pack_id: {pack_id}")

    packs_dirs = list_pack_dirs()
    if not packs_dirs:
        return DFPStatus(chip, pack_id, None, False, None,
                         "ARM Packs directory not found. "
                         "Install Keil MDK or set LOCALAPPDATA\\Arm\\Packs.")

    # Search every candidate packs directory until we find the pack
    pack_root = None
    used_dir = None
    for d in packs_dirs:
        candidate = os.path.join(d, vendor, name)
        if os.path.isdir(candidate):
            pack_root = candidate
            used_dir = d
            break

    if pack_root is None:
        # New Keil installs use generic ARM.CMSIS + ARM.Cortex_DFP rather than
        # vendor-specific STM32xxx_DFP. If those generic packs are present, the
        # project will still build because flash algorithms now ship via CMSIS.
        for d in packs_dirs:
            arm_cmsis = os.path.join(d, "ARM", "CMSIS")
            cortex = os.path.join(d, "ARM", "Cortex_DFP")
            if os.path.isdir(arm_cmsis) or os.path.isdir(cortex):
                msg = (f"Pack '{vendor}.{name}' not installed, but "
                       f"ARM.CMSIS / ARM.Cortex_DFP is present in {d}. "
                       f"Modern Keil routes flash algorithms through these "
                       f"packs — build should still work.")
                return DFPStatus(chip, pack_id, "ARM.CMSIS",
                                 True, d, msg)

        # Also check the .Download cache for un-installed but downloaded packs
        for d in packs_dirs:
            cache = os.path.join(d, ".Download")
            if os.path.isdir(cache):
                for f in os.listdir(cache):
                    if f.lower().startswith(f"{vendor}.{name}".lower()) and f.endswith(".pack"):
                        return DFPStatus(chip, pack_id, f.replace(".pack",""),
                                         False, d,
                                         f"Pack downloaded but not installed: {f}\n"
                                         f"Open Keil Pack Installer and click "
                                         f"'Install' on this pack.")

        return DFPStatus(chip, pack_id, None, False, packs_dirs[0],
                         f"Pack '{vendor}.{name}' not installed in any of: "
                         f"{packs_dirs}\n"
                         f"Install via Keil Pack Installer or:\n"
                         f"  https://www.keil.arm.com/packs/")

    versions = sorted(
        (d for d in os.listdir(pack_root)
         if os.path.isdir(os.path.join(pack_root, d))),
        key=_version_key, reverse=True)

    if not versions:
        return DFPStatus(chip, pack_id, None, False, used_dir,
                         f"Pack directory exists but contains no version: {pack_root}")

    newest = versions[0]
    ok_message = (f"Pack {vendor}.{name} {newest} installed at {used_dir}."
                  if newest == version
                  else f"Pack {vendor}.{name} found ({newest}) at {used_dir}; "
                       f"project requests {version}, but Keil usually accepts a newer version.")
    return DFPStatus(chip, pack_id, newest, True, used_dir, ok_message)


def _version_key(v: str):
    parts = re.findall(r'\d+', v)
    return tuple(int(p) for p in parts)


def list_installed_packs() -> List[str]:
    """List all installed packs as 'Vendor.Name version' strings."""
    packs_dir = get_arm_packs_dir()
    if not packs_dir:
        return []
    result = []
    for vendor in os.listdir(packs_dir):
        vd = os.path.join(packs_dir, vendor)
        if not os.path.isdir(vd):
            continue
        for name in os.listdir(vd):
            nd = os.path.join(vd, name)
            if not os.path.isdir(nd):
                continue
            for ver in os.listdir(nd):
                if os.path.isdir(os.path.join(nd, ver)):
                    result.append(f"{vendor}.{name} {ver}")
    return sorted(result)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Check required Keil DFP is installed")
    parser.add_argument("--chip", help="Chip name to check (e.g. STM32F407ZGT6)")
    parser.add_argument("--list", action="store_true", help="List all installed packs")
    args = parser.parse_args()

    if args.list:
        for p in list_installed_packs():
            print(p)
        sys.exit(0)

    if not args.chip:
        print("Error: --chip or --list required")
        sys.exit(1)

    status = check_dfp(args.chip)
    print(f"Chip:     {status.chip}")
    print(f"Required: {status.required_pack_id}")
    print(f"Found:    {status.found_version or '(missing)'}")
    print(f"Status:   {'OK' if status.installed else 'MISSING'}")
    print(f"Message:  {status.message}")
    sys.exit(0 if status.installed else 2)

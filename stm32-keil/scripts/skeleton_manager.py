"""
Extract and maintain minimal project skeletons from full templates.
"""
import os
import sys
import shutil
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Set, Optional


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import ensure_dir, load_chip_db


# Files to ALWAYS keep in any skeleton
CORE_DRIVE_FILES = [
    "Drive/Source/delay.c",
    "Drive/Source/GPIO.c",
    "Drive/Source/USART.c",
    "Drive/Source/led.c",
    "Drive/Include/delay.h",
    "Drive/Include/GPIO.h",
    "Drive/Include/USART.h",
    "Drive/Include/led.h",
]

CORE_USER_FILES = [
    "User/main.c",
]

# SPL source files always needed as base
CORE_SPL_SOURCES = [
    "misc.c",
    "stm32f4xx_rcc.c",
    "stm32f4xx_gpio.c",
    "stm32f4xx_usart.c",
]

CORE_SPL_SOURCES_F103 = [
    "misc.c",
    "stm32f10x_rcc.c",
    "stm32f10x_gpio.c",
    "stm32f10x_usart.c",
]

# Files/patterns to EXCLUDE from skeleton
EXCLUDE_PATTERNS = [
    "*.o",
    "*.d",
    "*.crf",
    "*.axf",
    "*.hex",
    "*.bin",
    "*.iex",
    "*.bak",
    "*.dep",
    "*.uvguix.*",
    "JLinkSettings.ini",
    "JLinkLog.txt",
    "JLinkSettings",
]

EXCLUDE_DIRS = [
    "Objects",
    "Listings",
    "RTE",
    ".vscode",
    "DebugConfig",
    "__pycache__",
]

EXCLUDE_TOP_DIRS = [
    "DSP",
]


def extract_skeleton(
    source_dir: str,
    output_dir: str,
    family: str = "F407",
    keep_all_spl_headers: bool = True,
    keep_all_cmsis: bool = True,
    extra_keep_patterns: Optional[List[str]] = None,
) -> int:
    """
    Extract a minimal skeleton from a full template project.

    Args:
        source_dir: Path to the full template project
        output_dir: Path where skeleton will be created
        family: "F103" or "F407"
        keep_all_spl_headers: If True, keep all SPL .h files (recommended)
        keep_all_cmsis: If True, keep all CMSIS headers
        extra_keep_patterns: Additional glob patterns to keep

    Returns:
        Number of files copied
    """
    source_dir = os.path.abspath(source_dir)
    output_dir = os.path.abspath(output_dir)

    if not os.path.isdir(source_dir):
        print(f"Error: Source directory not found: {source_dir}")
        return 0

    # Clean output directory
    if os.path.isdir(output_dir):
        shutil.rmtree(output_dir)
    ensure_dir(output_dir)

    # Build list of files to keep
    keep_files = _build_keep_list(source_dir, family, keep_all_spl_headers,
                                   keep_all_cmsis, extra_keep_patterns)

    # Copy files
    copied = 0
    for rel_path in sorted(keep_files):
        src = os.path.join(source_dir, rel_path)
        dst = os.path.join(output_dir, rel_path)

        if not os.path.isfile(src):
            continue

        ensure_dir(os.path.dirname(dst))
        shutil.copy2(src, dst)
        copied += 1

    print(f"Skeleton extracted: {copied} files from {source_dir} -> {output_dir}")

    # Clean up .uvprojx — remove references to files excluded from skeleton
    for fname in os.listdir(os.path.join(output_dir, "Project")):
        if fname.endswith(".uvprojx"):
            count = _cleanup_uvprojx(os.path.join(output_dir, "Project", fname), output_dir)
            print(f"Cleaned {count} missing file references from {fname}")

    return copied


def _build_keep_list(
    source_dir: str,
    family: str,
    keep_all_spl_headers: bool,
    keep_all_cmsis: bool,
    extra_patterns: Optional[List[str]],
) -> Set[str]:
    """Build the set of relative file paths to keep in the skeleton."""
    import glob as glob_mod

    keep = set()

    # Always keep project files
    for f in glob_mod.glob(os.path.join(source_dir, "Project", "*.uvprojx")):
        keep.add(os.path.relpath(f, source_dir))
    for f in glob_mod.glob(os.path.join(source_dir, "Project", "*.uvoptx")):
        keep.add(os.path.relpath(f, source_dir))

    # Keep DebugConfig
    for f in glob_mod.glob(os.path.join(source_dir, "Project", "DebugConfig", "*")):
        rel = os.path.relpath(f, source_dir)
        keep.add(rel)

    # Keep OUT.ini if it exists
    out_ini = os.path.join(source_dir, "Project", "out.ini")
    if os.path.isfile(out_ini):
        keep.add("Project/out.ini")

    # Keep core User files
    for f in CORE_USER_FILES:
        full = os.path.join(source_dir, f)
        if os.path.isfile(full):
            keep.add(f)
    # Also keep it.h, it.c, conf.h from User
    for name in os.listdir(os.path.join(source_dir, "User")):
        full = os.path.join(source_dir, "User", name)
        if os.path.isfile(full) and not name.startswith("."):
            keep.add(os.path.relpath(full, source_dir))

    # Keep core Drive files
    for f in CORE_DRIVE_FILES:
        full = os.path.join(source_dir, f)
        if os.path.isfile(full):
            keep.add(f)

    # Keep all CMSIS core headers
    if keep_all_cmsis:
        cmsis_include = os.path.join(source_dir, "STM32", "CMSIS", "Include")
        if os.path.isdir(cmsis_include):
            for root, _, files in os.walk(cmsis_include):
                for fname in files:
                    full = os.path.join(root, fname)
                    keep.add(os.path.relpath(full, source_dir))

        # CMSIS device headers
        cmsis_device = os.path.join(source_dir, "STM32", "CMSIS", "Device")
        if os.path.isdir(cmsis_device):
            for root, _, files in os.walk(cmsis_device):
                for fname in files:
                    full = os.path.join(root, fname)
                    keep.add(os.path.relpath(full, source_dir))

    # Keep SPL headers
    if keep_all_spl_headers:
        sp = "STM32F10x" if family == "F103" else "STM32F4xx"
        spl_inc = os.path.join(source_dir, "STM32", f"{sp}_StdPeriph_Driver", "inc")
        if os.path.isdir(spl_inc):
            for f in os.listdir(spl_inc):
                full = os.path.join(spl_inc, f)
                if os.path.isfile(full):
                    keep.add(os.path.relpath(full, source_dir))

    # Keep core SPL sources
    sp = "STM32F10x" if family == "F103" else "STM32F4xx"
    spl_src = os.path.join(source_dir, "STM32", f"{sp}_StdPeriph_Driver", "src")
    core_spl = CORE_SPL_SOURCES_F103 if family == "F103" else CORE_SPL_SOURCES
    if os.path.isdir(spl_src):
        for f in core_spl:
            full = os.path.join(spl_src, f)
            if os.path.isfile(full):
                keep.add(os.path.relpath(full, source_dir))

    # Extra patterns
    if extra_patterns:
        for pat in extra_patterns:
            for f in glob_mod.glob(os.path.join(source_dir, pat)):
                if os.path.isfile(f):
                    keep.add(os.path.relpath(f, source_dir))

    # Filter out exclusions
    result = set()
    for rel in keep:
        skip = False
        for exc_dir in EXCLUDE_DIRS:
            if exc_dir in Path(rel).parts:
                skip = True
                break
        for exc_dir in EXCLUDE_TOP_DIRS:
            if rel.startswith(exc_dir + os.sep) or rel == exc_dir:
                skip = True
                break
        if not skip:
            basename = os.path.basename(rel)
            for exc_pat in EXCLUDE_PATTERNS:
                if Path(basename).match(exc_pat):
                    skip = True
                    break
        if not skip:
            result.add(rel)

    return result


def list_skeletons(skill_dir: Optional[str] = None) -> List[str]:
    """List available skeletons."""
    if skill_dir is None:
        skill_dir = str(Path(__file__).resolve().parent.parent)
    skeleton_dir = os.path.join(skill_dir, "skeleton")
    if not os.path.isdir(skeleton_dir):
        return []
    return [d for d in os.listdir(skeleton_dir)
            if os.path.isdir(os.path.join(skeleton_dir, d))]


def create_minimal_main_c(output_path: str, family: str = "F407") -> None:
    """Create a minimal main.c for a new project."""
    if family == "F103":
        header = "stm32f10x.h"
    else:
        header = "stm32f4xx.h"

    content = f'''/**
*****************************************************************************
*
*  @file    main.c
*  @brief   主程序
*
*  @author  stm32-keil skill
*  @date    2025/5/22
*  @version 1.0
*
*****************************************************************************
**/

#include "{header}"
#include <stdio.h>
#include "delay.h"
#include "GPIO.h"
#include "USART.h"
#include "led.h"

int main(void)
{{
    Delay_Init();
    USART1_Init(115200);
    LED_Init();

    printf("System initialized.\\\\r\\\\n");

    while (1)
    {{
        LED1_Toggle;
        Delay_ms(500);
    }}
}}
'''
    ensure_dir(os.path.dirname(output_path))
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)


def get_skeleton_path(family: str, skill_dir: Optional[str] = None,
                      library: str = "SPL") -> str:
    """Return the path to the minimal project template for this family/library.

    Templates:
      F103 / SPL  → skeleton/f103
      F407 / SPL  → skeleton/f407
      F103 / HAL  → skeleton/hal_f103
      F407 / HAL  → skeleton/hal_f407

    Other vendor folders (skeleton/stm32f407, skeleton/stm32c8t6, ...) are
    peripheral examples consumed by example_searcher.py, not templates.
    """
    if skill_dir is None:
        skill_dir = str(Path(__file__).resolve().parent.parent)
    family_key = "f103" if family == "F103" else "f407"
    if library.upper() == "HAL":
        family_key = f"hal_{family_key}"
    return os.path.join(skill_dir, "skeleton", family_key)


def _cleanup_uvprojx(uvprojx_path: str, skeleton_dir: str) -> int:
    """Remove references to files that don't exist in the skeleton."""
    tree = ET.parse(uvprojx_path)
    root = tree.getroot()
    target = root.find(".//Target")
    if target is None:
        return 0

    groups = target.find("Groups")
    if groups is None:
        return 0

    removed = 0
    groups_to_remove = []
    proj_dir = os.path.dirname(uvprojx_path)

    for group in groups.findall("Group"):
        files_elem = group.find("Files")
        if files_elem is None:
            continue

        files_to_remove = []
        for f in files_elem.findall("File"):
            fp = f.findtext("FilePath", "")
            abs_path = os.path.normpath(os.path.join(proj_dir, fp))
            if not os.path.exists(abs_path):
                files_to_remove.append(f)

        for f in files_to_remove:
            files_elem.remove(f)
            removed += 1

        # Remove empty groups
        if len(files_elem.findall("File")) == 0:
            groups_to_remove.append(group)

    for g in groups_to_remove:
        groups.remove(g)
        removed += 1

    tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
    return removed


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract and manage project skeletons")
    sub = parser.add_subparsers(dest="command")

    extract_p = sub.add_parser("extract", help="Extract skeleton from template")
    extract_p.add_argument("--source", required=True, help="Path to full template")
    extract_p.add_argument("--output", required=True, help="Output skeleton directory")
    extract_p.add_argument("--family", default="F407", choices=["F103", "F407"])

    sub.add_parser("list", help="List available skeletons")

    args = parser.parse_args()

    if args.command == "extract":
        extract_skeleton(args.source, args.output, args.family)
    elif args.command == "list":
        skeletons = list_skeletons()
        if skeletons:
            print("Available skeletons:")
            for s in skeletons:
                print(f"  - {s}")
        else:
            print("No skeletons found.")
    else:
        parser.print_help()

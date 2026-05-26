"""
Create a new Keil project from skeleton template.
"""
import os
import sys
import re
import shutil
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import ensure_dir, load_chip_db, get_chip_family, normalize_path
from uvprojx_modifier import modify_device, rename_project, read_current_config
from skeleton_manager import get_skeleton_path, list_skeletons
from template_fetcher import fetch_template


def create_project(
    chip: str,
    name: str,
    path: str,
    library: str = "SPL",
    chip_db_path: Optional[str] = None,
    skill_dir: Optional[str] = None,
) -> Dict:
    """
    Create a new Keil project from skeleton.

    Args:
        chip: Chip model (e.g., STM32F407ZGT6)
        name: Project name
        path: Target directory for the project
        library: "SPL" or "HAL"
        chip_db_path: Path to chip_db.json (auto-detected if None)
        skill_dir: Path to skill directory (auto-detected if None)
    """
    if skill_dir is None:
        skill_dir = str(Path(__file__).resolve().parent.parent)

    # Validate chip
    db = load_chip_db(chip_db_path)
    if chip not in db:
        return {
            "success": False,
            "error": f"Unknown chip: {chip}. Available: {', '.join(db.keys())}"
        }

    chip_info = dict(db[chip])
    chip_info["library"] = library
    family = chip_info["family"]
    # Find skeleton (vendor template preferred; falls back to download)
    skeleton_path = get_skeleton_path(family, skill_dir, library)
    if not os.path.isdir(skeleton_path):
        print(f"No skeleton found for {family}/{library}, downloading from ST GitHub...")
        result = fetch_template(family, skill_dir, library)
        if not result["success"]:
            return {
                "success": False,
                "error": f"Failed to download template for {family} ({library}): {result['error']}"
            }
        skeleton_path = get_skeleton_path(family, skill_dir, library)


    # Check if project directory is empty
    project_dir = os.path.join(path, name)
    if os.path.isdir(project_dir) and os.listdir(project_dir):
        return {
            "success": False,
            "error": f"Directory {project_dir} is not empty. Please choose a different name or path."
        }

    # Copy skeleton
    ensure_dir(project_dir)
    _copy_skeleton(skeleton_path, project_dir)

    # Fix any absolute paths in .uvprojx / .uvoptx carried over from skeleton
    _fix_absolute_paths(project_dir)

    # Find the .uvprojx — could be under Project/ (our generated layout) or
    # under USER/ (vendor 正点原子 layout) or somewhere else.
    uvprojx_files = list(Path(project_dir).rglob("*.uvprojx"))
    if not uvprojx_files:
        return {"success": False, "error": "No .uvprojx found in skeleton"}

    old_uvprojx = str(uvprojx_files[0])
    proj_subdir = os.path.dirname(old_uvprojx)

    # Rename .uvprojx / .uvoptx in-place (next to where the original was)
    new_uvprojx = _rename_in_dir(proj_subdir, name)

    # Update device settings & target name
    if new_uvprojx and os.path.isfile(new_uvprojx):
        modify_device(new_uvprojx, chip, chip_db_path)
        rename_project(new_uvprojx, name)

        # Sync .uvoptx target name so ST-Link / debug settings remain bound
        uvoptx_path = os.path.splitext(new_uvprojx)[0] + ".uvoptx"
        if os.path.isfile(uvoptx_path):
            _update_uvoptx_targetname(uvoptx_path, name)

    # Generate README.md (with chip details, no hardcoded pins)
    readme_path = os.path.join(project_dir, "README.md")
    _generate_readme(readme_path, name, chip, chip_info)

    final_uvprojx = new_uvprojx if (new_uvprojx and os.path.isfile(new_uvprojx)) else old_uvprojx

    return {
        "success": True,
        "project_path": normalize_path(project_dir),
        "uvprojx_path": normalize_path(final_uvprojx),
        "chip": chip,
        "family": family,
        "library": library,
        "error": None,
    }


def _copy_skeleton(src: str, dst: str) -> None:
    """Copy skeleton directory to project directory."""
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)


def _fix_absolute_paths(project_dir: str) -> None:
    """Convert any absolute Windows paths in .uvprojx and .uvoptx to relative
    paths.  Skeletons sometimes carry over absolute paths from the machine
    they were created on (e.g. D:\\workspace_for_claude\\...\\User\\main.c).
    Without this fix the project opens with broken file references on any
    other machine."""
    # Search in both Project/ subdir (old layout) and root (new layout)
    search_dirs = [os.path.join(project_dir, "Project"), project_dir]
    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        for fname in os.listdir(search_dir):
            if not (fname.endswith(".uvprojx") or fname.endswith(".uvoptx")):
                continue
            full = os.path.join(search_dir, fname)
            _fix_paths_in_xml(full)


def _fix_paths_in_xml(xml_path: str) -> None:
    """Fix absolute paths in a single .uvprojx or .uvoptx file."""
    try:
        tree = ET.parse(xml_path)
    except Exception:
        return
    root = tree.getroot()
    changed = False
    for tag in ("FilePath", "PathWithFileName", "Filename"):
        for elem in root.iter(tag):
            if elem.text and _is_abs_windows_path(elem.text):
                rel = _abs_to_rel_path(elem.text)
                if rel:
                    elem.text = rel
                    changed = True
    if changed:
        tree.write(xml_path, encoding="UTF-8", xml_declaration=True)


def _is_abs_windows_path(p: str) -> bool:
    """Match patterns like C:\\... or D:/..."""
    return bool(re.match(r"^[A-Za-z]:[\\/]", p))


def _abs_to_rel_path(abs_path: str) -> Optional[str]:
    """Convert an absolute path to a relative path from the project's
    .uvprojx directory.

    Looks for known top-level project subdirectories and rewrites the path
    relative to the directory holding the .uvprojx (which can be either
    User/ or Project/). Returns None if the path cannot be converted.
    """
    p = abs_path.replace("/", "\\")
    # Vendor (正点原子): USER/CORE/FWLIB/SYSTEM/HARDWARE/STM32F10x_FWLib/OBJ
    # Generated layout: User/Drive/STM32/Project
    top_dirs = [
        "USER", "User",
        "CORE", "Core",
        "FWLIB", "STM32F10x_FWLib",
        "SYSTEM", "System",
        "HARDWARE", "Hardware",
        "OBJ", "Obj",
        "Drive", "STM32", "Project",
    ]
    for top_dir in top_dirs:
        marker = f"\\{top_dir}\\"
        idx = p.lower().find(marker.lower())
        if idx >= 0:
            rest = p[idx + len(marker):]
            return f"..\\{top_dir}\\{rest}"
    return None


def _rename_in_dir(proj_subdir: str, new_name: str) -> str:
    """Rename any .uvprojx/.uvoptx in `proj_subdir` to {new_name}.uvprojx/.uvoptx.
    Returns the path of the renamed .uvprojx (empty string on failure)."""
    new_uvprojx = ""
    if not os.path.isdir(proj_subdir):
        return ""
    for fname in os.listdir(proj_subdir):
        full = os.path.join(proj_subdir, fname)
        if not os.path.isfile(full):
            continue
        if fname.endswith(".uvprojx"):
            dest = os.path.join(proj_subdir, f"{new_name}.uvprojx")
            if full != dest:
                os.replace(full, dest)
            new_uvprojx = dest
        elif fname.endswith(".uvoptx"):
            dest = os.path.join(proj_subdir, f"{new_name}.uvoptx")
            if full != dest:
                os.replace(full, dest)
        elif fname.endswith(".uvguix") or ".uvguix." in fname:
            # Keil-generated per-user GUI state; safe to delete to avoid
            # confusion from old usernames.
            try:
                os.remove(full)
            except OSError:
                pass
    return new_uvprojx


def _rename_project_files(project_dir: str, new_name: str) -> None:
    """Legacy entry point — searches both Project/ and USER/ subdirs."""
    for sub in ("Project", "USER"):
        d = os.path.join(project_dir, sub)
        if os.path.isdir(d):
            _rename_in_dir(d, new_name)


def _update_uvoptx_targetname(uvoptx_path: str, name: str) -> None:
    """Update TargetName in .uvoptx to match project name, ensuring
    debugger settings (ST-Link) are properly associated with the target."""
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(uvoptx_path)
        root = tree.getroot()
        target = root.find(".//Target")
        if target is not None:
            tn = target.find("TargetName")
            if tn is not None:
                tn.text = name
                tree.write(uvoptx_path, encoding="UTF-8", xml_declaration=True)
    except Exception:
        pass  # Non-critical; Keil will auto-fix on first open


def _generate_readme(readme_path: str, name: str, chip: str, chip_info: Dict) -> None:
    flash_kb = int(chip_info["flash_size"], 16) // 1024
    ram_kb = int(chip_info["ram_size"], 16) // 1024
    family = chip_info["family"]
    core = chip_info["core"]
    fpu = "有" if chip_info.get("has_fpu", False) else "无"
    library = chip_info.get("library", "SPL")
    proj_dir = os.path.dirname(readme_path)

    # Detect structure: old (Project/ subdir) vs new (uvprojx at root)
    has_project_subdir = os.path.isdir(os.path.join(proj_dir, "Project"))
    uvprojx_rel = f"Project/{name}.uvprojx" if has_project_subdir else f"{name}.uvprojx"

    if has_project_subdir:
        tree_block = f"""{name}/
├── Project/     # Keil 工程文件 ({name}.uvprojx)
├── User/        # 用户代码 (main.c, 中断, 配置头)
├── Drive/       # 用户外设驱动层 (.c/.h)
└── STM32/       # CMSIS + {library} 库"""
    else:
        tree_block = f"""{name}/
├── {name}.uvprojx   # Keil 工程文件
├── Hardware/    # 外设驱动 (.c/.h)
├── Library/     # {library} 库
├── Start/       # 启动文件 + CMSIS
├── System/      # 系统层 (Delay, USART)
└── User/        # 用户代码 (main.c, 中断, 配置头)"""

    content = f"""# {name}

## 芯片信息
- **型号**: {chip}
- **系列**: {family}
- **内核**: {core}
- **Flash**: {flash_kb}KB
- **RAM**: {ram_kb}KB
- **FPU**: {fpu}
- **库**: {library}

## 引脚分配
> 由 stm32-keil skill 在确认引脚后填入。

| 外设 | 引脚 | 端口 | 说明 |
|------|------|------|------|
| _待填_ | | | |

## 工程结构
```
{tree_block}
```

## 编译与烧录

### 编译
在 Keil MDK-ARM v5 中打开 `{uvprojx_rel}`，按 **F7** 编译；
或在命令行：
```
uv4.exe -j0 -b {uvprojx_rel}
```

### 烧录
通过 ST-Link / J-Link / DFU 烧录。在 Keil 中按 **F8**，或：
```
python scripts/flasher.py --project {uvprojx_rel}
```

## 自动生成
此工程由 **stm32-keil skill** 自动生成。
"""
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create a new STM32 Keil project")
    parser.add_argument("--chip", required=True, help="Chip model (e.g., STM32F407ZGT6)")
    parser.add_argument("--name", required=True, help="Project name")
    parser.add_argument("--path", required=True, help="Parent directory for the project")
    parser.add_argument("--library", default="SPL", choices=["SPL", "HAL"],
                        help="Peripheral library: SPL (legacy) or HAL (recommended for F4)")
    parser.add_argument("--smoke-build", action="store_true",
                        help="After creation, run an incremental compile to verify integrity")

    args = parser.parse_args()

    result = create_project(args.chip, args.name, args.path, library=args.library)
    if result["success"]:
        print(f"Project created: {result['project_path']}")
        print(f"Keil project: {result['uvprojx_path']}")
        print(f"Chip: {result['chip']} ({result['family']}/{result.get('library','SPL')})")
        if args.smoke_build:
            try:
                from keil_builder import compile_project, get_build_summary
                print("\nRunning smoke build...")
                br = compile_project(result["uvprojx_path"], rebuild=False, timeout=180)
                print(get_build_summary(br))
                if not br.success:
                    print("\nSmoke build failed — skeleton may be incomplete.")
                    sys.exit(2)
            except Exception as e:
                print(f"Smoke build skipped: {e}")
    else:
        print(f"Error: {result['error']}")
        sys.exit(1)

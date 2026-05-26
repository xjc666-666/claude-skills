"""
Create a new MSPM0G3519 Keil project from skeleton template.

The skeleton/empty/ is a complete working project with full DriverLib and BSP
drivers (OLED, delay) already included.  Creating a new project is just:
copy skeleton -> rename files -> fix paths -> smoke build.

Uses TEXT replacement only to preserve Keil's exact uvprojx format.
"""
import os
import sys
import re
import shutil
from pathlib import Path
from typing import Optional, Dict

SCRIPT_DIR = str(Path(__file__).resolve().parent)
SKILL_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)

from utils import ensure_dir, normalize_path, load_chip_db, load_hardware_pin_map
from sdk_detector import find_sdk


def create_project(
    name: str,
    path: str,
    sdk_path: Optional[str] = None,
    smoke_build: bool = True,
) -> Dict:
    """Create a new MSPM0G3519 Keil project from the empty skeleton."""

    # Validate
    chip_db = load_chip_db()
    chip = "MSPM0G3519"
    if chip not in chip_db:
        return {"success": False, "error": f"Unknown chip: {chip}"}
    chip_info = chip_db[chip]

    if sdk_path is None:
        sdk_info = find_sdk()
        if sdk_info is None:
            return {"success": False, "error": "MSPM0 SDK not found"}
        sdk_path = sdk_info["path"]

    skeleton_path = os.path.join(SKILL_DIR, "skeleton", "empty")
    if not os.path.isdir(skeleton_path):
        return {"success": False, "error": f"Skeleton not found: {skeleton_path}"}

    project_dir = os.path.join(path, name)
    if os.path.isdir(project_dir) and os.listdir(project_dir):
        return {"success": False, "error": f"目录 {project_dir} 非空"}

    # ---- Step 1: Copy skeleton (includes full DriverLib + BSP drivers) ----
    print("Copying skeleton...")
    ensure_dir(project_dir)
    _copy_skeleton(skeleton_path, project_dir)

    # ---- Step 2: Rename project files ----
    proj_subdir = os.path.join(project_dir, "Project")
    new_uvprojx = _rename_project_files(proj_subdir, name)
    if not new_uvprojx:
        return {"success": False, "error": "Failed to rename project files"}

    # ---- Step 3: Apply text replacements to .uvprojx ----
    print("Fixing project settings...")
    _fix_uvprojx_text(new_uvprojx, name, sdk_path)

    # ---- Step 4: Fix absolute paths ----
    _fix_absolute_paths_in_uvprojx(new_uvprojx)

    # ---- Step 5: Generate README ----
    _generate_readme(os.path.join(project_dir, "README.md"), name, chip, chip_info)

    # ---- Step 6: Smoke build ----
    smoke_result = None
    if smoke_build:
        print("\nRunning smoke build...")
        try:
            from keil_builder import compile_project, get_build_summary
            br = compile_project(new_uvprojx, rebuild=False, timeout=180)
            smoke_result = {"success": br.success, "errors": len(br.errors),
                          "warnings": len(br.warnings), "size_info": br.size_info}
            print(get_build_summary(br))
        except Exception as e:
            smoke_result = {"success": False, "error": str(e)}
            print(f"Smoke build skipped: {e}")

    print(f"\n[IMPORTANT] 首次烧录前请在 Keil 中配置 CMSIS-DAP Debugger (Flash -> Configure Flash Tools -> Debug)")

    return {
        "success": True,
        "project_path": normalize_path(project_dir),
        "uvprojx_path": normalize_path(new_uvprojx),
        "chip": chip,
        "sdk_path": normalize_path(sdk_path),
        "smoke_build": smoke_result,
    }


def _copy_skeleton(src: str, dst: str) -> None:
    """Copy skeleton, excluding Output/, __pycache__, .uvguix files."""
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if item in ("Output", "__pycache__", ".git"):
            continue
        if os.path.isdir(s):
            shutil.copytree(s, d)
        elif not any(k in item.lower() for k in ('uvguix',)):
            shutil.copy2(s, d)


def _rename_project_files(proj_subdir: str, new_name: str) -> Optional[str]:
    """Rename empty.uvprojx/uvoptx to project name. Remove .uvguix files."""
    new_uvprojx = None
    if not os.path.isdir(proj_subdir):
        return None
    for fname in os.listdir(proj_subdir):
        full = os.path.join(proj_subdir, fname)
        if not os.path.isfile(full):
            continue
        lower = fname.lower()
        if 'uvguix' in lower:
            os.remove(full)
        elif fname.endswith('.uvprojx'):
            dest = os.path.join(proj_subdir, f"{new_name}.uvprojx")
            os.replace(full, dest)
            new_uvprojx = dest
        elif fname.endswith('.uvoptx'):
            dest = os.path.join(proj_subdir, f"{new_name}.uvoptx")
            os.replace(full, dest)
    return new_uvprojx


def _fix_uvprojx_text(uvprojx_path: str, project_name: str, sdk_path: str) -> None:
    """Apply text replacements to .uvprojx. No XML parsing, no Groups modification."""
    with open(uvprojx_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # 1. DriverSelection: ULINK(4096) -> CMSIS-DAP(3)
    text = text.replace('<DriverSelection>4096</DriverSelection>',
                        '<DriverSelection>3</DriverSelection>')

    # 2. TargetName -> project name
    text = re.sub(r'<TargetName>[^<]*</TargetName>',
                  f'<TargetName>{project_name}</TargetName>', text)

    # 3. OutputName -> project name
    text = re.sub(r'<OutputName>[^<]*</OutputName>',
                  f'<OutputName>{project_name}</OutputName>', text)

    # 4. syscfg.bat path -> use detected SDK path
    syscfg_bat = sdk_path.replace('\\', '\\\\') + '\\\\tools\\\\keil\\\\syscfg.bat'
    sdk_examples = sdk_path.replace('\\', '\\\\') + '\\\\examples'
    new_cmd = f'cmd.exe /C \\"{syscfg_bat} {sdk_examples} ../User/config.syscfg\\"'
    text = re.sub(
        r'<UserProg1Name>cmd\.exe /C "[^"]*syscfg\.bat[^"]*"</UserProg1Name>',
        f'<UserProg1Name>{new_cmd}</UserProg1Name>',
        text
    )

    # 5. Set RunToMain for reset-and-run
    if '<RunToMain>' not in text:
        text = text.replace('<UpdateFlashBeforeDebugging>1</UpdateFlashBeforeDebugging>',
                            '<UpdateFlashBeforeDebugging>1</UpdateFlashBeforeDebugging>\n'
                            '            <RunToMain>1</RunToMain>')

    with open(uvprojx_path, 'w', encoding='utf-8') as f:
        f.write(text)


def _fix_absolute_paths_in_uvprojx(uvprojx_path: str) -> None:
    """Replace any absolute Windows paths with relative ones."""
    with open(uvprojx_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # Replace patterns like C:\...\User\main.c -> ..\User\main.c
    def replace_abs(match):
        abs_path = match.group(1)
        # Try to find a known project subdir
        for marker in ['User', 'BSP', 'Source', 'Project', 'Output']:
            idx = abs_path.replace('/', '\\').lower().find(marker.lower() + '\\')
            if idx >= 0:
                return f'<FilePath>..\\{abs_path[idx:]}</FilePath>'
        return match.group(0)

    text = re.sub(r'<FilePath>([A-Za-z]:\\[^<]+)</FilePath>', replace_abs, text)
    text = re.sub(r'<PathWithFileName>([A-Za-z]:\\[^<]+)</PathWithFileName>', replace_abs, text)

    with open(uvprojx_path, 'w', encoding='utf-8') as f:
        f.write(text)


def _generate_readme(readme_path: str, name: str, chip: str, chip_info: Dict) -> None:
    """Generate project README with hardware pin table."""
    hw = load_hardware_pin_map()
    flash_kb = chip_info.get("flash_kb", 512)
    ram_total = chip_info.get("ram_total_kb", 128)
    cpuclk = chip_info.get("default_cpuclk", 80000000)

    fixed = hw.get("fixed_pins", {})
    rows = []
    oled = fixed.get("OLED", {})
    for sig, pin in [("SCLK", oled.get("sclk")), ("MOSI", oled.get("mosi")),
                      ("CS", oled.get("cs")), ("DC", oled.get("dc")), ("RES", oled.get("res"))]:
        if pin: rows.append(f"| OLED | {pin} | SPI0 {sig} | 硬件固定 |")
    kb = fixed.get("Keyboard", {})
    for label, pin in kb.get("rows", {}).items():
        rows.append(f"| Keyboard | {pin} | 行线 {label} | 硬件固定 |")
    for label, pin in kb.get("columns", {}).items():
        rows.append(f"| Keyboard | {pin} | 列线 {label} | 硬件固定 |")
    dbg = fixed.get("Debug", {})
    rows.append(f"| Debug | {dbg.get('swclk','')} | SWCLK | 系统保留 |")
    rows.append(f"| Debug | {dbg.get('swdio','')} | SWDIO | 系统保留 |")
    hfx = fixed.get("HFXT", {})
    rows.append(f"| Clock | {hfx.get('xin','')} | HFXIN {hfx.get('frequency_mhz',40)}MHz | 系统保留 |")
    rows.append(f"| Clock | {hfx.get('xout','')} | HFXOUT | 系统保留 |")

    content = f"""# {name}

## 芯片信息
- **型号**: {chip}
- **内核**: {chip_info.get('core', 'Cortex-M0+')}
- **封装**: {chip_info.get('package', 'LQFP-80(PN)')}
- **Flash**: {flash_kb} KB
- **RAM**: {ram_total} KB
- **主频**: {cpuclk // 1000000} MHz
- **SDK**: {chip_info.get('sdk_version', '2.08.00.03')}

## 硬件固定引脚
| 外设 | 引脚 | 说明 |
|------|------|------|
{chr(10).join(rows)}

## 用户外设
| 外设 | 引脚 | 说明 |
|------|------|------|
| _待添加_ | | |

## 编译与烧录
### 编译: 打开 `Project\\{name}.uvprojx`，F7
### 首次烧录: Flash -> Configure Flash Tools -> Debug -> CMSIS-DAP Debugger -> Settings 确认 SWD -> 勾选 Reset and Run

此工程由 **mspm0g3519 skill** 生成。
"""
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Create MSPM0G3519 Keil project")
    parser.add_argument("--name", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--sdk-path", default=None)
    parser.add_argument("--no-smoke-build", action="store_true")
    args = parser.parse_args()

    result = create_project(args.name, args.path, args.sdk_path,
                           smoke_build=not args.no_smoke_build)
    if result["success"]:
        print(f"\nProject created: {result['project_path']}")
        print(f"Keil project: {result['uvprojx_path']}")
    else:
        print(f"\nError: {result['error']}")
        sys.exit(1)

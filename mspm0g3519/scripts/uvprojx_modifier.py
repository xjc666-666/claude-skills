"""
Modify MSPM0G3519 .uvprojx (Keil uVision project) XML files.
Standalone, no stm32-keil dependency.
"""
import os
import sys
import re
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, List, Dict

SCRIPT_DIR = str(Path(__file__).resolve().parent)
sys.path.insert(0, SCRIPT_DIR)
from utils import normalize_path, load_chip_db


def read_config(uvprojx_path: str) -> Dict:
    """Read a .uvprojx file and return key settings as dict."""
    if not os.path.isfile(uvprojx_path):
        return {"error": f"File not found: {uvprojx_path}"}

    tree = ET.parse(uvprojx_path)
    root = tree.getroot()

    config = {
        "uvprojx_path": normalize_path(uvprojx_path),
        "targets": [],
        "groups": [],
        "defines": {},
    }

    for target in root.iter("Target"):
        tcfg = {}
        tn = target.find("TargetName")
        tcfg["name"] = tn.text if tn is not None else ""

        dev = target.find("Device")
        tcfg["device"] = dev.text if dev is not None else ""

        oname = target.find("OutputName")
        tcfg["output_name"] = oname.text if oname is not None else ""

        # Includes
        inc_paths = []
        for cads_elem in target.iter("Cads"):
            for incp in cads_elem.iter("IncludePath"):
                if incp.text:
                    inc_paths.extend(incp.text.split(";"))
        tcfg["include_paths"] = inc_paths

        # Defines
        for cads_elem in target.iter("Cads"):
            for var in cads_elem.iter("VariousControls"):
                defs = var.find("Define")
                if defs is not None and defs.text:
                    tcfg["defines"] = defs.text

        # Groups
        groups = target.find("Groups")
        if groups is not None:
            for gname_elem in groups.iter("GroupName"):
                gcfg = {"name": gname_elem.text or "", "files": []}
                gfiles_elem = gname_elem.find("Files") if hasattr(gname_elem, 'find') else None
                if gfiles_elem is not None:
                    for fe in gfiles_elem.iter("File"):
                        fcfg = {}
                        fn = fe.find("FileName")
                        fcfg["name"] = fn.text if fn is not None else ""
                        fp = fe.find("FilePath")
                        fcfg["path"] = fp.text if fp is not None else ""
                        ft = fe.find("FileType")
                        fcfg["type"] = ft.text if ft is not None else "1"
                        gcfg["files"].append(fcfg)
                tcfg["groups"].append(gcfg)

        # Pre-build steps
        bm = target.find("BeforeMake")
        if bm is not None:
            rp = bm.find("RunUserProg1")
            if rp is not None:
                dn = rp.find("UserProg1Name")
                if dn is not None and dn.text:
                    tcfg["before_make_cmd"] = dn.text

        config["targets"].append(tcfg)

    return config


def modify_device(uvprojx_path: str, chip: str = "MSPM0G3519") -> bool:
    """Set the Device tag in .uvprojx from chip_db."""
    chip_db = load_chip_db()
    chip_info = chip_db.get(chip, {})
    device = chip_info.get("device", chip)

    try:
        tree = ET.parse(uvprojx_path)
        root = tree.getroot()
        changed = False
        for el in root.iter("Device"):
            if el.text != device:
                el.text = device
                changed = True

        # Also update CPU DLL parameters
        cpu_dll_args = chip_info.get("cpu_string", "")
        if cpu_dll_args:
            for el in root.iter("SimDlls"):
                for param in el.iter("SimDllsArguments"):
                    if param.text and param.text != cpu_dll_args:
                        param.text = cpu_dll_args
                        changed = True

        if changed:
            tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
        return True
    except Exception as e:
        print(f"Error modifying device: {e}")
        return False


def rename_project(uvprojx_path: str, new_name: str) -> bool:
    """Update TargetName and OutputName in .uvprojx."""
    try:
        tree = ET.parse(uvprojx_path)
        root = tree.getroot()
        changed = False

        for tn in root.iter("TargetName"):
            tn.text = new_name
            changed = True
        for on in root.iter("OutputName"):
            on.text = new_name
            changed = True

        if changed:
            tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
        return True
    except Exception as e:
        print(f"Error renaming project: {e}")
        return False


def add_group(uvprojx_path: str, group_name: str, files: List[Dict],
              target_name: Optional[str] = None) -> bool:
    """Add source files to a group in .uvprojx.
    Keil format: <Group><GroupName>X</GroupName><Files><File/>...</Files></Group>
    Source group may use flat format: <GroupName>Source<Files/></GroupName> + <File/> siblings
    files: [{"name": "led.c", "path": "..\\\\BSP\\\\LED\\\\led.c", "type": "1"}, ...]"""
    try:
        tree = ET.parse(uvprojx_path)
        root = tree.getroot()

        for target in root.iter("Target"):
            if target_name and target.find("TargetName").text != target_name:
                continue

            groups = target.find("Groups")
            if groups is None:
                groups = ET.SubElement(target, "Groups")

            # Try Group wrapper format first
            for grp in groups:
                grp_tag = grp.tag.split("}")[-1] if "}" in grp.tag else grp.tag
                if grp_tag != "Group":
                    continue
                gn = grp.find("GroupName")
                if gn is not None and (gn.text or "").strip() == group_name:
                    files_elem = grp.find("Files")
                    if files_elem is None:
                        files_elem = ET.SubElement(grp, "Files")
                    for f in files:
                        fe = ET.SubElement(files_elem, "File")
                        fn = ET.SubElement(fe, "FileName"); fn.text = f["name"]
                        fp = ET.SubElement(fe, "FilePath"); fp.text = f["path"]
                        ft = ET.SubElement(fe, "FileType"); ft.text = f.get("type", "1")
                    tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
                    return True

            # Try flat format (used for Source group)
            children = list(groups)
            for i, child in enumerate(children):
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag == "GroupName" and (child.text or "").strip() == group_name:
                    # Find insertion point (after last File before next GroupName)
                    insert_idx = i + 1
                    while insert_idx < len(children):
                        ntag = children[insert_idx].tag.split("}")[-1] if "}" in children[insert_idx].tag else children[insert_idx].tag
                        if ntag == "GroupName":
                            break
                        insert_idx += 1
                    for f in files:
                        fe = ET.Element("File")
                        fn = ET.SubElement(fe, "FileName"); fn.text = f["name"]
                        fp = ET.SubElement(fe, "FilePath"); fp.text = f["path"]
                        ft = ET.SubElement(fe, "FileType"); ft.text = f.get("type", "1")
                        groups.insert(insert_idx, fe)
                        insert_idx += 1
                    tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
                    return True

            # Group doesn't exist - create in Group wrapper format
            grp = ET.SubElement(groups, "Group")
            gn = ET.SubElement(grp, "GroupName"); gn.text = group_name
            files_elem = ET.SubElement(grp, "Files")
            for f in files:
                fe = ET.SubElement(files_elem, "File")
                fn = ET.SubElement(fe, "FileName"); fn.text = f["name"]
                fp = ET.SubElement(fe, "FilePath"); fp.text = f["path"]
                ft = ET.SubElement(fe, "FileType"); ft.text = f.get("type", "1")

        tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
        return True
    except Exception as e:
        print(f"Error adding group: {e}")
        return False


def remove_group(uvprojx_path: str, group_name: str) -> bool:
    """Remove a source group from the .uvprojx."""
    try:
        tree = ET.parse(uvprojx_path)
        root = tree.getroot()
        for gn in list(root.iter("GroupName")):
            if gn.text == group_name:
                parent = gn if True else None
                groups = root.find(".//Groups")
                if groups is not None:
                    groups.remove(gn)
                break
        tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
        return True
    except Exception as e:
        print(f"Error removing group: {e}")
        return False


def update_defines(uvprojx_path: str, defines: str) -> bool:
    """Update the Define field in .uvprojx."""
    try:
        tree = ET.parse(uvprojx_path)
        root = tree.getroot()
        for cads in root.iter("Cads"):
            for var in cads.iter("VariousControls"):
                defn = var.find("Define")
                if defn is not None:
                    defn.text = defines
        tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
        return True
    except Exception as e:
        print(f"Error updating defines: {e}")
        return False


def update_includes(uvprojx_path: str, include_paths: str) -> bool:
    """Update IncludePath in .uvprojx."""
    try:
        tree = ET.parse(uvprojx_path)
        root = tree.getroot()
        for cads in root.iter("Cads"):
            for incp in cads.iter("IncludePath"):
                incp.text = include_paths
        tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
        return True
    except Exception as e:
        print(f"Error updating includes: {e}")
        return False


def update_syscfg_bat(uvprojx_path: str, sdk_path: str) -> bool:
    """Update the syscfg.bat pre-build command in .uvprojx with correct SDK path."""
    if not os.path.isfile(uvprojx_path):
        return False

    syscfg_bat = os.path.join(sdk_path, "tools", "keil", "syscfg.bat")
    examples = os.path.join(sdk_path, "examples")
    new_cmd = f'cmd.exe /C "{syscfg_bat} {examples} ../User/config.syscfg"'

    try:
        tree = ET.parse(uvprojx_path)
        root = tree.getroot()
        changed = False

        for bm in root.iter("BeforeMake"):
            for rp in bm.iter("RunUserProg1"):
                for dn in rp.iter("UserProg1Name"):
                    dn.text = new_cmd
                    changed = True

        if changed:
            tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
        return True
    except Exception as e:
        print(f"Error updating syscfg.bat: {e}")
        return False


def fix_absolute_paths(project_dir: str) -> bool:
    """Convert absolute Windows paths to relative in .uvprojx/.uvoptx files."""
    # Search in Project/ subdir for .uvprojx/.uvoptx
    proj_dir = os.path.join(project_dir, "Project")
    if not os.path.isdir(proj_dir):
        return False

    for fname in os.listdir(proj_dir):
        if not (fname.endswith(".uvprojx") or fname.endswith(".uvoptx")):
            continue
        full = os.path.join(proj_dir, fname)
        _fix_paths_in_xml(full)

    return True


def _fix_paths_in_xml(xml_path: str) -> None:
    """Fix absolute paths in a .uvprojx or .uvoptx."""
    try:
        tree = ET.parse(xml_path)
    except Exception:
        return
    root = tree.getroot()
    changed = False
    for tag in ("FilePath", "PathWithFileName", "Filename"):
        for elem in root.iter(tag):
            if elem.text and _is_abs_windows_path(elem.text):
                rel = _abs_to_rel(elem.text)
                if rel:
                    elem.text = rel
                    changed = True
    if changed:
        tree.write(xml_path, encoding="UTF-8", xml_declaration=True)


def _is_abs_windows_path(p: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", p))


def _abs_to_rel(abs_path: str) -> Optional[str]:
    """Convert absolute path to relative path from project directory."""
    p = abs_path.replace("/", "\\")
    markers = ["User\\", "BSP\\", "Source\\", "Project\\", "Output\\"]
    for marker in markers:
        idx = p.lower().find(marker.lower())
        if idx >= 0:
            rest = p[idx:]
            return f"..\\{rest}"
    return None


def add_source_group(uvprojx_path: str, files: List[str]) -> bool:
    """Add DriverLib .c files to the Source group in .uvprojx."""
    file_entries = []
    for f in sorted(files):
        name = os.path.basename(f)
        file_entries.append({
            "name": name,
            "path": f"..\\\\Source\\\\ti\\\\driverlib\\\\{name}",
            "type": "1"
        })
    return add_group(uvprojx_path, "Source", file_entries)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Modify Keil .uvprojx project files")
    sub = parser.add_subparsers(dest="command")

    sp_read = sub.add_parser("read")
    sp_read.add_argument("--project", required=True)

    sp_dev = sub.add_parser("device")
    sp_dev.add_argument("--project", required=True)
    sp_dev.add_argument("--chip", default="MSPM0G3519")

    sp_rename = sub.add_parser("rename")
    sp_rename.add_argument("--project", required=True)
    sp_rename.add_argument("--name", required=True)

    sp_add = sub.add_parser("add-group")
    sp_add.add_argument("--project", required=True)
    sp_add.add_argument("--name", required=True, help="Group name")
    sp_add.add_argument("--files", required=True, help="JSON array of file objects")

    sp_rm = sub.add_parser("remove-group")
    sp_rm.add_argument("--project", required=True)
    sp_rm.add_argument("--name", required=True)

    sp_def = sub.add_parser("defines")
    sp_def.add_argument("--project", required=True)
    sp_def.add_argument("--defines", required=True)

    sp_inc = sub.add_parser("includes")
    sp_inc.add_argument("--project", required=True)
    sp_inc.add_argument("--paths", required=True)

    sp_sys = sub.add_parser("update-syscfg-bat")
    sp_sys.add_argument("--project", required=True)
    sp_sys.add_argument("--sdk-path", required=True)

    sp_fix = sub.add_parser("fix-paths")
    sp_fix.add_argument("--project-dir", required=True)

    args = parser.parse_args()

    if args.command == "read":
        config = read_config(args.project)
        print(json.dumps(config, indent=2, ensure_ascii=False))
    elif args.command == "device":
        modify_device(args.project, args.chip)
    elif args.command == "rename":
        rename_project(args.project, args.name)
    elif args.command == "add-group":
        files = json.loads(args.files)
        add_group(args.project, args.name, files)
    elif args.command == "remove-group":
        remove_group(args.project, args.name)
    elif args.command == "defines":
        update_defines(args.project, args.defines)
    elif args.command == "includes":
        update_includes(args.project, args.paths)
    elif args.command == "update-syscfg-bat":
        update_syscfg_bat(args.project, args.sdk_path)
    elif args.command == "fix-paths":
        fix_absolute_paths(args.project_dir)
    else:
        parser.print_help()

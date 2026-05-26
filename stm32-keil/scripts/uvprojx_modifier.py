"""
Programmatically modify Keil MDK-ARM v5 .uvprojx XML files.
"""
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import load_chip_db


def read_current_config(uvprojx_path: str) -> Dict[str, Any]:
    """Parse a .uvprojx file and return all key settings as a dict."""
    tree = ET.parse(uvprojx_path)
    root = tree.getroot()

    ns = {"": ""}
    config = {}

    # Find first target
    target = root.find(".//Target")
    if target is None:
        raise ValueError("No <Target> found in .uvprojx")

    config["target_name"] = target.findtext("TargetName", "")
    config["toolset_number"] = target.findtext("ToolsetNumber", "")
    config["toolset_name"] = target.findtext("ToolsetName", "")

    # Device settings
    tc = target.find(".//TargetCommonOption")
    if tc is not None:
        config["device"] = tc.findtext("Device", "")
        config["vendor"] = tc.findtext("Vendor", "")
        config["pack_id"] = tc.findtext("PackID", "")
        config["cpu"] = tc.findtext("Cpu", "")
        config["flash_driver_dll"] = tc.findtext("FlashDriverDll", "")
        config["svd_file"] = tc.findtext("SFDFile", "")

    # Compiler settings
    cads = target.find(".//Cads")
    if cads is not None:
        vc = cads.find("VariousControls")
        if vc is not None:
            config["defines"] = vc.findtext("Define", "")
            config["include_path"] = vc.findtext("IncludePath", "")
            config["misc_controls"] = vc.findtext("MiscControls", "")

    # uAC6 flag
    config["uac6"] = target.findtext("uAC6", "0")

    # Group structure
    groups = target.find("Groups")
    if groups is not None:
        config["groups"] = []
        for grp in groups.findall("Group"):
            gname = grp.findtext("GroupName", "")
            files = []
            for f in grp.findall(".//File"):
                fn = f.findtext("FileName", "")
                fp = f.findtext("FilePath", "")
                ft = f.findtext("FileType", "1")
                inc = "1"
                cp = f.find(".//IncludeInBuild")
                if cp is not None:
                    inc = cp.text or "1"
                files.append({"name": fn, "path": fp, "type": ft, "include_in_build": inc})
            config["groups"].append({"name": gname, "files": files})

    # Output settings
    config["output_dir"] = target.findtext("OutputDirectory", "")
    config["output_name"] = target.findtext("OutputName", "")
    config["create_hex"] = target.findtext("CreateHexFile", "0")

    # Linker settings
    ldad = target.find(".//LDads")
    if ldad is not None:
        config["scatter_file"] = ldad.findtext("ScatterFile", "")

    return config


def modify_device(uvprojx_path: str, chip_name: str, chip_db_path: Optional[str] = None) -> bool:
    """
    Modify a .uvprojx file to target a specific chip.
    Updates all device-specific fields.
    """
    db = load_chip_db(chip_db_path)
    if chip_name not in db:
        print(f"Error: Chip '{chip_name}' not found in database")
        return False

    chip = db[chip_name]
    tree = ET.parse(uvprojx_path)
    root = tree.getroot()

    target = root.find(".//Target")
    if target is None:
        print("Error: No <Target> found")
        return False

    # Update device
    tc = target.find(".//TargetCommonOption")
    if tc is not None:
        _set_or_create(tc, "Device", chip["device"])
        _set_or_create(tc, "PackID", chip["pack_id"])
        _set_or_create(tc, "Cpu", chip["cpu_string"])
        _set_or_create(tc, "FlashDriverDll", chip["flash_driver"])
        _set_or_create(tc, "SFDFile", f"$$Device:{chip['device']}$CMSIS\\SVD\\{chip['svd_file']}")

    # Update preprocessor defines
    cads = target.find(".//Cads")
    if cads is not None:
        vc = cads.find("VariousControls")
        if vc is not None:
            _set_or_create(vc, "Define", chip["defines"])

    # Update DLL simulation arguments
    for dll_el in target.iter():
        if dll_el.tag in ("SimDlgDllArguments", "TargetDlgDllArguments"):
            dll_el.text = chip["sim_dll_args"]

    # Update TargetDllArguments (MPU for CM4, empty for CM3)
    for td in target.iter("TargetDllArguments"):
        if chip.get("has_fpu", False):
            td.text = " -MPU"
        else:
            td.text = ""

    # Update OnChipMemories
    _update_onchip_memories(target, chip)

    # Update IRAM/IROM had flags
    _update_had_flags(target, chip)

    # Write back
    tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
    print(f"Device updated to {chip_name}")
    return True


def _update_onchip_memories(target: ET.Element, chip: Dict) -> None:
    """Update the OnChipMemories section with correct RAM/ROM sizes."""
    ocm = target.find(".//OnChipMemories")
    if ocm is None:
        return

    ram_size = chip["ram_size"]
    flash_size = chip["flash_size"]

    for mem in ocm:
        mem_type = mem.findtext("Type", "")
        if mem.tag == "IRAM" and mem_type == "0":
            _set_or_create(mem, "Size", ram_size)
        elif mem.tag == "IROM" and mem_type == "1":
            _set_or_create(mem, "Size", flash_size)

    # Update OCR_RVCT4 (ROM) and OCR_RVCT9 (RAM)
    rvct4 = ocm.find("OCR_RVCT4")
    if rvct4 is not None:
        _set_or_create(rvct4, "Size", flash_size)
    rvct9 = ocm.find("OCR_RVCT9")
    if rvct9 is not None:
        _set_or_create(rvct9, "Size", ram_size)

    # OCR_RVCT10 is IRAM2 (CCM), only for F4
    rvct10 = ocm.find("OCR_RVCT10")
    if rvct10 is not None:
        if chip.get("has_iram2", False):
            _set_or_create(rvct10, "StartAddress", "0x10000000")
            _set_or_create(rvct10, "Size", "0x10000")
        else:
            _set_or_create(rvct10, "StartAddress", "0x0")
            _set_or_create(rvct10, "Size", "0x0")


def _update_had_flags(target: ET.Element, chip: Dict) -> None:
    """Update hadIRAM, hadIROM, hadIRAM2 flags."""
    for flag in target.iter():
        if flag.tag == "hadIRAM2":
            flag.text = "1" if chip.get("has_iram2", False) else "0"


def add_source_group(uvprojx_path: str, group_name: str, files: List[Dict[str, str]]) -> bool:
    """
    Add a new Group with source files to the project.

    files: list of {"name": "main.c", "path": "..\\User\\main.c", "type": "1"}
    """
    tree = ET.parse(uvprojx_path)
    root = tree.getroot()

    target = root.find(".//Target")
    if target is None:
        return False

    groups = target.find("Groups")
    if groups is None:
        groups = ET.SubElement(target, "Groups")

    # Check if group already exists
    for existing in groups.findall("Group"):
        if existing.findtext("GroupName") == group_name:
            # Group exists, add files
            fe = existing.find("Files")
            if fe is None:
                fe = ET.SubElement(existing, "Files")
            for f in files:
                _add_file_element(fe, f)
            tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
            return True

    # Create new group
    grp = ET.SubElement(groups, "Group")
    gn = ET.SubElement(grp, "GroupName")
    gn.text = group_name

    fe = ET.SubElement(grp, "Files")
    for f in files:
        _add_file_element(fe, f)

    tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
    print(f"Group '{group_name}' added with {len(files)} file(s)")
    return True


def _add_file_element(parent: ET.Element, file_info: Dict[str, str]) -> None:
    """Add a <File> element to a <Files> parent."""
    f_elem = ET.SubElement(parent, "File")
    fn = ET.SubElement(f_elem, "FileName")
    fn.text = file_info.get("name", "")
    ft = ET.SubElement(f_elem, "FileType")
    ft.text = file_info.get("type", "1")
    fp = ET.SubElement(f_elem, "FilePath")
    fp.text = file_info.get("path", "")


def remove_source_group(uvprojx_path: str, group_name: str) -> bool:
    """Remove a Group (and all its files) from the project."""
    tree = ET.parse(uvprojx_path)
    root = tree.getroot()

    target = root.find(".//Target")
    if target is None:
        return False

    groups = target.find("Groups")
    if groups is None:
        return False

    for grp in groups.findall("Group"):
        if grp.findtext("GroupName") == group_name:
            groups.remove(grp)
            tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
            print(f"Group '{group_name}' removed")
            return True

    return False


def add_file_to_group(uvprojx_path: str, group_name: str,
                      file_info: Dict[str, str]) -> bool:
    """Add a single file to an existing group."""
    tree = ET.parse(uvprojx_path)
    root = tree.getroot()

    target = root.find(".//Target")
    if target is None:
        return False

    groups = target.find("Groups")
    if groups is None:
        return False

    for grp in groups.findall("Group"):
        if grp.findtext("GroupName") == group_name:
            fe = grp.find("Files")
            if fe is None:
                fe = ET.SubElement(grp, "Files")
            _add_file_element(fe, file_info)
            tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
            print(f"File '{file_info.get('name')}' added to group '{group_name}'")
            return True

    return False


def update_defines(uvprojx_path: str, defines: str) -> bool:
    """Update the preprocessor defines string."""
    tree = ET.parse(uvprojx_path)
    root = tree.getroot()

    target = root.find(".//Target")
    if target is None:
        return False

    cads = target.find(".//Cads")
    if cads is None:
        return False

    vc = cads.find("VariousControls")
    if vc is None:
        vc = ET.SubElement(cads, "VariousControls")

    _set_or_create(vc, "Define", defines)
    tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
    return True


def update_include_paths(uvprojx_path: str, paths: str) -> bool:
    """Update the include paths string (semicolon separated)."""
    tree = ET.parse(uvprojx_path)
    root = tree.getroot()

    target = root.find(".//Target")
    if target is None:
        return False

    cads = target.find(".//Cads")
    if cads is None:
        return False

    vc = cads.find("VariousControls")
    if vc is None:
        vc = ET.SubElement(cads, "VariousControls")

    _set_or_create(vc, "IncludePath", paths)
    tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
    return True


def rename_project(uvprojx_path: str, new_name: str) -> bool:
    """Rename the project target and update OutputName.

    Both <TargetName> and <OutputName> live under <Target>, but OutputName
    is usually a sub-child of <TargetCommonOption>. Use .iter() so we don't
    miss it regardless of nesting depth."""
    tree = ET.parse(uvprojx_path)
    root = tree.getroot()

    target = root.find(".//Target")
    if target is None:
        return False

    # TargetName (directly under Target)
    tn = target.find("TargetName")
    if tn is not None:
        tn.text = new_name

    # OutputName (under TargetCommonOption, but iter() walks any depth)
    for on_el in target.iter("OutputName"):
        on_el.text = new_name

    tree.write(uvprojx_path, encoding="UTF-8", xml_declaration=True)
    print(f"Project renamed to '{new_name}'")
    return True


def _set_or_create(parent: ET.Element, tag: str, text: str) -> None:
    """Set element text, creating the element if it doesn't exist."""
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    el.text = text


# Ensure CDATA sections for specific elements that need them
def _indent_xml(elem: ET.Element, level: int = 0) -> None:
    """Pretty-print XML with indentation."""
    indent = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for subelem in elem:
            _indent_xml(subelem, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Modify Keil .uvprojx files")
    sub = parser.add_subparsers(dest="command")

    # Read config
    read_p = sub.add_parser("read", help="Read project configuration")
    read_p.add_argument("--project", required=True, help="Path to .uvprojx")

    # Modify device
    dev_p = sub.add_parser("device", help="Change target device")
    dev_p.add_argument("--project", required=True)
    dev_p.add_argument("--chip", required=True, help="Chip model (e.g., STM32F407ZGT6)")

    # Add group
    grp_p = sub.add_parser("add-group", help="Add source group")
    grp_p.add_argument("--project", required=True)
    grp_p.add_argument("--name", required=True, help="Group name")
    grp_p.add_argument("--files", required=True, help="JSON array of file dicts")

    # Remove group
    rm_p = sub.add_parser("remove-group", help="Remove source group")
    rm_p.add_argument("--project", required=True)
    rm_p.add_argument("--name", required=True)

    # Update defines
    def_p = sub.add_parser("defines", help="Update preprocessor defines")
    def_p.add_argument("--project", required=True)
    def_p.add_argument("--defines", required=True)

    # Update include paths
    inc_p = sub.add_parser("includes", help="Update include paths")
    inc_p.add_argument("--project", required=True)
    inc_p.add_argument("--paths", required=True)

    args = parser.parse_args()

    if args.command == "read":
        config = read_current_config(args.project)
        print(json.dumps(config, indent=2, ensure_ascii=False))
    elif args.command == "device":
        modify_device(args.project, args.chip)
    elif args.command == "add-group":
        files = json.loads(args.files)
        add_source_group(args.project, args.name, files)
    elif args.command == "remove-group":
        remove_source_group(args.project, args.name)
    elif args.command == "defines":
        update_defines(args.project, args.defines)
    elif args.command == "includes":
        update_include_paths(args.project, args.paths)
    else:
        parser.print_help()

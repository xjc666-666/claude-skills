"""
Auto-fix ARMCLANG V6.24 compilation errors for MSPM0G3519 projects.
"""
import os
import sys
import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = str(Path(__file__).resolve().parent)
SKILL_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)
from utils import (
    normalize_path, load_error_patterns, load_chip_db,
    BuildError, extract_includes_from_c, find_in_project
)
from uvprojx_modifier import add_group
from syscfg_generator import generate_syscfg
from driverlib_manager import get_driverlib_c_files


def fix_errors(errors_json: str, project_dir: str, apply: bool = False,
               max_rounds: int = 5) -> Dict:
    """Auto-fix compile errors. Returns fix plan (dry-run) or fix result (apply)."""
    errors = _parse_error_json(errors_json)
    if not errors:
        return {"fixed": 0, "unfixable": 0, "fixes": [], "message": "No errors to fix"}

    pattern_db = load_error_patterns()
    fixes = []
    unfixable = []

    for err in errors:
        matched = False
        for pattern in pattern_db.get("patterns", []):
            m = re.search(pattern["regex"], err.message, re.IGNORECASE)
            if m:
                strategy_name = pattern.get("fix_strategy", "")
                strategy = pattern_db.get("fix_strategies", {}).get(strategy_name, {})

                fix = {
                    "error": err,
                    "pattern_id": pattern["id"],
                    "strategy": strategy_name,
                    "fixable": strategy.get("auto_fix", False),
                    "action": strategy.get("action", ""),
                    "file": _resolve_file(err.file, project_dir),
                    "matches": m.groups(),
                }

                if fix["fixable"] and apply:
                    _apply_fix(fix, project_dir, m)
                    fix["applied"] = True
                else:
                    fix["applied"] = False

                fixes.append(fix)
                matched = True
                break

        if not matched:
            unfixable.append({
                "error": err,
                "message": "No matching fix strategy found",
            })

    return {
        "fixed": len([f for f in fixes if f.get("applied")]),
        "total_fixable": len([f for f in fixes if f.get("fixable")]),
        "unfixable": len(unfixable),
        "fixes": fixes,
        "unfixable_errors": unfixable,
        "apply_mode": apply,
    }


def _apply_fix(fix: Dict, project_dir: str, match: re.Match) -> None:
    """Apply a specific fix based on the strategy."""
    strategy = fix["strategy"]
    filepath = fix["file"]

    if strategy == "mspm0_identifier":
        identifier = match.group(1) if match.groups() else ""
        # Try to find which header defines this identifier
        dl_api_map = load_error_patterns().get("dl_api_header_map", {})
        for prefix, header in dl_api_map.items():
            if identifier.startswith(prefix):
                _add_include_to_file(filepath, f"#include <ti/driverlib/{header}>")
                return
        # Check BSP headers
        _add_include_to_file(filepath, '#include "bsp.h"')

    elif strategy == "ensure_bsp_h":
        _add_include_to_file(filepath, '#include "bsp.h"')

    elif strategy == "insert_semicolon":
        line_num = fix["error"].line
        if line_num > 0 and filepath and os.path.isfile(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if line_num <= len(lines):
                lines[line_num - 1] = lines[line_num - 1].rstrip() + ";\n"
                with open(filepath, "w", encoding="utf-8") as f:
                    f.writelines(lines)

    elif strategy in ("run_syscfg", "syscfg_not_run"):
        # Trigger syscfg generation
        uvprojx_path = _find_uvprojx(project_dir)
        if uvprojx_path:
            generate_syscfg(project_dir)

    elif strategy == "missing_driverlib_source":
        # Find the missing DL function and add source file
        func_name = match.group(1) if match.groups() else ""
        dl_source_map = load_error_patterns().get("dl_source_map", {})
        # Try to find from header mention in error
        # For now, just report - needs specific file path
        pass

    elif strategy == "add_include":
        # Try to find the function in project headers
        func_name = match.group(1) if match.groups() else ""
        found = False
        for root, dirs, files in os.walk(project_dir):
            for f in files:
                if f.endswith(".h"):
                    fpath = os.path.join(root, f)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                            if func_name in fh.read():
                                rel = os.path.relpath(fpath, os.path.dirname(filepath))
                                _add_include_to_file(filepath, f'#include "{rel}"')
                                found = True
                                break
                    except Exception:
                        pass
            if found:
                break


def _add_include_to_file(filepath: str, include_line: str) -> bool:
    """Add an #include line to a source file."""
    if not filepath or not os.path.isfile(filepath):
        return False
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if include_line in content:
        return True

    lines = content.split("\n")
    last_include_idx = -1
    for i, line in enumerate(lines):
        if re.match(r'^\s*#include\s+', line):
            last_include_idx = i

    if last_include_idx >= 0:
        lines.insert(last_include_idx + 1, include_line)
    else:
        lines.insert(0, include_line)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return True


def _resolve_file(file_path: str, project_dir: str) -> Optional[str]:
    """Resolve a file path from build output to absolute path."""
    if not file_path:
        return None
    # Try relative to project
    candidates = [
        file_path,
        os.path.join(project_dir, file_path),
        os.path.join(project_dir, "User", file_path),
        os.path.join(project_dir, "BSP", file_path),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return file_path


def _find_uvprojx(project_dir: str) -> Optional[str]:
    """Find .uvprojx in project."""
    for sub in [os.path.join(project_dir, "Project"), project_dir]:
        if os.path.isdir(sub):
            for f in os.listdir(sub):
                if f.endswith(".uvprojx"):
                    return os.path.join(sub, f)
    return None


def _parse_error_json(errors_json: str) -> List[BuildError]:
    """Parse error JSON to list of BuildError."""
    try:
        data = json.loads(errors_json)
    except json.JSONDecodeError:
        return []

    if isinstance(data, list):
        return [BuildError(
            file=e.get("file", ""),
            line=e.get("line", 0),
            code=e.get("code", ""),
            message=e.get("message", "")
        ) for e in data]
    return []


def print_fix_report(result: Dict) -> None:
    """Print fix report."""
    print("=" * 60)
    if result["apply_mode"]:
        print(f"自动修复: {result['fixed']}/{result['total_fixable']} 个问题")
    else:
        print(f"[DRY-RUN] 可修复: {result['total_fixable']} 个, 无法自动修复: {result['unfixable']} 个")
    print("=" * 60)

    for fix in result.get("fixes", []):
        err = fix["error"]
        status = "FIXED" if fix.get("applied") else ("FIXABLE" if fix["fixable"] else "MANUAL")
        print(f"  [{status}] {err.file}:{err.line}: {err.message[:80]}")
        print(f"    策略: {fix['strategy']} -> {fix['action']}")

    for uf in result.get("unfixable_errors", []):
        err = uf["error"]
        print(f"  [UNFIXABLE] {err.file}:{err.line}: {err.message[:80]}")

    print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Auto-fix MSPM0G3519 compile errors")
    parser.add_argument("--errors", required=True, help="JSON array of errors")
    parser.add_argument("--project-dir", required=True, help="Project root directory")
    parser.add_argument("--apply", action="store_true", help="Apply fixes (default: dry-run)")

    args = parser.parse_args()

    result = fix_errors(args.errors, args.project_dir, apply=args.apply)
    print_fix_report(result)

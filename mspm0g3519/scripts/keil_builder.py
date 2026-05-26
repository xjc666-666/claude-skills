"""
Compile MSPM0G3519 Keil project via uv4.exe (ARMCLANG V6.24).
"""
import os
import sys
import re
import json
from pathlib import Path
from typing import List, Optional, Dict, Tuple

SCRIPT_DIR = str(Path(__file__).resolve().parent)
sys.path.insert(0, SCRIPT_DIR)
from utils import (
    find_keil_installation, run_command, normalize_path,
    BuildError, BuildResult, MSPM0G3519_FLASH, MSPM0G3519_RAM,
    format_size_info
)


def compile_project(
    uvprojx_path: str,
    keil_uv4_dir: Optional[str] = None,
    timeout: int = 300,
    rebuild: bool = False,
) -> BuildResult:
    """Compile a Keil project and return results."""

    if keil_uv4_dir is None:
        keil_uv4_dir = find_keil_installation()
        if keil_uv4_dir is None:
            return BuildResult(
                success=False,
                errors=[BuildError("", 0, "", "Keil MDK-ARM not found.")],
                warnings=[],
                output="Error: Keil installation not found."
            )

    uv4_exe = os.path.join(keil_uv4_dir, "uv4.exe")
    if not os.path.isfile(uv4_exe):
        return BuildResult(
            success=False,
            errors=[BuildError("", 0, "", f"uv4.exe not found at {uv4_exe}")],
            warnings=[],
            output=f"Error: {uv4_exe} does not exist."
        )

    project_dir = os.path.dirname(uvprojx_path)
    project_file = os.path.basename(uvprojx_path)

    flag = "-r" if rebuild else "-b"
    cmd = [uv4_exe, "-j0", flag, project_file]

    returncode, stdout, stderr = run_command(cmd, cwd=project_dir, timeout=timeout)

    htm_text = _read_build_log_htm(project_dir)
    full_output = stdout + "\n" + stderr + "\n" + htm_text

    # Write build output
    output_path = os.path.join(project_dir, "build_output.txt")
    with open(output_path, "w", encoding="utf-8", errors="ignore") as f:
        f.write(full_output)

    errors = _parse_errors(full_output)
    warnings = _parse_warnings(full_output)
    size_info = _parse_program_size(full_output)

    success = returncode == 0 and len(errors) == 0
    if not success and len(errors) == 0 and returncode != 0:
        errors.append(BuildError("", 0, "SYSTEM", f"Build failed with return code {returncode}"))

    hex_path = _find_output_hex(project_dir)
    chip = "MSPM0G3519"

    return BuildResult(
        success=success,
        errors=errors,
        warnings=warnings,
        output=full_output,
        hex_path=hex_path,
        size_info=size_info,
        chip=chip,
    )


def _read_build_log_htm(project_dir: str) -> str:
    """Read Keil's HTML build log and return plain text."""
    obj_dir = os.path.join(project_dir, "Objects")
    if not os.path.isdir(obj_dir):
        return ""
    candidates = [f for f in os.listdir(obj_dir) if f.endswith(".build_log.htm")]
    if not candidates:
        return ""
    candidates.sort(key=lambda f: os.path.getmtime(os.path.join(obj_dir, f)), reverse=True)
    path = os.path.join(obj_dir, candidates[0])
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return ""
    text = None
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text)


def _parse_errors(output: str) -> List[BuildError]:
    """Parse ARMCLANG V6.24 errors."""
    errors = []
    seen = set()

    # ARMClang: "filename:line:col: error: message"
    armclang = re.compile(
        r'^(.+?):(\d+):(?:\d+:)?\s*(?:error|fatal error):\s*(.+)$',
        re.MULTILINE
    )
    for m in armclang.finditer(output):
        key = (m.group(1).strip(), int(m.group(2)), m.group(3).strip())
        if key in seen:
            continue
        seen.add(key)
        errors.append(BuildError(key[0], key[1], "", key[2]))

    # ARMCC5 style: "filename(line): error: #code: message"
    armcc5 = re.compile(
        r'^(.+?)\((\d+)\):\s*(?:error|致命错误|fatal error):\s*(?:#(\d+(?:-D)?):\s*)?(.+)$',
        re.MULTILINE
    )
    for m in armcc5.finditer(output):
        key = (m.group(1).strip(), int(m.group(2)), m.group(4).strip())
        if key in seen:
            continue
        seen.add(key)
        errors.append(BuildError(key[0], key[1], m.group(3) or "", key[2]))

    # Linker errors: "error: L6xxxE: ..."
    linker = re.compile(
        r'^(?:.*?):\s*error:\s*(L\d+[A-Z]?):\s*(.+)$',
        re.MULTILINE
    )
    for m in linker.finditer(output):
        key = ("", 0, m.group(2).strip())
        if key in seen:
            continue
        seen.add(key)
        errors.append(BuildError("", 0, m.group(1), key[2]))

    return errors


def _parse_warnings(output: str) -> List[BuildError]:
    """Parse ARMCLANG warnings."""
    warnings = []
    seen = set()

    armclang = re.compile(
        r'^(.+?):(\d+):(?:\d+:)?\s*warning:\s*(.+)$',
        re.MULTILINE
    )
    for m in armclang.finditer(output):
        key = (m.group(1).strip(), int(m.group(2)), m.group(3).strip())
        if key in seen:
            continue
        seen.add(key)
        warnings.append(BuildError(key[0], key[1], "", key[2]))

    return warnings


def _parse_program_size(output: str) -> Optional[Dict]:
    """Parse 'Program Size: Code=... RO-data=... RW-data=... ZI-data=...' from build output."""
    m = re.search(
        r'Program Size:\s*Code=(\d+)\s+RO-data=(\d+)\s+RW-data=(\d+)\s+ZI-data=(\d+)',
        output
    )
    if not m:
        return None
    code, ro, rw, zi = (int(x) for x in m.groups())
    return {
        "code": code,
        "ro_data": ro,
        "rw_data": rw,
        "zi_data": zi,
        "flash_bytes": code + ro + rw,
        "ram_bytes": rw + zi,
    }


def _find_output_hex(project_dir: str) -> Optional[str]:
    """Find the output .hex file in Objects/ or Listings/."""
    for sub in ("Objects", "Listings"):
        d = os.path.join(project_dir, sub)
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".hex"):
                    return normalize_path(os.path.join(d, f))
    return None


def get_build_summary(result: BuildResult) -> str:
    """Generate human-readable build summary."""
    lines = []
    if result.success:
        lines.append("编译成功！")
        hex_info = f"\n输出文件: {result.hex_path}" if result.hex_path else ""
        lines.append(f"0 个错误, {len(result.warnings)} 个警告{hex_info}")
        if result.size_info:
            lines.append(format_size_info(result.size_info))
    else:
        lines.append(f"编译失败: {len(result.errors)} 个错误, {len(result.warnings)} 个警告")

    for err in result.errors:
        loc = f"{err.file}:{err.line}" if err.file else "链接器"
        lines.append(f"  ERROR [{err.code}] {loc}: {err.message}")

    for warn in result.warnings[:10]:
        lines.append(f"  WARNING [{warn.code}] {warn.file}:{warn.line}: {warn.message}")

    if len(result.warnings) > 10:
        lines.append(f"  ... 还有 {len(result.warnings) - 10} 个警告")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Compile MSPM0G3519 Keil project")
    parser.add_argument("--project", required=True, help="Path to .uvprojx file")
    parser.add_argument("--keil", default=None, help="Path to Keil UV4 directory")
    parser.add_argument("--timeout", type=int, default=300, help="Build timeout in seconds")
    parser.add_argument("--rebuild", action="store_true", help="Full rebuild")

    args = parser.parse_args()

    result = compile_project(
        args.project,
        keil_uv4_dir=args.keil,
        timeout=args.timeout,
        rebuild=args.rebuild,
    )

    print(get_build_summary(result))

    if not result.success:
        sys.exit(1)

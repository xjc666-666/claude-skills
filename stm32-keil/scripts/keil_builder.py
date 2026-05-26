"""
Compile a Keil MDK-ARM project and capture build output.
"""
import os
import sys
import re
import json
from pathlib import Path
from typing import List, Optional, Tuple, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import (
    find_keil_installation, run_command, normalize_path,
    BuildError, BuildResult
)


def compile_project(
    uvprojx_path: str,
    keil_uv4_dir: Optional[str] = None,
    timeout: int = 300,
    rebuild: bool = False,
) -> BuildResult:
    """
    Compile a Keil project and return results.

    Args:
        uvprojx_path: Path to .uvprojx file
        keil_uv4_dir: Path to Keil UV4 directory (auto-detect if None)
        timeout: Build timeout in seconds
        rebuild: If True, full rebuild (-r); else incremental (-b, much faster)

    Returns:
        BuildResult with success, errors, warnings, and output
    """
    if keil_uv4_dir is None:
        keil_uv4_dir = find_keil_installation()
        if keil_uv4_dir is None:
            return BuildResult(
                success=False,
                errors=[BuildError("", 0, "", "Keil MDK-ARM not found. Checked standard paths.")],
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

    # Build command: -r = full rebuild, -b = incremental build
    flag = "-r" if rebuild else "-b"
    cmd = [uv4_exe, "-j0", flag, project_file]

    # Execute
    returncode, stdout, stderr = run_command(cmd, cwd=project_dir, timeout=timeout)

    # Combine output. uv4.exe writes the actual build log to
    # Project/Objects/<name>.build_log.htm rather than stdout, so include
    # that file's text in our parsed view.
    htm_text = _read_build_log_htm(project_dir)
    full_output = stdout + "\n" + stderr + "\n" + htm_text
    output_path = os.path.join(project_dir, "build_output.txt")
    with open(output_path, "w", encoding="utf-8", errors="ignore") as f:
        f.write(full_output)

    # Parse errors and warnings
    errors = _parse_errors(full_output)
    warnings = _parse_warnings(full_output)
    size_info = _parse_program_size(full_output)

    # Determine success
    success = returncode == 0 and len(errors) == 0
    if not success and len(errors) == 0 and returncode != 0:
        # Might be a system error
        errors.append(BuildError("", 0, "SYSTEM", f"Build failed with return code {returncode}"))

    # Find output hex file
    hex_path = _find_output_hex(project_dir)

    # Try to read chip from .uvprojx for capacity calculation
    chip_name = _read_chip_from_project(uvprojx_path)

    return BuildResult(
        success=success,
        errors=errors,
        warnings=warnings,
        output=full_output,
        hex_path=hex_path,
        size_info=size_info,
        chip=chip_name,
    )


def _read_build_log_htm(project_dir: str) -> str:
    """Read Keil's HTML build log and return its plain text.
    Keil writes its real build output here, not to stdout."""
    obj_dir = os.path.join(project_dir, "Objects")
    if not os.path.isdir(obj_dir):
        return ""
    candidates = [f for f in os.listdir(obj_dir) if f.endswith(".build_log.htm")]
    if not candidates:
        return ""
    # Newest one
    candidates.sort(key=lambda f: os.path.getmtime(os.path.join(obj_dir, f)),
                    reverse=True)
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
    # Strip HTML tags so our error/size regexes can match cleanly
    return re.sub(r"<[^>]+>", "", text)


def _read_chip_from_project(uvprojx_path: str) -> Optional[str]:
    """Extract Device tag from .uvprojx (e.g. STM32F407ZGTx)."""
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(uvprojx_path)
        for el in tree.iter("Device"):
            if el.text:
                return el.text.strip()
    except Exception:
        pass
    return None


def _parse_errors(output: str) -> List[BuildError]:
    """Parse compilation errors from Keil build output.
    Supports both ARMCC5 ("file(line): error: #code: msg") and
    ARMClang/ARMCC6 ("file:line:col: error: msg [warning_flag]")."""
    errors = []
    seen = set()

    # ARMCC5: "filename(line): error:  #code: message"
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

    # ARMClang/ARMCC6: "filename:line:col: error: message"
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
    """Parse compilation warnings (both ARMCC5 and ARMClang formats)."""
    warnings = []
    seen = set()

    armcc5 = re.compile(
        r'^(.+?)\((\d+)\):\s*warning:\s*#(\d+(?:-D)?):\s*(.+)$',
        re.MULTILINE
    )
    for m in armcc5.finditer(output):
        key = (m.group(1).strip(), int(m.group(2)), m.group(4).strip())
        if key in seen:
            continue
        seen.add(key)
        warnings.append(BuildError(key[0], key[1], m.group(3), key[2]))

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
    """Find the output .hex file. `project_dir` is the directory holding the
    .uvprojx (typically <root>/Project/), so Objects/ sits next to it."""
    for sub in ("Objects", "Listings", os.path.join("Project", "Objects"),
                os.path.join("Project", "Listings")):
        d = os.path.join(project_dir, sub)
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".hex"):
                    return normalize_path(os.path.join(d, f))
    return None


def detect_armcc_version(keil_uv4_dir: str) -> Optional[str]:
    """Detect installed ARMCC version."""
    armcc5_path = os.path.join(keil_uv4_dir, "..", "ARMCC", "bin", "armcc.exe")
    armcc6_path = os.path.join(keil_uv4_dir, "..", "ARMCLANG", "bin", "armclang.exe")

    versions = []
    if os.path.isfile(armcc5_path):
        versions.append("ARMCC5")
    if os.path.isfile(armcc6_path):
        versions.append("ARMCC6")

    return ", ".join(versions) if versions else None


def get_build_summary(result: BuildResult) -> str:
    """Generate a human-readable build summary."""
    lines = []
    if result.success:
        lines.append("编译成功！")
        hex_info = f"\n输出文件: {result.hex_path}" if result.hex_path else ""
        lines.append(f"0 个错误, {len(result.warnings)} 个警告{hex_info}")
        if result.size_info:
            lines.append(_format_size_info(result.size_info, result.chip))
    else:
        lines.append(f"编译失败: {len(result.errors)} 个错误, {len(result.warnings)} 个警告")

    for err in result.errors:
        loc = f"{err.file}:{err.line}" if err.file else "链接器"
        lines.append(f"  ERROR [{err.code}] {loc}: {err.message}")

    for warn in result.warnings[:10]:  # Limit warnings
        lines.append(f"  WARNING [{warn.code}] {warn.file}:{warn.line}: {warn.message}")

    if len(result.warnings) > 10:
        lines.append(f"  ... 还有 {len(result.warnings) - 10} 个警告")

    return "\n".join(lines)


def _format_size_info(size: Dict, device: Optional[str]) -> str:
    """Format size info as a human-readable usage report, with capacity %
    if the chip's flash/RAM size is known from chip_db."""
    flash = size["flash_bytes"]
    ram = size["ram_bytes"]
    body = (
        f"Code={size['code']} B, RO-data={size['ro_data']} B, "
        f"RW-data={size['rw_data']} B, ZI-data={size['zi_data']} B"
    )
    cap = _lookup_capacity(device) if device else None
    if cap is None:
        return f"占用: Flash={_kb(flash)}, RAM={_kb(ram)}  ({body})"

    flash_max, ram_max = cap
    fp = 100.0 * flash / flash_max if flash_max else 0
    rp = 100.0 * ram / ram_max if ram_max else 0
    flag = []
    if fp >= 90:
        flag.append(f"⚠ Flash {fp:.0f}%")
    if rp >= 90:
        flag.append(f"⚠ RAM {rp:.0f}%")
    suffix = "  " + " ".join(flag) if flag else ""
    return (f"占用: Flash={_kb(flash)}/{_kb(flash_max)} ({fp:.1f}%), "
            f"RAM={_kb(ram)}/{_kb(ram_max)} ({rp:.1f}%){suffix}\n  ({body})")


def _kb(n: int) -> str:
    if n >= 1024:
        return f"{n/1024:.1f} KB"
    return f"{n} B"


def _lookup_capacity(device: str) -> Optional[Tuple[int, int]]:
    """Look up (flash_bytes, ram_bytes) for a Keil Device string."""
    try:
        from utils import load_chip_db
        db = load_chip_db()
    except Exception:
        return None
    for info in db.values():
        if info.get("device", "") == device:
            return (int(info["flash_size"], 16), int(info["ram_size"], 16))
    # Fallback: substring match
    for info in db.values():
        d = info.get("device", "")
        if d and (d in device or device in d):
            return (int(info["flash_size"], 16), int(info["ram_size"], 16))
    return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Compile a Keil project")
    parser.add_argument("--project", required=True, help="Path to .uvprojx file")
    parser.add_argument("--keil", default=None, help="Path to Keil UV4 directory")
    parser.add_argument("--timeout", type=int, default=300, help="Build timeout in seconds")
    parser.add_argument("--rebuild", action="store_true",
                        help="Full rebuild (-r). Default is incremental (-b, faster).")

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

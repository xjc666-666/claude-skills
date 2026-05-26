"""
Parse Keil compilation errors and auto-fix source code.

Supports ARMCC5 (#error_code) and ARMClang/ARMCC6 (clang-style) message formats.
Detects project family (F103/F407) from .uvprojx defines or chip_db and
selects the correct SPL header. Includes a --dry-run mode to preview edits.
"""
import os
import sys
import re
import json
import difflib
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import (
    BuildError, load_error_patterns, normalize_path, load_chip_db,
)


# ─── family-aware SPL header maps ─────────────────────────────────────

# Maps a peripheral identifier prefix (in either F1/F4 form) to header basename.
# Family resolution prepends "stm32f10x_" or "stm32f4xx_".
_PERIPH_HEADERS = {
    "gpio": "gpio",
    "usart": "usart",
    "tim": "tim",
    "spi": "spi",
    "i2c": "i2c",
    "adc": "adc",
    "dac": "dac",
    "dma": "dma",
    "exti": "exti",
    "rcc": "rcc",
    "pwr": "pwr",
    "iwdg": "iwdg",
    "wwdg": "wwdg",
    "rtc": "rtc",
    "can": "can",
    "flash": "flash",
    "sdio": "sdio",
}

# SPL type → peripheral mapping (no F1/F4 suffix yet)
_TYPE_TO_PERIPH = {
    "GPIO_InitTypeDef": "gpio",
    "USART_InitTypeDef": "usart",
    "USART_ClockInitTypeDef": "usart",
    "NVIC_InitTypeDef": "_misc",   # special: misc.h, no fxxx prefix
    "TIM_TimeBaseInitTypeDef": "tim",
    "TIM_OCInitTypeDef": "tim",
    "TIM_ICInitTypeDef": "tim",
    "TIM_BDTRInitTypeDef": "tim",
    "SPI_InitTypeDef": "spi",
    "I2C_InitTypeDef": "i2c",
    "ADC_InitTypeDef": "adc",
    "ADC_CommonInitTypeDef": "adc",
    "DAC_InitTypeDef": "dac",
    "DMA_InitTypeDef": "dma",
    "EXTI_InitTypeDef": "exti",
    "RCC_ClocksTypeDef": "rcc",
    "CAN_InitTypeDef": "can",
    "CAN_FilterInitTypeDef": "can",
    "RTC_InitTypeDef": "rtc",
    "RTC_TimeTypeDef": "rtc",
    "RTC_DateTypeDef": "rtc",
}


def _header_for_periph(periph: str, family: str) -> str:
    """Resolve peripheral key to a concrete SPL header file name."""
    if periph == "_misc":
        return "misc.h"
    prefix = "stm32f10x_" if family == "F103" else "stm32f4xx_"
    return f"{prefix}{periph}.h"


def detect_family(project_dir: str) -> str:
    """Best-effort family detection.

    Order: .uvprojx defines → chip lookup → directory heuristic → 'F407'.
    """
    proj_dir = os.path.join(project_dir, "Project")
    uvprojx = None
    if os.path.isdir(proj_dir):
        for f in os.listdir(proj_dir):
            if f.endswith(".uvprojx"):
                uvprojx = os.path.join(proj_dir, f)
                break

    if uvprojx and os.path.isfile(uvprojx):
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(uvprojx)
            for vc in tree.iter("VariousControls"):
                define = (vc.findtext("Define") or "").upper()
                if "STM32F10X" in define or "STM32F1" in define:
                    return "F103"
                if "STM32F40_41XXX" in define or "STM32F4" in define:
                    return "F407"
            for dev in tree.iter("Device"):
                t = (dev.text or "").upper()
                if "STM32F1" in t:
                    return "F103"
                if "STM32F4" in t:
                    return "F407"
        except Exception:
            pass

    # heuristic from filesystem
    for root, dirs, _ in os.walk(project_dir):
        joined = " ".join(dirs).lower()
        if "stm32f10x_stdperiph_driver" in joined or "stm32f10x" in joined:
            return "F103"
        if "stm32f4xx_stdperiph_driver" in joined or "stm32f4xx" in joined:
            return "F407"
        break

    return "F407"


@dataclass
class FixResult:
    """Result of an attempted fix."""
    error: BuildError
    fixed: bool
    description: str
    file_edits: List[Tuple[str, int, str, str]] = field(default_factory=list)
    # file_edits: list of (filepath, line_index, old_text_or_empty, new_text)
    # When old_text == "", new_text is treated as an #include directive to add.


@dataclass
class FixCycleResult:
    cycle: int
    errors_before: int
    errors_after: int
    fixes_applied: List[FixResult]
    success: bool
    message: str


def analyze_and_fix(
    errors: List[BuildError],
    project_dir: str,
    family: Optional[str] = None,
    verbose: bool = True,
) -> List[FixResult]:
    """
    Analyze build errors and generate fixes.

    Args:
        errors: List of BuildError from compilation
        project_dir: Root directory of the project
        family: "F103" or "F407"; auto-detected if None
        verbose: Print fix descriptions

    Returns:
        List of FixResult describing each fix attempt
    """
    if family is None:
        family = detect_family(project_dir)
    patterns = load_error_patterns()
    results = []

    for error in errors:
        fix = _try_fix_error(error, patterns, project_dir, family)
        if fix:
            if verbose and fix.fixed:
                print(f"  [FIXED] {fix.description}")
            elif verbose:
                print(f"  [UNFIXED] {error.code or '?'}: {error.message}")
            results.append(fix)

    return results


def _try_fix_error(
    error: BuildError,
    patterns: Dict,
    project_dir: str,
    family: str,
) -> Optional[FixResult]:
    """Try to fix a single build error."""
    msg = error.message

    # Pattern-based matching (works for both ARMCC5 with #code and ARMClang)
    for pat in patterns.get("patterns", []):
        regex = pat["regex"]
        match = re.search(regex, msg, re.IGNORECASE)
        if match:
            return _apply_fix_strategy(error, pat, match, project_dir, family)

    # ARMClang fallback: messages without a "#code:" prefix
    # e.g. "use of undeclared identifier 'GPIO_InitTypeDef'"
    m = re.search(r"use of undeclared identifier ['\"]([^'\"]+)['\"]", msg, re.IGNORECASE)
    if m:
        return _fix_undeclared_identifier(error, m, project_dir, family)
    m = re.search(r"unknown type name ['\"]([^'\"]+)['\"]", msg, re.IGNORECASE)
    if m:
        return _fix_undeclared_identifier(error, m, project_dir, family)
    m = re.search(r"implicit declaration of function ['\"]([^'\"]+)['\"]", msg, re.IGNORECASE)
    if m:
        return _fix_undeclared_function(error, m, project_dir, family)
    m = re.search(r"['\"]([^'\"]+\.h)['\"]\s+file not found", msg, re.IGNORECASE)
    if m:
        return _fix_missing_header(error, m, project_dir, family)
    m = re.search(r"expected ['\"]?;['\"]?\s+after", msg, re.IGNORECASE)
    if m:
        return _fix_expected_semicolon(error, None, project_dir, family)

    return FixResult(
        error=error,
        fixed=False,
        description=f"Cannot auto-fix: {msg}",
    )


def _apply_fix_strategy(error, pattern, match, project_dir, family):
    pattern_id = pattern["id"]
    dispatch = {
        "undeclared_identifier": _fix_undeclared_identifier,
        "missing_header": _fix_missing_header,
        "undeclared_function": _fix_undeclared_function,
        "expected_semicolon": _fix_expected_semicolon,
        "unused_variable": _fix_unused_variable,
        "undefined_symbol_linker": _fix_undefined_symbol,
        "not_a_member": _fix_not_a_member,
        "unknown_register": _fix_unknown_register,
        "missing_return": _fix_missing_return,
        "multiple_definition": _fix_multiple_definition,
        "too_few_arguments": _fix_too_few_args,
    }
    handler = dispatch.get(pattern_id)
    if handler:
        return handler(error, match, project_dir, family)

    return FixResult(
        error=error,
        fixed=False,
        description=f"Pattern '{pattern_id}' recognized but auto-fix not available."
    )


def _fix_undeclared_identifier(error, match, project_dir, family):
    identifier = match.group(1)

    # 1) Known SPL type → header (family-aware)
    if identifier in _TYPE_TO_PERIPH:
        periph = _TYPE_TO_PERIPH[identifier]
        header = _header_for_periph(periph, family)
        return FixResult(
            error=error,
            fixed=True,
            description=f"Adding #include \"{header}\" for {identifier} (family={family})",
            file_edits=[(error.file, 0, "", f'#include "{header}"')],
        )

    # 2) Peripheral macros like GPIO_PIN_5 / RCC_AHB1Periph_GPIOA
    pref_match = re.match(r"^(GPIO|USART|UART|TIM|SPI|I2C|ADC|DAC|DMA|EXTI|RCC|PWR|RTC|CAN|FLASH|SDIO|IWDG|WWDG)_", identifier, re.IGNORECASE)
    if pref_match:
        periph = pref_match.group(1).lower()
        if periph == "uart":
            periph = "usart"
        if periph in _PERIPH_HEADERS:
            header = _header_for_periph(periph, family)
            return FixResult(
                error=error,
                fixed=True,
                description=f"Adding #include \"{header}\" for {identifier} (family={family})",
                file_edits=[(error.file, 0, "", f'#include "{header}"')],
            )

    # 3) Search project headers
    found = _search_in_headers(identifier, project_dir)
    if found:
        return FixResult(
            error=error,
            fixed=True,
            description=f"Adding #include \"{found['header']}\" for {identifier}",
            file_edits=[(error.file, 0, "", f'#include "{found["header"]}"')],
        )

    return FixResult(error=error, fixed=False,
                     description=f"Cannot find declaration of '{identifier}'")


def _fix_missing_header(error, match, project_dir, family):
    header = match.group(1)
    found_path = _find_file_in_project(header, project_dir)
    if found_path:
        return FixResult(
            error=error,
            fixed=False,
            description=f"Header {header} exists at {found_path}; add its directory to IncludePath in .uvprojx",
        )
    return FixResult(error=error, fixed=False,
                     description=f"Cannot find {header} in project. Ensure SPL/HAL is complete.")


def _fix_undeclared_function(error, match, project_dir, family):
    func_name = match.group(1)

    # Match against family-aware SPL conventions: SPI_Init → spi
    m = re.match(r"^([A-Z]+\d*)_", func_name)
    if m:
        periph_raw = m.group(1).lower().rstrip("0123456789")
        # Some functions have numeric suffix in periph (USART1_Init)
        if periph_raw in _PERIPH_HEADERS:
            return FixResult(
                error=error,
                fixed=True,
                description=f"Adding #include \"{_header_for_periph(periph_raw, family)}\" for {func_name}",
                file_edits=[(error.file, 0, "", f'#include "{_header_for_periph(periph_raw, family)}"')],
            )

    found = _search_function_in_project(func_name, project_dir)
    if found:
        return FixResult(
            error=error,
            fixed=True,
            description=f"Adding #include \"{found['header']}\" for {func_name}",
            file_edits=[(error.file, 0, "", f'#include "{found["header"]}"')],
        )
    return FixResult(error=error, fixed=False,
                     description=f"Cannot find declaration of function '{func_name}'")


def _fix_expected_semicolon(error, match, project_dir, family):
    """Most compilers report 'expected ;' on the line AFTER the missing one
    (when the next token reveals the missing punctuation). Try both lines."""
    if not error.file:
        return FixResult(error=error, fixed=False, description="No source file referenced")

    abs_path = error.file if os.path.isabs(error.file) else os.path.join(project_dir, error.file)
    if not os.path.isfile(abs_path):
        return FixResult(error=error, fixed=False, description="Cannot locate source file")

    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    err_idx = error.line - 1
    # Compilers typically point to current line for ARMCC5, but ARMClang
    # often points to the next token (one line after). Try error line first,
    # then the previous one.
    for candidate in (err_idx, err_idx - 1):
        if not (0 <= candidate < len(lines)):
            continue
        line = lines[candidate].rstrip("\r\n")
        stripped = line.rstrip()
        if not stripped:
            continue
        if stripped.endswith((";", "{", "}", ",", "\\", ")", "(", ":")):
            continue
        if stripped.lstrip().startswith(("//", "#", "*", "/*")):
            continue
        # Add a semicolon
        new_line = stripped + ";\n"
        return FixResult(
            error=error,
            fixed=True,
            description=f"Adding missing semicolon at line {candidate + 1}",
            file_edits=[(abs_path, candidate, lines[candidate], new_line)],
        )

    return FixResult(error=error, fixed=False, description="Cannot determine exact syntax fix")


def _fix_unused_variable(error, match, project_dir, family):
    var_name = match.group(1)
    if not error.file:
        return FixResult(error=error, fixed=False, description="No source file referenced")

    abs_path = error.file if os.path.isabs(error.file) else os.path.join(project_dir, error.file)
    if not os.path.isfile(abs_path):
        return FixResult(error=error, fixed=False, description="Cannot locate source file")

    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    idx = error.line - 1
    if 0 <= idx < len(lines) and var_name in lines[idx]:
        old = lines[idx]
        new = f"// {old.rstrip()}  // [unused, auto-commented]\n"
        return FixResult(
            error=error,
            fixed=True,
            description=f"Commenting out unused variable '{var_name}'",
            file_edits=[(abs_path, idx, old, new)],
        )

    return FixResult(error=error, fixed=False, description=f"Cannot locate '{var_name}'")


def _fix_undefined_symbol(error, match, project_dir, family):
    symbol = match.group(1)

    # Derive SPL source filename from symbol
    m = re.match(r"^([A-Z]+\d*)_", symbol)
    if m:
        periph_raw = m.group(1).lower().rstrip("0123456789")
        if periph_raw in _PERIPH_HEADERS:
            prefix = "stm32f10x_" if family == "F103" else "stm32f4xx_"
            src_file = f"{prefix}{periph_raw}.c"
            found = _find_file_in_project(src_file, project_dir)
            if found:
                return FixResult(
                    error=error,
                    fixed=False,
                    description=f"{src_file} present at {found} but not added to Keil group. "
                                f"Run uvprojx_modifier.py add-group --group SPL with this file.",
                )
            return FixResult(
                error=error,
                fixed=False,
                description=f"Missing SPL source {src_file}. "
                            f"Copy from skeleton/{family.lower()}/STM32/... and add to project.",
            )
    if symbol.lower().startswith(("nvic_", "systick_")):
        found = _find_file_in_project("misc.c", project_dir)
        if found:
            return FixResult(error=error, fixed=False,
                             description=f"misc.c present at {found}, add to Keil group.")
        return FixResult(error=error, fixed=False,
                         description="Missing misc.c for NVIC/SysTick functions.")

    return FixResult(error=error, fixed=False,
                     description=f"Cannot resolve symbol '{symbol}'")


def _fix_not_a_member(error, match, project_dir, family):
    member = match.group(1) if match.lastindex and match.lastindex >= 1 else ""
    struct = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
    return FixResult(
        error=error,
        fixed=False,
        description=(f"'{member}' is not a member of '{struct}'. "
                     f"Likely chip-family mismatch (currently family={family}). "
                     f"Check the SPL header for the correct field name."),
    )


def _fix_unknown_register(error, match, project_dir, family):
    register = match.group(1)
    expected_define = ("STM32F10X_MD or STM32F10X_HD or STM32F10X_XL" if family == "F103"
                       else "STM32F40_41xxx")
    return FixResult(
        error=error,
        fixed=False,
        description=(f"Register/macro '{register}' undefined. "
                     f"Ensure {expected_define} is set in .uvprojx Define field."),
    )


def _fix_missing_return(error, match, project_dir, family):
    if not error.file:
        return FixResult(error=error, fixed=False, description="No source file referenced")
    abs_path = error.file if os.path.isabs(error.file) else os.path.join(project_dir, error.file)
    if not os.path.isfile(abs_path):
        return FixResult(error=error, fixed=False, description="Cannot locate source file")

    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    idx = error.line - 1
    for i in range(idx - 1, max(idx - 30, 0), -1):
        if re.search(r'\b(int|uint8_t|uint16_t|uint32_t|u8|u16|u32|float|double|char)\s+\w+\s*\(', lines[i]):
            return FixResult(
                error=error, fixed=True,
                description="Adding 'return 0;' before closing brace",
                file_edits=[(abs_path, idx - 1, lines[idx - 1], lines[idx - 1] + "    return 0;\n")],
            )
        if re.search(r'\bvoid\s+\w+\s*\(', lines[i]):
            return FixResult(
                error=error, fixed=True,
                description="Adding 'return;' before closing brace",
                file_edits=[(abs_path, idx - 1, lines[idx - 1], lines[idx - 1] + "    return;\n")],
            )
    return FixResult(error=error, fixed=False, description="Cannot determine return type")


def _fix_multiple_definition(error, match, project_dir, family):
    symbol = match.group(1)
    return FixResult(
        error=error, fixed=False,
        description=f"'{symbol}' defined multiple times. Add 'static' or move to a single .c file.",
    )


def _fix_too_few_args(error, match, project_dir, family):
    return FixResult(
        error=error, fixed=False,
        description="Too few arguments. Check the function declaration for required parameters.",
    )


# ─── apply edits ──────────────────────────────────────────────────────

def apply_fix_edits(fix_results: List[FixResult], project_dir: str,
                    dry_run: bool = False) -> Tuple[int, str]:
    """
    Apply file edits from fix results.

    When old_text == "", new_text is treated as an #include line and inserted
    at a sensible location (after the last existing #include / file-header
    comment), and only if the include is not already present.

    Returns (files_modified, unified_diff_text).
    """
    edits_per_file: Dict[str, List[Tuple[int, str, str]]] = {}
    for fix in fix_results:
        if not fix.fixed:
            continue
        for filepath, line_idx, old_text, new_text in fix.file_edits:
            if not filepath:
                continue
            if not os.path.isabs(filepath):
                filepath = os.path.join(project_dir, filepath)
            if not os.path.isfile(filepath):
                continue
            edits_per_file.setdefault(filepath, []).append((line_idx, old_text, new_text))

    modified = 0
    diff_parts: List[str] = []

    for filepath, edits in edits_per_file.items():
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            original = f.read()
        new_content = original

        # First handle include-insertion edits (old_text == "")
        include_edits = [(li, nt) for li, ot, nt in edits if ot == "" and nt.lstrip().startswith("#include")]
        replace_edits = [(li, ot, nt) for li, ot, nt in edits if not (ot == "" and nt.lstrip().startswith("#include"))]

        if include_edits:
            new_content = _insert_includes(new_content, [nt for _, nt in include_edits])

        # Then handle replacement edits
        for line_idx, old_text, new_text in replace_edits:
            if old_text and old_text in new_content:
                new_content = new_content.replace(old_text, new_text, 1)
            elif old_text == "" and new_text and not new_text.lstrip().startswith("#include"):
                # Append-at-top fallback (rarely used)
                new_content = new_text + "\n" + new_content

        if new_content != original:
            diff = "".join(difflib.unified_diff(
                original.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=filepath, tofile=filepath, n=2,
            ))
            diff_parts.append(diff)
            if not dry_run:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(new_content)
            modified += 1

    return modified, "\n".join(diff_parts)


_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+[<"]([^>"]+)[>"]', re.MULTILINE)


def _insert_includes(content: str, includes: List[str]) -> str:
    """Insert each #include line into content if not already present.

    Insertion point: just after the last existing #include in the file. If
    there is no existing #include, insert after the first block comment
    (the file-header doxygen comment) so the file header stays at the top."""
    existing = set(_INCLUDE_RE.findall(content))
    to_add = []
    for line in includes:
        m = _INCLUDE_RE.match(line)
        if not m:
            continue
        if m.group(1) in existing:
            continue
        to_add.append(line.strip())
        existing.add(m.group(1))

    if not to_add:
        return content

    # Find the position right after the last existing #include
    matches = list(_INCLUDE_RE.finditer(content))
    if matches:
        last = matches[-1]
        line_end = content.find("\n", last.end())
        if line_end < 0:
            line_end = len(content)
        insertion = "\n" + "\n".join(to_add)
        return content[:line_end] + insertion + content[line_end:]

    # No existing includes — place after first block comment if present
    bc = re.match(r'\s*/\*[\s\S]*?\*/\s*\n', content)
    if bc:
        end = bc.end()
        return content[:end] + "\n".join(to_add) + "\n\n" + content[end:]

    # Otherwise prepend at top
    return "\n".join(to_add) + "\n\n" + content


# ─── search helpers ───────────────────────────────────────────────────

def _search_in_headers(identifier: str, project_dir: str) -> Optional[Dict]:
    pat = re.compile(r'\b' + re.escape(identifier) + r'\b')
    for root, _, files in os.walk(project_dir):
        for fname in files:
            if fname.endswith((".h", ".hpp")):
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        if pat.search(f.read()):
                            return {"header": os.path.basename(fpath), "path": fpath}
                except Exception:
                    continue
    return None


def _search_function_in_project(func_name: str, project_dir: str) -> Optional[Dict]:
    pattern = re.compile(
        r'(?:extern\s+)?[\w\s\*]+\s+' + re.escape(func_name) + r'\s*\(',
    )
    for root, _, files in os.walk(project_dir):
        for fname in files:
            if fname.endswith((".h", ".hpp")):
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        if pattern.search(f.read()):
                            return {"header": os.path.basename(fpath), "path": fpath}
                except Exception:
                    continue
    return None


def _find_file_in_project(filename: str, project_dir: str) -> Optional[str]:
    basename = os.path.basename(filename)
    for root, _, files in os.walk(project_dir):
        for fname in files:
            if fname.lower() == basename.lower():
                return os.path.relpath(os.path.join(root, fname), project_dir)
    return None


# ─── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze and fix compilation errors")
    parser.add_argument("--errors", required=True, help="JSON array of BuildError objects")
    parser.add_argument("--project", required=True, help="Project root directory")
    parser.add_argument("--family", choices=["F103", "F407"], default=None,
                        help="Chip family (auto-detected if omitted)")
    parser.add_argument("--apply", action="store_true",
                        help="Write fixes to files (default: dry-run, prints diff only)")
    parser.add_argument("--verbose", action="store_true", default=True)

    args = parser.parse_args()

    errors_data = json.loads(args.errors)
    errors = [BuildError(**e) for e in errors_data]

    fixes = analyze_and_fix(errors, args.project, family=args.family, verbose=args.verbose)

    n, diff = apply_fix_edits(fixes, args.project, dry_run=not args.apply)

    if diff:
        print("\n=== Proposed edits (diff) ===")
        print(diff)

    fixed_count = sum(1 for f in fixes if f.fixed)
    mode = "applied" if args.apply else "previewed (use --apply to write)"
    print(f"\nFixed: {fixed_count}/{len(fixes)} errors; "
          f"{n} file(s) {mode}")
    for fix in fixes:
        status = "OK" if fix.fixed else "--"
        print(f"  [{status}] {fix.description}")

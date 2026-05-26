"""
Write/generate code for MSPM0G3519 projects.
- Copy BSP modules on demand
- Generate main.c
- Add printf redirect
- Generate ISR functions
"""
import os
import sys
import re
import shutil
import json
from pathlib import Path
from typing import Dict, List, Optional

SCRIPT_DIR = str(Path(__file__).resolve().parent)
SKILL_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)
from utils import normalize_path, load_bsp_index, load_hardware_pin_map
from uvprojx_modifier import add_group, read_config


def add_bsp_modules(project_dir: str, modules: List[str],
                    uvprojx_path: Optional[str] = None) -> Dict:
    """Copy BSP driver modules from references_bsp/ to project BSP/ on demand."""
    bsp_index = load_bsp_index()
    ref_bsp_dir = os.path.join(SKILL_DIR, "references", "EVM_TEST_OLED", "BSP")
    proj_bsp_dir = os.path.join(project_dir, "BSP")

    if not os.path.isdir(proj_bsp_dir):
        os.makedirs(proj_bsp_dir)

    if uvprojx_path is None:
        uvprojx_path = _find_uvprojx(project_dir)

    results = []
    for mod_name in modules:
        info = bsp_index.get(mod_name)
        if info is None:
            results.append({"module": mod_name, "status": "unknown", "error": "Module not in bsp_index"})
            continue

        bsp_name = info.get("bsp")
        if bsp_name is None:
            results.append({"module": mod_name, "status": "skipped", "reason": "No BSP files needed (syscfg-only)"})
            continue

        # Skip if driver is already in the skeleton template
        if info.get("in_template"):
            results.append({"module": mod_name, "status": "builtin",
                          "reason": f"Driver '{bsp_name}' is built into the skeleton template"})
            continue

        # Copy BSP files
        src_dir = os.path.join(ref_bsp_dir, bsp_name)
        dst_dir = os.path.join(proj_bsp_dir, bsp_name)

        if not os.path.isdir(src_dir):
            results.append({"module": mod_name, "status": "error", "error": f"Reference BSP not found: {src_dir}"})
            continue

        copied = []
        if os.path.isdir(dst_dir):
            existing = set(os.listdir(dst_dir))
        else:
            os.makedirs(dst_dir)
            existing = set()

        for item in os.listdir(src_dir):
            s = os.path.join(src_dir, item)
            d = os.path.join(dst_dir, item)
            if os.path.isfile(s):
                shutil.copy2(s, d)
                copied.append(item)

        # Update bsp.h
        bsp_h_path = os.path.join(proj_bsp_dir, "bsp.h")
        add_line = info.get("add_to_bsp_h")
        if add_line and os.path.isfile(bsp_h_path):
            _add_include_to_bsp_h(bsp_h_path, add_line)

        # Add .c files to .uvprojx BSP group
        if uvprojx_path and os.path.isfile(uvprojx_path):
            c_files = [f for f in copied if f.endswith(".c")]
            if c_files:
                file_entries = []
                for f in c_files:
                    file_entries.append({
                        "name": f,
                        "path": f"..\\\\BSP\\\\{bsp_name}\\\\{f}",
                        "type": "1"
                    })
                add_group(uvprojx_path, "BSP", file_entries)

        results.append({
            "module": mod_name,
            "status": "copied",
            "bsp": bsp_name,
            "files": copied,
            "init_call": info.get("init_call"),
        })

    return {"success": True, "results": results}


def generate_main_c(project_dir: str, requirements: Dict, request_desc: str = "") -> Dict:
    """Generate main.c based on user requirements.
    requirements: {"UART0": {"baud": 115200}, "OLED": {}, "GPIO_LED": {"pins": ["PA14"]}}
    """
    user_dir = os.path.join(project_dir, "User")
    main_c_path = os.path.join(user_dir, "main.c")
    if not os.path.isdir(user_dir):
        return {"success": False, "error": f"User directory not found: {user_dir}"}

    bsp_index = load_bsp_index()

    # Collect includes
    includes = ["#include \"ti_msp_dl_config.h\"", "#include \"bsp.h\""]
    # Collect init calls
    init_calls = ["    SYSCFG_DL_init();"]
    # Collect main loop logic
    loop_logic = []

    for periph_name, config in requirements.items():
        info = bsp_index.get(periph_name)
        if info is None:
            loop_logic.append(f"    // TODO: {periph_name} not found in bsp_index")
            continue

        init_call = info.get("init_call")
        if init_call:
            # Substitute parameters from config
            call = init_call
            for key, val in config.items():
                if not isinstance(val, (dict, list)):
                    call = call.replace(f"{{{key}}}", str(val))
            init_calls.append(f"    {call};")

        # Generate loop logic based on peripheral type
        if periph_name == "UART" or periph_name == "printf":
            loop_logic.append("    // UART echo / communication handled via interrupt")
            loop_logic.append("    // Send data with: printf(\"message\");")
        elif periph_name == "LED":
            loop_logic.append("    // LED toggle pattern")
            loop_logic.append("    // GPIO_toggle pin; delay_ms(500);")
        elif periph_name == "OLED":
            loop_logic.append("    OLED_ShowString(0, 0, (u8*)\"Hello MSPM0!\");")
        elif periph_name == "ADC":
            loop_logic.append("    // uint16_t adc_val = adc0_read_channel(0);")
        elif periph_name == "Keyboard":
            loop_logic.append("    // char key = get_keyboard_value();")

    # Build main.c content
    lines = []
    lines.append("/**")
    lines.append(" * @file    main.c")
    lines.append(" * @brief   MSPM0G3519 Application")
    lines.append(f" * @author  mspm0g3519 skill")
    lines.append(" */")
    lines.append("")
    for inc in includes:
        lines.append(inc)
    lines.append("")
    if request_desc:
        lines.append(f"// Request: {request_desc}")
        lines.append("")

    lines.append("int main(void)")
    lines.append("{")
    for call in init_calls:
        lines.append(call)
    lines.append("")

    if not loop_logic:
        loop_logic.append("    // Main application loop")
        loop_logic.append("    // TODO: Add your application logic here")
        loop_logic.append("    delay_ms(500);")

    lines.append("    while (1)")
    lines.append("    {")
    for logic in loop_logic:
        lines.append(f"    {logic}")
    lines.append("    }")
    lines.append("}")

    # Write the file
    with open(main_c_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return {
        "success": True,
        "main_c_path": normalize_path(main_c_path),
        "includes": includes,
        "init_calls": init_calls,
        "loop_logic": loop_logic,
    }


def add_printf_redirect(project_dir: str) -> Dict:
    """Add printf redirect through UART0 to the project's main.c or a separate file."""

    # Create printf_redirect.c in BSP
    printf_c_path = os.path.join(project_dir, "BSP", "printf_redirect.c")
    printf_h_path = os.path.join(project_dir, "BSP", "printf_redirect.h")

    printf_c_content = """/**
 * @file    printf_redirect.c
 * @brief   printf redirect to UART0 for MSPM0G3519
 */
#include "printf_redirect.h"
#include <ti/driverlib/dl_uart.h>
#include "ti_msp_dl_config.h"

int fputc(int ch, FILE *f)
{
    DL_UART_transmitDataBlocking(UART_0_INST, (uint8_t)ch);
    return ch;
}

int fputs(const char *str, FILE *f)
{
    while (*str) {
        fputc(*str++, f);
    }
    return 0;
}
"""

    printf_h_content = """/**
 * @file    printf_redirect.h
 * @brief   printf redirect declarations
 */
#ifndef __PRINTF_REDIRECT_H__
#define __PRINTF_REDIRECT_H__

#include <stdio.h>

#ifdef __cplusplus
extern "C" {
#endif

int fputc(int ch, FILE *f);
int fputs(const char *str, FILE *f);

#ifdef __cplusplus
}
#endif

#endif /* __PRINTF_REDIRECT_H__ */
"""

    with open(printf_c_path, "w", encoding="utf-8") as f:
        f.write(printf_c_content)
    with open(printf_h_path, "w", encoding="utf-8") as f:
        f.write(printf_h_content)

    # Update bsp.h
    bsp_h_path = os.path.join(project_dir, "BSP", "bsp.h")
    _add_include_to_bsp_h(bsp_h_path, '#include "printf_redirect.h"')

    # Add to .uvprojx
    uvprojx_path = _find_uvprojx(project_dir)
    if uvprojx_path:
        add_group(uvprojx_path, "BSP", [{
            "name": "printf_redirect.c",
            "path": "..\\\\BSP\\\\printf_redirect.c",
            "type": "1"
        }])

    return {
        "success": True,
        "printf_c": normalize_path(printf_c_path),
        "printf_h": normalize_path(printf_h_path),
    }


def generate_isr(project_dir: str, peripheral: str, interrupt_name: str,
                 handler_body: str = "") -> Dict:
    """Generate an ISR function for a peripheral and add it to main.c."""
    main_c_path = os.path.join(project_dir, "User", "main.c")
    if not os.path.isfile(main_c_path):
        return {"success": False, "error": "main.c not found"}

    with open(main_c_path, "r", encoding="utf-8") as f:
        content = f.read()

    isr_name = f"{peripheral}_INST_IRQHandler"

    if handler_body:
        body = handler_body
    else:
        body = f"""    switch (DL_{peripheral}_getPendingInterrupt({peripheral}_INST)) {{
        case DL_{peripheral}_IIDX_RX:
            // Handle RX interrupt
            break;
        default:
            break;
    }}"""

    isr_code = f"""
void {isr_name}(void)
{{
{body}
}}
"""

    # Append ISR before the last closing brace or end of file
    content = content.rstrip() + "\n" + isr_code

    with open(main_c_path, "w", encoding="utf-8") as f:
        f.write(content)

    return {
        "success": True,
        "isr_name": isr_name,
        "file": normalize_path(main_c_path),
    }


def _add_include_to_bsp_h(bsp_h_path: str, include_line: str) -> bool:
    """Add an #include line to bsp.h if not already present."""
    if not os.path.isfile(bsp_h_path):
        return False
    with open(bsp_h_path, "r", encoding="utf-8") as f:
        content = f.read()

    if include_line in content:
        return True  # Already present

    # Find last #include line and append after it
    lines = content.split("\n")
    last_include_idx = -1
    for i, line in enumerate(lines):
        if re.match(r'^\s*#include\s+', line):
            last_include_idx = i

    if last_include_idx >= 0:
        lines.insert(last_include_idx + 1, include_line)
    else:
        lines.insert(0, include_line)

    with open(bsp_h_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return True


def _find_uvprojx(project_dir: str) -> Optional[str]:
    """Find the .uvprojx file in a project directory."""
    for sub in [os.path.join(project_dir, "Project"), project_dir]:
        if os.path.isdir(sub):
            for f in os.listdir(sub):
                if f.endswith(".uvprojx"):
                    return os.path.join(sub, f)
    return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Write code for MSPM0G3519 projects")
    parser.add_argument("--project-dir", required=True, help="Project root directory")
    parser.add_argument("--add-bsp", default=None, help='JSON array of module names, e.g. ["UART0","LED"]')
    parser.add_argument("--gen-main", action="store_true", help="Generate main.c")
    parser.add_argument("--requirements", default="{}", help="JSON requirements for main.c")
    parser.add_argument("--request-desc", default="", help="Description of user request")
    parser.add_argument("--add-printf", action="store_true", help="Add printf redirect")
    parser.add_argument("--gen-isr", default=None, help='JSON: {"peripheral":"UART","interrupt":"RX"}')

    args = parser.parse_args()
    results = {}

    if args.add_bsp:
        modules = json.loads(args.add_bsp)
        results["add_bsp"] = add_bsp_modules(args.project_dir, modules)

    if args.gen_main:
        reqs = json.loads(args.requirements)
        results["gen_main"] = generate_main_c(args.project_dir, reqs, args.request_desc)

    if args.add_printf:
        results["add_printf"] = add_printf_redirect(args.project_dir)

    if args.gen_isr:
        isr_config = json.loads(args.gen_isr)
        results["gen_isr"] = generate_isr(
            args.project_dir,
            isr_config.get("peripheral", ""),
            isr_config.get("interrupt", ""),
            isr_config.get("body", ""),
        )

    print(json.dumps(results, indent=2, ensure_ascii=False))

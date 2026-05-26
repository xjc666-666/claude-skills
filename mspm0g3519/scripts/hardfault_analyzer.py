"""
Analyze Cortex-M0+ HardFault register dumps.
Resolves PC/LR to function symbols from .map file.
"""
import os
import sys
import re
import json
from pathlib import Path
from typing import Dict, List, Optional


def analyze_hardfault(registers: Dict, map_path: str) -> Dict:
    """Analyze HardFault register dump."""

    # Load .map file symbols
    symbols = _parse_map_file(map_path)
    if not symbols:
        return {"success": False, "error": f"Could not parse map file: {map_path}"}

    pc = int(registers.get("PC", "0"), 16) if isinstance(registers.get("PC"), str) else registers.get("PC", 0)
    lr = int(registers.get("LR", "0"), 16) if isinstance(registers.get("LR"), str) else registers.get("LR", 0)
    psr = int(registers.get("xPSR", "0"), 16) if isinstance(registers.get("xPSR"), str) else registers.get("xPSR", 0)
    cfsr = int(registers.get("CFSR", "0"), 16) if isinstance(registers.get("CFSR"), str) else registers.get("CFSR", 0)
    hfsr = int(registers.get("HFSR", "0"), 16) if isinstance(registers.get("HFSR"), str) else registers.get("HFSR", 0)

    pc_func = _resolve_symbol(symbols, pc)
    lr_func = _resolve_symbol(symbols, lr)

    # Cortex-M0+ diagnosis
    diagnosis = []
    forced = (hfsr >> 30) & 1  # FORCED bit
    vecttbl = (hfsr >> 1) & 1  # VECTTBL bit

    if vecttbl:
        diagnosis.append("VECTTBL: Vector table read error. Check if startup file is correct or if VTOR is set properly.")
    if forced:
        if cfsr & 0x01:
            diagnosis.append("IACCVIOL (Instruction access violation): PC may be pointing to invalid memory.")
        if cfsr & 0x02:
            diagnosis.append("DACCVIOL (Data access violation): Invalid memory access detected.")
        if cfsr & 0x0100:
            diagnosis.append("UNDEFINSTR (Undefined instruction): Executing data or corrupted instruction.")
        if cfsr & 0x0200:
            diagnosis.append("INVSTATE (Invalid state): Branch to non-thumb code address.")

        # Common patterns
        if pc == 0x00000000 or pc < 0x08000000:
            diagnosis.append("NULL pointer dereference: PC is at or near address 0.")
        if pc_func and "HardFault" in pc_func:
            diagnosis.append("Recursive HardFault: HardFault occurred inside HardFault Handler.")
        if psr & 0x1FF >= 0x100:
            diagnosis.append(f"Exception number in xPSR: {(psr & 0x1FF)}. Check ISR for nested exception.")

    if not diagnosis:
        diagnosis.append("Unknown fault cause. Check CFSR and HFSR register bits for more detail.")

    return {
        "success": True,
        "pc": f"0x{pc:08X}",
        "pc_function": pc_func,
        "pc_offset": f"0x{pc - symbols[pc_func]:X}" if pc_func and pc_func in symbols else "",
        "lr": f"0x{lr:08X}",
        "lr_function": lr_func,
        "psr": f"0x{psr:08X}",
        "cfsr": f"0x{cfsr:08X}",
        "hfsr": f"0x{hfsr:08X}",
        "forced": bool(forced),
        "vecttbl_error": bool(vecttbl),
        "diagnosis": diagnosis,
    }


def _parse_map_file(map_path: str) -> Dict[str, int]:
    """Parse Keil .map file and extract symbol -> address mapping."""
    if not os.path.isfile(map_path):
        return {}

    symbols = {}
    try:
        with open(map_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return {}

    # ARM linker .map format: address  size  type  name
    # 0x00001234  0x00000080  Code  RO  main.o(.text)
    # Also: entry points: symbol  0x00001234
    for line in content.split("\n"):
        # Match symbol table entries
        m = re.match(r'\s*(0x[0-9A-Fa-f]+)\s+\w+\s+(\w+)', line)
        if m:
            addr = int(m.group(1), 16)
            name = m.group(2)
            symbols[name] = addr

        # Match "section layout" items: symbol  0x00001234  ...
        m = re.match(r'\s+(\w+)\s+(0x[0-9A-Fa-f]+)\s+', line)
        if m and not m.group(1).startswith("0x"):
            addr = int(m.group(2), 16)
            symbols[m.group(1)] = addr

    return symbols


def _resolve_symbol(symbols: Dict[str, int], addr: int) -> Optional[str]:
    """Find the function containing the given address."""
    best_name = None
    best_addr = 0

    for name, sym_addr in symbols.items():
        if sym_addr <= addr and sym_addr > best_addr:
            best_name = name
            best_addr = sym_addr

    return best_name


def generate_hardfault_handler_c() -> str:
    """Generate MSPM0G3519 HardFault_Handler C code."""
    return '''void HardFault_Handler(void)
{
    register uint32_t r0 __asm("r0");
    register uint32_t r1 __asm("r1");
    register uint32_t r2 __asm("r2");
    register uint32_t r3 __asm("r3");
    register uint32_t r12 __asm("r12");
    register uint32_t lr __asm("lr");
    register uint32_t pc __asm("pc");
    register uint32_t psr __asm("xpsr");

    printf("HardFault\\r\\n");
    printf("R0=0x%08X R1=0x%08X R2=0x%08X R3=0x%08X\\r\\n", r0, r1, r2, r3);
    printf("R12=0x%08X LR=0x%08X PC=0x%08X xPSR=0x%08X\\r\\n", r12, lr, pc, psr);
    printf("CFSR=0x%08X HFSR=0x%08X\\r\\n",
           (unsigned)SCB->CFSR, (unsigned)SCB->HFSR);

    while (1);
}
'''


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MSPM0G3519 HardFault Analyzer")
    parser.add_argument("--registers", required=True, help='JSON: {"PC":"0x00001234","LR":"0x...","xPSR":"...","CFSR":"...","HFSR":"..."}')
    parser.add_argument("--map", required=True, help="Path to .map file")
    parser.add_argument("--gen-handler", action="store_true", help="Generate HardFault_Handler code")

    args = parser.parse_args()

    if args.gen_handler:
        print(generate_hardfault_handler_c())
    else:
        regs = json.loads(args.registers)
        result = analyze_hardfault(regs, args.map)
        print(json.dumps(result, indent=2, ensure_ascii=False))

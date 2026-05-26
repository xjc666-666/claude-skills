"""
Analyze STM32 HardFault exceptions using .map file and register dump.
"""
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, NamedTuple, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))


class SymbolEntry(NamedTuple):
    name: str
    address: int
    size: int


class HardFaultReport(NamedTuple):
    pc_address: str
    pc_symbol: Optional[str]
    pc_offset: int
    lr_address: str
    lr_symbol: Optional[str]
    fault_type: str
    fault_detail: str
    suggestions: List[str]
    call_stack: List[str]


def parse_map_file(map_path: str) -> Dict[int, SymbolEntry]:
    """
    Parse an ARMCC .map file to extract symbol→address mappings.
    Returns a dict keyed by address for binary search.
    """
    symbols: Dict[int, SymbolEntry] = {}

    if not os.path.isfile(map_path):
        raise FileNotFoundError(f"Map file not found: {map_path}")

    with open(map_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Match entries in the "Global Symbols" section
    # Format: "    symbol_name       0x08001234   Thumb Code     123  main.o(.text)"
    pattern = re.compile(
        r'^\s+(?P<name>\S+)\s+(?P<addr>0x[0-9A-Fa-f]+)\s+(?:Thumb Code|ARM Code|Data|Number)\s+\d+\s+(?P<obj>\S+)',
        re.MULTILINE
    )

    for m in pattern.finditer(content):
        name = m.group("name")
        addr = int(m.group("addr"), 16)

        # Skip compiler-generated symbols
        if name.startswith("__") or name.startswith("$"):
            continue

        if addr not in symbols or ".text" in m.group("obj"):
            size = _estimate_size(content, name, addr)
            symbols[addr] = SymbolEntry(name, addr, size)

    return symbols


def _estimate_size(content: str, name: str, addr: int) -> int:
    """Estimate function size from .map next symbol or cross-reference."""
    # Try to find the size from the cross-reference section
    # Format: "    main                                    0x080001c0   Thumb Code    86  main.o(.text)"
    pat = re.compile(
        rf'^\s+{re.escape(name)}\s+(0x[0-9A-Fa-f]+)\s+(?:Thumb Code|ARM Code)\s+(\d+)\s',
        re.MULTILINE
    )
    m = pat.search(content)
    if m:
        return int(m.group(2))
    return 0


def _find_symbol(symbols: Dict[int, SymbolEntry], address: int) -> Tuple[Optional[SymbolEntry], int]:
    """Binary search for the symbol containing the given address."""
    sorted_addrs = sorted(symbols.keys())
    if not sorted_addrs or address < sorted_addrs[0]:
        return None, 0

    for i in range(len(sorted_addrs) - 1):
        if sorted_addrs[i] <= address < sorted_addrs[i + 1]:
            sym = symbols[sorted_addrs[i]]
            return sym, address - sorted_addrs[i]

    # Check last entry
    last_addr = sorted_addrs[-1]
    sym = symbols[last_addr]
    if sym.size > 0 and address <= last_addr + sym.size:
        return sym, address - last_addr

    return None, 0


def _classify_fault(pc: int, lr: int, pc_sym: Optional[str]) -> Tuple[str, str, List[str]]:
    """Classify HardFault type based on PC, LR, and symbol context."""
    suggestions = ["检查 PC 指向的函数是否有越界、野指针或栈溢出的问题。"]

    if pc == 0:
        return ("NULL Pointer", "PC 为 0，函数指针为 NULL 时调用。", [
            "检查是否有未初始化的函数指针被调用。",
            "检查中断向量表是否正确，是否有未实现的中断处理函数。",
        ])
    if pc < 0x20000000:
        if pc < 0x08000100:
            return ("Boot/Vector Error", "PC 指向 Flash 低地址（向量表区域），可能是中断向量表或引导区问题。", [
                "检查 startup 文件和中断向量偏移 (SCB->VTOR)。",
                "检查 BOOT 引脚配置和 Flash 起始地址。",
            ])
        # Normal Flash range, continue to symbol lookup below
    if pc_sym is None:
        if 0x20000000 <= pc < 0x40000000:
            return ("Executing from RAM", "PC 在 SRAM 区域。代码可能跳转到了数据/缓冲区。", [
                "检查是否有缓冲区溢出导致返回地址被覆盖。",
                "检查函数指针是否指向了数据而非代码。",
            ])
        return ("Unknown Code", f"PC=0x{pc:08X} 不在 .map 文件任何已知符号中。", [
            "PC 值是否合理？确认寄存器值未被损坏。",
            "检查 .map 文件是否为同一次编译的产物。",
        ])

    # Known symbol in valid Flash — general fault with symbol info
    return _general_fault(pc, lr, pc_sym)


def _general_fault(pc: int, lr: int, pc_sym: str) -> Tuple[str, str, List[str]]:
    # Check LR for EXC_RETURN
    if (lr & 0xFF000000) == 0xFF000000:
        return ("Exception within Exception", "LR 是 EXC_RETURN 值，可能在中断处理函数中发生二次异常。", [
            "检查中断优先级分组 (NVIC_PriorityGroupConfig) 和抢占优先级。",
            "中断处理函数中是否调用了阻塞函数或访问了非位带区的外设寄存器？",
        ])

    return ("Bus/Usage/Memory Fault",
            f"PC 在 {pc_sym} 中，LR=0x{lr:08X}。具体子类型需要从 CFSR 寄存器读取。", [
                "读取 SCB->CFSR (Configurable Fault Status Register, 地址 0xE000ED28) 获取子故障类型：",
                "  CFSR[25:24]=1: 非对齐访问 (UNALIGNED)",
                "  CFSR[28:26]=1: 总线错误 (取指/数据/中断向量)",
                "  CFSR[18:16]=1: 用法错误 (未定义指令/除0/状态不符)",
                "  CFSR[0]=1: 存储器管理错误 (MPU 违规)",
                "建议在 HardFault_Handler 中打印 R0-R3,R12,LR,PC,xPSR 栈帧以获取完整上下文。",
            ])


def analyze_hardfault(
    map_path: str,
    pc: str,
    lr: str,
    r0: str = "0x00000000",
    r1: str = "0x00000000",
    r2: str = "0x00000000",
    r3: str = "0x00000000",
    r12: str = "0x00000000",
    xpsr: str = "0x00000000",
) -> HardFaultReport:
    """Analyze a HardFault from register values and .map file."""

    pc_val = int(pc, 16)
    lr_val = int(lr, 16) if lr and lr != "0x00000000" else 0

    symbols = parse_map_file(map_path)
    pc_sym, pc_off = _find_symbol(symbols, pc_val)
    lr_sym, _ = _find_symbol(symbols, lr_val) if lr_val else (None, 0)

    fault_type, fault_detail, suggestions = _classify_fault(pc_val, lr_val,
                                                              pc_sym.name if pc_sym else None)

    # Build call stack
    call_stack = []
    if pc_sym:
        call_stack.append(f"  --> {pc_sym.name}+{pc_off}  (0x{pc_val:08X})  [崩溃点]")
    else:
        call_stack.append(f"  --> ???  (0x{pc_val:08X})  [崩溃点 — 未在 .map 中找到]")
    if lr_sym and lr_val:
        call_stack.append(f"  <- {lr_sym.name}  (0x{lr_val:08X})  [返回地址]")
    elif lr_val:
        call_stack.append(f"  <- ???  (0x{lr_val:08X})  [返回地址 — 未在 .map 中找到]")

    return HardFaultReport(
        pc_address=f"0x{pc_val:08X}",
        pc_symbol=pc_sym.name if pc_sym else None,
        pc_offset=pc_off,
        lr_address=f"0x{lr_val:08X}" if lr_val else "N/A",
        lr_symbol=lr_sym.name if lr_sym else None,
        fault_type=fault_type,
        fault_detail=fault_detail,
        suggestions=suggestions,
        call_stack=call_stack,
    )


def format_report(report: HardFaultReport) -> str:
    """Format HardFault analysis as readable text."""
    lines = [
        "=" * 60,
        "  HardFault Analysis Report",
        "=" * 60,
        "",
        f"  Fault Type:  {report.fault_type}",
        f"  Detail:      {report.fault_detail}",
        "",
        "  Registers:",
        f"    PC  = {report.pc_address}  ({report.pc_symbol or '???'}+{report.pc_offset})",
        f"    LR  = {report.lr_address}  ({report.lr_symbol or '???'})",
        "",
        "  Call Stack (推测):",
    ]
    for cs in report.call_stack:
        lines.append(f"    {cs}")

    lines += ["", "  Suggestions:"]
    for s in report.suggestions:
        lines.append(f"    - {s}")

    lines += ["", "=" * 60]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze STM32 HardFault from .map and registers")
    parser.add_argument("--map", required=True, help="Path to .map file")
    parser.add_argument("--pc", required=True, help="Program Counter (hex)")
    parser.add_argument("--lr", default="0x00000000", help="Link Register (hex)")
    parser.add_argument("--r0", default="0x00000000"); parser.add_argument("--r1", default="0x00000000")
    parser.add_argument("--r2", default="0x00000000"); parser.add_argument("--r3", default="0x00000000")
    parser.add_argument("--r12", default="0x00000000"); parser.add_argument("--xpsr", default="0x00000000")
    args = parser.parse_args()

    report = analyze_hardfault(args.map, args.pc, args.lr,
                               args.r0, args.r1, args.r2, args.r3,
                               args.r12, args.xpsr)
    print(format_report(report))

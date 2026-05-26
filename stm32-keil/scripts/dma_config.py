"""
DMA configuration assistant for STM32.
Given a peripheral and direction, returns valid DMA controller/stream/channel options.
"""
import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))


class DMAOption(NamedTuple):
    dma_controller: int    # 1 or 2
    stream: Optional[int]  # 0-7 for F407, None for F103
    channel: int           # 0-7 (F407) or 1-7 (F103)
    peripheral: str
    direction: str


def load_dma_mapping(family: str) -> Dict:
    """Load DMA mapping database for a chip family."""
    data_dir = os.path.join(Path(__file__).resolve().parent.parent, "data")
    name = f"dma_mapping_{family.lower()}.json"
    path = os.path.join(data_dir, name)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"DMA mapping not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_dma_options(
    family: str,
    peripheral: str,
    direction: str = "any",
) -> List[DMAOption]:
    """
    Find all DMA controller/stream/channel options for a given peripheral.

    Args:
        family: "F103" or "F407"
        peripheral: e.g. "USART1_TX", "SPI1_RX", "ADC1"
        direction: "M2P" (memory→periph), "P2M" (periph→mem), or "any"

    Returns:
        List of DMAOption
    """
    db = load_dma_mapping(family)
    mappings = db.get("mappings", [])
    results = []

    for m in mappings:
        if family == "F407":
            if m["peripheral"].upper() == peripheral.upper():
                if direction == "any" or m.get("direction", "any") == direction:
                    results.append(DMAOption(
                        dma_controller=m["dma"],
                        stream=m["stream"],
                        channel=m["channel"],
                        peripheral=m["peripheral"],
                        direction=m.get("direction", "any"),
                    ))
        else:  # F103
            for p in m["peripherals"]:
                if p.upper() == peripheral.upper():
                    results.append(DMAOption(
                        dma_controller=m["dma"],
                        stream=None,
                        channel=m["channel"],
                        peripheral=p,
                        direction="any",  # F103 direction is implicit
                    ))

    return results


def generate_dma_init_code(
    family: str,
    option: DMAOption,
    src_addr: str = "(uint32_t)&periph_dr",
    dst_addr: str = "(uint32_t)&buffer",
    buf_size: int = 1,
) -> str:
    """Generate SPL DMA initialization code for the selected option."""
    if family == "F407":
        return _gen_dma_f407(option, src_addr, dst_addr, buf_size)
    else:
        return _gen_dma_f103(option, src_addr, dst_addr, buf_size)


def _gen_dma_f407(opt: DMAOption, src: str, dst: str, size: int) -> str:
    return f"""/**
  * @brief  DMA{opt.dma_controller} Stream{opt.stream} 初始化
  *         通道{opt.channel}, 外设: {opt.peripheral}
  */
void MYDMA_Config(void)
{{
    DMA_InitTypeDef DMA_InitStructure;

    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_DMA{opt.dma_controller}, ENABLE);

    DMA_DeInit(DMA{opt.dma_controller}_Stream{opt.stream});
    DMA_InitStructure.DMA_Channel = DMA_Channel_{opt.channel};
    DMA_InitStructure.DMA_PeripheralBaseAddr = {src};
    DMA_InitStructure.DMA_Memory0BaseAddr = {dst};
    DMA_InitStructure.DMA_DIR = DMA_DIR_{'MemoryToPeripheral' if opt.direction == 'M2P' else 'PeripheralToMemory'};
    DMA_InitStructure.DMA_BufferSize = {size};
    DMA_InitStructure.DMA_PeripheralInc = DMA_PeripheralInc_Disable;
    DMA_InitStructure.DMA_MemoryInc = DMA_MemoryInc_Enable;
    DMA_InitStructure.DMA_PeripheralDataSize = DMA_PeripheralDataSize_Byte;
    DMA_InitStructure.DMA_MemoryDataSize = DMA_MemoryDataSize_Byte;
    DMA_InitStructure.DMA_Mode = DMA_Mode_Normal;
    DMA_InitStructure.DMA_Priority = DMA_Priority_High;
    DMA_InitStructure.DMA_FIFOMode = DMA_FIFOMode_Disable;
    DMA_Init(DMA{opt.dma_controller}_Stream{opt.stream}, &DMA_InitStructure);
}}
"""


def _gen_dma_f103(opt: DMAOption, src: str, dst: str, size: int) -> str:
    return f"""/**
  * @brief  DMA{opt.dma_controller} Channel{opt.channel} 初始化
  *         外设: {opt.peripheral}
  */
void MYDMA_Config(void)
{{
    DMA_InitTypeDef DMA_InitStructure;

    RCC_AHBPeriphClockCmd(RCC_AHBPeriph_DMA{opt.dma_controller}, ENABLE);

    DMA_DeInit(DMA{opt.dma_controller}_Channel{opt.channel});
    DMA_InitStructure.DMA_PeripheralBaseAddr = {src};
    DMA_InitStructure.DMA_MemoryBaseAddr = {dst};
    DMA_InitStructure.DMA_DIR = DMA_DIR_PeripheralSRC;
    DMA_InitStructure.DMA_BufferSize = {size};
    DMA_InitStructure.DMA_PeripheralInc = DMA_PeripheralInc_Disable;
    DMA_InitStructure.DMA_MemoryInc = DMA_MemoryInc_Enable;
    DMA_InitStructure.DMA_PeripheralDataSize = DMA_PeripheralDataSize_Byte;
    DMA_InitStructure.DMA_MemoryDataSize = DMA_MemoryDataSize_Byte;
    DMA_InitStructure.DMA_Mode = DMA_Mode_Normal;
    DMA_InitStructure.DMA_Priority = DMA_Priority_High;
    DMA_InitStructure.DMA_M2M = DMA_M2M_Disable;
    DMA_Init(DMA{opt.dma_controller}_Channel{opt.channel}, &DMA_InitStructure);
}}
"""


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Find DMA channels for a peripheral")
    parser.add_argument("--family", required=True, choices=["F103", "F407"],
                        help="Chip family")
    parser.add_argument("--peripheral", required=True,
                        help="Peripheral name (e.g., USART1_TX, SPI1_RX)")
    parser.add_argument("--direction", default="any", choices=["M2P", "P2M", "any"],
                        help="Transfer direction")
    parser.add_argument("--generate", action="store_true",
                        help="Generate init code for the first matching option")
    args = parser.parse_args()

    options = get_dma_options(args.family, args.peripheral, args.direction)

    if not options:
        print(f"No DMA mapping found for {args.peripheral} on {args.family}")
        sys.exit(1)

    print(f"DMA options for {args.peripheral} ({args.family}):")
    for opt in options:
        stream_str = f"Stream{opt.stream}" if opt.stream is not None else f"Ch{opt.channel}"
        print(f"  DMA{opt.dma_controller} {stream_str} Channel{opt.channel}"
              f"  [{opt.direction}]")

    if args.generate and options:
        code = generate_dma_init_code(args.family, options[0])
        print("\n// Generated init code:")
        print(code)

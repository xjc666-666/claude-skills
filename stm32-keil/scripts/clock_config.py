"""
STM32 clock tree configurator.
Calculates PLL/AHB/APB prescalers and generates SPL init code.
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))


class ClockConfig(NamedTuple):
    family: str
    hse_hz: int
    sysclk_hz: int
    pll_m: int         # F407 only
    pll_n: int
    pll_p: int           # F407: 2/4/6/8; F103: PLL multiplier directly
    pll_q: int           # F407 only (48MHz for USB)
    hclk_prescaler: int  # AHB divider (1,2,4,8,16...512)
    pclk1_prescaler: int # APB1 divider
    pclk2_prescaler: int # APB2 divider
    hclk_hz: int
    pclk1_hz: int
    pclk2_hz: int
    warnings: List[str]
    init_code: str
    diagram: str


# Hardware constraints
_CONSTRAINTS = {
    "F407": {
        "sysclk_max": 168_000_000,
        "pclk1_max": 42_000_000,
        "pclk2_max": 84_000_000,
        "pll_vco_in_min": 1_000_000,
        "pll_vco_in_max": 2_000_000,
        "pll_vco_out_min": 192_000_000,
        "pll_vco_out_max": 432_000_000,
        "pll_m_range": range(2, 64),
        "pll_n_range": range(192, 433),
        "pll_p_options": [2, 4, 6, 8],
        "pll_q_options": range(2, 16),
        "usb_clk": 48_000_000,
    },
    "F103": {
        "sysclk_max": 72_000_000,
        "pclk1_max": 36_000_000,
        "pclk2_max": 72_000_000,
        "pll_mul_range": range(2, 17),
        "pll_in_min": 4_000_000,
        "pll_in_max": 16_000_000,
        "hse_prediv_options": [1, 2],
    },
}

_AHB_PRESCALERS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512]
_APB_PRESCALERS = [1, 2, 4, 8, 16]


def calculate(family: str, hse_hz: int = 0, target_sysclk: int = 0) -> ClockConfig:
    """Calculate optimal clock tree configuration."""
    c = _CONSTRAINTS[family]
    warnings = []

    if family == "F407":
        # Default values
        hse = hse_hz or 25_000_000
        target = target_sysclk or 168_000_000

        best = None
        best_err = float("inf")

        for m in c["pll_m_range"]:
            vco_in = hse // m
            if not (c["pll_vco_in_min"] <= vco_in <= c["pll_vco_in_max"]):
                continue
            for n in c["pll_n_range"]:
                vco_out = vco_in * n
                if not (c["pll_vco_out_min"] <= vco_out <= c["pll_vco_out_max"]):
                    continue
                for p in c["pll_p_options"]:
                    pll_out = vco_out // p
                    if pll_out > c["sysclk_max"]:
                        continue
                    err = abs(pll_out - target)
                    if err < best_err:
                        best_err = err
                        best = (m, n, p, pll_out)

        if best is None:
            raise ValueError("No valid PLL configuration found")
        m, n, p, pll_out = best

        # PLL_Q for USB 48MHz
        q = None
        for qq in c["pll_q_options"]:
            q_out = n * hse // m // qq
            if q_out == c["usb_clk"]:
                q = qq
                break
        if q is None:
            q = 0
            warnings.append(f"USB 48MHz clock not achievable with PLL_N={n}")

        # AHB/APB prescalers
        hclk_div = _find_prescaler(pll_out, pll_out, _AHB_PRESCALERS)
        hclk = pll_out // hclk_div
        pclk2_max = min(hclk, c["pclk2_max"])
        pclk2_div = _find_prescaler(hclk, pclk2_max, _APB_PRESCALERS)
        pclk2 = hclk // pclk2_div
        pclk1_max = min(hclk, c["pclk1_max"])
        pclk1_div = _find_prescaler(hclk, pclk1_max, _APB_PRESCALERS)
        pclk1 = hclk // pclk1_div

        if pll_out != target:
            warnings.append(f"Actual SYSCLK={pll_out} Hz (target={target} Hz, error={pll_out - target:+d} Hz)")

        init_code = _gen_code_f407(hse, m, n, p, q, hclk_div, pclk1_div, pclk2_div)
        diagram = _gen_diagram_f407(hse, m, n, p, q, pll_out, hclk, pclk1, pclk2, hclk_div, pclk1_div, pclk2_div)

        return ClockConfig(family="F407", hse_hz=hse, sysclk_hz=pll_out,
                          pll_m=m, pll_n=n, pll_p=p, pll_q=q,
                          hclk_prescaler=hclk_div, pclk1_prescaler=pclk1_div, pclk2_prescaler=pclk2_div,
                          hclk_hz=hclk, pclk1_hz=pclk1, pclk2_hz=pclk2, warnings=warnings,
                          init_code=init_code, diagram=diagram)

    else:  # F103
        hse = hse_hz or 8_000_000
        target = target_sysclk or 72_000_000

        best = None
        best_err = float("inf")
        for prediv in c["hse_prediv_options"]:
            pll_in = hse // prediv
            if not (c["pll_in_min"] <= pll_in <= c["pll_in_max"]):
                continue
            for mul in c["pll_mul_range"]:
                pll_out = pll_in * mul
                if pll_out > c["sysclk_max"]:
                    continue
                err = abs(pll_out - target)
                if err < best_err:
                    best_err = err
                    best = (prediv, mul, pll_out)
        if best is None:
            raise ValueError("No valid PLL configuration found")
        prediv, mul, pll_out = best

        hclk_div = _find_prescaler(pll_out, pll_out, _AHB_PRESCALERS)
        hclk = pll_out // hclk_div
        pclk2_max = min(hclk, c["pclk2_max"])
        pclk2_div = _find_prescaler(hclk, pclk2_max, _APB_PRESCALERS)
        pclk2 = hclk // pclk2_div
        pclk1_max = min(hclk, c["pclk1_max"])
        pclk1_div = _find_prescaler(hclk, pclk1_max, _APB_PRESCALERS)
        pclk1 = hclk // pclk1_div

        if pll_out != target:
            warnings.append(f"Actual SYSCLK={pll_out} Hz (target={target} Hz)")

        init_code = _gen_code_f103(hse, prediv, mul, hclk_div, pclk1_div, pclk2_div)
        diagram = _gen_diagram_f103(hse, prediv, mul, pll_out, hclk, pclk1, pclk2, hclk_div, pclk1_div, pclk2_div)

        return ClockConfig(family="F103", hse_hz=hse, sysclk_hz=pll_out,
                          pll_m=0, pll_n=mul, pll_p=prediv, pll_q=0,
                          hclk_prescaler=hclk_div, pclk1_prescaler=pclk1_div, pclk2_prescaler=pclk2_div,
                          hclk_hz=hclk, pclk1_hz=pclk1, pclk2_hz=pclk2, warnings=warnings,
                          init_code=init_code, diagram=diagram)


def _find_prescaler(sysclk: int, target_max: int, options: List[int]) -> int:
    best = 1
    for div in options:
        if sysclk // div <= target_max:
            best = div
            break
    return best


def _gen_code_f407(hse, m, n, p, q, hclk_div, pclk1_div, pclk2_div):
    hdiv = f"RCC_SYSCLK_Div{hclk_div}" if hclk_div > 1 else "RCC_SYSCLK_Div1"
    p1div = f"RCC_HCLK_Div{pclk1_div}" if pclk1_div > 1 else "RCC_HCLK_Div1"
    p2div = f"RCC_HCLK_Div{pclk2_div}" if pclk2_div > 1 else "RCC_HCLK_Div1"
    pcfg = f"RCC_PLLP_{p}" if p in (2, 4, 6, 8) else "RCC_PLLP_2"
    qcfg = f"RCC_PLLQ_{q}" if q else "0"
    return f"""/**
  * @brief  系统时钟初始化
  *         HSE={hse} → PLL(/{m}, ×{n}, /{p}) → {hse // m * n // p} Hz
  */
void Clock_Init(void)
{{
    RCC_DeInit();

    /* HSE */
    RCC_HSEConfig(RCC_HSE_ON);
    while (RCC_WaitForHSEStartUp() == ERROR);

    /* PLL: HSE / PLL_M(={m}) * PLL_N(={n}) / PLL_P(={p}) = {hse // m * n // p} Hz */
    RCC_PLLConfig(RCC_PLLSource_HSE, {m}, {n}, {pcfg}, {qcfg});
    RCC_PLLCmd(ENABLE);
    while (RCC_GetFlagStatus(RCC_FLAG_PLLRDY) == RESET);

    /* SYSCLK = PLL */
    RCC_SYSCLKConfig(RCC_SYSCLKSource_PLLCLK);

    /* AHB={hclk_div}, APB1={pclk1_div}, APB2={pclk2_div} */
    RCC_HCLKConfig({hdiv});
    RCC_PCLK1Config({p1div});
    RCC_PCLK2Config({p2div});

    SystemCoreClockUpdate();
}}
"""


def _gen_code_f103(hse, prediv, mul, hclk_div, pclk1_div, pclk2_div):
    hdiv_s = f"RCC_SYSCLK_Div{hclk_div}" if hclk_div > 1 else "RCC_SYSCLK_Div1"
    p1div_s = f"RCC_HCLK_Div{pclk1_div}" if pclk1_div > 1 else "RCC_HCLK_Div1"
    p2div_s = f"RCC_HCLK_Div{pclk2_div}" if pclk2_div > 1 else "RCC_HCLK_Div1"
    prediv_cfg = "RCC_HSEPrediv_Div1" if prediv == 1 else "RCC_HSEPrediv_Div2"
    mul_cfg = f"RCC_PLLMul_{mul}"
    return f"""/**
  * @brief  系统时钟初始化
  *         HSE={hse} /{prediv} ×{mul} → {hse // prediv * mul} Hz
  */
void Clock_Init(void)
{{
    RCC_DeInit();

    /* HSE */
    RCC_HSEConfig(RCC_HSE_ON);
    while (RCC_WaitForHSEStartUp() == ERROR);

    /* HSE /{prediv} */
    RCC_HSEPredivCmd({prediv_cfg});

    /* PLL: HSE/{prediv} × {mul} = {hse // prediv * mul} Hz */
    RCC_PLLConfig(RCC_PLLSource_HSE_Div{prediv}, {mul_cfg});
    RCC_PLLCmd(ENABLE);
    while (RCC_GetFlagStatus(RCC_FLAG_PLLRDY) == RESET);

    /* Flash latency and clock config */
    FLASH_PrefetchBufferCmd(ENABLE);
    FLASH_SetLatency(FLASH_Latency_2);

    /* SYSCLK = PLL, AHB={hclk_div}, APB1={pclk1_div}, APB2={pclk2_div} */
    RCC_SYSCLKConfig(RCC_SYSCLKSource_PLLCLK);
    RCC_HCLKConfig({hdiv_s});
    RCC_PCLK1Config({p1div_s});
    RCC_PCLK2Config({p2div_s});

    SystemCoreClockUpdate();
}}
"""


# ASCII tree diagram generation (simplified)
def _gen_diagram_f407(hse, m, n, p, q, sysclk, hclk, pclk1, pclk2, hdiv, p1div, p2div):
    vco = hse // m * n
    return f"""HSE {hse//1000000} MHz
  |
  +-- PLL_M (/ {m}) --> {hse//m//1000000} MHz
        |
        +-- PLL_N (x {n}) --> VCO={vco//1000000} MHz
              |
              +-- PLL_P (/ {p}) --> SYSCLK={sysclk//1000000} MHz
              |     |
              |     +-- AHB (/ {hdiv}) --> HCLK={hclk//1000000} MHz
              |           |
              |           +-- APB1 (/ {p1div}) --> PCLK1={pclk1//1000000} MHz (max 42)
              |           |
              |           +-- APB2 (/ {p2div}) --> PCLK2={pclk2//1000000} MHz (max 84)
              |
              +-- PLL_Q (/ {q}) --> 48 MHz (USB/SDIO)"""


def _gen_diagram_f103(hse, prediv, mul, sysclk, hclk, pclk1, pclk2, hdiv, p1div, p2div):
    return f"""HSE {hse//1000000} MHz
  |
  +-- HSEPrediv (/ {prediv}) --> {hse//prediv//1000000} MHz
        |
        +-- PLLMUL (x {mul}) --> SYSCLK={sysclk//1000000} MHz
              |
              +-- AHB (/ {hdiv}) --> HCLK={hclk//1000000} MHz
                    |
                    +-- APB1 (/ {p1div}) --> PCLK1={pclk1//1000000} MHz (max 36)
                    |
                    +-- APB2 (/ {p2div}) --> PCLK2={pclk2//1000000} MHz (max 72)"""


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Calculate STM32 clock tree configuration")
    parser.add_argument("--family", required=True, choices=["F103", "F407"],
                        help="Chip family")
    parser.add_argument("--hse", type=int, default=0,
                        help="HSE frequency in Hz (default: 8MHz F103, 25MHz F407)")
    parser.add_argument("--target", type=int, default=0,
                        help="Target SYSCLK in Hz (default: max for family)")
    parser.add_argument("--diagram", action="store_true", help="Print clock tree diagram")
    parser.add_argument("--code", action="store_true", help="Print initialization code")
    args = parser.parse_args()

    cfg = calculate(args.family, args.hse, args.target)

    print(f"Family: {cfg.family}")
    print(f"SYSCLK: {cfg.sysclk_hz // 1000000} MHz (HCLK: {cfg.hclk_hz // 1000000} MHz)")
    print(f"PCLK1:  {cfg.pclk1_hz // 1000000} MHz")
    print(f"PCLK2:  {cfg.pclk2_hz // 1000000} MHz")

    if args.diagram:
        print("\n" + cfg.diagram)

    if args.code:
        print("\n" + cfg.init_code)

    if cfg.warnings:
        print("\nWarnings:")
        for w in cfg.warnings:
            print(f"  - {w}")

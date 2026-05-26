"""
Search example projects for peripheral initialization code patterns.
"""
import os
import re
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import (
    extract_functions_from_c, extract_includes_from_c,
    extract_defines_from_h, normalize_path
)


# Peripheral type keywords for detection
PERIPHERAL_KEYWORDS = {
    "GPIO": ["gpio", "config_gpio", "set_gpio", "gpio_init", "paout", "pain"],
    "USART": ["usart", "uart", "serial", "sendbyte", "printf", "fputc"],
    "TIM": ["timer", "tim_", "timing", "pwm", "oc_init", "ic_init"],
    "SPI": ["spi", "spi_init"],
    "I2C": ["i2c", "i2c_init", "i2c_software"],
    "ADC": ["adc", "adc_init", "get_adc"],
    "DAC": ["dac", "dac_init", "set_dac"],
    "DMA": ["dma", "dma_init", "dma_config"],
    "EXTI": ["exti", "exti_init", "interrupt"],
    "RCC": ["rcc", "clock", "hse", "hsi", "pll"],
    "NVIC": ["nvic", "nvic_init", "priority"],
    "SysTick": ["systick", "delay_init", "delay_ms", "delay_us"],
    "LED": ["led", "led_init", "led_on", "led_off", "led_toggle"],
    "KEY": ["key", "key_init", "button", "keyboard"],
    "OLED": ["oled", "oled_init", "display"],
    "PLL": ["pll", "pll_init", "frequency"],
    "DDS": ["ad995", "ad983", "dds"],
    "Flash": ["flash", "flash_init", "erase"],
    "RTC": ["rtc", "rtc_init"],
    "WWDG": ["wwdg", "iwdg", "watchdog"],
    "FSMC": ["fsmc", "fmc"],
    "SDIO": ["sdio", "sd_init"],
    "CAN": ["can", "can_init"],
}


def search_examples(
    examples_dir: str,
    peripheral: str,
    family: Optional[str] = None,
    max_results: int = 5,
    cross_family: bool = True,
) -> List[Dict]:
    """
    Search example projects for code related to a peripheral.

    Args:
        examples_dir: Path to examples/ directory
        peripheral: Peripheral name (e.g., "GPIO", "USART", "TIM")
        family: Optional chip family filter ("F103" or "F407")
        max_results: Maximum number of results to return
        cross_family: If True, include cross-family results (marked with cross_family=True)

    Returns:
        List of search results, each containing init_code, header_includes, etc.
    """
    if not os.path.isdir(examples_dir):
        return []

    keywords = PERIPHERAL_KEYWORDS.get(peripheral.upper(), [peripheral.lower()])
    match_results = []    # Same family
    cross_results = []    # Different family

    # Walk through examples directory
    for root, _, files in os.walk(examples_dir):
        for fname in files:
            if not fname.endswith(".c") and not fname.endswith(".h"):
                continue

            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().lower()
            except Exception:
                continue

            # Check if this file is relevant
            score = 0
            for kw in keywords:
                score += content.count(kw.lower())

            if score == 0:
                continue

            # Extract relevant functions
            functions = extract_functions_from_c(fpath)
            relevant_funcs = []
            for func in functions:
                func_lower = func["name"].lower()
                if any(kw in func_lower for kw in keywords):
                    relevant_funcs.append(func)

            if not relevant_funcs and score < 2:
                continue

            # Build result
            includes = extract_includes_from_c(fpath)
            rel_path = os.path.relpath(fpath, examples_dir)

            # Try to determine chip family from the path or content
            file_family = _detect_family(fpath, content)
            is_cross = family and file_family and family.upper() != file_family.upper()

            result = {
                "source_file": rel_path,
                "peripheral": peripheral,
                "family": file_family or "unknown",
                "header_includes": includes,
                "init_functions": [
                    {
                        "name": f["name"],
                        "return_type": f["return_type"],
                        "params": f["params"],
                        "body": f["body"][:2000],
                    }
                    for f in relevant_funcs
                ],
                "score": score,
            }

            if is_cross:
                result["cross_family"] = True
                cross_results.append(result)
            else:
                match_results.append(result)

    # Sort by relevance score
    match_results.sort(key=lambda r: r["score"], reverse=True)
    cross_results.sort(key=lambda r: r["score"], reverse=True)

    # Interleave: top same-family first, then top cross-family
    combined = []
    same_limit = max_results // 2 + max_results % 2
    cross_limit = max_results // 2
    combined.extend(match_results[:same_limit])
    combined.extend(cross_results[:cross_limit])

    # Fill remaining slots from whichever has more
    remaining = max_results - len(combined)
    if remaining > 0:
        rest = match_results[same_limit:] + cross_results[cross_limit:]
        rest.sort(key=lambda r: r["score"], reverse=True)
        combined.extend(rest[:remaining])

    return combined[:max_results]


def search_by_requirement(
    examples_dir: str,
    requirement: str,
    family: Optional[str] = None,
) -> List[Dict]:
    """
    Search examples for code matching a free-text requirement.
    Extracts keywords from the requirement and searches accordingly.

    Args:
        examples_dir: Path to examples directory
        requirement: Free-text requirement (e.g., "用USART1发送数据到电脑")
        family: Optional chip family filter

    Returns:
        Combined search results across matched peripherals
    """
    requirement_lower = requirement.lower()

    matched_peripherals = []
    for periph, keywords in PERIPHERAL_KEYWORDS.items():
        for kw in keywords:
            if kw in requirement_lower:
                matched_peripherals.append(periph)
                break

    if not matched_peripherals:
        return []

    all_results = []
    for periph in matched_peripherals:
        results = search_examples(examples_dir, periph, family, max_results=2)
        all_results.extend(results)

    return all_results


def _detect_family(filepath: str, content_lower: str) -> Optional[str]:
    """Detect chip family from file path or content."""
    path_lower = filepath.lower()
    if "f103" in path_lower or "stm32f10x" in path_lower:
        return "F103"
    if "f407" in path_lower or "stm32f4xx" in path_lower or "stm32f40" in path_lower:
        return "F407"

    if "stm32f10x" in content_lower:
        return "F103"
    if "stm32f4xx" in content_lower:
        return "F407"

    return None


def index_examples(examples_dir: str) -> Dict:
    """
    Build a full index of all example projects for fast lookup.

    Returns:
        Index dict: {peripheral: {family: [file_list]}}
    """
    if not os.path.isdir(examples_dir):
        return {}

    index = {}

    for periph, keywords in PERIPHERAL_KEYWORDS.items():
        index[periph] = {"F103": [], "F407": [], "unknown": []}

        for root, _, files in os.walk(examples_dir):
            for fname in files:
                if not fname.endswith((".c", ".h")):
                    continue

                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read().lower()
                except Exception:
                    continue

                score = sum(content.count(kw) for kw in keywords)
                if score > 1:
                    rel = os.path.relpath(fpath, examples_dir)
                    family = _detect_family(fpath, content) or "unknown"
                    index[periph][family].append({
                        "file": rel,
                        "score": score,
                    })

        # Sort by score
        for fam in index[periph]:
            index[periph][fam].sort(key=lambda x: x["score"], reverse=True)

    return index


def get_init_template(peripheral: str, family: str) -> Dict:
    """
    Get a standard initialization template for a peripheral.
    Provides fallback templates when examples are not available.

    Returns template dict with init_code, header_includes, init_call, etc.
    """
    templates = _get_builtin_templates()
    key = f"{peripheral.upper()}_{family.upper()}"
    if key in templates:
        return templates[key]
    if peripheral.upper() in templates:
        return templates[peripheral.upper()]
    return {
        "init_code": "",
        "header_includes": [],
        "init_call": "",
        "global_vars": "",
        "interrupt_handlers": "",
    }


def _get_builtin_templates() -> Dict:
    """Built-in initialization templates for common peripherals."""
    return {
        "GPIO_F407": {
            "header_includes": ["GPIO.h", "stm32f4xx.h"],
            "init_call": "Config_GPIO(GPIOx, GPIO_Pin_x, GPIO_MODE_OUTPUT);",
            "init_code": """void Config_GPIO(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin, GPIO_Mode_TypeDef Mode)
{
    GPIO_InitTypeDef GPIO_InitStructure;

    /* 使能GPIO时钟 */
    if (GPIOx == GPIOA) RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOA, ENABLE);
    else if (GPIOx == GPIOB) RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOB, ENABLE);
    else if (GPIOx == GPIOC) RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOC, ENABLE);
    else if (GPIOx == GPIOD) RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOD, ENABLE);
    else if (GPIOx == GPIOE) RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOE, ENABLE);
    else if (GPIOx == GPIOF) RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOF, ENABLE);
    else if (GPIOx == GPIOG) RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOG, ENABLE);

    GPIO_InitStructure.GPIO_Pin = GPIO_Pin;
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_InitStructure.GPIO_OType = GPIO_OType_PP;
    GPIO_InitStructure.GPIO_PuPd = GPIO_PuPd_UP;

    if (Mode == GPIO_MODE_OUTPUT)
        GPIO_InitStructure.GPIO_Mode = GPIO_Mode_OUT;
    else
        GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IN;

    GPIO_Init(GPIOx, &GPIO_InitStructure);
}""",
            "global_vars": "",
            "interrupt_handlers": "",
        },

        "USART_F407": {
            "header_includes": ["USART.h", "stm32f4xx.h", "stdio.h"],
            "init_call": "USART1_Init(115200);",
            "init_code": """void USART1_Init(u32 bound)
{
    GPIO_InitTypeDef GPIO_InitStructure;
    USART_InitTypeDef USART_InitStructure;
    NVIC_InitTypeDef NVIC_InitStructure;

    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOB, ENABLE);
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_USART1, ENABLE);

    GPIO_PinAFConfig(GPIOB, GPIO_PinSource6, GPIO_AF_USART1);
    GPIO_PinAFConfig(GPIOB, GPIO_PinSource7, GPIO_AF_USART1);

    GPIO_InitStructure.GPIO_Pin = GPIO_Pin_6 | GPIO_Pin_7;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_AF;
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_InitStructure.GPIO_OType = GPIO_OType_PP;
    GPIO_InitStructure.GPIO_PuPd = GPIO_PuPd_UP;
    GPIO_Init(GPIOB, &GPIO_InitStructure);

    NVIC_InitStructure.NVIC_IRQChannel = USART1_IRQn;
    NVIC_InitStructure.NVIC_IRQChannelPreemptionPriority = 1;
    NVIC_InitStructure.NVIC_IRQChannelSubPriority = 0;
    NVIC_InitStructure.NVIC_IRQChannelCmd = ENABLE;
    NVIC_Init(&NVIC_InitStructure);

    USART_InitStructure.USART_BaudRate = bound;
    USART_InitStructure.USART_WordLength = USART_WordLength_8b;
    USART_InitStructure.USART_StopBits = USART_StopBits_1;
    USART_InitStructure.USART_Parity = USART_Parity_No;
    USART_InitStructure.USART_HardwareFlowControl = USART_HardwareFlowControl_None;
    USART_InitStructure.USART_Mode = USART_Mode_Rx | USART_Mode_Tx;
    USART_Init(USART1, &USART_InitStructure);

    USART_ITConfig(USART1, USART_IT_RXNE, ENABLE);
    USART_Cmd(USART1, ENABLE);
}

int fputc(int ch, FILE *f)
{
    USART_Sendbyte(USART1, (uint8_t)ch);
    return ch;
}""",
            "global_vars": "extern int USART_RxData;",
            "interrupt_handlers": """void USART1_IRQHandler(void)
{
    if (USART_GetITStatus(USART1, USART_IT_RXNE) == SET)
    {
        USART_RxData = USART_ReceiveData(USART1);
        USART_ClearITPendingBit(USART1, USART_IT_RXNE);
    }
}""",
        },

        "GPIO_F103": {
            "header_includes": ["GPIO.h", "stm32f10x.h"],
            "init_call": "Config_GPIO(GPIOx, GPIO_Pin_x, GPIO_MODE_OUTPUT);",
            "init_code": """void Config_GPIO(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin, GPIO_Mode_TypeDef Mode)
{
    GPIO_InitTypeDef GPIO_InitStructure;

    /* 使能GPIO时钟 */
    if (GPIOx == GPIOA) RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA, ENABLE);
    else if (GPIOx == GPIOB) RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB, ENABLE);
    else if (GPIOx == GPIOC) RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOC, ENABLE);
    else if (GPIOx == GPIOD) RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOD, ENABLE);
    else if (GPIOx == GPIOE) RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOE, ENABLE);
    else if (GPIOx == GPIOF) RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOF, ENABLE);
    else if (GPIOx == GPIOG) RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOG, ENABLE);

    GPIO_InitStructure.GPIO_Pin = GPIO_Pin;
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_InitStructure.GPIO_Mode = (Mode == GPIO_MODE_OUTPUT) ? GPIO_Mode_Out_PP : GPIO_Mode_IN_FLOATING;

    GPIO_Init(GPIOx, &GPIO_InitStructure);
}""",
            "global_vars": "",
            "interrupt_handlers": "",
        },

        "USART_F103": {
            "header_includes": ["USART.h", "stm32f10x.h", "stdio.h"],
            "init_call": "USART1_Init(115200);",
            "init_code": """void USART1_Init(u32 bound)
{
    GPIO_InitTypeDef GPIO_InitStructure;
    USART_InitTypeDef USART_InitStructure;
    NVIC_InitTypeDef NVIC_InitStructure;

    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA | RCC_APB2Periph_USART1, ENABLE);

    GPIO_InitStructure.GPIO_Pin = GPIO_Pin_9;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_AF_PP;
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOA, &GPIO_InitStructure);

    GPIO_InitStructure.GPIO_Pin = GPIO_Pin_10;
    GPIO_InitStructure.GPIO_Mode = GPIO_Mode_IN_FLOATING;
    GPIO_Init(GPIOA, &GPIO_InitStructure);

    NVIC_InitStructure.NVIC_IRQChannel = USART1_IRQn;
    NVIC_InitStructure.NVIC_IRQChannelPreemptionPriority = 1;
    NVIC_InitStructure.NVIC_IRQChannelSubPriority = 0;
    NVIC_InitStructure.NVIC_IRQChannelCmd = ENABLE;
    NVIC_Init(&NVIC_InitStructure);

    USART_InitStructure.USART_BaudRate = bound;
    USART_InitStructure.USART_WordLength = USART_WordLength_8b;
    USART_InitStructure.USART_StopBits = USART_StopBits_1;
    USART_InitStructure.USART_Parity = USART_Parity_No;
    USART_InitStructure.USART_HardwareFlowControl = USART_HardwareFlowControl_None;
    USART_InitStructure.USART_Mode = USART_Mode_Rx | USART_Mode_Tx;
    USART_Init(USART1, &USART_InitStructure);

    USART_ITConfig(USART1, USART_IT_RXNE, ENABLE);
    USART_Cmd(USART1, ENABLE);
}""",
            "global_vars": "extern int USART_RxData;",
            "interrupt_handlers": """void USART1_IRQHandler(void)
{
    if (USART_GetITStatus(USART1, USART_IT_RXNE) == SET)
    {
        USART_RxData = USART_ReceiveData(USART1);
        USART_ClearITPendingBit(USART1, USART_IT_RXNE);
    }
}""",
        },

        "SysTick": {
            "header_includes": ["delay.h"],
            "init_call": "Delay_Init();",
            "init_code": """static __IO uint32_t TimingDelay;

void Delay_Init(void)
{
    SysTick_Config(SystemCoreClock / 1000000);
}

void TimingDelay_Decrement(void)
{
    if (TimingDelay != 0) TimingDelay--;
}

void Delay_us(uint32_t nTime)
{
    TimingDelay = nTime;
    while (TimingDelay != 0);
}

void Delay_ms(uint32_t nTime)
{
    TimingDelay = nTime * 1000;
    while (TimingDelay != 0);
}""",
            "global_vars": "",
            "interrupt_handlers": """void SysTick_Handler(void)
{
    TimingDelay_Decrement();
}""",
        },
        "I2C_F407": {
            "header_includes": ["delay.h", "stm32f4xx.h"],
            "init_call": "I2C_Init();",
            "init_code": """/* I2C SCL=PB8 SDA=PB9 */
void I2C_Init(void) {
    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOB, ENABLE);
    GPIO_InitTypeDef s;
    s.GPIO_Pin = GPIO_Pin_8 | GPIO_Pin_9;
    s.GPIO_Mode = GPIO_Mode_OUT;
    s.GPIO_OType = GPIO_OType_OD;
    s.GPIO_Speed = GPIO_Speed_100MHz;
    s.GPIO_PuPd = GPIO_PuPd_UP;
    GPIO_Init(GPIOB, &s);
    PBout(8)=1; PBout(9)=1;
}
static void I2C_Start(void) {
    PBout(9)=1; PBout(8)=1; Delay_us(4);
    PBout(9)=0; Delay_us(4); PBout(8)=0;
}
static void I2C_Stop(void) {
    PBout(8)=0; PBout(9)=0; Delay_us(4);
    PBout(8)=1; PBout(9)=1; Delay_us(4);
}
static uint8_t I2C_WaitAck(void) {
    PBout(9)=1; Delay_us(1);
    PBout(8)=1; Delay_us(1);
    uint8_t ack = PBin(9);
    PBout(8)=0;
    return ack;
}
static void I2C_SendByte(uint8_t data) {
    uint8_t i;
    for (i=0; i<8; i++) {
        PBout(9) = (data & 0x80) >> 7;
        data <<= 1;
        PBout(8)=1; Delay_us(2);
        PBout(8)=0; Delay_us(2);
    }
    I2C_WaitAck();
}
static uint8_t I2C_ReadByte(uint8_t ack) {
    uint8_t i, val=0;
    PBout(9)=1;
    for (i=0; i<8; i++) {
        val <<= 1;
        PBout(8)=1; Delay_us(2);
        if (PBin(9)) val |= 1;
        PBout(8)=0; Delay_us(2);
    }
    PBout(9) = ack?0:1;
    PBout(8)=1; Delay_us(2);
    PBout(8)=0;
    return val;
}""",
            "global_vars": "",
            "interrupt_handlers": """""",
        },
        "I2C_F103": {
            "header_includes": ["delay.h", "stm32f10x.h"],
            "init_call": "I2C_Init();",
            "init_code": """/* I2C SCL=PB6(推挽) SDA=PB7(开漏+外部上拉) */
void I2C_Init(void) {
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB, ENABLE);
    Config_GPIO(GPIOB, GPIO_Pin_6, GPIO_MODE_OUTPUT);                /* SCL: 推挽 */
    Config_GPIO(GPIOB, GPIO_Pin_7, GPIO_MODE_INPUT);                 /* SDA: 浮空输入 */
    PBout(6)=1; /* SCL=H */  /* SDA 靠外部上拉 */
}
static void SDA_Out(void) { Config_GPIO(GPIOB, GPIO_Pin_7, GPIO_MODE_OUTPUT); }
static void SDA_In(void)  { Config_GPIO(GPIOB, GPIO_Pin_7, GPIO_MODE_INPUT); }
static void I2C_Start(void) { SDA_Out(); PBout(7)=1; PBout(6)=1; Delay_us(4); PBout(7)=0; Delay_us(4); PBout(6)=0; }
static void I2C_Stop(void)  { SDA_Out(); PBout(6)=0; PBout(7)=0; Delay_us(4); PBout(6)=1; PBout(7)=1; SDA_In(); Delay_us(4); }
static uint8_t I2C_WaitAck(void) {
    SDA_In(); Delay_us(1); PBout(6)=1; Delay_us(1);
    uint8_t ack = PBin(7); PBout(6)=0; return ack;
}
static void I2C_SendByte(uint8_t data) {
    uint8_t i; SDA_Out();
    for (i=0; i<8; i++) { PBout(7)=(data&0x80)>>7; data<<=1; PBout(6)=1; Delay_us(2); PBout(6)=0; Delay_us(2); }
    I2C_WaitAck();
}""",
            "global_vars": "",
            "interrupt_handlers": """""",
        },
        "SPI_F407": {
            "header_includes": ["stm32f4xx_spi.h"],
            "init_call": "SPI1_Init();",
            "init_code": """void SPI1_Init(void) {
    GPIO_InitTypeDef g; SPI_InitTypeDef s;
    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOB, ENABLE);
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_SPI1, ENABLE);
    GPIO_PinAFConfig(GPIOB, GPIO_PinSource3, GPIO_AF_SPI1);
    GPIO_PinAFConfig(GPIOB, GPIO_PinSource4, GPIO_AF_SPI1);
    GPIO_PinAFConfig(GPIOB, GPIO_PinSource5, GPIO_AF_SPI1);
    g.GPIO_Pin = GPIO_Pin_3|GPIO_Pin_4|GPIO_Pin_5;
    g.GPIO_Mode = GPIO_Mode_AF; g.GPIO_OType = GPIO_OType_PP;
    g.GPIO_Speed = GPIO_Speed_100MHz; g.GPIO_PuPd = GPIO_PuPd_UP;
    GPIO_Init(GPIOB, &g);
    SPI_StructInit(&s); s.SPI_Direction = SPI_Direction_2Lines_FullDuplex;
    s.SPI_Mode = SPI_Mode_Master; s.SPI_DataSize = SPI_DataSize_8b;
    s.SPI_CPOL = SPI_CPOL_High; s.SPI_CPHA = SPI_CPHA_2Edge;
    s.SPI_NSS = SPI_NSS_Soft; s.SPI_BaudRatePrescaler = SPI_BaudRatePrescaler_256;
    s.SPI_FirstBit = SPI_FirstBit_MSB;
    SPI_Init(SPI1, &s); SPI_Cmd(SPI1, ENABLE);
}
uint8_t SPI1_ReadWriteByte(uint8_t tx) {
    while (SPI_I2S_GetFlagStatus(SPI1, SPI_FLAG_TXE) == RESET);
    SPI_I2S_SendData(SPI1, tx);
    while (SPI_I2S_GetFlagStatus(SPI1, SPI_FLAG_RXNE) == RESET);
    return SPI_I2S_ReceiveData(SPI1);
}""",
            "global_vars": "",
            "interrupt_handlers": """""",
        },
        "SPI_F103": {
            "header_includes": ["stm32f10x_spi.h"],
            "init_call": "SPI1_Init();",
            "init_code": """void SPI1_Init(void) {
    GPIO_InitTypeDef g; SPI_InitTypeDef s;
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA | RCC_APB2Periph_SPI1, ENABLE);
    g.GPIO_Pin = GPIO_Pin_5|GPIO_Pin_6|GPIO_Pin_7;
    g.GPIO_Mode = GPIO_Mode_AF_PP; g.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOA, &g);
    SPI_StructInit(&s); s.SPI_Direction = SPI_Direction_2Lines_FullDuplex;
    s.SPI_Mode = SPI_Mode_Master; s.SPI_DataSize = SPI_DataSize_8b;
    s.SPI_CPOL = SPI_CPOL_High; s.SPI_CPHA = SPI_CPHA_2Edge;
    s.SPI_NSS = SPI_NSS_Soft; s.SPI_BaudRatePrescaler = SPI_BaudRatePrescaler_256;
    s.SPI_FirstBit = SPI_FirstBit_MSB;
    SPI_Init(SPI1, &s); SPI_Cmd(SPI1, ENABLE);
}
uint8_t SPI1_ReadWriteByte(uint8_t tx) {
    while (SPI_I2S_GetFlagStatus(SPI1, SPI_FLAG_TXE) == RESET);
    SPI_I2S_SendData(SPI1, tx);
    while (SPI_I2S_GetFlagStatus(SPI1, SPI_FLAG_RXNE) == RESET);
    return SPI_I2S_ReceiveData(SPI1);
}""",
            "global_vars": "",
            "interrupt_handlers": """""",
        },
        "TIM_F407": {
            "header_includes": ["stm32f4xx_tim.h"],
            "init_call": "TIM3_PWM_Init(8399, 9999);",
            "init_code": """void TIM3_PWM_Init(uint16_t arr, uint16_t psc) {
    GPIO_InitTypeDef g; TIM_TimeBaseInitTypeDef t; TIM_OCInitTypeDef oc;
    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOC, ENABLE);
    RCC_APB1PeriphClockCmd(RCC_APB1Periph_TIM3, ENABLE);
    GPIO_PinAFConfig(GPIOC, GPIO_PinSource6, GPIO_AF_TIM3);
    g.GPIO_Pin = GPIO_Pin_6; g.GPIO_Mode = GPIO_Mode_AF;
    g.GPIO_OType = GPIO_OType_PP; g.GPIO_Speed = GPIO_Speed_100MHz;
    g.GPIO_PuPd = GPIO_PuPd_UP; GPIO_Init(GPIOC, &g);
    t.TIM_Prescaler = psc; t.TIM_Period = arr;
    t.TIM_CounterMode = TIM_CounterMode_Up;
    t.TIM_ClockDivision = TIM_CKD_DIV1;
    TIM_TimeBaseInit(TIM3, &t);
    oc.TIM_OCMode = TIM_OCMode_PWM1;
    oc.TIM_OutputState = TIM_OutputState_Enable;
    oc.TIM_Pulse = arr/2; oc.TIM_OCPolarity = TIM_OCPolarity_High;
    TIM_OC1Init(TIM3, &oc); TIM_OC1PreloadConfig(TIM3, TIM_OCPreload_Enable);
    TIM_ARRPreloadConfig(TIM3, ENABLE); TIM_Cmd(TIM3, ENABLE);
}""",
            "global_vars": "",
            "interrupt_handlers": """""",
        },
        "TIM_F103": {
            "header_includes": ["stm32f10x_tim.h"],
            "init_call": "TIM3_PWM_Init(7199, 9999);",
            "init_code": """void TIM3_PWM_Init(uint16_t arr, uint16_t psc) {
    GPIO_InitTypeDef g; TIM_TimeBaseInitTypeDef t; TIM_OCInitTypeDef oc;
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA, ENABLE);
    RCC_APB1PeriphClockCmd(RCC_APB1Periph_TIM3, ENABLE);
    g.GPIO_Pin = GPIO_Pin_6; g.GPIO_Mode = GPIO_Mode_AF_PP;
    g.GPIO_Speed = GPIO_Speed_50MHz; GPIO_Init(GPIOA, &g);
    t.TIM_Prescaler = psc; t.TIM_Period = arr;
    t.TIM_CounterMode = TIM_CounterMode_Up; t.TIM_ClockDivision = TIM_CKD_DIV1;
    TIM_TimeBaseInit(TIM3, &t);
    oc.TIM_OCMode = TIM_OCMode_PWM1;
    oc.TIM_OutputState = TIM_OutputState_Enable;
    oc.TIM_Pulse = arr/2; oc.TIM_OCPolarity = TIM_OCPolarity_High;
    TIM_OC1Init(TIM3, &oc); TIM_Cmd(TIM3, ENABLE);
}""",
            "global_vars": "",
            "interrupt_handlers": """""",
        },
        "ADC_F407": {
            "header_includes": ["stm32f4xx_adc.h"],
            "init_call": "ADC1_Init();",
            "init_code": """void ADC1_Init(void) {
    GPIO_InitTypeDef g; ADC_CommonInitTypeDef ac; ADC_InitTypeDef a;
    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOA, ENABLE);
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_ADC1, ENABLE);
    g.GPIO_Pin = GPIO_Pin_5; g.GPIO_Mode = GPIO_Mode_AN;
    g.GPIO_PuPd = GPIO_PuPd_NOPULL; GPIO_Init(GPIOA, &g);
    ADC_CommonStructInit(&ac); ac.ADC_Mode = ADC_Mode_Independent;
    ac.ADC_Prescaler = ADC_Prescaler_Div4;
    ac.ADC_DMAAccessMode = ADC_DMAAccessMode_Disabled;
    ac.ADC_TwoSamplingDelay = ADC_TwoSamplingDelay_5Cycles;
    ADC_CommonInit(&ac);
    ADC_StructInit(&a); a.ADC_Resolution = ADC_Resolution_12b;
    a.ADC_ScanConvMode = DISABLE; a.ADC_ContinuousConvMode = ENABLE;
    a.ADC_ExternalTrigConvEdge = ADC_ExternalTrigConvEdge_None;
    a.ADC_DataAlign = ADC_DataAlign_Right; a.ADC_NbrOfConversion = 1;
    ADC_Init(ADC1, &a);
    ADC_RegularChannelConfig(ADC1, ADC_Channel_5, 1, ADC_SampleTime_480Cycles);
    ADC_Cmd(ADC1, ENABLE); ADC_SoftwareStartConv(ADC1);
}
uint16_t ADC1_GetValue(void) {
    while (!ADC_GetFlagStatus(ADC1, ADC_FLAG_EOC));
    return ADC_GetConversionValue(ADC1);
}""",
            "global_vars": "",
            "interrupt_handlers": """""",
        },
        "ADC_F103": {
            "header_includes": ["stm32f10x_adc.h"],
            "init_call": "ADC1_Init();",
            "init_code": """void ADC1_Init(void) {
    GPIO_InitTypeDef g; ADC_InitTypeDef a;
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA | RCC_APB2Periph_ADC1, ENABLE);
    g.GPIO_Pin = GPIO_Pin_1; g.GPIO_Mode = GPIO_Mode_AIN;
    GPIO_Init(GPIOA, &g);
    ADC_StructInit(&a); a.ADC_Mode = ADC_Mode_Independent;
    a.ADC_ScanConvMode = DISABLE; a.ADC_ContinuousConvMode = ENABLE;
    a.ADC_ExternalTrigConv = ADC_ExternalTrigConv_None;
    a.ADC_DataAlign = ADC_DataAlign_Right; a.ADC_NbrOfChannel = 1;
    ADC_Init(ADC1, &a);
    ADC_RegularChannelConfig(ADC1, ADC_Channel_1, 1, ADC_SampleTime_239Cycles5);
    ADC_Cmd(ADC1, ENABLE);
    ADC_ResetCalibration(ADC1);
    while (ADC_GetResetCalibrationStatus(ADC1));
    ADC_StartCalibration(ADC1);
    while (ADC_GetCalibrationStatus(ADC1));
    ADC_SoftwareStartConvCmd(ADC1, ENABLE);
}
uint16_t ADC1_GetValue(void) {
    while (!ADC_GetFlagStatus(ADC1, ADC_FLAG_EOC));
    return ADC_GetConversionValue(ADC1);
}""",
            "global_vars": "",
            "interrupt_handlers": """""",
        },
        "DMA_F407": {
            "header_includes": ["stm32f4xx_dma.h"],
            "init_call": "MYDMA_Config(DMA2_Stream7, DMA_Channel_4, (uint32_t)&USART1->DR, (uint32_t)buf, 100);",
            "init_code": """void MYDMA_Config(DMA_Stream_TypeDef* s, uint32_t ch, uint32_t par, uint32_t mar, uint16_t ndtr) {
    DMA_InitTypeDef d;
    RCC_AHB1PeriphClockCmd((uint32_t)s >= (uint32_t)DMA2 ? RCC_AHB1Periph_DMA2 : RCC_AHB1Periph_DMA1, ENABLE);
    DMA_DeInit(s);
    d.DMA_Channel = ch; d.DMA_PeripheralBaseAddr = par;
    d.DMA_Memory0BaseAddr = mar; d.DMA_DIR = DMA_DIR_MemoryToPeripheral;
    d.DMA_BufferSize = ndtr; d.DMA_PeripheralInc = DMA_PeripheralInc_Disable;
    d.DMA_MemoryInc = DMA_MemoryInc_Enable;
    d.DMA_PeripheralDataSize = DMA_PeripheralDataSize_Byte;
    d.DMA_MemoryDataSize = DMA_MemoryDataSize_Byte;
    d.DMA_Mode = DMA_Mode_Normal; d.DMA_Priority = DMA_Priority_High;
    d.DMA_FIFOMode = DMA_FIFOMode_Disable;
    DMA_Init(s, &d);
}
void MYDMA_Enable(DMA_Stream_TypeDef* s, uint16_t ndtr) {
    DMA_Cmd(s, DISABLE); DMA_SetCurrDataCounter(s, ndtr); DMA_Cmd(s, ENABLE);
}""",
            "global_vars": "",
            "interrupt_handlers": """""",
        },
        "DMA_F103": {
            "header_includes": ["stm32f10x_dma.h"],
            "init_call": "MYDMA_Config(DMA1_Channel4, (uint32_t)&USART1->DR, (uint32_t)buf, 100);",
            "init_code": """void MYDMA_Config(DMA_Channel_TypeDef* ch, uint32_t par, uint32_t mar, uint16_t ndtr) {
    DMA_InitTypeDef d;
    RCC_AHBPeriphClockCmd((uint32_t)ch >= (uint32_t)DMA2_Channel1 ? RCC_AHBPeriph_DMA2 : RCC_AHBPeriph_DMA1, ENABLE);
    DMA_DeInit(ch);
    d.DMA_PeripheralBaseAddr = par; d.DMA_MemoryBaseAddr = mar;
    d.DMA_DIR = DMA_DIR_PeripheralSRC; d.DMA_BufferSize = ndtr;
    d.DMA_PeripheralInc = DMA_PeripheralInc_Disable;
    d.DMA_MemoryInc = DMA_MemoryInc_Enable;
    d.DMA_PeripheralDataSize = DMA_PeripheralDataSize_Byte;
    d.DMA_MemoryDataSize = DMA_MemoryDataSize_Byte;
    d.DMA_Mode = DMA_Mode_Normal; d.DMA_Priority = DMA_Priority_High;
    d.DMA_M2M = DMA_M2M_Disable;
    DMA_Init(ch, &d);
}
void MYDMA_Enable(DMA_Channel_TypeDef* ch, uint16_t ndtr) {
    DMA_Cmd(ch, DISABLE); DMA_SetCurrDataCounter(ch, ndtr); DMA_Cmd(ch, ENABLE);
}""",
            "global_vars": "",
            "interrupt_handlers": """""",
        },
        "CAN_F407": {
            "header_includes": ["stm32f4xx_can.h"],
            "init_call": "CAN1_Init();",
            "init_code": """void CAN1_Init(void) {
    GPIO_InitTypeDef g; CAN_InitTypeDef c; CAN_FilterInitTypeDef f;
    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOA, ENABLE);
    RCC_APB1PeriphClockCmd(RCC_APB1Periph_CAN1, ENABLE);
    GPIO_PinAFConfig(GPIOA, GPIO_PinSource11, GPIO_AF_CAN1);
    GPIO_PinAFConfig(GPIOA, GPIO_PinSource12, GPIO_AF_CAN1);
    g.GPIO_Pin = GPIO_Pin_11|GPIO_Pin_12; g.GPIO_Mode = GPIO_Mode_AF;
    g.GPIO_OType = GPIO_OType_PP; g.GPIO_Speed = GPIO_Speed_100MHz;
    g.GPIO_PuPd = GPIO_PuPd_UP; GPIO_Init(GPIOA, &g);
    CAN_DeInit(CAN1); CAN_StructInit(&c);
    c.CAN_Mode = CAN_Mode_Normal; c.CAN_SJW = CAN_SJW_1tq;
    c.CAN_BS1 = CAN_BS1_4tq; c.CAN_BS2 = CAN_BS2_3tq;
    c.CAN_Prescaler = 42; CAN_Init(CAN1, &c);
    f.CAN_FilterNumber = 0; f.CAN_FilterMode = CAN_FilterMode_IdMask;
    f.CAN_FilterScale = CAN_FilterScale_32bit;
    f.CAN_FilterIdHigh = 0; f.CAN_FilterIdLow = 0;
    f.CAN_FilterMaskIdHigh = 0; f.CAN_FilterMaskIdLow = 0;
    f.CAN_FilterFIFOAssignment = CAN_FIFO0;
    f.CAN_FilterActivation = ENABLE; CAN_FilterInit(&f);
}""",
            "global_vars": "",
            "interrupt_handlers": """""",
        },
        "CAN_F103": {
            "header_includes": ["stm32f10x_can.h"],
            "init_call": "CAN1_Init();",
            "init_code": """void CAN1_Init(void) {
    GPIO_InitTypeDef g; CAN_InitTypeDef c; CAN_FilterInitTypeDef f;
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA | RCC_APB2Periph_AFIO, ENABLE);
    RCC_APB1PeriphClockCmd(RCC_APB1Periph_CAN1, ENABLE);
    g.GPIO_Pin = GPIO_Pin_11|GPIO_Pin_12; g.GPIO_Mode = GPIO_Mode_AF_PP;
    g.GPIO_Speed = GPIO_Speed_50MHz; GPIO_Init(GPIOA, &g);
    CAN_DeInit(CAN1); CAN_StructInit(&c);
    c.CAN_Mode = CAN_Mode_Normal; c.CAN_SJW = CAN_SJW_1tq;
    c.CAN_BS1 = CAN_BS1_4tq; c.CAN_BS2 = CAN_BS2_3tq;
    c.CAN_Prescaler = 36; CAN_Init(CAN1, &c);
    f.CAN_FilterNumber = 0; f.CAN_FilterMode = CAN_FilterMode_IdMask;
    f.CAN_FilterScale = CAN_FilterScale_32bit;
    f.CAN_FilterIdHigh = 0; f.CAN_FilterIdLow = 0;
    f.CAN_FilterMaskIdHigh = 0; f.CAN_FilterMaskIdLow = 0;
    f.CAN_FilterFIFOAssignment = CAN_FIFO0;
    f.CAN_FilterActivation = ENABLE; CAN_FilterInit(&f);
}""",
            "global_vars": "",
            "interrupt_handlers": """""",
        },
        "EXTI_F407": {
            "header_includes": ["stm32f4xx_exti.h", "stm32f4xx_syscfg.h"],
            "init_call": "EXTI_Init();",
            "init_code": """void EXTI_Init(void) {
    GPIO_InitTypeDef g; EXTI_InitTypeDef e; NVIC_InitTypeDef n;
    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOB, ENABLE);
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_SYSCFG, ENABLE);
    g.GPIO_Pin = GPIO_Pin_0; g.GPIO_Mode = GPIO_Mode_IN;
    g.GPIO_PuPd = GPIO_PuPd_UP; GPIO_Init(GPIOB, &g);
    SYSCFG_EXTILineConfig(EXTI_PortSourceGPIOB, EXTI_PinSource0);
    e.EXTI_Line = EXTI_Line0; e.EXTI_Mode = EXTI_Mode_Interrupt;
    e.EXTI_Trigger = EXTI_Trigger_Falling;
    e.EXTI_LineCmd = ENABLE; EXTI_Init(&e);
    n.NVIC_IRQChannel = EXTI0_IRQn;
    n.NVIC_IRQChannelPreemptionPriority = 2;
    n.NVIC_IRQChannelSubPriority = 0;
    n.NVIC_IRQChannelCmd = ENABLE; NVIC_Init(&n);
}""",
            "global_vars": "",
            "interrupt_handlers": """void EXTI0_IRQHandler(void) {
    if (EXTI_GetITStatus(EXTI_Line0) == SET) {
        EXTI_ClearITPendingBit(EXTI_Line0);
    }
}""",
        },
        "EXTI_F103": {
            "header_includes": ["stm32f10x_exti.h"],
            "init_call": "EXTI_Init();",
            "init_code": """void EXTI_Init(void) {
    GPIO_InitTypeDef g; EXTI_InitTypeDef e; NVIC_InitTypeDef n;
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB | RCC_APB2Periph_AFIO, ENABLE);
    g.GPIO_Pin = GPIO_Pin_0; g.GPIO_Mode = GPIO_Mode_IN_FLOATING;
    GPIO_Init(GPIOB, &g);
    GPIO_EXTILineConfig(GPIO_PortSourceGPIOB, GPIO_PinSource0);
    e.EXTI_Line = EXTI_Line0; e.EXTI_Mode = EXTI_Mode_Interrupt;
    e.EXTI_Trigger = EXTI_Trigger_Falling;
    e.EXTI_LineCmd = ENABLE; EXTI_Init(&e);
    n.NVIC_IRQChannel = EXTI0_IRQn;
    n.NVIC_IRQChannelPreemptionPriority = 2;
    n.NVIC_IRQChannelSubPriority = 0;
    n.NVIC_IRQChannelCmd = ENABLE; NVIC_Init(&n);
}""",
            "global_vars": "",
            "interrupt_handlers": """void EXTI0_IRQHandler(void) {
    if (EXTI_GetITStatus(EXTI_Line0) == SET) {
        EXTI_ClearITPendingBit(EXTI_Line0);
    }
}""",
        },
        "IWDG_F407": {
            "header_includes": ["stm32f4xx_iwdg.h"],
            "init_call": "IWDG_Init(4, 625);",
            "init_code": """void IWDG_Init(uint8_t prer, uint16_t rlr) {
    IWDG_WriteAccessCmd(IWDG_WriteAccess_Enable);
    IWDG_SetPrescaler(prer); IWDG_SetReload(rlr);
    IWDG_ReloadCounter(); IWDG_Enable();
}
void IWDG_Feed(void) { IWDG_ReloadCounter(); }""",
            "global_vars": "",
            "interrupt_handlers": """""",
        },
        "IWDG_F103": {
            "header_includes": ["stm32f10x_iwdg.h"],
            "init_call": "IWDG_Init(4, 625);",
            "init_code": """void IWDG_Init(uint8_t prer, uint16_t rlr) {
    IWDG_WriteAccessCmd(IWDG_WriteAccess_Enable);
    IWDG_SetPrescaler(prer); IWDG_SetReload(rlr);
    IWDG_ReloadCounter(); IWDG_Enable();
}
void IWDG_Feed(void) { IWDG_ReloadCounter(); }""",
            "global_vars": "",
            "interrupt_handlers": """""",
        },
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Search STM32 example code")
    parser.add_argument("--examples", required=True, help="Path to examples directory")
    parser.add_argument("--peripheral", default=None, help="Peripheral name (GPIO, USART, etc.)")
    parser.add_argument("--requirement", default=None, help="Free-text requirement search")
    parser.add_argument("--family", default=None, choices=["F103", "F407"],
                        help="Chip family filter")
    parser.add_argument("--index", action="store_true", help="Build and print full index")

    args = parser.parse_args()

    if args.index:
        idx = index_examples(args.examples)
        print(json.dumps(idx, indent=2, ensure_ascii=False))
    elif args.requirement:
        results = search_by_requirement(args.examples, args.requirement, args.family)
        print(json.dumps(results, indent=2, ensure_ascii=False))
    elif args.peripheral:
        results = search_examples(args.examples, args.peripheral, args.family)
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        parser.print_help()

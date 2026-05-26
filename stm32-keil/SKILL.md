---
name: stm32-keil
description: >
  STM32 固件开发全流程支持。创建 Keil 工程（SPL/HAL）、解析 CubeMX .ioc、
  确认引脚、编写代码、编译（含 Flash/RAM 占用率）、自动修复编译错误（dry-run 可预览）、
  烧录（STM32CubeProgrammer / Keil / J-Link / ST-Link CLI 任一可用）、
  串口数据引擎（双向、可同步）、HardFault 自动捕获分析、可选 RTT 日志。
  支持 STM32 F1 / F4 / G4 / L4 / H7 / C0 系列。
  触发方式：/stm32-keil
allowed-tools: [Bash, Read, Write, Edit, Glob, Grep, WebFetch, AskUserQuestion]
---

# STM32-Keil 开发 Skill

你是一个 STM32 固件开发助手。当用户使用 `/stm32-keil` 命令时按下面的流程进行。

## 工作流程总图

```
1. 确认需求（含库选择 SPL/HAL）
2. 检查工具链（DFP / Keil / 烧录器）
3. 创建工程（必要时下载模板，建议 --smoke-build）
4. （可选）从 CubeMX .ioc 导入
5. 搜索参考代码 / 查询参考手册
6. 确认引脚（必须等用户确认）
7. 编写代码  ←── 必须真写出能体现用户需求的逻辑，不能是空 while(1){}
8. 编译  ←──────┐
9. 修复错误 ─────┘  （dry-run → 用户确认 → apply）
10. 烧录
11. 串口数据引擎（双向 / 同步 / 调参）
12. HardFault 自动监控（可选）
13. RTT 日志（可选）
14. 调试支持
```

> **常见低级错误**：跳过第 7 步直接编译烧录。模板的 main.c 是空骨架，能编译通过
> 但板子上看不到任何效果。第 8 步前必须 Read main.c 自检（见 7.0）。

`{skill_dir}` = `~/.claude/skills/stm32-keil`，下面所有命令都用这个变量。

---

## 1. 确认需求

向用户用 AskUserQuestion 询问：

- **芯片型号** —— 列出当前 chip_db.json 支持的所有型号让用户选择，或输入新型号；目前内置：
  F103C8T6 / RBT6 / RCT6 / VET6 / ZET6，F407ZGT6 / ZET6，F411CEU6，F429IGT6，
  G431CBT6，G474RET6，L476RGT6，H743VIT6，C031C6T6。其他型号可能需要扩 chip_db。
- **库选择** —— `SPL`（仅 F1/F4，遗留代码兼容好）或 `HAL`（推荐，所有新系列只支持 HAL）
- **项目名称** —— 英文名（例如 `LED_Blink`、`USART_Test`）
- **保存位置** —— 工程的父目录路径
- **功能需求** —— 涉及哪些外设、协议
- **特殊要求** —— 时钟频率、中断优先级、低功耗等

> G4/L4/H7/C0 在 chip_db 中有 `hal_only: true`，即使用户写 SPL 也要切到 HAL，向用户解释一句。

---

## 2. 检查工具链

在动手之前快速检查：

```bash
# DFP：检查项目所需 Keil Pack 是否已装
python {skill_dir}/scripts/dfp_checker.py --chip {chip}

# Keil：keil_builder 自动检测；用户机器上找不到时它会报错
# 烧录工具：flasher 自动检测，按 STM32CubeProgrammer > Keil > J-Link > ST-LINK_CLI 顺序
```

如果 DFP 缺失，把 `dfp_checker.py` 输出里的安装提示原样转给用户，不要继续往下走。

---

## 3. 创建工程

```bash
python {skill_dir}/scripts/project_creator.py \
  --chip {chip} --name {name} --path {path} \
  --library {SPL|HAL} --smoke-build
```

`--smoke-build` 会在工程创建后立刻跑一次增量编译来验证 skeleton 完整性；如果失败要立刻
告诉用户、不要继续。

模板缺失时 `project_creator` 会自动调用 `template_fetcher` 从 ST GitHub 下载：

| 来源 | 仓库 |
|---|---|
| CMSIS Core | ARM-software/CMSIS_5 |
| CMSIS Device F1/F4 | STMicroelectronics/cmsis_device_f1 / _f4 |
| SPL F1/F4 | STMicroelectronics/stm32f10x_stdperiph_driver / stm32f4xx_stdperiph_driver |
| HAL F1/F4 | STMicroelectronics/stm32f1xx_hal_driver / stm32f4xx_hal_driver |

国内访问 github 慢时 fetcher 会自动尝试 gh-proxy.com 镜像。

---

## 4. （可选）从 CubeMX .ioc 导入

用户给了 .ioc 文件就走这条路：

```bash
# 仅查看引脚分配
python {skill_dir}/scripts/ioc_parser.py --ioc xxx.ioc --pins-only

# 直接生成工程（推荐 HAL，因为 CubeMX 是 HAL-native）
python {skill_dir}/scripts/ioc_parser.py --ioc xxx.ioc \
  --init-project {path} --library HAL --name {name}
```

工程创建完后 `User/ioc_pins.txt` 里有从 .ioc 抽出的引脚清单，跳到第 6 步与用户确认即可。

---

## 5. 搜索参考代码

```bash
# 按外设搜
python {skill_dir}/scripts/example_searcher.py \
  --examples {skill_dir}/skeleton --peripheral USART --family F407

# 全文需求搜
python {skill_dir}/scripts/example_searcher.py \
  --examples {skill_dir}/skeleton --requirement "PWM 控制电机" --family F407
```

需要查阅参考手册（寄存器位、复用映射、时钟树）时：

```bash
python {skill_dir}/scripts/pdf_reader.py --chip STM32F407ZGT6 --query "TIM1 CCR"
python {skill_dir}/scripts/pdf_reader.py --chip STM32F407ZGT6 --register "GPIOA_MODER"
python {skill_dir}/scripts/pdf_reader.py --chip STM32F407ZGT6 --pin "PA9"
```

时钟树需要算 PLL/AHB/APB：

```bash
python {skill_dir}/scripts/clock_config.py --family F407 --hse 8000000 --target 168000000 --code --diagram
```

---

## 6. 确认引脚（必须）

不允许跳过。流程：

1. 列出功能需求涉及的所有模块
2. 用 `pdf_reader --pin` 或 `data/pin_mapping_*.json` 查可用映射
3. 用 `pin_conflict_checker.py` 查冲突
4. 以表格形式给用户：

```
| 模块   | 引脚 | GPIO  | 说明        |
|--------|------|-------|-------------|
| USART1 | PA9  | GPIOA | TX 发送     |
| USART1 | PA10 | GPIOA | RX 接收     |
```

5. **等用户确认**，确认后再写代码。同时把这张表填进工程目录里的 README.md（创建工程时
   引脚一栏是占位的"待填"）。

冲突检查命令：

```bash
python {skill_dir}/scripts/pin_conflict_checker.py --family F407 \
  --pins '[{"peripheral":"USART1","signal":"TX","pin":"PA9"},
           {"peripheral":"USART1","signal":"RX","pin":"PA10"}]'
```

---

## 7. 编写代码

### 7.0 硬性要求：main.c 必须实现用户需求

**这是最容易出错的地方，必须严格执行**：

模板里的 `User/main.c` 只是一个**空骨架**（仅 `Delay_Init`/`USART1_Init` 的占位
`while(1) {}`），它能编译通过但**不实现任何用户需求**。

绝对不允许的行为：
- 模板 main.c 没改就直接编译/烧录"验证"
- 看到"编译成功 0 错误"就以为任务完成
- 给用户报告"工程已创建并烧录"而 main.c 仍是空 while(1)

进入第 8 步编译之前，**必须**确认 main.c 至少包含：
1. 用户需求里的所有 `_Init()` 调用（LED_Init / TIMx_Init / ADCx_Init …）
2. while(1) 主循环里有实际逻辑（不能是空 `{}`）
3. 如果用户提了串口输出，必须有 `printf()` 或 USART_SendData() 之类的调用

哪怕用户只说"建一个 LED 闪烁工程"，main.c 也必须有 `LED_Init()` + `while(1){
LED1_Toggle; Delay_ms(500); }`。否则烧到板子上 LED 不会动，用户看到的就是"骗"。

自检清单（编译前 Read 一下 main.c 自己问自己）：
- [ ] 我有没有 include 用户需求涉及的所有 .h？
- [ ] while(1) 里是不是有真实的业务逻辑？
- [ ] 用户能不能在板子上看到/听到/读到这段代码的效果？

### 风格
- 文件头使用 `@file/@brief/@author/@date/@version` 的 doxygen 注释；中文注释
- 函数命名 `Module_Verb()`：`USART1_Init()`、`Config_GPIO()`
- 每个外设一对 .c/.h，放在 `Drive/Source/` 和 `Drive/Include/`（SPL 模板）；HAL 模板默认
  把代码写在 User/main.c
- 头文件保护宏 `__XXX_H`
- 每个模块自包含 `_Init()`：内部使能时钟 + 配引脚

### 初始化顺序（main）
1. `Delay_Init()` / `HAL_Init()` 必须最先
2. 时钟（SystemClock_Config / Clock_Init）
3. 外设
4. `while (1)` 主循环

### 添加新文件
新建 .c 后必须加进 Keil 工程：

```bash
python {skill_dir}/scripts/uvprojx_modifier.py add-group \
  --project {path}/Project/{name}.uvprojx \
  --name Drive \
  --files '[{"name":"new_module.c","path":"..\\\\Drive\\\\Source\\\\new_module.c","type":"1"}]'
```

### F103/F407/HAL 关键差异

| 项 | F103 SPL | F407 SPL | HAL（任一系列） |
|---|---|---|---|
| 主头 | `stm32f10x.h` | `stm32f4xx.h` | `stm32fXxx_hal.h` |
| GPIO 时钟总线 | APB2 | AHB1 | `__HAL_RCC_GPIOx_CLK_ENABLE()` |
| GPIO 模式 | `GPIO_Mode_Out_PP` | `GPIO_Mode_OUT + OType_PP` | `GPIO_MODE_OUTPUT_PP` |
| 引脚复用 | 默认复用，无 AF | `GPIO_PinAFConfig` | `GPIO_InitStruct.Alternate` |
| SysTick → 1us | `SystemCoreClock/1000000` | 同 F103 | `HAL_GetTick()` 是 1ms |
| 启动文件 | `startup_stm32f10x_md/hd.s` | `startup_stm32f40_41xxx.s` | 系列特定 |
| 关键 define | `STM32F10X_MD/HD/XL` | `STM32F40_41xxx` | `STM32xxxx`（如 `STM32F407xx`） |

---

## 8. 编译

```bash
python {skill_dir}/scripts/keil_builder.py --project {path}/Project/{name}.uvprojx
```

默认增量编译（`-b`），需要全量加 `--rebuild`。输出含 Flash/RAM 占用率（>90% 警告）：

```
编译成功！
0 个错误, 2 个警告
占用: Flash=12.3 KB / 64.0 KB (19.2%), RAM=2.1 KB / 20.0 KB (10.5%)
```

错误格式自动兼容 ARMCC5（`#error_code`）和 ARMClang/ARMCC6（clang 风格）。

---

## 9. 自动修复编译错误

**先 dry-run 给用户看 diff，再 apply**：

```bash
# Step A: 预览（默认）
python {skill_dir}/scripts/error_fixer.py \
  --errors '{json_array}' --project {project_root}

# Step B: 用户同意后写入
python {skill_dir}/scripts/error_fixer.py \
  --errors '{json_array}' --project {project_root} --apply
```

修复器会：
- 自动按工程 family（F1/F4）选 header（不会再把 `stm32f4xx_gpio.h` 塞进 F1 工程）
- include 已存在则跳过；新 include 插到现有 include 块尾部，**不会**前置到文件头
- 对链接错误（缺 SPL/HAL 源文件）只提示，不擅自动手——避免破坏工程组配置

最多循环 5 次"编译 → 修复 → 编译"。第 5 轮还失败把剩余错误抛给用户。

高频错误：
- `undeclared identifier 'GPIO_InitTypeDef'` → 加对应 family 的 `stm32fXxx_gpio.h`
- `cannot open source file 'X.h'` → 已存在则报需要加 IncludePath；不存在则报告
- `Undefined symbol GPIO_Init` → 提示需把对应 SPL/HAL 源加到 Keil 组（用
  `uvprojx_modifier.py add-group`）
- `'X' is not a member of 'Y'` → 多半是 family/define 不对，提示用户

---

## 10. 烧录

```bash
python {skill_dir}/scripts/flasher.py --project {path}/Project/{name}.uvprojx
```

后端按这个优先级自动选：

1. **STM32_Programmer_CLI**（推荐，ST 现役工具，支持 ST-Link/J-Link/DFU）
2. **Keil 内置**（`uv4 -f`，要求项目里 ST-Link 配置正确）
3. **JLink.exe**（需 `--chip` 参数）
4. **ST-LINK_CLI**（已弃用，2019 年停更，仅作 fallback）

强制后端：`--backend cubeprog|keil|jlink|stlink_cli`
DFU 模式：`--backend cubeprog --interface dfu`

烧录失败时会打印故障排查指南（USB 连接 / SWD 接线 / BOOT0 / RDP 解锁等）。

---

## 11. 串口数据引擎

### 启动守护进程

```bash
python {skill_dir}/scripts/serial_bridge.py --port COMx --baud 115200 &
python {skill_dir}/scripts/serial_bridge.py --status     # 查状态
python {skill_dir}/scripts/serial_bridge.py --list       # 列出可用 COM
python {skill_dir}/scripts/serial_bridge.py --stop       # 停止
```

### 读取（三种模式）

```bash
# 原始文本
python {skill_dir}/scripts/serial_bridge.py --tail 30

# 解析 key:value 或 key=value（推荐用于调参）
python {skill_dir}/scripts/serial_bridge.py --tail 20 --parse

# 纯数值数组（每行）
python {skill_dir}/scripts/serial_bridge.py --tail 10 --numbers
```

> `--parse` 只识别 `key=value` 或 `key: value` 这种格式。让板子打印 `dist=42, temp=24.5`
> 这种格式才好抽数据，**别**写 `距离 42 cm`。

### 主机 → 板子（下行）

```bash
# 发命令到板子（要求板子有简单命令解析）
python {skill_dir}/scripts/serial_bridge.py --send "set kp 1.5"
python {skill_dir}/scripts/serial_bridge.py --send "RAW_BYTES" --no-newline

# 等待板子复位完成（板子启动时输出 BOOT_OK 即可同步）
python {skill_dir}/scripts/serial_bridge.py --sync-on "BOOT_OK" --sync-timeout 5
```

### 闭环调参流程

```
启动 daemon
  ↓
sync-on "READY"          ← 跳过启动期残留
  ↓
tail --parse → 读当前值
  ↓
分析 → 改代码 #define 或参数
  ↓
编译 → 烧录 → 板子复位
  ↓
sync-on "READY" → tail --parse  ← 验证
  ↓
不满意就回头重新分析
```

---

## 12. HardFault 自动监控

如果板子可能崩溃，让它在 HardFault_Handler 里打印：

```c
void HardFault_Handler(void) {
    register uint32_t r0 __asm("r0");
    register uint32_t r1 __asm("r1");
    register uint32_t r2 __asm("r2");
    register uint32_t r3 __asm("r3");
    register uint32_t r12 __asm("r12");
    register uint32_t lr __asm("lr");
    register uint32_t pc __asm("pc");
    register uint32_t psr __asm("xpsr");
    printf("HardFault\r\nR0=0x%08X R1=0x%08X R2=0x%08X R3=0x%08X\r\n",
           r0, r1, r2, r3);
    printf("R12=0x%08X LR=0x%08X PC=0x%08X xPSR=0x%08X\r\n",
           r12, lr, pc, psr);
    printf("CFSR=0x%08X HFSR=0x%08X\r\n",
           (unsigned)SCB->CFSR, (unsigned)SCB->HFSR);
    while (1);
}
```

然后启动监控（要先有 daemon 在跑）：

```bash
python {skill_dir}/scripts/hardfault_watcher.py \
  --map {path}/Project/Listings/{name}.map
```

捕获到的崩溃会自动用 `hardfault_analyzer.py` 解析 PC → 函数符号 → 故障类型，并给出
建议（NULL pointer / 栈溢出 / 中断中再异常 / Bus/Usage/Memory fault 子类型等）。

---

## 13. RTT（可选，需要 J-Link）

板上没有空闲 USART 时可以用 RTT 通过 SWD 输出日志：

```bash
# 把 SEGGER_RTT.c/.h 模板放进工程
python {skill_dir}/scripts/rtt_helper.py emit --project {path}

# 把 SEGGER_RTT.c 加到 Keil 'Drive' 组（一次性）
python {skill_dir}/scripts/uvprojx_modifier.py add-group \
  --project {path}/Project/{name}.uvprojx \
  --name Drive \
  --files '[{"name":"SEGGER_RTT.c","path":"..\\\\Drive\\\\RTT\\\\SEGGER_RTT.c","type":"1"}]'

# 主机查看
python {skill_dir}/scripts/rtt_helper.py view --chip STM32F407ZGT6
```

代码里：

```c
#include "SEGGER_RTT.h"
SEGGER_RTT_Init();
SEGGER_RTT_printf(0, "tick=%u\n", HAL_GetTick());
```

> 这是精简实现，能跑通 J-Link RTT Viewer 的 printf。要完整功能就把 segger.com 上
> 官方版 SEGGER_RTT.zip 解压覆盖到 Drive/RTT/。

---

## 14. 调试支持

Keil 中按 **Ctrl+F5** 启动调试。常用快捷键：F9 设断点，F10 单步跨过，F11 单步进入，
Ctrl+F11 单步跳出，Ctrl+F10 运行到光标。

调试器：默认 ST-Link / SWD / 4MHz。在 `.uvoptx` 里改。

---

## 目录结构

```
{skill_dir}/
├── SKILL.md                 # 本文件
├── chip_db.json             # 芯片数据库（F1/F4/G4/L4/H7/C0）
├── data/                    # 引脚映射 JSON（F103/F407）
├── references/
│   ├── error_patterns.json  # 编译错误模式库
│   ├── STM32F103_reference_manual.pdf
│   └── STM32F407_reference_manual.pdf
├── scripts/
│   ├── project_creator.py     # 创建工程（含 --smoke-build）
│   ├── template_fetcher.py    # 下载 SPL/HAL/CMSIS 模板
│   ├── skeleton_manager.py    # 骨架管理
│   ├── uvprojx_modifier.py    # 改 .uvprojx
│   ├── keil_builder.py        # 编译 + Flash/RAM 占用率
│   ├── error_fixer.py         # 自动修错（dry-run / family-aware）
│   ├── flasher.py             # 多后端烧录
│   ├── dfp_checker.py         # DFP 预检
│   ├── ioc_parser.py          # CubeMX .ioc 导入
│   ├── pin_conflict_checker.py # 引脚冲突检查
│   ├── clock_config.py        # 时钟树计算
│   ├── dma_config.py          # DMA 通道分配
│   ├── pdf_reader.py          # 参考手册查询
│   ├── example_searcher.py    # 参考代码搜索
│   ├── serial_bridge.py       # 串口引擎（双向 + sync）
│   ├── serial_monitor.py      # 串口前台监控
│   ├── hardfault_analyzer.py  # 崩溃分析
│   ├── hardfault_watcher.py   # 自动捕获崩溃
│   └── rtt_helper.py          # RTT 模板 + viewer
└── skeleton/
    ├── f103/      # F103 SPL 模板
    ├── f407/      # F407 SPL 模板
    ├── hal_f103/  # F103 HAL 模板（懒加载）
    └── hal_f407/  # F407 HAL 模板（懒加载）
```

# mspm0g3519 — MSPM0G3519 + Keil MDK 全流程开发 Skill

完整的 MSPM0G3519 固件开发助手：建工程 → 配置外设 → 编写代码 → 编译（含占用率）
→ 自动修错 → 烧录（CMSIS-DAP） → 串口调参 → HardFault 分析。

芯片：TI MSPM0G3519（Cortex-M0+, LQFP-80）。

详细工作流见 [SKILL.md](SKILL.md)。

---

## 与 stm32-keil 的区别

| | **mspm0g3519** | **stm32-keil** |
|---|---|---|
| 芯片厂商 | TI | ST |
| 内核 | Cortex-M0+ | Cortex-M0/3/4/7 |
| 外设配置 | SysConfig (.syscfg JS) | CubeMX (.ioc) 或手动 |
| HAL 层 | TI DriverLib (dl_*.c) | ST SPL / HAL |
| 编译器 | ARMCLANG V6.24 | ARMCLANG V5/V6 均可 |
| 硬件固定引脚 | OLED/Keyboard 由 EVM 决定，不可改 | 无强制固定引脚 |
| 烧录后端 | CMSIS-DAP (uv4 -f) | ST-Link / J-Link / CubeProgrammer 多后端 |
| 支持型号 | 仅 MSPM0G3519 | F1/F4/G4/L4/H7/C0 多系列 |
| 工程模板 | 单骨架 + 按需复制 BSP | SPL/HAL 两套骨架，HAL 按系列下载 |
| 参考代码 | EVM_TEST_OLED 完整工程（17 外设） | 正点原子 70+ 实验例程 |

**何时用 mspm0g3519**：TI MSPM0G3519 开发板，需要 SysConfig 可视化配置引脚/时钟。

**何时用 stm32-keil**：STM32 系列芯片，使用 SPL 或 HAL 库，支持多型号、多烧录后端。

---

## 安装

### 1. 复制到 `~/.claude/skills/mspm0g3519/`

```
# Windows
xcopy /E /I mspm0g3519  %USERPROFILE%\.claude\skills\mspm0g3519

# Linux/macOS
cp -r mspm0g3519 ~/.claude/skills/
```

### 2. 安装 Python 依赖

```
pip install pyserial
```

### 3. 前置工具

| 工具 | 版本要求 | 说明 |
|------|----------|------|
| Keil MDK-ARM | v5.43+ | `uv4.exe` 需在 PATH 或自动检测 |
| TI DFP | MSPM0GX51X_DFP 1.0.0 | Keil Pack Installer 中安装 |
| MSPM0 SDK | 2.08.00.03 | `D:\ti\mspm0_sdk_2_08_00_03` |
| SysConfig | 1.25.0 | `D:\ti\sysconfig_1.25.0` |

SDK 和 SysConfig 路径自动搜索 `D:\ti\`, `C:\ti\`, 环境变量。搜不到会交互式询问。

---

## 使用

触发命令：`/mspm0g3519`

### 示例

```
/mspm0g3519 创建一个 LED 闪烁工程，放在 D:\Projects\
```

```
/mspm0g3519 创建 UART 回显工程，波特率 115200，使用 UART0
```

```
/mspm0g3519 创建多外设工程：OLED 显示 + UART0 printf 调试 + ADC0 采集 + RGB LED PWM
```

```
/mspm0g3519 写 OLED 和键盘的驱动，OLED 显示键值
```

---

## 工作流

```
 1. 确认需求（混合模式：简单全自动 / 复杂交互式）
 2. 检查工具链（Keil / SDK / SysConfig）
 3. 创建工程（骨架 + DriverLib 868 文件 + smoke build）
 4. 修改 syscfg（增删外设、配置引脚、时钟树）
 5. 生成 syscfg 代码（运行 syscfg_cli.bat）
 6. 编写代码（复制 BSP 驱动、生成 main.c、ISR）
 7. 代码质量检查（语法/逻辑/平台 三级，不可跳过）
 8. 编译（ARMCLANG V6.24，含 Flash/RAM 占用率）
 9. 自动修复编译错误（最多 5 轮）
10. 烧录（CMSIS-DAP，等待用户确认后执行）
11. 串口数据引擎（双向、可同步）
12. HardFault 自动监控（Cortex-M0+）
13. 调试支持
```

---

## 硬件固定引脚（不可修改）

以下引脚由 EVM 开发板硬件决定：

| 外设 | 引脚 | 说明 |
|------|------|------|
| OLED - SCLK | PB3 | SPI0 时钟 |
| OLED - MOSI | PB2 | SPI0 数据输出 |
| OLED - CS | PC9 | OLED 片选 |
| OLED - DC | PC8 | OLED 数据/命令 |
| OLED - RES | PB23 | OLED 复位 |
| Keyboard - H1~H4 | PB6, PB7, PB8, PB9 | 矩阵键盘行线 |
| Keyboard - V1~V4 | PB20, PB24, PB25, PB27 | 矩阵键盘列线 |
| Debug - SWCLK | PA20 | 调试时钟 |
| Debug - SWDIO | PA19 | 调试数据 |
| HFXT | PA5=HFXIN, PA6=HFXOUT | 40MHz 晶振 |

---

## 支持的外设

| 外设 | BSP 驱动 | syscfg 模块 |
|------|----------|-------------|
| GPIO LED | LED/ | GPIO |
| OLED (SPI0) | SPI0_OLED/ | GPIO + SPI |
| UART (0/1/4) | UART0/ | UART |
| printf redirect | UART0/ | UART |
| ADC (0/1) | ADC0/ | ADC12 |
| DAC | (syscfg only) | DAC12 |
| I2C | MYI2C1/ | I2C |
| SPI (1) | SPI1/ | SPI |
| SPI Flash (W25Q64) | W25Q64/ | SPI + GPIO |
| IMU (ICM-45686) | IMU/ | SPI + GPIO |
| RGB LED (PWM) | TimerG6_PWM_RGB/ | PWM |
| Buzzer | TimerG0_LED_BUZZER/ | PWM |
| Timer (TIMA1) | TimerA1/ | TIMER |
| Keyboard (4x4) | KeyBoard/ | GPIO |
| Key | KEY/ | GPIO |
| VREF | (syscfg only) | VREF |
| TRNG | (syscfg only) | TRNG |

---

## 脚本一览

| 脚本 | 用途 |
|------|------|
| `sdk_detector.py` | 自动检测 MSPM0 SDK + SysConfig 路径 |
| `project_creator.py` | 从骨架创建 Keil 工程 + DriverLib 复制 |
| `driverlib_manager.py` | DriverLib 文件列表（legacy，模板已内建） |
| `uvprojx_modifier.py` | 修改 .uvprojx XML 配置 |
| `syscfg_parser.py` | 解析/修改 syscfg JS 配置 |
| `syscfg_generator.py` | 运行 syscfg_cli.bat 生成 C 代码 |
| `code_writer.py` | 复制 BSP + 生成 main.c + printf + ISR |
| `code_checker.py` | 三级代码质量检查（语法/逻辑/平台） |
| `keil_builder.py` | uv4.exe 编译 + Flash/RAM 占用率 |
| `error_fixer.py` | 自动修复 ARMCLANG V6.24 编译错误 |
| `flasher.py` | CMSIS-DAP 烧录 |
| `serial_bridge.py` | 串口后台守护（双向） |
| `serial_monitor.py` | 串口前台监控 |
| `hardfault_analyzer.py` | Cortex-M0+ HardFault 寄存器分析 |
| `hardfault_watcher.py` | 串口 HardFault 自动捕获 |
| `clock_calculator.py` | 时钟树计算 (40MHz HFXT → 80MHz CPUCLK) |

---

## 芯片规格

- **型号**: MSPM0G3519
- **内核**: Cortex-M0+
- **封装**: LQFP-80(PN)
- **Flash**: 512 KB (0x00000000, 0x80000)
- **RAM**: 128 KB (Bank0 64KB + Bank1 64KB)
- **CPUCLK**: 80 MHz (40MHz HFXT → PLL x4 → /1)
- **MFPCLK**: 8 MHz (CPUCLK / 10)
- **编译器**: ARMCLANG V6.24

---

## 关键规则（开发时容易踩的坑）

1. **SysConfig 属性顺序**：`$name` 和 `peripheral.$assign` 必须写在最前面，否则引脚分配被静默忽略
2. **NVIC 双重使能**：`DL_xxx_enableInterrupt()` 后必须 `NVIC_EnableIRQ()`，缺一不可
3. **OLED 列地址 Bug**：`OLED_Set_Pos` 中 `(x & 0x0f) | 0x01` 必须改为 `| 0x00`
4. **OLED 页寻址**：SSD1306 写完一页后列回绕但页不递增，全屏刷新必须逐页写
5. **OLED 文字布局**：8×16 字体每字符占 2 pages，行间距必须 ≥2 pages
6. **LED 电平**：默认低电平点亮，高电平熄灭
7. **空 main() 陷阱**：骨架 main.c 的 while(1) 是空的，必须填充实际逻辑再编译烧录

---

## 分发给队友

将 `~/.claude/skills/mspm0g3519/` 目录复制到队友电脑相同位置即可。

队友需要：
1. 安装相同版本的 Keil DFP、MSPM0 SDK、SysConfig
2. `pip install pyserial`
3. 确认 CMSIS-DAP 调试器驱动正常

---

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| Keil 找不到 | 确保 `uv4.exe` 在 PATH 中或 `C:\Keil_v5\UV4` 下 |
| DFP 缺失 | 在 Keil Pack Installer 中搜索 MSPM0 安装 |
| SDK 找不到 | 设置环境变量 `MSPM0_SDK_PATH=D:\ti\mspm0_sdk_2_08_00_03` |
| SysConfig 版本不匹配 | 安装 `sysconfig_1.25.0` |
| CMSIS-DAP 连接失败 | 检查 USB 线、SWCLK(PA20)/SWDIO(PA19) 接线、板子供电 |
| 编译 0 错误但板子无效果 | main.c 的 while(1) 可能是空的 —— 运行代码质量检查 |
| 烧录报 "Target DLL cancelled" | 先在 Keil 中手动选一次 CMSIS-DAP 并点 OK |
| 按键无反应 | 检查 syscfg 中 GPIO 属性顺序（`$name` 必须在 `pin.$assign` 前） |

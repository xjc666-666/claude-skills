# Claude Skills

Claude Code 自定义技能集合。

---

## 技能列表

### stm32-keil — STM32 固件开发

STM32 全系列 Keil MDK 固件开发：SPL/HAL 工程 → 编译 → 自动修错 → 多后端烧录 → 串口监控。

| 项目 | 说明 |
|------|------|
| 芯片 | STM32 F1 / F4 |
| 触发 | `/stm32-keil` |
| 烧录 | ST-Link / J-Link |

### mspm0g3519 — MSPM0G3519 固件开发

TI MSPM0G3519 (Cortex-M0+) SysConfig 驱动开发全流程。

| 项目 | 说明 |
|------|------|
| 芯片 | MSPM0G3519 (LQFP-80) 启是科技开发板|
| 触发 | `/mspm0g3519` |
| 烧录 | CMSIS-DAP |

---

## 安装

```bash
git clone git@github.com:xjc666-666/claude-skills.git
cp -r claude-skills/stm32-keil ~/.claude/skills/
cp -r claude-skills/mspm0g3519 ~/.claude/skills/
```

### 前置依赖

- Keil MDK-ARM v5
- stm32-keil: 对应芯片 DFP
- mspm0g3519: MSPM0 SDK 2.08 + SysConfig 1.25.0 + TI DFP

---

## 使用示例

```bash
/stm32-keil 创建 LED 闪烁工程（工程需求）
/mspm0g3519 创建 OLED+键盘工程（工程需求）
```

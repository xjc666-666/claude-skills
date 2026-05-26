# stm32-keil — STM32 + Keil MDK 全流程开发 Skill

完整的 STM32 固件开发助手：建工程 → 编写代码 → 编译（含占用率） → 自动修错
→ 烧录（多后端） → 串口调参 → HardFault 分析 → RTT 日志。

支持系列：F1 / F4 / G4 / L4 / H7 / C0（HAL 系列要求 ST 仓库可访问以下载）

详细工作流见 [SKILL.md](SKILL.md)。

---

## 安装

### 1. 把这个目录复制到 `~/.claude/skills/stm32-keil/`

```
# Windows
xcopy /E /I stm32-keil  %USERPROFILE%\.claude\skills\stm32-keil

# Linux/macOS (理论支持但只测试过 Windows)
cp -r stm32-keil ~/.claude/skills/
```

### 2. 安装 Python 依赖

```
pip install -r requirements.txt
```

依赖：
- `pyserial` — 串口数据引擎（serial_bridge / serial_monitor）
- `PyMuPDF` — 参考手册查询（pdf_reader）

如果你不打算用串口或 PDF 查询，可以跳过对应包；其他脚本不依赖外部库，标准库即可。

### 3. 安装 Keil MDK-ARM v5

* 自动检测路径：环境变量 `KEIL_PATH` → 注册表 → 常见目录（`C:\Keil_v5`,
  `D:\Keil_v5`, `C:\keil\Keil_v5`, `Program Files\Keil_v5` 等） → `PATH`
* 没装会在编译/烧录时报错，**建工程本身不需要 Keil**
* 配套 DFP（如 `Keil.STM32F4xx_DFP`）必须通过 Keil Pack Installer 装上，否则
  Keil 编译会报 device 错误

### 4. （可选）安装烧录后端

按优先级自动选择第一个能找到的：

| 后端 | 何时用 | 安装地址 |
|---|---|---|
| **Keil 内置** | 默认，使用 .uvprojx 里配置的调试器 | 随 Keil |
| **STM32CubeProgrammer** | ST 官方，支持 ST-Link/J-Link/DFU | https://www.st.com/stm32cubeprog |
| **J-Link** | 用 Segger 调试器时 | https://www.segger.com/downloads/jlink |
| **ST-LINK_CLI** | 已弃用的 ST-Link Utility | 仅作 fallback |

---

## 兼容性

### 已测试

- Windows 11 + Keil MDK 5.43 + STM32F407ZGT6（端到端：建工程 → 编译 → 烧录 LED）

### 应该可用（未端到端验证）

- Windows 10 / 7
- 任意 F1/F4 SKU（chip_db.json 已含 11 颗常用型号）

### 不支持

- macOS / Linux：Keil 仅 Windows，烧录后端也都是 .exe；脚本本身大多跨平台，但
  没有 Keil 的话用处有限
- Keil µVision v4 及更早版本（.uvproj 旧格式不被解析器识别）

### 已知限制

- **DFP 必须装**：脚本能检测装在哪，但不会替你装。`dfp_checker.py --chip XXX`
  报缺时按提示去 Keil Pack Installer 装
- **HAL 模板需要联网**：第一次为某个系列建 HAL 工程会从 GitHub 下载 HAL 源码。
  国内访问慢时自动尝试 gh-proxy.com 镜像
- **PDF 参考手册仅含 F103/F407**：其他系列的查询返回 "manual not found"。可以
  手动放进 `references/` 并按 `STM32<系列>_reference_manual.pdf` 命名
- **skeleton/ 目录约 313 MB**：里面包含正点原子全套实验（70+ 个），是
  `example_searcher.py` 的外设参考代码库。**只需 F1/F4 SPL 模板的话**，可以删
  掉 `skeleton/stm32f407/` 和 `skeleton/stm32c8t6/`，保留 `skeleton/f103/` 和
  `skeleton/f407/` 即可（瘦身到约 30 MB）

---

## 分发给别人时的清单

1. 全部复制 `~/.claude/skills/stm32-keil/`
2. 让对方装 `requirements.txt`
3. 提醒装 Keil + 对应 DFP
4. 如果对方机器上 Keil 没在常见路径，让他们设 `KEIL_PATH` 环境变量指向 Keil 根目录（含 `UV4` 子目录）

### 不会自动同步的东西

- 你机器上的 Keil 安装路径（注册表 / 环境变量自动适应）
- 你的 ST-Link 配置（每个 .uvprojx 各自保存，新工程从模板继承）
- 串口默认 COM 口（serial_bridge 用 `--list` 让用户自行选）

### 可能要让对方手动调

- `chip_db.json` 没你要用的 SKU 时，照葫芦画瓢加一条（参考已有 F103/F407 条目）
- 用 ARMClang/ARMCC6 而不是 ARMCC5 时不需要手动改，错误解析已兼容两种格式
- ST-Link 驱动损坏时（DLL 报错）改用 STM32CubeProgrammer

---

## 开发说明

每个脚本都可以独立运行（带 `--help`），便于排查问题：

```
python scripts/dfp_checker.py --chip STM32F407ZGT6      # 检 DFP
python scripts/keil_builder.py --project path.uvprojx   # 单独编译
python scripts/flasher.py --project path.uvprojx        # 单独烧录
python scripts/serial_bridge.py --list                  # 列 COM
python scripts/clock_config.py --family F407 --code     # 算时钟树
```

跑端到端 smoke 测试（需要真实板子）：

```
python tests/smoke_test.py   # 假定测试目录为 D:\stm32-test\smoke
```

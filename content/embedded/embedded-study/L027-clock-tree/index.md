+++
title = "时钟树与外设时序来源"
date = "2026-10-11T23:29:07+08:00"
lastmod = "2026-10-11T23:29:07+08:00"
summary = "建立时钟树这一受约束频率分配网络的心智模型：用 Host Fake 审计源频率、PLL、AHB/APB 预分频和频率上限，再以 STM32F407xx 的 HSI 参考参数落实 CubeMX、HAL、LL、关键寄存器、ADC/DMA 与定时器时钟链。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 27
tags = ["clock-tree", "rcc", "pll", "sysclk", "hclk", "pclk", "clock-gating", "reset", "host-fake", "stm32f407", "cubemx", "hal", "ll", "registers", "c11"]
source_ids = ["st-rm0090-clock", "st-um1725-rcc", "st-ds8626-f407"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L027"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 27 课：时钟树与外设时序来源

UART 的波特率、定时器的周期、ADC 的转换节奏和 DMA 请求出现的速度，看起来属于不同外设，实际上都要先回答同一个问题：**驱动它的时钟从哪里来，沿途经过了哪些倍频、分频、门控和复位控制？** 如果这个问题答不清，代码中的 `168000000`、`42 MHz` 或某个预分频值就只是无法审计的魔法常数。

本课只推进一个核心概念：**时钟树**。时钟树是把振荡源经 PLL（phase-locked loop，锁相环）、总线预分频和门控，分配为内核、总线与外设工作时钟的受约束网络。

课程采用两条互不替代的轨道：

- Host Fake（主机替身）轨道把参数、公式、上限和错误路径写成不依赖芯片头文件的 C11 代码；
- STM32 参考轨道以 `STM32F407xx` 为目标，用内部 HSI 组成一套不依赖板级晶振的参考参数，并追到 CubeMX、HAL（hardware abstraction layer，硬件抽象层）、LL（low-layer，低层驱动）与关键寄存器。

当前没有具体开发板、完整料号、供电条件、CubeMX 工程、目标构建日志、烧录记录或测量结果。STM32 代码均是“参考实现，待目标工程编译”，`hardware_verified=false`；主机模型即使通过，也不能代替目标硬件证据。

## 1. 本节目标

完成本课后，你应能：

1. 从源频率逐级推导 PLL 输入、VCO、SYSCLK、HCLK、PCLK1、PCLK2 和外设输入时钟；
2. 区分预分频、时钟门控和外设复位，说明它们分别改变频率、可达性还是外设状态；
3. 用静态 C11 对象表达一份时钟方案，并在应用前检查整除关系、频率上限和错误路径；
4. 解释 STM32F407xx 上 HSI 16 MHz 到 168/42/84 MHz 的参考链，以及 APB 定时器时钟和 ADC 时钟如何继续派生；
5. 说明 `RCC_OscInitTypeDef`、`RCC_ClkInitTypeDef` 的字段、对象所有权、初始化顺序和 HAL 失败路径；
6. 从 HAL 操作追到 LL API 和 `RCC_CR`、`RCC_PLLCFGR`、`RCC_CFGR`、`FLASH_ACR`、门控/复位寄存器；
7. 分清 Host Fake 证明了什么、目标工程构建与上板测量还必须证明什么。

核心目标与计划一致：建立“时钟树”作为受约束频率分配与外设时序来源的心智模型，并以 STM32F407xx 完成待资料核对的双轨交付与验收设计。

## 2. 它解决什么问题

### 2.1 同一个配置错误为何会表现成不同故障

以下现象可能来自同一类根因：

- UART 实际波特率偏离预期，接收端持续报帧错误；
- 定时器周期恰好快一倍或慢一倍；
- ADC 配置能初始化，但转换时钟超过器件条件；
- DMA 已使能却没有计数变化，因为请求源没有工作；
- 外设寄存器写入似乎无效，因为对应总线门控尚未打开；
- 切换 SYSCLK 后程序不稳定，因为 Flash 等待周期或供电条件没有先满足。

逐个修改外设参数只能碰运气。时钟树把问题改写为一条可复核的因果链：

```text
源是否存在且稳定？
  -> PLL 输入、VCO 和输出是否合法？
  -> SYSCLK 是否真的切换到目标源？
  -> AHB/APB 预分频得到什么频率？
  -> 对应外设门控是否开启、复位是否释放？
  -> 外设还有没有自己的内核分频或时钟选择？
  -> 最终频率怎样进入波特率、周期、采样时间或请求节奏？
```

### 2.2 三种容易混淆的动作

| 动作 | 解决的问题 | 是否改变频率 | 典型结果 |
| --- | --- | --- | --- |
| 预分频 | 上游过快，需要按整数比例派生下游时钟 | 是 | `HCLK = SYSCLK / HPRE` |
| 时钟门控 | 空闲模块不应继续获得总线/内核时钟 | 通常不改比值，只决定是否送达 | 门控关闭时，软件不能把该外设视为可工作 |
| 外设复位 | 把外设寄存器和内部状态恢复到规定复位态 | 不用于计算频率 | 复位断言后必须释放，再重新初始化 |

门控不是“把频率变成 0 后继续按正常外设使用”，复位也不是一种分频。它们处在同一条控制链上，却承担不同责任。

### 2.3 本课边界

本课不展开 PLL 的模拟环路、电磁兼容、时钟安全系统、低功耗唤醒时钟、动态频率切换协议或 H7 多时钟域。它们会出现在后续调试、低功耗和系列差异课程。本课也不重新教授 DMA 或 ADC，只借用已完成的 `ADC1 -> DMA2` 路径说明“总线时钟、转换时钟和请求节奏不是同一个量”。

## 3. 必要前置知识

### 3.1 单位

- `1 Hz` 表示每秒一个周期；`1 MHz = 1,000,000 Hz`。
- 计算时统一使用 Hz，可避免 `16 MHz / 16` 与 `1,000,000 Hz` 混写造成单位错误。
- 频率经整数预分频器 `D` 后，结果为 `f_out = f_in / D`。

### 3.2 整数除法

C 的无符号整数除法会截去余数。若硬件模型要求得到整数 Hz，必须先检查余数，不能让 `17 / 2` 悄悄变成 `8`。本课 Host Fake 对每一级都做整除检查；这是一种模型约束，不表示所有真实 PLL 只能产生整数 Hz。

### 3.3 已学外设在本课中的位置

- 定时器课程已经使用“输入时钟 -> 预分频器 -> 计数器”的公式；本课负责追出那个输入时钟。
- UART、SPI、I2C 的速率配置都依赖总线或外设内核时钟；本课不重讲各自的波特率寄存器。
- ADC 课程已经说明采样与转换；本课追踪 ADC 公共预分频之前的 PCLK2。
- DMA 课程已经说明请求驱动；本课说明 DMA 总线门控只保证搬运引擎可访问，而请求速率来自 ADC 或其他请求源。

## 4. 核心原理

### 4.1 时钟树是一张受约束的有向网络

“树”强调从一个或多个源向下游分配，但 MCU 的完整时钟系统可能包含选择器、旁路和反馈 PLL，并不一定是数学上的纯树。对本课而言，可把一条选定路径看成有向链：每个节点只接受已经稳定的上游，执行选择、倍频、分频或门控，再把结果交给下游。

```text
source_hz
  -> / PLLM
  -> * PLLN                = VCO
  -> / PLLP                = SYSCLK
  -> / AHB divider         = HCLK
       -> / APB1 divider   = PCLK1
       -> / APB2 divider   = PCLK2
            -> / ADC div   = ADCCLK
```

每个箭头都附带约束：输入频率范围、允许的分频枚举、最大输出频率、源就绪状态和切换顺序。只有公式正确而约束不满足，配置仍然无效。

### 4.2 一份方案的五项责任

| 问题 | Host Fake | STM32F407xx 参考轨道 |
| --- | --- | --- |
| 它解决什么 | 把频率推导和越界检查变成可重复测试 | 把推导结果应用到 RCC、Flash 和外设门控 |
| 对象在哪里定义 | `clock_plan_t`、`clock_limits_t`、`clock_result_t` | 函数内的 `RCC_OscInitTypeDef`、`RCC_ClkInitTypeDef`，以及静态外设句柄 |
| 谁持有 | 测试/BSP 静态持有输入和结果 | 启动代码在调用期持有 RCC 配置对象；BSP 静态持有外设句柄和缓冲区 |
| 谁注入 | 测试把源、倍/除参数和上限传给计算函数 | `SystemClock_Config_Reference` 把参数提交给 HAL；CubeMX 配置决定生成值 |
| 调用如何流动 | 选择方案 -> 校验 -> 计算 -> 消费结果 | `HAL_Init` -> 配置电源/Flash/RCC -> 确认切换 -> 开门控/初始化外设 -> 启动数据路径 |

配置对象不是全局真理。Host Fake 的结果只在给定输入和限制下成立；STM32 HAL 的局部结构体也只在函数调用期间存在，HAL 把字段转成寄存器配置后不要求调用者长期保存它们。外设句柄则不同：中断和 DMA 回调还要使用它们，因此通常由 BSP 静态持有整个运行期。

### 4.3 先验证，再应用

安全的顺序不是“先切到高速，再看是否报错”，而是：

1. 明确源频率和目标频率；
2. 检查 PLL 输入、VCO、总线和外设限制；
3. 先满足供电调压与 Flash 等待周期要求；
4. 启动源并等待 ready（就绪）状态；
5. 启动 PLL 并等待锁定；
6. 写入预分频；
7. 切换 SYSCLK，并读取状态位确认实际源；
8. 对需要的外设开启门控、按需执行复位脉冲；
9. 初始化和启动外设；
10. 通过寄存器、系统变量或测量手段核对结果。

这也是错误路径的骨架。任何 ready 超时、HAL 返回非 `HAL_OK`、状态位不匹配或计算越界，都应停止向后初始化，并保存发生在哪一级。

## 5. 关键术语与直观模型

| 术语 | 中文解释 | 在本课中的作用 |
| --- | --- | --- |
| HSI | high-speed internal，高速内部振荡器 | F407 参考方案的 16 MHz 源，不依赖板级晶振 |
| HSE | high-speed external，高速外部时钟/振荡源 | 需要板级晶振或外部时钟条件，本课不假定存在 |
| PLL | 锁相环 | 通过 M/N/P 参数从源派生高速系统时钟 |
| VCO | voltage-controlled oscillator，压控振荡器 | PLL 内部倍频节点，必须满足器件规定范围 |
| RCC | reset and clock control，复位与时钟控制器 | 选择、分配、门控时钟并控制外设复位 |
| SYSCLK | system clock，系统时钟 | 系统时钟选择器的输出 |
| HCLK | AHB 总线/内核相关时钟 | 由 SYSCLK 经 AHB 预分频得到 |
| PCLK1/PCLK2 | APB1/APB2 外设总线时钟 | 分别由 HCLK 经 APB 预分频得到 |
| TIMxCLK | 定时器内核输入时钟 | F407 上还受 APB 预分频对应的定时器规则影响 |
| ADCCLK | ADC 转换时钟 | F407 上由 PCLK2 经 ADC 公共预分频得到 |
| clock gating | 时钟门控 | 决定时钟是否送到某个外设/总线接口 |
| reset | 复位 | 把模块恢复到文档规定状态，不等同于关时钟 |
| Flash latency | Flash 等待周期 | 高频运行时 CPU 等待 Flash 数据有效所需的周期配置 |

直观上，源像供水端，PLL 与预分频像受约束的变速箱，门控像阀门，复位像把设备控制状态恢复初始位置。这个比喻只帮助区分角色；最终判断仍以频率公式、状态位和手册限制为准。

## 6. 从输入到结果的完整流程

以本课参考参数为例，先只做数学推导：

```text
HSI = 16,000,000 Hz

PLL input = HSI / PLLM
          = 16,000,000 / 16
          = 1,000,000 Hz

VCO       = PLL input * PLLN
          = 1,000,000 * 336
          = 336,000,000 Hz

SYSCLK    = VCO / PLLP
          = 336,000,000 / 2
          = 168,000,000 Hz

HCLK      = SYSCLK / HPRE
          = 168,000,000 / 1
          = 168,000,000 Hz

PCLK1     = HCLK / PPRE1
          = 168,000,000 / 4
          = 42,000,000 Hz

PCLK2     = HCLK / PPRE2
          = 168,000,000 / 2
          = 84,000,000 Hz
```

再从总线继续追到具体使用者：

```text
APB1 timer input = 2 * PCLK1 = 84 MHz
APB2 timer input = 2 * PCLK2 = 168 MHz
ADC clock        = PCLK2 / 4 = 21 MHz
DMA2 interface   = AHB1 branch, HCLK = 168 MHz, and DMA2 gate enabled
```

上面的定时器倍频规则限定于 RM0090 所覆盖的 F407 参考目标和当前 APB 预分频不为 1 的条件：当对应 APB 预分频为 1 时，该域定时器时钟等于 PCLK；不为 1 时为 `2 * PCLK`。[S1] 迁移到其他系列时不能只复制这个公式，必须重新查看目标器件的时钟树、定时器时钟选择和可能存在的额外控制位。

调用流如下：

```text
应用/BSP 选择参数
  -> clock_tree_calculate() 纯计算并检查约束
  -> 得到 SYSCLK/HCLK/PCLK/外设输入时钟
  -> SystemClock_Config_Reference() 按安全顺序写硬件
  -> HAL_RCC_ClockConfig() 返回状态
  -> 读取 SWS/ready 位或 HAL 频率函数核对
  -> MX_DMA_Init()/MX_ADC1_Init() 开门控并配置外设
  -> HAL_ADC_Start_DMA() 启动请求链
  -> DMA IRQ -> HAL_DMA_IRQHandler() -> ADC 回调/错误记录
```

注意最后三步不是在说“DMA 的采样率等于 HCLK”。HCLK 和 DMA2 门控让搬运引擎能够访问总线；ADC 的 ADCCLK、采样时间、转换周期和触发方式决定请求何时产生；DMA 只能响应已有请求。

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

| 层级 | 时钟主题能力 | 信号/控制路径 | 本课与后续落点 |
| --- | --- | --- | --- |
| 基础 | HSI/HSE、PLL、SYSCLK、AHB/APB 预分频、门控、复位 | 源 -> PLL -> SYSCLK -> HCLK/PCLK -> 外设 | 本课完整建立推导、配置与审计闭环 |
| 进阶 | 外设专用时钟、定时器时钟、Flash 等待周期、MCO 时钟输出 | 总线时钟 -> 外设选择/分频；内部时钟 -> MCO 引脚 | 本课深入 ADC/定时器；MCO 测量在硬件实验中作为可选手段 |
| 高级 | 动态切换、时钟故障检测、多时钟域、低功耗源 | 故障/电源事件 -> 时钟控制 -> 中断或回退路径 | `low-power`、`fault-analysis` 和系列比较课程深入 |
| 跨外设联动 | Timer TRGO -> ADC -> DMA；UART/SPI 速率依赖 PCLK | timer clock -> TRGO -> ADC conversion -> DMA request -> IRQ | 本课只追时钟与请求节奏，`timer-trigger-routing` 和 `adc-timer-dma-pipeline` 实现完整链 |
| 系列差异 | F4/F7/H5/H7 的时钟域、选择器、最高频率、供电/Flash/缓存约束 | 各系列 RCC/PWR/FLASH 与总线域不同 | 本课只断言 F407；迁移时按具体器件重建整条链 |

高级能力不能只记名称。例如动态切换解决“性能和功耗需求随运行阶段变化”的问题，其控制链至少包含：先把新源启动并等待稳定 -> 调整电压与 Flash 条件 -> 切换系统源并确认状态 -> 重新审计受影响的外设时序。时钟故障检测则要把外部源故障事件、RCC 状态/中断、回退源和应用降级策略连接起来。二者都会改变全系统假设，因此不在本课用一段寄存器代码草率展开。

系列迁移表：

| 系列 | 可迁移机制 | 必须按具体器件资料重查 |
| --- | --- | --- |
| F4 | 源稳定后再切换、逐级算频率、门控/复位分离、外设最终分频 | F407 之外型号的上限、PLL 组合、定时器规则、外设所在总线 |
| F7 | 同一套审计方法仍成立 | RCC/PWR/Flash 条件、缓存影响、具体总线和专用时钟选择 |
| H5 | 同一套审计方法仍成立 | 新的电源/安全边界、时钟选择器、DMA 请求结构和寄存器布局 |
| H7 | 同一套审计方法仍成立 | 多时钟域、域间总线、内存/缓存、电源与特定内核时钟选择 |

本表没有宣称各系列的具体频率或寄存器编号；未选定完整器件前，这些都属于目标迁移时的资料核对项。

### 7.2 参考目标与时钟/复位链

参考器件为 `STM32F407xx`，寄存器与时钟树依据 RM0090 Rev 22，HAL/LL API 依据 UM1725 Rev 8，工作条件依据 DS8626 Rev 12。[S1][S2][S3] 尚未选定完整订货料号和封装，因此不声明引脚、外部晶振、供电网络或板级测量点。

本课选 HSI 的理由是它不依赖板卡是否焊接特定晶振。参考参数如下：

| 节点/控制 | 参数 | 结果或责任 |
| --- | --- | --- |
| HSI | 16 MHz | 主 PLL 源；先开启并等待 `HSIRDY` |
| PLLM | 16 | PLL 输入 1 MHz |
| PLLN | 336 | VCO 336 MHz |
| PLLP | 2 | SYSCLK 候选 168 MHz |
| PLLQ | 7 | 参考配置保留 48 MHz PLLQ 输出；本课不启动依赖它的外设 |
| HPRE | 1 | HCLK 168 MHz |
| PPRE1 | 4 | PCLK1 42 MHz |
| PPRE2 | 2 | PCLK2 84 MHz |
| ADC prescaler | 4 | ADCCLK 21 MHz |
| Voltage scale | Scale 1（`PWR_CR.VOS=1`） | 支持 HCLK 168 MHz 的参考调压档位 |
| VDD reference condition | 2.7 V 至 3.6 V | 本例 `FLASH_LATENCY_5` 的前置条件；不是对实际板卡的声明 |

RM0090 给出 F407 主 PLL 的参数字段和时钟树约束。DS8626 Rev 12 表 14 给出 `VOS=1` 时 HCLK 上限 168 MHz、PCLK1 上限 42 MHz、PCLK2 上限 84 MHz；表 15 给出 VDD 2.7 V 至 3.6 V 时 168 MHz Flash 访问需要 5 wait states。[S1][S3] 因此本课代码是一组带明确供电前置条件的参考参数，不是对未知板卡供电的事实声明。若实际 VDD 不在该区间，必须按数据手册重新选择 Flash latency；不得仅因 HAL 接受参数，就把电气条件视为已满足。

完整控制链：

```text
PWR interface gate
  -> voltage scale condition（板级供电与完整料号必须核对）
FLASH_ACR.LATENCY
  -> 在提高 HCLK 前设到匹配等待周期
RCC_CR.HSION -> RCC_CR.HSIRDY
  -> HSI 可作为 PLL 输入
RCC_PLLCFGR.PLLSRC/PLLM/PLLN/PLLP/PLLQ
RCC_CR.PLLON -> RCC_CR.PLLRDY
  -> PLL 输出稳定
RCC_CFGR.HPRE/PPRE1/PPRE2
RCC_CFGR.SW = PLL -> 检查 RCC_CFGR.SWS = PLL
  -> SYSCLK/HCLK/PCLK 生效
RCC_AHB1ENR.DMA2EN
  -> DMA2 总线接口得到时钟
RCC_APB2ENR.ADC1EN
  -> ADC1 接口得到时钟
ADC_CCR.ADCPRE = /4
  -> ADCCLK = 21 MHz
按需 RCC_AHB1RSTR.DMA2RST / RCC_APB2RSTR.ADC1RST 断言后释放
  -> 再执行外设初始化
```

复位链中的“断言后释放”很重要：一直保持复位时，外设不能运行；只开门控但不从异常状态恢复，也不等于完成复位。HAL 的 `__HAL_RCC_<PERIPH>_FORCE_RESET()` / `RELEASE_RESET()` 或对应 LL 调用应成对使用，并由拥有该外设初始化流程的 BSP 负责。

#### F407 参数合法性检查

对 F407 主 PLL，应用配置前至少要按 RM0090 的主 PLL 章节检查 `PLLM`/`PLLN`/`PLLP`/`PLLQ` 编码，并按 DS8626 Rev 12 表 36 检查 PLL 输入 0.95 至 2.10 MHz、VCO 输出 100 至 432 MHz、PLL 输出不超过 168 MHz。[S1][S3] 本例得到 1/336/168 MHz，落在这些范围内；代码还用显式上限检查最终总线和 ADC 结果。若改动参数或供电条件，应回到完整料号数据手册重新确认。这里不把一个参考参数集推广成所有 F4 器件、所有电压范围都有效的结论。

### 7.3 CubeMX、HAL、LL 与寄存器对照

#### CubeMX/CubeMX2 配置清单

在实际操作时先选择完整 STM32F407 料号，再记录工具版本和 STM32CubeF4 固件包版本。当前仓库没有这些运行证据，所以下列是配置清单，不是生成结果：

1. `RCC`: HSI 保持开启；不启用未确认存在的 HSE/LSE 板级源。
2. `Clock Configuration`: PLL source=HSI，`PLLM=16`、`PLLN=336`、`PLLP=2`、`PLLQ=7`。
3. `SYSCLK Source`: PLLCLK；AHB prescaler `/1`；APB1 `/4`；APB2 `/2`。
4. `System Core/PWR`: 本例在 VDD 2.7 V 至 3.6 V 的前提下选择 Voltage Scale 1 与 5 wait states；实际 VDD 不满足时必须按 DS8626 表 14/15 重算，不得照抄。[S3]
5. `ADC1`: 若复现实验，选择一个按封装/板卡核对过的 ADC 通道；ADC common prescaler `/4`。
6. `DMA2`: 若复用上一课路径，ADC1 选择 DMA2 Stream0/Channel0、peripheral-to-memory、half-word、memory increment、circular；映射只适用于当前 F407 参考目标。[S1]
7. `NVIC`: 开启 DMA2 Stream0 IRQ；是否开启 ADC IRQ取决于是否需要 ADC 错误中断路径。
8. 生成后检查 `.ioc`、`SystemClock_Config`、`HAL_RCC_MspInit`、`HAL_ADC_MspInit`、DMA 链接和 IRQ 文件，不机械覆盖用户代码区。

板级参数包括完整料号、ADC 引脚、输入电压、调试器、MCO 引脚和外部测量设备；这些均由实施者根据实际板卡填写，课程不虚构。

#### HAL 配置对象与错误路径

`RCC_OscInitTypeDef` 描述振荡源和 PLL：

| 字段 | 本例值 | 含义 |
| --- | --- | --- |
| `OscillatorType` | `RCC_OSCILLATORTYPE_HSI` | 本次要配置 HSI |
| `HSIState` | `RCC_HSI_ON` | 开启 HSI |
| `HSICalibrationValue` | `RCC_HSICALIBRATION_DEFAULT` | 使用 HAL 默认校准值；精度要求仍由数据手册和测量确认 |
| `PLL.PLLState` | `RCC_PLL_ON` | 开启主 PLL |
| `PLL.PLLSource` | `RCC_PLLSOURCE_HSI` | PLL 输入选择 HSI |
| `PLL.PLLM/N/P/Q` | `16/336/2/7` | 分频、倍频、系统输出和 48 MHz 域输出参数 |

`RCC_ClkInitTypeDef` 描述系统和总线分配：

| 字段 | 本例值 | 含义 |
| --- | --- | --- |
| `ClockType` | SYSCLK/HCLK/PCLK1/PCLK2 位组合 | 指明本次会修改哪些时钟 |
| `SYSCLKSource` | `RCC_SYSCLKSOURCE_PLLCLK` | 系统时钟选择 PLL |
| `AHBCLKDivider` | `RCC_SYSCLK_DIV1` | HCLK=SYSCLK |
| `APB1CLKDivider` | `RCC_HCLK_DIV4` | PCLK1=HCLK/4 |
| `APB2CLKDivider` | `RCC_HCLK_DIV2` | PCLK2=HCLK/2 |

两个结构体是函数内自动对象，由 `SystemClock_Config_Reference` 在调用期间持有并注入 HAL。它们不是供 IRQ 长期访问的句柄。HAL RCC 函数内部等待 ready/切换状态并返回 `HAL_StatusTypeDef`；调用者必须传播 `HAL_ERROR` 或 `HAL_TIMEOUT`，不能无条件继续初始化外设。[S2]

#### HAL 到 LL/关键寄存器对照

| 意图 | HAL 入口 | LL 入口示例 | F407 关键寄存器/状态 |
| --- | --- | --- | --- |
| 开启并等待 HSI | `HAL_RCC_OscConfig` 的 HSI 字段 | `LL_RCC_HSI_Enable` / `LL_RCC_HSI_IsReady` | `RCC_CR.HSION/HSIRDY` |
| 配置主 PLL | `HAL_RCC_OscConfig` 的 PLL 字段 | `LL_RCC_PLL_ConfigDomain_SYS` | `RCC_PLLCFGR.PLLSRC/PLLM/N/P/Q` |
| 开启并等待 PLL | `HAL_RCC_OscConfig` | `LL_RCC_PLL_Enable` / `LL_RCC_PLL_IsReady` | `RCC_CR.PLLON/PLLRDY` |
| 设置 Flash 等待周期 | `HAL_RCC_ClockConfig(..., FLASH_LATENCY_5)` | `LL_FLASH_SetLatency` | `FLASH_ACR.LATENCY` |
| 设置 AHB/APB 分频 | `HAL_RCC_ClockConfig` | `LL_RCC_SetAHBPrescaler`、`LL_RCC_SetAPB1Prescaler`、`LL_RCC_SetAPB2Prescaler` | `RCC_CFGR.HPRE/PPRE1/PPRE2` |
| 切换并确认 SYSCLK | `HAL_RCC_ClockConfig` | `LL_RCC_SetSysClkSource` / `LL_RCC_GetSysClkSource` | `RCC_CFGR.SW/SWS` |
| DMA2 门控/复位 | `__HAL_RCC_DMA2_CLK_ENABLE` 等 | `LL_AHB1_GRP1_EnableClock` 等 | `RCC_AHB1ENR.DMA2EN`、`RCC_AHB1RSTR.DMA2RST` |
| ADC1 门控/复位 | `__HAL_RCC_ADC1_CLK_ENABLE` 等 | `LL_APB2_GRP1_EnableClock` 等 | `RCC_APB2ENR.ADC1EN`、`RCC_APB2RSTR.ADC1RST` |
| ADC 公共分频 | ADC HAL 初始化字段 | 对应 LL ADC common 配置 | `ADC_CCR.ADCPRE` |

LL 函数名来自 UM1725 Rev 8 的 STM32F4 API 表面，但具体宏是否存在、参数名称和所在头文件必须与实际选用的 STM32CubeF4 包核对。[S2] 不允许由 HAL 和 LL 同时拥有同一组 RCC 配置：LL 在本课主要用于解释和调试读取；若改为 LL-only 实现，应把完整顺序和超时责任一并迁移。

#### IRQ/DMA 与时钟错误路径

复用 ADC1-DMA2 的观察链时，角色必须分开：

```text
PCLK2 -> ADC common /4 -> ADCCLK
  -> ADC 采样与转换完成
  -> ADC1 产生 DMA request

HCLK -> AHB1 -> DMA2 gate
  -> DMA2 响应 request，搬运 ADC1_DR 到 SRAM
  -> HT/TC/TE 标志
  -> DMA2_Stream0_IRQHandler
  -> HAL_DMA_IRQHandler(&hdma_adc1)
  -> HAL_ADC_ConvHalfCpltCallback / ConvCpltCallback / ErrorCallback
```

若 ADC 门控关闭、仍在复位、ADCCLK 配置错误或转换没有启动，DMA 侧可能表现为 `NDTR` 不变且没有 HT/TC 中断；这不等于 DMA 自己的 HCLK 太慢。若 DMA2 门控未开，则 DMA 寄存器初始化/访问和搬运路径本身不成立。若 IRQ handler 没有交给正确句柄，硬件标志可能出现但 HAL 回调不执行。

建议把错误证据保存在静态诊断对象，由 ISR 只写快照，主循环解释：

```c
typedef struct {
    volatile uint32_t dma_irq_count;
    volatile uint32_t half_count;
    volatile uint32_t full_count;
    volatile uint32_t adc_error;
    volatile uint32_t dma_error;
} clock_path_diag_t;

static clock_path_diag_t g_clock_path_diag;

void DMA2_Stream0_IRQHandler(void)
{
    g_clock_path_diag.dma_irq_count++;
    HAL_DMA_IRQHandler(&hdma_adc1);
}

void ADC_IRQHandler(void)
{
    HAL_ADC_IRQHandler(&hadc1);
}

void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1) {
        g_clock_path_diag.half_count++;
    }
}

void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1) {
        g_clock_path_diag.full_count++;
    }
}

void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1) {
        g_clock_path_diag.adc_error = HAL_ADC_GetError(hadc);
        if (hadc->DMA_Handle != NULL) {
            g_clock_path_diag.dma_error = HAL_DMA_GetError(hadc->DMA_Handle);
        }
    }
}
```

这段代码属于 STM32 目标适配/诊断层，依赖 HAL 句柄，生命周期覆盖整个运行期；它是参考实现，待目标工程编译。回调中只计数和保存错误，不打印、不重配 RCC，也不直接重启整条链。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

Host Fake 能验证：

- 每一级频率公式和单位；
- 零除数、非整除、32 位结果溢出和超过显式上限时返回确定错误；
- APB 预分频为 1 与不为 1 时，所注入的 F407 定时器规则得到预期结果；
- 配置与结果对象的静态所有权，不依赖动态内存。

它不能验证：HSI 的真实精度、PLL 是否锁定、Flash/供电条件、寄存器位布局、目标头文件宏、晶振质量、板级时钟输出或外设实际时序。

### 8.2 STM32 参考实现轨道

参考实现提供：

- HSI 16 MHz 到 168/42/84/21 MHz 的完整参数和公式；
- CubeMX 配置检查清单；
- 可移入 STM32CubeF4 工程的 HAL 时钟配置函数；
- LL/寄存器对照；
- ADC1 -> DMA2 IRQ/回调/错误观察路径；
- 构建、烧录和测量步骤。

仍由板卡决定的项目：完整料号、VDD、封装、ADC 引脚、MCO 引脚、探头与外部电路。仍由工程版本决定的项目：CubeMX/CubeMX2 版本、STM32CubeF4 包版本、HAL/LL 宏和启动文件。课程不给这些项目编造默认值。

证据分级：

| 证据 | 能证明 | 不能证明 |
| --- | --- | --- |
| Host Fake 断言 | 公式、边界和错误返回符合模型 | F407 寄存器和硬件时序 |
| CubeMX 时钟图/生成代码 | 工具根据所选版本接受并生成配置 | 固件已经构建、板卡电气条件满足 |
| 目标构建日志和 map | 头文件/API/链接在该工程成立 | PLL 已锁定、频率准确 |
| 调试器寄存器快照 | 运行时寄存器和状态位取值 | 引脚波形的频率精度 |
| MCO/定时器/串口测量 | 指定观察点的实际时序 | 未被观察的所有支路都正确 |

## 9. 最小代码示例

### 9.1 Host Fake：静态 C11 频率审计器

下面是一个完整单文件示例。它属于主机机制验证层，只依赖 C11 标准库，不使用动态内存。公开结构字段使用固定宽度整数；调用者持有配置、限制和结果对象，并把它们注入纯计算函数。

```c
#include <assert.h>
#include <stdint.h>
#include <stdio.h>

typedef enum {
    CLOCK_OK = 0,
    CLOCK_ERR_ARGUMENT,
    CLOCK_ERR_ZERO,
    CLOCK_ERR_NOT_INTEGRAL,
    CLOCK_ERR_OVERFLOW,
    CLOCK_ERR_LIMIT
} clock_status_t;

typedef struct {
    uint32_t source_hz;
    uint16_t pll_m;
    uint16_t pll_n;
    uint16_t pll_p;
    uint16_t ahb_div;
    uint16_t apb1_div;
    uint16_t apb2_div;
    uint16_t adc_div;
    uint8_t timer_multiplier_when_apb_divided;
} clock_plan_t;

typedef struct {
    uint32_t max_sysclk_hz;
    uint32_t max_hclk_hz;
    uint32_t max_pclk1_hz;
    uint32_t max_pclk2_hz;
    uint32_t max_adc_hz;
} clock_limits_t;

typedef struct {
    uint32_t pll_input_hz;
    uint32_t vco_hz;
    uint32_t sysclk_hz;
    uint32_t hclk_hz;
    uint32_t pclk1_hz;
    uint32_t pclk2_hz;
    uint32_t timer_apb1_hz;
    uint32_t timer_apb2_hz;
    uint32_t adc_hz;
} clock_result_t;

static clock_status_t exact_div_u64(uint64_t numerator,
                                    uint32_t denominator,
                                    uint32_t *result)
{
    uint64_t quotient;

    if ((denominator == 0U) || (result == NULL)) {
        return CLOCK_ERR_ZERO;
    }
    if ((numerator % denominator) != 0U) {
        return CLOCK_ERR_NOT_INTEGRAL;
    }
    quotient = numerator / denominator;
    if (quotient > UINT32_MAX) {
        return CLOCK_ERR_OVERFLOW;
    }
    *result = (uint32_t)quotient;
    return CLOCK_OK;
}

static clock_status_t timer_clock(uint32_t pclk_hz,
                                  uint16_t apb_div,
                                  uint8_t divided_multiplier,
                                  uint32_t *result)
{
    uint64_t value = pclk_hz;

    if (result == NULL) {
        return CLOCK_ERR_ARGUMENT;
    }
    if (apb_div != 1U) {
        value *= divided_multiplier;
    }
    if (value > UINT32_MAX) {
        return CLOCK_ERR_OVERFLOW;
    }
    *result = (uint32_t)value;
    return CLOCK_OK;
}

clock_status_t clock_tree_calculate(const clock_plan_t *plan,
                                    const clock_limits_t *limits,
                                    clock_result_t *result)
{
    clock_result_t next = {0};
    clock_status_t status;
    uint64_t vco;

    if ((plan == NULL) || (limits == NULL) || (result == NULL)) {
        return CLOCK_ERR_ARGUMENT;
    }
    if ((plan->source_hz == 0U) ||
        (plan->pll_m == 0U) || (plan->pll_n == 0U) ||
        (plan->pll_p == 0U) || (plan->ahb_div == 0U) ||
        (plan->apb1_div == 0U) || (plan->apb2_div == 0U) ||
        (plan->adc_div == 0U) ||
        (plan->timer_multiplier_when_apb_divided == 0U)) {
        return CLOCK_ERR_ZERO;
    }

    status = exact_div_u64(plan->source_hz,
                           plan->pll_m,
                           &next.pll_input_hz);
    if (status != CLOCK_OK) {
        return status;
    }

    vco = (uint64_t)next.pll_input_hz * plan->pll_n;
    if (vco > UINT32_MAX) {
        return CLOCK_ERR_OVERFLOW;
    }
    next.vco_hz = (uint32_t)vco;

    status = exact_div_u64(vco, plan->pll_p, &next.sysclk_hz);
    if (status != CLOCK_OK) {
        return status;
    }
    status = exact_div_u64(next.sysclk_hz,
                           plan->ahb_div,
                           &next.hclk_hz);
    if (status != CLOCK_OK) {
        return status;
    }
    status = exact_div_u64(next.hclk_hz,
                           plan->apb1_div,
                           &next.pclk1_hz);
    if (status != CLOCK_OK) {
        return status;
    }
    status = exact_div_u64(next.hclk_hz,
                           plan->apb2_div,
                           &next.pclk2_hz);
    if (status != CLOCK_OK) {
        return status;
    }
    status = timer_clock(next.pclk1_hz,
                         plan->apb1_div,
                         plan->timer_multiplier_when_apb_divided,
                         &next.timer_apb1_hz);
    if (status != CLOCK_OK) {
        return status;
    }
    status = timer_clock(next.pclk2_hz,
                         plan->apb2_div,
                         plan->timer_multiplier_when_apb_divided,
                         &next.timer_apb2_hz);
    if (status != CLOCK_OK) {
        return status;
    }
    status = exact_div_u64(next.pclk2_hz,
                           plan->adc_div,
                           &next.adc_hz);
    if (status != CLOCK_OK) {
        return status;
    }

    if ((next.sysclk_hz > limits->max_sysclk_hz) ||
        (next.hclk_hz > limits->max_hclk_hz) ||
        (next.pclk1_hz > limits->max_pclk1_hz) ||
        (next.pclk2_hz > limits->max_pclk2_hz) ||
        (next.adc_hz > limits->max_adc_hz)) {
        return CLOCK_ERR_LIMIT;
    }

    *result = next;
    return CLOCK_OK;
}

int main(void)
{
    static const clock_plan_t reference_plan = {
        16000000U, 16U, 336U, 2U, 1U, 4U, 2U, 4U, 2U
    };
    static const clock_limits_t reference_limits = {
        168000000U, 168000000U, 42000000U, 84000000U, 36000000U
    };
    clock_result_t result = {0};
    clock_plan_t bad_plan = reference_plan;

    assert(clock_tree_calculate(&reference_plan,
                                &reference_limits,
                                &result) == CLOCK_OK);
    assert(result.pll_input_hz == 1000000U);
    assert(result.vco_hz == 336000000U);
    assert(result.sysclk_hz == 168000000U);
    assert(result.hclk_hz == 168000000U);
    assert(result.pclk1_hz == 42000000U);
    assert(result.pclk2_hz == 84000000U);
    assert(result.timer_apb1_hz == 84000000U);
    assert(result.timer_apb2_hz == 168000000U);
    assert(result.adc_hz == 21000000U);

    bad_plan.apb1_div = 2U;
    assert(clock_tree_calculate(&bad_plan,
                                &reference_limits,
                                &result) == CLOCK_ERR_LIMIT);

    bad_plan = reference_plan;
    bad_plan.source_hz = 17000001U;
    assert(clock_tree_calculate(&bad_plan,
                                &reference_limits,
                                &result) == CLOCK_ERR_NOT_INTEGRAL);

    bad_plan = reference_plan;
    bad_plan.pll_m = 0U;
    assert(clock_tree_calculate(&bad_plan,
                                &reference_limits,
                                &result) == CLOCK_ERR_ZERO);

    puts("clock tree model: all checks passed");
    return 0;
}
```

这段 Fake 有意把限制对象与方案对象分开：公式是可迁移机制，`reference_limits` 和“APB 分频后乘 2”的参数是目标策略。迁移到另一器件时，必须从该器件资料重新注入上限和规则。Fake 没有穷举 F407 所有允许的预分频编码；把方案写入硬件前，还要由目标适配层检查枚举是否可编码。

推荐主机编译命令：

```text
cc -std=c11 -Wall -Wextra -Werror -pedantic clock_tree_fake.c -o clock_tree_fake
./clock_tree_fake
```

预期标准输出为 `clock tree model: all checks passed`。这是待学习者执行并保存的主机实验预期，不是本课声称已经产生的运行记录。

### 9.2 STM32F407 HAL 参考实现

以下函数属于目标 BSP/启动配置层，依赖实际 STM32CubeF4 HAL 头文件。它不假定板级 HSE，引入明确返回值而不是在函数内部吞掉错误。代码的前置条件是实际目标经核对满足 VDD 2.7 V 至 3.6 V；否则 `FLASH_LATENCY_5` 不能直接使用。代码是参考实现，待目标工程编译。

```c
static HAL_StatusTypeDef SystemClock_Config_Reference(void)
{
    RCC_OscInitTypeDef osc = {0};
    RCC_ClkInitTypeDef clk = {0};
    HAL_StatusTypeDef status;

    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

    osc.OscillatorType = RCC_OSCILLATORTYPE_HSI;
    osc.HSIState = RCC_HSI_ON;
    osc.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
    osc.PLL.PLLState = RCC_PLL_ON;
    osc.PLL.PLLSource = RCC_PLLSOURCE_HSI;
    osc.PLL.PLLM = 16U;
    osc.PLL.PLLN = 336U;
    osc.PLL.PLLP = RCC_PLLP_DIV2;
    osc.PLL.PLLQ = 7U;

    status = HAL_RCC_OscConfig(&osc);
    if (status != HAL_OK) {
        return status;
    }

    clk.ClockType = RCC_CLOCKTYPE_SYSCLK |
                    RCC_CLOCKTYPE_HCLK |
                    RCC_CLOCKTYPE_PCLK1 |
                    RCC_CLOCKTYPE_PCLK2;
    clk.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    clk.AHBCLKDivider = RCC_SYSCLK_DIV1;
    clk.APB1CLKDivider = RCC_HCLK_DIV4;
    clk.APB2CLKDivider = RCC_HCLK_DIV2;

    return HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_5);
}
```

DS8626 Rev 12 表 14 要求 168 MHz HCLK 使用 `VOS=1`，表 15 只在 VDD 2.7 V 至 3.6 V 一行给出 168 MHz/5 wait states；更低 VDD 对应 6 或 7 wait states，最低区间的 Flash 访问上限还是 160 MHz。[S3] 因此 `PWR_REGULATOR_VOLTAGE_SCALE1` 和 `FLASH_LATENCY_5` 不能脱离电源条件使用。把这段函数放入工程前，必须核对实际 VDD、温度/频率等级和 Flash latency 表；条件不同就由 CubeMX 和资料重新推导，不得只复制常量。[S1][S2][S3]

为了让时钟链真正落到一个外设请求路径，下面给出 ADC1/DMA2 的目标初始化。全局句柄和缓冲区由 BSP/应用静态持有；`HAL_ADC_MspInit` 负责 ADC1 门控、DMA 句柄实例化和双向句柄连接。`ADC_CHANNEL_0` 只是器件内部通道选择，实际 GPIO 端口、引脚和模拟连接必须在选定完整料号与板卡后由 CubeMX 生成，不能从本课推断。

```c
#define ADC_DMA_SAMPLE_COUNT 128U

ADC_HandleTypeDef hadc1;
DMA_HandleTypeDef hdma_adc1;
_Alignas(uint32_t)
static uint16_t g_adc_dma_samples[ADC_DMA_SAMPLE_COUNT];
static volatile HAL_StatusTypeDef g_adc_msp_status = HAL_OK;

static void MX_DMA_Init_Reference(void)
{
    __HAL_RCC_DMA2_CLK_ENABLE();

    /* 启动早期且 BSP 独占 DMA2 时才可复位整个 DMA2。 */
    __HAL_RCC_DMA2_FORCE_RESET();
    __HAL_RCC_DMA2_RELEASE_RESET();

    HAL_NVIC_SetPriority(DMA2_Stream0_IRQn, 0U, 0U);
    HAL_NVIC_EnableIRQ(DMA2_Stream0_IRQn);
}

void HAL_ADC_MspInit(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance != ADC1) {
        return;
    }

    __HAL_RCC_ADC1_CLK_ENABLE();
    __HAL_RCC_ADC1_FORCE_RESET();
    __HAL_RCC_ADC1_RELEASE_RESET();

    hdma_adc1.Instance = DMA2_Stream0;
    hdma_adc1.Init.Channel = DMA_CHANNEL_0;
    hdma_adc1.Init.Direction = DMA_PERIPH_TO_MEMORY;
    hdma_adc1.Init.PeriphInc = DMA_PINC_DISABLE;
    hdma_adc1.Init.MemInc = DMA_MINC_ENABLE;
    hdma_adc1.Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;
    hdma_adc1.Init.MemDataAlignment = DMA_MDATAALIGN_HALFWORD;
    hdma_adc1.Init.Mode = DMA_CIRCULAR;
    hdma_adc1.Init.Priority = DMA_PRIORITY_HIGH;
    hdma_adc1.Init.FIFOMode = DMA_FIFOMODE_DISABLE;

    if (HAL_DMA_Init(&hdma_adc1) != HAL_OK) {
        g_adc_msp_status = HAL_ERROR;
        return;
    }

    __HAL_LINKDMA(hadc, DMA_Handle, hdma_adc1);

    HAL_NVIC_SetPriority(ADC_IRQn, 0U, 0U);
    HAL_NVIC_EnableIRQ(ADC_IRQn);
}

static HAL_StatusTypeDef MX_ADC1_Init_Reference(void)
{
    ADC_ChannelConfTypeDef channel = {0};
    HAL_StatusTypeDef status;

    g_adc_msp_status = HAL_OK;
    hadc1.Instance = ADC1;
    hadc1.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV4;
    hadc1.Init.Resolution = ADC_RESOLUTION_12B;
    hadc1.Init.ScanConvMode = DISABLE;
    hadc1.Init.ContinuousConvMode = ENABLE;
    hadc1.Init.DiscontinuousConvMode = DISABLE;
    hadc1.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_NONE;
    hadc1.Init.ExternalTrigConv = ADC_SOFTWARE_START;
    hadc1.Init.DataAlign = ADC_DATAALIGN_RIGHT;
    hadc1.Init.NbrOfConversion = 1U;
    hadc1.Init.DMAContinuousRequests = ENABLE;
    hadc1.Init.EOCSelection = ADC_EOC_SINGLE_CONV;

    status = HAL_ADC_Init(&hadc1);
    if ((status != HAL_OK) || (g_adc_msp_status != HAL_OK)) {
        return HAL_ERROR;
    }

    channel.Channel = ADC_CHANNEL_0;
    channel.Rank = 1U;
    channel.SamplingTime = ADC_SAMPLETIME_84CYCLES;
    return HAL_ADC_ConfigChannel(&hadc1, &channel);
}
```

这里的中断优先级 `0` 只是无 RTOS 参考工程的明确值；集成到已有系统时，应按该系统的中断优先级政策重新分配。整块 DMA2 复位只允许出现在启动早期且 BSP 确认没有其他 DMA2 stream 使用者时；共享资源已经运行后不能用它恢复单个 stream。`_Alignas(uint32_t)` 满足 `HAL_ADC_Start_DMA` 的 `uint32_t *` 入口对齐，实际搬运宽度仍由 DMA half-word 配置决定。DMA2 Stream0/Channel0 到 ADC1 的映射、`ADC_CLOCK_SYNC_PCLK_DIV4` 和字段名称以 RM0090 Rev 22、UM1725 Rev 8 为依据，仍需和实际 STM32CubeF4 包头文件核对。[S1][S2]

最小调用顺序：

```c
int main(void)
{
    HAL_Init();

    if (SystemClock_Config_Reference() != HAL_OK) {
        Error_Handler();
    }

    MX_GPIO_Init(); /* 由实际 ADC 引脚/板卡配置生成。 */
    MX_DMA_Init_Reference();
    if (MX_ADC1_Init_Reference() != HAL_OK) {
        Error_Handler();
    }

    if (HAL_ADC_Start_DMA(&hadc1,
                          (uint32_t *)g_adc_dma_samples,
                          ADC_DMA_SAMPLE_COUNT) != HAL_OK) {
        Error_Handler();
    }

    for (;;) {
        app_process_events();
    }
}
```

调用顺序的理由：`HAL_Init` 建立 HAL 基础状态；系统时钟必须先稳定，后续超时和外设分频才有可信基准；DMA2 应在 ADC 启动 DMA 前完成门控、句柄和 IRQ 初始化；ADC 初始化再把 ADC 公共分频、通道和 DMA 句柄连接起来；最后才启动数据流。`Error_Handler` 在这里是控制流入口，不代表已经观察到某个错误，也不应销毁发生错误时的状态快照。

可在配置成功后做软件侧交叉检查：

```c
typedef struct {
    uint32_t sysclk_hz;
    uint32_t hclk_hz;
    uint32_t pclk1_hz;
    uint32_t pclk2_hz;
    uint32_t cfgr;
    uint32_t cr;
} rcc_snapshot_t;

static void rcc_take_snapshot(rcc_snapshot_t *snapshot)
{
    if (snapshot != NULL) {
        snapshot->sysclk_hz = HAL_RCC_GetSysClockFreq();
        snapshot->hclk_hz = HAL_RCC_GetHCLKFreq();
        snapshot->pclk1_hz = HAL_RCC_GetPCLK1Freq();
        snapshot->pclk2_hz = HAL_RCC_GetPCLK2Freq();
        snapshot->cfgr = RCC->CFGR;
        snapshot->cr = RCC->CR;
    }
}
```

快照对象由诊断/BSP 静态持有，初始化后由应用显式调用。HAL 频率查询值来自软件配置推导，寄存器快照证明配置状态；两者都不是频率计的物理测量结果。

## 10. 常见错误

1. **从 `SystemCoreClock` 倒推一切**：它是软件维护值，不自动证明每条外设支路和门控都正确。
2. **只看 PLL 输出，不看总线上限**：SYSCLK 合法不代表 PCLK1/PCLK2 配置一定合法。
3. **把 APB 定时器输入当成 PCLK**：F407 在 APB 预分频不为 1 时使用本课所述定时器规则，直接使用 PCLK 会造成两倍误差。[S1]
4. **把 DMA HCLK 当采样率**：DMA 的总线时钟影响服务能力，请求节奏仍来自 ADC/定时器等源。
5. **先切高速再设置 Flash latency**：切换顺序违反约束，可能在软件来得及修正前就失效。
6. **只开外设门控，不释放复位**：外设仍可能保持复位态。
7. **用复位代替门控**：复位用于恢复状态，不是正常的功耗门控接口。
8. **等待 ready 没有超时**：源故障会把启动流程永久锁死；HAL 状态必须传播到统一错误路径。
9. **配置后不检查 SWS**：写入 `SW` 是请求，`SWS` 才报告系统当前使用的源。
10. **把 HSI 标称值当精密测量值**：需要准确通信或测量时必须查数据手册精度条件，并用合适仪器验证。
11. **盲目复制 `FLASH_LATENCY_5`**：它依赖系列、VDD、调压档位和频率，迁移时必须重新查表。
12. **混用 HAL 与 LL 写同一 RCC**：一个层维护的顺序和状态可能被另一个层绕开，导致难以审计。
13. **把 CubeMX 绿色时钟图当上板证据**：它证明配置器接受约束，不证明板上振荡器、电源和波形。
14. **把 F407 公式复制到 H7**：多域和专用内核时钟可能改变路径，必须从新目标的 RCC 图重新开始。

## 11. 调试观察点

按“源到叶子”排查，避免从业务回调反向猜测：

1. `RCC_CR.HSION/HSIRDY`：HSI 是否开启且稳定；
2. `RCC_PLLCFGR`：源和 M/N/P/Q 是否与设计一致；
3. `RCC_CR.PLLON/PLLRDY`：PLL 是否开启且锁定；
4. `FLASH_ACR.LATENCY`：等待周期是否与目标条件一致；
5. `RCC_CFGR.SW/SWS`：请求源和实际系统源是否一致；
6. `RCC_CFGR.HPRE/PPRE1/PPRE2`：总线分频编码是否一致；
7. `HAL_RCC_GetSysClockFreq/GetHCLKFreq/GetPCLK1Freq/GetPCLK2Freq`：软件推导是否为 168/168/42/84 MHz；
8. `RCC_AHB1ENR.DMA2EN`、`RCC_APB2ENR.ADC1EN`：门控是否开启；
9. `RCC_AHB1RSTR.DMA2RST`、`RCC_APB2RSTR.ADC1RST`：是否意外保持复位；
10. `ADC_CCR.ADCPRE`：ADCCLK 是否为 PCLK2/4；
11. DMA `NDTR` 与中断标志：请求是否真正到达；
12. 回调计数与错误码：IRQ 是否沿正确句柄传播。

若 `SWS` 不是 PLL：先看 HSI/PLL ready 和 HAL 返回值，不要先改 ADC。若 `SWS` 正确但 ADC `NDTR` 不变：沿 PCLK2 -> ADC 门控/复位 -> ADCPRE -> ADC 启动/触发 -> DMA request -> DMA2 门控/stream 的顺序继续查。若软件频率值正确但串口实际速率错误：还要检查具体外设分频和物理测量，不能回头篡改 `SystemCoreClock` 掩盖问题。

可选硬件观察是 MCO（microcontroller clock output，微控制器时钟输出）：将某个允许输出的内部时钟经规定分频送到 MCO 引脚，再用频率计或示波器测量。实际 MCO 源、分频、引脚复用、引脚速度和测量带宽必须按完整料号/板卡核对；本课不指定虚构引脚。

## 12. 实战实验

### 实验 A：主机参考方案

1. 将 9.1 节代码保存到实验目录。
2. 使用可用 C11 编译器和严格警告选项构建。
3. 保存编译命令、编译器版本、标准输出和退出码。
4. 手算 168/42/84/21 MHz，与结构体结果逐项对照。
5. 解释为什么 `timer_apb1_hz=84 MHz`，而不是 42 MHz 或 168 MHz。

验收：所有断言通过；记录只能写成“主机模型通过”，不能写成“F407 硬件通过”。

### 实验 B：错误注入

建立表格记录“修改项、预期错误、实际返回、结果对象是否应被消费”：

- `pll_m=0` -> `CLOCK_ERR_ZERO`；
- `source_hz=17,000,001 Hz, pll_m=16` -> `CLOCK_ERR_NOT_INTEGRAL`；
- `apb1_div=2` 且上限仍为 42 MHz -> `CLOCK_ERR_LIMIT`；
- 把 `max_adc_hz` 改为 20 MHz -> `CLOCK_ERR_LIMIT`；
- 传入空结果指针 -> `CLOCK_ERR_ARGUMENT`。

检查函数失败时没有把半计算结果提交给调用者；这由局部 `next` 最后一次性赋值保证。

### 实验 C：APB 定时器规则

1. 在保持 HCLK 168 MHz 时，把 APB1 divisor 从 4 改为 1，同时把 PCLK1 上限设为足够容纳该测试值；
2. 验证 PCLK1=168 MHz 且定时器输入也是 168 MHz，而不是再乘 2；
3. 恢复 divisor=4，验证 PCLK1=42 MHz、定时器输入=84 MHz；
4. 说明为什么“定时器总是 PCLK 的两倍”是错误记忆。

这个实验只验证注入的规则。是否允许该总线频率由目标限制决定，不能因为放宽 Fake 上限就写入 F407。

### 实验 D：生成 STM32F407 目标工程

1. 选择实际完整料号，记录 CubeMX/CubeMX2 和 STM32CubeF4 版本；
2. 按 7.3 配置 HSI/PLL/AHB/APB，并截图或导出时钟图；
3. 对照生成的 `SystemClock_Config` 与 9.2，解释每一处差异；
4. 查完整料号数据手册，记录 VDD、调压档位、目标 HCLK 与 Flash latency 的依据；
5. 构建并保存完整日志、编译器版本和 map 文件；没有工具链则明确记录“本步骤未执行”；
6. 调试器连接后保存 RCC/FLASH/PWR 快照；没有板卡则明确记录“本步骤未执行”。

### 实验 E：ADC1-DMA2 时钟与请求链

1. 选择真实可用的 ADC 引脚和安全输入电压；
2. 核对 PCLK2=84 MHz、`ADCPRE=/4`、ADCCLK=21 MHz；
3. 先不开 ADC 转换，观察 DMA `NDTR` 不应因 HCLK 存在而自行递减；
4. 启动 ADC-DMA 后观察 `NDTR`、半/全回调计数和错误码；
5. 分别记录 ADC1 门控、DMA2 门控或 IRQ 配置错误时的现象，再恢复正确配置；
6. 不在故障注入时超过器件电气范围，也不在 HAL 运行中用调试器直接改 RCC 来“修复”。

### 实验 F：物理频率观察

1. 按完整料号和板卡原理图选择合法 MCO 或定时器输出引脚；
2. 用 CubeMX 配置输出，并计算内部源、输出分频和预期频率；
3. 用带宽足够的仪器测量，记录探头、采样率、时基和误差；
4. 将测量值与寄存器快照、HAL 软件值分列保存；
5. 只有具备具体板卡、构建、烧录和测量证据后，后续流程才可以讨论提高硬件验证状态。

### 实验 G：系列迁移审计

选择一个具体 F7、H5 或 H7 完整料号，从其第一方参考手册和数据手册重新填写：源、PLL、系统/域时钟、AHB/APB、外设专用时钟、门控、复位、PWR/Flash 条件、定时器规则、ADC/DMA 路径。每一项写文档版本和章节；没有证据的格子写“未核对”，不要从 F407 行复制。

## 13. 自检题

1. 时钟树解决的核心问题是什么？
2. `16 MHz / 16 * 336 / 2` 的 PLL 输入、VCO 和 SYSCLK 分别是多少？
3. HPRE=/1、PPRE1=/4、PPRE2=/2 时，HCLK、PCLK1、PCLK2 分别是多少？
4. 为什么预分频、门控和复位不能互相替代？
5. 谁持有 Host Fake 的配置和结果？谁把它们注入计算函数？
6. `RCC_CFGR.SW` 与 `SWS` 分别表达什么？为什么两个都要看？
7. F407 的 APB1 预分频为 4 时，PCLK1=42 MHz，为什么 APB1 定时器输入是 84 MHz？
8. PCLK2=84 MHz、ADC divisor=4 时，ADCCLK 是多少？
9. DMA2 得到 168 MHz AHB 时钟，能否推出 ADC 每秒产生 168M 个请求？为什么？
10. `RCC_OscInitTypeDef` 为什么可以是函数局部对象，而 `ADC_HandleTypeDef` 通常要静态持有？
11. Host Fake 全部通过后，还缺哪些证据才能说明目标硬件工作？
12. 为什么迁移 H7 时不能只修改 `max_sysclk_hz`？

参考要点：时钟树把源到使用者的频率和约束变成可追踪链；PLL 输入/VCO/SYSCLK 为 1/336/168 MHz；HCLK/PCLK1/PCLK2 为 168/42/84 MHz；预分频改比率、门控决定送达、复位恢复状态；调用者持有并注入 Fake 对象；SW 是切换请求、SWS 是当前状态；F407 的对应 APB 分频不为 1 时应用定时器规则；ADCCLK=21 MHz；DMA 服务时钟不等于请求速率；RCC 配置对象调用后可释放，外设句柄仍被 IRQ/DMA 使用；还需目标版本、构建、烧录、寄存器与测量证据；H7 的域、PWR/Flash、选择器和寄存器均需重查。

## 14. 面试题

1. 请从 HSI 开始，完整推导 STM32F407 参考方案到 PCLK1、PCLK2、TIMxCLK 和 ADCCLK。
2. 一个 UART 波特率恰好快两倍，你如何判断是时钟树、外设分频还是测量问题？
3. 为什么配置系统时钟时要同时考虑 PWR 和 Flash，而不只是 RCC？
4. HAL 配置 SYSCLK 失败后，初始化代码应该如何保留证据并阻止后续外设启动？
5. 写 `RCC_CFGR.SW` 后为什么还要轮询 `SWS`？
6. 外设没有响应时，如何区分“门控关闭”“保持复位”“内核时钟选择错误”和“IRQ 未连接”？
7. 为什么 `HAL_RCC_GetPCLK1Freq()` 不能替代示波器对 UART 或 MCO 的测量？
8. DMA 的 HCLK、ADC 的 ADCCLK 与 Timer TRGO 的频率分别在 `Timer -> ADC -> DMA` 链上决定什么？
9. 将 F407 配置迁移到 H7，你会先收集哪些第一方资料，建立什么检查表？

## 15. 延伸思考

- 如果需要运行时从高速切到低速，哪些外设的波特率、超时和定时参数必须一起重算？如何避免切换中途出现不一致状态？
- 如果 HSE 失效，系统应继续运行、降级还是复位？哪一层负责检测，哪一层决定业务策略？
- `SystemCoreClock` 是缓存值还是物理事实？何时更新它，如何发现它与寄存器不一致？
- 一个系统有多个异步时钟域时，数据跨域为什么不能只靠“两个频率都已知”保证安全？
- 对低功耗唤醒，唤醒源时钟、内核恢复、Flash/PWR 稳定和外设超时应该按什么顺序重新建立？

## 16. 本节总结

时钟树不是一组孤立频率，而是一张受约束的分配网络。可靠配置必须从源开始，依次证明 PLL 输入/VCO/输出、SYSCLK、AHB/APB、外设内核分频、门控与复位，并把最终频率带入具体时序参数。公式、合法范围、状态和切换顺序缺一不可。

Host Fake 把参数、上限和错误路径变成静态 C11 对象，可验证 16 MHz HSI 经 PLL 得到 168 MHz SYSCLK、168 MHz HCLK、42/84 MHz PCLK 和 21 MHz ADCCLK，也能拒绝零除数、非整除和超限方案。它只证明模型。

STM32F407xx 参考轨道把同一思路落实到 RCC、PWR、FLASH、ADC 和 DMA：先满足电源/Flash 条件，等待 HSI/PLL 稳定，设置 AHB/APB 分频，切换并确认 SYSCLK，再开启外设门控、释放复位并启动请求链。当前没有目标构建或硬件证据，所以 `hardware_verified=false` 保持不变。

## 17. 下一步

下一主题是 `hal-ll-register-crosswalk`：把本课已经看到的 HAL 调用、LL 操作和寄存器状态整理成系统化对照方法。随后进入 `timer-trigger-routing`，将定时器时钟、TRGO、ADC 触发和 DMA 请求连成可测量链；再进入高级控制定时器和 `adc-timer-dma-pipeline`。低功耗、缓存和 F4/F7/H5/H7 深化分别在后续对应阶段展开。

## 18. 参考资料

- [S1] STMicroelectronics，*STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 advanced Arm-based 32-bit MCUs - Reference manual*，RM0090 Rev 22（May 2026）。用于 RCC 时钟树、主 PLL、AHB/APB 分频、门控/复位、Flash 接口、ADC 公共时钟、定时器时钟规则与 DMA/ADC 路径；结论范围仅限手册列出的器件。<https://www.st.com/resource/en/reference_manual/dm00031020.pdf>，访问日期：2026-10-09。
- [S2] STMicroelectronics，*Description of STM32F4 HAL and low-layer drivers*，UM1725 Rev 8（March 2023）。用于 `RCC_OscInitTypeDef`、`RCC_ClkInitTypeDef`、`HAL_RCC_OscConfig`、`HAL_RCC_ClockConfig`、RCC/Flash LL API、ADC/DMA HAL 回调和错误接口。<https://www.st.com/resource/en/user_manual/dm00105879.pdf>，访问日期：2026-10-09。
- [S3] STMicroelectronics，*STM32F405xx STM32F407xx datasheet*，DS8626 Rev 12（March 2026）。用于器件范围、HSI 16 MHz、HCLK/PCLK 上限、Voltage Scale、供电区间、Flash wait-state、主 PLL 和 ADC 工作条件。<https://www.st.com/resource/en/datasheet/stm32f407vg.pdf>，访问日期：2026-10-12。

三份资料均来自 `config/source-policy.toml` 允许的 `st.com` 第一方域名。本次运行的 `source-evidence.md` 记录了本地 PDF、SHA-256、版本、关键页码和适用边界；本课没有把 F407 结论外推到未选定的 F7/H5/H7 器件，也没有把参考代码描述成已在目标 STM32CubeF4 工程编译或运行。

+++
title = "ADC-定时器-DMA 分段缓冲流水线"
date = "2026-10-15T16:00:04+08:00"
lastmod = "2026-10-15T16:00:04+08:00"
summary = "建立 ADC-定时器-DMA 分段缓冲流水线，以 C11 Host Fake 验证速率预算、半区所有权和错误路径，并以 STM32F407xx 的 TIM2 到 ADC1、DMA2 Stream0/Channel0 参考实现核对时钟、CubeMX、HAL、LL、寄存器和迁移边界。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 31
tags = ["adc", "timer", "dma", "pipeline", "circular-buffer", "half-transfer", "ownership", "tim2", "adc1", "stm32f407", "cubemx", "hal", "ll", "registers", "host-fake", "c11"]
source_ids = ["st-rm0090-adc-timer-dma-pipeline", "st-ds8626-adc-timer-dma-pipeline", "st-um1725-adc-timer-dma-pipeline", "st-an4031-adc-timer-dma-pipeline", "st-stm32cubef4-1.28.3-adc-timer-dma-pipeline", "st-stm32cubef7-1.17.3-adc-timer-dma-pipeline", "st-stm32cubeh5-1.5.0-adc-timer-dma-pipeline", "st-stm32cubeh7-1.12.1-adc-timer-dma-pipeline"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L031"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 31 课：ADC-定时器-DMA 分段缓冲流水线

本课把已经分别学过的定时器触发、ADC 转换和 DMA（Direct Memory Access，直接存储器访问）接成一条持续数据通路。唯一的新核心概念是：**ADC-定时器-DMA 分段缓冲流水线**。

它解决的不是“怎样再调用一个 HAL 函数”，而是持续采样时的端到端约束：谁决定采样时刻，ADC 能否在下次触发前完成，DMA 把哪个传输单元写到哪里，HT/TC（half transfer/transfer complete，半传输/传输完成）何时交还稳定分段，应用必须在什么时候消费，以及任何一级出错后谁停止源并保存现场。

本课有两条轨道：

- Host Fake（主机替身）用固定数组和确定性 tick 验证节拍、状态、半区所有权、消费者落后和错误路径；它不模拟真实总线、电气输入或寄存器副作用。
- STM32 参考轨道固定为 `STM32F407xx` 的 `TIM2 update -> TIM2_TRGO -> ADC1 regular conversion -> DMA2 Stream0/Channel0 -> circular buffer`，给出时钟链、CubeMX 清单、HAL 参考代码、IRQ/回调、错误恢复和 LL/寄存器对照。[S1][S3][S4]

当前没有具体开发板、完整订货料号、ADC 引脚、模拟源、目标工程或测量记录。所有 STM32 代码均为“参考实现，待目标工程编译和上板验证”；本文未编译目标代码、未烧录、未测量，`hardware_verified=false`。

## 1. 本节目标

核心目标与 `plan.json` 一致：**建立 ADC-定时器-DMA 分段缓冲流水线，能够以触发速率、转换预算、DMA 传输与半区所有权解释样本从定时器事件到应用消费的完整路径，并以 STM32F407xx 的 `TIM2 -> ADC1 -> DMA2 Stream0/Channel0` 参考实现逐项核对。**

完成本课后，你应能：

1. 从 `TIM2 update` 开始，逐跳解释 TRGO、ADC 转换、DMA 请求、内存写入、HT/TC、IRQ、HAL 回调和应用消费；
2. 用触发周期、ADC 转换时间、半缓冲周期和应用最坏处理时间判断链路是否有余量；
3. 明确 timer、ADC、DMA、样本缓冲区和消费者对象在哪里定义、谁持有、谁注入配置或事件；
4. 解释为什么回调只能发布分段，不能在中断中进行长时间批处理；
5. 在 Host Fake 中验证正常流、未武装、转换超期、DMA 故障、消费者落后和非法配置；
6. 按 CubeMX、HAL、LL 和关键寄存器四层核对 F407 参考实现；
7. 区分静态配置、主机断言、目标构建、寄存器读回和仪器测量五种不同强度的证据；
8. 迁移到 F7、H5、H7 时保留预算与所有权方法，同时重查时钟、请求路由、内存可达性、缓存和安全属性。

## 2. 它解决什么问题

### 2.1 轮询和单样本回调为何不够

若每次定时器到期都进入 CPU 中断，再由软件启动 ADC，等待 EOC（end of conversion，转换结束），最后读取一个样本，CPU 同时承担了“决定采样时刻”和“搬运每个结果”两项工作：

```text
timer IRQ -> CPU latency -> start ADC -> wait/ADC IRQ -> CPU reads DR -> store sample
```

这条路径适合低速验证，却有三个持续采样问题：

1. ADC 启动时刻包含中断响应和软件路径抖动；
2. 每个样本都需要 CPU 介入，速率提高后中断负担随样本数增长；
3. 应用看到的是零散样本，难以说明一批数据在何时稳定、何时会被覆盖。

硬件流水线把周期性工作留在外设之间：

```text
TIM2 update
  -> TIM2_TRGO
  -> ADC1 sample/convert
  -> ADC1 DMA request
  -> DMA2 writes one uint16_t sample
  -> HT or TC only at segment boundary
  -> CPU consumes one stable half-buffer
```

CPU 不再逐样本搬运，但这不等于“无需软件”。软件仍负责初始化、所有权交接、批处理、诊断、停止和恢复。[S1][S3]

### 2.2 最小可审计形态

本课先固定一个最小形态：

- 单个 ADC regular rank（规则组序列中的一个转换位置）；
- TIM2 更新事件作为唯一触发源；
- ADC 连续转换关闭，每个允许的外部触发只启动一次转换；
- DMA 外设到内存、半字到半字、内存递增、循环模式；
- 一个偶数长度的静态 `uint16_t` 数组，逻辑上分成等长前后两半；
- HT 交还前半区，TC 交还后半区；
- 回调只登记事件，应用上下文处理数据；
- 任何错误先停源并保存首个故障，不在 ISR 中盲目重启。

例如 128 个样本的缓冲区在 1 kHz 触发下，每 64 ms 交还一个半区。HT 到来后 DMA 正在写后半区，应用可读前半区；TC 到来后 DMA 回卷到前半区，应用可读后半区。应用若 64 ms 内还未处理完当前半区，下一轮 DMA 就可能覆盖它。

### 2.3 本课不解决什么

- 不配置多通道 scan、交错 ADC 或注入组；这些会改变样本布局与序列边界。
- 不启用 DMA double-buffer mode；本课的“双半区”来自一个 circular buffer 的 HT/TC，不等于硬件双缓冲 `M0AR/M1AR`。
- 不引入 RTOS（Real-Time Operating System，实时操作系统）任务通知；应用用主循环消费。
- 不实现数字滤波；批处理函数只作为消费者边界。
- 不把 F407 的 stream/channel、无 D-Cache 结论或寄存器字段外推到 F7/H5/H7。
- 不虚构 ADC 引脚、VDDA/VREF、外部电路、输入源阻抗、构建结果或波形。

## 3. 必要前置知识

以下前置均已出现在 `learning-state.toml.completed`：

- `adc`：一次转换包含采样、量化、完成和结果交付；真实精度还受参考电压、源阻抗与采样时间影响。
- `dma`：一次外设请求搬运一个配置宽度的数据项；`NDTR` 计数数据项而不是字节；循环模式与 HT/TC 可建立分段交接。
- `clock-tree`：振荡源、PLL、AHB/APB 预分频、外设门控和内核时钟必须逐级推导。
- `hal-ll-register-crosswalk`：HAL 配置意图、LL/寄存器状态和运行证据是不同层次。
- `timer-trigger-routing`：`TIM2 update -> TIM2_TRGO -> ADC1` 必须逐跳核对，并遵守“先武装接收端，后启动源”。
- `advanced-control-timer`：已经见过源事件、预装载、故障和输出安全边界的分析方法；本课不使用 TIM1 高级输出能力。

未完成的 cache、RTOS、driver architecture 不是隐含前置。涉及它们时只界定迁移问题和后续落点。

## 4. 核心原理

### 4.1 一条流水线，三种流

这条流水线同时包含三种流：

```text
控制流：初始化 -> 武装 ADC/DMA -> 启动 TIM2 -> 停止/恢复
事件流：TIM2 update -> TRGO -> ADC EOC -> DMA request -> HT/TC/error IRQ
数据流：模拟输入 -> ADC1_DR -> DMA2 -> samples[] -> application
```

控制流只在启动、停止或恢复时由 CPU 推进。稳定运行时，事件流由硬件逐跳触发，数据流由 ADC 和 DMA 搬运。软件在 HT/TC 边界获得批次，而不是参与每个样本的生成。

混淆三种流会产生典型误判：`HAL_TIM_Base_Start()==HAL_OK` 只证明控制流接受启动；`TIM2_SR.UIF=1` 只证明源事件存在；`NDTR` 递减才说明 DMA 正在接收请求；应用批次计数增加才说明软件完成了交接。没有一个单点能替代整条链的证据。

### 4.2 分段缓冲区的所有权

这里的“所有权”不是 C 语言关键字，而是一条并发访问规则：同一时刻一个半区只能由 DMA 写或由应用读。

| 时刻 | DMA 正在写 | 可由应用读取 | 禁止动作 |
| --- | --- | --- | --- |
| 启动后至第一次 HT | 前半区 | 无 | 应用读取尚未完成的前半区 |
| HT 后至 TC | 后半区 | 前半区 | 应用修改前半区；继续读取到下一次回卷 |
| TC 后至下一次 HT | 前半区 | 后半区 | 应用读取前一轮已失效的前半区 |

HT/TC 不是“开始处理所有数据”的命令，而是所有权交接点。回调发布“第几个半区、第几代数据已经完成”；消费者领取后必须在 DMA 下一次进入该半区前结束。单个 bitmask 会合并重复事件，因此生产实现应使用单调批次计数器，或使用容量和溢出策略明确的队列。

`volatile` 只能要求编译器执行访问，不能自动形成多字段一致快照，也不能解决消费者落后。示例在主循环读取 ISR 更新的计数器时使用短临界区；真正的并发协议还必须结合目标内核、编译器和系统上下文核对。

### 4.3 四个预算必须同时成立

设：

- `f_trigger`：TIM2 TRGO 频率；
- `T_trigger = 1 / f_trigger`：触发周期；
- `T_conv`：一次 ADC 采样加转换时间；
- `N`：整个缓冲区的样本数，必须为偶数；
- `T_half = (N / 2) * T_trigger`：半区交还间隔；
- `T_app_worst`：应用处理一个半区的最坏时间。

最小约束是：

```text
T_conv < T_trigger
T_app_worst < T_half
DMA 能在相邻 ADC 请求之间完成一次 half-word 搬运
缓冲区位于 DMA2 可访问且生命周期覆盖整个运行期的内存
```

实际设计还要留出时钟误差、总线争用、中断屏蔽和其他高优先级负载的余量，不能用等号作为稳健设计。Host Fake 能验证“配置的转换延迟超过触发间隔时进入错误”，却不能证明真实 ADC 和 DMA 的纳秒级时序。

### 4.4 ADC 完成、DMA 请求与 EOC/OVR

每个 TIM2_TRGO 被 ADC1 接收后，ADC 完成一个规则组转换，把结果送到 `ADC1->DR`，并在启用 DMA 请求时请求 DMA2 搬运。DMA2 Stream0 从固定外设地址读取一个半字，写到递增的内存地址，再让 `NDTR` 减 1。[S1][S4]

EOC 是转换完成状态边界；OVR（overrun，过载）表示结果交付未满足目标硬件规则。DMA 模式下 EOC 的清除、OVR 对 DMA 请求的影响以及恢复顺序必须按 RM0090 和实际 STM32CubeF4 驱动版本核对，不能从 Host Fake 推断。[S1][S3]

在参考配置中：

- `ContinuousConvMode=DISABLE`：避免一个触发自行展开为无限连续转换；
- `ExternalTrigConv=T2_TRGO`、边沿为 rising：明确由 TIM2_TRGO 启动；
- `DMAContinuousRequests=ENABLE`：对应持续 DMA 请求所需的 ADC 配置；
- `DMA_CIRCULAR`：`NDTR` 到终点后按硬件规则重装并从缓冲区起点继续；
- DMA 的 HT/TC/error 中断由 `DMA2_Stream0_IRQHandler` 进入 HAL 分发。

### 4.5 对象在哪里、谁持有、谁注入、如何流动

| 对象 | 定义位置 | 持有者 | 谁注入 | 调用/数据如何流动 |
| --- | --- | --- | --- | --- |
| timer | Host Fake 的 `pipeline_t.timer`；目标端 `TIM_HandleTypeDef htim2` | 测试 fixture 或 BSP 静态持有 | 测试/CubeMX 注入周期；时钟配置注入内核频率 | tick/update -> TRGO |
| ADC | `pipeline_t.adc`；目标端 `ADC_HandleTypeDef hadc1` | fixture 或 BSP | 测试注入转换延迟；板级层注入合法 channel | trigger -> sample/convert -> EOC/request |
| DMA | `pipeline_t.dma`；目标端 `DMA_HandleTypeDef hdma_adc1` | fixture 或 BSP；HAL 通过链接关系使用 | 测试注入长度/故障；MSP 注入 stream/channel/宽度 | request -> DR 到 samples[index] -> HT/TC |
| buffer | fixture 或 BSP 的静态 `uint16_t samples[]` | 应用分配；运行时 DMA 写、应用分段读 | 组装代码把地址和长度交给 DMA | 每次请求写一项，边界后分段交还 |
| consumer | fixture 的诊断/领取函数；目标端 App 主循环 | 应用 | HT/TC 回调发布批次 | 领取稳定半区 -> 批处理 -> 标记完成 |
| diagnostics | 静态计数器和首错快照 | BSP/App 共同约定，单一模块写入 | IRQ/HAL 回调注入事件 | ISR 记录，主循环读取并决定恢复 |

初始化者负责注入配置，但运行事件由硬件注入。应用不能直接改写 HAL 正在管理的 DMA stream，也不能把一个自动变量缓冲区交给 DMA 后离开其作用域。

## 5. 关键术语与直观模型

| 术语 | 准确含义 | 在本课中的位置 |
| --- | --- | --- |
| TRGO | trigger output，触发输出 | TIM2 把 update 事件导出到 ADC 触发选择器 |
| EOC | end of conversion，转换结束 | ADC 产生一个可交付结果的状态边界 |
| DMA request | 外设给 DMA 的一次搬运机会 | ADC 完成转换后请求搬运 `DR` 中的一项 |
| circular mode | 循环模式 | DMA 到达缓冲区终点后重新从起点继续 |
| HT | half transfer，半传输 | 前半区已经写完，可交给应用 |
| TC | transfer complete，传输完成 | 后半区已经写完，DMA 即将/已经回卷 |
| NDTR | number of data to transfer，待传输数据数 | 按配置的数据项宽度递减，不是字节计数 |
| overrun | 过载 | 新结果到来时旧结果未按目标规则交付的硬件错误 |
| half-buffer | 半缓冲区/半区 | 一个循环数组中由 HT/TC 划分的两个稳定批次 |
| generation | 代次 | 某半区完成的单调次数，用于识别漏批和旧数据 |
| backpressure | 背压 | 消费者跟不上时向上游施加减速/停止；本课用停源和报错处理 |

直观上可把它想成两只周转箱，但必须保留硬件事实：这里不是两块独立内存，而是一个数组的两个区间；DMA 的当前位置由 stream 地址推进和 `NDTR` 决定，HT/TC 只是边界事件。

## 6. 从输入到结果的完整流程

### 6.1 初始化控制流

```text
HAL_Init
  -> SystemClock_Config
       HSI -> PLL -> SYSCLK/HCLK -> PCLK1/PCLK2
  -> board_adc_gpio_init(actual channel/pin/electrical conditions)
  -> MX_DMA_Init
       DMA2 clock gate + DMA2_Stream0 NVIC
  -> MX_ADC1_Init
       HAL_ADC_Init -> HAL_ADC_MspInit
         ADC1 clock gate
         HAL_DMA_Init(DMA2_Stream0/Channel0)
         __HAL_LINKDMA(hadc1, DMA_Handle, hdma_adc1)
       configure one board-provided channel/rank/sample time
  -> MX_TIM2_Init
       PSC/ARR + master TRGO=update
  -> Pipeline_Start
       clear software diagnostics
       HAL_ADC_Start_DMA(buffer, N)    receiver first
       HAL_TIM_Base_Start(TIM2)        source last
```

初始化阶段可能通过 `TIM2_EGR.UG` 装载 prescaler。由于 `MMS=update` 时 UG 也与 update 事件有关，必须在 ADC/DMA 武装前完成 TIM2 初始化，避免把初始化事件误计为有效样本。[S1]

### 6.2 稳态事件流和数据流

```text
TIM2 counter reaches update
  -> TIM2_CR2.MMS exports update as TIM2_TRGO
  -> ADC1_CR2.EXTSEL/EXTEN accepts TIM2_TRGO rising edge
  -> ADC1 samples selected rank and completes conversion
  -> ADC result reaches ADC1_DR and DMA request is generated
  -> DMA2 Stream0 reads ADC1_DR, writes samples[write_index]
  -> DMA_S0NDTR decrements by one half-word item
  -> index reaches N/2: HTIF0 -> DMA IRQ -> ADC half callback
  -> index reaches N:   TCIF0 -> DMA IRQ -> ADC full callback; circular wrap
  -> callback increments generation/event counter only
  -> main loop snapshots counters and consumes the completed half
```

TIM2 update IRQ 不参与此路径。开启 `HAL_TIM_Base_Start_IT` 只会增加一条 `update -> TIM2 IRQ -> CPU` 的观察支路，不能替代 TRGO 配置，也会增加负载。

### 6.3 停止和恢复流

正常停止按“先停源，再停接收端”执行：

```text
HAL_TIM_Base_Stop
  -> no new periodic TRGO
  -> HAL_ADC_Stop_DMA
       disable ADC DMA path and stop owned stream through HAL
  -> snapshot diagnostics
  -> buffer may be reassigned only after stop completes
```

错误路径先保存首个故障：HAL ADC error、HAL DMA error、`ADC_SR`、`DMA_LISR`、`DMA_S0NDTR` 和软件批次计数。ISR 只置错误事件；主循环再停 TIM2、调用 `HAL_ADC_Stop_DMA`、评估数据有效范围并决定是否重新初始化。恢复前必须解释根因，不能用循环重启掩盖持续 OVR、错误映射或消费者过慢。

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

| 层级 | 能力、工作原理与链路 | 本课处理和后续落点 |
| --- | --- | --- |
| 基础功能 | ADC 单次转换；TIM PSC/ARR 产生 update；DMA 按请求搬运一项；中断报告状态 | 作为已学前置，只复习它们如何形成一个样本 |
| 进阶功能 | timer 硬件触发单 rank ADC；DMA circular 写固定数组；HT/TC 分段交接 | 本课完整深入，形成最小可审计流水线 |
| 高级功能 | 多 rank scan 会形成交织样本帧；DMA double-buffer 用 `M0AR/M1AR` 切换目标；ADC 交错提高吞吐；DMAMUX/GPDMA 可加入请求选择、同步或链表；cache maintenance 解决 DMA 与 CPU 的可见性 | 工作原理会改变布局、请求或所有权；分别落到多通道采样、系列 DMA、`dma-coherency` 和性能专题 |
| 跨外设联动 | `TIM2 TRGO -> ADC1 -> DMA2 -> IRQ -> application`；触发、转换、搬运、通知和消费共享同一速率预算 | 本课核心；后续 `peripheral-integration-lab` 加入具体传感器、时间戳和系统消费需求 |
| 系列差异 | 预算公式和“先接收端后源、先停源后接收端”可迁移；时钟选择、请求路由、DMA 架构、内存域、缓存和安全属性不可直接复制 | F407 给出参考实现；F7/H5/H7 按 7.5 重建证据表 |

高级功能不能只看成“更多开关”。例如多通道 scan 会让一次 trigger 产生一个序列，DMA 数组要按 rank 顺序解释；double-buffer mode 由硬件在两个目标地址间切换，交接边界不再只由一个数组的 HT/TC 表示；F7/H7 的 D-Cache 可能让 DMA 已写而 CPU 仍读到旧 cache line，所有权交接必须增加 cache invalidate 和对齐约束。它们改变当前核心概念中的数据布局或可见性，因此不能未经验证直接加入本课代码。

### 7.2 参考目标与完整时钟/复位链

参考器件范围为 `STM32F407xx`，具体订货料号和封装尚未选择。参考文档为 RM0090 Rev 22、DS8626 Rev 12、UM1725 Rev 8、AN4031 Rev 3，驱动边界固定为 STM32CubeF4 v1.28.3。[S1][S2][S3][S4][S5]

为避免虚构板载晶振，参考时钟从 F407 内部 HSI 的标称 16 MHz 推导：

```text
HSI = 16 MHz
  -> PLLM = 16: PLL input = 1 MHz
  -> PLLN = 336: VCO = 336 MHz
  -> PLLP = 2: SYSCLK = 168 MHz
  -> AHB prescaler /1: HCLK = 168 MHz
       -> AHB1 bus
          -> RCC_AHB1ENR.DMA2EN = 1
          -> DMA2 interface clock available
  -> APB1 prescaler /4: PCLK1 = 42 MHz
       -> F407 rule when APB prescaler != 1: TIM2 kernel = 2 * PCLK1 = 84 MHz
       -> RCC_APB1ENR.TIM2EN = 1
       -> PSC = 83: counter clock = 1 MHz
       -> ARR = 999: update/TRGO = 1 kHz, T_trigger = 1 ms
  -> APB2 prescaler /2: PCLK2 = 84 MHz
       -> RCC_APB2ENR.ADC1EN = 1
       -> ADC common prescaler /4: ADCCLK = 21 MHz
       -> sample time 84 cycles + 12-bit conversion 12 cycles
       -> T_sample+convert = 96 / 21 MHz ~= 4.57 us
       -> 再加 DS8626 规定的外部触发延迟，才得到完整 T_conv
       -> 完整理论裕量 = 1 ms - T_conv
```

F407 12 位一次转换的 `sample cycles + 12 cycles` 关系、外部触发附加延迟以及 ADC 时钟限制必须以 RM0090/DS8626 的当前修订版和实际工作条件为准。[S1][S2] `4.57 us` 只表示采样加转换周期；未加入外部触发延迟前，不把 `995.43 us` 声称为完整裕量。上述数字是文档约束下的参考推导，不是实测频率或精度。

若 `N=128`：

```text
buffer bytes = 128 samples * 2 bytes = 256 bytes
half samples = 64
T_half = 64 * 1 ms = 64 ms
full wrap period = 128 ms
```

因此应用的 `T_app_worst` 必须显著小于 64 ms。DMA 一次请求搬运一个 half-word；不能把 `NDTR=128` 解读为 128 字节。

门控、复位和运行使能是三层不同动作：

1. `DMA2EN`、`ADC1EN`、`TIM2EN` 打开总线接口时钟；
2. `DMA2RST`、共享 `ADCRST`、`TIM2RST` 只应由知道所有使用者的启动/恢复所有者短暂断言并释放；
3. `DMA_S0CR.EN`、ADC enable/DMA 请求配置和 `TIM2_CR1.CEN` 才启动运行。

共享复位会影响同一控制器或 ADC 公共域中的其他用户。局部错误回调无权无条件复位整个 DMA2 或 ADC 域。

### 7.3 CubeMX/CubeMX2 配置清单

以下是配置意图，不是某块开发板的现成 `.ioc`：

1. **MCU Selector**：选择实际完整 STM32F407 订货料号；确认封装引出了所需 ADC1 channel。未固定料号时不得猜 pin。
2. **RCC/Clock**：参考值使用 HSI、PLLM=16、PLLN=336、PLLP=2、PLLQ=7、AHB=/1、APB1=/4、APB2=/2；实际电压、速度等级、Flash latency 和温度条件按 DS8626 复查。
3. **TIM2 Parameter Settings**：Clock Source=Internal Clock、Counter Mode=Up、Prescaler=83、Period=999、Clock Division=DIV1、Auto-reload preload 按应用需求明确；Master Output Trigger=Update Event、Master/Slave Mode=Disable。
4. **ADC1 Parameter Settings**：Resolution=12 bits、Scan Conversion=Disabled、Continuous Conversion=Disabled、Discontinuous=Disabled、Data Alignment=Right、Number of Conversion=1、External Trigger Source=`Timer 2 Trigger Out event`、Edge=Rising、DMA Continuous Requests=Enabled、EOC Selection=Single Conversion。
5. **ADC1 Channel**：由完整料号、封装、原理图和模拟源注入实际 channel、rank 1、采样时间。参考预算使用 84 cycles，但必须按输入源阻抗和精度要求重算。
6. **ADC1 DMA Settings**：DMA2 Stream0、Channel0、Peripheral to Memory、Circular、Peripheral Increment Disabled、Memory Increment Enabled、Peripheral/Memory Data Width=Half Word、Priority=High、FIFO Disabled。[S1][S4]
7. **NVIC**：启用 `DMA2 Stream0 global interrupt` 和 `ADC global interrupt`。本课固定的 STM32CubeF4 v1.28.3 `HAL_ADC_Start_DMA()` 路径会启用 OVR 中断，因此必须让 `ADC_IRQHandler -> HAL_ADC_IRQHandler` 可达；迁移到其他包版本时重新核对。优先级必须纳入整个系统规划，示例值不是通用答案。[S3][S5]
8. **生成后静态审计**：确认 DMA clock/NVIC 在 ADC 初始化前就绪；`HAL_ADC_MspInit` 中有 `HAL_DMA_Init` 与 `__HAL_LINKDMA`；ADC 为外部触发且非 continuous；TIM2 为 update TRGO；启动顺序为 `HAL_ADC_Start_DMA` 先、`HAL_TIM_Base_Start` 后。

不要用 CubeMX 绿色勾号代替手册核对。生成器能保证所选版本的配置一致性，但不能替你确认板级模拟条件、速率余量或消费者是否及时。

### 7.4 HAL 初始化字段、句柄所有权和调用顺序

`TIM_HandleTypeDef htim2`、`ADC_HandleTypeDef hadc1`、`DMA_HandleTypeDef hdma_adc1` 和 `g_samples[]` 都由 BSP 静态持有，生命周期覆盖整个采集会话。HAL 通过 `__HAL_LINKDMA(&hadc1, DMA_Handle, hdma_adc1)` 建立双向关系：ADC 句柄找到 DMA 句柄，DMA 句柄的 `Parent` 能让 IRQ 分发回 ADC HAL 回调。[S3]

关键字段的作用如下：

| 结构字段 | 解决的问题 | 参考值 |
| --- | --- | --- |
| `htim2.Init.Prescaler/Period` | 从 84 MHz 得到 1 kHz update | 83 / 999 |
| `MasterOutputTrigger` | 选择哪种 TIM2 事件导出为 TRGO | `TIM_TRGO_UPDATE` |
| `hadc1.Init.ClockPrescaler` | 从 PCLK2 得到 ADCCLK | `ADC_CLOCK_SYNC_PCLK_DIV4` |
| `Resolution/DataAlign` | 定义结果位宽和 `DR` 中的排列 | 12-bit / right |
| `ScanConvMode/NbrOfConversion` | 定义一个 trigger 的序列结构 | disabled / 1 |
| `ContinuousConvMode` | 是否由一次触发自行连续转换 | disabled |
| `ExternalTrigConv/Edge` | ADC 听哪个内部源和边沿 | T2_TRGO / rising |
| `DMAContinuousRequests` | 允许持续 DMA 请求配合循环采集 | enabled |
| `hdma_adc1.Init.Channel` | 把 ADC1 request 映射到 stream | channel 0 |
| `Direction` | 数据流方向 | peripheral-to-memory |
| `PeriphInc/MemInc` | `DR` 固定、数组地址递增 | disabled / enabled |
| `PeriphDataAlignment/MemDataAlignment` | 一项传输的两端宽度 | half-word / half-word |
| `Mode` | 到终点后是否继续 | circular |

HAL 调用链：

```text
HAL_ADC_Start_DMA(&hadc1, buffer, N)
  -> register ADC-facing DMA callbacks in hdma_adc1
  -> configure/start DMA transfer using ADC1_DR, buffer and N
  -> enable ADC DMA request path and ADC

DMA2_Stream0_IRQHandler
  -> HAL_DMA_IRQHandler(&hdma_adc1)
       -> HT: ADC DMA half callback
          -> HAL_ADC_ConvHalfCpltCallback(&hadc1)
       -> TC: ADC DMA complete callback
          -> HAL_ADC_ConvCpltCallback(&hadc1)
       -> transfer/direct/FIFO error
          -> ADC/DMA error propagation
          -> HAL_ADC_ErrorCallback(&hadc1)
```

确切内部函数名和错误合并细节以 STM32CubeF4 v1.28.3 源码为准；应用只依赖公开回调契约，不复制 HAL 内部实现。[S3][S5]

### 7.5 HAL、LL 与关键寄存器/状态位对照

| 链路节点 | HAL 配置/API | LL 入口示例 | F407 关键寄存器/状态 |
| --- | --- | --- | --- |
| HSI/PLL/总线 | `HAL_RCC_OscConfig`、`HAL_RCC_ClockConfig` | RCC LL 配置与读回 API | `RCC_CR`、`PLLCFGR`、`CFGR`、ready/switch 状态 |
| DMA2 门控/复位 | `__HAL_RCC_DMA2_CLK_ENABLE` | RCC LL AHB1 enable/reset | `RCC_AHB1ENR.DMA2EN`、`AHB1RSTR.DMA2RST` |
| TIM2 门控/复位 | `__HAL_RCC_TIM2_CLK_ENABLE` | RCC LL APB1 enable/reset | `RCC_APB1ENR.TIM2EN`、`APB1RSTR.TIM2RST` |
| ADC1 门控/复位 | `__HAL_RCC_ADC1_CLK_ENABLE` | RCC LL APB2 enable/reset | `RCC_APB2ENR.ADC1EN`、`APB2RSTR.ADCRST`（共享） |
| TIM2 节拍 | `HAL_TIM_Base_Init` | `LL_TIM_SetPrescaler/AutoReload` | `TIM2_PSC`、`ARR`、`EGR.UG`、`CR1.CEN`、`SR.UIF` |
| TRGO | `HAL_TIMEx_MasterConfigSynchronization` | `LL_TIM_SetTriggerOutput` | `TIM2_CR2.MMS=update` |
| ADC 时钟/规则组 | `HAL_ADC_Init`、`HAL_ADC_ConfigChannel` | ADC common/regular LL API | `ADC_CCR.ADCPRE`、`SQR1/SQR3`、`SMPRx` |
| ADC 触发 | external trigger source/edge fields | regular trigger source/edge LL API | `ADC1_CR2.EXTSEL/EXTEN`、`CONT` |
| ADC DMA 请求 | `DMAContinuousRequests=ENABLE`、`HAL_ADC_Start_DMA` | ADC DMA mode LL API | `ADC1_CR2.DMA/DDS`；具体编码按 RM0090 核对 |
| ADC 状态 | HAL ADC state/error APIs | ADC flag LL API | `ADC1_SR.EOC/OVR`、`ADC1_DR` |
| DMA 请求映射 | `DMA2_Stream0` + `DMA_CHANNEL_0` | `LL_DMA_SetChannelSelection` | `DMA_S0CR.CHSEL=0`；映射见 RM0090 请求表 |
| DMA 契约 | `HAL_DMA_Init` | direction/inc/size/mode LL API | `S0CR.DIR/PINC/MINC/PSIZE/MSIZE/CIRC/PL` |
| 地址和计数 | `HAL_ADC_Start_DMA(..., N)` | address/data-length LL API | `S0PAR=&ADC1->DR`、`S0M0AR=buffer`、`S0NDTR=N` |
| HT/TC/error | DMA IRQ + ADC callbacks | DMA IT/flag LL API | `S0CR.HTIE/TCIE/TEIE/DMEIE`、`LISR.HTIF0/TCIF0/TEIF0/DMEIF0/FEIF0` |
| flag 清除 | `HAL_DMA_IRQHandler` 内部处理 | `LL_DMA_ClearFlag_*` | 向 `DMA_LIFCR` 对应 clear 位写 1 |
| NVIC | `HAL_NVIC_SetPriority/EnableIRQ` | NVIC CMSIS API | enable/pending/active 状态与向量入口 |

这张表用于观察和解释 HAL，不授权在 stream 运行时用 LL 改写。`DMA_S0CR.EN=1` 时多数 stream 配置、地址和 `NDTR` 不应被重写；若选择 LL-only 驱动，必须由单一所有者负责停流、等待 EN 清零、清标志、配置、启中断和重启。[S1][S4]

### 7.6 F4、F7、H5、H7 迁移表

| 项目 | F407 本课参考 | 迁移时必须做什么 |
| --- | --- | --- |
| 完整料号 | 仅限定 `STM32F407xx` 文档范围，未选封装 | 固定完整 F7/H5/H7 料号、封装和修订版，重新选合法 ADC channel/pin |
| timer/ADC clock | APB1 timer x2 规则；ADC 同步自 PCLK2 /4 | 重建 oscillator/PLL/bus/kernel clock 树，核对独立 ADC kernel clock 和 timer clock 规则 |
| 请求选择 | ADC1 -> DMA2 Stream0/Channel0 | 查目标 request table；核对 stream/channel、DMAMUX request ID 或 GPDMA request/port |
| DMA 架构 | F4 stream/channel，circular + HT/TC | F7 仍需按具体器件重查；H5/H7 可能使用 DMAMUX/GPDMA/不同控制器和标志语义 |
| IRQ/回调 | DMA2 Stream0 IRQ 进入 F4 HAL ADC half/full/error 回调 | 以目标 Cube 包版本核对 IRQ 名、HAL API、callback registration 和 error code |
| 内存可达性 | 缓冲区必须在 DMA2 可访问 SRAM；F407 Cortex-M4 无 D-Cache | 查 DMA 主设备到 SRAM/TCM/域的可达性；不可把 buffer 随意放进 TCM 或不可达域 |
| D-Cache/MPU | 当前 F407 参考无需 D-Cache 维护 | F7/H7 按 cache line 对齐、MPU 属性和 invalidate/clean 顺序设计；落到 `dma-coherency` |
| 安全域 | 当前参考无 TrustZone 配置 | H5 固定 secure/non-secure 外设、DMA、内存和中断归属，核对安全属性 |
| 低功耗 | 本课不让流水线跨低功耗状态 | 重查时钟门控、stop mode 保持、唤醒源和恢复顺序 |

F7、H5、H7 的系列包来源只用于界定复查范围；本文没有固定这些系列的完整目标器件，因此不声称某个请求号、寄存器位或 HAL 宏可直接使用。[S6][S7][S8]

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

Host Fake 把一个 tick 定义为测试时间单位。fixture 静态持有 timer、ADC、DMA、8 项 `uint16_t` 缓冲区和消费者状态：

- timer 每隔 `trigger_period_ticks` 发出一个事件；
- ADC 需要 `conversion_ticks` 才完成；忙时又收到 trigger，记录转换预算错误；
- ADC 完成后给 DMA 一次 request；
- DMA 每次只写一个样本，到 4 项发布前半区，到 8 项发布后半区并回卷；
- 若 DMA 准备重新写一个仍归应用所有的半区，记录消费者落后并停止；
- 可注入 DMA 故障；首个错误保持不被后续错误覆盖。

它能证明：状态和事件顺序、每次 request 最多写一项、分段边界、未完成分段不可消费、落后不会静默覆盖、停止和故障路径可审计。

它不能证明：F407 request mapping、ADC/DMA 寄存器副作用、总线仲裁、真实 IRQ 时延、模拟精度、OVR 清除规则、cache 可见性或板级电气条件。

### 8.2 STM32 参考实现轨道

参考实现可以直接复用的只有目标无关的控制原则和已核对的 F407 HAL 字段。以下内容必须由实际工程补齐：

- 完整 STM32F407 订货料号、封装和目标板；
- ADC channel、GPIO port/pin、VDDA/VREF、输入电压和源阻抗；
- CubeMX/CubeMX2、STM32CubeF4、编译器和调试器版本；
- 中断优先级与整个系统的约束；
- 缓冲区最终链接地址以及 DMA2 可达性；
- 构建、烧录、寄存器读回、自由运行数据和仪器测量证据。

当前状态：参考代码未在目标工程编译，未烧录，未测量。主机逻辑验证即使执行通过，也不能改变 `hardware_verified=false`。

### 8.3 五种证据不要混用

| 证据 | 能回答的问题 | 不能回答的问题 |
| --- | --- | --- |
| 文档/静态推导 | 路由是否合法，字段语义和理论预算是什么 | 工程是否正确生成、硬件是否运行 |
| Host Fake 断言 | 所有权协议和错误策略是否自洽 | STM32 外设是否按此行为 |
| 目标 clean build | 代码、头文件、链接和版本是否一致 | 引脚、信号和运行时序是否正确 |
| 寄存器读回/计数 | 实际配置与事件是否到达观察点 | 模拟精度和绝对时间是否达标 |
| 示波器/逻辑分析仪/信号源 | 可输出节点的时间、电气与频率结果 | 片内 TRGO 若未路由到可观察节点，不能直接看到 |

## 9. 最小代码示例

### 9.1 C11 Host Fake：状态、所有权和错误路径

下面是一份可独立放入主机测试工程的示例。它只使用固定宽度整数、固定数组和静态生命周期，不使用动态内存。

```c
#include <assert.h>
#include <stddef.h>
#include <stdint.h>

#define PIPE_BUFFER_COUNT 8U
#define PIPE_HALF_COUNT   (PIPE_BUFFER_COUNT / 2U)

typedef uint8_t pipe_status_t;
#define PIPE_OK                    ((pipe_status_t)0U)
#define PIPE_ERR_BAD_CONFIG        ((pipe_status_t)1U)
#define PIPE_ERR_NOT_ARMED         ((pipe_status_t)2U)
#define PIPE_ERR_ADC_BUSY          ((pipe_status_t)3U)
#define PIPE_ERR_DMA_STOPPED       ((pipe_status_t)4U)
#define PIPE_ERR_DMA_FAULT         ((pipe_status_t)5U)
#define PIPE_ERR_CONSUMER_LATE     ((pipe_status_t)6U)
#define PIPE_ERR_SEGMENT_NOT_READY ((pipe_status_t)7U)

typedef struct {
    uint32_t period_ticks;
    uint32_t elapsed_ticks;
    uint8_t running;
} fake_timer_t;

typedef struct {
    uint32_t conversion_ticks;
    uint32_t remaining_ticks;
    uint16_t pending_sample;
    uint8_t armed;
    uint8_t busy;
} fake_adc_t;

typedef struct {
    uint16_t *buffer;
    uint32_t count;
    uint32_t write_index;
    uint8_t running;
    uint8_t fault_on_next_request;
} fake_dma_t;

typedef struct {
    fake_timer_t timer;
    fake_adc_t adc;
    fake_dma_t dma;
    uint16_t samples[PIPE_BUFFER_COUNT];
    uint32_t trigger_count;
    uint32_t conversion_count;
    uint32_t dma_write_count;
    uint32_t published_generation[2];
    uint32_t consumed_generation[2];
    uint8_t segment_owned_by_app[2];
    uint16_t next_sample;
    pipe_status_t first_error;
} pipeline_t;

static void pipe_record_first_error(pipeline_t *p, pipe_status_t error)
{
    if (p->first_error == PIPE_OK) {
        p->first_error = error;
    }
}

static void pipe_stop_on_error(pipeline_t *p, pipe_status_t error)
{
    pipe_record_first_error(p, error);
    p->timer.running = 0U;
    p->adc.armed = 0U;
    p->dma.running = 0U;
}

static pipe_status_t pipe_init(pipeline_t *p,
                               uint32_t trigger_period_ticks,
                               uint32_t conversion_ticks,
                               uint32_t buffer_count)
{
    uint32_t i;

    if ((p == NULL) || (trigger_period_ticks == 0U) ||
        (conversion_ticks == 0U) ||
        (buffer_count != PIPE_BUFFER_COUNT) ||
        ((PIPE_BUFFER_COUNT & 1U) != 0U)) {
        return PIPE_ERR_BAD_CONFIG;
    }

    *p = (pipeline_t){0};
    for (i = 0U; i < PIPE_BUFFER_COUNT; ++i) {
        p->samples[i] = 0U;
    }
    p->timer.period_ticks = trigger_period_ticks;
    p->adc.conversion_ticks = conversion_ticks;
    p->dma.buffer = p->samples;
    p->dma.count = buffer_count;
    p->next_sample = 100U;
    p->first_error = PIPE_OK;
    return PIPE_OK;
}

static pipe_status_t pipe_start(pipeline_t *p)
{
    if ((p == NULL) || (p->dma.buffer == NULL) ||
        (p->dma.count != PIPE_BUFFER_COUNT)) {
        return PIPE_ERR_BAD_CONFIG;
    }

    p->timer.elapsed_ticks = 0U;
    p->adc.remaining_ticks = 0U;
    p->adc.busy = 0U;
    p->dma.write_index = 0U;
    p->first_error = PIPE_OK;

    /* Receiver first, source last. */
    p->dma.running = 1U;
    p->adc.armed = 1U;
    p->timer.running = 1U;
    return PIPE_OK;
}

static void pipe_publish_boundary(pipeline_t *p, uint32_t segment)
{
    p->segment_owned_by_app[segment] = 1U;
    p->published_generation[segment]++;
}

static pipe_status_t fake_dma_request(pipeline_t *p, uint16_t sample)
{
    uint32_t segment;

    if (p->dma.running == 0U) {
        pipe_stop_on_error(p, PIPE_ERR_DMA_STOPPED);
        return PIPE_ERR_DMA_STOPPED;
    }
    if (p->dma.fault_on_next_request != 0U) {
        p->dma.fault_on_next_request = 0U;
        pipe_stop_on_error(p, PIPE_ERR_DMA_FAULT);
        return PIPE_ERR_DMA_FAULT;
    }

    segment = (p->dma.write_index < PIPE_HALF_COUNT) ? 0U : 1U;
    if (((p->dma.write_index == 0U) ||
         (p->dma.write_index == PIPE_HALF_COUNT)) &&
        (p->segment_owned_by_app[segment] != 0U)) {
        pipe_stop_on_error(p, PIPE_ERR_CONSUMER_LATE);
        return PIPE_ERR_CONSUMER_LATE;
    }

    p->dma.buffer[p->dma.write_index] = sample;
    p->dma.write_index++;
    p->dma_write_count++;

    if (p->dma.write_index == PIPE_HALF_COUNT) {
        pipe_publish_boundary(p, 0U); /* HT */
    } else if (p->dma.write_index == p->dma.count) {
        pipe_publish_boundary(p, 1U); /* TC */
        p->dma.write_index = 0U;      /* circular reload */
    }
    return PIPE_OK;
}

static pipe_status_t fake_adc_trigger(pipeline_t *p)
{
    if (p->adc.armed == 0U) {
        pipe_stop_on_error(p, PIPE_ERR_NOT_ARMED);
        return PIPE_ERR_NOT_ARMED;
    }
    if (p->adc.busy != 0U) {
        pipe_stop_on_error(p, PIPE_ERR_ADC_BUSY);
        return PIPE_ERR_ADC_BUSY;
    }

    p->adc.pending_sample = p->next_sample;
    p->next_sample++;
    p->adc.remaining_ticks = p->adc.conversion_ticks;
    p->adc.busy = 1U;
    p->trigger_count++;
    return PIPE_OK;
}

static pipe_status_t pipe_tick(pipeline_t *p)
{
    pipe_status_t status;

    if (p == NULL) {
        return PIPE_ERR_BAD_CONFIG;
    }
    if (p->first_error != PIPE_OK) {
        return p->first_error;
    }

    /* Complete an earlier conversion before considering this tick's trigger. */
    if (p->adc.busy != 0U) {
        p->adc.remaining_ticks--;
        if (p->adc.remaining_ticks == 0U) {
            p->adc.busy = 0U;
            p->conversion_count++;
            status = fake_dma_request(p, p->adc.pending_sample);
            if (status != PIPE_OK) {
                return status;
            }
        }
    }

    if (p->timer.running != 0U) {
        p->timer.elapsed_ticks++;
        if (p->timer.elapsed_ticks == p->timer.period_ticks) {
            p->timer.elapsed_ticks = 0U;
            return fake_adc_trigger(p);
        }
    }
    return PIPE_OK;
}

static pipe_status_t pipe_take_segment(pipeline_t *p,
                                       uint32_t segment,
                                       const uint16_t **data,
                                       uint32_t *count,
                                       uint32_t *generation)
{
    if ((p == NULL) || (segment > 1U) || (data == NULL) ||
        (count == NULL) || (generation == NULL)) {
        return PIPE_ERR_BAD_CONFIG;
    }
    if (p->segment_owned_by_app[segment] == 0U) {
        return PIPE_ERR_SEGMENT_NOT_READY;
    }

    *data = &p->samples[segment * PIPE_HALF_COUNT];
    *count = PIPE_HALF_COUNT;
    *generation = p->published_generation[segment];
    p->consumed_generation[segment] = *generation;
    p->segment_owned_by_app[segment] = 0U;
    return PIPE_OK;
}

static void run_ticks_until_writes(pipeline_t *p, uint32_t target_writes)
{
    while ((p->dma_write_count < target_writes) &&
           (p->first_error == PIPE_OK)) {
        (void)pipe_tick(p);
    }
}

static void test_valid_pipeline(void)
{
    pipeline_t p;
    const uint16_t *data;
    uint32_t count;
    uint32_t generation;

    assert(pipe_init(&p, 3U, 1U, PIPE_BUFFER_COUNT) == PIPE_OK);
    assert(pipe_start(&p) == PIPE_OK);

    run_ticks_until_writes(&p, PIPE_HALF_COUNT);
    assert(p.published_generation[0] == 1U);
    assert(pipe_take_segment(&p, 0U, &data, &count, &generation) == PIPE_OK);
    assert(count == PIPE_HALF_COUNT);
    assert(generation == 1U);
    assert(data[0] == 100U);
    assert(data[3] == 103U);

    run_ticks_until_writes(&p, PIPE_BUFFER_COUNT);
    assert(p.published_generation[1] == 1U);
    assert(pipe_take_segment(&p, 1U, &data, &count, &generation) == PIPE_OK);
    assert(data[0] == 104U);
    assert(data[3] == 107U);
    assert(p.trigger_count == p.conversion_count);
    assert(p.conversion_count == p.dma_write_count);
}

static void test_conversion_budget_failure(void)
{
    pipeline_t p;

    assert(pipe_init(&p, 3U, 4U, PIPE_BUFFER_COUNT) == PIPE_OK);
    assert(pipe_start(&p) == PIPE_OK);
    while (p.first_error == PIPE_OK) {
        (void)pipe_tick(&p);
    }
    assert(p.first_error == PIPE_ERR_ADC_BUSY);
    assert(p.timer.running == 0U);
}

static void test_consumer_late(void)
{
    pipeline_t p;

    assert(pipe_init(&p, 2U, 1U, PIPE_BUFFER_COUNT) == PIPE_OK);
    assert(pipe_start(&p) == PIPE_OK);
    run_ticks_until_writes(&p, PIPE_BUFFER_COUNT);
    assert(p.segment_owned_by_app[0] == 1U);
    assert(p.segment_owned_by_app[1] == 1U);

    while (p.first_error == PIPE_OK) {
        (void)pipe_tick(&p);
    }
    assert(p.first_error == PIPE_ERR_CONSUMER_LATE);
    assert(p.dma_write_count == PIPE_BUFFER_COUNT);
}

static void test_dma_fault(void)
{
    pipeline_t p;

    assert(pipe_init(&p, 3U, 1U, PIPE_BUFFER_COUNT) == PIPE_OK);
    assert(pipe_start(&p) == PIPE_OK);
    p.dma.fault_on_next_request = 1U;
    while (p.first_error == PIPE_OK) {
        (void)pipe_tick(&p);
    }
    assert(p.first_error == PIPE_ERR_DMA_FAULT);
    assert(p.dma_write_count == 0U);
}

static void test_inactive_and_invalid_paths(void)
{
    pipeline_t p;
    const uint16_t *data;
    uint32_t count;
    uint32_t generation;
    uint32_t i;

    assert(pipe_init(&p, 2U, 1U, PIPE_BUFFER_COUNT - 1U) ==
           PIPE_ERR_BAD_CONFIG);

    /* A configured but stopped source cannot fabricate a trigger or batch. */
    assert(pipe_init(&p, 2U, 1U, PIPE_BUFFER_COUNT) == PIPE_OK);
    for (i = 0U; i < 8U; ++i) {
        assert(pipe_tick(&p) == PIPE_OK);
    }
    assert(p.trigger_count == 0U);
    assert(p.dma_write_count == 0U);
    assert(p.published_generation[0] == 0U);
    assert(p.published_generation[1] == 0U);
    assert(pipe_take_segment(&p, 0U, &data, &count, &generation) ==
           PIPE_ERR_SEGMENT_NOT_READY);

    assert(pipe_start(&p) == PIPE_OK);
    p.adc.armed = 0U;
    while (p.first_error == PIPE_OK) {
        (void)pipe_tick(&p);
    }
    assert(p.first_error == PIPE_ERR_NOT_ARMED);
    assert(p.dma_write_count == 0U);

    assert(pipe_init(&p, 2U, 1U, PIPE_BUFFER_COUNT) == PIPE_OK);
    assert(pipe_start(&p) == PIPE_OK);
    p.dma.running = 0U;
    while (p.first_error == PIPE_OK) {
        (void)pipe_tick(&p);
    }
    assert(p.first_error == PIPE_ERR_DMA_STOPPED);
    assert(p.dma_write_count == 0U);

    /* A started but unfinished conversion has not produced a DMA request. */
    assert(pipe_init(&p, 3U, 2U, PIPE_BUFFER_COUNT) == PIPE_OK);
    assert(pipe_start(&p) == PIPE_OK);
    assert(pipe_tick(&p) == PIPE_OK);
    assert(pipe_tick(&p) == PIPE_OK);
    assert(pipe_tick(&p) == PIPE_OK);
    assert(p.trigger_count == 1U);
    assert(p.conversion_count == 0U);
    assert(p.dma_write_count == 0U);
    assert(pipe_tick(&p) == PIPE_OK);
    assert(p.conversion_count == 0U);
    assert(p.dma_write_count == 0U);
}

int main(void)
{
    test_valid_pipeline();
    test_conversion_budget_failure();
    test_consumer_late();
    test_dma_fault();
    test_inactive_and_invalid_paths();
    return 0;
}
```

代码的责任边界：

- `pipe_init` 是组装：注入触发周期、转换延迟和 buffer 长度，连接固定 buffer 并初始化诊断；长度不等于固定容量时拒绝配置；
- `pipe_start` 体现先 DMA、再 ADC、最后 timer 的接收端优先顺序；
- `pipe_tick` 推进逻辑时间，不代表真实 ISR 或总线周期；
- `fake_dma_request` 是唯一写 buffer 的函数，并在写入新半区前检查应用是否归还；
- `pipe_take_segment` 是唯一交给消费者的入口，未发布分段返回错误；
- 测试 fixture 持有所有对象并注入故障，不存在堆分配。

### 9.2 STM32F407 HAL 参考实现

以下代码以 STM32CubeF4 v1.28.3/UM1725 Rev 8 为边界，展示完整外设调用路径。`BOARD_ADC_CHANNEL` 和 `board_adc_gpio_init()` 必须由实际完整料号、封装、原理图与电气条件提供。代码未在目标工程编译，仍需与生成工程合并和核对。

#### 9.2.1 静态对象、诊断和时钟

```c
#include "main.h"

#define PIPE_SAMPLE_COUNT 128U
#define PIPE_HALF_COUNT   (PIPE_SAMPLE_COUNT / 2U)

#define PIPE_EVT_HALF0 (1UL << 0)
#define PIPE_EVT_HALF1 (1UL << 1)
#define PIPE_EVT_ERROR (1UL << 2)

TIM_HandleTypeDef htim2;
ADC_HandleTypeDef hadc1;
DMA_HandleTypeDef hdma_adc1;

_Alignas(uint32_t)
static uint16_t g_samples[PIPE_SAMPLE_COUNT];

typedef struct {
    volatile uint32_t half_generation[2];
    volatile uint32_t events;
    volatile uint32_t first_error;
    volatile uint32_t hal_adc_error;
    volatile uint32_t hal_dma_error;
    volatile uint32_t adc_sr_before_hal;
    volatile uint32_t dma_lisr_before_hal;
    volatile uint32_t adc_sr_at_error;
    volatile uint32_t dma_lisr_at_error;
    volatile uint32_t dma_ndtr_at_error;
} pipeline_diag_t;

static pipeline_diag_t g_diag;

/* 由实际 board/App 层提供；声明在此，避免隐式函数声明。 */
uint8_t board_adc_gpio_init(uint32_t board_adc_channel);
void app_store_pipeline_fault_snapshot(const pipeline_diag_t *diag);

static void SystemClock_Config_Reference(void)
{
    RCC_OscInitTypeDef osc = {0};
    RCC_ClkInitTypeDef clk = {0};

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
    if (HAL_RCC_OscConfig(&osc) != HAL_OK) {
        Error_Handler();
    }

    clk.ClockType = RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK |
                    RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    clk.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    clk.AHBCLKDivider = RCC_SYSCLK_DIV1;
    clk.APB1CLKDivider = RCC_HCLK_DIV4;
    clk.APB2CLKDivider = RCC_HCLK_DIV2;
    if (HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_5) != HAL_OK) {
        Error_Handler();
    }
}
```

`_Alignas(uint32_t)` 适配 F4 HAL 的 `uint32_t *pData` 参数入口；实际 DMA 两端宽度仍为 half-word。数组必须位于 DMA2 可访问的静态存储区。实际链接地址需通过 map 文件和目标总线矩阵核对。

#### 9.2.2 DMA/ADC MSP、ADC 和 TIM2 初始化

```c
static void MX_DMA_Init_Reference(void)
{
    __HAL_RCC_DMA2_CLK_ENABLE();
    HAL_NVIC_SetPriority(DMA2_Stream0_IRQn, 5U, 0U);
    HAL_NVIC_EnableIRQ(DMA2_Stream0_IRQn);
}

void HAL_ADC_MspInit(ADC_HandleTypeDef *hadc)
{
    if ((hadc == NULL) || (hadc->Instance != ADC1)) {
        return;
    }

    __HAL_RCC_ADC1_CLK_ENABLE();

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
        Error_Handler();
    }

    __HAL_LINKDMA(hadc, DMA_Handle, hdma_adc1);

    HAL_NVIC_SetPriority(ADC_IRQn, 5U, 0U);
    HAL_NVIC_EnableIRQ(ADC_IRQn);
}

static HAL_StatusTypeDef MX_ADC1_Init_Reference(uint32_t board_adc_channel)
{
    ADC_ChannelConfTypeDef channel = {0};

    hadc1.Instance = ADC1;
    hadc1.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV4;
    hadc1.Init.Resolution = ADC_RESOLUTION_12B;
    hadc1.Init.ScanConvMode = DISABLE;
    hadc1.Init.ContinuousConvMode = DISABLE;
    hadc1.Init.DiscontinuousConvMode = DISABLE;
    hadc1.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_RISING;
    hadc1.Init.ExternalTrigConv = ADC_EXTERNALTRIGCONV_T2_TRGO;
    hadc1.Init.DataAlign = ADC_DATAALIGN_RIGHT;
    hadc1.Init.NbrOfConversion = 1U;
    hadc1.Init.DMAContinuousRequests = ENABLE;
    hadc1.Init.EOCSelection = ADC_EOC_SINGLE_CONV;
    if (HAL_ADC_Init(&hadc1) != HAL_OK) {
        return HAL_ERROR;
    }

    channel.Channel = board_adc_channel;
    channel.Rank = 1U;
    channel.SamplingTime = ADC_SAMPLETIME_84CYCLES;
    channel.Offset = 0U;
    return HAL_ADC_ConfigChannel(&hadc1, &channel);
}

static HAL_StatusTypeDef MX_TIM2_Init_Reference(void)
{
    TIM_ClockConfigTypeDef clock_source = {0};
    TIM_MasterConfigTypeDef master = {0};

    __HAL_RCC_TIM2_CLK_ENABLE();

    htim2.Instance = TIM2;
    htim2.Init.Prescaler = 83U;
    htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim2.Init.Period = 999U;
    htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    if (HAL_TIM_Base_Init(&htim2) != HAL_OK) {
        return HAL_ERROR;
    }

    clock_source.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
    if (HAL_TIM_ConfigClockSource(&htim2, &clock_source) != HAL_OK) {
        return HAL_ERROR;
    }

    master.MasterOutputTrigger = TIM_TRGO_UPDATE;
    master.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
    return HAL_TIMEx_MasterConfigSynchronization(&htim2, &master);
}
```

`HAL_ADC_MspInit` 不猜 GPIO。实际工程必须在调用 ADC 初始化前执行板级 `board_adc_gpio_init()`，将经核对的 pin 配置为 analog/no-pull，并确认输入条件符合 DS8626。CubeMX 生成工程也可能把 GPIO 初始化放入 MSP；无论放在哪里，板级所有者必须唯一。

#### 9.2.3 组装、启动、停止和恢复

```c
typedef uint8_t pipeline_status_t;
#define PIPELINE_OK             ((pipeline_status_t)0U)
#define PIPELINE_ERR_BOARD      ((pipeline_status_t)1U)
#define PIPELINE_ERR_ADC_INIT   ((pipeline_status_t)2U)
#define PIPELINE_ERR_TIM_INIT   ((pipeline_status_t)3U)
#define PIPELINE_ERR_ADC_START  ((pipeline_status_t)4U)
#define PIPELINE_ERR_TIM_START  ((pipeline_status_t)5U)
#define PIPELINE_ERR_STOP       ((pipeline_status_t)6U)
#define PIPELINE_ERR_RUNTIME    ((pipeline_status_t)7U)
#define PIPELINE_ERR_SYSTEM_INIT ((pipeline_status_t)8U)

static void pipeline_record_first_error(uint32_t error)
{
    if (g_diag.first_error == 0U) {
        g_diag.first_error = error;
    }
}

static void pipeline_reset_session_diag(void)
{
    uint32_t primask = __get_PRIMASK();

    __disable_irq();
    __DMB();
    g_diag = (pipeline_diag_t){0};
    __DMB();
    if (primask == 0U) {
        __enable_irq();
    }
}

static pipeline_status_t Pipeline_Start(void)
{
    g_diag.events = 0U;

    /* Arm DMA + ADC receiver before starting the periodic source. */
    if (HAL_ADC_Start_DMA(&hadc1,
                          (uint32_t *)g_samples,
                          PIPE_SAMPLE_COUNT) != HAL_OK) {
        pipeline_record_first_error(PIPELINE_ERR_ADC_START);
        return PIPELINE_ERR_ADC_START;
    }

    if (HAL_TIM_Base_Start(&htim2) != HAL_OK) {
        (void)HAL_ADC_Stop_DMA(&hadc1);
        pipeline_record_first_error(PIPELINE_ERR_TIM_START);
        return PIPELINE_ERR_TIM_START;
    }
    return PIPELINE_OK;
}

static pipeline_status_t Pipeline_Stop(void)
{
    HAL_StatusTypeDef tim_status;
    HAL_StatusTypeDef adc_status;

    tim_status = HAL_TIM_Base_Stop(&htim2); /* source first */
    adc_status = HAL_ADC_Stop_DMA(&hadc1);
    if ((tim_status != HAL_OK) || (adc_status != HAL_OK)) {
        pipeline_record_first_error(PIPELINE_ERR_STOP);
        return PIPELINE_ERR_STOP;
    }
    return PIPELINE_OK;
}

static pipeline_status_t Pipeline_InitAndStart(uint32_t board_adc_channel)
{
    pipeline_reset_session_diag();

    /* board_adc_gpio_init() is supplied by the actual board layer. */
    if (board_adc_gpio_init(board_adc_channel) != 0U) {
        pipeline_record_first_error(PIPELINE_ERR_BOARD);
        return PIPELINE_ERR_BOARD;
    }

    MX_DMA_Init_Reference();
    if (MX_ADC1_Init_Reference(board_adc_channel) != HAL_OK) {
        pipeline_record_first_error(PIPELINE_ERR_ADC_INIT);
        return PIPELINE_ERR_ADC_INIT;
    }
    if (MX_TIM2_Init_Reference() != HAL_OK) {
        pipeline_record_first_error(PIPELINE_ERR_TIM_INIT);
        return PIPELINE_ERR_TIM_INIT;
    }
    return Pipeline_Start();
}

static pipeline_status_t App_ComposeAndStart(uint32_t board_adc_channel)
{
    /* The system composition root owns shared HAL and clock setup. */
    if (HAL_Init() != HAL_OK) {
        pipeline_record_first_error(PIPELINE_ERR_SYSTEM_INIT);
        return PIPELINE_ERR_SYSTEM_INIT;
    }
    SystemClock_Config_Reference();
    return Pipeline_InitAndStart(board_adc_channel);
}

static pipeline_status_t Pipeline_Recover(void)
{
    pipeline_status_t stop_status = Pipeline_Stop();

    /* Persist the captured first-fault snapshot before clearing/restarting. */
    app_store_pipeline_fault_snapshot(&g_diag);
    if (stop_status != PIPELINE_OK) {
        return stop_status;
    }

    /* Recovery starts a new session after preserving the old snapshot. */
    pipeline_reset_session_diag();
    return Pipeline_Start();
}
```

这里的五个动作明确分开：

1. **声明**：公开 `Pipeline_InitAndStart/Stop` 和诊断快照接口；
2. **实现**：TIM2、ADC1、DMA2 的具体 HAL 代码；
3. **实例化**：静态句柄、buffer 和诊断对象；
4. **组装**：`App_ComposeAndStart()` 作为系统组装根，先持有共享 HAL/时钟初始化，再把板级 channel/GPIO 注入 DMA、ADC、TIM2 流水线；pipeline BSP 不在运行期私自重配共享时钟；
5. **使用**：App 启动后只领取已发布半区，错误时请求恢复。

依赖方向为 `App -> pipeline BSP -> STM32F4 HAL -> registers`；板级 GPIO 信息由 board layer 注入 BSP，而不是由 App 或通用流水线猜测。

#### 9.2.4 IRQ、回调和应用消费

```c
void DMA2_Stream0_IRQHandler(void)
{
    /* HAL may clear serviced flags before invoking the application callback. */
    g_diag.adc_sr_before_hal = ADC1->SR;
    g_diag.dma_lisr_before_hal = DMA2->LISR;
    __DMB();
    HAL_DMA_IRQHandler(&hdma_adc1);
}

void ADC_IRQHandler(void)
{
    g_diag.adc_sr_before_hal = ADC1->SR;
    g_diag.dma_lisr_before_hal = DMA2->LISR;
    __DMB();
    HAL_ADC_IRQHandler(&hadc1);
}

void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef *hadc)
{
    if ((hadc != NULL) && (hadc->Instance == ADC1)) {
        g_diag.half_generation[0]++;
        g_diag.events |= PIPE_EVT_HALF0;
    }
}

void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *hadc)
{
    if ((hadc != NULL) && (hadc->Instance == ADC1)) {
        g_diag.half_generation[1]++;
        g_diag.events |= PIPE_EVT_HALF1;
    }
}

void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *hadc)
{
    if ((hadc != NULL) && (hadc->Instance == ADC1)) {
        g_diag.hal_adc_error = HAL_ADC_GetError(hadc);
        g_diag.adc_sr_at_error = g_diag.adc_sr_before_hal;
        if (hadc->DMA_Handle != NULL) {
            g_diag.hal_dma_error = HAL_DMA_GetError(hadc->DMA_Handle);
            g_diag.dma_lisr_at_error = g_diag.dma_lisr_before_hal;
            g_diag.dma_ndtr_at_error = hadc->DMA_Handle->Instance->NDTR;
        }
        pipeline_record_first_error(PIPELINE_ERR_RUNTIME);
        g_diag.events |= PIPE_EVT_ERROR;
    }
}

typedef struct {
    uint32_t events;
    uint32_t generation[2];
} pipeline_events_t;

static pipeline_events_t Pipeline_TakeEvents(void)
{
    pipeline_events_t snapshot;
    uint32_t primask = __get_PRIMASK();

    __disable_irq();
    __DMB();
    snapshot.events = g_diag.events;
    snapshot.generation[0] = g_diag.half_generation[0];
    snapshot.generation[1] = g_diag.half_generation[1];
    g_diag.events = 0U;
    __DMB();
    if (primask == 0U) {
        __enable_irq();
    }
    return snapshot;
}

static void app_process_half(const uint16_t *samples,
                             uint32_t count,
                             uint32_t generation)
{
    /* App context only: finish before the same half is written again. */
    (void)samples;
    (void)count;
    (void)generation;
}

static void App_RunPipeline(void)
{
    uint32_t consumed_generation[2] = {0U, 0U};

    for (;;) {
        pipeline_events_t event = Pipeline_TakeEvents();
        uint32_t ready_halves = event.events &
                                (PIPE_EVT_HALF0 | PIPE_EVT_HALF1);

        if ((event.events & PIPE_EVT_ERROR) != 0U) {
            if (Pipeline_Recover() != PIPELINE_OK) {
                Error_Handler();
            }
            consumed_generation[0] = 0U;
            consumed_generation[1] = 0U;
            continue;
        }

        /* HT and TC pending together means half 0 has reached reuse risk. */
        if (ready_halves == (PIPE_EVT_HALF0 | PIPE_EVT_HALF1)) {
            pipeline_record_first_error(PIPELINE_ERR_RUNTIME);
            if (Pipeline_Recover() != PIPELINE_OK) {
                Error_Handler();
            }
            consumed_generation[0] = 0U;
            consumed_generation[1] = 0U;
            continue;
        }

        if ((event.events & PIPE_EVT_HALF0) != 0U) {
            if (event.generation[0] != (consumed_generation[0] + 1U)) {
                pipeline_record_first_error(PIPELINE_ERR_RUNTIME);
                if (Pipeline_Recover() != PIPELINE_OK) {
                    Error_Handler();
                }
                consumed_generation[0] = 0U;
                consumed_generation[1] = 0U;
                continue;
            }
            app_process_half(&g_samples[0], PIPE_HALF_COUNT,
                             event.generation[0]);
            consumed_generation[0] = event.generation[0];
        }

        if ((event.events & PIPE_EVT_HALF1) != 0U) {
            if (event.generation[1] != (consumed_generation[1] + 1U)) {
                pipeline_record_first_error(PIPELINE_ERR_RUNTIME);
                if (Pipeline_Recover() != PIPELINE_OK) {
                    Error_Handler();
                }
                consumed_generation[0] = 0U;
                consumed_generation[1] = 0U;
                continue;
            }
            app_process_half(&g_samples[PIPE_HALF_COUNT], PIPE_HALF_COUNT,
                             event.generation[1]);
            consumed_generation[1] = event.generation[1];
        }
    }
}
```

IRQ 入口先只读保存 `ADC_SR` 和 `DMA_LISR`，因为 HAL 分发可能在调用应用错误回调前清除已处理标志；错误回调再把入口快照连同 HAL error code 和 `NDTR` 归档。两个参考 IRQ 使用相同抢占优先级；实际系统若允许它们互相抢占，必须把快照拆成各自的 IRQ 上下文或增加可证明的同步协议。

回调只做常数时间的计数和置位，不打印、不滤波、不重初始化。若一次快照同时含 HT 和 TC，DMA 已到达回卷边界，前半区不再按稳定批次处理；示例将其判为消费者落后并启动新采集会话。generation 能发现同一半区在应用领取前已经发布多次；但这些诊断发现错误时数据可能已经被覆盖，不能把已处理结果追认为有效。正确设计仍应通过 `T_app_worst < T_half`、调度延迟上界和实测余量预防错误。恢复会明确丢弃旧会话的未完成/未消费批次，持久化故障快照后原子清空本会话诊断；若重新启动失败，新会话会重新锁存启动错误。

这个示例用短暂全局关中断取得多字段快照，适用于说明边界，不是所有系统的最终并发方案。加入 RTOS 后应使用与 ISR API、优先级和调度延迟匹配的通知机制；那属于后续并发课程。

## 10. 常见错误

1. **在 TIM2 ISR 中调用 `HAL_ADC_Start_DMA`**：这会重复重配/启动 DMA，并把采样时刻放回软件路径。DMA 应在源启动前武装一次，后续由 TRGO 驱动 ADC。
2. **ADC continuous mode 与外部周期触发同时开启**：一次 trigger 可能展开为连续转换，样本数不再与 timer event 一一对应。
3. **DMA normal mode**：`NDTR` 到零后停住，只得到一个 buffer；持续采样最小形态需要 circular mode。
4. **漏掉 `DMAContinuousRequests`**：ADC/DMA 的持续请求行为不符合预期。必须同时核对 HAL 字段和 `ADC_CR2` 读回。
5. **漏掉 `__HAL_LINKDMA`**：ADC HAL 无法通过句柄关系正确使用 DMA 和分发回调。
6. **把 `Length=128` 当成字节**：half-word 配置下是 128 个 16 位样本，即 256 字节。
7. **在 HT 回调处理整个 buffer**：后半区还在写；HT 只交还前半区。
8. **在 TC 回调继续读前半区**：TC 后 DMA 已回卷并可能开始覆盖前半区。
9. **只用事件 bit，不检查代次**：两个相同事件在主循环领取前发生时会被合并，漏批没有证据。
10. **buffer 放在栈上**：启动函数返回后对象生命周期结束，DMA 仍会写无效地址。
11. **启动 timer 后再武装 ADC/DMA**：早期 TRGO 会丢失，首个批次的边界不再明确。
12. **错误时先清标志再记录**：会丢失首个故障现场。先保存 ADC/DMA 状态、NDTR、flag 和批次计数。
13. **HAL 和 LL 同时拥有 stream**：HAL 状态机与直接寄存器改写互相破坏；一个硬件对象只能有一个配置所有者。
14. **把 callback GPIO 当采样时刻**：GPIO 翻转包含转换、DMA、IRQ 和软件延迟，只能观察软件通知链。
15. **在断点下判断实时性**：CPU 暂停而 timer/ADC/DMA 可能继续，人工制造 OVR 或消费者落后。
16. **把 F407 映射复制到 H7/H5**：请求控制器、内存域、缓存和安全属性可能完全不同。

## 11. 调试观察点

按上游到下游逐段采证：

| 顺序 | 观察点 | 成功证据 | 仍不能证明 |
| --- | --- | --- | --- |
| 1 | RCC/clock | 时钟 ready/switch 正确；DMA2EN、TIM2EN、ADC1EN 置位 | 实际频率已经测量 |
| 2 | TIM2 配置 | PSC=83、ARR=999、MMS=update | timer 正在运行 |
| 3 | TIM2 运行 | CEN=1、CNT 变化、UIF 周期出现 | ADC 接受了 TRGO |
| 4 | ADC 配置 | EXTSEL=T2_TRGO、EXTEN=rising、CONT=0、DMA/DDS 符合预期 | ADC 输入电气正确 |
| 5 | DMA 静态配置 | CHSEL=0、DIR=P2M、CIRC/MINC=1、PSIZE/MSIZE=half-word | request 正在到达 |
| 6 | DMA 运行 | EN=1、PAR 指向 ADC1_DR、M0AR 指向 buffer、NDTR 递减 | 应用及时消费 |
| 7 | IRQ/HAL | HTIF0/TCIF0 到达并清除；回调 generation 增长 | 没有漏批或时序余量充足 |
| 8 | App | consumed generation 连续，处理时间小于半区周期 | ADC 绝对精度达标 |

故障定位树：

```text
TIM2 CNT 不动
  -> 查 HSI/PLL/switch/APB1、TIM2EN、复位释放、CEN

CNT/UIF 正常，ADC 无转换
  -> 查 MMS、EXTSEL/EXTEN、ADC enable、初始化 UG 和启动顺序

ADC EOC/DR 变化，NDTR 不动
  -> 查 ADC DMA/DDS、DMA2 clock、Stream0/Channel0、EN、PAR/M0AR

NDTR 递减，无 HT/TC callback
  -> 查 HTIE/TCIE、LISR、NVIC enable/pending、向量入口和句柄

callback 增长，App 无批次
  -> 查事件快照、generation、主循环阻塞和中断临界区

出现 TE/DME/FE
  -> 保存 LISR/NDTR/PAR/M0AR/CR/FCR，核对地址、宽度、可达内存和 FIFO 配置

出现 ADC OVR
  -> 保存 ADC_SR/HAL errors，核对转换间隔、DMA request、断点影响和总线服务

generation 跳变
  -> 消费者超过 T_half 或中断长期屏蔽；先停源，不能继续使用已覆盖批次
```

推荐断点：`Pipeline_Start` 的两个启动调用、`DMA2_Stream0_IRQHandler`、三个 ADC 回调和 `Pipeline_Recover`。观察寄存器时以只读为主；调试器写寄存器会改变被观察系统。

## 12. 实战实验

### 实验 A：Host Fake 正常流和边界

1. 将 9.1 节代码放入独立主机测试文件，用 C11 和严格 warning 编译。
2. 记录编译器版本、命令、完整输出、退出码和测试退出码。
3. 在正常用例中验证样本 `100..107` 依序出现，HT 只发布前 4 项，TC 只发布后 4 项。
4. 在分段尚未完成前调用 `pipe_take_segment`，断言返回 `PIPE_ERR_SEGMENT_NOT_READY`。
5. 让消费者及时领取两个半区，运行多个回卷周期，断言 trigger、conversion 和 DMA write 计数保持一致。

合格结论仅是 Host Fake 所有权模型通过，不是目标构建或硬件证据。

### 实验 B：速率和故障注入

1. 保持 trigger period=3 ticks，把 conversion 从 1 改为 4，确认第二个 trigger 到来时报告 ADC busy 并停源。
2. 不领取首轮两个半区，确认 DMA 准备再次写前半区时报告 consumer late，而不是覆盖后继续。
3. 注入 `fault_on_next_request`，确认没有伪造 DMA write 或发布事件。
4. 新增 timer stopped、ADC not armed、DMA stopped 和非法 buffer length 用例。
5. 对每个用例记录首错、停止状态、三个计数和已发布 generation。

### 实验 C：CubeMX 静态审计

1. 固定实际 F407 完整料号和板级 ADC 输入；没有这些信息时将实验标记为阻塞。
2. 按 7.3 配置 `.ioc`，保存 CubeMX/CubeMX2 与 STM32CubeF4 版本。
3. 生成后搜索 `TIM_TRGO_UPDATE`、`ADC_EXTERNALTRIGCONV_T2_TRGO`、`ADC_EXTERNALTRIGCONVEDGE_RISING`、`DMA_CIRCULAR`、`DMA_CHANNEL_0` 和 `__HAL_LINKDMA`。
4. 确认 `MX_DMA_Init` 先于 ADC init，ADC/DMA start 先于 TIM2 start。
5. 对照 7.5 生成一张 HAL 字段、LL 读值和预期寄存器字段表。

静态审计不构成目标构建、烧录或运行证据。

### 实验 D：目标构建与读回计划

1. 记录板卡、完整 MCU marking、原理图版本、输入源、VDDA/VREF、调试器、Cube 包和工具链版本。
2. 将 board GPIO/channel 注入点接入实际工程，执行 clean build；保存命令、完整日志、退出码、warning 和产物哈希。
3. 烧录前停在 `Pipeline_Start`，读回时钟、PSC/ARR/MMS、EXTSEL/EXTEN、DMA CR/PAR/M0AR/NDTR。
4. 单步越过 `HAL_ADC_Start_DMA` 后确认 stream 与 ADC 已武装，再启动 TIM2。
5. 自由运行，使用定时窗口读取 HT/TC generation、NDTR 和错误计数；不要用长期单步估算吞吐。
6. 当前课程没有执行这些步骤，结果必须由未来运行记录提供。

### 实验 E：半区时限和错误注入

1. 在 App 处理入口和出口读取适合目标的周期计数器或切换一个已核对 GPIO，测量 `T_app_worst`。
2. 对比 `T_app_worst` 与 64 ms 参考半区周期，并记录最大值而非平均值。
3. 暂时让 App 延迟超过半区周期，验证 generation 跳变诊断；实验后恢复。
4. 分别停止 TIM2、故意选择错误 ADC trigger、禁用 DMA IRQ，观察故障停在哪一级。
5. 不要用超出数据手册范围的模拟电压注入故障。

### 实验 F：F7/H5/H7 迁移审计

为一个具体完整料号填写：timer/ADC kernel clock、合法 trigger route、DMA/DMAMUX/GPDMA request、IRQ/flag、buffer 可达内存、D-Cache/MPU、TrustZone/安全域、目标 Cube 包版本。任何空项都表示迁移尚未完成，不能复用 F407 值代填。

## 13. 自检题

1. 为什么 `TIM2_SR.UIF` 周期出现仍不能证明 buffer 正在更新？
2. 为什么参考配置关闭 ADC continuous mode，却开启 DMA continuous requests？
3. `NDTR=128`、两端 half-word 时，样本数和字节数分别是多少？
4. HT 到达后，DMA 和应用分别拥有哪个半区？
5. TC 到达后，为什么应用不能继续读取旧的前半区？
6. `T_conv < T_trigger` 与 `T_app_worst < T_half` 分别保护哪一级？
7. 为什么回调中只递增 generation，而不执行滤波？
8. `__HAL_LINKDMA` 对 IRQ 到 ADC 回调的分发有什么作用？
9. `DMA2_Stream0_IRQHandler` 已进入但 ADC half callback 不发生，应按什么顺序检查？
10. 为什么 bitmask 事件不足以证明没有漏批？
11. 错误恢复为何要先停 TIM2，再停 ADC/DMA？
12. Host Fake 的 consumer late 能证明真实 F407 一定没有总线问题吗？为什么？
13. F407 参考配置中 `PCLK1=42 MHz`，为何 TIM2 kernel 是 84 MHz？
14. ADCCLK=21 MHz 为何不等于采样率 21 Msps？
15. 从 F407 迁移到 H7，哪些所有权原则可保留，哪些硬件事实必须重查？

建议答案应分别指出事件证据、数据证据、所有权和时间预算，不能只说“检查配置”。

## 14. 面试题

### 14.1 设计 timer-triggered ADC DMA circular buffer 时，最重要的四个约束是什么？

应包含：合法且稳定的硬件触发链；ADC 转换时间小于触发周期；DMA 请求映射、宽度和内存可达性正确；应用最坏处理时间小于半区重用时间，并有漏批/错误诊断。

### 14.2 HT/TC 是否等于双缓冲？

不等于。本课用一个 circular array 的中点和终点事件形成两个逻辑半区；硬件 double-buffer mode 通常在 `M0AR/M1AR` 两个目标地址间切换，并有 current target 等不同状态。两者都可形成交接，但配置和错误边界不同。

### 14.3 为什么不能在 DMA 回调里直接处理 64 个样本？

回调处于中断上下文。长时间处理会延迟其他中断、扩大最坏时延，甚至让下一次边界到来前仍未返回。回调应发布分段和错误，应用上下文按预算处理；是否需要 RTOS 通知由后续架构决定。

### 14.4 如何证明一次 timer event 最终成为一个按序样本？

分层证据应包括：TIM2 update/TRGO 配置和频率；ADC trigger selection、EOC/OVR；DMA request 映射、NDTR 递减和地址；HT/TC generation；buffer 中已知输入对应的顺序；错误计数为零。仅看 callback frequency 或某个 HAL 返回值都不够。

### 14.5 消费者偶尔超过半区时间，扩大 buffer 就一定能解决吗？

扩大 buffer 增加 `T_half`，可以吸收更长抖动，但也增加延迟和内存占用，不能消除无界阻塞或错误优先级。应测量最坏时间、识别阻塞源、设计丢批/停源策略，再决定容量。

### 14.6 F7/H7 上 DMA 写完，CPU 为何仍可能读到旧数据？

带 D-Cache 的内核可能从 cache line 读取旧副本，而 DMA 直接更新内存。所有权交接需增加目标相关的 cache/MPU 策略、对齐和 invalidate/clean 顺序。这是 `dma-coherency` 的核心问题，不能把 F407 无 D-Cache 的代码直接复制过去。

## 15. 延伸思考

1. 若加入 4 个 ADC channel，buffer 中的“半区”应按样本数还是完整 frame（帧）边界交还？
2. 若每个批次还需要精确时间戳，应该让另一个 timer capture、DMA 或软件在哪个边界记录？会引入什么同步误差？
3. 如何让硬件过载、DMA error、应用漏批分别拥有独立计数，而不是都折叠成一个 error bit？
4. 若输入处理需要改变采样率，PSC/ARR 应在什么安全边界更新，如何防止半批使用两个采样周期？
5. 使用 double-buffer mode 后，谁判断 current target，何时允许应用归还 buffer？
6. H5 的 secure ADC/DMA 向 non-secure 应用交付数据时，所有权和访问控制需要增加哪些主体？
7. 低功耗进入前应该停哪一级，唤醒后怎样证明第一个有效批次没有混入恢复期样本？

## 16. 本节总结

本课唯一的新核心概念是 **ADC-定时器-DMA 分段缓冲流水线**：

```text
TIM2 update/TRGO defines when
  -> ADC1 converts one sample
  -> DMA2 moves one half-word without per-sample CPU work
  -> HT/TC transfers one stable half-buffer to software ownership
  -> App consumes before that half is reused
  -> errors stop the source, preserve evidence, then recover explicitly
```

它成立需要四类约束共同满足：触发链合法、转换预算足够、DMA 契约正确、消费者在半区时限内完成。对象由 fixture 或 BSP 静态持有，初始化者注入配置，timer/ADC/DMA 注入运行事件，回调只发布边界，应用消费稳定分段。

Host Fake 证明状态、所有权和错误模型；STM32F407xx 参考实现把同一模型落实到 `TIM2 -> ADC1 -> DMA2 Stream0/Channel0`、时钟/复位、CubeMX、HAL、LL、寄存器和 IRQ。两条轨道互相解释，但证据不能互换。当前未编译目标代码、未烧录、未测量，`hardware_verified=false`。

## 17. 下一步

下一主题 `peripheral-integration-lab` 应固定一块真实板卡、完整 MCU、模拟输入和批处理需求，把本文参考链推进为可构建、可读回、可测量的系统实验。若目标改为 F7/H7 且启用 D-Cache，应先创建 `dma-coherency` 专题，固定 buffer 内存区域、cache line 对齐与 MPU/cache 策略；不能由本课 F407 或 Host Fake 结论直接外推。

## 18. 参考资料

- [S1] STMicroelectronics, *STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 advanced Arm-based 32-bit MCUs - Reference manual*, RM0090 Rev 22, May 2026：RCC、TIM2、ADC regular external trigger/DMA/EOC/OVR、DMA2 request mapping、stream registers、status and interrupt flags；访问日期 2026-10-15。<https://www.st.com/resource/en/reference_manual/dm00031020.pdf>
- [S2] STMicroelectronics, *STM32F405xx STM32F407xx datasheet*, DS8626 Rev 12, March 2026：器件范围、clock/electrical limits、ADC input and package boundaries；访问日期 2026-10-15。<https://www.st.com/resource/en/datasheet/stm32f407vg.pdf>
- [S3] STMicroelectronics, *Description of STM32F4 HAL and low-layer drivers*, UM1725 Rev 8, March 2023：TIM/ADC/DMA HAL and LL initialization、start/stop、IRQ、callback and error APIs；访问日期 2026-10-15。<https://www.st.com/resource/en/user_manual/dm00105879.pdf>
- [S4] STMicroelectronics, *Using the STM32F2/F4/F7 DMA controller*, AN4031 DocID022648 Rev 3, June 2016：stream/channel、arbitration、FIFO、circular/double-buffer behavior and error analysis；具体 F407 mapping 仍以 RM0090 为准；访问日期 2026-10-15。<https://www.st.com/resource/en/application_note/an4031-using-the-stm32f2f4f7-series-dma-controller-stmicroelectronics.pdf>
- [S5] STMicroelectronics, *STM32Cube MCU Package for STM32F4 series*, STM32CubeF4 v1.28.3, 23 July 2025：`stm32f4xx_hal_adc.*`、`stm32f4xx_hal_dma.*`、`stm32f4xx_hal_tim.*`、LL headers and CMSIS device header 的代码边界；访问日期 2026-10-15。<https://www.st.com/en/embedded-software/stm32cubef4.html>
- [S6] STMicroelectronics, *STM32Cube MCU Package for STM32F7 series*, STM32CubeF7 v1.17.3, 25 April 2025：仅用于限定 F7 clock/DMA/cache/API 迁移复查范围；访问日期 2026-10-15。<https://www.st.com/en/embedded-software/stm32cubef7.html>
- [S7] STMicroelectronics, *STM32Cube MCU Package for STM32H5 series*, STM32CubeH5 v1.5.0, 5 February 2025：仅用于限定 H5 GPDMA/DMAMUX/security/API 迁移复查范围；访问日期 2026-10-15。<https://www.st.com/en/embedded-software/stm32cubeh5.html>
- [S8] STMicroelectronics, *STM32Cube MCU Package for STM32H7 series*, STM32CubeH7 v1.12.1, 6 December 2024：仅用于限定 H7 clock/DMA/DMAMUX/memory-domain/cache/API 迁移复查范围；访问日期 2026-10-15。<https://www.st.com/en/embedded-software/stm32cubeh7.html>

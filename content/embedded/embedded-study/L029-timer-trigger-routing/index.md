+++
title = "定时器触发路由：从 TIM2 更新事件到 ADC1 转换"
date = "2026-10-13T16:00:04+08:00"
lastmod = "2026-10-13T16:00:04+08:00"
summary = "建立定时器触发路由的事件链，用 C11 Host Fake 验证源事件、路由、接收端选择与错误边界，并以 STM32F407xx 的 TIM2 更新事件到 ADC1 外部触发路径核对时钟、CubeMX、HAL、LL、寄存器和 IRQ 证据。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 29
tags = ["timer", "trigger-routing", "trgo", "adc", "tim2", "stm32f407", "cubemx", "hal", "ll", "registers", "host-fake", "c11"]
source_ids = ["st-rm0090-timer-trigger-routing", "st-ds8626-timer-trigger-routing", "st-um1725-timer-trigger-routing", "st-stm32cubef4-1.28.3", "st-stm32cubef7-1.17.3", "st-stm32cubeh5-1.5.0", "st-stm32cubeh7-1.12.1"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L029"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 29 课：定时器触发路由

软件可以在定时器中断里调用 HAL（hardware abstraction layer，硬件抽象层）的 `HAL_ADC_Start()`，但这样会把中断响应时间和软件抖动加入采样时刻。更直接的做法是让定时器事件在芯片内部成为 ADC（analog-to-digital converter，模数转换器）的启动条件：CPU 负责先配置和使能，稳定运行阶段由硬件事件链推进。

本课只推进一个新核心概念：**定时器触发路由的事件链**，即把“源事件 -> 触发输出 -> 芯片内部路由 -> 接收端触发选择/边沿 -> 接收端动作 -> 可观察证据”串成一条可逐段核对的因果链。TRGO（trigger output，触发输出）、ITR（internal trigger，内部触发）、主模式和 ADC 外部触发是解释这条链的辅助术语，不是额外核心概念。

课程采用两条严格分开的轨道：Host Fake（主机替身）验证状态机、所有权和拒绝路径；STM32 轨道落实到 `STM32F407xx` 的 `TIM2 更新事件 -> TIM2_TRGO -> ADC1 常规组转换`。当前没有具体开发板、完整订货料号、板级时钟、ADC 引脚与模拟输入，也没有目标构建、烧录或测量记录。STM32 代码均为“参考实现，待目标工程编译和上板验证”，`hardware_verified=false`。

## 1. 本节目标

完成本课后，你应能：

1. 用一条事件链解释定时器为何不需要 CPU 中断也能启动 ADC；
2. 区分源事件存在、TRGO 选择正确、内部连接合法、ADC 选择匹配、边沿允许和转换完成六类证据；
3. 说明配置对象在哪里定义、谁持有、谁注入，以及事件如何从定时器流到 ADC；
4. 在 Host Fake 中覆盖停止、错误 TRGO、断路、接收端不匹配和边沿拒绝；
5. 在 STM32F407xx 上追踪 TIM2 与 ADC1 的完整时钟/复位链，并计算触发周期和转换预算；
6. 把 CubeMX/HAL 配置对应到 LL（low-layer，低层驱动）操作及 `RCC`、`TIM2`、`ADC1` 的关键寄存器和状态位；
7. 说明最小链路为何不需要 TIM2 IRQ，以及 ADC IRQ、DMA 回调分别能证明什么；
8. 迁移到 F7、H5、H7 时保留追踪方法，同时重新核对目标器件的时钟、触发表、API 和系统属性。

核心目标与本次计划逐字一致：建立定时器触发路由的事件链，能够从定时器事件追踪到内部触发输出、接收外设的触发选择和可观察结果，并以 STM32F407xx 的定时器到 ADC 参考路径核对实现与证据边界。

## 2. 它解决什么问题

### 2.1 中断回调不是硬件触发的必要中转站

下面两种路径都可能让 ADC 开始转换，但时间性质不同：

```text
软件中转：TIM update -> TIM IRQ -> CPU/HAL callback -> ADC software start
硬件路由：TIM update -> TIM TRGO -> ADC trigger mux/edge -> ADC conversion
```

其中 IRQ（interrupt request，中断请求）进入 ISR（interrupt service routine，中断服务程序）。第一条路径适合执行软件决策；第二条路径把事件关系固定在外设内部，避免把 ISR 的进入延迟变成采样时刻的一部分。硬件路由仍需要 CPU 完成初始化、错误处理和结果消费，但每个触发不需要 CPU 搬运一次“开始”命令。[S1]

### 2.2 “定时器在跑”不等于“ADC 被触发”

计数器变化只证明定时器时钟和 `CEN` 等前置条件成立。完整成功还要求：

```text
TIM2 到达更新条件
  -> 更新事件被 MMS 选择为 TIM2_TRGO
  -> ADC1 的触发选择指向 TIM2_TRGO
  -> ADC1 允许所需边沿
  -> ADC1 已使能且前一次转换允许接受新触发
  -> ADC 置位 STRT/EOC，数据进入 ADC_DR
  -> 可选 ADC IRQ 分发到 HAL 和应用回调
```

任何一跳不匹配，前一跳仍可能看起来完全正常。触发路由模型解决的正是这种“源正常、结果不动”的定位问题。

### 2.3 本课边界

- 深入一个合法路径：`TIM2 update -> TIM2_TRGO -> ADC1 regular conversion`。
- 不把 TIM2 主从同步网络作为第二概念；ITR 只用于与当前 ADC 路径辨析。
- 不把 DMA（direct memory access，直接存储器访问）缓冲区所有权、半满/完成回调并入本课；它属于 `adc-timer-dma-pipeline`。
- 不展开互补输出、死区、刹车和重复计数；它们属于 `advanced-control-timer`。
- 不指定 ADC 通道或引脚，因为封装、板卡和模拟输入尚未给出。

## 3. 必要前置知识

本课依赖已经完成的 `timer`、`adc`、`dma`、`clock-tree` 和 `hal-ll-register-crosswalk`。只复习当前链路直接需要的结论：

- 边沿向上计数模式下，定时器更新节拍由定时器内核时钟、`PSC`（prescaler，预分频器）和 `ARR`（auto-reload register，自动重装载寄存器）共同决定。
- ADC 的“软件启动”和“外部触发”是两种启动条件；配置外部触发后，启动 API 的作用通常是使能并武装接收端，而不是伪造一次定时器事件。
- RCC（reset and clock control，复位与时钟控制器）的门控、外设复位、外设运行使能是三类动作。
- HAL API 返回成功、寄存器配置正确、硬件事件发生、IRQ 被服务、应用消费完成是不同证据层。
- ADC 时钟决定单次转换耗时；它本身不是采样率。周期触发频率还受转换时间和应用处理能力约束。

## 4. 核心原理

### 4.1 一条链，六个检查点

| 检查点 | 它解决的问题 | 配置或事件 | 可观察证据 |
| --- | --- | --- | --- |
| 源事件 | 何时产生一次节拍 | TIM2 计数模式、PSC、ARR | `CNT` 变化、`SR.UIF`、更新频率 |
| 触发输出 | 哪一种内部事件离开源外设 | 主模式 `MMS=update` | `TIM2_CR2.MMS` 读回；不能仅凭 `UIF` 推断 |
| 内部路由 | 该信号能否到达接收端 | F407 ADC 外部触发表中的 `TIM2_TRGO` 输入 | RM0090 路由表 + ADC 选择读回 |
| 接收选择 | 接收端听谁、听哪个边沿 | `ADC_CR2.EXTSEL/EXTEN` | 选择值和边沿读回 |
| 接收动作 | ADC 是否已使能并接受事件 | `ADON`、规则组序列、转换空闲条件 | `SR.STRT/EOC/OVR`、`DR` |
| 软件证据 | 谁观察或消费结果 | 可选 ADC IRQ/HAL handler/回调 | IRQ 计数、回调计数、错误码、样本值 |

每一行都只能证明本行及其之前已观测到的条件。比如 `TIM2_SR.UIF=1` 不能证明 `ADC_SR.EOC=1`；ADC 回调计数增加则至少证明触发、转换、EOC、中断和 HAL 分发已经走通。

### 4.2 对象、持有、注入和流动

| 问题 | Host Fake | STM32F407xx 参考轨道 |
| --- | --- | --- |
| 对象在哪里定义 | 公共类型定义 timer、route、ADC 和故障码 | HAL/CMSIS 定义句柄、寄存器和宏；板级支持包（board support package，BSP）目标适配文件定义实例 |
| 谁持有 | 测试在栈上持有完整 fixture，无动态内存 | BSP 静态持有 `htim2`、`hadc1` 和诊断记录，生命周期覆盖初始化到停止 |
| 谁注入 | 测试注入使能、选择、路由连通性与边沿故障 | CubeMX/目标 BSP 注入时钟参数、主模式、ADC 外部触发和板级通道 |
| 调用如何流动 | `fake_timer_tick -> fake_route_deliver -> fake_adc_trigger` | `HAL_TIM_Base_Start` 后：TIM2 update -> TRGO -> ADC1；完成后 ADC IRQ -> HAL -> callback |
| 谁消费 | 测试读取计数和拒绝原因 | 应用从 ISR 写入的最小诊断记录中读取事件和最新样本 |

这不是软件架构课，因此不额外引入函数指针或动态组装。重要的是：配置由软件持有，周期事件由硬件注入，二者不能混成一个“调用了所以必然发生”的结论。

### 4.3 TRGO、ITR 与 ADC 触发输入不要混写

TRGO 是定时器向芯片内部导出的触发信号。定时器作为源时，通过主模式选择 `MMS` 决定 TRGO 代表 enable、update 或比较参考等哪一种事件。ITR 是定时器作为接收端时可选择的内部触发输入，常与 `TIMx_SMCR.TS/SMS` 一起构成定时器主从网络。[S1]

本课接收端是 ADC1，不是另一个定时器。F407 的 ADC1 通过 `ADC_CR2.EXTSEL/EXTEN` 多路选择器（multiplexer，简称 mux）选择 `TIM2_TRGO` 及边沿；这里没有要填写的 `TIMx_SMCR.TS=ITRy`。把 ITR 编号硬塞进 `TIM2 -> ADC1` 路径，会把两种接收端的触发选择器混淆。

### 4.4 更新事件不只可能来自自然溢出

在向上计数模式下，计数器从 `ARR` 回卷会形成更新事件；软件写 `EGR.UG` 也可请求更新，以装载预分频等预装载值。[S1] 当 `MMS=update` 时，初始化阶段的软件更新也可能具有 TRGO 含义。稳妥顺序是先完成 TIM2 初始化和必要的更新生成，再配置/武装 ADC，最后才启动 TIM2；调试时不要在 ADC 已武装后随意写 `UG`，否则可能人为制造一次转换。

### 4.5 频率与吞吐预算

对本课参考参数，使用 HSI 16 MHz 经 PLL 得到 168 MHz SYSCLK：

```text
HCLK = 168 MHz
APB1 prescaler = /4 -> PCLK1 = 42 MHz
APB1 prescaler != 1 -> TIM2 kernel clock = 2 * PCLK1 = 84 MHz
PSC = 83 -> counter clock = 84 MHz / (83 + 1) = 1 MHz
ARR = 999 -> update/TRGO = 1 MHz / (999 + 1) = 1 kHz

APB2 prescaler = /2 -> PCLK2 = 84 MHz
ADC common prescaler = /4 -> ADCCLK = 21 MHz
12-bit, sample time = 84 cycles -> reference conversion budget
  = (84 + 12) / 21 MHz ~= 4.57 us
trigger period = 1 ms, greater than this single-conversion budget
```

APB 分频不为 1 时的定时器倍频规则、ADC 公共分频和 12-bit 转换周期关系应按 RM0090/DS8626 对目标订货料号复核。[S1][S2] `4.57 us` 是由参考配置推导的预算，不是本次测量结果；模拟源阻抗还可能要求更长采样时间。

## 5. 关键术语与直观模型

把内部路由想成一组已经焊在硅片里的信号线和多路选择器：

```text
事件生产者                 固定片内连接                事件消费者
TIM2 counter
  -> update event
  -> CR2.MMS selects update
  -> TIM2_TRGO ----------> ADC1 CR2.EXTSEL selects TIM2_TRGO
                            ADC1 CR2.EXTEN accepts rising edge
                            -> sample/convert -> EOC/OVR
```

软件不能任意拉一根新线，只能从目标器件手册列出的连接中选择。源端和接收端各自正确仍不够，中间必须存在目标器件明确支持的路径。STM32CubeF4 v1.28.3 的 HAL/LL 头文件与 RM0090 对该路径分别提供 `TIM_TRGO_UPDATE`、`ADC_EXTERNALTRIGCONV_T2_TRGO`、`LL_TIM_TRGO_UPDATE` 和 `LL_ADC_REG_TRIG_EXT_TIM2_TRGO`。[S1][S3][S4]

## 6. 从输入到结果的完整流程

### 6.1 初始化控制流

```text
HAL_Init
  -> SystemClock_Config_Reference
       -> HSI ready -> PLL ready -> SYSCLK switch
       -> AHB/APB prescalers and Flash latency
  -> board_adc_gpio_init          [板级待填]
  -> MX_TIM2_Init_Reference
       -> TIM2 clock gate/reset release
       -> PSC/ARR/counter mode
       -> master TRGO = update
  -> MX_ADC1_Init_Reference
       -> ADC1 clock gate/shared reset release
       -> ADC common prescaler, rank/channel/sample time
       -> external source = TIM2_TRGO, edge = rising
       -> ADC_IRQn configured for observation
  -> BSP_TriggerChain_Start
       -> HAL_ADC_Start_IT         [先武装接收端]
       -> HAL_TIM_Base_Start       [后启动源]
```

### 6.2 稳态硬件事件流

```text
TIM2 counter reaches update condition
  -> update event / UIF
  -> TIM2_CR2.MMS exports update as TIM2_TRGO
  -> ADC1 trigger mux selected by EXTSEL sees TIM2_TRGO
  -> EXTEN rising-edge permission accepts event
  -> ADC1 samples selected board channel and converts
  -> ADC1_SR.EOC; result in ADC1_DR
  -> optional ADC_IRQn
  -> ADC_IRQHandler
  -> HAL_ADC_IRQHandler(&hadc1)
  -> HAL_ADC_ConvCpltCallback
  -> application later consumes diagnostic snapshot
```

TRGO 到 ADC 开始这一段没有 `TIM2_IRQHandler`、`HAL_TIM_PeriodElapsedCallback` 或软件启动调用。ADC IRQ 只用于观察转换结果；即使关闭 ADC IRQ，硬件触发仍可发生，只是必须改用轮询或 DMA 获取证据。

### 6.3 停止与错误流

停止按“先停源，后停接收端”的顺序：

```text
HAL_TIM_Base_Stop(&htim2)
  -> 不再产生周期更新/TRGO
HAL_ADC_Stop_IT(&hadc1)
  -> 禁止 EOC/OVR interrupt，停止规则组接收
```

启动 TIM2 失败时，应回滚已经武装的 ADC。运行期出现 ADC overrun（过载）时，`HAL_ADC_ErrorCallback` 记录 `HAL_ADC_GetError()` 和 `ADC_SR.OVR` 对应证据，再由非 ISR 上下文决定停止、丢样还是恢复。不能在错误回调里无限重启并抹掉首个故障现场。

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

| 层级 | 能力、工作原理与链路 | 本课范围或后续落点 |
| --- | --- | --- |
| 基础 | 更新、比较等定时器事件；`PSC/ARR` 把内核时钟分成确定节拍；软件可轮询 flag 或启用中断 | 本课以更新事件作为唯一源事件 |
| 进阶 | 主模式把源事件导出为 TRGO；接收外设用自己的 mux 和边沿选择接受事件；接收端不一定是另一个 timer | 本课完整深入 `TIM2 update -> TRGO -> ADC1` |
| 高级 | 多定时器同步可用一个 TRGO 驱动接收 timer 的 reset/gated/trigger 模式；预装载决定参数何时生效；中心对齐和重复计数改变更新时刻；控制定时器的刹车可在故障时异步压制输出 | `advanced-control-timer` 核对具体触发/输出/安全链，不在本课配置这些字段 |
| 跨外设联动 | Timer 规定采样时刻，ADC 完成转换后发 DMA 请求，DMA 填充分段缓冲并在半满/完成时通知软件；触发节拍、转换时间、搬运带宽和缓冲所有权共同决定是否丢样 | `adc-timer-dma-pipeline` 落实 `TRGO -> ADC -> DMA -> IRQ/应用消费` |
| 系列差异 | “源事件 -> 导出 -> 固定路由 -> 接收选择 -> 动作 -> 证据”可迁移；宏名、选择编码、时钟域、ADC 启动条件和系统属性不可从 F4 外推 | 本课只实现 F407；F7/H5/H7 按下表重新建图 |

高级功能不是更多名称，而是改变事件链的时刻或故障边界。例如预装载把 CPU 写入值与硬件实际使用值分开，到更新事件才把影子值装入工作路径；重复计数器则让若干个计数周期后才发更新；刹车输入沿独立安全路径压制 PWM 输出。它们都会改变“哪个事件何时成为 TRGO/输出证据”，所以后续课必须把触发链、输出链和故障链同时画出。

F4/F7/H5/H7 的迁移检查：

| 系列 | 保留的方法 | 必须重新核对并实测的内容 |
| --- | --- | --- |
| F4 | 本课六检查点和先接收端、后源端的启动顺序 | 本文编码只限 RM0090 覆盖器件；换 F4 子系列仍查 timer/ADC 实例、触发表、最大时钟和引脚 |
| F7 | 同样追踪 TRGO 到 ADC mux，不用 TIM ISR 模拟硬件链 | 目标 RM 的 ADC `EXTSEL` 编码、timer 时钟规则、HAL/LL 常量；若后续接 DMA，还要加入 Cortex-M7 数据缓存（data cache，D-Cache）与内存可达性证据 [S5] |
| H5 | 同样先证明源、路由和接收动作 | 选定完整型号后重查 ADC kernel clock、trigger mux、TrustZone/安全属性；后续 DMA 使用 GPDMA 时重建 request/channel/linked-list 与安全归属 [S6] |
| H7 | 同样以事件链而非 API 相似度迁移 | 选定 H7 子系列后重查时钟域、ADC kernel clock/校准、trigger 编码、DMA/DMAMUX、存储域和 D-Cache；双核型号还要确定初始化与 IRQ 所属核 [S7] |

表中 F7/H5/H7 只定义迁移审计面，不给出未经目标参考手册冻结的寄存器值或请求编号。实施时应为目标完整料号另建来源清单，不能把 F407 的 `EXTSEL=0110` 复制过去。

### 7.2 参考目标与时钟/复位链

#### 参考边界

- 器件范围：`STM32F407xx`，具体封装和完整订货料号待填。
- 参考手册：RM0090 Rev 22；数据手册：DS8626 Rev 12。[S1][S2]
- HAL/LL 说明：UM1725 Rev 8；实际核对包：STM32CubeF4 v1.28.3。[S3][S4]
- 固定内部路径：`TIM2 update -> TIM2_TRGO -> ADC1 regular trigger`。
- 板级待填：时钟源条件、ADC channel/pin、VDDA/VREF+、信号范围和源阻抗、调试器及 IRQ 优先级政策。

#### 完整时钟、门控与复位链

```text
板级参考时钟：HSI 16 MHz（片内；实际项目可改，但必须重新计算）
  -> PLLM /16 = 1 MHz
  -> PLLN x336 = 336 MHz VCO
  -> PLLP /2 = 168 MHz SYSCLK
  -> AHB /1 = 168 MHz HCLK / Cortex-M4 core clock
       |
       +-> APB1 /4 = 42 MHz PCLK1
       |    -> APB1 prescaler != 1, TIM2 kernel clock = 84 MHz
       |    -> RCC_APB1ENR.TIM2EN gate
       |    -> optional RCC_APB1RSTR.TIM2RST pulse then release
       |    -> PSC /84 -> 1 MHz counter clock
       |    -> ARR /1000 -> 1 kHz update -> TIM2_TRGO
       |
       +-> APB2 /2 = 84 MHz PCLK2
            -> RCC_APB2ENR.ADC1EN gate
            -> optional shared RCC_APB2RSTR.ADCRST pulse then release
            -> ADC common prescaler /4 = 21 MHz ADCCLK
            -> sample 84 cycles + 12-bit conversion 12 cycles
            -> EOC/OVR -> optional ADC_IRQn
```

必须区分六个动作：

1. `TIM2EN/ADC1EN` 是时钟门控，允许模块寄存器接口和内部逻辑获得时钟；
2. `TIM2RST/ADCRST` 是复位请求，必须随后释放；`ADCRST` 影响 ADC 公共复位域，运行期不能当 ADC1 私有恢复按钮；
3. `TIM2_CR1.CEN` 是计数使能，只有它开始后才有周期计数；
4. `TIM2_CR2.MMS=update` 选择 TRGO 含义，不等于启动计数；
5. `ADC_CR2.EXTSEL/EXTEN` 选择来源和边沿，不等于 ADC 已使能；
6. `ADC_CR2.ADON` 与外部事件共同构成转换启动条件；外部触发模式不靠 `SWSTART` 周期启动。

复位操作只放在启动期，并要求相关共享资源没有其他使用者。真实项目若由引导程序或其他 BSP 已管理复位，应让所有者统一处理，不能在局部初始化函数中无条件重置共享外设。

#### 时序参数为什么不能只看 1 kHz

定时器决定触发间隔，ADC 决定一次触发要占用多久。若下一次 TRGO 在 ADC 尚未完成前到达，其行为和错误证据必须按 RM0090 的 ADC 触发/overrun 规则分析；软件不能假设硬件自动排队无限多个触发。参考值 `1 ms >> 4.57 us` 留出很大余量，但目标工程还需加入模拟建立时间、IRQ 最坏延迟或 DMA 带宽预算。[S1][S2]

### 7.3 CubeMX、HAL、LL 与寄存器对照

#### CubeMX/CubeMX2 配置清单

1. **MCU Selector**：选择实际 STM32F407 完整料号，记录 STM32CubeMX/CubeMX2 和 STM32CubeF4 版本；本文不代替封装选择。
2. **System Core -> RCC / Clock Configuration**：参考方案使用 HSI，PLL M=16、N=336、P=2；AHB=/1、APB1=/4、APB2=/2；目标 VDD、Flash latency 和频率限制按 DS8626 重新核对。
3. **Timers -> TIM2**：Clock Source=`Internal Clock`；Prescaler=`83`；Counter Mode=`Up`；Counter Period=`999`；Auto-reload preload=`Enable`；Master/Slave -> Trigger Event Selection=`Update Event`，Master/Slave Mode=`Disable`。
4. **Analog -> ADC1**：选择板卡实际可用的 ADC channel/pin；Resolution=`12 bits`；Scan=`Disable`；Continuous Conversion=`Disable`；Number of Conversion=`1`；External Trigger Source=`Timer 2 Trigger Out event`；Edge=`Rising`；Data Alignment=`Right`；ADC clock prescaler=`PCLK2/4`；rank 1 sampling time参考 `84 cycles`，最终按源阻抗核对。
5. **NVIC**：NVIC（nested vectored interrupt controller，嵌套向量中断控制器）中最小硬件触发不启用 TIM2 global interrupt。为获得本课回调证据，启用共享 `ADC global interrupt`；优先级值按完整系统策略设置，示例值不能直接当产品策略。
6. **DMA**：本课最小链关闭 ADC DMA。若 GUI 自动添加 DMA，先删除，避免把“转换触发”和“结果搬运”混成一个故障面。DMA 在后续流水线课启用。
7. **GPIO**：只由实际完整料号、封装、原理图和信号条件选择 analog mode/no pull；本文没有合法依据指定 pin。
8. **生成后审计**：检查 `SystemClock_Config`、`MX_TIM2_Init`、`HAL_TIM_Base_MspInit`、`MX_ADC1_Init`、`HAL_ADC_MspInit`、`ADC_IRQHandler` 和启动顺序，不能以 GUI 无红叉代替源码证据。

#### HAL 初始化字段与句柄所有权

| 对象/字段 | 意义 | 所有权与生命周期 |
| --- | --- | --- |
| `TIM_HandleTypeDef htim2` | 绑定 `TIM2`，保存 PSC/ARR、模式、HAL 状态和锁 | BSP 静态持有；初始化、运行、停止期间一直有效 |
| `TIM_MasterConfigTypeDef` | 调用期提交 TRGO 来源和 master/slave mode | TIM2 初始化函数栈上持有；提交后无需保留 |
| `ADC_HandleTypeDef hadc1` | 绑定 `ADC1`，保存 ADC 初始化字段、状态和错误码 | BSP 静态持有；IRQ handler 必须引用同一实例 |
| `ADC_ChannelConfTypeDef` | 提交板级 channel、rank 和 sampling time | ADC 初始化函数栈上持有；通道值由板级组装注入 |
| `g_trigger_diag` | ISR 写最小事件计数、样本和错误码 | BSP 静态持有；应用只读取快照，不在 ISR 做重处理 |

`htim2.Init.Prescaler` 与 `Period` 分别写入 PSC/ARR；`CounterMode` 选择向上计数；`AutoReloadPreload` 决定 ARR 更新是否经预装载。`MasterOutputTrigger=TIM_TRGO_UPDATE` 才把更新事件导出，`MasterSlaveMode=DISABLE` 表示当前不构建 timer-to-timer 同步链。[S3][S4]

`hadc1.Init.ClockPrescaler` 选择 ADC 公共分频；`ContinuousConvMode=DISABLE` 确保每个获准外部事件启动一次序列，而不是一次触发后自由连续运行；`ExternalTrigConv=ADC_EXTERNALTRIGCONV_T2_TRGO` 与 `ExternalTrigConvEdge=...RISING` 共同配置来源和边沿；`NbrOfConversion=1` 表示单 rank。`HAL_ADC_ConfigChannel` 再提交实际 ADC channel、rank 和 sample time。[S3][S4]

#### HAL 到 LL/关键寄存器交叉表

下表只适用于 RM0090 覆盖的 STM32F407xx 和 STM32CubeF4 v1.28.3 API 面。[S1][S3][S4]

| 意图与前置条件 | HAL 字段/API | LL 同意图入口 | F407 关键寄存器/事件 | 成功证据与排错方向 |
| --- | --- | --- | --- | --- |
| 开 TIM2 时钟；APB1 已稳定 | `__HAL_RCC_TIM2_CLK_ENABLE()` | `LL_APB1_GRP1_EnableClock(...TIM2)` | `RCC_APB1ENR.TIM2EN` | 读回 1 只证明门控；`CNT` 不动再查 reset/CEN |
| 启动期复位 TIM2 | `...TIM2_FORCE_RESET/RELEASE_RESET` | `LL_APB1_GRP1_ForceReset/ReleaseReset` | `RCC_APB1RSTR.TIM2RST` | 必须看到 reset 释放；运行期不可无所有权复位 |
| 开 ADC1 时钟；APB2 已稳定 | `__HAL_RCC_ADC1_CLK_ENABLE()` | `LL_APB2_GRP1_EnableClock(...ADC1)` | `RCC_APB2ENR.ADC1EN` | 门控成功不证明 ADCCLK、ADON 或触发存在 |
| 启动期复位 ADC 公共域 | `...ADC_FORCE_RESET/RELEASE_RESET` | `LL_APB2_GRP1_ForceReset/ReleaseReset` | `RCC_APB2RSTR.ADCRST` | 影响 ADC 共享域；所有 ADC 使用者必须静止 |
| 形成 TIM2 节拍；counter disabled | `Prescaler=83`、`Period=999` 后 `HAL_TIM_Base_Init` | `LL_TIM_SetPrescaler`、`LL_TIM_SetAutoReload` | `TIM2_PSC=83`、`TIM2_ARR=999` | 读回 + 时钟推导得 1 kHz；不是实测波形 |
| 装载预分频/预装载值 | HAL 初始化内部更新动作；显式时可用 generate event 宏 | `LL_TIM_GenerateEvent_UPDATE` | `TIM2_EGR.UG`，并可能置 `SR.UIF` | ADC 已武装后写 UG 可能额外触发，排查“多一个样本” |
| 把 update 导出为 TRGO | `HAL_TIMEx_MasterConfigSynchronization`，`TIM_TRGO_UPDATE` | `LL_TIM_SetTriggerOutput(TIM2, LL_TIM_TRGO_UPDATE)` | `TIM2_CR2.MMS=010` | MMS 读回；UIF 不能单独证明 TRGO 选择 |
| 启动/停止源 | `HAL_TIM_Base_Start/Stop` | `LL_TIM_EnableCounter/DisableCounter` | `TIM2_CR1.CEN`、`CNT`、`SR.UIF` | `CNT/UIF` 证明源运行；无需 `DIER.UIE` 或 TIM2 IRQ |
| 选择 ADC 公共时钟 | `ClockPrescaler=ADC_CLOCK_SYNC_PCLK_DIV4` | `LL_ADC_SetCommonClock(...DIV4)` | `ADC_CCR.ADCPRE=01` | PCLK2 84 MHz 时推导 ADCCLK 21 MHz |
| 选择 TIM2_TRGO 和上升沿；ADC 尚未运行 | `ExternalTrigConv=T2_TRGO`、`ExternalTrigConvEdge=RISING` 后 `HAL_ADC_Init` | `LL_ADC_REG_SetTriggerSource(...TIM2_TRGO)`；`LL_ADC_REG_StartConversionExtTrig(...RISING)` | `ADC1_CR2.EXTSEL=0110`、`EXTEN=01` | 两字段都要读回；此路径不配置 timer ITR/SMCR |
| 配置一个规则 rank | `HAL_ADC_ConfigChannel` | `LL_ADC_REG_SetSequencerRanks`、sampling-time API | `SQRx`、`SMPRx` | channel/pin 必须来自真实板级；错误通道仍可能 EOC 但数据无意义 |
| 武装 ADC 和 EOC/OVR 观察 | `HAL_ADC_Start_IT` | `LL_ADC_Enable`、`LL_ADC_EnableIT_EOCS/OVR` | `ADC_CR2.ADON`、`ADC_CR1.EOCIE/OVRIE`；外部模式不置 `SWSTART` | HAL 返回 + ADON/IT 读回只证明 armed，尚未证明 TRGO 到达 |
| 硬件接受触发并转换 | 无周期软件调用 | 查询 `STRT/EOC/OVR`；读规则数据 | `ADC_SR.STRT/EOC/OVR`、`ADC_DR` | EOC/DR 是接收动作证据；OVR 表示结果未及时处理 |
| 分发 ADC IRQ | `ADC_IRQHandler -> HAL_ADC_IRQHandler` | LL-only 驱动自行查/清 flag | NVIC pending/active、ADC flags | 进 handler 无回调时查句柄实例、flag/IT enable 和向量连接 |
| 完成/错误回调 | `HAL_ADC_ConvCpltCallback`、`HAL_ADC_ErrorCallback` | LL-only 无 HAL 回调 | HAL state/error + ADC flags | 回调证明软件观察链；不能证明模拟电压准确 |

ADC 的 `EXTSEL=0110` 是 F407 规则组外部触发 mux 对 `TIM2_TRGO` 的选择，不是 TIM2 ITR 编号。HAL 的 `HAL_ADC_Start_IT` 在外部触发边沿已配置时使能 ADC 和中断，但不会用 `SWSTART` 替代外部事件；该行为已按 STM32CubeF4 v1.28.3 的 `stm32f4xx_hal_adc.c` 核对。[S4]

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

以下是一个单文件 C11 模型。它不包含 STM32 头文件，不使用动态内存；公开状态和返回码使用固定宽度整数。timer、route、ADC 三个对象都由测试 fixture 持有，测试直接注入配置和故障。

```c
/* host_timer_trigger_test.c: Host Fake，只证明模型逻辑。 */
#include <assert.h>
#include <stdint.h>

typedef uint32_t fake_bool_t;
typedef uint32_t fake_status_t;

#define FAKE_FALSE UINT32_C(0)
#define FAKE_TRUE  UINT32_C(1)

#define FAKE_OK                    UINT32_C(0)
#define FAKE_ERR_TIMER_STOPPED     UINT32_C(1)
#define FAKE_ERR_TRGO_DISABLED     UINT32_C(2)
#define FAKE_ERR_TRGO_SELECTION    UINT32_C(3)
#define FAKE_ERR_ROUTE_DISCONNECTED UINT32_C(4)
#define FAKE_ERR_ROUTE_SOURCE      UINT32_C(5)
#define FAKE_ERR_ROUTE_SINK        UINT32_C(6)
#define FAKE_ERR_ADC_DISABLED      UINT32_C(7)
#define FAKE_ERR_ADC_SOURCE        UINT32_C(8)
#define FAKE_ERR_ADC_EDGE          UINT32_C(9)

#define FAKE_TRGO_NONE   UINT32_C(0)
#define FAKE_TRGO_UPDATE UINT32_C(1)

#define FAKE_EDGE_RISING  UINT32_C(1)
#define FAKE_EDGE_FALLING UINT32_C(2)

#define FAKE_SOURCE_TIMER2 UINT32_C(2)
#define FAKE_SINK_ADC1     UINT32_C(1)

typedef struct {
    fake_bool_t enabled;
    fake_bool_t trgo_enabled;
    uint32_t trgo_selection;
    uint32_t source_id;
    uint32_t update_events;
} fake_timer_t;

typedef struct {
    fake_bool_t connected;
    uint32_t source_id;
    uint32_t sink_id;
    uint32_t delivered_events;
} fake_route_t;

typedef struct {
    fake_bool_t enabled;
    uint32_t sink_id;
    uint32_t selected_source_id;
    uint32_t allowed_edges;
    uint32_t conversion_starts;
} fake_adc_t;

typedef struct {
    fake_timer_t timer;
    fake_route_t route;
    fake_adc_t adc;
    fake_status_t last_status;
} fake_fixture_t;

static fake_status_t fake_adc_trigger(fake_adc_t *adc,
                                      uint32_t source_id,
                                      uint32_t edge)
{
    if (adc->enabled == FAKE_FALSE) {
        return FAKE_ERR_ADC_DISABLED;
    }
    if (adc->selected_source_id != source_id) {
        return FAKE_ERR_ADC_SOURCE;
    }
    if ((adc->allowed_edges & edge) == UINT32_C(0)) {
        return FAKE_ERR_ADC_EDGE;
    }

    adc->conversion_starts++;
    return FAKE_OK;
}

static fake_status_t fake_route_deliver(fake_route_t *route,
                                        fake_adc_t *adc,
                                        uint32_t source_id,
                                        uint32_t edge)
{
    fake_status_t status;

    if (route->connected == FAKE_FALSE) {
        return FAKE_ERR_ROUTE_DISCONNECTED;
    }
    if (route->source_id != source_id) {
        return FAKE_ERR_ROUTE_SOURCE;
    }
    if (route->sink_id != adc->sink_id) {
        return FAKE_ERR_ROUTE_SINK;
    }

    status = fake_adc_trigger(adc, source_id, edge);
    if (status == FAKE_OK) {
        route->delivered_events++;
    }
    return status;
}

static fake_status_t fake_timer_tick(fake_fixture_t *fixture)
{
    if (fixture->timer.enabled == FAKE_FALSE) {
        fixture->last_status = FAKE_ERR_TIMER_STOPPED;
        return fixture->last_status;
    }

    fixture->timer.update_events++;

    if (fixture->timer.trgo_enabled == FAKE_FALSE) {
        fixture->last_status = FAKE_ERR_TRGO_DISABLED;
        return fixture->last_status;
    }
    if (fixture->timer.trgo_selection != FAKE_TRGO_UPDATE) {
        fixture->last_status = FAKE_ERR_TRGO_SELECTION;
        return fixture->last_status;
    }

    fixture->last_status = fake_route_deliver(&fixture->route,
                                              &fixture->adc,
                                              fixture->timer.source_id,
                                              FAKE_EDGE_RISING);
    return fixture->last_status;
}

static fake_fixture_t make_valid_fixture(void)
{
    fake_fixture_t fixture = {0};

    fixture.timer.enabled = FAKE_TRUE;
    fixture.timer.trgo_enabled = FAKE_TRUE;
    fixture.timer.trgo_selection = FAKE_TRGO_UPDATE;
    fixture.timer.source_id = FAKE_SOURCE_TIMER2;

    fixture.route.connected = FAKE_TRUE;
    fixture.route.source_id = FAKE_SOURCE_TIMER2;
    fixture.route.sink_id = FAKE_SINK_ADC1;

    fixture.adc.enabled = FAKE_TRUE;
    fixture.adc.sink_id = FAKE_SINK_ADC1;
    fixture.adc.selected_source_id = FAKE_SOURCE_TIMER2;
    fixture.adc.allowed_edges = FAKE_EDGE_RISING;
    return fixture;
}

static void test_valid_chain_delivers_once_per_tick(void)
{
    fake_fixture_t fixture = make_valid_fixture();

    assert(fake_timer_tick(&fixture) == FAKE_OK);
    assert(fake_timer_tick(&fixture) == FAKE_OK);
    assert(fixture.timer.update_events == UINT32_C(2));
    assert(fixture.route.delivered_events == UINT32_C(2));
    assert(fixture.adc.conversion_starts == UINT32_C(2));
}

static void test_source_stopped(void)
{
    fake_fixture_t fixture = make_valid_fixture();

    fixture.timer.enabled = FAKE_FALSE;
    assert(fake_timer_tick(&fixture) == FAKE_ERR_TIMER_STOPPED);
    assert(fixture.timer.update_events == UINT32_C(0));
    assert(fixture.adc.conversion_starts == UINT32_C(0));
}

static void test_trgo_disabled_or_wrong_selection(void)
{
    fake_fixture_t fixture = make_valid_fixture();

    fixture.timer.trgo_enabled = FAKE_FALSE;
    assert(fake_timer_tick(&fixture) == FAKE_ERR_TRGO_DISABLED);
    assert(fixture.adc.conversion_starts == UINT32_C(0));

    fixture = make_valid_fixture();
    fixture.timer.trgo_selection = FAKE_TRGO_NONE;
    assert(fake_timer_tick(&fixture) == FAKE_ERR_TRGO_SELECTION);
    assert(fixture.adc.conversion_starts == UINT32_C(0));
}

static void test_route_disconnected(void)
{
    fake_fixture_t fixture = make_valid_fixture();

    fixture.route.connected = FAKE_FALSE;
    assert(fake_timer_tick(&fixture) == FAKE_ERR_ROUTE_DISCONNECTED);
    assert(fixture.adc.conversion_starts == UINT32_C(0));
}

static void test_receiver_source_and_edge_rejection(void)
{
    fake_fixture_t fixture = make_valid_fixture();

    fixture.adc.selected_source_id = UINT32_C(99);
    assert(fake_timer_tick(&fixture) == FAKE_ERR_ADC_SOURCE);
    assert(fixture.adc.conversion_starts == UINT32_C(0));

    fixture = make_valid_fixture();
    fixture.adc.allowed_edges = FAKE_EDGE_FALLING;
    assert(fake_timer_tick(&fixture) == FAKE_ERR_ADC_EDGE);
    assert(fixture.adc.conversion_starts == UINT32_C(0));
}

static void test_receiver_disabled_after_one_event(void)
{
    fake_fixture_t fixture = make_valid_fixture();

    assert(fake_timer_tick(&fixture) == FAKE_OK);
    fixture.adc.enabled = FAKE_FALSE;
    assert(fake_timer_tick(&fixture) == FAKE_ERR_ADC_DISABLED);
    assert(fixture.timer.update_events == UINT32_C(2));
    assert(fixture.adc.conversion_starts == UINT32_C(1));
}

int main(void)
{
    test_valid_chain_delivers_once_per_tick();
    test_source_stopped();
    test_trgo_disabled_or_wrong_selection();
    test_route_disconnected();
    test_receiver_source_and_edge_rejection();
    test_receiver_disabled_after_one_event();
    return 0;
}
```

可用任一 C11 主机编译器执行，例如：

```text
cc -std=c11 -Wall -Wextra -Werror -pedantic host_timer_trigger_test.c -o host_timer_trigger_test
./host_timer_trigger_test
```

退出码 `0` 是预期结果；断言失败应返回非零。本次课程生成没有把该代码保存为独立源文件，也没有留下编译日志，因此这里给的是实验命令，不声称已经编译通过。

这个 Fake 有意把事件链逐段拆开：timer 只知道自己的 source id 和 TRGO 选择；route 持有固定连接；ADC 持有接收选择和边沿许可。测试既是对象所有者，也是故障注入者。一次 `fake_timer_tick()` 最多调用一次 `fake_adc_trigger()`，因此正确配置下每个源事件只产生一次接收动作。它不能证明 F407 的路由编码、HAL 状态机、真实频率或模拟转换质量。

### 8.2 STM32 参考实现轨道

#### BSP 参考代码

以下代码属于目标 BSP 适配层，依赖方向为应用（application，App）-> BSP -> STM32CubeF4 HAL -> CMSIS/硬件。公开头文件负责声明，`.c` 文件负责实现并静态实例化句柄，板级模块注入 ADC channel/pin，App 只使用公开接口。它固定内部路径，但把 ADC channel/pin 的组装留给板级实现。代码未在本次运行中进入目标工程编译。

```c
/* bsp_timer_adc_trigger.h
 * 公开声明：不暴露 HAL 句柄，App 只依赖固定宽度类型和 BSP API。
 */
#ifndef BSP_TIMER_ADC_TRIGGER_H
#define BSP_TIMER_ADC_TRIGGER_H

#include <stdint.h>

typedef uint32_t bsp_trigger_status_t;

#define BSP_TRIGGER_OK              UINT32_C(0)
#define BSP_TRIGGER_ERR_CLOCK       UINT32_C(1)
#define BSP_TRIGGER_ERR_BOARD_GPIO  UINT32_C(2)
#define BSP_TRIGGER_ERR_TIM_INIT    UINT32_C(3)
#define BSP_TRIGGER_ERR_TIM_MASTER  UINT32_C(4)
#define BSP_TRIGGER_ERR_ADC_INIT    UINT32_C(5)
#define BSP_TRIGGER_ERR_ADC_CHANNEL UINT32_C(6)
#define BSP_TRIGGER_ERR_ADC_START   UINT32_C(7)
#define BSP_TRIGGER_ERR_TIM_START   UINT32_C(8)
#define BSP_TRIGGER_ERR_ADC_RUNTIME UINT32_C(9)

typedef struct {
    volatile uint32_t conversion_events;
    volatile uint32_t error_events;
    volatile uint32_t latest_sample;
    volatile uint32_t hal_adc_error;
    volatile uint32_t adc_sr_at_error;
    volatile bsp_trigger_status_t first_error;
} bsp_trigger_diag_t;

bsp_trigger_status_t BSP_TriggerChain_InitAndStart(uint32_t board_adc_channel);
void BSP_TriggerChain_Stop(void);
const bsp_trigger_diag_t *BSP_TriggerChain_GetDiag(void);

#endif
```

```c
/* bsp_timer_adc_trigger.c
 * 参考实现，待目标工程编译和上板验证。
 */
#include "bsp_timer_adc_trigger.h"
#include "stm32f4xx_hal.h"

static TIM_HandleTypeDef htim2;
static ADC_HandleTypeDef hadc1;

static bsp_trigger_diag_t g_trigger_diag;

/* 板级层必须实现：配置实际 ADC channel 对应引脚为 analog/no-pull。 */
extern bsp_trigger_status_t board_adc_gpio_init(uint32_t board_adc_channel);

static void record_first_error(bsp_trigger_status_t error)
{
    if (g_trigger_diag.first_error == BSP_TRIGGER_OK) {
        g_trigger_diag.first_error = error;
    }
}

static bsp_trigger_status_t SystemClock_Config_Reference(void)
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
        return BSP_TRIGGER_ERR_CLOCK;
    }

    clk.ClockType = RCC_CLOCKTYPE_SYSCLK |
                    RCC_CLOCKTYPE_HCLK |
                    RCC_CLOCKTYPE_PCLK1 |
                    RCC_CLOCKTYPE_PCLK2;
    clk.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    clk.AHBCLKDivider = RCC_SYSCLK_DIV1;
    clk.APB1CLKDivider = RCC_HCLK_DIV4;
    clk.APB2CLKDivider = RCC_HCLK_DIV2;
    if (HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_5) != HAL_OK) {
        return BSP_TRIGGER_ERR_CLOCK;
    }
    return BSP_TRIGGER_OK;
}

void HAL_TIM_Base_MspInit(TIM_HandleTypeDef *htim)
{
    if ((htim == NULL) || (htim->Instance != TIM2)) {
        return;
    }

    __HAL_RCC_TIM2_CLK_ENABLE();
    /* 仅限启动期且确认 TIM2 没有其他所有者。 */
    __HAL_RCC_TIM2_FORCE_RESET();
    __HAL_RCC_TIM2_RELEASE_RESET();
}

void HAL_ADC_MspInit(ADC_HandleTypeDef *hadc)
{
    if ((hadc == NULL) || (hadc->Instance != ADC1)) {
        return;
    }

    __HAL_RCC_ADC1_CLK_ENABLE();
    /* ADCRST 是共享 ADC 复位；仅限所有 ADC 使用者静止的启动期。 */
    __HAL_RCC_ADC_FORCE_RESET();
    __HAL_RCC_ADC_RELEASE_RESET();

    /* 示例优先级，产品集成时按完整中断策略重选。 */
    HAL_NVIC_SetPriority(ADC_IRQn, 5U, 0U);
    HAL_NVIC_EnableIRQ(ADC_IRQn);
}

static bsp_trigger_status_t MX_TIM2_Init_Reference(void)
{
    TIM_MasterConfigTypeDef master = {0};

    htim2.Instance = TIM2;
    htim2.Init.Prescaler = 83U;
    htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim2.Init.Period = 999U;
    htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
    if (HAL_TIM_Base_Init(&htim2) != HAL_OK) {
        return BSP_TRIGGER_ERR_TIM_INIT;
    }

    master.MasterOutputTrigger = TIM_TRGO_UPDATE;
    master.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
    if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &master) != HAL_OK) {
        return BSP_TRIGGER_ERR_TIM_MASTER;
    }
    return BSP_TRIGGER_OK;
}

static bsp_trigger_status_t MX_ADC1_Init_Reference(uint32_t board_adc_channel)
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
    hadc1.Init.DMAContinuousRequests = DISABLE;
    hadc1.Init.EOCSelection = ADC_EOC_SINGLE_CONV;
    if (HAL_ADC_Init(&hadc1) != HAL_OK) {
        return BSP_TRIGGER_ERR_ADC_INIT;
    }

    channel.Channel = board_adc_channel;
    channel.Rank = 1U;
    channel.SamplingTime = ADC_SAMPLETIME_84CYCLES;
    channel.Offset = 0U;
    if (HAL_ADC_ConfigChannel(&hadc1, &channel) != HAL_OK) {
        return BSP_TRIGGER_ERR_ADC_CHANNEL;
    }
    return BSP_TRIGGER_OK;
}

static bsp_trigger_status_t BSP_TriggerChain_Start(void)
{
    /* 先武装接收端；外部触发模式下不会用 SWSTART 伪造事件。 */
    if (HAL_ADC_Start_IT(&hadc1) != HAL_OK) {
        g_trigger_diag.hal_adc_error = HAL_ADC_GetError(&hadc1);
        record_first_error(BSP_TRIGGER_ERR_ADC_START);
        return BSP_TRIGGER_ERR_ADC_START;
    }

    /* 后启动源。此处不启用 TIM2 update interrupt。 */
    if (HAL_TIM_Base_Start(&htim2) != HAL_OK) {
        (void)HAL_ADC_Stop_IT(&hadc1);
        record_first_error(BSP_TRIGGER_ERR_TIM_START);
        return BSP_TRIGGER_ERR_TIM_START;
    }
    return BSP_TRIGGER_OK;
}

void BSP_TriggerChain_Stop(void)
{
    /* 先停源，防止停止接收端时又到达新事件。 */
    (void)HAL_TIM_Base_Stop(&htim2);
    (void)HAL_ADC_Stop_IT(&hadc1);
}

bsp_trigger_status_t BSP_TriggerChain_InitAndStart(uint32_t board_adc_channel)
{
    bsp_trigger_status_t status;

    g_trigger_diag = (bsp_trigger_diag_t){0};

    status = SystemClock_Config_Reference();
    if (status != BSP_TRIGGER_OK) {
        record_first_error(status);
        return status;
    }

    status = board_adc_gpio_init(board_adc_channel);
    if (status != BSP_TRIGGER_OK) {
        record_first_error(BSP_TRIGGER_ERR_BOARD_GPIO);
        return BSP_TRIGGER_ERR_BOARD_GPIO;
    }

    status = MX_TIM2_Init_Reference();
    if (status != BSP_TRIGGER_OK) {
        record_first_error(status);
        return status;
    }

    status = MX_ADC1_Init_Reference(board_adc_channel);
    if (status != BSP_TRIGGER_OK) {
        record_first_error(status);
        return status;
    }

    return BSP_TriggerChain_Start();
}

void ADC_IRQHandler(void)
{
    HAL_ADC_IRQHandler(&hadc1);
}

void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *hadc)
{
    if ((hadc != NULL) && (hadc->Instance == ADC1)) {
        g_trigger_diag.latest_sample = HAL_ADC_GetValue(hadc);
        g_trigger_diag.conversion_events++;
    }
}

void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *hadc)
{
    if ((hadc != NULL) && (hadc->Instance == ADC1)) {
        g_trigger_diag.hal_adc_error = HAL_ADC_GetError(hadc);
        g_trigger_diag.adc_sr_at_error = hadc->Instance->SR;
        g_trigger_diag.error_events++;
        record_first_error(BSP_TRIGGER_ERR_ADC_RUNTIME);
    }
}

const bsp_trigger_diag_t *BSP_TriggerChain_GetDiag(void)
{
    return &g_trigger_diag;
}
```

`board_adc_gpio_init()` 和传入的 `board_adc_channel` 是明确的板级注入点：它们必须由完整料号、封装、原理图和模拟电气条件确定，不能用本文猜一个 pin。若实际工程的 `ADC_ChannelConfTypeDef` 在所选包/子系列中没有 `Offset` 字段，应以安装包头文件为准删除或调整；本课目标包 STM32CubeF4 v1.28.3 已核对该字段存在。[S4]

App 的最小使用顺序是：

```c
/* main.c：App 使用层，参考实现，待目标工程编译。 */
#include "board.h"                  /* BOARD_ADC_CHANNEL 与板级 GPIO 实现 */
#include "bsp_timer_adc_trigger.h" /* 只依赖 BSP 公开声明 */

int main(void)
{
    HAL_Init();

    if (BSP_TriggerChain_InitAndStart(BOARD_ADC_CHANNEL) != BSP_TRIGGER_OK) {
        Error_Handler();
    }

    for (;;) {
        const bsp_trigger_diag_t *diag = BSP_TriggerChain_GetDiag();
        app_consume_trigger_snapshot(diag->conversion_events,
                                     diag->latest_sample,
                                     diag->error_events);
    }
}
```

`BOARD_ADC_CHANNEL`、`Error_Handler()` 和 `app_consume_trigger_snapshot()` 属于实际板级/App 工程。应用读取多个 ISR 更新字段时，产品代码还应使用短临界区或一致性快照协议；`volatile` 只约束访问，不提供多字段原子快照。

#### IRQ 与 DMA 回调边界

本课最小路径的 IRQ 关系如下：

| 路径 | 是否需要 | 原因 |
| --- | --- | --- |
| TIM2 update IRQ / `HAL_TIM_PeriodElapsedCallback` | 不需要 | 更新事件直接成为 TRGO；开启它只增加软件观察点，不参与 ADC 启动 |
| ADC_IRQn / `HAL_ADC_ConvCpltCallback` | 为本课观察而启用 | 证明 ADC 完成、IRQ 和 HAL 分发；关闭后可改用轮询或 DMA |
| ADC overrun / `HAL_ADC_ErrorCallback` | 与 ADC IRQ 一起处理 | 保存运行期过载错误；不能只记“无数据” |
| DMA stream IRQ / half/full callbacks | 本课不需要 | 最小链没有启用 DMA，留到 `adc-timer-dma-pipeline` |

若为了对比启用 `HAL_TIM_Base_Start_IT()`，则还必须提供正确 TIM2 IRQ handler 并调用 `HAL_TIM_IRQHandler(&htim2)`，随后 `HAL_TIM_PeriodElapsedCallback()` 才会发生；该回调计数只能证明软件观察到 update，ADC 硬件触发本身不依赖它。

后续换成 `HAL_ADC_Start_DMA()` 时，必须新增 DMA 句柄、`__HAL_LINKDMA`、DMA stream/request 映射、IRQ handler、`HAL_ADC_ConvHalfCpltCallback`、`HAL_ADC_ConvCpltCallback`、`HAL_ADC_ErrorCallback` 和缓冲区半区所有权。那条链是：

```text
TIM2_TRGO -> ADC conversion -> ADC DMA request
  -> DMA writes buffer -> HT/TC/error flag -> DMA IRQ
  -> HAL_DMA_IRQHandler -> ADC DMA callback -> application consumer
```

它是本课事件链的下游扩展，不是证明 TRGO 路由所必需的条件。

#### 构建、烧录与观察步骤

1. 在实际 CubeMX 工程选择完整 F407 料号和合法 ADC channel/pin，生成代码后把参考字段逐项合入 user-code 区或独立 BSP 文件。
2. 固定并记录 CubeMX、STM32CubeF4、交叉编译器版本；全量构建，保存命令、退出码和 warning。当前未执行。
3. 在烧录前静态检查 `MMS=update`、`EXTSEL=T2_TRGO`、`EXTEN=rising`、`ContinuousConvMode=DISABLE` 和“ADC 先启动，TIM2 后启动”。
4. 连接调试器并烧录；当前未执行。不要在未知板卡上先假定 ADC 引脚或输入电压。
5. 运行后观察 conversion counter 是否约每秒增加 1000；再用定时窗口而非单步估算。该数值是预期，不是本课已有结果。
6. 若有逻辑分析仪，TRGO 是片内信号，不能假定能直接从引脚看到。可在诊断版代码中于 ADC callback 短暂翻转一个已核对的 GPIO，但该波形包含转换和 IRQ 延迟，只能作为软件观察链证据。
7. 保存目标板、完整料号、固件包、构建日志、烧录日志、寄存器快照和测量条件后，才可评估是否将 `hardware_verified` 改为 true。

## 9. 最小代码示例

最小 HAL 差异可以压缩为四个关键配置和两个启动调用：

```c
htim2.Init.Prescaler = 83U;
htim2.Init.Period = 999U;
master.MasterOutputTrigger = TIM_TRGO_UPDATE;

hadc1.Init.ContinuousConvMode = DISABLE;
hadc1.Init.ExternalTrigConv = ADC_EXTERNALTRIGCONV_T2_TRGO;
hadc1.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_RISING;

/* 初始化和 channel 配置完成后： */
(void)HAL_ADC_Start_IT(&hadc1);  /* arm receiver */
(void)HAL_TIM_Base_Start(&htim2); /* start source */
```

但这段不能脱离第 8.2 节独立复制：它省略时钟树、门控/复位、返回值、板级 ADC channel、NVIC、回滚和错误记录。最小理解单元是六跳事件链，最小工程单元仍必须包含所有前置条件和错误路径。

## 10. 常见错误

### 10.1 在 TIM2 回调里软件启动 ADC

这样得到的是 `update -> IRQ -> CPU -> SWSTART`，不是本课的 `update -> TRGO -> ADC`。它可能工作，但无法证明内部触发路由，采样时刻还包含 ISR 延迟。先检查代码中是否出现周期性 `HAL_ADC_Start*()`，再检查 TIM2 update interrupt 是否被误当成必要条件。

### 10.2 只设置 `TIM_TRGO_UPDATE`，没设置 ADC 来源或边沿

TRGO 是源端声明；ADC 必须同时选择 `TIM2_TRGO` 并启用边沿。`EXTSEL` 正确而 `EXTEN=00` 时仍是软件启动条件，内部信号不会开始规则组转换。[S1][S4]

### 10.3 把 TIM2_TRGO 写成某个 ITR 编号

ADC 的接收 mux 在 `ADC_CR2.EXTSEL`。ITR 编号用于 timer-to-timer 接收路径，必须查目标定时器互连表。当前路径不使用 `TIMx_SMCR.TS/SMS`。

### 10.4 开启 `ContinuousConvMode`

若连续模式开启，一次触发可能让 ADC 持续转换，`conversion_events` 不再与 TRGO 一一对应。验证“每个允许源事件一次动作”时应先关闭连续模式，单 rank、单转换。

### 10.5 启动顺序反了

先启动 TIM2 再武装 ADC 会让早期 TRGO 被接收端错过；在复杂配置中，还可能把初始化产生的 update 混入样本。顺序应是：完成 TIM2 初始化/UG -> 完成 ADC 初始化 -> `HAL_ADC_Start_IT` -> `HAL_TIM_Base_Start`。

### 10.6 把 PCLK1 当 TIM2 内核时钟

本参考配置 `PCLK1=42 MHz`，但 APB1 prescaler 不为 1 时，TIM2 内核时钟按 F407 规则为 `84 MHz`。若错用 42 MHz，触发频率会算低一半。[S1]

### 10.7 把 ADCCLK 当采样率

21 MHz 是 ADC 工作时钟。一次 12-bit 转换还包含采样周期和 12 个处理周期；规则序列长度、触发间隔、模拟建立条件与结果消费都会影响可用采样率。[S1][S2]

### 10.8 在 ADC 已武装后随意生成 UG

当 `MMS=update` 时，软件 `EGR.UG` 也是 update 来源，可能多触发一次 ADC。调试器手工写寄存器也会改变被观察系统。若发现“启动时多一个样本”，先审计 UG 发生时刻。

### 10.9 用 HAL 返回值代替硬件证据

`HAL_TIM_Base_Start()==HAL_OK` 只说明 HAL 接受启动并设置了运行状态；它不证明 ADC mux 或模拟输入正确。至少分层记录 CEN/CNT/UIF、MMS、EXTSEL/EXTEN、ADON、EOC/OVR 和回调计数。

### 10.10 无条件复位共享资源

`ADCRST` 不是 ADC1 私有复位。系统若已有 ADC2/ADC3 使用者，无条件复位会破坏它们。复位动作必须由启动期唯一所有者执行，恢复时优先停止并重初始化受影响对象，而不是在局部错误回调里直接复位共享域。

## 11. 调试观察点

按“从源到接收端”顺序采证，不要随机改参数：

| 顺序 | 观察点 | 预期静态/动态证据 | 不能据此声称 |
| --- | --- | --- | --- |
| 1 | RCC/clock | `TIM2EN=1`、`ADC1EN=1`；推导 TIM2=84 MHz、ADCCLK=21 MHz | 真实板上频率已测得 |
| 2 | TIM2 配置 | PSC=83、ARR=999、CR2.MMS=update | 计数器已运行 |
| 3 | TIM2 运行 | CR1.CEN=1、CNT 变化、UIF 周期置位 | TRGO 已被 ADC 接受 |
| 4 | ADC 触发配置 | EXTSEL=`TIM2_TRGO`、EXTEN=rising、CONT=0 | ADC 已完成转换 |
| 5 | ADC 运行 | ADON=1；TRGO 后 STRT/EOC；无 OVR | 模拟值一定准确 |
| 6 | IRQ 链 | ADC_IRQn enable/pending/active；进入 `ADC_IRQHandler` | 应用已消费样本 |
| 7 | HAL/App | conversion counter 增加；error code/OVR 为 0 | 频率和抖动已由仪器确认 |

推荐设置以下断点或 watch：

- `BSP_TriggerChain_Start`：确认 ADC start 在 TIM start 之前；
- `ADC_IRQHandler`：确认向量入口使用 `&hadc1`；
- `HAL_ADC_ConvCpltCallback`：观察 `ADC1->SR`、`ADC1->DR` 和 event counter；
- `HAL_ADC_ErrorCallback`：第一时间保存 HAL error 与 `ADC_SR`，不要先清现场；
- `TIM2->CNT`、`TIM2->CR2`、`ADC1->CR2`：只读观察配置，避免调试器写回。

暂停内核可能改变实时关系。外设是否随 halt 停止还受 debug freeze 配置影响；若 TIM2 继续而 CPU/IRQ 停止，ADC 可能累计 overrun。单步后出现的 OVR 不应直接归因于正常运行。目标实验应分别记录“自由运行”与“断点暂停”的条件。

故障定位树：

```text
CNT 不变
  -> 查 HSI/PLL/APB1、TIM2EN、TIM2RST 是否释放、CEN

CNT/UIF 正常，ADC 无 STRT/EOC
  -> 查 MMS=update
  -> 查 RM0090 路径确为 TIM2_TRGO
  -> 查 EXTSEL/EXTEN、ADON、初始化后是否又被覆盖

ADC EOC 出现，无 ADC_IRQHandler
  -> 查 EOCIE/OVRIE、NVIC enable/pending、向量表、优先级屏蔽

进入 ADC_IRQHandler，无应用回调
  -> 查是否调用 HAL_ADC_IRQHandler(&hadc1)
  -> 查句柄 Instance、HAL state、flag 与 interrupt enable

回调计数正常，样本不合理
  -> 触发链大概率已通；转查 channel/pin、analog mode、VDDA/VREF、输入范围、源阻抗和采样时间

出现 OVR
  -> 查触发是否快于转换/消费
  -> 查断点是否暂停 CPU 而 timer 继续
  -> 保存首个 SR/HAL error，再决定停止或恢复
```

## 12. 实战实验

### 实验 A：Host Fake 故障矩阵

目标：只验证事件链的状态、所有权和拒绝边界。

步骤：

1. 将第 8.1 节保存为独立主机测试源并用 C11 严格警告编译；记录编译器版本、命令、输出和退出码。
2. 运行原始测试，记录进程退出码。
3. 在有效链测试中增加 1000 次 tick，断言 update、delivered、conversion 都等于 1000。
4. 分别注入 timer stopped、TRGO disabled、wrong selection、route disconnected、wrong ADC source、wrong edge、ADC disabled。
5. 对每个故障同时断言返回码和 `conversion_starts`，防止“报错但仍误启动”。
6. 增加“先成功一次、再停止源”的用例，断言停止后 timer event 和 ADC action 都不再增长。

合格证据：编译日志、测试退出码、每个错误码与计数断言。它不构成 STM32 硬件证据。

### 实验 B：CubeMX 静态审计

目标：在没有板卡时验证配置意图没有在生成代码中断裂。

步骤：

1. 选一个实际完整料号；若尚未决定，不生成并把该项标记为阻塞，而不是随意选封装。
2. 按 7.3 清单配置 TIM2 和 ADC1；ADC pin 必须来自真实板卡原理图。
3. 在生成代码中搜索 `TIM_TRGO_UPDATE`、`ADC_EXTERNALTRIGCONV_T2_TRGO` 和 `ADC_EXTERNALTRIGCONVEDGE_RISING`。
4. 确认没有 `HAL_TIM_Base_Start_IT(&htim2)` 被当成触发前置；确认 ADC start 位于 TIM2 start 之前。
5. 对照交叉表逐项记录字段、预计寄存器位和生成位置。

合格证据：工程版本、完整料号、配置截图或 `.ioc` diff、生成代码 diff、静态审计表。静态审计不等于编译或上板。

### 实验 C：目标构建与寄存器读回计划

目标：有目标环境后把“参考实现”推进到“可构建配置”。

步骤：

1. 提供开发板、完整 MCU 标识、板级时钟、ADC 输入、电压参考、调试器、Cube 与工具链版本。
2. 实现 board GPIO 注入点，把参考 BSP 合入目标工程并进行 clean build。
3. 保存 build 命令、全部输出、退出码和产物哈希；警告不能只截图最后一行。
4. 烧录后先停在 TIM2 启动前，读回 PSC/ARR/MMS、EXTSEL/EXTEN、ADON。
5. 自由运行固定时间，读取 conversion/error counter；不要用长期单步测频率。
6. 故意把 ADC source 改为另一项，确认 TIM2 仍运行但 ADC counter 停止，再恢复配置。
7. 故意停止 TIM2，确认 ADC 不再新增转换；不要通过拔除模拟输入来验证触发链。

当前状态：未构建、未烧录、未测量、未执行这些步骤。

### 实验 D：频率和转换余量

目标：把时钟推导、事件频率和接收能力放在同一张预算表。

步骤：

1. 从实际 clock tree 记录 SYSCLK/HCLK/PCLK1/TIM2 kernel/PCLK2/ADCCLK。
2. 用实际 PSC/ARR 计算 trigger frequency。
3. 用 ADC 分辨率和 sample time 计算单 rank conversion time；多 rank 时累加序列预算。
4. 写出 `trigger period / conversion time` 余量，不只写“足够快”。
5. 逐步提高触发率，观察 EOC 计数和 OVR；设置安全输入并遵守数据手册电气边界。
6. 用定时窗口或外部仪器交叉验证，记录误差来源。若用 callback GPIO，注明它包含 ADC/IRQ/软件延迟。

## 13. 自检题

1. 为什么 `TIM2_SR.UIF=1` 不能证明 ADC1 已经转换？
2. 本课的 `TIM2_TRGO` 与 ITR 分别站在什么角色上？为什么 ADC 路径不填写 ITR 编号？
3. `TIM2EN`、`TIM2RST`、`CR1.CEN`、`CR2.MMS` 各解决什么问题？
4. `ADC_CR2.EXTSEL` 和 `EXTEN` 缺一项分别会怎样？
5. 为什么 `HAL_ADC_Start_IT()` 要先于 `HAL_TIM_Base_Start()`？
6. 为什么本课关闭 `ContinuousConvMode`？
7. 在参考时钟下，PCLK1 为 42 MHz，为什么 TIM2 内核时钟是 84 MHz？
8. 为什么 21 MHz ADCCLK 不等于 21 Msps？
9. 本课为什么不需要 TIM2 update IRQ？ADC IRQ 又提供了哪一级证据？
10. 若 `CNT/UIF` 正常、ADC `EOC` 从不出现，你会按什么顺序查三项配置？
11. 调试器断点为什么可能人为制造 ADC overrun？
12. Host Fake 通过后，仍有哪些 F407 事实完全没有被证明？

建议先作答，再核对要点：完整答案应明确区分源、导出、路由、接收选择、动作和软件观察，不能只说“检查配置”。

## 14. 面试题

### 14.1 如何设计固定频率 ADC 采样，而不在 timer ISR 中启动 ADC？

回答应包含：由 timer 的更新/比较事件导出 TRGO；在目标手册中核对到 ADC 的合法连接；ADC 选择来源和边沿；先武装 ADC 再启动 timer；按 clock -> PSC/ARR -> trigger period 与 ADC conversion time 做预算；用 EOC/OVR、IRQ 或 DMA 建立结果证据。

### 14.2 定时器更新中断和更新 TRGO 有什么关系？

二者可来自同一 update event，但走不同分支。`DIER.UIE -> NVIC -> CPU ISR` 是软件通知路径；`CR2.MMS=update -> TRGO -> receiver mux` 是片内硬件触发路径。关闭 update IRQ 不等于关闭 update TRGO。

### 14.3 为什么硬件触发仍然需要软件错误处理？

硬件只推进已配置的事件链。错误配置、转换过载、IRQ 丢失、错误模拟输入和消费者跟不上仍需软件检测、保存现场、停止源和恢复。自动触发减少周期性 CPU 介入，不取消系统所有权和故障策略。

### 14.4 从 F407 迁移到 H7，可以直接复制哪些内容？

可以复制追踪问题的方法和“先接收、后源”的通用顺序；不能直接复制 RCC 位、timer/ADC kernel clock、EXTSEL 编码、HAL 宏、IRQ/DMA 映射、存储域或 D-Cache 策略。必须先固定 H7 完整料号及其第一方手册，再重建交叉表。

### 14.5 如何证明采样时刻由硬件 timer 决定，而不是 ISR？

代码上没有周期性 TIM ISR -> ADC start 调用；配置上有 `MMS=update` 和 ADC `EXTSEL/EXTEN`；关闭 TIM2 update IRQ 后 ADC 仍产生 EOC/DMA 数据；改变 PSC/ARR 后转换节拍相应变化。若需定量抖动证据，还应使用合适的片内事件输出、DMA 时间戳或外部仪器方案，不能仅凭 callback GPIO 波形下结论。

## 15. 延伸思考

1. 若想在计数周期中点而不是更新边界采样，应选择比较参考事件还是更改计数模式？哪些表和时序必须重查？
2. `MMS=update` 时，初始化 `UG` 可能产生额外触发。你会如何安排初始化和清除诊断计数，使第一次有效样本边界明确？
3. 两个 ADC 消费同一个 timer 事件时，谁持有源 timer？任一消费者停止时，是否有权停掉共享源？
4. ADC callback 只保存最新值会丢失历史。加入 DMA 后，触发频率、buffer length、半满间隔和最坏消费时间应满足什么关系？
5. 在 F7/H7 上，DMA 已写入内存但 CPU 仍读到旧 cache line 时，事件链的“可观察结果”应增加哪一层证据？
6. 安全控制系统中，触发路由配置被意外改写如何检测？可以考虑启动时读回、周期诊断、写保护或独立监控，但每项都需按目标器件安全手册核对。

## 16. 本节总结

本课唯一的新核心概念是**定时器触发路由的事件链**：

```text
TIM2 update
  -> TIM2_CR2.MMS exports TIM2_TRGO
  -> fixed F407 internal connection
  -> ADC1_CR2.EXTSEL/EXTEN selects source and edge
  -> ADC1 sample/convert
  -> EOC/OVR and optional IRQ callback
```

真正可迁移的不是 `0110` 或某个 HAL 宏，而是逐跳回答：源在哪里定义、谁持有配置、谁注入事件、内部连接是否合法、接收端是否武装、最终证据到达哪一层。Host Fake 证明这个状态和错误模型；STM32F407xx 参考轨道说明它如何落到 RCC、TIM2、ADC1、CubeMX、HAL、LL 和寄存器。两者证据不能互换。

当前没有目标硬件证据：STM32 参考代码未在本次运行中编译、烧录或测量，`hardware_verified=false`。

## 17. 下一步

下一主题 `advanced-control-timer` 将沿用事件链方法，深入互补输出、死区、刹车输入、重复计数和预装载/影子寄存器如何改变输出时刻与安全边界。随后 `adc-timer-dma-pipeline` 把本课已核对的 `TIM2_TRGO -> ADC1` 上游与 DMA request、缓冲区所有权、半满/完成 IRQ 和应用消费连接成可测量流水线。

## 18. 参考资料

- [S1] STMicroelectronics, *STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 advanced Arm-based 32-bit MCUs - Reference manual*, RM0090 Rev 22, May 2026：RCC、通用定时器、ADC 规则组外部触发、状态/中断；访问日期 2026-10-14。<https://www.st.com/resource/en/reference_manual/dm00031020.pdf>
- [S2] STMicroelectronics, *STM32F405xx STM32F407xx datasheet*, DS8626 Rev 12, March 2026：器件适用范围、时钟与 ADC 工作条件；访问日期 2026-10-14。<https://www.st.com/resource/en/datasheet/stm32f407vg.pdf>
- [S3] STMicroelectronics, *Description of STM32F4 HAL and low-layer drivers*, UM1725 Rev 8, March 2023：RCC/TIM/ADC HAL 与 LL API；访问日期 2026-10-14。<https://www.st.com/resource/en/user_manual/dm00105879.pdf>
- [S4] STMicroelectronics, *STM32Cube MCU Package for STM32F4 series*, STM32CubeF4 v1.28.3, 23 July 2025：本机安装包的 `stm32f4xx_hal_tim.*`、`stm32f4xx_hal_adc.*`、`stm32f4xx_ll_tim.h`、`stm32f4xx_ll_adc.h` 和设备头文件用于核对宏、字段及启动/IRQ 行为；访问日期 2026-10-14。<https://www.st.com/en/embedded-software/stm32cubef4.html>
- [S5] STMicroelectronics, *STM32Cube MCU Package for STM32F7 series*, STM32CubeF7 v1.17.3, 25 April 2025：仅用于限定 F7 迁移时需重查的 API、目标与缓存边界；访问日期 2026-10-14。<https://www.st.com/en/embedded-software/stm32cubef7.html>
- [S6] STMicroelectronics, *STM32Cube MCU Package for STM32H5 series*, STM32CubeH5 v1.5.0, 5 February 2025：仅用于限定 H5 迁移时需重查的 API、GPDMA 与安全属性边界；访问日期 2026-10-14。<https://www.st.com/en/embedded-software/stm32cubeh5.html>
- [S7] STMicroelectronics, *STM32Cube MCU Package for STM32H7 series*, STM32CubeH7 v1.12.1, 6 December 2024：仅用于限定 H7 迁移时需重查的 API、时钟域、DMA/DMAMUX、存储域与缓存边界；访问日期 2026-10-14。<https://www.st.com/en/embedded-software/stm32cubeh7.html>

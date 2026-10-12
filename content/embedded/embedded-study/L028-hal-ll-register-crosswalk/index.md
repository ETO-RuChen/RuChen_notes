+++
title = "HAL、LL 与寄存器的交叉映射"
date = "2026-10-12T20:17:48+08:00"
lastmod = "2026-10-12T20:17:48+08:00"
summary = "建立 HAL、LL 与寄存器交叉映射的追踪方法：先以 C11 Host Fake 验证前置条件、状态转换和 IRQ 消费，再以 STM32F407xx 的 ADC1 到 DMA2 Stream0 路径核对时钟门控、初始化字段、硬件标志、回调和错误证据。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 28
tags = ["hal", "ll", "registers", "crosswalk", "adc", "dma", "irq", "rcc", "host-fake", "stm32f407", "cubemx", "c11"]
source_ids = ["st-rm0090-crosswalk", "st-um1725-crosswalk", "st-ds8626-crosswalk"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L028"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 28 课：HAL、LL 与寄存器的交叉映射

调用 `HAL_ADC_Start_DMA()` 返回 `HAL_OK`，只说明 HAL（hardware abstraction layer，硬件抽象层）接受了这次启动请求；它不等于 ADC 已完成转换，也不等于 DMA 已写入缓冲区，更不等于应用已经消费数据。要判断链路真正停在哪里，必须把同一个操作在三个观察层对齐：HAL 的句柄和状态机、LL（low-layer，低层驱动）的近位域操作，以及芯片寄存器和状态位。

本课只推进一个核心概念：**HAL、LL 与寄存器交叉映射**。它是把同一硬件状态转换在抽象 API、近寄存器 API、寄存器/标志位三个层次逐项对应，并核对前置条件与可观察结果的方法。它不是三套独立硬件，也不是鼓励在一个运行中的驱动里随意混写 HAL、LL 和寄存器。

课程采用两条轨道：Host Fake（主机替身）先验证调用顺序、前置条件、状态转换和错误路径；STM32 参考轨道再把方法落实到 `STM32F407xx` 的 `ADC1 -> DMA2 Stream0/Channel0`。当前没有具体开发板、完整订货料号、板级 ADC 引脚、模拟输入、CubeMX 工程、目标构建日志、烧录记录或寄存器快照。所有 STM32 代码均为“参考实现，待目标工程编译”，没有烧录或测量证据，`hardware_verified=false`。

## 1. 本节目标

完成本课后，你应能：

1. 从一个操作意图建立“前置条件 -> HAL 对象/API -> LL 操作 -> 寄存器/标志 -> 观察证据”的交叉表；
2. 区分 API 返回成功、硬件开始运行、硬件置位标志、IRQ 被服务和应用消费完成五个时刻；
3. 说明配置对象、HAL 句柄、DMA 缓冲区和诊断快照分别在哪里定义、由谁持有、由谁注入；
4. 沿 `HAL_ADC_Start_DMA -> ADC 请求 -> DMA 搬运 -> DMA IRQ -> HAL_DMA_IRQHandler -> ADC 回调` 追踪控制流和数据流；
5. 在 STM32F407xx 上将 RCC 门控、ADC 公共预分频、DMA stream 配置、ADC/DMA 使能和中断标志对应到 HAL、LL 与 RM0090 寄存器；
6. 用证据定位失败属于参数、时钟/复位、ADC、DMA、NVIC/向量、HAL 分发还是应用消费；
7. 说明迁移 F7、H5、H7 时哪些映射必须按新目标的第一方资料重建。

核心目标与本次计划一致：建立 HAL、LL 与寄存器交叉映射的追踪方法，能以 STM32F407xx 的 ADC1 -> DMA2 Stream0 参考路径说明一个 HAL 初始化/启动调用如何落到时钟门控、外设/DMA 配置、状态位和 IRQ 回调，并保持 `hardware_verified=false` 的证据边界。

## 2. 它解决什么问题

### 2.1 “函数成功”与“工作完成”之间还有一条链

一次 ADC-DMA 启动至少有五种不同证据：

```text
HAL_ADC_Start_DMA() 返回 HAL_OK
  -> ADC 与 DMA 的相关使能状态已被请求
  -> ADC 转换事件产生 DMA 请求
  -> DMA 搬运并置位 HT/TC 或错误标志
  -> NVIC 接受 IRQ，向量处理函数调用 HAL 分发
  -> HAL 调用应用回调，应用随后消费对应缓冲区
```

只观察第一行，无法证明后四行。只看到 DMA `TCIF0`，也不能证明向量、HAL 分发和应用回调正常。交叉映射解决的是**证据断层**：每一层都写清“要发生什么、前置条件是什么、成功后能观察什么、失败时下一站查哪里”。

### 2.2 为什么不能靠背 API 或背寄存器

- 只背 HAL：遇到 `HAL_OK` 但缓冲区不变时，不知道应观察 ADC 请求、DMA 计数还是 IRQ。
- 只背寄存器：知道 `DMA_S0CR.EN`，却可能绕过 HAL 句柄状态、锁和回调连接，制造软件与硬件视图不一致。
- 只看 CubeMX：生成代码展示了一种配置，但不证明目标时钟、电气输入、请求映射和实际运行结果。
- 只看调试器：暂停内核可能改变外设/总线的相对时序；单次快照必须放回事件链解释。

交叉映射的目的不是选出“最好的一层”，而是让设计、实现和调试使用同一条因果链。

### 2.3 本课边界

ADC 采样、DMA 传输契约、中断优先级和时钟树已经完成，本课不把它们重新计为新概念。这里固定一个受控案例来练习追踪法，不展开定时器 TRGO（trigger output，触发输出）、双缓冲、缓存一致性或 RTOS 任务通知。它们分别在 `timer-trigger-routing`、`adc-timer-dma-pipeline`、`dma-coherency` 和后续并发课程深入。

## 3. 必要前置知识

### 3.1 最小复习

- ADC 转换完成后产生数据；在 DMA 模式下，外设请求驱动 DMA 从 `ADC_DR` 搬到内存。
- DMA 的 `NDTR` 是剩余数据项计数；它变化说明请求到达且搬运发生，不说明应用已处理数据。
- 硬件状态标志、外设中断使能、NVIC 使能、向量入口和 HAL 回调是不同关卡。
- RCC（reset and clock control，复位与时钟控制器）门控让外设接口获得时钟；它不决定 ADC 何时产生请求。
- HAL 句柄是软件对象，寄存器是硬件接口；两者相关但不是同一个对象。

### 3.2 术语

| 术语 | 准确含义 | 本课观察点 |
| --- | --- | --- |
| HAL | 硬件抽象层，以句柄、初始化结构体、状态机和统一回调组织外设流程 | 返回值、句柄状态、错误码、回调 |
| LL | 低层驱动，通常以接近寄存器位域的内联函数/宏表达局部硬件动作 | 单项配置、使能和 flag 查询/清除 |
| CMSIS | Cortex Microcontroller Software Interface Standard，Cortex 微控制器软件接口标准 | 设备头文件、IRQ 名称、NVIC 接口和寄存器结构入口 |
| 句柄 | HAL 用来关联外设实例、初始化参数、DMA 子句柄、状态与错误的长期软件对象 | `hadc1`、`hdma_adc1` |
| 初始化结构体 | 调用期内描述目标配置的字段集合 | `hadc1.Init`、`ADC_ChannelConfTypeDef`、`hdma_adc1.Init` |
| IRQ | interrupt request，中断请求 | 外设/ DMA 标志到处理函数的入口请求 |
| NVIC | nested vectored interrupt controller，嵌套向量中断控制器 | IRQ enable、pending、优先级和向量分发 |
| 状态位 | 硬件报告已发生或正在发生事件的位 | `DMA_LISR.TCIF0`、`ADC_SR.OVR` 等 |

## 4. 核心原理

### 4.1 一行交叉映射必须回答七件事

对每个操作意图，建立如下记录：

| 字段 | 要回答的问题 |
| --- | --- |
| 意图 | 这一步解决什么问题？ |
| 前置条件 | 哪些时钟、复位、静止状态或对象连接必须先成立？ |
| HAL | 哪个字段或 API 表达意图？返回值只证明什么？ |
| LL | 同一意图是否有 LL 操作？其适用版本是什么？ |
| 寄存器/标志 | 芯片实际接收配置或报告结果的位置是什么？ |
| 成功证据 | 调用后可以安全观察什么？哪个事件尚未被证明？ |
| 错误去向 | 失败如何返回、置位、进入 IRQ 或被应用记录？ |

“HAL 名称看起来相似”不是映射证据。HAL 可能一次写多个字段、安装内部回调并改变句柄状态；LL 通常只表达局部动作；直接寄存器路径还要求调用者自己负责顺序、清标志和软件状态。因此映射可以是一对多或多对一，不要求 API 数量相等。

### 4.2 同一转换的三个观察层

```text
操作意图：启动 ADC，并把结果循环搬到内存

HAL 层
  hadc1.Init + hdma_adc1.Init + __HAL_LINKDMA
  HAL_ADC_Start_DMA(&hadc1, buffer, count)
       |
       | 展开并核对
       v
LL 层
  配置 ADC/DMA 的局部字段、清标志、开中断、使能 stream/ADC、启动转换
       |
       | 最终作用于
       v
寄存器/事件层
  RCC enable/reset -> ADC_CCR/CR1/CR2/SQR/SMPR
  DMA_S0CR/PAR/M0AR/NDTR -> ADC request -> LISR flags
  -> NVIC -> vector -> HAL dispatch -> callback
```

HAL、LL 与寄存器不是顺序执行的三段程序。一个 HAL 函数内部通常直接通过设备头文件宏或寄存器访问完成工作，不一定调用公开 LL API。LL 列用于表达“如果以 LL 方式完成同一意图，应操作什么”，不是对 HAL 源码调用栈的虚构。

### 4.3 五种成功不能合并

| 成功层次 | 可以证明 | 不能证明 |
| --- | --- | --- |
| 参数/API 成功 | HAL 接受参数并完成其同步配置路径 | 外设事件已经发生 |
| 配置提交成功 | 目标寄存器读回符合预期 | 输入信号、触发或请求一定到达 |
| 硬件事件成功 | EOC、HT、TC 等状态出现 | IRQ 一定被内核服务 |
| IRQ 分发成功 | 进入正确向量并调用正确 HAL handler | 应用回调一定完成业务消费 |
| 应用消费成功 | 所有权协议允许使用对应数据块 | 下一周期不会覆盖或发生过载 |

调试时应记录“目前最深到哪一层”，不要笼统写“DMA 不工作”。

### 4.4 五项责任

| 问题 | Host Fake | STM32F407xx 参考轨道 |
| --- | --- | --- |
| 它解决什么 | 在无芯片头文件时验证启动前置条件、状态转换和错误路径 | 把同一意图落实到 F407 的时钟、ADC、DMA 和 IRQ 接口 |
| 对象在哪里定义 | 公共契约、快照、错误码在主机接口中定义 | 设备头文件定义寄存器；BSP 定义 HAL 句柄和缓冲区 |
| 谁持有 | 测试静态/栈上持有契约和 Fake 状态 | BSP 在整个运行期静态持有 `hadc1`、`hdma_adc1` 和缓冲区 |
| 谁注入 | 测试注入前置状态、请求与故障 | CubeMX/BSP 写初始化字段并用 `__HAL_LINKDMA` 连接句柄；板级组装选择 ADC 通道 |
| 调用如何流动 | 启动 -> 产生请求 -> 置位完成/错误 -> Fake IRQ -> 消费事件 | RCC -> DMA/ADC 配置 -> HAL 启动 -> 硬件请求/搬运 -> DMA IRQ -> HAL -> 应用回调 |

### 4.5 不混写的纪律

可以在调试器中用寄存器视图**读取** HAL 配置结果，也可以用交叉表解释 HAL；但不要在 HAL 正持有同一外设时用 LL 或调试器直接改配置来“修好”现场。这样会绕过 HAL 的 `State`、`Lock`、错误码和内部回调连接。若决定改为 LL-only 或寄存器驱动，应明确建立新的所有权边界、完整初始化/停止/清错顺序和测试，而不是在一次事务中临时混用。

## 5. 关键术语与直观模型

把交叉映射想成一份带检查点的货运单：HAL 是业务委托和软件状态，LL 是局部控制动作，寄存器/标志是设备真正接受和报告的接口。货运单上的“已受理”不是“已送达”；每个中转点都要有可观察凭据。

最小表可以这样写：

| 意图 | HAL | LL | 硬件状态 | 观察结论 |
| --- | --- | --- | --- | --- |
| 允许 DMA2 工作 | `__HAL_RCC_DMA2_CLK_ENABLE()` | `LL_AHB1_GRP1_EnableClock(...)` | `RCC_AHB1ENR.DMA2EN=1` | 只证明门控打开，不证明有 ADC 请求 |
| 启动 stream | `HAL_ADC_Start_DMA()` 的内部启动路径 | `LL_DMA_EnableStream(...)` | `DMA_S0CR.EN=1` | 只证明 stream 已使能，不证明已搬运 |
| 证明搬运完成 | ADC 完成回调最终被调用 | 查询 `TC0` flag | `DMA_LISR.TCIF0=1` | flag 证明硬件完成一轮；回调还依赖 IRQ 链 |

## 6. 从输入到结果的完整流程

### 6.1 初始化控制流

```text
HAL_Init
  -> SystemClock_Config
       -> HSI/PLL/AHB/APB/Flash 条件稳定
  -> MX_DMA_Init
       -> DMA2 AHB1 门控
       -> DMA2_Stream0 IRQ 优先级与 NVIC enable
  -> MX_ADC1_Init
       -> HAL_ADC_Init
            -> HAL_ADC_MspInit
                 -> ADC1 APB2 门控
                 -> HAL_DMA_Init(&hdma_adc1)
                 -> __HAL_LINKDMA(&hadc1, DMA_Handle, hdma_adc1)
       -> HAL_ADC_ConfigChannel
  -> HAL_ADC_Start_DMA
```

每个返回 `HAL_StatusTypeDef` 的调用都必须立即检查。初始化失败后继续运行，会把首个错误覆盖成下游“无数据”。

### 6.2 运行时数据流与中断流

```text
软件启动或外部触发
  -> ADC 开始转换
  -> ADC_DR 产生数据并发出 DMA 请求
  -> DMA2 Stream0 从 ADC1->DR 读 half-word
  -> DMA2 Stream0 写内存并递减 NDTR
  -> 到半边界：HTIF0；到末尾：TCIF0；出错：TEIF0/DMEIF0/FEIF0
  -> DMA2_Stream0_IRQn pending
  -> DMA2_Stream0_IRQHandler()
  -> HAL_DMA_IRQHandler(&hdma_adc1)
  -> HAL 安装的 ADC-DMA 内部回调
  -> HAL_ADC_ConvHalfCpltCallback / HAL_ADC_ConvCpltCallback / HAL_ADC_ErrorCallback
  -> 应用只记录事件；主循环消费数据或执行恢复
```

控制流沿函数和 IRQ 入口移动，数据流从 `ADC_DR` 到内存。两条流在 DMA 标志和 HAL handler 处会合，但不能混为一条线。

### 6.3 失败定位树

```text
HAL_ADC_Start_DMA != HAL_OK
  -> 查参数、句柄状态、DMA 句柄关联和 HAL 错误码

HAL_OK，但 NDTR 从不变化
  -> 查 RCC 门控/复位、ADC 时钟、ADC enable、触发/软件启动、DMA request、stream enable

NDTR 变化且 flag 出现，但不进 IRQ
  -> 查 stream interrupt enable、NVIC enable/pending、优先级屏蔽、向量表入口

进入 DMA2_Stream0_IRQHandler，但无 ADC 回调
  -> 查是否调用 HAL_DMA_IRQHandler(&hdma_adc1)、句柄是否为同一实例、HAL 内部回调连接

回调发生，但应用看不到数据
  -> 查事件变量、volatile/并发规则、缓冲区半区所有权和消费速度
```

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

| 层级 | 能力与工作原理 | 触发/数据/中断链 | 本课与后续落点 |
| --- | --- | --- | --- |
| 基础 | 从初始化/启动动作追到门控、配置、使能、状态和错误返回 | 软件调用 -> 配置寄存器 -> 状态读回 | 本课完整示范 |
| 进阶 | 将硬件 flag、NVIC、向量、HAL handler 和应用回调分层观察 | ADC request -> DMA HT/TC/TE -> IRQ -> 回调 | 本课静态交叉表；`register-view` 做实时证据采集 |
| 高级 | 双缓冲在两个地址间切换以延长消费窗口；DMA burst 用一次请求序列搬多个寄存器；链表 DMA 由描述符驱动后续节点 | 请求路由 -> DMA 队列/双缓冲 -> 分段中断 -> 消费者；缓存系统还需 clean/invalidate | 双缓冲与 burst 在 DMA 深化实验；缓存一致性在 `dma-coherency`；H5 GPDMA 链表按具体目标课核对 |
| 跨外设联动 | 定时器更新事件经 TRGO 驱动 ADC，ADC 完成产生 DMA 请求，DMA 批量完成再通知软件 | Timer TRGO -> ADC sample/convert -> DMA -> IRQ/任务 | `timer-trigger-routing` 与 `adc-timer-dma-pipeline` |
| 系列差异 | 映射方法可迁移，具体时钟、请求器、DMA 控制器、缓存和安全属性不可照搬 | 每个目标从 RCC/trigger/request/memory/IRQ 重新建图 | F4 本课；F7/H5/H7 在对应系列与性能课程深化 |

F4/F7/H5/H7 的迁移重点：

| 系列 | 可迁移 | 必须按具体器件第一方资料重查 |
| --- | --- | --- |
| F4 | 意图、前置条件、证据层次和错误树 | 本课给出的 stream/channel、RCC 位、ADC/DMA 字段只限 RM0090 覆盖器件 |
| F7 | 同样可从 HAL 追到 flag/IRQ/回调 | DMA 请求表、存储区可达性；具备数据缓存的目标还要重建 DMA 缓冲区一致性协议 |
| H5 | 同样区分 API 成功与硬件完成 | GPDMA/DMAMUX 的 request、channel、链表节点、时钟、TrustZone/安全属性；未选目标前不写寄存器名 |
| H7 | 同样按控制流和数据流收集证据 | DMA/BDMA/MDMA 选择、DMAMUX、域时钟、总线/内存域可达性、D-Cache；双核型号还需核对共享与中断归属 |

高级功能不能靠替换一个 API 名获得。例如缓存存在时，即使 DMA `TC` 已置位，CPU 读取的 cache line 仍可能是旧数据；此时交叉表必须增加“缓冲区位于何处、谁 clean/invalidate、屏障何时发生”这一层证据。F407 本案例不据此推断 F7/H7 行为。

### 7.2 参考目标与时钟/复位链

参考目标为 `STM32F407xx`，寄存器和请求映射依据 RM0090 Rev 22，HAL/LL API 边界依据 UM1725 Rev 8，运行条件边界由 DS8626 Rev 12 约束。[S1][S2][S3] 本课没有选定封装、引脚或开发板。

沿用上一课已建立的参考参数集，不声称未知板卡采用此配置：

```text
HSI 16 MHz
  -> PLLM /16 = 1 MHz
  -> PLLN x336 = 336 MHz VCO
  -> PLLP /2 = 168 MHz SYSCLK
  -> AHB /1 = 168 MHz HCLK
       -> DMA2 AHB1 interface：168 MHz 分支 + RCC_AHB1ENR.DMA2EN
  -> APB2 /2 = 84 MHz PCLK2
       -> ADC common prescaler /4 = 21 MHz ADCCLK
       -> ADC1 interface gate：RCC_APB2ENR.ADC1EN
```

最终 21 MHz 是这组参考参数下的 ADC 时钟，不是采样率。采样时间与分辨率对应的转换周期共同决定请求上限；软件触发/外部触发决定何时开始；DMA2 的 HCLK 只支撑总线访问。[S1][S3]

完整门控与复位顺序：

```text
HSI ready -> PLL ready -> SYSCLK switch confirmed
  -> AHB/APB prescalers established
  -> enable DMA2 AHB1 gate
  -> optional DMA2 reset pulse, then release (only before other DMA2 users run)
  -> enable ADC1 APB2 gate
  -> optional shared ADC reset pulse, then release (only before every ADC user is idle)
  -> program DMA2 Stream0 while EN=0; clear stale flags
  -> program ADC common prescaler and ADC1 fields
  -> enable NVIC path
  -> enable DMA stream and ADC/DMA request
  -> trigger conversion
```

门控、复位和外设使能是三个动作：门控决定寄存器接口/模块能否获得时钟；复位把模块恢复到规定状态；`DMA_S0CR.EN` 与 `ADC_CR2.ADON` 才启动对应运行状态。整块 DMA2 复位只能在确认没有其他 stream 使用者时执行；F407 的 `RCC_APB2RSTR.ADCRST` 是 ADC1/2/3 共用复位，只有确认所有 ADC 使用者都静止时才可脉冲，不能用它恢复单个 ADC1。[S1]

### 7.3 CubeMX、HAL、LL 与寄存器对照

#### CubeMX/CubeMX2 配置清单

1. 选择实际使用的 STM32F407 完整料号；记录 STM32CubeMX/CubeMX2 和 STM32CubeF4 包版本。
2. **RCC / Clock Configuration**：参考方案选择 HSI，设置 PLLM=16、PLLN=336、PLLP=2，AHB=/1、APB1=/4、APB2=/2；目标工程必须按完整料号、VDD、调压与 Flash 条件重新核对。
3. **ADC1**：选择实际板卡允许的 ADC 通道和模拟引脚；本课不指定引脚。12-bit、right alignment、single conversion rank；参考连续模式开启，ADC clock=PCLK2/4，采样时间需按模拟源阻抗核对。
4. **DMA Settings**：ADC1 request，DMA2 Stream0/Channel0，Peripheral-to-Memory，Circular，Peripheral Increment Disabled，Memory Increment Enabled，Peripheral/Memory Data Width=Half Word，Priority=High，FIFO Disabled。该映射来自 RM0090 表 44，只适用于手册覆盖目标。[S1]
5. **NVIC**：启用 DMA2 Stream0 global interrupt；如需要由 HAL 处理 ADC overrun（过载），启用共享 ADC global interrupt。优先级按完整系统策略选择，不能从本文复制为通用值。
6. **Project Manager**：生成后审计 `SystemClock_Config`、`MX_DMA_Init`、`HAL_ADC_MspInit`、`MX_ADC1_Init`、`stm32f4xx_it.c` 和句柄链接，不以 GUI 绿色状态代替源码审计。

板级必须提供：完整料号、实际 ADC channel/pin、模拟输入范围/参考与源阻抗、外部时钟条件（如不用 HSI）、中断优先级政策。缺少这些信息时，参考机制仍可实现，但不能声称引脚、电气或时序已适配。

#### 对象、所有权和生命周期

| 对象 | 定义/实例化 | 持有者与生命周期 | 注入方式 |
| --- | --- | --- | --- |
| `ADC_HandleTypeDef hadc1` | BSP/生成代码的目标适配文件 | BSP 静态持有，覆盖初始化、运行、IRQ 与停止 | `Instance`、`Init` 字段由初始化函数写入 |
| `DMA_HandleTypeDef hdma_adc1` | BSP/生成代码的目标适配文件 | BSP 静态持有；IRQ handler 与 ADC 句柄长期引用 | `HAL_DMA_Init` 后由 `__HAL_LINKDMA` 双向连接 |
| `ADC_ChannelConfTypeDef channel` | ADC 初始化函数内 | 调用期局部对象；提交后可结束生命周期 | 板级组装传入合法通道常量 |
| DMA 缓冲区 | BSP 数据模块 | BSP/DMA 共同持有；DMA 运行时应用不得写正在填充区 | 地址和数据项数传给 `HAL_ADC_Start_DMA` |
| 诊断记录 | BSP 诊断模块 | 静态持有；ISR 写最小字段，主循环读取 | 回调注入事件、HAL/寄存器快照 |

#### HAL 初始化字段

`hadc1.Init` 的关键字段不是装饰性元数据：

- `ClockPrescaler`：选择 ADC 公共时钟相对 PCLK2 的分频，本例 `/4`；最终进入 ADC common control register 的 `ADCPRE`。
- `Resolution`、`DataAlign`：决定 ADC 结果格式及 `ADC_DR` 中的有效布局。
- `ScanConvMode`、`NbrOfConversion`：本例单 rank；多 rank 会改变序列与 DMA 数据顺序。
- `ContinuousConvMode`：转换完成后继续下一次转换；它不同于 DMA circular。
- `ExternalTrigConvEdge`、`ExternalTrigConv`：本例软件启动；未来 Timer TRGO 课改为硬件触发。
- `DMAContinuousRequests`：使连续 DMA 请求与 circular stream 配合；对应 F4 ADC `CR2.DDS` 行为。
- `EOCSelection`：HAL 如何解释 conversion/sequence 完成；迁移时按包版本核对。

`hdma_adc1.Init` 定义方向、地址递增、peripheral/memory 数据宽度、normal/circular、优先级和 FIFO。`HAL_ADC_Start_DMA` 的 `Length` 最终对应 DMA 数据项数，本例 half-word 配置下不是字节数。[S1][S2]

#### HAL、LL、寄存器交叉表

下表的寄存器语义来自 RM0090 Rev 22；LL 名称以 UM1725 Rev 8 的 STM32F4 API 面为版本边界。实际工程仍需与安装的 STM32CubeF4 头文件逐项比对。[S1][S2]

| 意图/前置条件 | HAL 字段或动作 | 同意图 LL 入口 | F407 寄存器/状态 | 成功观察与错误边界 |
| --- | --- | --- | --- | --- |
| 开 DMA2 门控；RCC 可访问 | `__HAL_RCC_DMA2_CLK_ENABLE()` | `LL_AHB1_GRP1_EnableClock(LL_AHB1_GRP1_PERIPH_DMA2)` | `RCC_AHB1ENR.DMA2EN` | 读回为 1 只证明门控；无请求时 NDTR 仍不变 |
| 开 ADC1 门控；PCLK2 已建立 | `__HAL_RCC_ADC1_CLK_ENABLE()` | `LL_APB2_GRP1_EnableClock(LL_APB2_GRP1_PERIPH_ADC1)` | `RCC_APB2ENR.ADC1EN` | 读回为 1；不证明 ADCCLK/触发正确 |
| 复位并释放 DMA2；所有 stream 静止 | `__HAL_RCC_DMA2_FORCE_RESET()` / `__HAL_RCC_DMA2_RELEASE_RESET()` | `LL_AHB1_GRP1_ForceReset/ReleaseReset(LL_AHB1_GRP1_PERIPH_DMA2)` | `RCC_AHB1RSTR.DMA2RST` | 必须看到 reset 位释放；共享运行期禁止整块复位 |
| 复位并释放 ADC 公共接口；ADC1/2/3 均静止 | `__HAL_RCC_ADC_FORCE_RESET()` / `__HAL_RCC_ADC_RELEASE_RESET()` | `LL_APB2_GRP1_ForceReset/ReleaseReset(LL_APB2_GRP1_PERIPH_ADC)` | `RCC_APB2RSTR.ADCRST` | 该位共用于全部 ADC，不能当成 ADC1 私有恢复动作 |
| 设置 ADC 公共分频；ADC 未运行 | `ClockPrescaler=ADC_CLOCK_SYNC_PCLK_DIV4` 后 `HAL_ADC_Init` | `LL_ADC_SetCommonClock(..., LL_ADC_CLOCK_SYNC_PCLK_DIV4)` | `ADC_CCR.ADCPRE=01` | PCLK2 84 MHz 时推导 ADCCLK 21 MHz；这是计算值，不是物理测量 |
| 选择 DMA 请求映射；stream disabled | `Instance=DMA2_Stream0`、`Channel=DMA_CHANNEL_0` | `LL_DMA_SetChannelSelection(DMA2, LL_DMA_STREAM_0, LL_DMA_CHANNEL_0)` | `DMA_S0CR.CHSEL=000`；RM0090 表 44 | 读回映射正确仍不证明 ADC request 到达 |
| 配方向/宽度/递增/循环；EN=0 | `hdma_adc1.Init.*` 后 `HAL_DMA_Init` | `LL_DMA_SetDataTransferDirection`、`SetPeriphSize`、`SetMemorySize`、`SetMemoryIncMode`、`SetMode` | `DMA_S0CR.DIR/PINC/MINC/PSIZE/MSIZE/CIRC/PL`、`DMA_S0FCR` | HAL 返回值与寄存器读回；EN=1 时不得改大多数配置字段 |
| 连接软件对象；两个句柄已存在 | `__HAL_LINKDMA(hadc, DMA_Handle, hdma_adc1)` | 无硬件 LL 等价；这是 HAL 软件连接 | `hadc1.DMA_Handle` 与 `hdma_adc1.Parent`，不写外设寄存器 | 指针双向一致；错误连接会让 IRQ 到错误 parent/回调 |
| 提交地址和计数；buffer 有效 | `HAL_ADC_Start_DMA(hadc, buffer, count)` 内部 DMA 启动 | `LL_DMA_SetPeriphAddress`、`SetMemoryAddress`、`SetDataLength` | `DMA_S0PAR=&ADC1->DR`、`M0AR=buffer`、`NDTR=count` | 地址/计数读回；仍未证明已产生一次请求 |
| 开 HT/TC/error interrupt；旧 flag 已清 | HAL ADC-DMA 启动内部配置 DMA callback/IT | `LL_DMA_EnableIT_HT/TC/TE/DME`；FIFO error 按实际配置核对 | `DMA_S0CR.HTIE/TCIE/TEIE/DMEIE`、`DMA_S0FCR.FEIE` | enable 位 + NVIC enable 均需要；有 flag 无 IRQ 时查后半链 |
| 使能 stream；配置已完成 | HAL ADC-DMA 启动内部 DMA start | `LL_DMA_EnableStream(DMA2, LL_DMA_STREAM_0)` | `DMA_S0CR.EN` | EN=1 证明 stream armed；NDTR 变化才证明请求/搬运 |
| 允许 ADC DMA 请求与连续请求 | `HAL_ADC_Start_DMA`，结合 `DMAContinuousRequests=ENABLE` | `LL_ADC_REG_SetDMATransfer(...UNLIMITED)`，常量名按包版本复核 | `ADC_CR2.DMA[1:0]`、`DDS` | 位读回；错误模式可能导致序列后停止请求 |
| 使能 ADC 并软件启动；ADC 配置合法 | `HAL_ADC_Start_DMA` | `LL_ADC_Enable`、`LL_ADC_REG_StartConversionSWStart` | `ADC_CR2.ADON`、`SWSTART`；转换状态在 `ADC_SR` | SWSTART 是启动动作；EOC/OVR 与 DMA 请求才是后续证据 |
| 半/全搬运或 DMA 错误 | HAL DMA handler 分发到 ADC 回调 | `LL_DMA_IsActiveFlag_HT0/TC0/TE0/DME0/FE0` 与 clear API | `DMA_LISR.HTIF0/TCIF0/TEIF0/DMEIF0/FEIF0`；`DMA_LIFCR` 清除 | flag 是硬件证据；handler 必须按文档顺序处理/清除 |
| ADC overrun 等 ADC 错误 | `HAL_ADC_IRQHandler` / `HAL_ADC_ErrorCallback` / `HAL_ADC_GetError` | 查询并清 ADC flag 的 LL API，按包版本复核 | `ADC_SR.OVR` 等、`ADC_CR1` 对应中断使能 | 区分 ADC_IRQn 与 DMA2 Stream0 IRQ；保存 ADC 和 DMA 两侧错误码 |

关键审计结论：`__HAL_LINKDMA` 没有寄存器等价物，因为它解决的是软件对象关系；反过来，某些硬件 flag 也未必有一个独立 HAL API，可能只在 handler 内部被消费。交叉映射不应强迫三列一一同名。

#### HAL 参考实现

以下代码属于目标 BSP 适配层，依赖方向为 App -> BSP -> STM32CubeF4 HAL -> CMSIS/硬件。句柄、缓冲区和诊断记录由 BSP 静态持有整个运行期。代码未在本次运行中放入实际 Cube 工程编译，需以安装包头文件核对字段和宏。

```c
/* 示例，待目标工程编译和上板验证。 */
#include "stm32f4xx_hal.h"
#include <stdint.h>

#define ADC_DMA_SAMPLE_COUNT 128U

typedef uint32_t bsp_adc_error_t;

#define BSP_ADC_OK               UINT32_C(0)
#define BSP_ADC_ERR_CLOCK        UINT32_C(1)
#define BSP_ADC_ERR_DMA_INIT     UINT32_C(2)
#define BSP_ADC_ERR_ADC_INIT     UINT32_C(3)
#define BSP_ADC_ERR_CHANNEL      UINT32_C(4)
#define BSP_ADC_ERR_START        UINT32_C(5)
#define BSP_ADC_ERR_RUNTIME      UINT32_C(6)

typedef struct {
    volatile uint32_t half_events;
    volatile uint32_t full_events;
    volatile uint32_t error_events;
    volatile uint32_t hal_adc_error;
    volatile uint32_t hal_dma_error;
    volatile bsp_adc_error_t first_error;
} bsp_adc_diag_t;

ADC_HandleTypeDef hadc1;
DMA_HandleTypeDef hdma_adc1;

_Alignas(uint32_t)
static uint16_t g_adc_samples[ADC_DMA_SAMPLE_COUNT];
static bsp_adc_diag_t g_adc_diag;
static HAL_StatusTypeDef g_adc_msp_status = HAL_OK;

static void bsp_record_first_error(bsp_adc_error_t error)
{
    if (g_adc_diag.first_error == BSP_ADC_OK) {
        g_adc_diag.first_error = error;
    }
}

static void MX_DMA_Init_Reference(void)
{
    __HAL_RCC_DMA2_CLK_ENABLE();

    /* 仅允许在启动早期、确认 DMA2 没有其他使用者时复位。 */
    __HAL_RCC_DMA2_FORCE_RESET();
    __HAL_RCC_DMA2_RELEASE_RESET();

    /* 示例优先级；集成时按完整系统策略重新选择。 */
    HAL_NVIC_SetPriority(DMA2_Stream0_IRQn, 5U, 0U);
    HAL_NVIC_EnableIRQ(DMA2_Stream0_IRQn);
}

void HAL_ADC_MspInit(ADC_HandleTypeDef *hadc)
{
    if ((hadc == NULL) || (hadc->Instance != ADC1)) {
        return;
    }

    __HAL_RCC_ADC1_CLK_ENABLE();
    /* ADCRST 共用于 ADC1/2/3；只允许在所有 ADC 使用者均静止的启动期执行。 */
    __HAL_RCC_ADC_FORCE_RESET();
    __HAL_RCC_ADC_RELEASE_RESET();

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
        bsp_record_first_error(BSP_ADC_ERR_DMA_INIT);
        return;
    }

    __HAL_LINKDMA(hadc, DMA_Handle, hdma_adc1);
}

static bsp_adc_error_t MX_ADC1_Init_Reference(uint32_t board_adc_channel)
{
    ADC_ChannelConfTypeDef channel = {0};

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

    if ((HAL_ADC_Init(&hadc1) != HAL_OK) ||
        (g_adc_msp_status != HAL_OK)) {
        bsp_record_first_error(BSP_ADC_ERR_ADC_INIT);
        return BSP_ADC_ERR_ADC_INIT;
    }

    channel.Channel = board_adc_channel;
    channel.Rank = 1U;
    channel.SamplingTime = ADC_SAMPLETIME_84CYCLES;
    if (HAL_ADC_ConfigChannel(&hadc1, &channel) != HAL_OK) {
        bsp_record_first_error(BSP_ADC_ERR_CHANNEL);
        return BSP_ADC_ERR_CHANNEL;
    }

    return BSP_ADC_OK;
}

static bsp_adc_error_t BSP_ADC_Start(void)
{
    if ((hadc1.DMA_Handle != &hdma_adc1) ||
        (hdma_adc1.Parent != &hadc1)) {
        bsp_record_first_error(BSP_ADC_ERR_START);
        return BSP_ADC_ERR_START;
    }

    if (HAL_ADC_Start_DMA(&hadc1,
                          (uint32_t *)g_adc_samples,
                          ADC_DMA_SAMPLE_COUNT) != HAL_OK) {
        g_adc_diag.hal_adc_error = HAL_ADC_GetError(&hadc1);
        g_adc_diag.hal_dma_error = HAL_DMA_GetError(&hdma_adc1);
        bsp_record_first_error(BSP_ADC_ERR_START);
        return BSP_ADC_ERR_START;
    }

    return BSP_ADC_OK;
}
```

这里把板级 ADC channel 作为组装参数传入，避免虚构引脚。`_Alignas(uint32_t)` 满足 HAL 启动入口的指针对齐要求，实际 DMA 传输宽度仍由 half-word 配置决定。通道宏只能由选定完整料号、封装、板卡原理图和 CubeMX pinout 共同确定。

调用顺序属于 BSP 组装层：

```c
/* 示例，待目标工程编译和上板验证。 */
int main(void)
{
    HAL_Init();

    if (SystemClock_Config_Reference() != HAL_OK) {
        Error_Handler();
    }

    MX_GPIO_Init(); /* 实际 ADC 模拟引脚由目标工程生成。 */
    MX_DMA_Init_Reference();

    if (MX_ADC1_Init_Reference(BSP_ADC_CHANNEL) != BSP_ADC_OK) {
        Error_Handler();
    }

    if (BSP_ADC_Start() != BSP_ADC_OK) {
        Error_Handler();
    }

    for (;;) {
        app_consume_adc_events();
    }
}
```

`BSP_ADC_CHANNEL` 必须在实际板级配置头文件中定义为合法的 `ADC_CHANNEL_x`；它不是本文偷偷选定的占位引脚。`SystemClock_Config_Reference` 复用上一课的 HSI 参考方案，实施时由实际 CubeMX 工程生成并审计。

#### IRQ、回调与错误路径

```c
/* stm32f4xx_it.c：向量层，只把正确句柄交给 HAL。 */
void DMA2_Stream0_IRQHandler(void)
{
    HAL_DMA_IRQHandler(&hdma_adc1);
}

/* 若目标配置启用 ADC IRQ，用它捕获 ADC 侧中断源。 */
void ADC_IRQHandler(void)
{
    HAL_ADC_IRQHandler(&hadc1);
}

/* BSP 事件层：ISR 中只记录，不打印、不重新初始化。 */
void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef *hadc)
{
    if ((hadc != NULL) && (hadc->Instance == ADC1)) {
        g_adc_diag.half_events++;
    }
}

void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *hadc)
{
    if ((hadc != NULL) && (hadc->Instance == ADC1)) {
        g_adc_diag.full_events++;
    }
}

void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *hadc)
{
    if ((hadc != NULL) && (hadc->Instance == ADC1)) {
        g_adc_diag.hal_adc_error = HAL_ADC_GetError(hadc);
        g_adc_diag.hal_dma_error = HAL_DMA_GetError(hadc->DMA_Handle);
        g_adc_diag.error_events++;
        bsp_record_first_error(BSP_ADC_ERR_RUNTIME);
    }
}
```

DMA 硬件置位 flag 后，只有对应 stream interrupt enable、NVIC enable、内核未屏蔽该优先级、向量表指向正确 handler、handler 使用正确句柄、HAL 内部 DMA callback 已由 `HAL_ADC_Start_DMA` 安装，才会进入 ADC 完成/错误回调。[S2]

恢复动作放在主循环：先阻止应用把新数据当成有效；调用 `HAL_ADC_Stop_DMA`；保存 `ADC_SR/CR1/CR2`、`DMA_S0CR/NDTR/LISR`、HAL 错误码；确认 stream disabled；按错误类型清理和重新初始化。不能在 ISR 中打印或复位整个 DMA2，也不能只清 flag 后假装根因消失。

#### 声明、实现、实例化、组装和使用

即使本课不是架构课，也要把五个动作分清：

| 动作 | 示例位置 | 责任 |
| --- | --- | --- |
| 声明 | `bsp_adc.h` 中声明 `BSP_ADC_Start`、事件读取接口和错误类型 | 定义 App 能依赖的契约，不暴露寄存器 |
| 实现 | `bsp_adc_stm32f407.c` 中实现 HAL 初始化、回调和恢复 | 依赖 STM32CubeF4 HAL/CMSIS |
| 实例化 | 同文件定义 `hadc1`、`hdma_adc1`、静态缓冲区 | 建立唯一长期对象和生命周期 |
| 组装 | `board.c`/`main.c` 选择实际 channel，按顺序调用 clock/DMA/ADC init | 注入板级决定并连接对象 |
| 使用 | `app.c` 消费半区/全区事件 | 只依赖 BSP 契约，不改 HAL/寄存器 |

依赖方向始终从 App 指向 BSP 接口，再到目标实现；中断从硬件反向进入实现，但不会让 App 持有 HAL 句柄。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

Host Fake 不模拟 F407 位布局，只表达“启动前置条件、循环请求、计数重装、半/全完成标志、IRQ 消费和显式停止”的最小闭环。它与本课 F407 参考配置的 circular DMA 生命周期一致；公开接口使用固定宽度整数，不使用动态内存。

```c
/* host_crosswalk.c：C11，主机机制模型。 */
#include <assert.h>
#include <stdint.h>
#include <string.h>

typedef int32_t peripheral_status_t;

#define PERIPH_OK             INT32_C(0)
#define PERIPH_ERR_ARGUMENT  -INT32_C(1)
#define PERIPH_ERR_CLOCK     -INT32_C(2)
#define PERIPH_ERR_CONFIG    -INT32_C(3)
#define PERIPH_ERR_DMA       -INT32_C(4)
#define PERIPH_ERR_IRQ       -INT32_C(5)
#define PERIPH_ERR_RUNNING   -INT32_C(6)

typedef struct {
    uint8_t clock_enabled;
    uint8_t config_committed;
    uint8_t dma_linked;
    uint8_t irq_registered;
    uint32_t transfer_count;
} peripheral_contract_t;

typedef struct {
    uint8_t running;
    uint8_t request_enabled;
    uint8_t half_flag;
    uint8_t complete_flag;
    uint8_t error_flag;
    uint32_t remaining;
    uint32_t reload_count;
    uint32_t half_callbacks;
    uint32_t completed_callbacks;
    uint32_t error_callbacks;
} peripheral_snapshot_t;

peripheral_status_t peripheral_start(
    const peripheral_contract_t *contract,
    peripheral_snapshot_t *state)
{
    peripheral_snapshot_t next;

    if ((contract == NULL) || (state == NULL) ||
        (contract->transfer_count < 2U) ||
        ((contract->transfer_count % 2U) != 0U)) {
        return PERIPH_ERR_ARGUMENT;
    }
    if (state->running != 0U) {
        return PERIPH_ERR_RUNNING;
    }
    if (contract->clock_enabled == 0U) {
        return PERIPH_ERR_CLOCK;
    }
    if (contract->config_committed == 0U) {
        return PERIPH_ERR_CONFIG;
    }
    if (contract->dma_linked == 0U) {
        return PERIPH_ERR_DMA;
    }
    if (contract->irq_registered == 0U) {
        return PERIPH_ERR_IRQ;
    }

    next = *state;
    next.running = 1U;
    next.request_enabled = 1U;
    next.half_flag = 0U;
    next.complete_flag = 0U;
    next.error_flag = 0U;
    next.remaining = contract->transfer_count;
    next.reload_count = contract->transfer_count;
    *state = next;
    return PERIPH_OK;
}

peripheral_status_t peripheral_fake_request(
    peripheral_snapshot_t *state,
    uint8_t inject_dma_error)
{
    if (state == NULL) {
        return PERIPH_ERR_ARGUMENT;
    }
    if ((state->running == 0U) || (state->request_enabled == 0U)) {
        return PERIPH_ERR_RUNNING;
    }
    if (inject_dma_error != 0U) {
        state->error_flag = 1U;
        state->request_enabled = 0U;
        return PERIPH_ERR_DMA;
    }
    state->remaining--;
    if (state->remaining == (state->reload_count / 2U)) {
        state->half_flag = 1U;
    }
    if (state->remaining == 0U) {
        state->complete_flag = 1U;
        state->remaining = state->reload_count;
    }
    return PERIPH_OK;
}

void peripheral_fake_irq(peripheral_snapshot_t *state)
{
    if (state == NULL) {
        return;
    }
    if (state->error_flag != 0U) {
        state->error_flag = 0U;
        state->running = 0U;
        state->request_enabled = 0U;
        state->error_callbacks++;
        return;
    }
    if (state->half_flag != 0U) {
        state->half_flag = 0U;
        state->half_callbacks++;
    }
    if (state->complete_flag != 0U) {
        state->complete_flag = 0U;
        state->completed_callbacks++;
    }
}

peripheral_status_t peripheral_stop(peripheral_snapshot_t *state)
{
    if (state == NULL) {
        return PERIPH_ERR_ARGUMENT;
    }
    if (state->running == 0U) {
        return PERIPH_ERR_RUNNING;
    }

    state->request_enabled = 0U;
    state->running = 0U;
    state->remaining = 0U;
    return PERIPH_OK;
}

static void test_circular_completion_requires_irq_consumption(void)
{
    const peripheral_contract_t contract = {1U, 1U, 1U, 1U, 4U};
    peripheral_snapshot_t state;
    uint32_t index;

    (void)memset(&state, 0, sizeof(state));
    assert(peripheral_start(&contract, &state) == PERIPH_OK);
    assert(state.running == 1U);

    for (index = 0U; index < 2U; index++) {
        assert(peripheral_fake_request(&state, 0U) == PERIPH_OK);
    }
    assert(state.half_flag == 1U);
    assert(state.half_callbacks == 0U);
    peripheral_fake_irq(&state);
    assert(state.half_flag == 0U);
    assert(state.half_callbacks == 1U);

    for (index = 0U; index < 2U; index++) {
        assert(peripheral_fake_request(&state, 0U) == PERIPH_OK);
    }
    assert(state.complete_flag == 1U);
    assert(state.remaining == contract.transfer_count);
    assert(state.request_enabled == 1U);
    assert(state.completed_callbacks == 0U);
    peripheral_fake_irq(&state);
    assert(state.complete_flag == 0U);
    assert(state.completed_callbacks == 1U);
    assert(state.running == 1U);

    assert(peripheral_stop(&state) == PERIPH_OK);
    assert(state.running == 0U);
    assert(state.request_enabled == 0U);
}

static void test_each_precondition(void)
{
    peripheral_contract_t contract = {1U, 1U, 1U, 1U, 4U};
    peripheral_snapshot_t state;

    (void)memset(&state, 0, sizeof(state));
    contract.clock_enabled = 0U;
    assert(peripheral_start(&contract, &state) == PERIPH_ERR_CLOCK);

    contract.clock_enabled = 1U;
    contract.config_committed = 0U;
    assert(peripheral_start(&contract, &state) == PERIPH_ERR_CONFIG);

    contract.config_committed = 1U;
    contract.dma_linked = 0U;
    assert(peripheral_start(&contract, &state) == PERIPH_ERR_DMA);

    contract.dma_linked = 1U;
    contract.irq_registered = 0U;
    assert(peripheral_start(&contract, &state) == PERIPH_ERR_IRQ);
    assert(state.running == 0U);
}

static void test_dma_error_path(void)
{
    const peripheral_contract_t contract = {1U, 1U, 1U, 1U, 4U};
    peripheral_snapshot_t state;

    (void)memset(&state, 0, sizeof(state));
    assert(peripheral_start(&contract, &state) == PERIPH_OK);
    assert(peripheral_fake_request(&state, 1U) == PERIPH_ERR_DMA);
    assert(state.error_callbacks == 0U);
    peripheral_fake_irq(&state);
    assert(state.error_callbacks == 1U);
    assert(state.running == 0U);
}

int main(void)
{
    test_circular_completion_requires_irq_consumption();
    test_each_precondition();
    test_dma_error_path();
    return 0;
}
```

最小构建命令示例：

```text
cc -std=c11 -Wall -Wextra -Wpedantic -Werror host_crosswalk.c -o host_crosswalk
./host_crosswalk
```

课程正文不把这条主机构建命令列为 STM32 构建或硬件证据。即使断言全部通过，也只证明抽象前置条件、循环重装、显式停止和“flag 与 callback 是两个时刻”；它不证明 STM32 API、位布局、ADC 电气行为或真实 IRQ。主机检查是否执行以及结果如何，应以当次运行记录为准。

### 8.2 STM32 参考实现轨道

可由文档静态核对：RM0090 表 44 的 ADC1 -> DMA2 Stream0/Channel0 映射、F407 RCC/ADC/DMA 寄存器语义，UM1725 的 HAL/LL API 与回调契约，以及 DS8626 的器件工作条件边界。[S1][S2][S3]

仍需实际目标工程证明：

1. 完整 STM32F407 料号、封装、板卡原理图和合法 ADC 引脚；
2. CubeMX 与 STM32CubeF4 精确版本，生成 `.ioc` 和源码；
3. Arm 工具链版本、完整构建日志和 map 文件；
4. 烧录记录、调试器连接条件和固件标识；
5. RCC/ADC/DMA/NVIC 寄存器快照、缓冲区变化、回调计数和错误注入结果；
6. 模拟输入、参考电压、源阻抗与必要仪器记录。

缺少这些证据时保持 `hardware_verified=false`，但参考代码、配置和观察计划仍然完整保留。

## 9. 最小代码示例

最小可运行形态是 8.1 节的 Host Fake：四个前置条件全部满足才进入 running；半数请求时置 half flag，四次请求后置完成 flag 并按 circular 语义重装计数；只有 Fake IRQ 消费 flag 后才增加相应回调计数，停止则必须显式请求。这个分离正是交叉映射的最小价值。

将它映射到 F407：

| Fake 字段 | F407 对应证据 | 明确不等价之处 |
| --- | --- | --- |
| `clock_enabled` | `RCC_AHB1ENR.DMA2EN`、`RCC_APB2ENR.ADC1EN` 与时钟链 | Fake 没有 PLL、总线和 ADC 分频位布局 |
| `config_committed` | ADC/DMA 配置寄存器读回 | Fake 不验证字段编码与电气限制 |
| `dma_linked` | HAL 句柄双向关联 + DMA request mapping | 前者是软件关系，后者是芯片路由，必须分别核对 |
| `irq_registered` | stream IT enable + NVIC enable + 正确向量 | Fake 把多个关卡压成一个布尔值 |
| `remaining` / `reload_count` | `DMA_S0NDTR.NDT` 与 circular 自动重装 | Fake 每次函数调用等于一个请求，不模拟总线仲裁或重装时序 |
| `half_flag` / `half_callbacks` | `DMA_LISR.HTIF0` 与 `HAL_ADC_ConvHalfCpltCallback` | Fake 只表达 flag 先于回调，不模拟 IRQ 延迟 |
| `complete_flag` | `DMA_LISR.TCIF0` | 真硬件 flag 的清除规则由 RM0090 定义 |
| `completed_callbacks` | `HAL_ADC_ConvCpltCallback` 中事件计数 | 真回调还依赖 HAL 内部 callback 和句柄 parent |

## 10. 常见错误

1. **把 `HAL_OK` 写成“采样完成”**：它最多证明同步启动路径成功。
2. **强迫三层 API 一一同名**：HAL 可能一次覆盖多个硬件动作；`__HAL_LINKDMA` 甚至没有硬件等价物。
3. **认为 HAL 会调用公开 LL API**：HAL 和 LL 可以共享设备头文件，但不能据此虚构调用关系。
4. **只看配置寄存器，不看状态 flag**：配置正确仍可能没有触发或请求。
5. **只看 flag，不看 IRQ enable/NVIC/vector**：flag 已置位不保证 handler 运行。
6. **handler 传错句柄**：IRQ 进入了，但错误的 stream handle 无法沿正确 parent 分发。
7. **忘记 `__HAL_LINKDMA`**：DMA 可被配置，却没有与 ADC HAL 状态机正确关联。
8. **在 EN=1 时改 DMA 配置**：F407 DMA stream 大多数配置必须在 disabled 状态修改。[S1]
9. **把 DMA2 HCLK 当采样率**：请求节奏来自 ADC 时钟、采样/转换周期和触发。
10. **把 `Length` 当字节数**：它是按 DMA 配置宽度计数的数据项数。
11. **ISR 内打印或重初始化**：延长中断并破坏首个故障现场；ISR 只保存最小证据。
12. **用调试器改寄存器修 HAL**：软件句柄与硬件状态立即失配。
13. **复位整个 DMA2 恢复单个 stream**：会破坏其他 DMA2 使用者。
14. **复制 F407 stream/channel 到 H5/H7**：DMA 架构、请求器和时钟/内存边界不同。
15. **把 CubeMX 生成当硬件证据**：生成只证明工具产出，不证明编译、烧录、电气和事件链。

## 11. 调试观察点

按因果链由前向后记录，不要随机翻寄存器：

1. `RCC_CFGR.SWS`、AHB/APB 分频和软件计算频率：上游时钟是否成立；
2. `RCC_AHB1ENR.DMA2EN`、`RCC_APB2ENR.ADC1EN`：门控是否打开；
3. `RCC_AHB1RSTR.DMA2RST`、`RCC_APB2RSTR.ADCRST`：模块是否意外仍在复位；注意 `ADCRST` 同时影响 ADC1/2/3；
4. `ADC_CCR.ADCPRE`：参考方案是否为 PCLK2/4；
5. `hadc1.DMA_Handle` 与 `hdma_adc1.Parent`：软件关联是否双向一致；
6. `DMA_S0CR` 的 CHSEL/DIR/MINC/PSIZE/MSIZE/CIRC/IT/EN，及 `PAR/M0AR/NDTR`：传输契约是否提交；
7. `ADC_CR1/CR2`：分辨率、DMA/DDS、ADON、触发边沿/源和 SWSTART 是否符合预期；
8. `ADC_SR`：EOC/OVR 等 ADC 侧事件；
9. `DMA_LISR`：HTIF0/TCIF0/TEIF0/DMEIF0/FEIF0；记录 handler 前后和清除行为；
10. NVIC enable/pending/active 与 `DMA2_Stream0_IRQHandler` 断点：硬件 flag 是否越过中断控制器；
11. `HAL_DMA_IRQHandler` 入参地址与 `hdma_adc1` 地址：是否分发给正确对象；
12. 半/全/错误回调计数和 HAL ADC/DMA 错误码：HAL 到应用的最后一段是否成立；
13. 缓冲区每半区的代次/校验：回调存在不等于应用及时消费。

建议每次故障保存一个快照表，包含时间点、HAL 返回、句柄状态、RCC、ADC、DMA、NVIC 和应用事件计数。只保存最终值会丢失“哪个 flag 最先出现”的信息。

## 12. 实战实验

### 实验 A：Host Fake 最小闭环

1. 将 8.1 节保存为 `host_crosswalk.c`；
2. 使用本机 C11 编译器和严格警告选项构建；
3. 记录编译器版本、命令、退出码和输出；
4. 单步确认第二次 request 后 `half_flag=1`，Fake IRQ 消费后半传输回调计数增加；
5. 确认第四次 request 后 `complete_flag=1`、计数已重装但 `completed_callbacks=0`；调用 Fake IRQ 后确认 flag 清除、完成回调计数增加且仍处于运行态；
6. 调用显式停止接口，确认 `running` 和请求使能清零。

验收只可写“主机模型通过”，不能写成 STM32 硬件结果。

### 实验 B：逐项错误注入

依次把 clock、configuration、DMA link、IRQ registration 置为 0，记录返回码、`running` 和 callback 计数。再注入 DMA error，确认错误 flag 出现时应用错误计数仍为 0，经过 IRQ 分发后才变为 1 并停止循环请求。要求失败时不出现伪完成。

### 实验 C：建立一张新外设交叉表

从已学 UART 或 SPI 选一个“启动一次中断传输”操作，按 4.1 的七列建表。只引用对应 F407 第一方资料；至少找出一个“HAL 软件对象动作，没有直接寄存器等价物”的行和一个“一项硬件 flag，由 HAL handler 内部消费”的行。

### 实验 D：生成并静态审计 F407 工程

1. 选择实际完整料号和合法 ADC 引脚，记录 CubeMX/CubeMX2 与 STM32CubeF4 版本；
2. 按 7.3 配置时钟、ADC1、DMA2 Stream0/Channel0 和 NVIC；
3. 生成代码但先不烧录；
4. 对照本课交叉表，标注生成代码中每个 HAL 字段最终对应的寄存器/状态；
5. 核对 `HAL_Init -> SystemClock_Config -> MX_GPIO_Init -> MX_DMA_Init -> MX_ADC1_Init -> HAL_ADC_Start_DMA`；
6. 核对 `__HAL_LINKDMA`、向量 handler 和回调是否完整；
7. 保存静态审计记录。生成本身不提高硬件验证状态。

### 实验 E：目标构建与寄存器观察计划

在实际具备工具链和板卡后：

1. 保存完整构建日志、工具链版本、固件 hash 和 map 文件；
2. 烧录前记录板卡、调试器、供电、ADC 输入条件；
3. 在启动前、HAL 返回后、第一次 HT、第一次 TC 和错误回调各保存一次快照；
4. 对比 `NDTR`、LISR flag、NVIC pending、回调计数和缓冲区；
5. 分别禁用 stream IT 与 NVIC，验证“flag 有但回调无”的两个断点；
6. 恢复配置后再验证，禁止用直接改寄存器代替重新初始化。

这些步骤当前未执行。

### 实验 F：跨系列迁移审计

选择一个具体 F7、H5 或 H7 完整料号，使用对应 RM、数据手册和 Cube 包重填：时钟/复位、ADC kernel clock、DMA controller、request/DMAMUX、内存可达性、cache、安全属性、IRQ 名称、HAL/LL 字段和错误 flag。任何未查到的单元写“未核对”，不得复制 F407 结论。

## 13. 自检题

1. `HAL_ADC_Start_DMA` 返回 `HAL_OK` 能证明什么，不能证明什么？
2. 为什么 HAL、LL、寄存器不是三套独立硬件？
3. 一行合格的交叉映射应包含哪七类信息？
4. `__HAL_LINKDMA` 为什么没有寄存器等价物？谁持有关联后的对象？
5. 为什么 `DMA_S0CR.EN=1` 不能证明搬运发生？
6. `NDTR` 递减、`TCIF0` 置位、ADC 完成回调发生分别证明哪一层？
7. `TCIF0` 已出现但 handler 不运行，应先检查哪几个关卡？
8. handler 已运行却无 ADC 回调，应检查什么？
9. PCLK2=84 MHz、ADC 分频=/4 时 ADCCLK 是多少？为什么它不是采样率？
10. 初始化结构体可以是局部对象，而 `hadc1`/`hdma_adc1` 通常静态持有，原因是什么？
11. Host Fake 通过后仍缺哪些目标证据？
12. 迁移到 H7 时，为什么不能只替换 HAL 头文件？

参考要点：API 成功只覆盖同步软件路径；三个层是同一状态转换的不同表达/观察面；交叉表包含意图、前置、HAL、LL、硬件、证据、错误；link 宏连接软件对象；EN 只表示 armed；NDTR/flag/callback 依次证明搬运、硬件完成、IRQ/HAL 分发；时钟为 21 MHz但请求还受采样、转换和触发决定；句柄会被 IRQ 长期引用；目标还需版本、构建、烧录、寄存器与电气证据；H7 的时钟域、DMA/DMAMUX、内存、cache 和寄存器都要重建映射。

## 14. 面试题

1. 请解释“HAL 返回成功不等于硬件事件完成”，并给出 ADC-DMA 的五级证据。
2. 你如何从 `HAL_ADC_Start_DMA` 追到 DMA2 Stream0 的寄存器和完成回调？
3. 为什么读取寄存器验证 HAL 配置是合理的，而运行中用 LL 改同一外设通常危险？
4. DMA `TC` 已置位但应用没收到数据，你会按什么顺序排查？
5. `__HAL_LINKDMA` 做了什么？忘记它可能表现为何种故障？
6. 如何区分 ADC 没产生请求、DMA 请求映射错误、NVIC 未使能和 handler 传错句柄？
7. 为什么 F407 的 ADC1 Stream0/Channel0 结论不能直接迁移到 H5？
8. 在带 D-Cache 的 F7/H7 上，为什么 DMA 完成仍不一定意味着 CPU 读到新数据？交叉表需新增哪些责任？
9. 如何设计一份故障快照，使其既能定位首错，又不会让 ISR 本身制造时序问题？

## 15. 延伸思考

- 若 HAL 一次调用写十个寄存器，交叉表应按“API”还是按“操作意图”拆行？什么粒度最利于故障定位？
- 如果目标项目决定 ADC 使用 HAL、DMA 使用 LL，谁负责两边软件状态、停止顺序和错误恢复？是否值得承担这个组合边界？
- 寄存器快照是瞬间状态。对于写 1 清除、读后清除或高速变化的 flag，应如何使用 trace、事件计数或断点避免误读？
- 自动生成代码更新后，怎样用静态检查或单元测试发现句柄关联、IRQ handler 或配置字段被改坏？
- 在 Timer -> ADC -> DMA -> task 链路中，怎样给每一段定义时间戳和所有权证据，使延迟与丢样可定位？

## 16. 本节总结

HAL、LL 与寄存器交叉映射是一种追踪方法：从操作意图出发，逐项列出前置条件、软件对象/API、近位域动作、硬件配置/状态、成功证据和错误去向。它避免把 HAL、LL、寄存器误当成互不相关的知识，也避免把一次函数返回误写成整条硬件链路完成。

Host Fake 用静态 C11 对象验证了最小机制：时钟、配置、DMA 关联和 IRQ 路径缺一不可；circular 计数会重装并持续请求，正常停止必须显式发生；硬件完成 flag 与应用回调是两个时刻；错误也必须经过明确分发路径。它不模拟 STM32。

STM32F407xx 参考轨道把方法落实到 ADC1 -> DMA2 Stream0/Channel0：HSI/PLL/AHB/APB/ADC 分频建立运行时钟，RCC 分别控制 DMA2/ADC1 门控与复位，HAL 初始化结构体提交配置，句柄连接软件对象，ADC 请求驱动 DMA，DMA flag 经 NVIC、向量和 `HAL_DMA_IRQHandler` 进入 ADC 回调。当前未进行目标构建、烧录或测量，`hardware_verified=false` 保持不变。

## 17. 下一步

下一课 `timer-trigger-routing` 将把软件启动替换为 Timer TRGO，使用本课方法追踪“定时器事件 -> 内部触发路由 -> ADC 边沿选择 -> 转换事件”。随后 `advanced-control-timer` 深入互补输出、死区、刹车、重复计数和预装载；`adc-timer-dma-pipeline` 把触发、采样、DMA 和消费连成可测量流水线。调试阶段的 `register-view` 会把本课静态交叉表转为实时证据采集流程。

## 18. 参考资料

- [S1] STMicroelectronics，*STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 advanced Arm-based 32-bit MCUs - Reference manual*，RM0090 Rev 22（May 2026）。用于 RCC 门控/复位、ADC 公共与实例寄存器、DMA2 stream/channel、表 44 请求映射、flag 和配置限制；适用范围仅限手册列出的器件。<https://www.st.com/resource/en/reference_manual/dm00031020.pdf>，访问日期：2026-10-12。
- [S2] STMicroelectronics，*Description of STM32F4 HAL and low-layer drivers*，UM1725 Rev 8（March 2023）。用于 STM32F4 HAL/LL 的 ADC、DMA、RCC API、句柄关联、状态返回、IRQ handler 和回调契约；实际工程仍须与所用 STM32CubeF4 包头文件核对。<https://www.st.com/resource/en/user_manual/dm00105879.pdf>，访问日期：2026-10-12。
- [S3] STMicroelectronics，*STM32F405xx STM32F407xx datasheet*，DS8626 Rev 12（March 2026）。用于器件范围、时钟和 ADC 工作条件边界；本文没有据此假定封装、引脚、板级输入或物理测量结果。<https://www.st.com/resource/en/datasheet/stm32f407vg.pdf>，访问日期：2026-10-12。

三份资料均来自 `config/source-policy.toml` 允许的 `st.com` 第一方域名。F7、H5、H7 仅列出迁移时必须重查的类别；由于没有选择具体目标和对应第一方资料，本课不声称它们的具体寄存器、request ID、缓存维护 API 或安全配置。

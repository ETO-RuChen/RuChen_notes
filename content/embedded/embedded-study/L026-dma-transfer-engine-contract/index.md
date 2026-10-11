+++
title = "DMA 传输引擎与传输契约"
date = "2026-10-07T19:21:14+08:00"
lastmod = "2026-10-07T19:21:14+08:00"
summary = "以双轨方式建立 DMA 传输契约：Host Fake 验证请求、计数、循环缓冲区和错误路径；STM32F407xx 参考实现把 ADC1 请求落实到 DMA2 Stream0/Channel0，给出 168/84/21 MHz 时钟链、CubeMX 配置、HAL 初始化与回调、LL/寄存器对照和上板验证边界。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 26
tags = ["dma", "transfer-engine", "ownership", "peripheral-request", "circular-mode", "half-transfer", "host-fake", "stm32f407", "cubemx", "hal", "ll", "registers", "c11"]
source_ids = ["st-an4031", "st-rm0090-dma", "st-um1725"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L026"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 26 课：DMA 传输引擎与传输契约

DMA（Direct Memory Access，直接存储器访问）解决一个具体问题：当外设持续产生数据，或一块缓冲区需要搬到另一端时，CPU 不必为每一个传输单元都执行一次读、写和计数更新。CPU 先提交一份传输契约，DMA 再根据请求事件搬运数据，最后以半传输、全传输或错误状态把结果交还给软件。

本课只推进两个核心概念：

1. DMA 传输引擎：CPU 配置后由 DMA 根据外设请求在存储器与外设之间搬运数据，减少 CPU 逐项参与。
2. DMA 传输契约与所有权交接：源/目的端点、数据宽度、传输计数、触发与完成策略共同定义缓冲区何时可读写。

本课采用双轨：Host Fake（主机替身）验证请求驱动的逻辑流和缓冲区契约；STM32 参考轨道则以 `STM32F407xx` 为目标，把同一契约落实到 `ADC1 -> DMA2 Stream0/Channel0 -> 双半缓冲区 -> 中断回调`。后者包含时钟树、CubeMX 清单、HAL 代码、LL/寄存器对照和故障路径，不再把“没有开发板”当成省略硬件实现的理由。

这里没有指定开发板、封装、外部晶振、模拟信号源或调试器。参考时钟使用芯片内部 HSI，ADC 引脚仅以 `ADC1_IN0` 为示例并要求按所选封装核对；代码尚未放入具体 STM32CubeF4 工程编译，也未烧录、测量或上板，因此 `hardware_verified` 仍为 `false`。

## 1. 本节目标

完成本课后，你应能：

- 用“源端点、目的端点、传输宽度、计数、请求、模式、状态”描述一次 DMA 传输；
- 解释 CPU 配置、外设请求、DMA 搬运一个传输单元、计数递减和完成通知之间的调用流；
- 区分 memory-to-peripheral（存储器到外设）、peripheral-to-memory（外设到存储器）和 memory-to-memory（存储器到存储器）；
- 在固定数组的 Host Fake 中验证普通模式、循环模式、请求不足和错误路径；
- 说明缓冲区的所有权何时从应用交给 DMA，何时在半传输或全传输边界交还；
- 在 STM32F407xx 上解释 ADC1 请求如何进入 DMA2 Stream0/Channel0，能从 HAL 字段追到 LL API 和关键寄存器位；
- 按迁移表区分 F4 已核对事实与 F7/H5/H7 必须重新查证的请求映射、缓存和内存域问题。

核心目标与计划一致：将 DMA 理解为由外设请求驱动的独立数据搬运机制，并能用端点、触发、计数与完成状态描述一次传输，在 Host Fake 中验证正常/循环传输和错误观察路径。

## 2. 它解决什么问题

### 2.1 CPU 逐项搬运的边界

没有 DMA 时，接收一批 UART、SPI、I2C 或 ADC 数据通常要经历：

```text
外设产生一个数据就绪事件
  -> CPU 进入轮询或中断处理
  -> CPU 读取外设数据寄存器
  -> CPU 写入内存并递增软件索引
  -> CPU 再等待下一个数据
```

这条路径适合少量数据，但每个传输单元都消耗 CPU 时间，并增加中断抖动。DMA 把中间的读、写、地址递增和计数递减交给一个专门的传输引擎：

```text
CPU 提交契约
  -> 外设发出 request（请求）
  -> DMA 搬运一个 transfer unit（传输单元）
  -> 剩余计数递减
  -> 半传输/全传输/错误状态可观察
```

DMA 并不是“自动理解业务数据”的处理器。它只知道端点、宽度、地址递增规则、计数和触发条件；校验包格式、解析协议和处理业务仍由 CPU 或其他软件负责。

### 2.2 本课的边界

- Host Fake 只建模一个 DMA 通道/数据流对象；硬件参考轨道固定为 STM32F407xx 的 ADC1、DMA2 Stream0、Channel0，该映射来自 RM0090 Rev 22 表 44。[S2]
- 传输宽度只允许 `1/2/4` 字节，表示一次请求搬运多少字节；不模拟非对齐硬件行为。
- 源和目的都用固定容量字节数组表示；数组通过端点结构暴露，不能访问容量之外的地址。
- 请求事件一次最多搬运一个传输单元；没有请求就保持等待，不会凭空消耗计数。
- 普通模式完成后停止；循环模式完成一轮后把索引回到起点并继续等待下一轮请求。
- 半传输只作为可观察事件：当一轮计数完成一半时记录事件。真实硬件的标志清除和中断行为必须按目标系列核对。
- 硬件示例使用循环模式、16 位外设/内存宽度和 128 个样本的静态缓冲区。它不假定某块开发板可用，也不把参考代码写成已经编译或测量过的结果。

## 3. 必要前置知识

计划中的前置主题已经在 `config/learning-state.toml` 的 `completed` 中记录，包括指针、内存布局、UART、SPI、I2C 和 ADC。仍需从零确认以下最小知识：

1. **数组和边界**：数组有固定容量，合法索引是 `0` 到 `capacity - 1`；DMA 不能越界写入。
2. **结构体持有状态**：配置和运行状态可以放进一个静态结构体，由调用者分配并持有。
3. **事件与状态**：请求是“发生一次搬运机会”的事件，完成和错误是调用方可以读取的状态。

本课不要求掌握具体 STM32 型号的 DMA 命名，也不把某个 HAL 句柄字段当作通用标准。

## 4. 核心原理

### 4.1 DMA 传输引擎

DMA 传输引擎是一个独立于应用循环的搬运执行者。它在一次请求到来时只做一件事：按契约复制一个传输单元，然后更新位置和计数。

它解决的是“谁逐项搬运”的问题，而不是“数据代表什么”的问题。

在本课的 Host Fake 中：

- **定义位置**：`dma_fake_t` 定义在示例代码中，包含契约和运行状态；`dma_endpoint_t` 定义源/目的缓冲区。
- **持有者**：测试的 `main` 函数持有静态 `dma_fake_t` 和静态数组；Fake 不从堆上取得内存。
- **注入者**：测试调用 `dma_fake_init` 注入契约，调用 `fake_dma_step` 注入一个外设请求事件。
- **调用流**：`fake_dma_step` 检查请求和边界 -> 复制一个传输单元 -> 递减剩余计数 -> 记录半/全传输或错误事件。

### 4.2 传输契约与所有权交接

传输契约是“DMA 可以怎样访问缓冲区”的明确约定：

| 契约字段 | 回答的问题 | Host Fake 表示 |
| --- | --- | --- |
| 源端点 | 从哪里读？ | `buffer`、`capacity`、`offset` |
| 目的端点 | 写到哪里？ | `buffer`、`capacity`、`offset` |
| 数据宽度 | 一次请求搬多少字节？ | `width_bytes`，只能为 1、2、4 |
| 传输计数 | 还需要多少个传输单元？ | `remaining_units` |
| 请求 | 什么时候允许搬运？ | `fake_dma_step(request)` 的 `request=1` |
| 模式 | 完成后停止还是回卷？ | `DMA_MODE_NORMAL` / `DMA_MODE_CIRCULAR` |
| 完成策略 | 什么时候交还结果？ | 半传输、全传输事件 |

所有权交接指的是：在 DMA 运行期间，应用不能同时修改 DMA 可能读取或写入的区域。普通模式全传输事件之后，应用可以重新取得整个缓冲区；在循环模式中，应用通常只能消费已经由半传输或全传输边界确认的区域，另一半仍可能被 DMA 改写。这个规则是软件协议，不能只靠一个指针命名来保证。

### 4.3 三种方向

方向改变的是谁提供数据、谁接收数据，传输引擎的“请求 -> 复制一个单元 -> 更新计数”机制不变：

| 方向 | 典型数据流 | 应用交接重点 |
| --- | --- | --- |
| memory-to-peripheral | 内存中的发送缓冲区 -> 外设数据寄存器 | DMA 读取区在启动后不能被应用改写，直到对应完成边界 |
| peripheral-to-memory | 外设数据寄存器 -> 内存接收缓冲区 | 应用不能读取尚未由完成事件交还的区域 |
| memory-to-memory | 一块内存 -> 另一块内存 | 两端地址、宽度和重叠策略必须明确；本课不定义重叠复制语义 |

真实 STM32 中，外设数据寄存器是否允许某种宽度、请求来自哪个外设、地址是否递增，以及是否支持存储器到存储器，都要看具体参考手册。已核对的 AN4031 DocID022648 Rev 3（June 2016）可作为 F2/F4/F7 DMA 的概念入口；其封面和引言明确说明 F4 是示例，不能替代 H5/H7 目标器件的参考手册。[S1][S2]

## 5. 关键术语与直观模型

| 术语 | 直观含义 | 本课中的可观察形式 |
| --- | --- | --- |
| DMA | 直接存储器访问 | `dma_fake_t` 的一次请求搬运 |
| peripheral request | 外设请求 | `fake_dma_step(adc_request)` 中的 `1` |
| transfer unit | 传输单元 | `width_bytes` 个字节 |
| source/destination endpoint | 源/目的端点 | 缓冲区指针、容量和偏移 |
| transfer count | 传输计数 | `remaining_units` |
| normal mode | 普通模式 | 全传输后状态为完成，不再搬运 |
| circular mode | 循环模式 | 一轮完成后偏移回到起点，继续等待请求 |
| half-transfer | 半传输 | 一轮过半时记录 `DMA_EVT_HALF` |
| full-transfer | 全传输 | 一轮结束时记录 `DMA_EVT_FULL` |
| transfer error | 传输错误 | 宽度非法或容量不足，状态变为错误 |
| channel/stream | 通道/数据流 | STM32 系列相关术语，本课不指定实例 |
| buffer ownership | 缓冲区所有权 | 完成边界前后应用与 DMA 的读写责任 |
| request mapping | 请求映射 | 某外设请求连接到哪个 DMA 资源，待核对 |

## 6. 从输入到结果的完整流程

一次请求驱动的传输可以按以下步骤审计：

1. **声明**：接口文件声明端点、模式、状态和 `dma_fake_init`、`fake_dma_step`；调用方通过 `dma_fake_t.state`、`last_status` 与 `events` 观察结果。
2. **实现**：实现文件检查宽度、容量、请求值和当前状态；合法时复制一个传输单元。
3. **实例化**：测试函数定义固定数组和一个静态 DMA 对象。
4. **组装**：初始化者把源/目的数组、宽度、计数和模式写入 DMA 对象，形成传输契约。
5. **使用**：外设事件循环调用 `fake_dma_step(1)`；调用方读取状态和事件，在完成边界消费缓冲区。

调用流如下：

```text
应用/BSP 组装契约
  -> DMA 对象保存端点、宽度、计数和模式
  -> 外设产生 request
  -> fake_dma_step(request)
       -> 检查请求/状态/边界
       -> 复制一个 transfer unit
       -> 更新 offset 与 remaining_units
       -> 记录 HALF 或 FULL
  -> 应用读取状态并按所有权边界消费数据
```

这里的“组装”只是把已经存在的静态对象连接起来，不引入依赖注入框架、函数指针或动态内存。

## 7. 嵌入式系统中的对应位置

### 7.1 Host Fake 的层次和生命周期

- **接口层**：定义 `dma_endpoint_t`、`dma_config_t`、`dma_state_t` 和状态查询函数；它描述契约，不包含芯片寄存器。
- **实现层**：实现边界检查、单元复制、计数和事件；对象由调用者提供，生命周期由调用者决定。
- **实例层**：应用或测试定义 `uint8_t source[]`、`uint8_t destination[]` 和 `dma_fake_t dma`。
- **组装层**：BSP 或测试初始化者把端点和配置注入 `dma_fake_init`。
- **使用层**：外设事件处理代码调用 `fake_dma_step`，应用只消费完成边界交付的数据。

真实项目可能把接口放在驱动头文件、把 F4/F7/H5/H7 实现放在系列适配文件、把资源选择放在 BSP 组装代码。具体文件名和 HAL 句柄字段不是本课的通用结论。

### 7.2 DMA 能力地图

先看完整能力边界，再决定本课深入哪里：

| 层级 | STM32 DMA 能力 | 本课处理方式 |
| --- | --- | --- |
| 基础 | 外设到内存、内存到外设、内存到内存；字节/半字/字宽；地址递增；普通模式 | Host Fake 建模三种方向；F407 参考实现深入 ADC 外设到内存 |
| 进阶 | 循环模式、半传输/全传输中断、软件优先级、错误标志 | F407 双半缓冲区完整展开，包含回调和错误恢复入口 |
| 高级 | FIFO、FIFO 阈值、存储器/外设突发、双缓冲、外设流控制、仲裁 | 给出寄存器入口和适用问题；双缓冲、突发与吞吐测量留给后续实验 |
| 跨外设 | ADC 连续采样、UART/SPI 收发、定时器更新/捕获请求、Timer TRGO -> ADC -> DMA | 本课实现 ADC 连续请求；定时器触发路由和 ADC-Timer-DMA 流水线分别在后续主题深入 |
| 跨系列 | F4/F7 的 stream/channel、H5/H7 的请求选择和 DMA/内存架构差异 | 只把 RM0090 结论用于 F407；迁移时重新查目标系列手册，不复制编号 |

本课聚焦“请求、端点、计数、循环缓冲区所有权”两个核心概念。FIFO/突发解决总线效率，双缓冲解决连续流切换，优先级与仲裁解决多个请求竞争；这些高级能力不能只记名称，但也不在本课同时引入新的配置主线。

### 7.3 STM32F407 参考数据路径

参考目标为 `STM32F407xx`。为了让请求、搬运和所有权都能观察，选择单通道 ADC 连续转换作为请求源：

```text
ADC1_IN0（板级模拟输入，封装相关）
  -> ADC1 采样/转换
  -> ADC1_DR 保存 12 位右对齐结果
  -> ADC1 产生 DMA request
  -> DMA2 Stream0 / Channel0
       PAR  = &ADC1->DR             固定外设地址
       M0AR = adc_dma_samples       递增内存地址
       NDTR = 128                   128 个半字传输单元
  -> HTIF0：前 64 个样本交给应用
  -> TCIF0：后 64 个样本交给应用，循环模式自动重装 NDTR
  -> TEIF0/DMEIF0/FEIF0 或 ADC OVR：进入错误路径
```

RM0090 Rev 22 表 44 给出 ADC1 到 DMA2 Stream0/Channel0 的请求映射；`DMA_SxNDTR.NDT` 表示“数据项数量”而不是字节数，传输中每完成一项递减，循环模式结束时自动重装。[S2] 因此 `Length=128` 与半字宽组合表示 128 个 16 位样本，而不是 128 字节。

对象和所有权如下：

| 对象 | 定义位置 | 持有者 | 谁配置/使用 |
| --- | --- | --- | --- |
| `ADC_HandleTypeDef hadc1` | `main.c` 或 CubeMX 生成文件 | 应用/BSP 静态持有 | `MX_ADC1_Init` 配置，启动函数使用 |
| `DMA_HandleTypeDef hdma_adc1` | `stm32f4xx_hal_msp.c` 或 `main.c` | BSP 静态持有 | `HAL_ADC_MspInit` 初始化并通过 `__HAL_LINKDMA` 连接到 `hadc1` |
| `adc_dma_samples[128]` | 应用静态存储区 | 应用分配，运行时由 DMA 写 | 半/全完成回调只发布哪一半可读，应用不能提前消费 |
| 就绪与错误事件 | 应用模块静态变量 | ISR 写、主循环取走 | 临界区完成交接；回调中不做长时间处理 |

### 7.4 时钟树、外设时钟与复位链

DMA 没有像 ADC 那样单独可编程的内核分频器，但它仍依赖 RCC 给 AHB1 接口开门。以下使用不依赖外部晶振的 HSI 参考配置；它是可复现的参数集，不代表已经在某块板上验证：

```text
HSI = 16 MHz
  -> PLLM = 16：PLL 输入 = 16 / 16 = 1 MHz
  -> PLLN = 336：VCO = 1 * 336 = 336 MHz
  -> PLLP = 2：SYSCLK = 336 / 2 = 168 MHz
  -> AHB HPRE = 1：HCLK/AHB1 = 168 MHz
       -> RCC_AHB1ENR.DMA2EN = 1：DMA2 AHB1 接口可工作
  -> APB2 PPRE2 = 2：PCLK2 = 84 MHz
       -> RCC_APB2ENR.ADC1EN = 1：ADC1 接口时钟开启
       -> ADC prescaler = 4：ADC clock = 84 / 4 = 21 MHz
```

`ADC_CLOCK_SYNC_PCLK_DIV4` 把 ADC 时钟选择写入 ADC 公共配置，`ADC_SAMPLETIME_84CYCLES` 决定输入采样阶段的周期数。DMA 的服务节奏最终由 ADC 产生请求的速度限制，不应把 168 MHz HCLK 直接当成采样率。实际转换时间还要结合分辨率固定转换周期、采样周期和模拟源阻抗按 RM0090 ADC 章节计算。

时钟和复位要按下面顺序审计：

1. `HAL_RCC_OscConfig` 建立 HSI -> PLL，`HAL_RCC_ClockConfig` 设置 SYSCLK、HPRE、PPRE1、PPRE2。
2. `__HAL_RCC_DMA2_CLK_ENABLE()` 对应 `RCC_AHB1ENR.DMA2EN`（bit 22）；未开门时写 DMA 寄存器和请求传输都不能按预期工作。[S2]
3. `__HAL_RCC_ADC1_CLK_ENABLE()` 打开 ADC1 的 APB2 接口时钟，ADC 公共预分频再从 PCLK2 得到 21 MHz。
4. `RCC_AHB1RSTR.DMA2RST`（bit 22）可以复位 DMA2，`RCC_APB2RSTR.ADCRST` 可以复位 ADC 模块。复位会影响同一控制器的其他用户，只能在确认所有相关 stream/ADC 都已停机后用于恢复。
5. 先开 DMA2 时钟并配置 stream/NVIC，再初始化并启动 ADC；停止时先停 ADC DMA 请求，再按所有权规则回收缓冲区。

### 7.5 CubeMX 配置清单

参考选择 `STM32F407VGTx` 裸芯片工程，不绑定开发板。若所用封装不是 LQFP100，必须重新核对 ADC1_IN0 是否引出；模拟输入电压和源阻抗也必须符合所选器件数据手册。

1. **System Core / RCC**：使用 HSI，不启用 HSE；Debug 选择 Serial Wire。
2. **Clock Configuration**：PLL Source=HSI，PLLM=16、PLLN=336、PLLP=2、PLLQ=7；AHB=/1、APB1=/4、APB2=/2，得到 SYSCLK/HCLK=168 MHz、PCLK1=42 MHz、PCLK2=84 MHz。
3. **ADC1**：选择 IN0；Resolution=12 bits、Data Alignment=Right、Scan Conversion=Disabled、Continuous Conversion=Enabled、DMA Continuous Requests=Enabled、EOC Selection=Single Conversion、External Trigger Edge=None/Software Start、Regular Rank 1、Sampling Time=84 cycles。
4. **GPIO**：若使用 `PA0/ADC1_IN0`，模式为 Analog、No pull；换封装或换通道时同步修改 `ADC_CHANNEL_x` 和引脚。
5. **ADC1 / DMA Settings**：Add ADC1，DMA2 Stream0、Channel0、Peripheral to Memory、Circular、Peripheral Increment Disabled、Memory Increment Enabled、Peripheral/Memory Data Width=Half Word、Priority=High、FIFO Disabled。
6. **NVIC**：启用 `DMA2 Stream0 global interrupt`；若要通过 HAL 捕获 ADC overrun，同时启用共享 `ADC global interrupt`。中断优先级按整个应用统一规划，示例值 `5` 不是通用最优值。
7. **Project Manager**：记录实际 STM32CubeMX 与 STM32CubeF4 包版本，再生成代码。本文 API 边界按 UM1725 Rev 8（March 2023）核对，但没有声明与任意未来包版本逐行相同。[S3]
8. **生成后审计**：确认调用顺序为 `HAL_Init -> SystemClock_Config -> MX_GPIO_Init -> MX_DMA_Init -> MX_ADC1_Init -> HAL_ADC_Start_DMA`，并检查 `__HAL_LINKDMA(hadc, DMA_Handle, hdma_adc1)` 没有丢失。

### 7.6 HAL 调用流和错误路径

UM1725 Rev 8 明确说明：`HAL_DMA_Init` 配置方向、数据格式、普通/循环或外设流控、优先级、递增、FIFO 和突发；中断模式由 NVIC、`HAL_DMA_Start_IT` 和 DMA IRQ 中的 `HAL_DMA_IRQHandler` 组成。ADC 侧的 `HAL_ADC_Start_DMA(hadc, pData, Length)` 启用 ADC DMA 请求与 ADC，半传输、全传输和错误分别进入 `HAL_ADC_ConvHalfCpltCallback`、`HAL_ADC_ConvCpltCallback`、`HAL_ADC_ErrorCallback`。[S3]

```text
main
  -> HAL_Init
  -> SystemClock_Config
  -> MX_DMA_Init                     开 DMA2 时钟和 DMA2_Stream0_IRQn
  -> MX_ADC1_Init
       -> HAL_ADC_Init
            -> HAL_ADC_MspInit
                 -> GPIO/ADC1 时钟
                 -> HAL_DMA_Init(&hdma_adc1)
                 -> __HAL_LINKDMA(&hadc1, DMA_Handle, hdma_adc1)
  -> HAL_ADC_Start_DMA(&hadc1, buffer, 128)
       -> 配置 PAR/M0AR/NDTR 与中断回调
       -> 使能 DMA stream、ADC DMA request 和 ADC

DMA2_Stream0_IRQHandler
  -> HAL_DMA_IRQHandler(&hdma_adc1)
       -> HT：HAL_ADC_ConvHalfCpltCallback
       -> TC：HAL_ADC_ConvCpltCallback
       -> TE/DME/FE：ADC/DMA 错误状态与 HAL_ADC_ErrorCallback

ADC_IRQHandler
  -> HAL_ADC_IRQHandler(&hadc1)
       -> OVR 等 ADC 错误：HAL_ADC_ErrorCallback
```

错误回调只记录 `HAL_ADC_GetError`、`HAL_DMA_GetError` 和“需要恢复”事件；不要在 ISR 中打印、重新初始化整个系统或处理 64 个样本。主循环取得事件后执行 `HAL_ADC_Stop_DMA`，保存诊断快照，确认缓冲区不再被写，再决定清错并重新启动。UM1725 特别指出：DMA 场景发生 ADC overrun 时可用 `HAL_ADC_Stop_DMA()` 重新初始化 DMA，随后按需再次调用 `HAL_ADC_Start_DMA()`；重启前必须先找到处理不及时、总线竞争或配置错误等根因。[S3]

### 7.7 HAL、LL 与关键寄存器对照

下表的寄存器语义来自 RM0090 Rev 22，LL API 名称来自 UM1725 Rev 8。[S2][S3]

| 传输契约 | HAL 配置/API | LL 观察或配置入口 | STM32F407 关键位/寄存器 |
| --- | --- | --- | --- |
| 请求映射 | `hdma_adc1.Instance=DMA2_Stream0`、`Channel=DMA_CHANNEL_0` | `LL_DMA_SetChannelSelection(DMA2, LL_DMA_STREAM_0, LL_DMA_CHANNEL_0)` | `DMA_S0CR.CHSEL=000`；RM0090 表 44 的 ADC1 映射 |
| 方向 | `DMA_PERIPH_TO_MEMORY` | `LL_DMA_SetDataTransferDirection` | `DMA_S0CR.DIR=00` |
| 端点地址 | `HAL_ADC_Start_DMA(..., buffer, 128)` | `LL_DMA_SetPeriphAddress`、`LL_DMA_SetMemoryAddress` | `DMA_S0PAR=&ADC1->DR`、`DMA_S0M0AR=buffer` |
| 传输数量 | `Length=128` | `LL_DMA_SetDataLength` / `LL_DMA_GetDataLength` | `DMA_S0NDTR.NDT=128`，每项完成后递减 |
| 宽度 | `PDATAALIGN_HALFWORD`、`MDATAALIGN_HALFWORD` | `LL_DMA_SetPeriphSize`、`LL_DMA_SetMemorySize` | `PSIZE=01`、`MSIZE=01` |
| 地址递增 | `PINC_DISABLE`、`MINC_ENABLE` | `LL_DMA_SetPeriphIncMode`、`LL_DMA_SetMemoryIncMode` | `PINC=0`、`MINC=1` |
| 循环与优先级 | `DMA_CIRCULAR`、`DMA_PRIORITY_HIGH` | `LL_DMA_SetMode`、`LL_DMA_SetStreamPriorityLevel` | `CIRC=1`、`PL=10` |
| 直接/FIFO 模式 | `DMA_FIFOMODE_DISABLE` | `LL_DMA_DisableFifoMode` | `DMA_S0FCR.DMDIS=0`，即 direct mode |
| 启动 | `HAL_ADC_Start_DMA` | `LL_DMA_EnableStream` | 清旧标志后设置 `DMA_S0CR.EN=1`；EN=1 时多数配置位禁止改写 |
| 半/全/错误中断 | HAL DMA IRQ 与 ADC 回调 | `LL_DMA_EnableIT_HT/TC/TE/DME` 及 flag API | `HTIE/TCIE/TEIE/DMEIE`；`DMA_LISR.HTIF0/TCIF0/TEIF0/DMEIF0/FEIF0` |
| 清除标志 | `HAL_DMA_IRQHandler` 内部处理 | 对应 `LL_DMA_ClearFlag_*` | 向 `DMA_LIFCR.CHTIF0/CTCIF0/CTEIF0/CDMEIF0/CFEIF0` 写 1 |
| 双缓冲扩展 | HAL DMAEx 扩展 API | `M0AR/M1AR` 与 current target API | `DBM`、`CT`、`M0AR`、`M1AR`；本课主线不启用 |

这张表用来理解 HAL 背后的硬件，不允许在 HAL 正持有 stream 时再用 LL 偷改同一组配置。选择 HAL 就让 `DMA_HandleTypeDef` 及其状态机拥有 stream；选择 LL/寄存器实现则由驱动自己负责停流、清标志、顺序和错误恢复，不能让两个所有者同时配置。

### 7.8 F4、F7、H5、H7 迁移边界

| 迁移项 | F407 本课已核对 | 换系列时必须重新核对 |
| --- | --- | --- |
| 请求编号 | ADC1 -> DMA2 Stream0/Channel0 | 目标器件请求表、stream/channel 或 request ID/选择器命名 |
| 时钟/复位 | AHB1 的 DMA2EN/DMA2RST，APB2 的 ADC 时钟/复位 | DMA/ADC 所在总线、独立内核时钟、复位域与低功耗门控 |
| 缓存 | F407 Cortex-M4 无数据缓存，本例无需 D-cache 维护 | F7/H7 的 D-cache、MPU 属性、clean/invalidate 顺序与 cache line 对齐；必须按目标手册和应用笔记设计 |
| 可访问内存 | 本例要求缓冲区放在 DMA2 可访问的普通 SRAM | H7 等器件的内存域、TCM、总线矩阵、DMA 主设备可达性 |
| 安全属性 | 本课无 TrustZone 配置 | H5 的安全/非安全属性、特权和请求路由 |
| HAL/LL 字段 | UM1725 Rev 8 的 STM32F4 API | 对应系列 Cube 包、驱动头文件和版本迁移说明 |

AN4031 Rev 3 覆盖 F2/F4/F7 并以 F4 为示例，可帮助理解 stream、channel、FIFO、仲裁和双缓冲，但不能替代具体目标器件的请求表。[S1] RM0090 只约束其首页列出的 F405/407/415/417/427/437/429/439 器件；本文不把 F407 的编号或无缓存结论直接外推到 H5/H7。[S2]

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 能证明什么

- 每个 `request=1` 最多搬运一个传输单元；`request=0` 不改变缓冲区和计数；
- 普通模式在全传输后停止，循环模式回卷到一轮起点；
- 半传输和全传输事件出现在定义的计数边界；
- 非法宽度、源/目的容量不足、空端点和错误状态会被报告；
- 应用在完成边界前不应消费 DMA 尚未交还的区域。

### 8.2 Host Fake 不能证明什么

- 某个 STM32 的实际 DMA 实例、通道、数据流或请求选择器编号；
- 外设数据寄存器是否能按 1、2、4 字节访问；
- 总线仲裁、优先级、吞吐量、突发访问或真实时序；
- D-cache/MPU/内存域带来的缓存一致性行为；
- 具体寄存器标志清除顺序和 HAL API 返回值。

因此本课把可核对的 F407 参考实例、时钟和寄存器字段写清楚，但不会把这些内容冒充目标板结果。板级电源、封装引脚、模拟前端、实际 Cube 包版本、编译器输出、波形和采样数据仍须由真实工程补证。

### 8.3 STM32 参考实现的验证边界

当前可以由文档静态核对的内容包括 ADC1 的 DMA2 Stream0/Channel0 映射、RCC 门控/复位位、DMA 配置字段、NDTR 计数语义、状态/清除标志和 HAL/LL API 名称。以下证据尚不存在，所以不能把 `hardware_verified` 改成 `true`：

1. 所选 `STM32F407xx` 完整订货号、封装、板卡原理图和 ADC1_IN0 接线；
2. STM32CubeMX、STM32CubeF4、编译器和链接脚本的确切版本；
3. 参考代码在目标工程的零错误构建日志和 `.map` 中的缓冲区位置；
4. 烧录记录、DMA2 Stream0 寄存器快照、HT/TC/错误计数与 ADC 波形；
5. 用信号源或稳定电压输入得到的 128 点数据，以及半缓冲区处理能在下一次覆盖前完成的时序证据。

完成上述项目后，才能证明的不只是“代码看起来像 HAL”，而是具体板卡上的时钟、请求、数据宽度、缓冲区可达性和中断闭环都成立。

## 9. 最小代码示例

### 9.1 Host Fake 轨道

下面代码是 C11 子集的 Host Fake。它使用静态对象和固定数组，不含动态内存、函数指针、STM32 头文件或 HAL 调用。`fake_dma_step(request)` 模拟一次外设请求事件。

```c
#include <assert.h>
#include <stddef.h>
#include <stdint.h>

#define DMA_ENDPOINT_CAPACITY 16U
#define DMA_EVENT_CAPACITY 32U

typedef uint8_t dma_status_t;
#define DMA_OK ((dma_status_t)0U)
#define DMA_ERR_BAD_CONFIG ((dma_status_t)1U)
#define DMA_ERR_BAD_REQUEST ((dma_status_t)2U)
#define DMA_ERR_BOUNDS ((dma_status_t)3U)
#define DMA_ERR_STOPPED ((dma_status_t)4U)

typedef uint8_t dma_mode_t;
#define DMA_MODE_NORMAL ((dma_mode_t)0U)
#define DMA_MODE_CIRCULAR ((dma_mode_t)1U)

typedef uint8_t dma_state_t;
#define DMA_STATE_READY ((dma_state_t)0U)
#define DMA_STATE_RUNNING ((dma_state_t)1U)
#define DMA_STATE_COMPLETE ((dma_state_t)2U)
#define DMA_STATE_ERROR ((dma_state_t)3U)

typedef uint8_t dma_event_t;
#define DMA_EVT_TRANSFER ((dma_event_t)0U)
#define DMA_EVT_HALF ((dma_event_t)1U)
#define DMA_EVT_FULL ((dma_event_t)2U)
#define DMA_EVT_WAIT ((dma_event_t)3U)
#define DMA_EVT_ERROR ((dma_event_t)4U)

typedef struct {
    uint8_t *buffer;
    uint32_t capacity;
    uint32_t offset;
} dma_endpoint_t;

typedef struct {
    dma_endpoint_t source;
    dma_endpoint_t destination;
    uint32_t width_bytes;
    uint32_t transfer_units;
    dma_mode_t mode;
} dma_config_t;

typedef struct {
    dma_config_t config;
    uint32_t remaining_units;
    uint32_t completed_units;
    dma_state_t state;
    dma_status_t last_status;
    dma_event_t events[DMA_EVENT_CAPACITY];
    uint32_t event_count;
} dma_fake_t;

static void dma_log(dma_fake_t *dma, dma_event_t event)
{
    if (dma->event_count < DMA_EVENT_CAPACITY) {
        dma->events[dma->event_count] = event;
        dma->event_count += 1U;
    }
}

static uint8_t dma_width_is_valid(uint32_t width_bytes)
{
    return (uint8_t)(width_bytes == 1U || width_bytes == 2U || width_bytes == 4U);
}

static uint8_t dma_endpoint_can_transfer(const dma_endpoint_t *endpoint,
                                         uint32_t offset,
                                         uint32_t width_bytes)
{
    if (endpoint == NULL || endpoint->buffer == NULL) {
        return 0U;
    }
    if (offset > endpoint->capacity || width_bytes > endpoint->capacity - offset) {
        return 0U;
    }
    return 1U;
}

static dma_status_t dma_config_is_valid(const dma_config_t *config)
{
    if (config == NULL || config->source.buffer == NULL ||
        config->destination.buffer == NULL) {
        return DMA_ERR_BAD_CONFIG;
    }
    if (dma_width_is_valid(config->width_bytes) == 0U ||
        config->transfer_units == 0U ||
        (config->mode != DMA_MODE_NORMAL && config->mode != DMA_MODE_CIRCULAR)) {
        return DMA_ERR_BAD_CONFIG;
    }
    if (config->source.offset > config->source.capacity ||
        config->destination.offset > config->destination.capacity) {
        return DMA_ERR_BAD_CONFIG;
    }
    if (config->transfer_units >
            (config->source.capacity - config->source.offset) / config->width_bytes ||
        config->transfer_units >
            (config->destination.capacity - config->destination.offset) / config->width_bytes) {
        return DMA_ERR_BOUNDS;
    }
    return DMA_OK;
}

dma_status_t dma_fake_init(dma_fake_t *dma, const dma_config_t *config)
{
    dma_status_t status;

    if (dma == NULL) {
        return DMA_ERR_BAD_CONFIG;
    }
    status = dma_config_is_valid(config);
    if (status != DMA_OK) {
        dma->state = DMA_STATE_ERROR;
        dma->last_status = status;
        return status;
    }
    dma->config = *config;
    dma->remaining_units = config->transfer_units;
    dma->completed_units = 0U;
    dma->state = DMA_STATE_RUNNING;
    dma->last_status = DMA_OK;
    dma->event_count = 0U;
    return DMA_OK;
}

dma_status_t fake_dma_step(dma_fake_t *dma, uint8_t request)
{
    uint32_t width_bytes;
    uint32_t source_offset;
    uint32_t destination_offset;

    if (dma == NULL) {
        return DMA_ERR_BAD_CONFIG;
    }
    if (request == 0U) {
        dma_log(dma, DMA_EVT_WAIT);
        return DMA_OK;
    }
    if (request != 1U) {
        dma->state = DMA_STATE_ERROR;
        dma->last_status = DMA_ERR_BAD_REQUEST;
        dma_log(dma, DMA_EVT_ERROR);
        return DMA_ERR_BAD_REQUEST;
    }
    if (dma->state == DMA_STATE_COMPLETE) {
        dma->last_status = DMA_ERR_STOPPED;
        dma_log(dma, DMA_EVT_ERROR);
        return DMA_ERR_STOPPED;
    }
    if (dma->state != DMA_STATE_RUNNING) {
        dma->last_status = DMA_ERR_BAD_CONFIG;
        dma_log(dma, DMA_EVT_ERROR);
        return DMA_ERR_BAD_CONFIG;
    }

    width_bytes = dma->config.width_bytes;
    source_offset = dma->config.source.offset;
    destination_offset = dma->config.destination.offset;
    if (dma_endpoint_can_transfer(&dma->config.source, source_offset, width_bytes) == 0U ||
        dma_endpoint_can_transfer(&dma->config.destination, destination_offset, width_bytes) == 0U) {
        dma->state = DMA_STATE_ERROR;
        dma->last_status = DMA_ERR_BOUNDS;
        dma_log(dma, DMA_EVT_ERROR);
        return DMA_ERR_BOUNDS;
    }

    for (uint32_t i = 0U; i < width_bytes; ++i) {
        dma->config.destination.buffer[destination_offset + i] =
            dma->config.source.buffer[source_offset + i];
    }
    dma->config.source.offset += width_bytes;
    dma->config.destination.offset += width_bytes;
    dma->remaining_units -= 1U;
    dma->completed_units += 1U;
    dma_log(dma, DMA_EVT_TRANSFER);

    if (dma->completed_units * 2U == dma->config.transfer_units) {
        dma_log(dma, DMA_EVT_HALF);
    }
    if (dma->remaining_units == 0U) {
        dma_log(dma, DMA_EVT_FULL);
        if (dma->config.mode == DMA_MODE_CIRCULAR) {
            dma->config.source.offset -= dma->config.transfer_units * width_bytes;
            dma->config.destination.offset -= dma->config.transfer_units * width_bytes;
            dma->remaining_units = dma->config.transfer_units;
            dma->completed_units = 0U;
        } else {
            dma->state = DMA_STATE_COMPLETE;
        }
    }
    return DMA_OK;
}

static void assert_event(const dma_fake_t *dma, uint32_t index, dma_event_t event)
{
    assert(index < dma->event_count);
    assert(dma->events[index] == event);
}

static void test_normal_mode(void)
{
    uint8_t source[DMA_ENDPOINT_CAPACITY] = { 10U, 11U, 12U, 13U };
    uint8_t destination[DMA_ENDPOINT_CAPACITY] = { 0U };
    dma_fake_t dma;
    dma_config_t config = {
        { source, DMA_ENDPOINT_CAPACITY, 0U },
        { destination, DMA_ENDPOINT_CAPACITY, 0U },
        1U, 4U, DMA_MODE_NORMAL
    };

    assert(dma_fake_init(&dma, &config) == DMA_OK);
    assert(fake_dma_step(&dma, 0U) == DMA_OK);
    assert(destination[0] == 0U);
    assert(fake_dma_step(&dma, 1U) == DMA_OK);
    assert(fake_dma_step(&dma, 1U) == DMA_OK);
    assert(fake_dma_step(&dma, 1U) == DMA_OK);
    assert(fake_dma_step(&dma, 1U) == DMA_OK);
    assert(dma.state == DMA_STATE_COMPLETE);
    assert(destination[0] == 10U && destination[3] == 13U);
    assert_event(&dma, 0U, DMA_EVT_WAIT);
    assert_event(&dma, 1U, DMA_EVT_TRANSFER);
    assert_event(&dma, 3U, DMA_EVT_HALF);
    assert_event(&dma, 6U, DMA_EVT_FULL);
    assert(fake_dma_step(&dma, 1U) == DMA_ERR_STOPPED);
}

static void test_circular_mode(void)
{
    uint8_t source[DMA_ENDPOINT_CAPACITY] = { 1U, 2U, 3U, 4U };
    uint8_t destination[DMA_ENDPOINT_CAPACITY] = { 0U };
    dma_fake_t dma;
    dma_config_t config = {
        { source, DMA_ENDPOINT_CAPACITY, 0U },
        { destination, DMA_ENDPOINT_CAPACITY, 0U },
        1U, 4U, DMA_MODE_CIRCULAR
    };

    assert(dma_fake_init(&dma, &config) == DMA_OK);
    for (uint32_t i = 0U; i < 8U; ++i) {
        assert(fake_dma_step(&dma, 1U) == DMA_OK);
    }
    assert(dma.state == DMA_STATE_RUNNING);
    assert(dma.remaining_units == 4U);
    assert(destination[0] == 1U && destination[3] == 4U);
}

static void test_error_paths(void)
{
    uint8_t source[DMA_ENDPOINT_CAPACITY] = { 1U, 2U };
    uint8_t destination[DMA_ENDPOINT_CAPACITY] = { 0U };
    dma_fake_t dma;
    dma_config_t bad_width = {
        { source, DMA_ENDPOINT_CAPACITY, 0U },
        { destination, DMA_ENDPOINT_CAPACITY, 0U },
        3U, 1U, DMA_MODE_NORMAL
    };
    dma_config_t bad_bounds = {
        { source, 1U, 0U },
        { destination, DMA_ENDPOINT_CAPACITY, 0U },
        2U, 1U, DMA_MODE_NORMAL
    };

    assert(dma_fake_init(&dma, &bad_width) == DMA_ERR_BAD_CONFIG);
    assert(dma_fake_init(&dma, &bad_bounds) == DMA_ERR_BOUNDS);
    {
        dma_config_t valid = {
            { source, DMA_ENDPOINT_CAPACITY, 0U },
            { destination, DMA_ENDPOINT_CAPACITY, 0U },
            1U, 2U, DMA_MODE_NORMAL
        };
        assert(dma_fake_init(&dma, &valid) == DMA_OK);
        assert(fake_dma_step(&dma, 1U) == DMA_OK);
        dma.config.destination.capacity = 1U;
        assert(fake_dma_step(&dma, 1U) == DMA_ERR_BOUNDS);
    }
    assert(fake_dma_step(&dma, 2U) == DMA_ERR_BAD_REQUEST);
}

int main(void)
{
    test_normal_mode();
    test_circular_mode();
    test_error_paths();
    return 0;
}
```

代码中的 `for` 循环只复制一个已经通过边界检查的传输单元；它不是在一次请求中清空整个缓冲区。`request=0` 只记录等待，`request=1` 才允许一次搬运，其他值进入错误状态。

这里把 `request=0` 定义为幂等的“没有搬运机会”：即使对象已经处于完成或错误状态，也只记录等待而不改变状态；终态下再次提交真正的 `request=1` 才会得到停止或错误返回。这个语义属于 Host Fake 的显式状态机约定，不代表所有 STM32 DMA 外设的硬件行为。

#### Host Fake 预期逻辑结果

| 场景 | 关键观察 |
| --- | --- |
| 普通模式，4 个 1 字节请求 | 目的数组得到 `10,11,12,13`，状态为完成，再请求返回停止错误 |
| 请求不足 | 未发生请求的时刻目的数组和剩余计数不变 |
| 循环模式，8 个请求 | 两轮复制完成，状态仍运行，剩余计数回到 4 |
| 宽度为 3 | 初始化拒绝，不能悄悄按字节猜测 |
| 源容量 1、宽度 2 | 初始化报告越界，目的数组不被部分写入 |
| 请求值为 2 | 报告非法请求，状态进入错误 |

这些是从代码推导出的逻辑预期，不是本次运行的构建或硬件证据。

### 9.2 STM32F407 HAL 参考实现轨道

以下代码面向 STM32F407xx，API 以 UM1725 Rev 8 为边界，假定 CubeMX 选择 ADC1_IN0、DMA2 Stream0/Channel0 和循环模式。它是“待放入目标工程编译”的参考实现，不是本次运行产生的构建证据。`Error_Handler()`、链接脚本和启动文件由实际 CubeMX 工程提供。

#### 9.2.1 时钟树代码

```c
static void SystemClock_Config(void)
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

这段代码得到 HCLK=168 MHz、PCLK1=42 MHz、PCLK2=84 MHz；ADC 初始化再除以 4 得到 21 MHz。更换电源电压、器件速度等级或温度范围时，必须重新核对数据手册中的最大频率、Flash latency 和电压缩放要求，不能只复制 PLL 数字。

#### 9.2.2 DMA、ADC 和 MSP 初始化

```c
#include "main.h"

#define ADC_DMA_SAMPLE_COUNT 128U
#define ADC_DMA_HALF_COUNT   (ADC_DMA_SAMPLE_COUNT / 2U)

ADC_HandleTypeDef hadc1;
DMA_HandleTypeDef hdma_adc1;

_Alignas(uint32_t)
static uint16_t g_adc_dma_samples[ADC_DMA_SAMPLE_COUNT];

static void MX_DMA_Init(void)
{
    __HAL_RCC_DMA2_CLK_ENABLE();

    HAL_NVIC_SetPriority(DMA2_Stream0_IRQn, 5U, 0U);
    HAL_NVIC_EnableIRQ(DMA2_Stream0_IRQn);
}

void HAL_ADC_MspInit(ADC_HandleTypeDef *hadc)
{
    GPIO_InitTypeDef gpio = {0};

    if (hadc->Instance != ADC1) {
        return;
    }

    __HAL_RCC_ADC1_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();

    gpio.Pin = GPIO_PIN_0;
    gpio.Mode = GPIO_MODE_ANALOG;
    gpio.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOA, &gpio);

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

static void MX_ADC1_Init(void)
{
    ADC_ChannelConfTypeDef channel = {0};

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
    if (HAL_ADC_Init(&hadc1) != HAL_OK) {
        Error_Handler();
    }

    channel.Channel = ADC_CHANNEL_0;
    channel.Rank = 1U;
    channel.SamplingTime = ADC_SAMPLETIME_84CYCLES;
    if (HAL_ADC_ConfigChannel(&hadc1, &channel) != HAL_OK) {
        Error_Handler();
    }
}
```

`g_adc_dma_samples` 必须是静态生命周期，不能指向启动函数返回后失效的栈。`_Alignas(uint32_t)` 满足 HAL API 的 `uint32_t *pData` 入口对齐，实际 DMA 宽度仍由 `PSIZE/MSIZE=half-word` 决定。若链接脚本把该数组放到特殊内存，必须再确认 DMA2 可访问该区域。

#### 9.2.3 启动、IRQ、回调和缓冲区交接

```c
#define ADC_DMA_EVT_FIRST_HALF  (1UL << 0)
#define ADC_DMA_EVT_SECOND_HALF (1UL << 1)
#define ADC_DMA_EVT_ERROR       (1UL << 2)

static volatile uint32_t g_adc_dma_events;
static volatile uint32_t g_adc_error_code;
static volatile uint32_t g_dma_error_code;

static HAL_StatusTypeDef adc_dma_start(void)
{
    g_adc_dma_events = 0U;
    g_adc_error_code = HAL_ADC_ERROR_NONE;
    g_dma_error_code = HAL_DMA_ERROR_NONE;

    return HAL_ADC_Start_DMA(&hadc1,
                             (uint32_t *)g_adc_dma_samples,
                             ADC_DMA_SAMPLE_COUNT);
}

void DMA2_Stream0_IRQHandler(void)
{
    HAL_DMA_IRQHandler(&hdma_adc1);
}

void ADC_IRQHandler(void)
{
    HAL_ADC_IRQHandler(&hadc1);
}

void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1) {
        g_adc_dma_events |= ADC_DMA_EVT_FIRST_HALF;
    }
}

void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1) {
        g_adc_dma_events |= ADC_DMA_EVT_SECOND_HALF;
    }
}

void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1) {
        g_adc_error_code = HAL_ADC_GetError(hadc);
        if (hadc->DMA_Handle != NULL) {
            g_dma_error_code = HAL_DMA_GetError(hadc->DMA_Handle);
        }
        g_adc_dma_events |= ADC_DMA_EVT_ERROR;
    }
}

static uint32_t adc_dma_take_events(void)
{
    uint32_t events;
    uint32_t primask = __get_PRIMASK();

    __disable_irq();
    __DMB();
    events = g_adc_dma_events;
    g_adc_dma_events = 0U;
    __DMB();
    if (primask == 0U) {
        __enable_irq();
    }
    return events;
}

static void adc_process_block(const uint16_t *samples, uint32_t count)
{
    /* 应用处理入口：必须在 DMA 下一次覆盖该半区前完成。 */
    (void)samples;
    (void)count;
}

static HAL_StatusTypeDef adc_dma_recover(void)
{
    HAL_StatusTypeDef status = HAL_ADC_Stop_DMA(&hadc1);
    if (status != HAL_OK) {
        return status;
    }

    /* 先把 g_adc_error_code/g_dma_error_code 记入诊断，再清状态重启。 */
    return adc_dma_start();
}
```

主程序的最小调用顺序：

```c
int main(void)
{
    HAL_Init();
    SystemClock_Config();
    MX_GPIO_Init();
    MX_DMA_Init();
    MX_ADC1_Init();

    if (adc_dma_start() != HAL_OK) {
        Error_Handler();
    }

    for (;;) {
        uint32_t events = adc_dma_take_events();

        if ((events & ADC_DMA_EVT_FIRST_HALF) != 0U) {
            adc_process_block(&g_adc_dma_samples[0], ADC_DMA_HALF_COUNT);
        }
        if ((events & ADC_DMA_EVT_SECOND_HALF) != 0U) {
            adc_process_block(&g_adc_dma_samples[ADC_DMA_HALF_COUNT],
                              ADC_DMA_HALF_COUNT);
        }
        if ((events & ADC_DMA_EVT_ERROR) != 0U) {
            if (adc_dma_recover() != HAL_OK) {
                Error_Handler();
            }
        }
    }
}
```

半完成回调后，DMA 正在写后 64 个样本，应用获得前半区；全完成回调后，循环模式回到前半区，应用获得后半区。应用必须在同一半区下一次被 DMA 覆盖前处理完。这个 bitmask 示例会合并尚未取走的重复事件；如果处理时间接近半缓冲周期，生产代码应改用单调事件计数器或无锁队列，并通过示波器/周期计数器证明没有漏批次。

不要在同一个 stream 上混用 HAL 状态机和 LL 重配置。若改写为 LL-only 驱动，最低顺序是：确认 `LL_DMA_IsEnabledStream` 为 0 -> 清旧标志 -> 设置 channel、方向、地址、宽度、递增、模式、优先级和长度 -> 开 HT/TC/TE/DME 中断 -> `LL_DMA_EnableStream`。RM0090 规定 EN=1 时大多数配置位、NDTR、PAR 和 M0AR 不允许改写。[S2][S3]

## 10. 常见错误

1. **把 DMA 当成无限带宽的 memcpy**：每个请求只代表一个传输机会，真实吞吐还受总线和外设节奏影响。
2. **忽略传输宽度**：计数是“传输单元数”，不是字节数；宽度为 4 时，4 个计数代表 16 个字节。
3. **只检查起始地址不检查末端**：`offset + width` 超过容量会越界；应使用减法形式检查，避免无符号加法溢出。
4. **在循环模式中读取正在写入的半区**：半传输/全传输事件是所有权边界，事件前不能假定对应区域稳定。
5. **普通模式完成后继续提交请求**：完成是终态，必须重新组装或重新启动，而不是继续改计数。
6. **把 Host Fake 的宽度规则当硬件规则**：真实外设寄存器的允许宽度、对齐和请求映射必须查目标器件手册。
7. **把 F4/F7 的 stream/channel 术语套到 H5/H7**：系列之间的请求选择器和 DMA 资源结构需要逐器件核对。
8. **忽略缓存和内存域**：F7/H7 的缓存、一致性和内存域行为是待按目标器件手册核对的后续问题；本课不把它们当作已验证结论，也不猜测具体操作。
9. **只初始化 ADC、没有打开 DMA2 时钟**：`HAL_DMA_Init` 能否访问寄存器取决于 `RCC_AHB1ENR.DMA2EN`，初始化顺序应让 `MX_DMA_Init` 位于 `MX_ADC1_Init` 之前。
10. **请求映射选错**：ADC1 在本参考目标上使用 DMA2 Stream0/Channel0 是 RM0090 的器件结论，不是“所有 STM32 的 ADC1 都这样”。
11. **把 128 当成字节数**：`HAL_ADC_Start_DMA` 的 `Length` 最终进入 NDTR，是按所配数据宽度计数的数据项；本例是 128 个半字。
12. **漏掉 `__HAL_LINKDMA`**：没有把 `hdma_adc1` 连接到 `hadc1.DMA_Handle`，ADC HAL 无法沿父子句柄传播 DMA 回调和错误。
13. **在回调里处理整批数据或打印**：ISR 运行过久会让下一半缓冲区在应用完成前被覆盖，也会放大 ADC overrun 风险。
14. **HAL 和 LL 同时拥有同一 stream**：HAL 的状态、回调指针与真实寄存器会失配。LL 可以用于解释和观测，但配置所有权必须唯一。
15. **把事件 bitmask 当成无损队列**：相同事件多次到达会被合并；只有证明主循环总能在下一次同类事件前取走标志时才适用。

## 11. 调试观察点

- 在每次 `fake_dma_step(1)` 前后记录源偏移、目的偏移、剩余计数和状态，确认一次请求只改变一个传输单元。
- 把请求序列写成 `0,1,0,1`，观察等待事件不会改变目标数组或计数。
- 在半传输边界单步，确认半传输事件发生在第二个单元之后（4 单元示例），而不是初始化时。
- 在循环模式全传输后检查偏移回到零；如果状态变成完成，说明错误地复用了普通模式路径。
- 故障注入宽度 3、容量不足和非法请求，确认错误路径没有部分写入。
- F407 板级调试时先看 `RCC_AHB1ENR.DMA2EN=1`、`DMA2_Stream0->CR.EN=1`、`CHSEL=0`、`DIR=0`、`CIRC=1`、`MINC=1`、`PSIZE/MSIZE=1`，再看 `PAR` 是否等于 ADC1_DR 地址、`M0AR` 是否落在目标 SRAM、`NDTR` 是否从 128 递减。
- 在 DMA2 Stream0 IRQ 前后观察 `DMA_LISR` 的 HTIF0/TCIF0/TEIF0/DMEIF0/FEIF0 和 `DMA_LIFCR` 清除行为；如果标志不断进入但回调计数不增，检查 IRQ handler 是否调用了正确的 `HAL_DMA_IRQHandler(&hdma_adc1)`。
- 若 `NDTR` 不变，按“ADC 是否转换 -> ADC DMA request 是否开启 -> 请求映射是否正确 -> DMA stream 是否使能 -> 时钟是否开启”的方向逐段定位，不要先怀疑缓冲区业务逻辑。
- 若出现 OVR，保存 ADC/DMA error code、NDTR、LISR 和 ADC 状态快照，再由主循环停止并恢复；不要在错误回调中直接覆盖证据。
- 不把主机断言通过写成 DMA 硬件吞吐、实时性或一致性已经验证。

## 12. 实战实验

### 实验 A：普通模式与请求不足

1. 将第 9 节代码保存为临时 `dma_fake.c`，用本机可用的 C11 编译器构建；Reviewer 已执行一次严格警告编译和断言测试，但你仍应把自己的命令和输出保存为实验记录。
2. 在普通模式中把请求序列改成 `1,0,1,1,0,1`，每步打印 `completed_units`、`remaining_units` 和目的数组。
3. 解释为什么 `0` 请求不会推进计数，以及全传输后再次请求为什么必须报停止错误。

### 实验 B：循环缓冲区的所有权

1. 把传输单元数改为 8，源数组填入 `0..7`，每两个请求后记录一次事件日志。
2. 在半传输事件后只读取目的数组的前半部分；在全传输事件后再读取后半部分。
3. 写出一条规则：应用消费某一半缓冲区时，DMA 当前允许写入哪一半？如果规则无法从事件和偏移推导，说明所有权契约还不完整。

### 实验 C：错误注入表

记录以下列：注入动作、返回状态、目标数组是否改变、剩余计数、状态、仍不能证明的硬件事实。至少覆盖非法宽度、源越界、目的越界、请求值为 2、普通模式完成后再次请求。

### 实验 D：生成 STM32F407 ADC-DMA 工程

1. 在 CubeMX 选择实际使用的 STM32F407 完整料号，按 7.5 节配置 HSI、PLL、ADC1_IN0 和 DMA2 Stream0/Channel0；保存 `.ioc`、CubeMX 版本和 STM32CubeF4 包版本。
2. 生成工程后对照 9.2 节检查调用顺序、`HAL_ADC_MspInit`、`__HAL_LINKDMA`、IRQ handler 和回调；差异必须由生成器版本或工程选项解释，不能机械覆盖。
3. 构建并保存编译日志与 `.map`。确认 `g_adc_dma_samples` 位于 DMA2 可访问的 SRAM，记录地址和长度；若没有目标工具链，本步骤记为“未执行”。
4. 上板前先让 ADC 输入接到符合电气范围的稳定电压，设置半/全回调计数器，观察 `NDTR`、HT/TC 标志与 128 个样本。没有合适板卡和仪器时不得编造结果。

### 实验 E：从 HAL 追到寄存器

暂停在 `HAL_ADC_Start_DMA` 返回后，逐项记录 HAL 字段、LL 读值和寄存器位：CHSEL、DIR、PINC/MINC、PSIZE/MSIZE、CIRC、PL、PAR、M0AR、NDTR、HTIE/TCIE/TEIE。然后只通过 HAL 停止 DMA，确认 EN 清零后配置寄存器才可安全改写。禁止在 HAL 运行时用调试器写寄存器“修好”配置。

### 实验 F：迁移差异表

再选择一个具体 F7、H5 或 H7 器件，仅查该器件第一方资料，填写：请求源、DMA 资源命名、宽度、地址递增、半/全标志、错误清除、可访问内存和缓存/安全限制。把每一项与 F407 行并排比较；没有文档页码、版本或具体适用范围的项目写“待核对”。

## 13. 自检题

1. 一个 `request=1` 为什么最多搬运一个传输单元，而不是整个数组？
2. 传输计数为 4、宽度为 2 字节时，完整传输包含多少字节？
3. 普通模式与循环模式在全传输事件后的状态和偏移有什么差异？
4. 为什么 `request=0` 不能减少 `remaining_units`？
5. 谁持有源/目的端点和剩余计数？哪个调用者负责注入初始契约？
6. 半传输事件能证明应用可以读取整个缓冲区吗？为什么？
7. Host Fake 的越界检查能否证明真实 STM32 总线一定不会产生错误？
8. 本例 HSI=16 MHz、PLLM=16、PLLN=336、PLLP=2、HPRE=1、PPRE2=2、ADC prescaler=4 时，HCLK、PCLK2 和 ADC clock 各是多少？
9. `Length=128`、PSIZE/MSIZE=half-word 时，NDTR 初值和缓冲区字节数各是多少？
10. 为什么 `__HAL_LINKDMA` 不只是一个方便宏，而是 ADC HAL 回调链的一部分？

参考要点：一次请求代表一次外设数据就绪机会；4×2 为 8 字节；普通模式进入完成且不再接受搬运，循环模式回卷并继续运行；无请求就没有搬运；DMA 对象持有运行状态，初始化者注入契约；半传输只交还已定义的一半；Host Fake 只能证明模型边界逻辑，不能证明硬件总线行为；时钟依次为 168/84/21 MHz；NDTR=128、缓冲区 256 字节；链接宏同时把 DMA 句柄挂到 ADC 句柄并建立 DMA 的 Parent 回指，使 IRQ 中的 DMA 回调能回到 ADC HAL。

## 14. 面试题

1. 请从 CPU 提交配置开始，完整描述一次 peripheral-to-memory DMA 传输的调用流。
2. 为什么 DMA 的传输计数通常不能直接解释为字节数？
3. 循环 DMA 接收环形缓冲区时，如何避免应用读取 DMA 正在写入的区域？
4. 如果目的缓冲区只够容纳 3 个 4 字节单元，而配置为 4 个单元，你会在哪一层拒绝配置？为什么？
5. F4/F7 的 stream/channel 说明能否直接作为 H5/H7 的请求映射依据？你会查哪些第一方资料？
6. 在带数据缓存的 MCU 上，为什么“DMA 已写入内存”不必然等于“CPU 立即读到新内容”？本课哪些部分不能回答这个问题？
7. 请从 `HAL_ADC_Start_DMA` 依次指出 `DMA_S0PAR/M0AR/NDTR/S0CR` 分别承载传输契约的哪个部分。
8. DMA2 Stream0 IRQ 已进入但 `HAL_ADC_ConvCpltCallback` 从不执行，你会按什么证据顺序排查？

## 15. 延伸思考

- 把 `fake_dma_step` 从“函数调用请求”改成固定时间刻度事件时，哪些契约字段保持不变，哪些新状态需要引入？
- 如果一个外设请求偶尔丢失，普通模式的完成策略应继续等待、超时还是报错？请先写状态转移，不要直接添加 RTOS。
- 如果源和目的端点重叠，应该定义前向复制、后向复制还是明确拒绝？为什么 DMA 的硬件语义不能从 C 的 `memmove` 自动推断？
- 如果应用在半传输时修改源缓冲区，如何用所有权规则判断这是合法操作还是数据竞争？
- 选定 H7 后，哪些缓存/内存域结论必须由参考手册或应用笔记支持，不能由本课的固定数组模型推出？

## 16. 本节总结

DMA 把“逐项搬运”从 CPU 循环中分离出来：CPU 先组装源/目的端点、宽度、计数、请求和模式，DMA 在每个外设请求到来时搬运一个传输单元，更新偏移和剩余计数，并以半传输、全传输或错误状态交还可观察结果。传输契约同时规定了缓冲区所有权，避免应用与 DMA 同时修改同一部分数据。

Host Fake 用固定数组和静态状态覆盖了普通模式、循环模式、请求不足、非法宽度、越界和非法请求。STM32 参考轨道进一步把同一契约落实到 F407 的 ADC1、DMA2 Stream0/Channel0、168/84/21 MHz 时钟链、CubeMX 配置、HAL 初始化、IRQ/回调、LL API 和关键寄存器。两条轨道相互解释，但主机断言不能替代目标构建和上板证据。

现在缺少的是具体板卡、Cube 工程、构建日志、烧录记录和测量结果，而不是硬件实现说明。因此本课继续保持 `hardware_verified=false`，同时保留一条可直接进入真实工程验证的路径。

## 17. 下一步

课程路线的下一个主题是 `clock-tree`：把本课使用的 HSI、PLL、SYSCLK、HCLK、PCLK 与 ADC 时钟从“给定配置”提升为可系统推导、可测量和可排错的时钟树。随后依次进入 HAL/LL/寄存器对照、定时器触发路由、高级控制定时器，以及 `Timer TRGO -> ADC -> DMA -> 中断/任务` 的完整流水线。

## 18. 参考资料

- [S1] STMicroelectronics，*Using the STM32F2/F4/F7 DMA controller*，应用笔记 AN4031，DocID022648 Rev 3（June 2016）。封面和第 1 页引言说明覆盖 STM32F2/F4/F7，且以 F4 为示例；具体目标器件仍需回到对应参考手册。<https://www.st.com/resource/en/application_note/an4031-using-the-stm32f2f4f7-series-dma-controller-stmicroelectronics.pdf>，访问日期：2026-10-07。
- [S2] STMicroelectronics，*STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 advanced Arm-based 32-bit MCUs - Reference manual*，RM0090 Rev 22（May 2026）。表 44 用于 ADC1/DMA2 请求映射，第 7 章用于 RCC，第 10 章用于 DMA 寄存器、流/通道和标志；适用范围限于手册首页列出的器件。<https://www.st.com/resource/en/reference_manual/dm00031020.pdf>，访问日期：2026-10-09。
- [S3] STMicroelectronics，*Description of STM32F4 HAL and low-layer drivers*，UM1725 Rev 8（March 2023）。用于 `HAL_DMA_Init`、`HAL_DMA_IRQHandler`、`HAL_ADC_Start_DMA`、ADC 半/全完成与错误回调、`__HAL_LINKDMA` 及 LL DMA API 的接口边界。<https://www.st.com/resource/en/user_manual/dm00105879.pdf>，访问日期：2026-10-09。

三条资料均来自 `config/source-policy.toml` 允许的 `st.com` 域名，且为第一方来源。S1、S2、S3 的本地 PDF、SHA-256、版本和关键页证据均保存在本次运行目录；H5/H7 的缓存、内存域和请求映射仍必须按目标器件资料重新核对。

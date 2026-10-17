+++
title = "外设集成实验：采集批次到串行 DMA 的有界交接"
date = "2026-10-16T23:29:09+08:00"
lastmod = "2026-10-16T23:29:09+08:00"
summary = "建立采集批次交给传输 DMA 时的端到端有界所有权与背压边界，并用 C11 Host Fake 验证正常交接、超期、停源和恢复，以 STM32F407xx 的 TIM2-ADC1-DMA2 到 USART2-DMA1 参考链核对时钟、CubeMX、HAL、LL、寄存器与迁移边界。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 32
tags = ["peripheral-integration", "bounded-ownership", "backpressure", "adc", "timer", "dma", "uart", "stm32f407", "cubemx", "hal", "ll", "registers", "host-fake", "c11"]
source_ids = ["st-rm0090-peripheral-integration", "st-ds8626-peripheral-integration", "st-um1725-peripheral-integration", "st-an4031-peripheral-integration", "st-stm32cubef4-1.28.3-peripheral-integration"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L032"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 32 课：外设集成实验——采集批次到串行 DMA 的有界交接

上一课已经建立 `TIM2 update/TRGO -> ADC1 -> DMA2 circular buffer` 的持续采集链：DMA（Direct Memory Access，直接存储器访问）每写完一个半区，就通过 HT/TC（half transfer/transfer complete，半传输/传输完成）交出一个暂时稳定的批次。本课再接上 `USART2 TX DMA`，但重点不是“多调用一个发送函数”，而是只推进一个新核心概念：**端到端有界批次所有权与背压**。

“有界”有两层含义：内存只有两个固定半区，时间也只有从批次发布到采集 DMA 再次写入该半区之间的一段窗口。发送 DMA 领取半区后，应用不能修改它；采集 DMA 也必须等发送完成归还后才能重用它。若消费者赶不上，backpressure（背压）不是悄悄覆盖或重发未知数据，而是阻止上游继续产生数据。本课策略固定为：**先停 TIM2 采集源，锁存首个故障和现场，再清理链路；只有显式恢复才能开始新会话。**

本课提供两条证据互不替代的轨道：

- Host Fake（主机替身）用 C11 固定数组和确定性 tick 验证所有权、截止时间、错误与恢复；它不模拟寄存器、电气信号、总线仲裁或 UART 波形。
- STM32 参考实现固定为 `STM32F407xx` 的 `TIM2 -> ADC1 -> DMA2 Stream0/Channel0 -> 两个半区 -> USART2 TX -> DMA1 Stream6/Channel4`。该映射、HAL（Hardware Abstraction Layer，硬件抽象层）调用和寄存器字段以 RM0090、UM1725、AN4031 与 STM32CubeF4 v1.28.3 为边界。[S1][S3][S4][S5]

当前没有具体开发板、完整订货料号、封装、晶振、ADC 输入、USART 引脚/对端、目标工程、构建日志、烧录记录或测量数据。所有 STM32 代码均是**参考实现，待目标工程编译和上板验证**；本文没有执行烧录或测量，`hardware_verified=false`。

## 1. 本节目标

核心目标与本次 `plan.json` 一致：**建立采集批次交给传输 DMA 时的端到端有界所有权与背压边界，并以 STM32F407xx 参考链核对其启动、完成、超期和停源路径。**

完成本课后，你应能：

1. 画出采集 DMA 写、批次待领取、发送 DMA 读、归还四种状态及唯一合法转移；
2. 说明采样数组、批次描述符、发送槽和故障快照在哪里定义，谁持有、谁注入事件；
3. 分开解释控制流、事件流和数据流，不把 HAL 返回值、回调或串口打印互相当作证据；
4. 由触发周期、半区长度和串行帧格式计算重用窗口与线速时间，并指出静态计算尚缺哪些最坏情况证据；
5. 用 Host Fake 验证正常 A/B 交替、发送忙/超期、TX/采集错误、重复事件、停源和新会话恢复；
6. 按 CubeMX、HAL、LL（Low-Layer，低层驱动）和关键寄存器四层核对 F407 参考实现；
7. 从 F4 迁移到 F7、H5、H7 时保留所有权方法，同时重查 DMA 架构、请求路由、内存可达性、缓存、时钟域和安全属性。

## 2. 它解决什么问题

### 2.1 两个 DMA 为什么会争用同一块内存

采集 DMA 是生产者：它从 `ADC1_DR` 读取 16 位结果，循环写入 `samples[]`。发送 DMA 是消费者：它从一个已完成半区读取字节，写到 `USART2_DR`。CPU 不逐样本或逐字节搬运，只在批次边界安排交接。

```text
TIM2 update/TRGO
  -> ADC1 conversion
  -> DMA2 writes samples[0..63]
  -> HT publishes half A
  -> App lends A to USART2 TX DMA
  -> DMA1 reads A while DMA2 writes half B
  -> TX complete returns A
  -> DMA2 may reuse A after half B completes
```

若 TX 尚未归还 A，DMA2 就开始下一轮写 A，发送出去的批次会由旧样本和新样本拼接。内存地址仍然合法，DMA 也可能都没有报错，因此“没有 TE 标志”不能证明数据一致。必须由软件在发布边界维护所有权，并用时间预算保证归还发生在重用之前。

### 2.2 为什么不是“忙就等一下”

循环采集不会因为主循环等待而自动停下。等待只会消耗剩余窗口；到达重用边界后，旧批次已经失去可信度。本课不引入无界队列、动态内存或阻塞重试。若发送槽忙、代次不连续、发送错误或截止时间已到，立即进入故障会话：

```text
detect first fault
  -> disable TIM2 CEN first
  -> freeze diagnostic snapshot
  -> stop/abort ADC and TX DMA in deferred control path
  -> reject all new batches
  -> explicit recover creates a new session
```

“先停源”只阻止未来触发。它不能撤销已经发生的 DMA 写入，因此故障批次不得追认为有效。若要证明 TIM2 在下一次触发前已经停下，还需目标上的 IRQ 最大延迟测量；Host Fake 只能验证顺序。

### 2.3 最小可运行形态

本课固定以下边界，避免把一个集成实验扩成多个新主题：

- 一个含 128 个 `uint16_t` 的静态循环数组，A/B 各 64 个样本；
- 单个 ADC regular rank，TIM2 以 1 kHz 产生 TRGO；
- 采集使用 DMA2 circular mode，发送使用 DMA1 normal mode；
- 每批发送半区内存的 128 个原始字节，不添加协议头、CRC 或可变长度；外部接收者必须另行约定字节序和固定批长；
- USART 示例为 115200 baud、8 data bits、no parity、1 stop bit（8N1）；不启用硬件流控；
- 应用一次只允许一个发送槽；没有动态内存、RTOS（实时操作系统）或运行期回调注册；
- 多通道帧、硬件 double-buffer、协议封装、缓存一致性和通用消息队列留给后续课程。

## 3. 必要前置知识

下列前置均已记录在 `learning-state.toml.completed`：

- `uart`：异步帧、波特率、发送完成和错误不是同一个时刻；
- `dma`：请求、stream/channel、方向、数据宽度、地址递增、HT/TC/error 和生命周期；
- `clock-tree`：振荡源、PLL、AHB/APB、门控与最终外设时钟逐级推导；
- `hal-ll-register-crosswalk`：HAL 意图、寄存器状态和运行证据必须分层；
- `timer-trigger-routing`：合法触发路由与“先武装接收端、最后启动源”；
- `advanced-control-timer`：源事件、预装载、故障停止和可观察边界；
- `adc-timer-dma-pipeline`：TIM2-ADC1-DMA2 的转换预算、循环半区和 HT/TC 交接。

缓存、RTOS、通用驱动架构尚未完成，不是本课隐含前置。F7/H7 的 D-Cache（数据缓存）、H5 的安全属性、DMAMUX/GPDMA 只作为迁移检查项，不进入本课最小模型。

## 4. 核心原理

### 4.1 所有权状态机

每个半区只允许处于一种状态：

| 状态 | 唯一可写者/读者 | 允许的下一步 | 禁止动作 |
| --- | --- | --- | --- |
| `CAPTURING` | ADC DMA 可写 | HT/TC 后变为 `READY` | CPU/TX DMA 读取未完成数据 |
| `READY` | 内容只读，尚无 TX 读者 | App 领取后变为 `TX_OWNED` | ADC DMA 重用、应用修改、重复领取 |
| `TX_OWNED` | USART TX DMA 只读 | TX complete 后变为 `RETURNED` | ADC DMA 重用、应用修改、第二次发送 |
| `RETURNED` | 无活动读写者 | 到重用边界后变为 `CAPTURING` | 把旧代次再次提交 |

在真实 circular DMA 中，HT/TC 后硬件自动进入另一个半区；软件不能暂停在一个抽象状态等待决定。因此每次边界事件还承担“即将重用另一半”的检查：

- HT：A 刚完成并发布；DMA 接下来写 B，所以 B 必须已经归还；
- TC：B 刚完成并发布；DMA 回卷写 A，所以 A 必须已经归还。

若待重用半区仍为 `TX_OWNED` 或 `READY`，系统先停 TIM2。由于 IRQ 有延迟，这个策略还要求“边界 IRQ 最坏延迟 + 停源时间 < 下一次触发间隔”；目标实验必须测量，不能由状态机自动保证。

### 4.2 代次和截止时间

半区索引只能区分 A/B，不能区分“哪一轮 A”。每次发布给该半区的 `generation` 加一，发送槽在启动时锁定 `(half, generation, address, byte_count, deadline)`。TX complete 只能归还完全匹配的槽；重复完成、旧回调或代次跳变都进入故障。

设总样本数为 `N`、触发周期为 `T_trigger`：

```text
half_samples = N / 2
T_half       = half_samples * T_trigger
deadline     = publish_time + T_half
```

这是该批次从“完成发布”到“DMA 开始重用同一半区”的名义窗口。安全条件是：

```text
T_tx_worst + T_irq_and_schedule_margin < T_half
```

平均发送时间不够。`T_tx_worst` 必须覆盖最低实际 baud、DMA/总线造成的间隙和 USART 最后一个停止位完成；margin 还要覆盖批次领取延迟与 TX complete IRQ 延迟。本课 Host Fake 用 tick 检查截止时间，目标端必须用测量补足最坏值。

### 4.3 三种流与停止顺序

```text
控制流：clock/init -> arm ADC DMA -> start TIM2 -> stop -> recover
事件流：update -> TRGO -> ADC request -> HT/TC -> TX DMA TC/error
数据流：ADC1_DR -> DMA2 -> samples half -> DMA1 -> USART2_DR -> TX pin
```

控制流的 `HAL_OK` 只说明调用被接受；事件流的回调只说明 HAL 分发到了软件；数据流必须由地址、`NDTR`、缓冲内容和外部接收结果逐段证明。错误顺序固定为：

1. 在最早可用入口保存只读寄存器快照；
2. 清 `TIM2_CR1.CEN`，阻止新触发；
3. 锁存首错、半区代次、TX 剩余计数和 HAL error code；
4. 主控制流停止 ADC DMA、abort TX DMA，并丢弃本会话所有待处理批次；
5. 保留历史快照，显式初始化新会话后才重新武装和启动。

### 4.4 对象、持有者、注入者与调用流

| 对象 | 解决的问题 | 定义与持有者 | 谁注入 | 调用/数据流 |
| --- | --- | --- | --- | --- |
| `samples[128]` | 为连续采集提供有界存储 | BSP 实现文件静态定义并持有 | 启动时地址交给 ADC HAL/DMA | DMA2 写；只在稳定半区由 DMA1 读 |
| `batch_half_t[2]` | 保存每半区状态、代次和期限 | 实验控制器私有持有 | HT/TC 发布；TX complete 归还 | `CAPTURING -> READY -> TX_OWNED -> RETURNED` |
| `tx_slot_t` | 锁定当前 TX 读取对象 | 串行适配层私有持有 | App 提交 `(half,generation)` | idle -> active -> complete/error -> idle |
| `fault_snapshot_t` | 保留首错与现场 | 组合根/实验控制器静态持有 | IRQ 或超期检查写一次 | stop source -> snapshot -> deferred cleanup |
| HAL handles | 绑定实例、DMA 和 HAL 状态 | BSP 实现文件静态/全局持有 | MSP/CubeMX 注入实例与 DMA 链接 | App 只通过 BSP API 使用，不直接重配 |

这里的“注入”是初始化者或硬件事件把依赖/事件交给对象，并不引入尚未学习的通用依赖注入框架。

## 5. 关键术语与直观模型

| 术语 | 本课准确含义 |
| --- | --- |
| producer/consumer | 生产者/消费者；ADC DMA 产生稳定批次，TX DMA 消费批次 |
| ownership | 所有权；约束某时刻谁可读写，并非 C 语言关键字 |
| batch | 批次；一次 HT 或 TC 对应的固定半区及其代次 |
| generation | 代次；识别同一半区不同轮次的单调编号 |
| deadline | 截止时间；批次必须在同半区重用前归还的时刻 |
| backpressure | 背压；下游来不及时阻止上游继续生产，本课实现为停 TIM2 并报错 |
| TX complete | 传输完成；最后一帧完成后才归还内存，不能只以 DMA 已装载最后一字节替代 |
| fault latch | 故障锁存；只保留会话的首个故障，后续状态作为附加计数而不覆盖根因 |

直观模型是两只固定周转箱 A/B。采集线装满 A 后把封条和代次交给运输线，同时转去装 B；运输线签收后只有读权。下一次采集线要回到 A 时，若运输线尚未签字归还，工厂不是把新货混入旧箱，而是停掉上游并保存现场。

## 6. 从输入到结果的完整流程

### 6.1 正常会话

1. 组合根配置时钟、GPIO 的板级待填项、DMA、ADC、TIM2 和 USART2；
2. 初始化批次控制器，使 A/B 都处于可开始采集的会话状态；
3. `HAL_ADC_Start_DMA` 先武装 ADC1 与 DMA2；
4. `HAL_TIM_Base_Start` 最后启动 TIM2，硬件链开始产生样本；
5. HT 发布 A，检查 B 可被采集，App 领取 A 并调用 `HAL_UART_Transmit_DMA`；
6. TX DMA 从 A 读取 128 byte；DMA2 同时写 B；
7. `HAL_UART_TxCpltCallback` 归还与发送槽匹配的 A；
8. TC 发布 B，检查 A 已归还，DMA2 回卷写 A；App 领取 B；
9. 以上过程只有在每个批次都在截止时间前归还时才能持续。

### 6.2 发送忙、超期或错误

若新批次到来而发送槽仍忙，不立即把新批次标成“已发送”，也不覆盖当前槽。控制器锁存 `TX_BUSY_AT_PUBLISH`，先停 TIM2，然后在主上下文清理 ADC/TX DMA。若当前 TX 完成回调随后到达，它属于故障会话，只补充现场，不得触发下一批发送。

若 `now >= deadline` 且槽仍 active，锁存 `TX_DEADLINE`。这里使用半开区间：必须在 deadline 之前完成；恰好到 deadline 已没有可证明的余量。

DMA TE/DME/FE、ADC error 或 UART error 都走同一停源入口，但保留不同错误码。首错不被后续 abort 产生的回调覆盖。

### 6.3 显式恢复

恢复不是清一个 error bit：先确认源已停，并且 HAL stop/abort 全部返回成功；成功的阻塞式 UART abort 会关闭 TX 中断和 DMA 请求、停止 DMA 且不执行 TX 完成回调。[S5] 若任一清理调用失败，保持 fault 与 `cleanup_pending`，禁止增加 `session_id` 或重新启动。清理成功后再重置 A/B 活动状态、发送槽和当前代次基线；历史故障快照不清除。重新执行“先武装 ADC DMA、后启动 TIM2”。`session_id` 用于诊断会话，不是假想的硬件回调令牌；安全恢复依赖重新启动前已证明 DMA/UART IRQ 源静默，而不是仅靠比较 session。

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

| 层级 | 能力与工作原理 | 触发/数据/中断链路 | 本课与后续落点 |
| --- | --- | --- | --- |
| 基础 | ADC 单次规则转换、定时器 update、UART TX、单次 DMA | 软件启动，各外设独立完成 | 已学；不足以保护跨 DMA 的共享内存 |
| 进阶 | TIM TRGO 触发 ADC、circular DMA HT/TC、UART TX DMA | `TIM2 -> ADC1 -> DMA2 -> HT/TC -> DMA1 -> USART2` | 本课深入端到端交接与停源 |
| 高级 | 多通道帧、DMA double-buffer、UART FIFO/阈值、链表 DMA | rank 序列或双地址切换改变批次边界；FIFO/链表改变请求与完成条件 | 多通道采集、DMA 高级模式和新系列专题 |
| 跨外设联动 | 采样节拍、内存所有权、串行吞吐共同约束 | 一个源、两个 DMA、两个 IRQ 域共享批次期限 | 本课核心；以后加入协议/存储/网络消费者 |
| 系列差异 | F4 stream/channel；F7/H7 缓存；H5 GPDMA/DMAMUX 与安全属性 | 请求选择、内存域、缓存可见性和 IRQ 标志均可能变化 | 迁移审计；不能复制 F407 数值 |

高级功能不是名字列表：硬件 double-buffer 通过两个内存地址和 current-target 状态让 DMA 在目标之间切换，解决软件在循环数组中判断重用点的问题，但仍要求消费者在目标再次被选择前归还；多通道 scan 则让一次触发产生一个 rank 序列，批次必须按完整 frame 而非任意样本切分；带 FIFO、DMAMUX 或链表的 DMA 会改变请求汇聚和完成事件，却不取消所有权与截止时间。它们分别落到 DMA 高级模式、多通道 ADC 和系列专项课程。

#### F4/F7/H5/H7 迁移表

| 项目 | F407 本课参考 | F7 | H5 | H7 |
| --- | --- | --- | --- | --- |
| DMA 请求 | 固定 stream/channel 映射 | 按具体 F7 RM 重查 stream/channel | 重查 GPDMA/DMAMUX request 与链表能力 | 重查 DMA/BDMA/MDMA 与 DMAMUX |
| 内存可达性 | 本课静态 SRAM 地址仍需链接图核对 | 重查 DMA 可达区与 D-Cache | 重查 SRAM、GPDMA 端口与 secure/non-secure 属性 | 重查 DTCM/AXI SRAM/域及 DMA master 可达性 |
| 缓存 | Cortex-M4 无 D-Cache；仍需编译器/并发边界 | 交接前后加入目标正确的 clean/invalidate、对齐与 MPU 策略 | 按具体内核/cache/安全配置重查 | D-Cache 与多域总线必须纳入所有权协议 |
| UART 能力 | USART2，无 FIFO 假设 | FIFO/实例能力按目标核对 | 新 USART/UART 与 FIFO/时钟选择重查 | kernel clock、FIFO 和实例差异重查 |
| 保留机制 | 代次、单一读写者、deadline、先停源、首错快照 | 全部保留 | 全部保留并增加安全所有者 | 全部保留并增加缓存/域所有者 |

### 7.2 参考目标与时钟/复位链

参考器件范围是 `STM32F407xx`，不是某块开发板。下面是一套便于算账的**参考时钟假设**，实际工程必须按晶振、电源和完整料号重算：[S1][S2]

```text
HSI 16 MHz
  -> PLLM /16 = 1 MHz
  -> PLLN x336 = 336 MHz VCO
  -> PLLP /4 = SYSCLK 84 MHz
  -> AHB /1 = HCLK 84 MHz
     -> APB1 /2 = PCLK1 42 MHz
        -> TIM2 kernel = 84 MHz（APB1 prescaler != 1 时的 timer 倍频规则）
        -> USART2 kernel/input clock = 42 MHz
     -> APB2 /2 = PCLK2 42 MHz
        -> ADC common prescaler /2 = ADCCLK 21 MHz
```

TIM2 参考值：

```text
f_counter = 84 MHz / (PSC + 1) = 84 MHz / 84 = 1 MHz
f_update  = 1 MHz / (ARR + 1)  = 1 MHz / 1000 = 1 kHz
T_trigger = 1 ms
```

ADC1 使用 12-bit resolution 和 84-cycle sample time 的参考条件时，按 F4 的转换周期模型：

```text
T_conv = (84 + 12) / 21 MHz ~= 4.57 us < 1 ms
```

该数值只说明数字时序余量；具体 ADC channel、源阻抗、VDDA/VREF 与所需采样时间属于板级待填项。不能从 4.57 us 推出模拟精度合格。[S1][S2]

128 个样本、每半区 64 个样本：

```text
T_half = 64 * 1 ms = 64 ms
bytes_per_batch = 64 * sizeof(uint16_t) = 128 byte
```

USART2 使用 115200 baud、8N1 时，每 byte 占 1 start + 8 data + 1 stop = 10 line bits：

```text
T_line_nominal = 128 * 10 / 115200 ~= 11.11 ms
```

11.11 ms 是无额外空隙的名义线速时间，不是已经证明的 `T_tx_worst`。若目标工程能证明实际 baud 下界为 114000、DMA 对 DR 的供给不会插入超过 1 ms 的累计间隙、领取与 IRQ 最大裕量为 2 ms，则条件式上界为：

```text
T_tx_worst + margin <= (1280 / 114000) + 1 ms + 2 ms
                    ~= 14.23 ms < 64 ms
```

这些“能证明”的条件当前没有目标测量，所以上式是验收公式而非实测结论。板上必须记录实际时钟、串行波形/接收时间和最坏 IRQ 延迟。

时钟门控与复位链：

| 资源 | RCC 门控 | 复位边界 | 所有权要求 |
| --- | --- | --- | --- |
| TIM2 | `RCC_APB1ENR.TIM2EN` | `RCC_APB1RSTR.TIM2RST` | 停源只清 CEN；局部错误不重置整个 APB1 |
| USART2 | `RCC_APB1ENR.USART2EN` | `RCC_APB1RSTR.USART2RST` | abort 优先于外设复位，避免影响共享配置 |
| ADC1 | `RCC_APB2ENR.ADC1EN` | `RCC_APB2RSTR.ADCRST` 为共享 ADC reset 域 | 只有知道 ADC2/3 使用者的组合根可复位 |
| DMA1/DMA2 | `RCC_AHB1ENR.DMA1EN/DMA2EN` | `RCC_AHB1RSTR.DMA1RST/DMA2RST` | 控制器含多个 stream，回调不得整体复位 |

必须区分“时钟已开”“外设已初始化”“DMA stream EN=1”“ADC/DMA 已武装”“TIM2 CEN=1”和“USART 正在发送”。这些状态不能用一个 `started` 布尔值代替。

### 7.3 CubeMX、HAL、LL 与寄存器对照

#### CubeMX/CubeMX2 配置清单

以下是配置意图，不是仓库中已生成的 `.ioc`。先固定完整 F407 料号和板卡原理图，再填写标为“板级待填”的项目。

| 页面 | 参考配置 | 为什么/边界 |
| --- | --- | --- |
| RCC/Clock | HSI=16 MHz；PLL 16/336/4；AHB /1；APB1 /2；APB2 /2 | 得到 84/42/42 MHz 参考树；若用 HSE，其频率与电气条件板级待填 |
| TIM2 | Prescaler=83；Period=999；internal clock；TRGO=Update Event | 产生 1 kHz update/TRGO；不需要 TIM2 update IRQ |
| ADC1 | 12-bit；scan/continuous/discontinuous disabled；T2_TRGO rising；1 conversion；DMA continuous requests；EOC single | 一次触发只产生一个结果；ADC channel/pin 板级待填 |
| ADC1 DMA | DMA2 Stream0/Channel0；P2M；peripheral no-increment；memory increment；half-word/half-word；circular；high priority | F407 ADC1 参考映射；处理 HT/TC/TE/DME/FE [S1][S4] |
| USART2 | asynchronous TX；115200；8N1；no flow control；oversampling 16 | TX pin/AF、电平和对端板级待填 |
| USART2 TX DMA | DMA1 Stream6/Channel4；M2P；byte/byte；memory increment；normal；medium priority | F407 USART2_TX 参考映射；每批重新武装 [S1] |
| NVIC | DMA2 Stream0 priority 5；DMA1 Stream6 priority 6；USART2 priority 6 | 采集边界优先；实际系统按全部 IRQ 和 RTOS 规则重算 |

USART2 IRQ 必须启用：STM32CubeF4 HAL 的 normal-mode DMA 发送在 DMA 计数结束后还要等待 USART TC（transmission complete，发送完成），最终用户 `TxCpltCallback` 由 UART IRQ 路径完成。只开 DMA1 Stream6 IRQ 不能把“最后一字节已交给 USART”当成“停止位已发完”。具体流程以固定 CubeF4 源码复核。[S3][S5]

生成工程后静态搜索：

```text
TIM_TRGO_UPDATE
ADC_EXTERNALTRIGCONV_T2_TRGO
ADC_EXTERNALTRIGCONVEDGE_RISING
DMA2_Stream0 + DMA_CHANNEL_0 + DMA_CIRCULAR
DMA1_Stream6 + DMA_CHANNEL_4 + DMA_NORMAL
__HAL_LINKDMA(&hadc1, DMA_Handle, hdma_adc1)
__HAL_LINKDMA(&huart2, hdmatx, hdma_usart2_tx)
DMA2_Stream0_IRQHandler / DMA1_Stream6_IRQHandler / USART2_IRQHandler
```

#### HAL 句柄、初始化字段和链接

下面代码属于 **BSP 实现层**，生命周期覆盖整个会话；依赖方向是 App -> `capture_tx.h` 接口 -> F407 BSP -> HAL。`board_adc_gpio_init()` 和 `board_usart2_gpio_init()` 是板级注入点，必须由实际原理图生成，本文不虚构引脚。

```c
/* main.c + capture_tx implementation excerpt; not built here. */
#include "stm32f4xx_hal.h"
#include <stdint.h>

#define SAMPLE_COUNT       128u
#define HALF_SAMPLE_COUNT   64u
#define HALF_BYTE_COUNT    128u

ADC_HandleTypeDef hadc1;
TIM_HandleTypeDef htim2;
UART_HandleTypeDef huart2;
DMA_HandleTypeDef hdma_adc1;
DMA_HandleTypeDef hdma_usart2_tx;
static uint16_t g_samples[SAMPLE_COUNT];

/* Supplied by the Cube-generated composition root and board adaptation. */
void Error_Handler(void);
void board_adc_gpio_init(void);
void board_usart2_gpio_init(void);

static void MX_DMA_Init(void)
{
    __HAL_RCC_DMA1_CLK_ENABLE();
    __HAL_RCC_DMA2_CLK_ENABLE();
    HAL_NVIC_SetPriority(DMA2_Stream0_IRQn, 5u, 0u);
    HAL_NVIC_EnableIRQ(DMA2_Stream0_IRQn);
    HAL_NVIC_SetPriority(DMA1_Stream6_IRQn, 6u, 0u);
    HAL_NVIC_EnableIRQ(DMA1_Stream6_IRQn);
}

static void MX_TIM2_Init(void)
{
    TIM_MasterConfigTypeDef master = {0};
    __HAL_RCC_TIM2_CLK_ENABLE();
    htim2.Instance = TIM2;
    htim2.Init.Prescaler = 83u;
    htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim2.Init.Period = 999u;
    htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    if (HAL_TIM_Base_Init(&htim2) != HAL_OK) { Error_Handler(); }
    master.MasterOutputTrigger = TIM_TRGO_UPDATE;
    master.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
    if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &master) != HAL_OK) {
        Error_Handler();
    }
}

static void MX_ADC1_Init(uint32_t board_adc_channel)
{
    ADC_ChannelConfTypeDef channel = {0};
    hadc1.Instance = ADC1;
    hadc1.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV2;
    hadc1.Init.Resolution = ADC_RESOLUTION_12B;
    hadc1.Init.ScanConvMode = DISABLE;
    hadc1.Init.ContinuousConvMode = DISABLE;
    hadc1.Init.DiscontinuousConvMode = DISABLE;
    hadc1.Init.NbrOfDiscConversion = 0u;
    hadc1.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_RISING;
    hadc1.Init.ExternalTrigConv = ADC_EXTERNALTRIGCONV_T2_TRGO;
    hadc1.Init.DataAlign = ADC_DATAALIGN_RIGHT;
    hadc1.Init.NbrOfConversion = 1u;
    hadc1.Init.DMAContinuousRequests = ENABLE;
    hadc1.Init.EOCSelection = ADC_EOC_SINGLE_CONV;
    if (HAL_ADC_Init(&hadc1) != HAL_OK) { Error_Handler(); }
    channel.Channel = board_adc_channel; /* Board-level value. */
    channel.Rank = 1u;
    channel.SamplingTime = ADC_SAMPLETIME_84CYCLES;
    channel.Offset = 0u;
    if (HAL_ADC_ConfigChannel(&hadc1, &channel) != HAL_OK) {
        Error_Handler();
    }
}

static void MX_USART2_UART_Init(void)
{
    huart2.Instance = USART2;
    huart2.Init.BaudRate = 115200u;
    huart2.Init.WordLength = UART_WORDLENGTH_8B;
    huart2.Init.StopBits = UART_STOPBITS_1;
    huart2.Init.Parity = UART_PARITY_NONE;
    huart2.Init.Mode = UART_MODE_TX;
    huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    huart2.Init.OverSampling = UART_OVERSAMPLING_16;
    if (HAL_UART_Init(&huart2) != HAL_OK) { Error_Handler(); }
    HAL_NVIC_SetPriority(USART2_IRQn, 6u, 0u);
    HAL_NVIC_EnableIRQ(USART2_IRQn);
}

void HAL_ADC_MspInit(ADC_HandleTypeDef *adc)
{
    if ((adc == NULL) || (adc->Instance != ADC1)) { return; }
    __HAL_RCC_ADC1_CLK_ENABLE();
    board_adc_gpio_init(); /* Board channel/pin/analog-mode injection. */
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
    if (HAL_DMA_Init(&hdma_adc1) != HAL_OK) { Error_Handler(); }
    __HAL_LINKDMA(adc, DMA_Handle, hdma_adc1);
}

void HAL_UART_MspInit(UART_HandleTypeDef *uart)
{
    if ((uart == NULL) || (uart->Instance != USART2)) { return; }
    __HAL_RCC_USART2_CLK_ENABLE();
    board_usart2_gpio_init(); /* Board TX pin/AF injection. */
    hdma_usart2_tx.Instance = DMA1_Stream6;
    hdma_usart2_tx.Init.Channel = DMA_CHANNEL_4;
    hdma_usart2_tx.Init.Direction = DMA_MEMORY_TO_PERIPH;
    hdma_usart2_tx.Init.PeriphInc = DMA_PINC_DISABLE;
    hdma_usart2_tx.Init.MemInc = DMA_MINC_ENABLE;
    hdma_usart2_tx.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
    hdma_usart2_tx.Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
    hdma_usart2_tx.Init.Mode = DMA_NORMAL;
    hdma_usart2_tx.Init.Priority = DMA_PRIORITY_MEDIUM;
    hdma_usart2_tx.Init.FIFOMode = DMA_FIFOMODE_DISABLE;
    if (HAL_DMA_Init(&hdma_usart2_tx) != HAL_OK) { Error_Handler(); }
    __HAL_LINKDMA(uart, hdmatx, hdma_usart2_tx);
}
```

字段含义：ADC `ContinuousConvMode=DISABLE` 保持“一次 TRGO 对应一次转换”，`DMAContinuousRequests=ENABLE` 允许持续 DMA 请求；ADC DMA 两端 half-word，一次请求搬一个 `uint16_t`；UART DMA 两端 byte，把同一半区按内存字节顺序发送；ADC circular 自动回卷，UART normal 每批重新武装；`__HAL_LINKDMA` 建立 HAL 句柄所有权关系。handle 和数组必须是静态生命周期，App 不拥有 stream 配置权。

#### 公开接口与五个动作

```c
/* capture_tx.h: declaration layer. */
#ifndef CAPTURE_TX_H
#define CAPTURE_TX_H
#include <stdint.h>
typedef enum {
    CAPTURE_TX_OK = 0,
    CAPTURE_TX_IDLE = 1,
    CAPTURE_TX_FAULT = 2,
    CAPTURE_TX_BAD_ARGUMENT = 3
} capture_tx_result_t;
capture_tx_result_t CaptureTx_Start(void);
capture_tx_result_t CaptureTx_Service(uint32_t now_ms);
capture_tx_result_t CaptureTx_Stop(void);
capture_tx_result_t CaptureTx_Recover(void);
uint32_t CaptureTx_FaultCode(void);
#endif
```

- **声明**：`capture_tx.h` 只暴露固定宽度接口；**实现**：F407 BSP 持有 HAL 与状态转换。
- **实例化**：BSP 中的数组、两个 half state、TX slot、当前首错与历史快照。
- **组装**：`main.c` 注入板级 ADC channel，按依赖顺序调用 `MX_*`，先 ADC DMA、后 TIM2。
- **使用**：App 周期调用 `CaptureTx_Service`，不直接改 HAL handle 或 DMA 寄存器。

#### 批次状态、回调和错误路径

以下属于 **F407 BSP 实现层**。ISR 只做常数时间检查、停源、快照和发布；HAL stop/abort 留给主控制流。短临界区仍须用目标的 IRQ 延迟测量验证。

```c
typedef enum {
    HALF_CAPTURING = 0,
    HALF_READY = 1,
    HALF_TX_OWNED = 2,
    HALF_RETURNED = 3
} half_state_t;

typedef enum {
    FAULT_NONE = 0,
    FAULT_CAPTURE_ORDER = 1,
    FAULT_REUSE_BUSY = 2,
    FAULT_TX_START = 3,
    FAULT_TX_DEADLINE = 4,
    FAULT_ADC_DMA = 5,
    FAULT_UART = 6,
    FAULT_STALE_CALLBACK = 7
} fault_code_t;

typedef struct {
    volatile half_state_t state;
    volatile uint32_t generation;
    volatile uint32_t deadline_ms;
} half_control_t;

typedef struct {
    volatile uint8_t active;
    volatile uint8_t half;
    volatile uint32_t generation;
    volatile uint32_t deadline_ms;
} tx_slot_t;

typedef struct {
    volatile fault_code_t first;
    volatile uint32_t session;
    volatile uint32_t tick_ms;
    volatile uint32_t adc_sr;
    volatile uint32_t dma2_lisr;
    volatile uint32_t dma1_hisr;
    volatile uint32_t usart_sr;
    volatile uint32_t adc_error;
    volatile uint32_t uart_error;
    volatile uint32_t adc_ndtr;
    volatile uint32_t tx_ndtr;
} fault_snapshot_t;

static half_control_t g_half[2];
static tx_slot_t g_tx;
static fault_snapshot_t g_current_fault;
static fault_snapshot_t g_history_fault;
static volatile uint32_t g_session;
static volatile uint8_t g_cleanup_pending;

static uint8_t deadline_reached(uint32_t now, uint32_t deadline)
{
    return ((int32_t)(now - deadline) >= 0) ? 1u : 0u;
}

static void stop_source_and_latch(fault_code_t code)
{
    uint32_t primask = __get_PRIMASK();

    __disable_irq();
    TIM2->CR1 &= ~TIM_CR1_CEN; /* First: stop future trigger source. */
    if (g_current_fault.first == FAULT_NONE) {
        g_current_fault.first = code;
        g_current_fault.session = g_session;
        g_current_fault.tick_ms = HAL_GetTick();
        g_current_fault.adc_sr = ADC1->SR;
        g_current_fault.dma2_lisr = DMA2->LISR;
        g_current_fault.dma1_hisr = DMA1->HISR;
        g_current_fault.usart_sr = USART2->SR;
        g_current_fault.adc_error = HAL_ADC_GetError(&hadc1);
        g_current_fault.uart_error = HAL_UART_GetError(&huart2);
        g_current_fault.adc_ndtr = DMA2_Stream0->NDTR;
        g_current_fault.tx_ndtr = DMA1_Stream6->NDTR;
        g_history_fault = g_current_fault;
    }
    g_cleanup_pending = 1u;
    if (primask == 0u) { __enable_irq(); }
}

static void publish_boundary(uint8_t finished, uint8_t next)
{
    uint32_t now = HAL_GetTick();

    if ((g_current_fault.first != FAULT_NONE) ||
        (g_half[finished].state != HALF_CAPTURING)) {
        stop_source_and_latch(FAULT_CAPTURE_ORDER);
        return;
    }
    if (g_half[next].state != HALF_RETURNED) {
        stop_source_and_latch(FAULT_REUSE_BUSY);
        return;
    }
    g_half[finished].generation++;
    g_half[finished].deadline_ms = now + 64u;
    g_half[finished].state = HALF_READY;
    g_half[next].state = HALF_CAPTURING;
}

static capture_tx_result_t try_start_ready_batch(void)
{
    uint8_t half;
    uint32_t primask = __get_PRIMASK();
    HAL_StatusTypeDef status;

    __disable_irq();
    if (g_current_fault.first != FAULT_NONE) {
        if (primask == 0u) { __enable_irq(); }
        return CAPTURE_TX_FAULT;
    }
    if (g_tx.active != 0u) {
        if (primask == 0u) { __enable_irq(); }
        return CAPTURE_TX_IDLE;
    }
    if (g_half[0].state == HALF_READY) {
        half = 0u;
    } else if (g_half[1].state == HALF_READY) {
        half = 1u;
    } else {
        if (primask == 0u) { __enable_irq(); }
        return CAPTURE_TX_IDLE;
    }
    g_half[half].state = HALF_TX_OWNED;
    g_tx.active = 1u;
    g_tx.half = half;
    g_tx.generation = g_half[half].generation;
    g_tx.deadline_ms = g_half[half].deadline_ms;

    /* Claim and DMA start acceptance form one atomic handoff. */
    status = HAL_UART_Transmit_DMA(
        &huart2,
        (uint8_t *)&g_samples[(uint32_t)half * HALF_SAMPLE_COUNT],
        (uint16_t)HALF_BYTE_COUNT);
    if (status != HAL_OK) {
        stop_source_and_latch(FAULT_TX_START);
        if (primask == 0u) { __enable_irq(); }
        return CAPTURE_TX_FAULT;
    }
    if (primask == 0u) { __enable_irq(); }
    return CAPTURE_TX_OK;
}

static capture_tx_result_t cleanup_hardware(void)
{
    HAL_StatusTypeDef tim_status;
    HAL_StatusTypeDef adc_status;
    HAL_StatusTypeDef uart_status;

    TIM2->CR1 &= ~TIM_CR1_CEN;
    tim_status = HAL_TIM_Base_Stop(&htim2);
    adc_status = HAL_ADC_Stop_DMA(&hadc1);
    uart_status = HAL_UART_AbortTransmit(&huart2);
    if ((tim_status != HAL_OK) || (adc_status != HAL_OK) ||
        (uart_status != HAL_OK)) {
        g_cleanup_pending = 1u;
        return CAPTURE_TX_FAULT;
    }
    g_tx.active = 0u;
    g_half[0].state = HALF_RETURNED;
    g_half[1].state = HALF_RETURNED;
    g_cleanup_pending = 0u;
    return CAPTURE_TX_OK;
}

capture_tx_result_t CaptureTx_Start(void)
{
    if ((g_cleanup_pending != 0u) ||
        (g_current_fault.first != FAULT_NONE)) {
        return CAPTURE_TX_FAULT;
    }
    g_session++;
    g_half[0].state = HALF_CAPTURING;
    g_half[1].state = HALF_RETURNED;
    g_half[0].generation = 0u;
    g_half[1].generation = 0u;
    g_tx.active = 0u;
    if (HAL_ADC_Start_DMA(&hadc1, (uint32_t *)g_samples,
                          SAMPLE_COUNT) != HAL_OK) {
        stop_source_and_latch(FAULT_ADC_DMA);
        return CAPTURE_TX_FAULT;
    }
    if (HAL_TIM_Base_Start(&htim2) != HAL_OK) {
        (void)HAL_ADC_Stop_DMA(&hadc1);
        stop_source_and_latch(FAULT_CAPTURE_ORDER);
        return CAPTURE_TX_FAULT;
    }
    return CAPTURE_TX_OK;
}

capture_tx_result_t CaptureTx_Service(uint32_t now_ms)
{
    uint32_t primask;
    uint8_t deadline_fault = 0u;

    if (g_cleanup_pending != 0u) {
        (void)cleanup_hardware();
        return CAPTURE_TX_FAULT;
    }
    if (g_current_fault.first != FAULT_NONE) {
        return CAPTURE_TX_FAULT;
    }

    /* Keep the active/deadline decision atomic with respect to TX complete. */
    primask = __get_PRIMASK();
    __disable_irq();
    if ((g_tx.active != 0u) &&
        (deadline_reached(now_ms, g_tx.deadline_ms) != 0u)) {
        stop_source_and_latch(FAULT_TX_DEADLINE);
        deadline_fault = 1u;
    }
    if (primask == 0u) { __enable_irq(); }
    if (deadline_fault != 0u) {
        return CAPTURE_TX_FAULT;
    }
    return try_start_ready_batch();
}

capture_tx_result_t CaptureTx_Stop(void)
{
    return cleanup_hardware();
}

capture_tx_result_t CaptureTx_Recover(void)
{
    if (g_current_fault.first == FAULT_NONE) {
        return CAPTURE_TX_BAD_ARGUMENT;
    }
    if (CaptureTx_Stop() != CAPTURE_TX_OK) {
        return CAPTURE_TX_FAULT;
    }
    g_current_fault = (fault_snapshot_t){0};
    return CaptureTx_Start();
}

uint32_t CaptureTx_FaultCode(void)
{
    return (uint32_t)g_current_fault.first;
}

void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef *adc)
{
    if ((adc != NULL) && (adc->Instance == ADC1)) {
        publish_boundary(0u, 1u);
    }
}

void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *adc)
{
    if ((adc != NULL) && (adc->Instance == ADC1)) {
        publish_boundary(1u, 0u);
    }
}

void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *adc)
{
    if ((adc != NULL) && (adc->Instance == ADC1)) {
        stop_source_and_latch(FAULT_ADC_DMA);
    }
}

void HAL_UART_TxCpltCallback(UART_HandleTypeDef *uart)
{
    uint8_t half;
    if ((uart == NULL) || (uart->Instance != USART2)) { return; }
    if (g_tx.active == 0u) {
        stop_source_and_latch(FAULT_STALE_CALLBACK);
        return;
    }
    half = g_tx.half;
    if ((g_half[half].state != HALF_TX_OWNED) ||
        (g_half[half].generation != g_tx.generation)) {
        stop_source_and_latch(FAULT_STALE_CALLBACK);
        return;
    }
    /* Service and this IRQ must apply the same half-open deadline rule. */
    if (deadline_reached(HAL_GetTick(), g_tx.deadline_ms) != 0u) {
        stop_source_and_latch(FAULT_TX_DEADLINE);
        return;
    }
    g_half[half].state = HALF_RETURNED;
    g_tx.active = 0u;
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *uart)
{
    if ((uart != NULL) && (uart->Instance == USART2)) {
        stop_source_and_latch(FAULT_UART);
    }
}
```

`CaptureTx_Service` 与 `HAL_UART_TxCpltCallback` 都使用同一半开区间截止规则：完成回调只有在 `now < deadline` 时归还半区；这样即使完成 IRQ 与主循环超期检查竞争，也不会把截止时刻或之后的完成误判为成功。`HAL_ADC_ErrorCallback` 同时承接 ADC/DMA 错误；`HAL_UART_ErrorCallback` 承接 UART/DMA 发送错误路径。STM32CubeF4 v1.28.3 源码确认阻塞式 `HAL_UART_AbortTransmit` 在成功返回前关闭 TXE/TC 中断与 DMAT、以无回调方式 abort TX DMA，并把 UART TX 状态恢复为 ready；若 DMA abort 超时则返回失败，因此上面的恢复路径必须检查返回值。[S5] 首错写入 `g_history_fault` 后不再被清理副作用覆盖。生产实现还应把历史快照暴露为只读诊断接口。

IRQ 入口先保存只读现场，因为 HAL 分发可能清标志：

```c
void DMA2_Stream0_IRQHandler(void)
{
    if (g_current_fault.first == FAULT_NONE) {
        g_current_fault.adc_sr = ADC1->SR;
        g_current_fault.dma2_lisr = DMA2->LISR;
        g_current_fault.adc_ndtr = DMA2_Stream0->NDTR;
    }
    HAL_DMA_IRQHandler(&hdma_adc1);
}

void DMA1_Stream6_IRQHandler(void)
{
    if (g_current_fault.first == FAULT_NONE) {
        g_current_fault.dma1_hisr = DMA1->HISR;
        g_current_fault.tx_ndtr = DMA1_Stream6->NDTR;
    }
    HAL_DMA_IRQHandler(&hdma_usart2_tx);
}

void USART2_IRQHandler(void)
{
    if (g_current_fault.first == FAULT_NONE) {
        g_current_fault.usart_sr = USART2->SR;
    }
    HAL_UART_IRQHandler(&huart2);
}
```

若 IRQ 可嵌套，应按入口分开快照槽或提供可证明的同步。不要在 IRQ 中打印、格式化 128 byte、重配 DMA 或复位 DMA1/DMA2。

#### HAL 到 LL/寄存器交叉核对

| HAL 意图 | LL/关键寄存器状态 | 运行时证据 |
| --- | --- | --- |
| TIM master update + base start | `TIM2_PSC=83`、`ARR=999`、`CR2.MMS=update`、`CR1.CEN=1` | `CNT/UIF`；仍不证明 ADC 接收触发 |
| ADC T2_TRGO rising | `ADC_CR2.EXTSEL/EXTEN`，`CONT=0` | EOC/OVR 与 `DR`；位编码按 RM0090 |
| ADC DMA continuous | `ADC_CR2.DMA/DDS` | DMA2 S0 `NDTR` 按样本递减 |
| ADC circular half-word | DMA2 S0 CHSEL=0、P2M、CIRC、MINC、PSIZE/MSIZE；`PAR=&ADC1_DR`、`M0AR=g_samples` | HTIF0/TCIF0/TEIF0/DMEIF0/FEIF0 |
| UART 115200 8N1 TX | `USART2_BRR`、CR1 UE/TE/word/parity、CR2 STOP | TXE/TC 与外部串行帧；BRR 按实际 PCLK1 |
| UART TX DMA | `USART2_CR3.DMAT`；DMA1 S6 CHSEL=4、M2P、MINC、byte、normal；`PAR=&USART2_DR` | DMA flags/S6NDTR，最后还要 USART TC |
| `HAL_UART_TxCpltCallback` | DMA 和 USART TC 路径均完成 | 此时才把 `TX_OWNED` 改为 `RETURNED` |

不要在 HAL 正管理 stream 时用 LL 重配它。LL 用于解释和只读核对；若改用 LL，就由 LL 适配层完整拥有初始化、IRQ、清标志和停止。DMA flag bank、清除寄存器及写 1 清除语义必须逐项按 RM0090 核对。[S1][S3][S4]

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

Host Fake 把一个 tick 当作 1 ms，只模拟批次边界、TX 完成、时间推进和错误注入。它不模拟“DMA 在 tick 内搬了多少字节”，因此测试通过只证明有界协议自洽。

下面是完整 C11 模型。Reviewer 于 2026-10-17 从本代码围栏原样提取源码，使用 GCC 16.2.0 和 `-std=c11 -Wall -Wextra -Werror -pedantic` 编译并执行；编译与测试退出码均为 0，完整命令和边界记录在本次运行目录的 `review.md`。该结果只证明 Host Fake 断言通过，不是 STM32 目标构建证据。

```c
#include <assert.h>
#include <stdint.h>
#include <string.h>

#define F_HALF_COUNT 2u
#define F_SAMPLE_COUNT 8u
#define F_HALF_SAMPLES 4u
#define F_HALF_BYTES 8u
#define F_REUSE_TICKS 64u

typedef enum { F_OK = 0, F_IDLE, F_FAULTED, F_BAD_ARGUMENT } f_result_t;
typedef enum { F_CAPTURING = 0, F_READY, F_TX_OWNED, F_RETURNED } f_state_t;
typedef enum {
    F_ERR_NONE = 0,
    F_ERR_NOT_RUNNING,
    F_ERR_CAPTURE_ORDER,
    F_ERR_REUSE_BUSY,
    F_ERR_TX_BUSY,
    F_ERR_TX_DEADLINE,
    F_ERR_TX,
    F_ERR_CAPTURE,
    F_ERR_STALE_COMPLETE
} f_error_t;

typedef struct {
    f_state_t state;
    uint32_t generation;
    uint32_t deadline;
} f_half_t;

typedef struct {
    uint8_t active;
    uint8_t half;
    uint32_t generation;
    uint32_t deadline;
    const uint8_t *data;
    uint16_t bytes;
} f_tx_t;

typedef struct {
    uint8_t valid;
    f_error_t code;
    uint32_t session;
    uint32_t tick;
    uint8_t tx_active;
    uint8_t tx_half;
    uint32_t tx_generation;
} f_fault_t;

typedef struct {
    uint16_t samples[F_SAMPLE_COUNT];
    f_half_t half[F_HALF_COUNT];
    f_tx_t tx;
    f_fault_t first;
    f_fault_t history;
    uint32_t session;
    uint32_t now;
    uint8_t armed;
    uint8_t source_running;
    uint8_t cleanup_pending;
} f_system_t;

static uint8_t reached(uint32_t now, uint32_t deadline)
{
    return ((int32_t)(now - deadline) >= 0) ? 1u : 0u;
}

static void stop_and_latch(f_system_t *s, f_error_t code)
{
    if (s == NULL) { return; }
    s->source_running = 0u; /* The first observable fault action. */
    if (s->first.valid == 0u) {
        s->first.valid = 1u;
        s->first.code = code;
        s->first.session = s->session;
        s->first.tick = s->now;
        s->first.tx_active = s->tx.active;
        s->first.tx_half = s->tx.half;
        s->first.tx_generation = s->tx.generation;
        s->history = s->first;
    }
    s->cleanup_pending = 1u;
}

static void f_init(f_system_t *s)
{
    if (s != NULL) {
        (void)memset(s, 0, sizeof(*s));
        s->half[0].state = F_RETURNED;
        s->half[1].state = F_RETURNED;
    }
}

static f_result_t f_start(f_system_t *s, uint32_t now)
{
    if (s == NULL) { return F_BAD_ARGUMENT; }
    if ((s->source_running != 0u) || (s->cleanup_pending != 0u)) {
        return F_BAD_ARGUMENT;
    }
    s->session++;
    s->now = now;
    s->armed = 1u; /* Arm receiver first. */
    s->half[0].state = F_CAPTURING;
    s->half[1].state = F_RETURNED;
    s->half[0].generation = 0u;
    s->half[1].generation = 0u;
    s->tx.active = 0u;
    (void)memset(&s->first, 0, sizeof(s->first));
    s->source_running = 1u; /* Start source last. */
    return F_OK;
}

static f_result_t f_boundary(f_system_t *s, uint8_t done, uint32_t now)
{
    uint8_t next;
    if ((s == NULL) || (done >= F_HALF_COUNT)) { return F_BAD_ARGUMENT; }
    s->now = now;
    if ((s->armed == 0u) || (s->source_running == 0u)) {
        stop_and_latch(s, F_ERR_NOT_RUNNING);
        return F_FAULTED;
    }
    next = (uint8_t)(done ^ 1u);
    if (s->half[done].state != F_CAPTURING) {
        stop_and_latch(s, F_ERR_CAPTURE_ORDER);
        return F_FAULTED;
    }
    if (s->half[next].state != F_RETURNED) {
        stop_and_latch(s, F_ERR_REUSE_BUSY);
        return F_FAULTED;
    }
    s->half[done].generation++;
    s->half[done].deadline = now + F_REUSE_TICKS;
    s->half[done].state = F_READY;
    s->half[next].state = F_CAPTURING;
    return F_OK;
}

static f_result_t f_submit(f_system_t *s)
{
    uint8_t half;
    if (s == NULL) { return F_BAD_ARGUMENT; }
    if (s->first.valid != 0u) { return F_FAULTED; }
    if (s->tx.active != 0u) {
        stop_and_latch(s, F_ERR_TX_BUSY);
        return F_FAULTED;
    }
    if (s->half[0].state == F_READY) { half = 0u; }
    else if (s->half[1].state == F_READY) { half = 1u; }
    else { return F_IDLE; }
    s->half[half].state = F_TX_OWNED;
    s->tx.active = 1u;
    s->tx.half = half;
    s->tx.generation = s->half[half].generation;
    s->tx.deadline = s->half[half].deadline;
    s->tx.data = (const uint8_t *)&s->samples[(uint32_t)half * F_HALF_SAMPLES];
    s->tx.bytes = F_HALF_BYTES;
    return F_OK;
}

static f_result_t f_complete(f_system_t *s, uint8_t half,
                             uint32_t generation, uint32_t now)
{
    if ((s == NULL) || (half >= F_HALF_COUNT)) { return F_BAD_ARGUMENT; }
    s->now = now;
    if ((s->tx.active == 0u) || (s->tx.half != half) ||
        (s->tx.generation != generation) ||
        (s->half[half].state != F_TX_OWNED)) {
        stop_and_latch(s, F_ERR_STALE_COMPLETE);
        return F_FAULTED;
    }
    if (reached(now, s->tx.deadline) != 0u) {
        stop_and_latch(s, F_ERR_TX_DEADLINE);
        return F_FAULTED;
    }
    s->half[half].state = F_RETURNED;
    s->tx.active = 0u;
    return F_OK;
}

static f_result_t f_poll(f_system_t *s, uint32_t now)
{
    if (s == NULL) { return F_BAD_ARGUMENT; }
    s->now = now;
    if ((s->tx.active != 0u) && (reached(now, s->tx.deadline) != 0u)) {
        stop_and_latch(s, F_ERR_TX_DEADLINE);
        return F_FAULTED;
    }
    return (s->first.valid != 0u) ? F_FAULTED : F_OK;
}

static f_result_t f_inject(f_system_t *s, f_error_t code, uint32_t now)
{
    if ((s == NULL) || ((code != F_ERR_TX) && (code != F_ERR_CAPTURE))) {
        return F_BAD_ARGUMENT;
    }
    s->now = now;
    stop_and_latch(s, code);
    return F_FAULTED;
}

static f_result_t f_cleanup(f_system_t *s)
{
    if (s == NULL) { return F_BAD_ARGUMENT; }
    s->source_running = 0u;
    s->armed = 0u;
    s->tx.active = 0u;
    s->half[0].state = F_RETURNED;
    s->half[1].state = F_RETURNED;
    s->cleanup_pending = 0u;
    return F_OK;
}

static f_result_t f_recover(f_system_t *s, uint32_t now)
{
    if ((s == NULL) || (s->first.valid == 0u)) { return F_BAD_ARGUMENT; }
    if (f_cleanup(s) != F_OK) { return F_FAULTED; }
    return f_start(s, now);
}

static void test_normal(void)
{
    f_system_t s;
    uint32_t generation;
    f_init(&s);
    assert(f_start(&s, 0u) == F_OK);
    assert(f_boundary(&s, 0u, 64u) == F_OK);
    assert(f_submit(&s) == F_OK);
    assert(s.tx.data == (const uint8_t *)&s.samples[0]);
    assert(s.tx.bytes == F_HALF_BYTES);
    generation = s.tx.generation;
    assert(f_complete(&s, 0u, generation, 76u) == F_OK);
    assert(f_boundary(&s, 1u, 128u) == F_OK);
    assert(f_submit(&s) == F_OK);
    generation = s.tx.generation;
    assert(f_complete(&s, 1u, generation, 140u) == F_OK);
    assert(f_boundary(&s, 0u, 192u) == F_OK);
    assert(s.first.valid == 0u);
    assert(s.half[0].generation == 2u);
}

static void test_reuse_busy(void)
{
    f_system_t s;
    f_init(&s);
    assert(f_start(&s, 0u) == F_OK);
    assert(f_boundary(&s, 0u, 64u) == F_OK);
    assert(f_submit(&s) == F_OK);
    assert(f_boundary(&s, 1u, 128u) == F_FAULTED);
    assert(s.source_running == 0u);
    assert(s.first.code == F_ERR_REUSE_BUSY);
}

static void test_deadline_first_fault(void)
{
    f_system_t s;
    f_system_t late_complete;
    f_init(&s);
    assert(f_start(&s, 0u) == F_OK);
    assert(f_boundary(&s, 0u, 64u) == F_OK);
    assert(f_submit(&s) == F_OK);
    assert(f_poll(&s, 128u) == F_FAULTED);
    assert(s.first.code == F_ERR_TX_DEADLINE);
    assert(f_inject(&s, F_ERR_TX, 129u) == F_FAULTED);
    assert(s.first.code == F_ERR_TX_DEADLINE); /* First fault is retained. */

    f_init(&late_complete);
    assert(f_start(&late_complete, 0u) == F_OK);
    assert(f_boundary(&late_complete, 0u, 64u) == F_OK);
    assert(f_submit(&late_complete) == F_OK);
    assert(f_complete(&late_complete, 0u, late_complete.tx.generation,
                      128u) == F_FAULTED);
    assert(late_complete.first.code == F_ERR_TX_DEADLINE);
}

static void test_errors_and_recovery(void)
{
    f_system_t s;
    f_system_t tx;
    uint32_t old_session;

    f_init(&tx);
    assert(f_start(&tx, 0u) == F_OK);
    assert(f_boundary(&tx, 0u, 64u) == F_OK);
    assert(f_submit(&tx) == F_OK);
    assert(f_inject(&tx, F_ERR_TX, 70u) == F_FAULTED);
    assert(tx.source_running == 0u);
    assert(tx.first.code == F_ERR_TX);

    f_init(&s);
    assert(f_start(&s, 0u) == F_OK);
    assert(f_inject(&s, F_ERR_CAPTURE, 10u) == F_FAULTED);
    assert(s.source_running == 0u);
    old_session = s.session;
    assert(f_recover(&s, 100u) == F_OK);
    assert(s.session == old_session + 1u);
    assert(s.first.valid == 0u);
    assert(s.history.code == F_ERR_CAPTURE);
}

static void test_invalid_and_stale(void)
{
    f_system_t s;
    f_system_t duplicate;
    f_system_t busy;
    f_init(&s);
    assert(f_boundary(&s, 2u, 0u) == F_BAD_ARGUMENT);
    assert(f_submit(&s) == F_IDLE);
    assert(f_boundary(&s, 0u, 1u) == F_FAULTED);

    f_init(&duplicate);
    assert(f_start(&duplicate, 0u) == F_OK);
    assert(f_boundary(&duplicate, 0u, 64u) == F_OK);
    assert(f_boundary(&duplicate, 0u, 65u) == F_FAULTED);
    assert(duplicate.first.code == F_ERR_CAPTURE_ORDER);

    f_init(&busy);
    assert(f_start(&busy, 0u) == F_OK);
    assert(f_boundary(&busy, 0u, 64u) == F_OK);
    assert(f_submit(&busy) == F_OK);
    assert(f_submit(&busy) == F_FAULTED);
    assert(busy.first.code == F_ERR_TX_BUSY);

    f_init(&s);
    assert(f_start(&s, 0u) == F_OK);
    assert(f_boundary(&s, 0u, 64u) == F_OK);
    assert(f_submit(&s) == F_OK);
    assert(f_complete(&s, 0u, s.tx.generation + 1u, 70u) == F_FAULTED);
    assert(s.first.code == F_ERR_STALE_COMPLETE);
}

int main(void)
{
    test_normal();
    test_reuse_busy();
    test_deadline_first_fault();
    test_errors_and_recovery();
    test_invalid_and_stale();
    return 0;
}
```

代码已显式断言第二次 `f_submit` 触发 TX busy、TX/capture error、非法 half、空 submit、重复 boundary、旧 generation、截止时刻才完成和恢复后的新 session。继续扩展时还应验证 `NULL` 参数不改变有效对象。本次 Reviewer 已把编译器版本、`-std=c11`、严格 warning、编译退出码和测试退出码写入运行记录；代码展示本身仍不是构建证据。

### 8.2 STM32 参考实现轨道

硬件轨道按以下证据层级推进：

1. **资料审计**：用 RM0090 核对 TIM2 TRGO、ADC1 DMA2 S0/C0、USART2_TX DMA1 S6/C4、flag bank 和清除顺序；用固定 CubeF4 源码核对 HAL 回调路径。
2. **生成代码审计**：检查 `.ioc`、`MX_*`、MSP、`__HAL_LINKDMA`、NVIC 和初始化顺序；生成成功不等于构建成功。
3. **目标构建**：保存完整 MCU/板卡、工具链、Cube 版本、clean build 命令、输出、warning、退出码和产物哈希。
4. **寄存器读回**：源未启动时核对静态配置；启动后只读观察 CEN、ADC trigger/DMA、两个 stream 的 CR/PAR/M0AR/NDTR、USART BRR/DMAT。
5. **运行测量**：记录 HT/TC/TX complete 的会话与代次、最坏时延、串行接收长度/内容和故障停源顺序。

当前只交付前两层的参考清单与代码，没有 3-5 层证据，不能声称目标代码已编译、已烧录或硬件链已经工作。

板级必须填写：完整 MCU marking、板卡/原理图版本、供电与时钟源、ADC channel/pin/输入条件、USART2 TX pin/AF/电平/对端、调试器、CubeMX/CubeMX2、STM32CubeF4 和编译器版本。缺一项就标为阻塞，不能用本课参考值代填。

## 9. 最小代码示例

最小使用代码属于 **App 使用层**。它与 7.3 的 `static MX_*` 参考初始化位于同一 `main.c` 翻译单元；若工程把 BSP 拆到其他文件，组合根必须改为调用有头文件声明的非 `static` 初始化接口，不能跨文件调用静态函数。组合根完成 HAL、时钟、DMA、GPIO、ADC、TIM 和 UART 初始化；App 只驱动会话：

```c
#include "capture_tx.h"
#include "stm32f4xx_hal.h"

int main(void)
{
    HAL_Init();
    SystemClock_Config();
    MX_DMA_Init();
    MX_TIM2_Init();
    MX_ADC1_Init(board_adc_channel());
    MX_USART2_UART_Init();

    if (CaptureTx_Start() != CAPTURE_TX_OK) { Error_Handler(); }
    for (;;) {
        capture_tx_result_t result = CaptureTx_Service(HAL_GetTick());
        if (result == CAPTURE_TX_FAULT) {
            while (user_requested_recovery() == 0u) {
                report_fault_without_blocking(CaptureTx_FaultCode());
            }
            if (CaptureTx_Recover() != CAPTURE_TX_OK) { Error_Handler(); }
        }
    }
}
```

初始化顺序体现所有权：共享时钟由组合根持有；BSP 实例化 handles 和 buffer；MSP 把 DMA 注入 ADC/UART handle；`CaptureTx_Start` 先武装接收端、后启动 TIM2；App 只消费状态。两个应用策略函数必须由实际工程定义，且故障报告不能阻塞在被诊断的 USART2 发送路径上。

## 10. 常见错误

1. **HT 后立刻把 A 标为可重用**：HT 只说明采集者写完 A；发送 DMA 完成并回调后才归还 A。
2. **把两个 DMA 都设成 circular**：UART TX 会无限重发旧半区，App 失去逐批提交和归还边界。本课 TX 使用 normal mode。
3. **只检查 `HAL_UART_Transmit_DMA == HAL_OK`**：它只表示启动被接受，不表示数据已离开 USART 停止位；归还必须等 TX complete。
4. **只开 DMA1 Stream6 IRQ**：DMA 计数归零与 USART TC 不同；HAL normal TX 的最终完成还需要 USART2 IRQ 路径。
5. **在 TC 回调才发现 A 未归还，却继续运行**：DMA 正准备回卷；必须先停源，不得把 A 当作仍然稳定。
6. **在回调中调用阻塞发送/打印**：会扩大边界 IRQ 延迟，甚至让下一触发先发生。回调只发布或锁存。
7. **用一个 ready bit 表示所有批次**：重复事件会合并，旧完成可能归还新一轮同半区。必须携带 generation。
8. **把 `NDTR=0` 当成线已空闲**：TX DMA 可能只把最后 byte 交给 USART，移位器仍在发送；还需 TC。
9. **ADC DMA 与 UART DMA 宽度都设 half-word**：UART DR 的发送数据单元与本课 byte 流契约不符；两条 DMA 的宽度职责不同。
10. **把 64 samples 当成 64 byte**：本课每 sample 是 `uint16_t`，一批是 128 byte；HAL UART size 参数按 byte 计。
11. **未定义线上的批次边界**：固定 128 byte 只能在双方预先同步时解码；加入 header/length/CRC 是后续协议概念，不在本课暗中实现。
12. **错误时先 abort 再快照**：HAL 可能改变 state、NDTR 或 flags。先停源和只读保存，再做清理。
13. **在局部错误里 reset DMA1/DMA2**：控制器含其他 stream；只有知道全部使用者的组合根才可整体 reset。
14. **把 `volatile` 当并发协议**：它不保证多字段一致快照、不提供批次所有权，也不能阻止 DMA 写内存。
15. **断点下判断实时性**：CPU 停止时外设可能继续，人工制造重用、OVR 或超期。实时预算用计数器、GPIO 时间戳或外部仪器自由运行测量。
16. **复制 F407 映射到 F7/H5/H7**：请求控制器、stream/request、内存域、缓存和安全属性可能不同；只保留分析方法。

## 11. 调试观察点

从源到消费者逐段采证，不从末端失败直接猜配置：

| 顺序 | 观察点 | 期望证据 | 仍不能证明 |
| --- | --- | --- | --- |
| 1 | RCC/clock | PLL ready/switch；TIM2/USART2/ADC1/DMA1/2 clocks enabled | 实际频率与容差已经测量 |
| 2 | TIM2 static | PSC=83、ARR=999、MMS=update | source 已运行 |
| 3 | TIM2 runtime | CEN=1、CNT/UIF 周期变化 | ADC 接受 TRGO |
| 4 | ADC | EXTSEL/EXTEN、CONT=0、DMA/DDS；DR/EOC | DMA request 已到达正确 stream |
| 5 | DMA2 S0 | CHSEL=0、P2M/circular/half-word、地址、NDTR、HT/TC | App/TX 及时归还 |
| 6 | batch controller | half state、generation、deadline、session | UART 线上内容正确 |
| 7 | DMA1 S6 | CHSEL=4、M2P/normal/byte、M0AR、NDTR | 最后 stop bit 已完成 |
| 8 | USART2 | BRR/TE/DMAT/TXE/TC、HAL gState/error | 对端已正确分批解析 |
| 9 | external receiver | 每批 128 byte、代次对应的内容和时间 | ADC 模拟精度合格 |

故障树：

```text
TIM2 CNT 不动
  -> 查 clock switch/APB1、TIM2EN/reset/CEN

CNT/UIF 正常，DMA2 NDTR 不动
  -> 查 MMS -> ADC EXTSEL/EXTEN -> ADC DMA/DDS -> S0 channel/address/EN

HT/TC 不来
  -> 查 DMA flags、interrupt enable、NVIC、vector 和 HAL handle link

批次 READY，DMA1 S6 不动
  -> 查 HAL gState、S6 mapping、M0AR/PAR/NDTR、USART2 DMAT/TXE

DMA1 NDTR 到零，无 TxCplt
  -> 查 USART2 TC/TCIE、USART2 IRQ enable/vector、HAL UART IRQ

REUSE_BUSY/TX_DEADLINE
  -> 保存 session/half/generation/deadline、S6 NDTR、IRQ latency；不要继续发送该批

TE/DME/FE 或 UART error
  -> 先确认 TIM2 CEN 已清，再读首错快照，核对地址、宽度、可达内存和 flag bank
```

推荐断点只用于控制流：`CaptureTx_Start` 两个 start 调用、`publish_boundary`、`HAL_UART_TxCpltCallback`、`stop_source_and_latch` 和 deferred cleanup。时间测量不要依赖断点。

## 12. 实战实验

### 实验 A：Host Fake 正常 A/B 交替

1. 将 8.1 的代码放入独立主机工程，以 C11 和 warnings-as-errors 编译；保存命令、编译器版本、完整输出和退出码。
2. 运行 `test_normal`，记录每个 boundary、submit、complete 后 A/B state、generation 和 TX slot。
3. 证明任何时刻只有一个 `TX_OWNED`，且 next half 进入 `CAPTURING` 前已是 `RETURNED`。
4. 将 complete 从 tick 76 改到 127，仍应成功；改到 128，应超期失败。

合格结论只限于模型协议，不是 F407 DMA 证据。

### 实验 B：背压、错误与首错

1. 发布 A 并启动 TX，不调用 complete；在 tick 128 发布 B，确认 `REUSE_BUSY` 且 `source_running=0`。
2. 对同一个 READY 批次调用两次 submit，确认第二次锁存 `TX_BUSY`，没有第二个发送槽。
3. 分别注入 TX error 与 capture error；确认都先停源，不产生成功归还。
4. 超期后再注入 TX error，确认 `first.code` 仍为 `TX_DEADLINE`。
5. 注入错误 generation 的 complete，确认旧回调不能归还当前批次。

### 实验 C：停止与新会话恢复

1. 在 A 被 TX 持有时注入错误，记录历史快照。
2. 执行 cleanup，确认 armed/source/TX 全部关闭，A/B 不再有活动所有者；任一 stop/abort 失败时不得开始新会话。
3. 显式 recover，确认只有清理成功后 session 才增加、当前首错清空、历史首错仍可查。
4. 可扩展 Fake 让应用事件携带 session，并断言旧应用事件被拒绝；这只验证上层事件协议。F407 HAL 回调本身不携带 session，硬件轨道必须通过成功的阻塞式 abort、DMA flag 清理和 IRQ 源静默来排除旧完成事件。

### 实验 D：CubeMX 静态审计

1. 固定完整 F407 料号和板级 ADC/USART 连接；未固定则将实验标记为阻塞。
2. 按 7.3 创建 `.ioc`，记录 CubeMX/CubeMX2 与 CubeF4 版本。
3. 搜索清单中的常量、stream/channel、link 和三个 IRQ。
4. 检查 `MX_DMA_Init` 在 ADC/UART init 之前；检查 ADC DMA start 在 TIM2 start 之前。
5. 生成 HAL 字段、LL 读值、预期寄存器字段的交叉表。静态审计不构成目标构建证据。

### 实验 E：目标构建、读回与内容核对计划

1. 保存板卡、MCU marking、原理图、ADC 输入、USART 对端、调试器、Cube 和工具链版本。
2. clean build 并保存日志、退出码、warning 和固件哈希；当前课程未执行。
3. 源未启动时读回时钟、PSC/ARR/MMS、ADC trigger/DMA、两个 DMA stream 和 USART BRR/format。
4. 越过 `HAL_ADC_Start_DMA`，确认 ADC/DMA2 已武装；再启动 TIM2。
5. 对端按固定 128 byte 收批；用已知稳定 ADC 输入核对每批内容不会跨代次混合。原始 `uint16_t` 的内存字节序必须记录。
6. 记录 HT/TC/TX complete 的 session、half、generation 与时间戳，统计最坏而不是平均延迟。

### 实验 F：真实背压和停源证据计划

1. 临时降低 UART baud 或扩大 batch，使 TX 超过 64 ms；不要改成越界电气条件。
2. 观察首错入口立即清 TIM2 CEN，随后 DMA2 NDTR 不再因新触发递减；记录从 boundary IRQ 到停源的最大延迟。
3. 核对故障批次没有被报告为成功，没有自动重启。
4. 人工确认恢复后 session 增加，再检查新的 A/B 交替。
5. 当前没有执行这些步骤，不能填写波形、测量值或“通过”。

### 实验 G：F7/H5/H7 迁移审计

为一个具体完整料号填写：timer/ADC/UART kernel clocks、合法 trigger route、DMA/DMAMUX/GPDMA request、IRQ/flag、buffer 可达内存、cache line/MPU、TrustZone/安全归属和目标 Cube 包版本。空项表示迁移未完成，不能拿 F407 值代填。

## 13. 自检题

1. 为什么 HT 发生后 A 不是立即可重用，而只是从采集写者交给消费者？
2. A 发布到再次写 A 的窗口为何是 64 个触发周期，而不是整个 128 个周期？
3. `HAL_UART_Transmit_DMA` 返回 `HAL_OK` 能证明什么，不能证明什么？
4. 为什么 DMA1 Stream6 `NDTR=0` 后仍需等 USART TC？
5. `READY`、`TX_OWNED`、`RETURNED` 分别允许谁访问半区？
6. generation 如何阻止旧 TX complete 归还新一轮 A？为什么 half index 不够？
7. TC 到来时 A 仍为 `TX_OWNED`，为何必须先停 TIM2？
8. `T_line_nominal=11.11 ms` 为什么不等于已证明的最坏发送时间？
9. 发生 TE 后为何先快照再 abort？为何不能直接 reset DMA1？
10. Host Fake 的 `source_running=0` 能证明真实 TIM2 在下一触发前停住吗？
11. ADC DMA 为什么用 half-word，UART DMA 为什么用 byte？HAL 的 length 单位分别是什么？
12. 从 F407 迁移到 H7，哪些所有权不变量保留，哪些硬件事实必须重查？

作答时应明确对象、持有者、注入者、控制/事件/数据流和证据类型，不能只回答“加锁”或“看回调”。

## 14. 面试题

### 14.1 两个 DMA 如何零拷贝共享一块循环缓冲区而不互相破坏？

答案应包含：按稳定批次交接；生产写与消费读互斥；发送槽锁定地址、长度、代次和 deadline；完成才归还；重用前未归还则停源；错误保存首错并显式恢复。零拷贝减少 CPU copy，不取消生命周期约束。

### 14.2 如何计算“UART 足够快”？

先从 batch byte、每 byte line bits 与实际 baud 下界算线速时间，再加入 DMA 供给间隙、领取延迟和 completion IRQ 最坏延迟，与 `T_half` 严格比较并留 margin。平均值、标称 baud 和一次正常波形不足以证明。

### 14.3 为什么 TX DMA complete 和 UART transmission complete 不是一回事？

前者表示 DMA 已把最后数据项交给外设；USART 仍可能在数据/移位寄存器中发送。内存何时可以归还取决于接口契约：若最后 byte 已被 DMA 读走，物理上内存可能已不再需要，但本课故意以最终 TX complete 作为单一、易审计的归还点，避免 HAL 事件语义混淆。

### 14.4 为什么背压策略选择停源，而不是覆盖旧批次或排队？

两半区容量固定，覆盖会形成不可检测的混合批；无界排队违反内存边界。停源使数据损失显式化并保留首错。其他策略可以设计，但必须定义容量、丢弃规则和可观察证据。

### 14.5 F7/H7 加 D-Cache 后协议要增加什么？

不仅是“调用 cache API”。必须固定 buffer 所在内存、DMA 可达性、cache line 对齐和范围；在所有权交接点按方向执行正确 clean/invalidate；用 barrier/MPU 策略和目标资料证明可见性。具体顺序属于 `dma-coherency` 后续课。

### 14.6 如何区分一次错误的根因和清理副作用？

第一错误入口先停源并冻结寄存器、HAL error、NDTR、session/half/generation；后续 abort 或迟到 IRQ 只记附加计数，不覆盖 first fault。恢复建立新 session，但保留历史快照。

## 15. 延伸思考

1. 若要在固定 128 byte 前加入 magic、length、generation 和 CRC，怎样保持 DMA 零拷贝？需要 scatter-gather、预留头部还是单独发送？
2. 多通道 ADC 的一个 frame 含多个 rank 时，半区长度必须如何对齐 frame，才能避免发送半帧？
3. 使用 DMA double-buffer 后，current target 与软件 state 如何交叉核对？它能消除哪类竞争，仍保留哪类 deadline？
4. 若允许“丢最新批次继续采集”，怎样证明被发送的旧批次未被 DMA 重用？诊断计数和协议代次如何设计？
5. 若串口对端有硬件流控，CTS 可无限拉低时 `T_tx_worst` 还能有界吗？系统应停采集、丢批还是切换存储？
6. 怎样在不使用同一 USART2 的前提下报告故障，避免诊断路径依赖故障对象？
7. 低功耗进入前如何停止源、等待 TX、撤销 DMA；唤醒后如何定义第一个有效 session？

## 16. 本节总结

本课唯一的新核心概念是 **端到端有界批次所有权与背压**：

```text
TIM2 defines production time
  -> ADC1 + DMA2 writes one half
  -> HT/TC publishes (half, generation, deadline)
  -> App lends that immutable half to USART2 TX DMA
  -> final TX complete returns ownership
  -> capture may reuse only a returned half
  -> late/busy/error stops TIM2 first and preserves the first fault
```

它解决两个 DMA 并发访问同一内存时的完整性问题。对象由 BSP 静态持有；HT/TC 注入生产事件，App 提交批次，TX complete 注入归还事件；控制流负责武装、启动、停源、清理和显式恢复。generation 防止旧事件混入新批，deadline 把“赶得上”变成可检查条件，首错快照让清理副作用不掩盖根因。

Host Fake 只能验证状态、顺序和错误策略；F407 参考轨道把机制落实到 TIM2、ADC1、DMA2 S0/C0、USART2 和 DMA1 S6/C4，并给出时钟、CubeMX、HAL、IRQ 与寄存器核对点。当前没有目标构建、烧录或测量证据，`hardware_verified=false`。

## 17. 下一步

本阶段的外设集成实验在这里收束。后续若走调试阶段，应把本课首错快照、NDTR、IRQ 时延和串行内容变成可重复的观测实验；若目标换成带 D-Cache 的 F7/H7，应先完成 `dma-coherency`，再复用这套所有权状态机；若加入多通道、协议头或 RTOS 队列，应分别成课，不在本课模型上无证据叠加。

掌握度不会因课程生成自动提高。只有用户完成自检、主机测试、目标构建或复习记录后，才可在后续运行中更新学习状态。

## 18. 参考资料

- [S1] STMicroelectronics, *STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 advanced Arm-based 32-bit MCUs - Reference manual*, RM0090 Rev 22, May 2026：RCC、TIM2 TRGO、ADC regular external trigger/DMA、DMA request mapping/stream/flag、USART2/DMA/TC；访问日期 2026-10-16。<https://www.st.com/resource/en/reference_manual/dm00031020.pdf>
- [S2] STMicroelectronics, *STM32F405xx STM32F407xx datasheet*, DS8626 Rev 12, March 2026：器件范围、时钟与电气上限、ADC 输入和封装边界；本文不据此虚构板级引脚；访问日期 2026-10-16。<https://www.st.com/resource/en/datasheet/stm32f407vg.pdf>
- [S3] STMicroelectronics, *Description of STM32F4 HAL and low-layer drivers*, UM1725 Rev 8, March 2023：ADC/TIM/DMA/UART HAL/LL 初始化、start/stop、IRQ、callback 和 error API；访问日期 2026-10-16。<https://www.st.com/resource/en/user_manual/dm00105879.pdf>
- [S4] STMicroelectronics, *Using the STM32F2/F4/F7 DMA controller*, AN4031 DocID022648 Rev 3, June 2016：stream/channel、仲裁、FIFO、circular/double-buffer 与 DMA 错误；具体 F407 request mapping 仍以 RM0090 为准；访问日期 2026-10-16。<https://www.st.com/resource/en/application_note/an4031-using-the-stm32f2f4f7-series-dma-controller-stmicroelectronics.pdf>
- [S5] STMicroelectronics, *STM32Cube MCU Package for STM32F4 series*, STM32CubeF4 v1.28.3, 23 July 2025：`stm32f4xx_hal_adc.*`、`dma.*`、`tim.*`、`uart.*`、LL headers 与 CMSIS device headers 的代码边界；访问日期 2026-10-16。<https://www.st.com/en/embedded-software/stm32cubef4.html>

来源均来自 `config/source-policy.toml` 允许的 ST 第一方域名。版本、章节和源码位置用于约束参考实现，不构成目标编译、寄存器读回或上板测量证据。

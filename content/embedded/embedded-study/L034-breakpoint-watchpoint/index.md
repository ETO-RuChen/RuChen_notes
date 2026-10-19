+++
title = "断点与观察点：以触发条件取得可审计现场"
date = "2026-10-18T16:00:05+08:00"
lastmod = "2026-10-18T16:00:05+08:00"
summary = "核心目标：建立断点与观察点作为可审计触发条件的心智模型：区分指令地址触发和数据访问触发，评估它们对执行时序的扰动，并为 STM32F407xx 制定来源可核对的调试验证方案。新核心概念：断点的指令地址触发与停止边界；观察点的数据访问触发与资源边界。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 34
tags = ["breakpoint", "watchpoint", "debugging", "evidence", "fpb", "dwt", "coresight", "stm32f407", "tim2", "hal", "ll", "host-fake", "c11"]
source_ids = ["arm-100166-r0p1-breakpoint-watchpoint", "st-rm0090-breakpoint-watchpoint", "st-ds8626-breakpoint-watchpoint", "st-um1725-breakpoint-watchpoint", "st-stm32cubef4-1.28.3-breakpoint-watchpoint"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L034"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 34 课：断点与观察点——以触发条件取得可审计现场

断点和观察点都会让调试器在满足条件时报告事件或暂停处理器，但它们回答的是不同问题：断点问“执行是否到达这条指令”，观察点问“谁访问了这个数据地址”。两者得到的都是触发瞬间附近的有限现场，不是程序自由运行过程的完整录像。

本课只推进两个新核心概念：**断点的指令地址触发与停止边界**、**观察点的数据访问触发与资源边界**。先用 C11 Host Fake（主机替身）验证触发规格、有限资源、暂停/恢复和错误路径，再落到 STM32F407xx 的 TIM2 中断状态对象。FPB（Flash Patch and Breakpoint，闪存补丁与断点单元）负责代码地址比较，DWT（Data Watchpoint and Trace，数据观察与跟踪单元）可承担数据访问匹配；它们都属于 Cortex-M4 调试组件，而不是 TIM2 外设。[S1][S2]

本课中的 HAL（Hardware Abstraction Layer，硬件抽象层）与 LL（Low-Layer，低层驱动）指 STM32CubeF4 的两层驱动接口；ADC（Analog-to-Digital Converter，模数转换器）与 DMA（Direct Memory Access，直接存储器访问）只作为已学跨外设链路的暂停边界出现，不新增采样或搬运机制。

参考边界为 Arm 100166 r0p1 revision 04、RM0090 Rev 22、DS8626 Rev 12、UM1725 Rev 8 与 STM32CubeF4 v1.28.3。[S1]-[S5] 当前没有完整订货料号、开发板、探针、目标工程、构建输出、连接记录、命中截图或测量结果。全部 STM32 代码均为**参考实现，待目标工程编译和上板验证**；本课 `hardware_verified=false`。

## 1. 本节目标

核心目标与本次 `plan.json` 一致：**建立断点与观察点作为可审计触发条件的心智模型：区分指令地址触发和数据访问触发，评估它们对执行时序的扰动，并为 STM32F407xx 制定来源可核对的调试验证方案。**

新核心概念与计划一致：

1. **断点的指令地址触发与停止边界**；
2. **观察点的数据访问触发与资源边界**。

完成本课后，你应能：

1. 把 IDE（Integrated Development Environment，集成开发环境）中的一个红点改写成包含机器指令地址、预期调用路径和结论边界的断点规格；
2. 为一个静态对象写出地址、大小、访问类型、合法写入者和资源槽明确的观察点规格；
3. 解释 FPB、DWT、调试服务器、探针、应用对象与停止现场各由谁持有；
4. 区分“命中过”与“自由运行时序正确”，并为后者选择独立证据；
5. 用 Host Fake 验证匹配、资源耗尽、无效规格、暂停/恢复和链路前置失败；
6. 在 STM32F407xx 上为 TIM2 回调入口和应用状态对象设计可复查的触发实验；
7. 说明核心暂停、TIM2 调试冻结与 ADC/DMA 继续推进是三个必须分别核对的问题；
8. 迁移到 F7、H5、H7 时保留触发契约，同时重查缓存、安全授权、时钟域和调试组件。

## 2. 它解决什么问题

### 2.1 从“在这里停一下”变成可证伪条件

程序偶发地把 `state` 写坏时，反复单步通常只能看到结果，看不到首次非法写入者。你真正需要的是：

```text
当 CPU 对 state 的 4 字节存储发生时
  -> 记录命中发生在哪条指令
  -> 检查调用者、写入值和对象所有权
  -> 判断这次写入是否合法
```

这是一条数据访问触发规格。相反，想确认错误分支是否到达时，条件应是：

```text
当 CPU 即将执行 error_path 对应的机器指令时
  -> 暂停
  -> 检查参数、返回码和调用路径
```

这是指令地址触发规格。源代码行只是工具映射入口；真正被比较的是机器指令地址或数据地址。[S1]

### 2.2 一次命中只证明触发条件成立

假设在 `HAL_TIM_PeriodElapsedCallback` 命中断点。它可以支持：

- 本次执行到达了回调对应的指令位置；
- 命中时调用栈、参数和已完成的软件写入具有记录中的值；
- 在已核对符号映射的前提下，该入口确实关联 TIM 回调路径。

它不能单独证明：

- TIM2 一直以 1 kHz 自由运行；
- 所有更新中断都被及时处理；
- ADC 收到了每次触发；
- DMA 缓冲区没有覆盖或丢样；
- 外部引脚产生了正确波形。

原因不是调试器“不可靠”，而是暂停本身改变了时间。RM0090 明确允许在核心暂停时选择让定时器继续计数或冻结；`DBG_TIM2_STOP` 只控制 TIM2 计数器，不等价于冻结 ADC、DMA 或整个总线系统。[S2]

### 2.3 观察点不是对象所有权

为 `g_debug_target_state.tim2_ticks` 设置写观察点，不会把对象所有权转给调试器。对象仍由应用诊断模块静态持有，TIM2 回调只是合法写入者，调试服务器只把地址、大小和访问类型注入 DWT 或其他可用调试机制。调试表达式若主动赋值，反而会成为额外写入者并污染证据。

## 3. 必要前置知识

本课直接复用已完成内容：

- `const-volatile`：`volatile` 使编译器按抽象机规则保留相关访问，但不提供线程安全，也不等于调试观察点；
- `linker-script`、`elf-map`：源符号必须映射到最终 ELF 中的指令或对象地址；
- `interrupt-priority`、`timer`：TIM2 更新事件经 NVIC（Nested Vectored Interrupt Controller，嵌套向量中断控制器）进入 IRQ（Interrupt Request，中断请求），再由 HAL 分派回调；
- `dma`、`adc-timer-dma-pipeline`：外设和 DMA 可以在核心暂停后继续推进，缓冲区所有权仍需审计；
- `clock-tree`：时序结论必须从实际时钟链和分频计算；
- `hal-ll-register-crosswalk`：HAL 返回值、句柄状态与寄存器事件属于不同证据层；
- `register-view`：每个现场都要记录取样时机、读副作用、暂停影响与交叉证据。

本课不假定已经掌握故障寄存器解码、完整栈回溯、RTOS（Real-Time Operating System，实时操作系统）感知调试、ITM（Instrumentation Trace Macrocell，仪器化跟踪宏单元）、SWO（Serial Wire Output，串行线输出）、ETM（Embedded Trace Macrocell，嵌入式跟踪宏单元）或 trace（跟踪）、逻辑分析仪与缓存一致性。它们只作为后续证据路径出现。

## 4. 核心原理

### 4.1 断点：比较指令地址

断点解决“控制流是否到达某处”。最小模型是：

```text
目标源位置
  -> 由 ELF（Executable and Linkable Format，可执行与可链接格式）
     和 DWARF（调试信息格式）解析为一个或多个机器指令地址
  -> 调试服务器选择硬件比较器或软件断点机制
  -> CPU 取指满足条件
  -> 进入调试暂停
  -> 调试器读取 PC、寄存器、栈和应用对象
```

在 Cortex-M4 中，FPB 可用比较器匹配代码空间地址，并可把匹配位置映射到 `BKPT` 指令。对本课的 STM32F407xx，RM0090 明确给出 **6 个指令比较器和 2 个 literal（字面量）比较器**；只有前者用于匹配指令取址，不能把两类资源相加后宣称有 8 个源码断点槽。[S2] 这仍只是芯片集成资源：复位向量断点、调试服务器保留资源、软件断点降级和工具限制都可能改变当前会话可安装的数量，因此实验还必须记录工具报告的实际分配结果。

源代码断点还有三个边界：

1. 一行 C 可能对应多条或零条独立指令；优化可能移动、合并或内联代码；
2. 调试服务器可能使用 FPB，也可能在可写存储器中替换软件指令；IDE 图标不说明底层机制；
3. “停在函数入口”通常表示尚未完成函数体副作用，必须结合反汇编位置判断哪些写入已经发生。

### 4.2 观察点：比较数据访问

观察点解决“谁读写了这个地址”。最小模型是：

```text
对象符号
  -> 解析运行地址、宽度和对齐
  -> 注入 read/write/access 条件
  -> CPU 发出数据访问
  -> DWT 比较器匹配
  -> 报告事件或暂停
  -> 检查命中指令、写入者、旧值/新值和所有权
```

对本课的 STM32F407xx，RM0090 明确给出 **4 个 DWT 比较器**，它们可被配置为 hardware watchpoint（硬件观察点）、ETM trigger、PC sampling 或 data address sampling，因此“芯片有 4 个比较器”不等于“当前会话一定能安装 4 个相同能力的写观察点”。[S2] 本课只要求一个 4 字节、写访问观察点，并把以下项目视为运行前核对项：

- 当前调试服务器是否支持写观察、读观察或读写观察；
- 地址与宽度是否满足硬件对齐/掩码要求；
- 一个规格占用几个硬件比较器；
- 条件表达式是由硬件完成，还是调试服务器暂停后再软件判断；
- 命中是精确停在访问前、访问后，还是只保证与该访问相关。

若工具文档和现场实验没有回答，就标为“待核对”，不能猜测。

### 4.3 五类对象：定义、持有、注入和流动

| 对象 | 解决的问题 | 在哪里定义、谁持有 | 谁注入 | 调用/事件如何流动 |
| --- | --- | --- | --- | --- |
| 断点规格 | 把“走到这里”变成精确条件 | 实验记录中的静态表；实验作者持有 | 调试配置把指令位置交给调试服务器 | 取指地址匹配 -> 命中 -> 暂停/报告 -> 读取现场 |
| 观察点规格 | 找到对象何时、由谁访问 | 实验记录中的静态表；对象模块仍持有对象 | 调试配置注入地址、大小和访问类型 | 数据访问 -> 匹配 -> 命中 -> 检查访问指令和写入者 |
| 比较器资源 | 在有限硬件中实现条件 | FPB/DWT 硬件持有；工具管理分配 | 调试服务器配置并释放槽位 | 规格申请 -> 占用/失败 -> 匹配 -> 释放 |
| 停止现场 | 固定命中附近的有限状态 | 调试器读取，实验记录持有副本 | 触发事件使核心进入 debug halt | 核心暂停 -> 读 PC（Program Counter，程序计数器）/寄存器/对象 -> 标注扰动 |
| 交叉证据 | 防止从暂停样本推出连续时序 | 实验记录持有 | 自由运行计数、trace 或外部测量注入 | 停止现场提出假设 -> 独立路径支持或否定 |

对象所有权不会因调试条件改变：应用模块持有状态，BSP（Board Support Package，板级支持包）持有 HAL 句柄，调试服务器持有比较器配置，实验记录持有快照。

### 4.4 三条流必须分开

- **控制流**：安装规格 -> 运行 -> 命中 -> 暂停 -> 检查 -> 恢复；
- **数据流**：指令/数据地址 -> 比较器 -> 命中状态 -> 调试器快照；
- **事件流**：TIM2 update -> IRQ -> `HAL_TIM_IRQHandler` -> 回调 -> 应用状态写入 -> 观察点。

断点观察控制流，观察点观察数据访问；它们都不能自动证明外设事件流完整。

### 4.5 暂停边界

核心进入调试暂停后，至少逐项回答：

1. CPU 是否停止执行普通指令；
2. TIM2 的 `DBG_TIM2_STOP` 是 0 还是 1；
3. ADC、DMA、另一个定时器和看门狗是否继续；
4. 探针读取内存时是否会触发总线访问或读副作用；
5. 恢复后积压的中断、标志和缓冲区数据如何处理。

RM0090 规定 `DBGMCU_APB1_FZ` 在上电复位后为 0，并且不由系统复位清零；其 `DBG_TIM2_STOP=0` 时 TIM2 在核心暂停期间继续计数，置 1 时 TIM2 计数器停止。[S2] 所以“我刚刚复位过”不足以推断冻结策略；每次实验都要读回或显式设置。

## 5. 关键术语与直观模型

| 术语 | 准确含义 | 直观模型 |
| --- | --- | --- |
| breakpoint（断点） | 以机器指令地址或调试事件为条件的停止/报告机制 | 控制流经过门牌号时触发 |
| watchpoint（观察点） | 以数据地址的读、写或访问为条件的调试机制 | 有人碰到指定抽屉时触发 |
| FPB | Flash Patch and Breakpoint，闪存补丁与断点单元 | 代码地址比较与重映射资源 |
| DWT | Data Watchpoint and Trace，数据观察与跟踪单元 | 数据访问比较、计数与跟踪事件资源 |
| CoreSight | Arm 片上调试与跟踪架构 | 连接调试端口、比较器和 trace 的架构集合 |
| SWD | Serial Wire Debug，串行线调试 | 探针通过 SWDIO/SWCLK 访问目标调试端口 |
| comparator（比较器） | 将运行中的地址/事件与配置条件进行硬件比较的有限资源 | 有固定数量的触发槽 |
| hit（命中） | 一次运行事件满足触发条件 | 条件为真，不等于系统整体正确 |
| debug halt（调试暂停） | 处理器停止普通指令执行、供调试器检查状态 | CPU 停住，但外设是否停要逐项核对 |
| cross evidence（交叉证据） | 与暂停现场相对独立的第二条验证路径 | 用自由运行计数或外部测量复核 |

## 6. 从输入到结果的完整流程

### 6.1 先写触发规格

断点规格最少包含：

| 字段 | TIM2 示例 |
| --- | --- |
| 目的 | 确认一次 TIM2 IRQ 已由 HAL 分派到应用更新函数 |
| 目标 | `DebugTarget_RecordTim2Tick` 的入口机器指令 |
| 地址来源 | 当前 ELF/DWARF 与反汇编；不手填课程中的虚构地址 |
| 预期调用者 | `HAL_TIM_PeriodElapsedCallback` |
| 命中前预期 | `tim2_ticks` 尚未由本次调用递增 |
| 可得结论 | 本次控制流到达目标入口 |
| 不可得结论 | 1 kHz 长期准确、IRQ 无丢失、DMA 完整 |
| 暂停策略 | 明确记录 TIM2 冻结位及其他外设状态 |
| 交叉证据 | 移除断点后自由运行的计数差或外部测量 |

观察点规格最少包含：

| 字段 | 状态对象示例 |
| --- | --- |
| 对象定义 | `app_debug_target.c` 的 `g_debug_target_state.tim2_ticks` |
| 所有者 | 应用诊断模块 |
| 合法写入者 | `DebugTarget_RecordTim2Tick` |
| 地址/大小 | 从当前 ELF 符号解析，4 字节，实际对齐待工具确认 |
| 访问类型 | write（写） |
| 资源槽 | 由调试工具实际报告并记录 |
| 命中后检查 | PC、反汇编、调用栈、`last_writer_id`、旧/新值 |
| 替代路径 | 比较器不足时，在唯一写入口设断点；需要时间线时用 trace/日志 |

### 6.2 安装前审计

1. 固定固件提交、构建配置、ELF、优化等级和链接时优化（Link-Time Optimization，LTO）状态；
2. 检查目标符号没有被裁剪或内联到无法辨认的位置；
3. 记录调试器、探针、调试服务器和设备描述版本；
4. 先清理无关断点/观察点，再安装一个规格；
5. 记录硬件资源分配是否成功，不把 IDE 图标当成安装成功证据；
6. 写明核心和 TIM2 的暂停/冻结策略；
7. 运行到第一次命中，只做预先列出的只读检查；
8. 保存现场后移除触发条件，自由运行并采集交叉证据。

### 6.3 资源不足时的降级顺序

```text
精确数据观察点不可用
  -> 将所有合法写入收敛到一个函数，在入口设断点
  -> 仍过于频繁时，加入有界软件条件和事件计数
  -> 需要连续时间线时，转向 ITM/SWO/ETM trace
  -> 需要外部时序时，转向逻辑分析仪/示波器
```

降级必须写进记录；不能把“工具没有报错”当成硬件观察点已经生效。

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

| 层级 | 能力 | 工作原理、链路与课程落点 |
| --- | --- | --- |
| 基础 | 函数入口断点、静态对象写观察点 | 指令取址进入 FPB/调试机制；数据访问进入 DWT 匹配。本课深入触发条件和证据边界 |
| 进阶 | 条件命中、资源分配、暂停/恢复审计 | 调试服务器分配有限槽位；暂停后检查 PC/栈/对象并记录扰动。本课覆盖工具无关规格，具体命令按工具版本核对 |
| 高级 | DWT 事件、ITM/SWO/ETM trace、采样与触发组合 | 事件经 CoreSight 路径输出时间线，减少反复暂停；仍需带宽、丢包和时间戳边界。后续进入 trace/性能专题 |
| 跨外设联动 | `RCC -> TIM2 -> ADC1 -> DMA2 -> IRQ/回调` 首次失败定位 | 在回调入口或应用状态写入点触发；暂停后分别审计 TIM2、ADC、DMA 和缓冲区，不能假设同步冻结 |
| 系列差异 | 保留“条件-资源-命中-扰动-交叉证据”契约 | F4 本课落地；F7/H7 重查缓存与多总线/时钟域；H5 重查 Armv8-M 与安全调试授权；具体数量、寄存器和工具支持必须加入目标系列第一方来源 |

高级功能不是“更多断点”。DWT 事件或 ETM 指令跟踪解决的是暂停过度扰动实时系统的问题：匹配/采样事件进入 CoreSight 数据路径，经片上缓冲/端口与探针输出，再由主机重建时间线。触发源、输出带宽、缓冲溢出和时间戳决定“没看到事件”能否作为证据。后续课程应分别在 trace/性能专题落地连续执行证据，在 `logic-analyzer` 落地外部信号证据，在缓存一致性专题落地 CPU 与 DMA 的可见性。

#### F4/F7/H5/H7 迁移审计

| 目标 | 可迁移机制 | 目标资料必须重查 |
| --- | --- | --- |
| STM32F407xx | 触发规格、对象所有权、命中记录、暂停扰动和交叉证据 | 完整料号/封装、FPB/DWT 实现、探针支持、`DBGMCU_APB1_FZ`、SWD 引脚和冻结策略 |
| F7 | 同一契约与实验顺序 | 对应 Cortex-M7 调试组件、I/D Cache 对代码/数据可见性的影响、总线与 DMA、DBGMCU 和 CubeF7 工具接口 |
| H5 | 同一契约与实验顺序 | Armv8-M、安全/非安全域的调试授权、生命周期状态、目标 DMA/时钟域与 CubeH5 接口 |
| H7 | 同一契约与实验顺序 | 具体内核、缓存、多电源/时钟域、DMA/内存可达性、DBGMCU 冻结矩阵与 CubeH7 接口 |

后 3 行只是迁移检查项，不是器件事实。没有相应 RM/DS/Cube 来源前，不复制 F407 的地址、位值或资源数量。

### 7.2 参考目标与时钟/复位链

#### 参考边界

- 参考系列：STM32F407xx；完整料号、封装和开发板未知；
- 内核：Cortex-M4 with FPU r0p1；RM0090 确认片上包含 FPB、DWT、ITM、TPIU 等调试组件，并给出 6 个 FPB 指令比较器、2 个 FPB literal 比较器和 4 个 DWT 比较器；当前工具可分配多少槽仍以调试服务器记录为准；[S2]
- 调试接口：CubeMX 中选择 Serial Wire 时涉及 PA13/SWDIO、PA14/SWCLK；是否与实际板载探针相连必须查原理图；[S2][S3]
- 时钟示例使用片内 HSI，不假定 HSE 晶振；168 MHz 配置只有在目标供电与 Flash 等待周期满足 DS8626 条件后才能使用；[S3]
- 代码边界：STM32CubeF4 v1.28.3 与 CMSIS（Cortex Microcontroller Software Interface Standard，Cortex 微控制器软件接口标准）；生成文件名和用户代码区按实际 CubeMX 版本核对。[S5]

#### 完整时钟链

```text
HSI = 16 MHz
  -> PLLM = 16，PLL 输入 = 1 MHz
  -> PLLN = 336，VCO = 336 MHz
  -> PLLP = 2，SYSCLK = 168 MHz
  -> AHB HPRE = /1，HCLK = 168 MHz
  -> APB1 PPRE1 = /4，PCLK1 = 42 MHz
  -> APB1 预分频不为 1，TIM2CLK = 2 * PCLK1 = 84 MHz
  -> RCC_APB1ENR.TIM2EN = 1
  -> PSC = 8399，计数 tick = 84 MHz / (8399 + 1) = 10 kHz
  -> ARR = 9，update = 10 kHz / (9 + 1) = 1 kHz
  -> DIER.UIE = 1，NVIC 允许 TIM2_IRQn
  -> update -> UIF -> TIM2_IRQHandler -> HAL_TIM_IRQHandler
  -> HAL_TIM_PeriodElapsedCallback -> DebugTarget_RecordTim2Tick
```

`PSC`、`ARR` 和时钟树只给出设计频率。断点命中后由调试器读取的 `CNT` 或 tick 值，不能证明自由运行时的 1 kHz；需要移除断点后的时间基准或外部测量。

#### 复位、门控和暂停链

```text
POR/system reset
  -> HAL_Init
  -> HSI/PLL 与 Flash latency
  -> SYSCLK/HCLK/PCLK1
  -> TIM2 BSP 独占外设时，置位再释放 RCC_APB1RSTR.TIM2RST
  -> RCC_APB1ENR.TIM2EN = 1
  -> HAL_TIM_Base_Init 写 PSC/ARR/CR1 并产生更新装载
  -> 清理待决状态并启用 TIM2 IRQ
  -> HAL_TIM_Base_Start_IT 使能 update interrupt 与计数器

SWD 连接
  -> 调试服务器分配 FPB/DWT 资源
  -> 指令或数据访问命中
  -> Cortex-M4 core halt
  -> DBGMCU_APB1_FZ.DBG_TIM2_STOP 决定 TIM2 继续或冻结
  -> 恢复后处理待决事件
```

需要特别区分：

- `DBGMCU_APB1_FZ` 由 POR（Power-On Reset，上电复位）清零，不由 system reset（系统复位）清零；[S2]
- `RCC_APB1RSTR.TIM2RST` 由 TIM2 BSP 在启动期独占使用；断言后释放会把 TIM2 外设寄存器恢复到复位态，不能在其他模块共享或定时器运行期间擅自执行；[S2][S4]
- `DBG_TIM2_STOP=1` 只明确冻结 TIM2 计数器，不能外推到 DMA2/ADC1；[S2]
- RM0090 说明调试会话中 FCLK/HCLK 不能被关闭，以维持调试连接；这不等于所有外设都有相同暂停行为；[S2]
- FPB/DWT 属于内核调试路径，TIM2 的 APB1 时钟决定事件源；二者时钟背景不同，却会在“命中后暂停”处相遇。

### 7.3 CubeMX、HAL、LL 与寄存器对照

#### CubeMX/CubeMX2 配置清单

| 页面 | 配置 | 固定值/边界 |
| --- | --- | --- |
| MCU Selector | 选择完整 STM32F407 订货料号 | 必须由实际器件确认；本课不代填封装 |
| System Core/RCC | HSI on，HSE off | 示例不依赖板载晶振 |
| Clock Configuration | SYSCLK 168 MHz、AHB /1、APB1 /4、APB2 /2 | 执行前核对 VDD 和 Flash latency |
| System Core/SYS | Debug = Serial Wire | 只说明 MCU 配置入口；探针连接和板级引脚查原理图 |
| Timers/TIM2 | Clock Source = Internal Clock；Prescaler 8399；Counter Period 9；Up；Clock Division 1 | 得到设计上的 1 kHz update |
| TIM2/NVIC | TIM2 global interrupt enabled | 中断优先级是项目参数；示例用 preempt 5/sub 0，不推定 RTOS 约束 |
| Project Manager | 记录 CubeMX 与 CubeF4 版本，保留用户代码 | 生成后审计 `.ioc`、clock、MSP（MCU Support Package，MCU 支持包）、IRQ 和头文件 |
| Debug freeze | 若工具提供 freeze 选项，显式记录；否则由应用宏或调试服务器设置 | 最终以 `DBGMCU_APB1_FZ` 读回为证据 |

可选 ADC1/DMA2 链只复用 L031/L032 已学配置，不为本课新增采样配置。若实际工程启用它，必须同时记录 ADC 触发源、DMA stream/channel、缓冲区所有者和 IRQ；本课不虚构这些板级/工程参数。

#### HAL 句柄、初始化字段和所有权

| 项目 | 所有者 | 生命周期 | 关键字段/职责 |
| --- | --- | --- | --- |
| `s_tim2` | `bsp_tim2.c` | 静态，整个固件运行期 | `Instance`、`Prescaler`、`CounterMode`、`Period`、`ClockDivision`、`AutoReloadPreload` |
| `g_debug_target_state` | `app_debug_target.c` | 静态存储期 | 被观察的 tick、合法写入者、错误码、回调序号 |
| FPB/DWT 槽位 | 调试组件；由调试服务器管理 | 当前调试会话 | 地址、访问类型、掩码/宽度与启用状态 |
| TIM2 IRQ | NVIC + `stm32f4xx_it.c` | TIM2 启动后 | 进入 `BspTim2_IrqHandler`，再交给 HAL |

初始化顺序必须是：

```text
HAL_Init
  -> BspClock_Config168MhzFromHsi
  -> AppDebugTarget_Init
  -> BspTim2_Init
  -> 明确设置 TIM2 freeze policy
  -> 安装调试触发条件
  -> BspTim2_Start
```

调试条件应在事件源启动前安装，避免错过首次写入；若工具只能连接后配置，则先保持 TIM2 未启动。

#### HAL 到 LL/寄存器/事件对照

| HAL/调试意图 | LL/关键寄存器或状态 | 硬件效果与检查点 |
| --- | --- | --- |
| `__HAL_RCC_TIM2_FORCE_RESET()` / `RELEASE_RESET()` | `RCC_APB1RSTR.TIM2RST` | 在 BSP 独占、事件源尚未启动时建立已知外设复位态；不得用于共享或运行中的 TIM2 |
| `HAL_TIM_Base_Init` | LL TIM 基础配置；`TIM2_PSC`、`ARR`、`CR1`、`EGR.UG` | 配置分频、周期、方向、预装载并把值装入影子路径 |
| `HAL_TIM_Base_Start_IT` | `TIM2_DIER.UIE`、`TIM2_CR1.CEN` | 允许 update IRQ 并启动计数；返回 `HAL_OK` 不是频率证据 |
| `TIM2_IRQHandler` -> `HAL_TIM_IRQHandler` | `TIM2_SR.UIF` 与中断使能条件 | HAL 判定 update、清理对应标志并调用 period callback；顺序以 CubeF4 v1.28.3 源码核对 |
| `__HAL_DBGMCU_FREEZE_TIM2()` | `DBGMCU_APB1_FZ.DBG_TIM2_STOP=1` | 核心暂停时 TIM2 计数停止；UM1725 列出该宏，RM0090 定义位语义 [S2][S4] |
| `__HAL_DBGMCU_UNFREEZE_TIM2()` | `DBG_TIM2_STOP=0` | 核心暂停时 TIM2 按正常模式继续计数 [S2][S4] |
| 函数入口断点 | FPB 或工具选择的软件机制 | 指令地址匹配后进入调试；底层机制由工具记录，不由 HAL 配置 [S1] |
| 写观察点 | DWT comparator/function，具体字段由调试服务器管理 | 数据写访问匹配；资源数和精确停点按目标/工具核对 [S1] |

不要让应用与调试服务器同时写 FPB/DWT 配置。HAL 没有“安装源代码断点”的外设 API；调试服务器通过 SWD/JTAG 和 AHB-AP 访问调试组件。应用只负责提供稳定、可定位的对象和写入口。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

Host Fake 使用符号化的 32 位位置/对象 ID，不模拟 Cortex-M4 地址、寄存器布局或 SWD。它只验证：

- 指令位置与写访问是两类不同条件；
- 比较器槽位有限且资源耗尽必须显式失败；
- 无效地址、零大小和错误访问类型被拒绝；
- 暂停后执行步不推进，恢复后才继续；
- 源未就绪时，首次失败点是前置链路而非“观察点坏了”；
- 一次命中只形成一条事件记录。

最小文件布局：

```text
host/
  debug_trigger_fake.h   # 声明：类型、固定宽度接口、容量
  debug_trigger_fake.c   # 实现：匹配、暂停、资源与错误路径
  test_debug_trigger.c   # 实例化、组装和使用：场景断言
```

#### `debug_trigger_fake.h`：声明

```c
#ifndef DEBUG_TRIGGER_FAKE_H
#define DEBUG_TRIGGER_FAKE_H

#include <stdint.h>

#define DEBUG_FAKE_SLOT_COUNT       2u

#define DEBUG_OK                    0u
#define DEBUG_ERR_ARGUMENT          1u
#define DEBUG_ERR_RESOURCE          2u
#define DEBUG_ERR_PAUSED            3u
#define DEBUG_ERR_SOURCE_BLOCKED    4u

#define DEBUG_TRIGGER_BREAKPOINT    1u
#define DEBUG_TRIGGER_WATCH_WRITE   2u

#define DEBUG_ACCESS_EXECUTE        1u
#define DEBUG_ACCESS_WRITE          2u

#define DEBUG_LOCATION_WORK         0x1001u
#define DEBUG_LOCATION_ERROR        0x1002u
#define DEBUG_OBJECT_DIAGNOSTIC     0x2001u
#define DEBUG_OBJECT_OTHER          0x2002u

typedef struct {
    uint32_t kind;
    uint32_t target;
    uint32_t width_bytes;
    uint32_t access;
} debug_trigger_spec_t;

typedef struct {
    uint32_t valid;
    uint32_t kind;
    uint32_t slot;
    uint32_t target;
    uint32_t access;
    uint32_t writer_id;
    uint32_t value_before;
    uint32_t value_after;
    uint32_t hit_sequence;
} debug_hit_t;

typedef struct {
    debug_trigger_spec_t slots[DEBUG_FAKE_SLOT_COUNT];
    uint8_t slot_used[DEBUG_FAKE_SLOT_COUNT];
    uint8_t paused;
    uint8_t source_ready;
    uint8_t reserved;
    uint32_t pc;
    uint32_t diagnostic_state;
    uint32_t other_state;
    uint32_t executed_steps;
    uint32_t hit_count;
    debug_hit_t last_hit;
} debug_fake_t;

void DebugFake_Init(debug_fake_t *self);
void DebugFake_SetSourceReady(debug_fake_t *self, uint32_t ready);
uint32_t DebugFake_Install(debug_fake_t *self,
                           const debug_trigger_spec_t *spec,
                           uint32_t *slot_out);
uint32_t DebugFake_Step(debug_fake_t *self, uint32_t location);
uint32_t DebugFake_Write(debug_fake_t *self,
                         uint32_t object_id,
                         uint32_t width_bytes,
                         uint32_t writer_id,
                         uint32_t value);
uint32_t DebugFake_Resume(debug_fake_t *self);

#endif
```

该文件只声明契约；测试持有 Fake 实例并注入规格。所有公开数值均使用固定宽度整数，没有动态内存。

#### `debug_trigger_fake.c`：实现

```c
#include "debug_trigger_fake.h"

#include <stddef.h>
#include <string.h>

static uint32_t DebugFake_SpecIsValid(const debug_trigger_spec_t *spec)
{
    if ((spec == NULL) || (spec->target == 0u) ||
        (spec->width_bytes != 4u)) {
        return 0u;
    }

    if ((spec->kind == DEBUG_TRIGGER_BREAKPOINT) &&
        (spec->access == DEBUG_ACCESS_EXECUTE)) {
        return 1u;
    }

    if ((spec->kind == DEBUG_TRIGGER_WATCH_WRITE) &&
        (spec->access == DEBUG_ACCESS_WRITE)) {
        return 1u;
    }

    return 0u;
}

static void DebugFake_RecordHit(debug_fake_t *self,
                                uint32_t slot,
                                const debug_trigger_spec_t *spec,
                                uint32_t writer_id,
                                uint32_t before,
                                uint32_t after)
{
    self->hit_count++;
    self->paused = 1u;
    self->last_hit.valid = 1u;
    self->last_hit.kind = spec->kind;
    self->last_hit.slot = slot;
    self->last_hit.target = spec->target;
    self->last_hit.access = spec->access;
    self->last_hit.writer_id = writer_id;
    self->last_hit.value_before = before;
    self->last_hit.value_after = after;
    self->last_hit.hit_sequence = self->hit_count;
}

void DebugFake_Init(debug_fake_t *self)
{
    if (self != NULL) {
        (void)memset(self, 0, sizeof(*self));
    }
}

void DebugFake_SetSourceReady(debug_fake_t *self, uint32_t ready)
{
    if (self != NULL) {
        self->source_ready = (ready != 0u) ? 1u : 0u;
    }
}

uint32_t DebugFake_Install(debug_fake_t *self,
                           const debug_trigger_spec_t *spec,
                           uint32_t *slot_out)
{
    uint32_t slot;

    if ((self == NULL) || (slot_out == NULL) ||
        (DebugFake_SpecIsValid(spec) == 0u)) {
        return DEBUG_ERR_ARGUMENT;
    }

    for (slot = 0u; slot < DEBUG_FAKE_SLOT_COUNT; ++slot) {
        if (self->slot_used[slot] == 0u) {
            self->slots[slot] = *spec;
            self->slot_used[slot] = 1u;
            *slot_out = slot;
            return DEBUG_OK;
        }
    }

    return DEBUG_ERR_RESOURCE;
}

uint32_t DebugFake_Step(debug_fake_t *self, uint32_t location)
{
    uint32_t slot;

    if ((self == NULL) || (location == 0u)) {
        return DEBUG_ERR_ARGUMENT;
    }
    if (self->paused != 0u) {
        return DEBUG_ERR_PAUSED;
    }

    self->pc = location;
    self->executed_steps++;

    for (slot = 0u; slot < DEBUG_FAKE_SLOT_COUNT; ++slot) {
        const debug_trigger_spec_t *spec = &self->slots[slot];
        if ((self->slot_used[slot] != 0u) &&
            (spec->kind == DEBUG_TRIGGER_BREAKPOINT) &&
            (spec->target == location)) {
            DebugFake_RecordHit(self, slot, spec, 0u,
                                self->diagnostic_state,
                                self->diagnostic_state);
            break;
        }
    }

    return DEBUG_OK;
}

uint32_t DebugFake_Write(debug_fake_t *self,
                         uint32_t object_id,
                         uint32_t width_bytes,
                         uint32_t writer_id,
                         uint32_t value)
{
    uint32_t *object;
    uint32_t before;
    uint32_t slot;

    if ((self == NULL) || (writer_id == 0u) || (width_bytes != 4u)) {
        return DEBUG_ERR_ARGUMENT;
    }
    if (self->paused != 0u) {
        return DEBUG_ERR_PAUSED;
    }
    if (self->source_ready == 0u) {
        return DEBUG_ERR_SOURCE_BLOCKED;
    }

    if (object_id == DEBUG_OBJECT_DIAGNOSTIC) {
        object = &self->diagnostic_state;
    } else if (object_id == DEBUG_OBJECT_OTHER) {
        object = &self->other_state;
    } else {
        return DEBUG_ERR_ARGUMENT;
    }

    before = *object;
    *object = value;

    for (slot = 0u; slot < DEBUG_FAKE_SLOT_COUNT; ++slot) {
        const debug_trigger_spec_t *spec = &self->slots[slot];
        if ((self->slot_used[slot] != 0u) &&
            (spec->kind == DEBUG_TRIGGER_WATCH_WRITE) &&
            (spec->target == object_id) &&
            (spec->width_bytes == width_bytes)) {
            DebugFake_RecordHit(self, slot, spec, writer_id, before, value);
            break;
        }
    }

    return DEBUG_OK;
}

uint32_t DebugFake_Resume(debug_fake_t *self)
{
    if ((self == NULL) || (self->paused == 0u)) {
        return DEBUG_ERR_ARGUMENT;
    }
    self->paused = 0u;
    return DEBUG_OK;
}
```

实现拥有匹配状态，不拥有测试策略。Fake 的“写后暂停”只是明确的模型规则，不代表 F407 DWT 的精确停点；真实工具必须通过命中指令和反汇编核对。

#### `test_debug_trigger.c`：实例化、组装和使用

```c
#include "debug_trigger_fake.h"

#include <stdio.h>

static uint32_t s_checks;

#define CHECK(expr) do {                                      \
    s_checks++;                                               \
    if (!(expr)) {                                            \
        (void)printf("check failed at line %u\n",             \
                     (unsigned)__LINE__);                     \
        return 1;                                             \
    }                                                         \
} while (0)

int main(void)
{
    debug_fake_t fake;
    debug_trigger_spec_t breakpoint_spec = {
        DEBUG_TRIGGER_BREAKPOINT,
        DEBUG_LOCATION_ERROR,
        4u,
        DEBUG_ACCESS_EXECUTE
    };
    debug_trigger_spec_t watch_spec = {
        DEBUG_TRIGGER_WATCH_WRITE,
        DEBUG_OBJECT_DIAGNOSTIC,
        4u,
        DEBUG_ACCESS_WRITE
    };
    debug_trigger_spec_t extra_spec = {
        DEBUG_TRIGGER_BREAKPOINT,
        DEBUG_LOCATION_WORK,
        4u,
        DEBUG_ACCESS_EXECUTE
    };
    debug_trigger_spec_t invalid_spec = {
        DEBUG_TRIGGER_WATCH_WRITE,
        DEBUG_OBJECT_DIAGNOSTIC,
        0u,
        DEBUG_ACCESS_WRITE
    };
    uint32_t slot0 = 99u;
    uint32_t slot1 = 99u;
    uint32_t step_count_at_hit;

    DebugFake_Init(&fake);
    CHECK(DebugFake_Install(&fake, &invalid_spec, &slot0) ==
          DEBUG_ERR_ARGUMENT);
    CHECK(DebugFake_Install(&fake, &breakpoint_spec, &slot0) == DEBUG_OK);
    CHECK(DebugFake_Install(&fake, &watch_spec, &slot1) == DEBUG_OK);
    CHECK((slot0 == 0u) && (slot1 == 1u));
    CHECK(DebugFake_Install(&fake, &extra_spec, &slot0) ==
          DEBUG_ERR_RESOURCE);

    CHECK(DebugFake_Step(&fake, DEBUG_LOCATION_WORK) == DEBUG_OK);
    CHECK((fake.paused == 0u) && (fake.hit_count == 0u));
    CHECK(DebugFake_Step(&fake, DEBUG_LOCATION_ERROR) == DEBUG_OK);
    CHECK((fake.paused != 0u) &&
          (fake.last_hit.kind == DEBUG_TRIGGER_BREAKPOINT));
    CHECK(fake.last_hit.target == DEBUG_LOCATION_ERROR);

    step_count_at_hit = fake.executed_steps;
    CHECK(DebugFake_Step(&fake, DEBUG_LOCATION_WORK) == DEBUG_ERR_PAUSED);
    CHECK(fake.executed_steps == step_count_at_hit);
    CHECK(DebugFake_Resume(&fake) == DEBUG_OK);

    CHECK(DebugFake_Write(&fake, DEBUG_OBJECT_DIAGNOSTIC,
                          4u, 7u, 1u) == DEBUG_ERR_SOURCE_BLOCKED);
    CHECK(fake.diagnostic_state == 0u);
    DebugFake_SetSourceReady(&fake, 1u);

    CHECK(DebugFake_Write(&fake, DEBUG_OBJECT_OTHER,
                          4u, 8u, 10u) == DEBUG_OK);
    CHECK(fake.paused == 0u);
    CHECK(DebugFake_Write(&fake, DEBUG_OBJECT_DIAGNOSTIC,
                          4u, 7u, 1u) == DEBUG_OK);
    CHECK((fake.paused != 0u) &&
          (fake.last_hit.kind == DEBUG_TRIGGER_WATCH_WRITE));
    CHECK((fake.last_hit.writer_id == 7u) &&
          (fake.last_hit.value_before == 0u) &&
          (fake.last_hit.value_after == 1u));
    CHECK(fake.last_hit.hit_sequence == 2u);

    (void)printf("debug_trigger_fake: %u checks passed\n",
                 (unsigned)s_checks);
    return 0;
}
```

参考主机构建命令：

```text
cc -std=c11 -Wall -Wextra -Wpedantic -Werror \
  debug_trigger_fake.c test_debug_trigger.c -o debug_trigger_fake
./debug_trigger_fake
```

本次没有执行这些命令，因此不声称代码已经主机构建。执行后应保存编译器版本、完整命令、退出码和输出；即使全部检查通过，也只证明 Fake 契约，不证明 FPB、DWT 或 SWD 硬件行为。

### 8.2 STM32 参考实现轨道

以下代码不直接编程 FPB/DWT。调试服务器负责安装断点/观察点；固件提供稳定对象、唯一合法写入口、可计算事件源和显式冻结策略。

#### `app_debug_target.h/.c`：对象定义与唯一写入口

```c
/* app_debug_target.h */
#ifndef APP_DEBUG_TARGET_H
#define APP_DEBUG_TARGET_H

#include <stdint.h>

#define DEBUG_WRITER_NONE          0u
#define DEBUG_WRITER_TIM2_CALLBACK 1u
#define DEBUG_ERROR_NONE           0u

typedef struct {
    uint32_t tim2_ticks;
    uint32_t callback_sequence;
    uint32_t last_writer_id;
    uint32_t last_error_code;
} debug_target_state_t;

extern volatile debug_target_state_t g_debug_target_state;

void AppDebugTarget_Init(void);
void DebugTarget_RecordTim2Tick(uint32_t writer_id);
void DebugTarget_RecordError(uint32_t error_code);

#endif
```

```c
/* app_debug_target.c */
#include "app_debug_target.h"

volatile debug_target_state_t g_debug_target_state;

void AppDebugTarget_Init(void)
{
    g_debug_target_state.tim2_ticks = 0u;
    g_debug_target_state.callback_sequence = 0u;
    g_debug_target_state.last_writer_id = DEBUG_WRITER_NONE;
    g_debug_target_state.last_error_code = DEBUG_ERROR_NONE;
}

void DebugTarget_RecordTim2Tick(uint32_t writer_id)
{
    g_debug_target_state.last_writer_id = writer_id;
    g_debug_target_state.tim2_ticks++;
    g_debug_target_state.callback_sequence++;
}

void DebugTarget_RecordError(uint32_t error_code)
{
    g_debug_target_state.last_error_code = error_code;
}
```

应用诊断模块定义并持有对象；TIM2 HAL 适配回调注入 `writer_id`。`volatile` 便于当前调试实验观察，但不提供并发原子性。观察点应优先放在 `tim2_ticks` 的 4 字节写访问上；若工具无法接受字段表达式，从 ELF/反汇编确认实际地址。

#### `bsp_clock.c`：完整 HSI 时钟实现

```c
#include "stm32f4xx_hal.h"
#include <stdint.h>

#define BSP_OK          0u
#define BSP_ERR_CLOCK   1u

uint32_t BspClock_Config168MhzFromHsi(void)
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
    osc.PLL.PLLM = 16u;
    osc.PLL.PLLN = 336u;
    osc.PLL.PLLP = RCC_PLLP_DIV2;
    osc.PLL.PLLQ = 7u;
    if (HAL_RCC_OscConfig(&osc) != HAL_OK) {
        return BSP_ERR_CLOCK;
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
        return BSP_ERR_CLOCK;
    }

    return BSP_OK;
}
```

该代码只有在完整料号、供电范围和 DS8626 的 Flash wait-state 条件核对后才可直接使用。真实板若使用 HSE，必须从其实际频率重新计算 PLL，不能只替换 `PLLSource`。

#### `bsp_tim2.h/.c`：句柄、MSP、冻结策略和 HAL 回调

```c
/* bsp_tim2.h */
#ifndef BSP_TIM2_H
#define BSP_TIM2_H

#include <stdint.h>

#define BSP_TIM2_OK             0u
#define BSP_TIM2_ERR_INIT       1u
#define BSP_TIM2_ERR_START      2u
#define BSP_TIM2_ERR_HAL        3u

uint32_t BspTim2_Init(void);
uint32_t BspTim2_Start(void);
void BspTim2_SetFreezePolicy(uint32_t freeze_when_core_halts);
void BspTim2_IrqHandler(void);

#endif
```

```c
/* bsp_tim2.c */
#include "bsp_tim2.h"
#include "app_debug_target.h"
#include "stm32f4xx_hal.h"

static TIM_HandleTypeDef s_tim2;

uint32_t BspTim2_Init(void)
{
    s_tim2.Instance = TIM2;
    s_tim2.Init.Prescaler = 8399u;
    s_tim2.Init.CounterMode = TIM_COUNTERMODE_UP;
    s_tim2.Init.Period = 9u;
    s_tim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    s_tim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;

    if (HAL_TIM_Base_Init(&s_tim2) != HAL_OK) {
        return BSP_TIM2_ERR_INIT;
    }
    return BSP_TIM2_OK;
}

uint32_t BspTim2_Start(void)
{
    if (HAL_TIM_Base_Start_IT(&s_tim2) != HAL_OK) {
        return BSP_TIM2_ERR_START;
    }
    return BSP_TIM2_OK;
}

void BspTim2_SetFreezePolicy(uint32_t freeze_when_core_halts)
{
    if (freeze_when_core_halts != 0u) {
        __HAL_DBGMCU_FREEZE_TIM2();
    } else {
        __HAL_DBGMCU_UNFREEZE_TIM2();
    }
}

void BspTim2_IrqHandler(void)
{
    HAL_TIM_IRQHandler(&s_tim2);
}

void HAL_TIM_Base_MspInit(TIM_HandleTypeDef *htim)
{
    if ((htim != NULL) && (htim->Instance == TIM2)) {
        /* Startup-only: this BSP is the sole TIM2 owner. */
        __HAL_RCC_TIM2_FORCE_RESET();
        __HAL_RCC_TIM2_RELEASE_RESET();
        __HAL_RCC_TIM2_CLK_ENABLE();
        HAL_NVIC_SetPriority(TIM2_IRQn, 5u, 0u);
        HAL_NVIC_EnableIRQ(TIM2_IRQn);
    }
}

void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
    if ((htim != NULL) && (htim->Instance == TIM2)) {
        DebugTarget_RecordTim2Tick(DEBUG_WRITER_TIM2_CALLBACK);
    }
}

void HAL_TIM_ErrorCallback(TIM_HandleTypeDef *htim)
{
    if ((htim != NULL) && (htim->Instance == TIM2)) {
        DebugTarget_RecordError((uint32_t)htim->ErrorCode);
    }
}
```

UM1725 Rev 8 明确列出 `HAL_TIM_Base_Start_IT`、`HAL_TIM_PeriodElapsedCallback`、`HAL_TIM_ErrorCallback` 和 TIM2 freeze/unfreeze 宏。[S4] `s_tim2` 由 BSP 静态持有，不暴露给应用；TIM2 BSP 也因此能在首次初始化且事件源未启动时独占执行 force/release reset。`HAL_TIM_Base_Init` 和 `HAL_TIM_Base_Start_IT` 的失败通过同步返回值进入 `Error_Handler`；不能因为存在 `HAL_TIM_ErrorCallback` 就假定这两个失败会自动调用它。该 callback 只锁存驱动实际从异步路径报告的错误，IRQ 和回调均不阻塞打印。

#### `stm32f4xx_it.c` 与 `main.c`：组装和使用

```c
/* stm32f4xx_it.c */
#include "bsp_tim2.h"

void TIM2_IRQHandler(void)
{
    BspTim2_IrqHandler();
}
```

```c
/* main.c */
#include "app_debug_target.h"
#include "bsp_tim2.h"
#include "stm32f4xx_hal.h"
#include <stdint.h>

#define APP_ERR_CLOCK  0x1001u
#define APP_ERR_TIM2   0x1002u
#define APP_ERR_START  0x1003u

uint32_t BspClock_Config168MhzFromHsi(void);

static void Error_Handler(uint32_t code)
{
    DebugTarget_RecordError(code);
    __disable_irq();
    for (;;) {
        /* Set an instruction breakpoint here; no blocking I/O in the path. */
    }
}

int main(void)
{
    HAL_Init();

    if (BspClock_Config168MhzFromHsi() != 0u) {
        Error_Handler(APP_ERR_CLOCK);
    }

    AppDebugTarget_Init();
    if (BspTim2_Init() != BSP_TIM2_OK) {
        Error_Handler(APP_ERR_TIM2);
    }

    /* Experiment A: 1 freezes TIM2; Experiment B: 0 lets TIM2 continue. */
    BspTim2_SetFreezePolicy(1u);

    /* Install debugger-side breakpoint/watchpoint before this call. */
    if (BspTim2_Start() != BSP_TIM2_OK) {
        Error_Handler(APP_ERR_START);
    }

    for (;;) {
        __WFI();
    }
}
```

依赖方向为 `main -> BSP/app`，`IRQ -> BSP -> HAL callback -> app state`。生命周期从静态实例化开始，经 `main` 组装并启动，直到复位。`Error_Handler` 的循环是可放置断点的错误边界，不代表产品恢复策略。

#### 可选 ADC/DMA 回调的观察边界

若把实验接到已有 `TIM2 -> ADC1 -> DMA2_Stream0` 工程，应保持句柄和缓冲区由 ADC/DMA BSP 持有，只让回调发布诊断事件：

```c
void DMA2_Stream0_IRQHandler(void)
{
    HAL_DMA_IRQHandler(hadc1.DMA_Handle);
}

void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef *hadc)
{
    if ((hadc != NULL) && (hadc->Instance == ADC1)) {
        DebugTarget_RecordDmaEvent(DEBUG_EVENT_DMA_HALF);
    }
}

void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *hadc)
{
    if ((hadc != NULL) && (hadc->Instance == ADC1)) {
        DebugTarget_RecordDmaEvent(DEBUG_EVENT_DMA_FULL);
    }
}

void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *hadc)
{
    if ((hadc != NULL) && (hadc->Instance == ADC1)) {
        DebugTarget_RecordError((uint32_t)HAL_ADC_GetError(hadc));
    }
}
```

这段是与已有 ADC/DMA BSP 对接的接口形状，不是独立可编译单元：`hadc1`、事件 ID、静态缓冲区、DMA mapping 与初始化顺序必须来自实际 L031/L032 工程和 CubeF4 v1.28.3。若只冻结 TIM2，暂停前已经产生的 ADC/DMA 请求仍可能继续；命中后先记录 `NDTR`、HAL error 和回调序号，再由资源所有者执行停止/恢复。不要在回调里为“方便调试”重配 RCC、DMA stream 或共享缓冲区。

#### 目标构建、连接与观察步骤

1. 确认完整 MCU、供电、原理图、探针与 SWD 接线，记录 CubeMX/CubeF4/编译器/调试服务器版本；
2. 生成工程后审计 `SystemClock_Config`、TIM2 MSP、IRQ handler、HAL callback 和 CMSIS 头文件宏；
3. 执行目标构建并保存日志；本次未执行，不能预写成功结果；
4. 烧录并连接后，先读回 SYSCLK/PCLK1/TIM2CLK、PSC、ARR、DIER、CR1 和 `DBGMCU_APB1_FZ`；
5. 在 `DebugTarget_RecordTim2Tick` 入口安装一个指令断点，记录底层资源与解析地址；
6. 对 `g_debug_target_state.tim2_ticks` 安装 4 字节写观察点，记录访问类型与资源槽；
7. 先用 freeze=1 命中一次，检查 PC、调用栈、`last_writer_id`、`CNT/UIF` 和 tick；恢复并记录待决事件；
8. 再用 freeze=0 重复，比较暂停期间 TIM2 和应用状态变化；不要把两次运行当成同一时间线；
9. 移除全部触发条件，自由运行固定时长，以计数差或外部测量核对 1 kHz 假设；
10. 若接入 ADC/DMA，分别记录 stream 状态、NDTR、缓冲区代次和回调序号，确认谁在暂停期间继续。

本次没有执行构建、烧录、连接、断点/观察点安装或测量；预期值是实验判据，不是运行证据。

## 9. 最小代码示例

第一次实践只保留一个事件源、一个断点和一个观察点：

```text
TIM2 1 kHz update
  -> TIM2_IRQHandler
  -> HAL_TIM_IRQHandler
  -> HAL_TIM_PeriodElapsedCallback
  -> DebugTarget_RecordTim2Tick
  -> g_debug_target_state.tim2_ticks++
```

触发规格：

```text
BP0:
  target = DebugTarget_RecordTim2Tick entry instruction
  expect caller = HAL_TIM_PeriodElapsedCallback
  allowed conclusion = control flow reached this entry once

WP0:
  target = g_debug_target_state.tim2_ticks
  size = 4 bytes
  access = write
  legal writer = DebugTarget_RecordTim2Tick
  allowed conclusion = one matching CPU write occurred
```

先不要启用 ADC/DMA、条件表达式或多个对象。只有当 BP0/WP0 的地址、资源、命中时刻和暂停策略都能记录清楚，才扩展链路。

## 10. 常见错误

### 10.1 把源代码行当成唯一机器地址

优化后源行可能消失、合并或对应多个地址。修正：保存 ELF、DWARF 与反汇编，记录实际安装地址；必要时关闭 LTO 或选择稳定的外部函数入口。

### 10.2 把 IDE 图标当成硬件资源已安装

工具可能延迟安装、降级为软件机制或因资源耗尽拒绝。修正：检查调试服务器日志和资源视图，并做一次负测试确认未匹配地址不会命中。

### 10.3 写观察点范围过大

观察整个结构体可能需要多个比较器或因对齐失败。修正：先选择一个自然对齐的 `uint32_t` 字段，记录实际地址和 4 字节宽度。

### 10.4 在表达式窗口写变量

手工赋值会引入调试器写入者，观察点可能命中自己的操作。修正：现场检查默认只读；任何调试写入都单独记录并重新开始实验。

### 10.5 默认所有外设随核心一起停止

F407 用 `DBG_TIM2_STOP` 决定 TIM2，DMA/ADC 必须另查。修正：把每个活动主体列成暂停矩阵，不用“系统暂停”概括。

### 10.6 用命中次数证明实时正确

断点暂停改变中断积压和调度；观察点也可能反复停核。修正：移除触发条件后用自由运行计数、trace 或外部测量交叉验证。

### 10.7 回调中阻塞打印

串口打印会扩展 ISR（Interrupt Service Routine，中断服务程序）时间，掩盖原故障。修正：回调只递增计数或锁存固定宽度错误码，延后输出。

### 10.8 把资源耗尽当成被观察代码失效

比较器槽位不足是调试配置错误，不是业务错误。修正：安装 API/工具操作必须有显式失败记录，并提供函数入口断点等替代路径。

## 11. 调试观察点

### 11.1 命中现场记录表

| 字段 | 必填内容 |
| --- | --- |
| 固件身份 | Git commit、ELF hash、优化/LTO、CubeF4/编译器版本 |
| 工具身份 | IDE、探针固件、调试服务器、设备描述版本 |
| 触发规格 | BP/WP、符号、实际地址、大小、访问类型、条件 |
| 资源结果 | 硬件/软件机制、槽位、安装成功/失败原文 |
| 命中状态 | PC、命中指令、调用栈、参数、对象旧/新值 |
| 暂停矩阵 | core、TIM2、ADC、DMA、watchdog 分别继续/冻结/未知 |
| 读副作用 | 读取了哪些寄存器，是否有清除/弹出语义 |
| 恢复结果 | 待决 IRQ、回调序号、错误码、缓冲区代次 |
| 交叉证据 | 自由运行计数、trace 或外部测量路径 |
| 结论边界 | 可以推出什么、不能推出什么 |

### 11.2 推荐只读顺序

1. 确认 PC 和命中指令；
2. 确认调用栈/调用者是否符合规格；
3. 读取 `g_debug_target_state` 和 HAL 句柄状态；
4. 读取 `DBGMCU_APB1_FZ`，确认 TIM2 freeze 策略；
5. 读取 TIM2 `CR1/DIER/SR/CNT/PSC/ARR`；
6. 若有 DMA，再读取 stream 状态、NDTR 和应用缓冲区代次；
7. 不在保存现场前清标志、改变量或重新初始化。

## 12. 实战实验

### 实验 A：Host Fake 的触发与资源边界

目标：让 `test_debug_trigger.c` 的全部断言通过。

步骤：

1. 按第 8.1 节建立 3 个文件并用 C11 严格告警构建；
2. 运行测试，保存构建命令、版本、退出码和输出；
3. 把 `DEBUG_FAKE_SLOT_COUNT` 改为 1，确认第二个安装返回资源错误；
4. 把观察规格大小改为 0，确认安装被拒绝；
5. 删除 `DebugFake_SetSourceReady`，确认首次失败是源阻塞且对象未改变；
6. 命中后不调用 resume，确认 step/write 均不推进；
7. 写一条结论：哪些断言只属于 Fake，哪些必须在 F407 重做。

验收：不能只写“测试通过”，必须列出各错误码和最后一条 hit record。

### 实验 B：函数入口断点

前提：完成目标构建、烧录和 SWD 连接；否则只完成规格设计。

步骤：

1. 由当前 ELF 找到 `DebugTarget_RecordTim2Tick` 入口指令；
2. 记录调试服务器采用的资源与安装结果；
3. 启动 TIM2，命中一次后检查 PC、调用者和 `tim2_ticks`；
4. 记录本次调用的递增发生在暂停前还是恢复后；
5. 移除断点，自由运行固定时长，记录 tick 差；
6. 对比“命中过”和“频率接近设计值”所需证据为何不同。

### 实验 C：4 字节写观察点

1. 从 ELF/工具解析 `g_debug_target_state.tim2_ticks` 地址；
2. 安装 4 字节 write 观察点，记录槽位和工具报告；
3. 命中后用反汇编确认产生存储的指令和调用路径；
4. 检查 `last_writer_id` 是否为 `DEBUG_WRITER_TIM2_CALLBACK`；
5. 手工在调试器中写对象一次，并明确把这次命中标为“调试器注入”，不得混入应用证据；
6. 资源不足时改为在唯一写入口设断点，记录降级原因。

### 实验 D：冻结与不冻结的对照

1. `BspTim2_SetFreezePolicy(1u)`，命中后记录两次 `CNT` 和 tick；
2. 完全重启实验，改为 `0u`，在同类命中点记录相同字段；
3. 每次都读回 `DBGMCU_APB1_FZ`，不要只相信源码；
4. 若存在 ADC/DMA，分别记录其状态，禁止从 TIM2 结果外推；
5. 恢复后检查待决 IRQ 和回调序号；
6. 说明暂停时间未知为何破坏频率比较。

## 13. 自检题

1. 断点与观察点分别比较什么？
2. 为什么源代码行号不是最终断点地址？
3. 谁持有 `g_debug_target_state`，谁只是注入观察条件？
4. 为什么 Arm TRM 写“完整 DWT 有 4 个比较器”仍不能直接宣布本次有 4 个观察点？
5. `DBG_TIM2_STOP=1` 能否证明 DMA2 也停止？为什么？
6. 在 `DebugTarget_RecordTim2Tick` 入口命中时，哪次状态写入可能还没发生？
7. 为什么一个 16 字节结构体观察点可能比一个 4 字节字段消耗更多资源？
8. 观察点命中 1000 次能否证明 TIM2 是 1 kHz？还缺什么？
9. 调试器主动改变量为何必须作为新的写入者记录？
10. 比较器资源耗尽时，最小替代验证路径是什么？

## 14. 面试题

### 14.1 硬件断点和软件断点有什么区别？

硬件断点使用片上地址比较资源，不必改写目标代码，但槽位有限；软件断点通常把可写代码位置替换为陷阱指令，数量限制和存储器可写性不同。实际 IDE 如何选择必须看调试服务器日志，不能只看红点。

### 14.2 观察点为什么比普通变量窗口更适合找越权写入？

变量窗口只给某次读取值；写观察点以数据访问为触发条件，能把访问指令、调用路径和写入者固定在命中现场。不过它仍受比较器、对齐、访问类型和暂停扰动限制。

### 14.3 核心暂停后外设会怎样？

没有统一答案。以 F407 为例，TIM2 是否停止由 DBGMCU freeze 位决定；其他定时器、watchdog、ADC、DMA 和通信外设必须逐项查参考手册和实际配置。核心 halt 不等于 SoC 全冻结。

### 14.4 如何证明一个观察点真的工作？

先记录安装成功和资源槽；再执行一个已知合法写入并应命中；执行一个非目标对象写入并应不命中；最后用命中 PC/反汇编确认访问关系。三个证据缺一都不足以确认规格完整。

### 14.5 为什么调试版本正常、发布版本异常？

优化、LTO、内联、内存布局和暂停时序都可能改变；调试器还可能改变外设冻结与实时关系。应固定两套构建的 ELF/Map，比较机器代码、对象地址和自由运行证据，而不是把问题笼统归因于“优化器”。

### 14.6 断点与 trace 如何选择？

需要检查一次控制流和有限现场时用断点；需要寻找一次数据写入者时用观察点；需要连续时序且暂停不可接受时用 trace 或外部测量。选择依据是可接受扰动和证据问题，不是工具界面熟悉度。

## 15. 延伸思考

1. 如何为每个断点定义最大允许暂停时间，而实际暂停时长又如何测量？
2. 如果 DWT 的命中只在访问完成后报告，旧值应从哪里取得？
3. 开启 D-Cache（Data Cache，数据缓存）的 F7/H7 上，CPU 数据访问、总线访问与 DMA 可见值可能不一致，观察点应挂在哪一层证据？
4. H5 的安全状态限制调试访问时，工具“看不到对象”可能有哪些授权原因？
5. 如何把触发规格转成可版本控制的调试服务器脚本，同时保持 IDE 无关？
6. trace 缓冲溢出时，“没有记录到非法写入”为什么不能证明它没发生？

## 16. 本节总结

断点和观察点的可靠用法可以压缩成一条纪律：

```text
先定义问题与触发条件
  -> 从当前 ELF 解析真实地址
  -> 申请并记录有限调试资源
  -> 命中后只采集预定现场
  -> 标注核心/外设暂停边界
  -> 恢复并采集独立的自由运行证据
  -> 只作证据允许的结论
```

断点回答指令地址是否到达，观察点回答数据访问是否发生。FPB/DWT、调试服务器和 IDE 负责触发实现；应用对象所有权并未转移。Host Fake 验证规格、资源和状态机，STM32F407xx 轨道则把它落到 SWD、DBGMCU、TIM2、HAL/LL/寄存器与 IRQ/error 路径。任何一次暂停都不是连续时序、外部波形或 DMA 完整性的充分证据。

## 17. 下一步

下一主题 `fault-analysis` 将把“主动设置的触发条件”推进到“异常自动保存的故障现场”：区分 fault 状态寄存器、堆栈帧和故障指令，并继续沿用本课的地址来源、取样时机、暂停扰动和交叉证据纪律。栈回溯、trace 与逻辑分析仪仍按课程顺序分别深入。

## 18. 参考资料

- [S1] Arm，*Arm Cortex-M4 Processor Technical Reference Manual Revision r0p1*，文档 100166，version `0001`，revision 04，15 May 2020。重点：Debug、FPB、DWT；用于核对指令地址比较、数据访问比较、实现可裁剪和资源有限性。<https://developer.arm.com/documentation/100166/0001>，访问日期：2026-10-18。
- [S2] STMicroelectronics，*STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 advanced Arm-based 32-bit MCUs - Reference manual*，RM0090 Rev 22，May 2026。重点：RCC、TIM2-TIM5、Debug support pages 1671-1700；用于核对 SWJ-DP、FPB/DWT 集成、DBGMCU、TIM2 freeze 和寄存器语义。<https://www.st.com/resource/en/reference_manual/dm00031020.pdf>，访问日期：2026-10-18。
- [S3] STMicroelectronics，*STM32F405xx STM32F407xx datasheet*，DS8626 Rev 12，March 2026。用于核对器件范围、16 MHz HSI、168 MHz 边界、TIM2、SWJ-DP 与 ETM 能力；不用于推导未指定开发板连接。<https://www.st.com/resource/en/datasheet/stm32f407vg.pdf>，访问日期：2026-10-18。
- [S4] STMicroelectronics，*Description of STM32F4 HAL and low-layer drivers*，UM1725 Rev 8，March 2023。重点：HAL debug freeze/unfreeze 宏、TIM base 初始化/启动、IRQ、period elapsed/error callback 和状态 API。<https://www.st.com/resource/en/user_manual/dm00105879.pdf>，访问日期：2026-10-18。
- [S5] STMicroelectronics，*STM32Cube MCU Package for STM32F4 series*，STM32CubeF4 v1.28.3，23 July 2025。对应 HAL/LL 源码与 CMSIS device headers 是编译接口边界；源码核对不构成目标构建证据。<https://www.st.com/en/embedded-software/stm32cubef4.html>，访问日期：2026-10-18。

结构化来源元数据见同目录 `lesson.json`。Arm 文档只定义 Cortex-M4 实现边界，ST 文档只约束其覆盖的 STM32F4 器件；F7、H5、H7 必须在选定完整目标后加入对应系列第一方资料。

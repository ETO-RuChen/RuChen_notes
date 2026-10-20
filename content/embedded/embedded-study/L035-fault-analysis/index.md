+++
title = "故障分析：把异常现场变成可证伪的证据链"
date = "2026-10-19T19:13:26+08:00"
lastmod = "2026-10-19T19:13:26+08:00"
summary = "核心目标：规划一节故障分析课：用异常入口保存的状态寄存器、堆栈帧和故障指令地址建立可证伪的故障证据链，并在 STM32F407xx 上形成待目标工程验证的最小 HardFault 现场采集路径。新核心概念：异常入口的故障现场快照与有效性边界；从故障状态到可证伪根因假设的证据链。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 35
tags = ["fault-analysis", "hardfault", "exception-frame", "cfsr", "hfsr", "evidence-chain", "stm32f407", "cortex-m4", "cmsis", "hal", "host-fake", "c11"]
source_ids = ["arm-100166-r0p1-fault-analysis", "st-rm0090-fault-analysis", "st-ds8626-fault-analysis", "st-um1725-fault-analysis", "st-stm32cubef4-1.28.3-fault-analysis", "st-pm0214-fault-analysis"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L035"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 35 课：故障分析：把异常现场变成可证伪的证据链

程序进入 HardFault（硬故障）后，调试器停在一个地址，只能证明“处理器现在位于这个现场”。它不能单独证明哪条指令最先出错、访问了哪个地址、错误是否精确，也不能证明外设和 DMA（Direct Memory Access，直接存储器访问）当时处于什么状态。可靠的故障分析必须同时保存状态寄存器、异常堆栈帧、地址有效位、固件身份和下一次验证条件。

本课采用两条轨道。Host Fake（主机替身）用纯 C11 验证首错保留、有效位、无效帧、未知状态和错误路径；STM32 轨道把同一契约落实到 STM32F407xx 的 Cortex-M4F 异常入口、SCB（System Control Block，系统控制块）与 CMSIS（Cortex Microcontroller Software Interface Standard，Cortex 微控制器软件接口标准）。当前没有完整订货料号、开发板、目标工程、编译输出、烧录记录或故障现场，所有 STM32 代码均为**参考实现，待目标工程编译和上板验证**，`hardware_verified=false`。

HAL（Hardware Abstraction Layer，硬件抽象层）与 LL（Low-Layer，底层驱动）的初始化职责和内核异常采集分开。资料边界为 Arm 100166 r0p1 revision 04、RM0090 Rev 22、DS8626 Rev 12、UM1725 Rev 8、STM32CubeF4 v1.28.3 和 PM0214 Rev 10。[S1]-[S6] 本课只推进计划规定的两个新核心概念，不展开完整栈回溯、DWARF unwind（调试信息栈展开）、RTOS（Real-Time Operating System，实时操作系统）任务现场、跨复位 crash dump（崩溃转储）、自动恢复或 trace（跟踪）。

## 1. 本节目标

核心目标与本次 `plan.json` 一致：**规划一节故障分析课：用异常入口保存的状态寄存器、堆栈帧和故障指令地址建立可证伪的故障证据链，并在 STM32F407xx 上形成待目标工程验证的最小 HardFault 现场采集路径。**

新核心概念与计划一致：

1. **异常入口的故障现场快照与有效性边界**；
2. **从故障状态到可证伪根因假设的证据链**。

完成本课后，你应能：

1. 解释为什么单独一个 PC（Program Counter，程序计数器）不足以定位根因；
2. 区分原始寄存器值、经有效位确认的地址和解释后的假设；
3. 根据 `EXC_RETURN`（异常返回编码）选择 MSP（Main Stack Pointer，主堆栈指针）或 PSP（Process Stack Pointer，进程堆栈指针）；
4. 识别基本异常帧中的 R0-R3、R12、LR（Link Register，链接寄存器）、PC 和 xPSR（组合程序状态寄存器），区分栈错误导致的不完整与浮点扩展超出本课支持范围；
5. 区分精确与非精确总线错误，不把非精确错误的堆栈 PC 当作故障指令；
6. 用 C11 Host Fake 验证首错保留、地址未知、无效帧和未知状态位；
7. 审计 STM32F407xx 的异常入口、SCB 快照、CubeMX 时钟与生成文件责任边界；
8. 写出一个可以被下一次实验推翻的根因假设，而不是直接宣布修复方案。

## 2. 它解决什么问题

### 2.1 为什么只看一个 PC 不够

假设调试器显示异常帧 PC 为 `0x08001234`。至少存在以下不同解释：

- 精确数据总线错误：堆栈 PC 可以指向导致错误的指令；
- 非精确数据总线错误：错误异步报告，堆栈返回地址与真正发起错误的指令无直接关系；
- 异常入栈期间出错：保存区可能不完整，读取 PC 本身就不可靠；
- 向量表取址出错：堆栈 PC 是被异常抢占的指令，不是错误向量读取地址；
- 可配置故障未使能或优先级不足，升级为 HardFault：需要继续读取 CFSR（Configurable Fault Status Register，可配置故障状态寄存器）；
- FPU（Floating-Point Unit，浮点单元）存在扩展或懒保存状态，而采集器未实现相应核验：不能把“未支持该帧”当成“已取得有效现场”。扩展帧本身并不使核心 PC 偏移改变。[S6]

因此，一个地址必须带上来源与条件：来自哪个 SP、帧格式是什么、是否发生 stacking fault（入栈故障）、对应状态位是否表明精确、地址寄存器的有效位是否为 1、它映射到哪个 ELF（Executable and Linkable Format，可执行与可链接格式）和反汇编。

### 2.2 课程要建立的最小闭环

```text
受控故障或 Fake 输入
  -> 先锁定“首个现场”的所有权
  -> 保存 MMFAR/BFAR 原始值，再保存 CFSR/HFSR
  -> 按 EXC_RETURN 判断 MSP/PSP 与基本/扩展帧
  -> 检查栈错误和地址有效位
  -> 复制可用的基本异常帧
  -> 用当前 ELF/反汇编解释 PC/LR
  -> 写出“支持什么、不能推出什么、下一次如何反驳”
```

成功标准不是“打印出了 HardFault”，而是每个结论都能追溯到快照字段，并存在一项可能推翻它的独立实验。

## 3. 必要前置知识

本课复用已完成主题，但不把它们等同于已掌握故障解码：

- `pointer`：能区分地址值与该地址处的对象；它不能证明一个异常 SP 指向可读完整帧；
- `const-volatile`：知道 SCB 和共享快照需要受控的易变访问；`volatile` 不提供原子性或持久化；
- `vector-table`、`startup`：知道异常号如何关联 handler 符号；它们不解释 CFSR；
- `linker-script`、`elf-map`、`memory-layout`：能将 PC 映射回当前固件；不同 ELF 的同一数值地址没有同一语义；
- `stack-heap`：知道 SP 与栈边界；完整调用栈恢复仍留给下一主题 `stack`；
- `interrupt-priority`：知道异常可嵌套；HardFault 的固定优先级和 lockup（锁死）边界需要本课资料补充；
- `clock-tree`：知道内核取指和总线访问依赖时钟链；故障状态不是脱离时钟、复位和暂停条件的抽象值；
- `hal-ll-register-crosswalk`：知道 HAL、CMSIS 与寄存器属于不同层；本课的 fault status 主要属于 Cortex-M 内核/CMSIS 路径；
- `register-view`、`breakpoint-watchpoint`：知道一次读数有取样时机和暂停扰动；本课把这种证据纪律用于处理器自动建立的现场。

## 4. 核心原理

### 4.1 核心概念一：快照与有效性边界

异常入口自动保存的是“进入异常时刻的有限上下文”，不是整机录像。Cortex-M4 的基本异常帧包含 8 个 32 位字：R0、R1、R2、R3、R12、LR、PC 和 xPSR。处理器同时把 `EXC_RETURN` 写入 handler 的 LR；其低位描述返回模式、使用 MSP 还是 PSP，以及是否存在浮点扩展状态。[S6]

本课的最小实现只解析**基本帧**。若 `EXC_RETURN` 表明浮点扩展帧，或者 CFSR 表明入栈、出栈、浮点懒保存发生故障，采集器仍保存原始状态，但把 `frame_valid` 置为 0，不输出 PC。这是保守的支持范围，不是声称扩展帧的核心 PC 偏移变了：PM0214 Figure 12 中两种帧均以 R0 为最低地址，PC 均在入口 SP[6]，浮点保存区在核心 8 字的高地址侧。[S6]

对象与所有权如下：

| 对象 | 定义位置 | 持有者 | 注入者 | 生命周期与调用流 |
| --- | --- | --- | --- | --- |
| 原始状态输入 | Host 测试夹具或 SCB | 输入源 | 测试夹具/处理器硬件 | `source -> capture`，仅采集期间读取 |
| 异常帧 | Host 输入对象或当前 MSP/PSP 指向区 | 处理器建立，采集器只复制 | `EXC_RETURN` 选择 | 异常入口后存在；是否完整必须单独判断 |
| 首错快照 | Host：测试函数的 `fault_store_t`；STM32：`fault_snapshot.c` 的静态对象 | Host 测试夹具 / STM32 诊断模块 | 采集函数写入 | Host 同步调用用 occupied 拒绝重复；STM32 从 EMPTY 到 WRITING 再到 COMPLETE |
| 解释报告 | `FaultReport_Build` 输出对象 | 调用者 | 已完成快照 | 可丢弃、可重建，不改写原始证据 |
| ELF/反汇编 | 目标构建产物 | 构建系统/实验记录 | 分析者选择当前固件 | 地址解释阶段使用，不能由 MCU 快照替代 |

五个动作必须分开：

1. **声明**：头文件定义快照字段和公开函数；
2. **实现**：`.c` 文件执行有效性检查和首错保留；
3. **实例化**：Host 由测试夹具创建独立 store；STM32 模块内部静态创建唯一快照对象；
4. **组装**：Host 测试连接 Fake 输入，STM32 的 HardFault handler 连接 MSP/PSP 与采集函数；
5. **使用**：测试断言或调试器只读快照，并结合 ELF 形成假设。

### 4.2 地址寄存器必须由有效位授权

MMFAR（MemManage Fault Address Register，存储器管理故障地址寄存器）与 BFAR（BusFault Address Register，总线故障地址寄存器）复位值未定义，旧值或无效值可能仍可读。只有 CFSR 中 `MMARVALID` 或 `BFARVALID` 为 1 时，地址才可用于当前故障解释。[S6]

PM0214 还规定了容易写反的读取顺序：在 handler 中先保存 MMFAR/BFAR 的值，再读取对应有效位，因为更高优先级异常可能改变地址寄存器。[S6] 因此快照保留两层：

```text
raw_bfar = 读到的 32 位原始值       // 始终是观测事实
bfar_valid = CFSR.BFARVALID         // 是否允许解释为当前故障地址
reported_address = valid ? raw : 未知
```

“原始值是 `0x40000000`”与“当前故障地址是 `0x40000000`”是两个不同命题。

### 4.3 精确错误与非精确错误

`PRECISERR=1` 表示精确数据总线错误，堆栈 PC 指向导致错误的指令；若 `BFARVALID=1`，BFAR 还提供有效地址。`IMPRECISERR=1` 表示异步的非精确数据总线错误，处理器不会为它写入 BFAR，异常帧返回地址与真正导致错误的指令无直接关系。[S6]

因此解释顺序必须是：

```text
先分类 precise / imprecise / stacking / usage / escalation
  -> 再决定 PC 能否称为“故障指令”
  -> 再决定 MMFAR/BFAR 能否称为“故障地址”
  -> 最后才查反汇编和数据流
```

若 `PRECISERR` 与 `IMPRECISERR` 同时出现，现场可能包含先后两个事件；不能任选一个方便的故事。报告应标为混合证据并设计更小的复现实验。

### 4.4 核心概念二：可证伪证据链

证据链不是“寄存器位到答案”的查表，而是四列记录：

| 层 | 示例 | 可以支持 | 不能单独支持 |
| --- | --- | --- | --- |
| 原始现场 | CFSR、HFSR、MMFAR、BFAR、SP、8 字帧 | 某次异常入口读到了这些位和值 | 值一定属于首个错误 |
| 有效性 | BFARVALID、无 STKERR、基本帧 | 某字段满足资料规定的解释前提 | 地址映射或源代码一定正确 |
| 映射 | 固件 hash、ELF、Map、反汇编 | PC 对应当前固件中的某条指令 | 该指令一定是根因而非受害点 |
| 假设与反驳 | “该 STR 向无效地址写入” | 指定了可验证的数据流 | 修复已经有效 |

一个合格假设示例：

> CFSR 显示 `PRECISERR=1` 且 `BFARVALID=1`，基本帧有效；当前 ELF 将堆栈 PC 映射到一条 `STR`，其目标地址与 BFAR 相同。因此“该次存储使用了无效目标指针”得到支持。下一次把指针范围断言提前到调用边界；若断言从未失败而相同现场仍出现，则推翻“错误在该调用边界之前形成”的假设。

不合格结论是：“BFAR 看起来像外设地址，所以 DMA 坏了。”核心异常帧不包含 DMA stream 的完整状态，也不能说明外设请求链是否正确。

## 5. 关键术语与直观模型

| 术语 | 本课含义 |
| --- | --- |
| HardFault（硬故障） | 异常处理错误或其他故障机制无法处理时进入的固定高优先级 fault |
| MemManage fault（存储器管理故障） | 由 MPU（Memory Protection Unit，存储器保护单元）或固定内存保护约束报告的访问故障 |
| BusFault（总线故障） | 指令取址或数据事务上的总线错误，可精确或非精确 |
| UsageFault（用法故障） | 未定义指令、非法状态、异常返回错误以及可选 trap 等处理器使用错误 |
| SCB（系统控制块） | 提供系统异常控制与 fault status 的 Cortex-M 内核寄存器块 |
| CFSR | 组合 UFSR、BFSR 和 MMFSR 的可配置故障状态寄存器 |
| HFSR | 说明 HardFault 激活原因的状态寄存器；`FORCED` 常表示可配置故障升级 |
| 异常堆栈帧 | 异常入口由硬件保存的有限寄存器集合，不等于完整调用栈 |
| EXC_RETURN（异常返回编码） | 异常入口写入 LR 的特殊值，描述返回模式、栈指针与帧形态 |
| MSP / PSP | 主堆栈指针 / 进程堆栈指针；由 `EXC_RETURN` 决定当前帧来源 |
| precise / imprecise | 精确 / 非精确；决定堆栈 PC 是否与出错数据事务直接关联 |
| 可证伪假设 | 明确写出支持证据和能推翻它的下一次观测条件 |

直观上，把快照看成一份“带校验条件的现场封条”：寄存器值是封条内容，有效位和帧条件是封条是否可用于某项结论的规则，ELF 是解释地址的版本字典。缺少其中任何一项，都不能补写成确定根因。

## 6. 从输入到结果的完整流程

### 6.1 采集阶段

1. handler 入口立即保留 LR 中的 `EXC_RETURN`；
2. 检查其栈选择位，取得 MSP 或 PSP；
3. 采集器把静态对象从 EMPTY 改为 WRITING，阻止后续现场覆盖；
4. 先读取 MMFAR/BFAR 原始值；
5. 再读取 CFSR、HFSR、SHCSR（System Handler Control and State Register，系统处理器控制与状态寄存器）；
6. 判断基本/扩展帧以及 stacking/unstacking/lazy preservation 错误；
7. 只有帧条件满足时才复制 8 字基本帧；
8. 从 CFSR 导出 `mmfar_valid`、`bfar_valid`，不改写原始值；
9. 执行内存屏障，将对象状态置为 COMPLETE；
10. 最小实现原地停住，避免自动恢复污染现场。

Host 示例仅支持同步调用，`occupied` 不是并发锁。STM32 示例约定只有 HardFault 路径写入，NMI（Non-Maskable Interrupt，不可屏蔽中断）不得调用同一采集器；内存屏障只约束发布顺序，不使“检查再写入”变为原子操作。HardFault 内再次 fault 可能直接 lockup，不能保证第二次入口还有机会执行首错检查。[S6]

### 6.2 解释阶段

1. 保存目标板、完整器件、固件 commit、ELF hash、编译器、优化和 CubeF4 版本；
2. 确认快照状态为 COMPLETE，若仍是 WRITING，按部分现场处理；
3. 先查 HFSR 是否为 `FORCED`，若是则继续查 CFSR，不把 FORCED 当根因；
4. 检查栈错误和帧格式，决定 PC/LR 是否可解释；
5. 检查 precise/imprecise，决定 PC 是否能指向故障指令；
6. 只在有效位为 1 时解释 MMFAR/BFAR；
7. 用同一次构建的 ELF/反汇编映射 PC/LR；
8. 检查指令操作数、寄存器值、地址计算和对象所有权；
9. 写出假设、反证条件和下一次最小变化；
10. 修改一个条件后完整复现，比较快照，而不是只看“还会不会死”。

### 6.3 输出模板

```text
事实：HFSR.FORCED=1，CFSR.PRECISERR=1，BFARVALID=1，BFAR=...
前提：基本帧有效；固件 hash 与 ELF 一致；无 STKERR/LSPERR
映射：stacked PC -> 当前反汇编的某条 load/store
假设：该指令使用的地址计算在本次输入下越界
不能推出：DMA、外设、供电或所有运行都错误
反证：在地址形成点加入范围记录；若范围始终合法而故障仍复现，则推翻该假设
```

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

| 层级 | 能力与信号/数据路径 | 本课落点或后续课程 |
| --- | --- | --- |
| 基础 | fault 发生 -> 异常入口 -> 保存 SCB 与基本帧 -> 调试器读取 | 本课深入最小 HardFault 快照 |
| 进阶 | 有效位 + precise/imprecise + ELF/反汇编 -> 可证伪假设 -> 对照复现 | 本课给出完整记录表和实验 |
| 高级 | 嵌套异常会改变优先级和地址寄存器；FPU 扩展/懒保存改变帧布局；MPU 提供更早的访问边界；持久 crash dump 与看门狗协作跨复位交接；trace 保存暂停前连续控制流 | 分别在 `stack`、MPU、可靠性和 trace 路线深入；本课遇到这些条件就标无效或待核对 |
| 跨外设联动 | `RCC -> core clock -> CPU load/store -> bus/peripheral/DMA`；外设错误可能成为总线背景，但核心帧不携带完整外设状态 | 复用 TIM2 -> ADC1 -> DMA2 作为观察清单，不重讲 DMA |
| 系列差异 | 保留“先采集、标有效性、再映射、再反证”的契约；内核、缓存、总线、安全状态、fault 寄存器和调试授权逐系列重查 | F407 是本课唯一落实目标；F7/H5/H7 在对应系列第一方资料齐备后深化 |

高级路径不是功能名列表：FPU 扩展帧在核心 8 字的高地址侧增加浮点保存区，核心 PC 仍是入口 SP[6]；本课拒绝扩展帧是因为未实现完整浮点状态核验，不应擅自给 PC 加 18 字偏移。[S6] MPU 将非法访问转换为可分类的 MemManage 证据，但前提是区域、权限和 handler 已正确配置；持久转储必须解决 RAM 初始化、掉电、版本和校验所有权；trace 通过时间序列补充非精确错误的前因，但缓冲溢出仍不能证明事件未发生。

迁移审计：

| 目标 | 保留 | 必须按目标资料重查 |
| --- | --- | --- |
| STM32F407xx | 首错静态快照、有效位、8 字基本帧证据纪律 | 本课按 Cortex-M4F、RM0090、PM0214 落实 |
| F7 | 证据链与只读报告接口 | Cortex-M7 fault 模型、缓存/写缓冲、总线实现、Cube 包符号；不得由 F407 外推 |
| H5 | 原始值与解释值分离 | 具体 Cortex-M33/Armv8-M、安全/非安全状态、TrustZone 调试授权和系列 fault 资料 |
| H7 | 首错保留与固件身份绑定 | 具体内核、D-Cache、多总线/时钟域、写缓冲、双核或安全配置及调试冻结 |

### 7.2 参考目标与时钟/复位链

参考器件为 `STM32F407xx`，内核为 Cortex-M4F；不假定完整订货料号、封装、开发板、HSE 晶振、SWD 接线或外部电路。[S2][S3]

本课使用板级依赖最少的 HSI 参考配置：

```text
内部 HSI 16 MHz
  -> PLL 关闭
  -> SYSCLK 选择 HSI，设计值 16 MHz
  -> AHB 预分频 /1
  -> HCLK / Cortex-M4 内核与 AHB，设计值 16 MHz
  -> CPU 取指、load/store、异常入口、SCB 访问

HCLK
  -> APB1 /1，设计值 16 MHz
  -> APB2 /1，设计值 16 MHz
```

这些是参考配置值，不是运行证据。目标实验必须读回 `RCC_CFGR`、`SystemCoreClock` 或 `HAL_RCC_GetHCLKFreq()`，并记录板卡和供电条件。SCB 不是由普通 F4 外设 RCC 门控位开启的外设；异常入口随内核运行。RCC 对 DMA、TIM、ADC 等外设的门控与复位只决定故障背景，不能代替核心快照。[S2][S6]

复位与暂停链必须分开：

```text
系统复位 -> 向量表初始 MSP/Reset_Handler -> SystemInit -> C 运行时初始化
         -> HAL_Init -> SystemClock_Config -> 应用

HardFault -> 硬件保存现场 -> HardFault_Handler -> 静态 RAM 快照 -> 停住
调试器 halt -> 核心停止；外设/DMA/看门狗是否继续必须逐项核对
```

本课不把普通 `.bss` 快照当作跨复位持久存储。调试器复位、软件系统复位和看门狗复位可能使 C 运行时重新初始化对象；跨复位保存需要链接段、完整器件复位语义、校验和与版本协议，留到可靠性课程。

### 7.3 CubeMX、HAL、LL 与寄存器对照

#### CubeMX/CubeMX2 配置清单

1. 选择具体 `STM32F407xx` 器件；完整料号和封装由实验者填写；
2. `System Core -> SYS -> Debug` 保持 Serial Wire，具体 SWD 引脚由选定封装/板卡核对；
3. RCC 选择 HSI，PLL 关闭；Clock Configuration 记录 SYSCLK/HCLK/PCLK1/PCLK2 均为设计值 16 MHz；
4. 不为 SCB 创建外设句柄，也不虚构 HAL fault callback；
5. 生成并审计 startup 向量表、`system_stm32f4xx.c`、`stm32f4xx_it.c`、`main.c`；
6. 确认 `HardFault_Handler` 的强定义最终进入 ELF，检查 map 文件没有被另一同名符号替代；
7. 记录 CubeMX、STM32CubeF4、编译器、优化、浮点 ABI（Application Binary Interface，应用二进制接口）和链接脚本版本；
8. 若启用硬件浮点或 lazy stacking（懒压栈），本课最小解析器应拒绝扩展帧，不能假装支持。

#### HAL、CMSIS、LL/寄存器责任边界

| 层 | 本课对象/调用 | 作用 | 不能替代什么 |
| --- | --- | --- | --- |
| startup/向量表 | `HardFault_Handler` 符号 | 把异常号 3 路由到入口 | 不采集 CFSR |
| HAL | `HAL_Init`、`HAL_RCC_OscConfig`、`HAL_RCC_ClockConfig` | 建立 HAL 基础和参考时钟 | HAL 没有应被虚构的通用 HardFault callback |
| CMSIS | `__get_MSP`、`__get_PSP`、`SCB->CFSR` 等 | 提供内核 intrinsic（内建函数）和寄存器结构 | 不替你判断证据是否有效 |
| LL/RCC 寄存器 | HSI、SYSCLK、AHB/APB 分频读回 | 核对异常发生时处理器运行条件 | 不给出软件根因 |
| SCB 寄存器 | CFSR、HFSR、SHCSR、MMFAR、BFAR | 分类 fault 与地址有效性 | 不包含完整外设/DMA 状态 |

本例没有 `TIM_HandleTypeDef` 一类持久外设句柄。`RCC_OscInitTypeDef` 和 `RCC_ClkInitTypeDef` 是 `SystemClock_Config` 栈上的一次性配置值，由该函数持有并注入 HAL；函数返回后，运行状态在 RCC 寄存器与 `SystemCoreClock` 中。SCB 由内核实现，CMSIS 提供访问声明；`g_fault_snapshot` 才是诊断模块静态持有的应用对象。

时钟配置的 HAL -> LL -> 寄存器对照如下。LL 名称以 STM32CubeF4 v1.28.3 为参考接口边界，目标工程仍须包含实际 LL 头文件并编译核对。[S2][S5]

| HAL 配置/调用 | 对应 LL 操作 | 关键寄存器字段与检查 |
| --- | --- | --- |
| `osc.HSIState=RCC_HSI_ON` + `HAL_RCC_OscConfig` | `LL_RCC_HSI_Enable`、`LL_RCC_HSI_IsReady` | `RCC_CR.HSION/HSIRDY`，切换前等待 ready |
| `osc.PLL.PLLState=RCC_PLL_OFF` | `LL_RCC_PLL_Disable`（PLL 未供 SYSCLK 时） | `RCC_CR.PLLON/PLLRDY`；NONE 是不配置，不等于 OFF；本例从复位后的 HSI 路径开始 |
| `clk.SYSCLKSource=RCC_SYSCLKSOURCE_HSI` | `LL_RCC_SetSysClkSource`、`LL_RCC_GetSysClkSource` | `RCC_CFGR.SW/SWS`，请求与实际来源要分别检查 |
| `clk.AHBCLKDivider=RCC_SYSCLK_DIV1` | `LL_RCC_SetAHBPrescaler` | `RCC_CFGR.HPRE`，决定 HCLK/内核时钟 |
| `clk.APB1CLKDivider=RCC_HCLK_DIV1` | `LL_RCC_SetAPB1Prescaler` | `RCC_CFGR.PPRE1`，决定 PCLK1 |
| `clk.APB2CLKDivider=RCC_HCLK_DIV1` | `LL_RCC_SetAPB2Prescaler` | `RCC_CFGR.PPRE2`，决定 PCLK2 |
| `SCB->CFSR/HFSR/...` | 无 STM32 外设 LL 包装；走 CMSIS | Cortex-M SCB 内核寄存器，不是 RCC 门控外设 |

关键对照：

| 现象/API | 硬件字段或事件 | 解释边界 |
| --- | --- | --- |
| handler 的 LR | `EXC_RETURN` | bit 2 选择 MSP/PSP；bit 4 区分基本/扩展浮点状态，具体编码按 PM0214 核对 |
| `SCB->HFSR` | `FORCED`、`VECTTBL` | FORCED 要继续读 CFSR；VECTTBL 时 stacked PC 是被抢占位置 |
| `SCB->CFSR` | MMFSR/BFSR/UFSR | 多位可同时存在；写 1 清除，最小采集器只读不清 |
| `SCB->MMFAR/BFAR` | 故障地址寄存器 | 必须由 MMARVALID/BFARVALID 授权 |
| CFSR `PRECISERR` | 精确数据总线错误 | stacked PC 与故障指令关联 |
| CFSR `IMPRECISERR` | 非精确数据总线错误 | BFAR 不由该错误写入，stacked PC 不指认发起指令 |
| CFSR 栈/懒保存错误 | `MSTKERR`、`STKERR`、`MLSPERR`、`LSPERR` 等 | 当前固定布局帧按无效处理 |

#### IRQ（Interrupt Request，中断请求）、DMA 回调和错误路径

HardFault 是系统异常，不经 `HAL_DMA_IRQHandler`、`HAL_TIM_IRQHandler` 或普通 HAL callback 分派。正常的 TIM2 -> ADC1 -> DMA2 链可能是：

```text
TIM2 update -> TRGO -> ADC1 conversion -> DMA2 request
  -> DMA2 stream flag -> DMA2_Stream0_IRQHandler
  -> HAL_DMA_IRQHandler -> ADC complete/error callback
```

而 HardFault 路径是：

```text
CPU fault / configurable fault escalation
  -> exception number 3 vector
  -> HardFault_Handler
  -> FaultSnapshot_Capture
```

若故障发生在 DMA 链附近，先锁存核心快照；随后由调试器按记录计划读取 DMA `NDTR`、stream flags、HAL handle state 和应用缓冲区代次。读取副作用、核心暂停时 DMA 是否继续、DBGMCU 是否冻结相关外设必须逐项标注。最小 handler 不调用复杂 HAL、`printf`、动态分配或外设重初始化，因为这些操作可能再次 fault 或覆盖证据。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

下面三个文件构成完整 C11 示例。它只验证数据契约和错误路径，不验证 Cortex-M4 实际压栈、任何寄存器位值或 STM32 行为。

#### `fault_capture.h`：声明

层次：可迁移诊断接口。依赖方向：测试/报告层依赖它，它不依赖硬件。生命周期：测试夹具持有输入、store 和报告，将 store 指针注入函数；实现本身无隐藏静态对象。

```c
#ifndef FAULT_CAPTURE_H
#define FAULT_CAPTURE_H

#include <stdint.h>

#define FAULT_STATUS_OK               ((uint8_t)0u)
#define FAULT_STATUS_BAD_ARGUMENT     ((uint8_t)1u)
#define FAULT_STATUS_BUSY             ((uint8_t)2u)
#define FAULT_STATUS_FRAME_INVALID    ((uint8_t)3u)
#define FAULT_STATUS_UNKNOWN_BITS     ((uint8_t)4u)

#define FAULT_HYP_UNCLASSIFIED        ((uint8_t)0u)
#define FAULT_HYP_PRECISE_BUS         ((uint8_t)1u)
#define FAULT_HYP_IMPRECISE_BUS       ((uint8_t)2u)
#define FAULT_HYP_MIXED_BUS           ((uint8_t)3u)
#define FAULT_HYP_USAGE               ((uint8_t)4u)
#define FAULT_HYP_ESCALATED           ((uint8_t)5u)
#define FAULT_HYP_FRAME_UNUSABLE      ((uint8_t)6u)
#define FAULT_HYP_UNKNOWN_STATUS      ((uint8_t)7u)

#define FAULT_CFSR_MMARVALID          (UINT32_C(1) << 7)
#define FAULT_CFSR_PRECISERR          (UINT32_C(1) << 9)
#define FAULT_CFSR_IMPRECISERR        (UINT32_C(1) << 10)
#define FAULT_CFSR_BFARVALID          (UINT32_C(1) << 15)
#define FAULT_CFSR_USAGE_MASK         (UINT32_C(0x030F) << 16)
#define FAULT_HFSR_VECTTBL            (UINT32_C(1) << 1)
#define FAULT_HFSR_FORCED             (UINT32_C(1) << 30)

typedef struct {
    uint32_t r0;
    uint32_t r1;
    uint32_t r2;
    uint32_t r3;
    uint32_t r12;
    uint32_t lr;
    uint32_t pc;
    uint32_t xpsr;
} fault_core_frame_t;

typedef struct {
    uint32_t cfsr;
    uint32_t hfsr;
    uint32_t shcsr;
    uint32_t raw_mmfar;
    uint32_t raw_bfar;
    uint32_t exc_return;
    fault_core_frame_t frame;
    uint8_t frame_read_ok;
    uint8_t basic_frame;
} fault_input_t;

typedef struct {
    uint32_t cfsr;
    uint32_t hfsr;
    uint32_t shcsr;
    uint32_t raw_mmfar;
    uint32_t raw_bfar;
    uint32_t exc_return;
    fault_core_frame_t frame;
    uint8_t occupied;
    uint8_t frame_valid;
    uint8_t mmfar_valid;
    uint8_t bfar_valid;
    uint8_t unknown_status_bits;
} fault_store_t;

typedef struct {
    uint32_t stacked_pc;
    uint32_t mmfar;
    uint32_t bfar;
    uint8_t stacked_pc_valid;
    uint8_t fault_instruction_valid;
    uint8_t mmfar_valid;
    uint8_t bfar_valid;
    uint8_t hypothesis;
} fault_report_t;

uint8_t FaultCapture_Collect(fault_store_t *store,
                             const fault_input_t *input);
uint8_t FaultReport_Build(const fault_store_t *store,
                          fault_report_t *report);

#endif
```

#### `fault_capture.c`：实现与首错存储所有权

`known_cfsr_mask` 只接受本模型声明支持的 Cortex-M4 fault 位。遇到保留位不丢弃原始快照，而是显式返回 `FAULT_STATUS_UNKNOWN_BITS`。

```c
#include "fault_capture.h"

#include <stddef.h>

#define CFSR_MMFSR_KNOWN (UINT32_C(0xBB))
#define CFSR_BFSR_KNOWN  (UINT32_C(0xBF) << 8)
#define CFSR_UFSR_KNOWN  FAULT_CFSR_USAGE_MASK
#define CFSR_FRAME_BAD   ((UINT32_C(1) << 3)  | \
                          (UINT32_C(1) << 4)  | \
                          (UINT32_C(1) << 5)  | \
                          (UINT32_C(1) << 11) | \
                          (UINT32_C(1) << 12) | \
                          (UINT32_C(1) << 13))
#define HFSR_KNOWN       ((UINT32_C(1) << 1)  | \
                          (UINT32_C(1) << 30) | \
                          (UINT32_C(1) << 31))

static uint32_t cfsr_known_mask(void)
{
    return CFSR_MMFSR_KNOWN | CFSR_BFSR_KNOWN | CFSR_UFSR_KNOWN;
}

uint8_t FaultCapture_Collect(fault_store_t *store,
                             const fault_input_t *input)
{
    uint32_t unknown;

    if ((store == NULL) || (input == NULL)) {
        return FAULT_STATUS_BAD_ARGUMENT;
    }
    if (store->occupied != 0u) {
        return FAULT_STATUS_BUSY;
    }

    /* 首先取得所有权，后续错误也不得静默覆盖第一次输入。 */
    store->occupied = 1u;
    store->cfsr = input->cfsr;
    store->hfsr = input->hfsr;
    store->shcsr = input->shcsr;
    store->raw_mmfar = input->raw_mmfar;
    store->raw_bfar = input->raw_bfar;
    store->exc_return = input->exc_return;
    store->mmfar_valid =
        (uint8_t)((input->cfsr & FAULT_CFSR_MMARVALID) != 0u);
    store->bfar_valid =
        (uint8_t)((input->cfsr & FAULT_CFSR_BFARVALID) != 0u);

    unknown = (input->cfsr & ~cfsr_known_mask()) |
              (input->hfsr & ~HFSR_KNOWN);
    store->unknown_status_bits = (uint8_t)(unknown != 0u);

    store->frame_valid =
        (uint8_t)((input->frame_read_ok != 0u) &&
                  (input->basic_frame != 0u) &&
                  ((input->cfsr & CFSR_FRAME_BAD) == 0u));
    if (store->frame_valid == 0u) {
        return FAULT_STATUS_FRAME_INVALID;
    }

    store->frame = input->frame;
    if (store->unknown_status_bits != 0u) {
        return FAULT_STATUS_UNKNOWN_BITS;
    }
    return FAULT_STATUS_OK;
}

uint8_t FaultReport_Build(const fault_store_t *store,
                          fault_report_t *report)
{
    uint8_t precise;
    uint8_t imprecise;

    if ((store == NULL) || (report == NULL) ||
        (store->occupied == 0u)) {
        return FAULT_STATUS_BAD_ARGUMENT;
    }

    report->stacked_pc = 0u;
    report->mmfar = 0u;
    report->bfar = 0u;
    report->stacked_pc_valid = 0u;
    report->fault_instruction_valid = 0u;
    report->mmfar_valid = 0u;
    report->bfar_valid = 0u;
    report->hypothesis = FAULT_HYP_UNCLASSIFIED;

    /* 地址有效性不依赖帧可读性：先保留独立有效的两类地址。 */
    if (store->mmfar_valid != 0u) {
        report->mmfar = store->raw_mmfar;
        report->mmfar_valid = 1u;
    }
    if (store->bfar_valid != 0u) {
        report->bfar = store->raw_bfar;
        report->bfar_valid = 1u;
    }

    if (store->frame_valid == 0u) {
        report->hypothesis = FAULT_HYP_FRAME_UNUSABLE;
        return FAULT_STATUS_FRAME_INVALID;
    }

    /* 可读的 stacked PC 首先是异常返回地址，不自动等于故障指令。 */
    report->stacked_pc = store->frame.pc;
    report->stacked_pc_valid = 1u;
    if (store->unknown_status_bits != 0u) {
        report->hypothesis = FAULT_HYP_UNKNOWN_STATUS;
        return FAULT_STATUS_UNKNOWN_BITS;
    }

    precise = (uint8_t)((store->cfsr & FAULT_CFSR_PRECISERR) != 0u);
    imprecise =
        (uint8_t)((store->cfsr & FAULT_CFSR_IMPRECISERR) != 0u);
    if ((precise != 0u) && (imprecise != 0u)) {
        report->hypothesis = FAULT_HYP_MIXED_BUS;
    } else if (imprecise != 0u) {
        report->hypothesis = FAULT_HYP_IMPRECISE_BUS;
    } else if (precise != 0u) {
        report->hypothesis = FAULT_HYP_PRECISE_BUS;
        /* 仅无冲突的精确总线状态允许 PC 成为故障指令候选。 */
        report->fault_instruction_valid =
            (uint8_t)(((store->cfsr & ~(FAULT_CFSR_PRECISERR |
                                       FAULT_CFSR_BFARVALID)) == 0u) &&
                      ((store->hfsr & ~FAULT_HFSR_FORCED) == 0u));
    } else if ((store->cfsr & FAULT_CFSR_USAGE_MASK) != 0u) {
        report->hypothesis = FAULT_HYP_USAGE;
    } else if ((store->hfsr & FAULT_HFSR_FORCED) != 0u) {
        report->hypothesis = FAULT_HYP_ESCALATED;
    } else {
        report->hypothesis = FAULT_HYP_UNCLASSIFIED;
    }
    return FAULT_STATUS_OK;
}
```

#### `test_fault_capture.c`：实例化、组装和使用

测试夹具实例化 store，注入人工帧和状态值，调用采集与报告接口。它不是 STM32 寄存器模拟器。

```c
#include "fault_capture.h"

#include <assert.h>
#include <stdio.h>

static fault_input_t valid_precise_input(void)
{
    fault_input_t input = {0};

    input.cfsr = FAULT_CFSR_PRECISERR | FAULT_CFSR_BFARVALID;
    input.hfsr = FAULT_HFSR_FORCED;
    input.raw_bfar = UINT32_C(0x40001000);
    input.exc_return = UINT32_C(0xFFFFFFF9);
    input.frame.pc = UINT32_C(0x08001234);
    input.frame.lr = UINT32_C(0x08001001);
    input.frame.xpsr = UINT32_C(0x21000000);
    input.frame_read_ok = 1u;
    input.basic_frame = 1u;
    return input;
}

static void test_precise_fault_and_first_fault_retention(void)
{
    fault_store_t store = {0};
    fault_report_t report = {0};
    fault_input_t first = valid_precise_input();
    fault_input_t second = valid_precise_input();

    assert(FaultCapture_Collect(&store, &first) == FAULT_STATUS_OK);
    assert(FaultReport_Build(&store, &report) == FAULT_STATUS_OK);
    assert(report.hypothesis == FAULT_HYP_PRECISE_BUS);
    assert(report.stacked_pc_valid == 1u);
    assert(report.stacked_pc == UINT32_C(0x08001234));
    assert(report.fault_instruction_valid == 1u);
    assert(report.mmfar_valid == 0u);
    assert(report.bfar_valid == 1u);
    assert(report.bfar == UINT32_C(0x40001000));

    second.frame.pc = UINT32_C(0x08009998);
    assert(FaultCapture_Collect(&store, &second) == FAULT_STATUS_BUSY);
    assert(store.frame.pc == UINT32_C(0x08001234));
}

static void test_address_without_valid_bit_is_unknown(void)
{
    fault_store_t store = {0};
    fault_report_t report = {0};
    fault_input_t input = valid_precise_input();

    input.cfsr = FAULT_CFSR_PRECISERR;
    input.raw_bfar = UINT32_C(0xDEADBEEF);
    assert(FaultCapture_Collect(&store, &input) == FAULT_STATUS_OK);
    assert(FaultReport_Build(&store, &report) == FAULT_STATUS_OK);
    assert(store.raw_bfar == UINT32_C(0xDEADBEEF));
    assert(report.bfar_valid == 0u);
    assert(report.bfar == 0u);
}

static void test_two_valid_address_registers_are_kept_separate(void)
{
    fault_store_t store = {0};
    fault_report_t report = {0};
    fault_input_t input = valid_precise_input();

    input.cfsr |= FAULT_CFSR_MMARVALID;
    input.raw_mmfar = UINT32_C(0x20000100);
    assert(FaultCapture_Collect(&store, &input) == FAULT_STATUS_OK);
    assert(FaultReport_Build(&store, &report) == FAULT_STATUS_OK);
    assert(report.mmfar_valid == 1u);
    assert(report.mmfar == UINT32_C(0x20000100));
    assert(report.bfar_valid == 1u);
    assert(report.bfar == UINT32_C(0x40001000));
}

static void test_invalid_frame_has_explicit_error(void)
{
    fault_store_t store = {0};
    fault_report_t report = {0};
    fault_input_t input = valid_precise_input();

    input.frame_read_ok = 0u;
    input.cfsr |= FAULT_CFSR_MMARVALID;
    input.raw_mmfar = UINT32_C(0x20000100);
    assert(FaultCapture_Collect(&store, &input) ==
           FAULT_STATUS_FRAME_INVALID);
    assert(store.occupied == 1u);
    assert(store.frame_valid == 0u);
    assert(FaultReport_Build(&store, &report) ==
           FAULT_STATUS_FRAME_INVALID);
    assert(report.hypothesis == FAULT_HYP_FRAME_UNUSABLE);
    assert(report.stacked_pc_valid == 0u);
    assert(report.fault_instruction_valid == 0u);
    assert(report.mmfar_valid == 1u);
    assert(report.mmfar == UINT32_C(0x20000100));
    assert(report.bfar_valid == 1u);
    assert(report.bfar == UINT32_C(0x40001000));
    input.raw_bfar = UINT32_C(0x40002000);
    assert(FaultCapture_Collect(&store, &input) == FAULT_STATUS_BUSY);
    assert(store.raw_bfar == UINT32_C(0x40001000));
}

static void test_unknown_status_bit_is_not_silently_accepted(void)
{
    fault_store_t store = {0};
    fault_report_t report = {0};
    fault_input_t input = valid_precise_input();

    input.cfsr |= (UINT32_C(1) << 6);
    assert(FaultCapture_Collect(&store, &input) ==
           FAULT_STATUS_UNKNOWN_BITS);
    assert(FaultReport_Build(&store, &report) ==
           FAULT_STATUS_UNKNOWN_BITS);
    assert(report.hypothesis == FAULT_HYP_UNKNOWN_STATUS);
}

static void test_imprecise_fault_rejects_pc_as_cause(void)
{
    fault_store_t store = {0};
    fault_report_t report = {0};
    fault_input_t input = valid_precise_input();

    input.cfsr = FAULT_CFSR_IMPRECISERR;
    assert(FaultCapture_Collect(&store, &input) == FAULT_STATUS_OK);
    assert(FaultReport_Build(&store, &report) == FAULT_STATUS_OK);
    assert(report.hypothesis == FAULT_HYP_IMPRECISE_BUS);
    assert(report.stacked_pc_valid == 1u);
    assert(report.fault_instruction_valid == 0u);
    assert(report.bfar_valid == 0u);
}

static void test_each_defined_usage_bit_is_classified(void)
{
    const uint32_t bits[] = {16u, 17u, 18u, 19u, 24u, 25u};
    uint32_t i;

    for (i = 0u; i < 6u; ++i) {
        fault_store_t store = {0};
        fault_report_t report = {0};
        fault_input_t input = valid_precise_input();
        input.cfsr = UINT32_C(1) << bits[i];
        assert(FaultCapture_Collect(&store, &input) == FAULT_STATUS_OK);
        assert(FaultReport_Build(&store, &report) == FAULT_STATUS_OK);
        assert(report.hypothesis == FAULT_HYP_USAGE);
        assert(report.stacked_pc_valid == 1u);
        assert(report.fault_instruction_valid == 0u);
    }
}

static void test_vector_or_debug_status_rejects_instruction_claim(void)
{
    const uint32_t bits[] = {FAULT_HFSR_VECTTBL, UINT32_C(1) << 31};
    uint32_t i;

    for (i = 0u; i < 2u; ++i) {
        fault_store_t store = {0};
        fault_report_t report = {0};
        fault_input_t input = valid_precise_input();
        input.hfsr |= bits[i];
        assert(FaultCapture_Collect(&store, &input) == FAULT_STATUS_OK);
        assert(FaultReport_Build(&store, &report) == FAULT_STATUS_OK);
        assert(report.stacked_pc_valid == 1u);
        assert(report.fault_instruction_valid == 0u);
    }
}

static void test_cross_domain_status_rejects_instruction_claim(void)
{
    fault_store_t store = {0};
    fault_report_t report = {0};
    fault_input_t input = valid_precise_input();

    input.cfsr |= (UINT32_C(1) << 1) | FAULT_CFSR_MMARVALID;
    input.raw_mmfar = UINT32_C(0x20000100);
    assert(FaultCapture_Collect(&store, &input) == FAULT_STATUS_OK);
    assert(FaultReport_Build(&store, &report) == FAULT_STATUS_OK);
    assert(report.stacked_pc_valid == 1u);
    assert(report.fault_instruction_valid == 0u);
    assert(report.mmfar_valid == 1u);
    assert(report.bfar_valid == 1u);
}

static void test_mixed_bus_status_rejects_instruction_claim(void)
{
    fault_store_t store = {0};
    fault_report_t report = {0};
    fault_input_t input = valid_precise_input();

    input.cfsr |= FAULT_CFSR_IMPRECISERR;
    assert(FaultCapture_Collect(&store, &input) == FAULT_STATUS_OK);
    assert(FaultReport_Build(&store, &report) == FAULT_STATUS_OK);
    assert(report.hypothesis == FAULT_HYP_MIXED_BUS);
    assert(report.stacked_pc_valid == 1u);
    assert(report.fault_instruction_valid == 0u);
}

static void test_unsupported_frames_are_not_copied(void)
{
    const uint32_t bits[] = {3u, 4u, 5u, 11u, 12u, 13u};
    uint32_t i;

    for (i = 0u; i < 7u; ++i) {
        fault_store_t store = {0};
        fault_report_t report = {0};
        fault_input_t input = valid_precise_input();
        if (i < 6u) {
            input.cfsr |= UINT32_C(1) << bits[i];
        } else {
            input.basic_frame = 0u;
            input.exc_return = UINT32_C(0xFFFFFFE9);
        }
        assert(FaultCapture_Collect(&store, &input) ==
               FAULT_STATUS_FRAME_INVALID);
        assert(store.frame.pc == 0u);
        assert(FaultReport_Build(&store, &report) ==
               FAULT_STATUS_FRAME_INVALID);
        assert(report.stacked_pc_valid == 0u);
        assert(report.bfar_valid == 1u);
    }
}

static void test_bad_arguments_and_empty_store_are_rejected(void)
{
    fault_store_t store = {0};
    fault_report_t report = {0};
    fault_input_t input = valid_precise_input();

    assert(FaultCapture_Collect(0, &input) == FAULT_STATUS_BAD_ARGUMENT);
    assert(FaultCapture_Collect(&store, 0) == FAULT_STATUS_BAD_ARGUMENT);
    assert(store.occupied == 0u);
    assert(FaultReport_Build(0, &report) == FAULT_STATUS_BAD_ARGUMENT);
    assert(FaultReport_Build(&store, 0) == FAULT_STATUS_BAD_ARGUMENT);
    assert(FaultReport_Build(&store, &report) == FAULT_STATUS_BAD_ARGUMENT);
}

static void test_reserved_usage_and_hfsr_bits_are_rejected(void)
{
    uint32_t bit;

    for (bit = 20u; bit < 24u; ++bit) {
        fault_store_t store = {0};
        fault_report_t report = {0};
        fault_input_t input = valid_precise_input();
        input.cfsr = UINT32_C(1) << bit;
        assert(FaultCapture_Collect(&store, &input) ==
               FAULT_STATUS_UNKNOWN_BITS);
        assert(FaultReport_Build(&store, &report) ==
               FAULT_STATUS_UNKNOWN_BITS);
        assert(report.fault_instruction_valid == 0u);
    }
    {
        fault_store_t store = {0};
        fault_report_t report = {0};
        fault_input_t input = valid_precise_input();
        input.hfsr |= UINT32_C(1);
        assert(FaultCapture_Collect(&store, &input) ==
               FAULT_STATUS_UNKNOWN_BITS);
        assert(FaultReport_Build(&store, &report) ==
               FAULT_STATUS_UNKNOWN_BITS);
    }
}

int main(void)
{
    test_precise_fault_and_first_fault_retention();
    test_address_without_valid_bit_is_unknown();
    test_two_valid_address_registers_are_kept_separate();
    test_invalid_frame_has_explicit_error();
    test_unknown_status_bit_is_not_silently_accepted();
    test_imprecise_fault_rejects_pc_as_cause();
    test_each_defined_usage_bit_is_classified();
    test_vector_or_debug_status_rejects_instruction_claim();
    test_cross_domain_status_rejects_instruction_claim();
    test_mixed_bus_status_rejects_instruction_claim();
    test_unsupported_frames_are_not_copied();
    test_bad_arguments_and_empty_store_are_rejected();
    test_reserved_usage_and_hfsr_bits_are_rejected();
    puts("fault_capture tests passed (13 groups)");
    return 0;
}
```

建议构建命令：

```text
cc -std=c11 -Wall -Wextra -Werror -pedantic fault_capture.c test_fault_capture.c -o fault_capture_test
./fault_capture_test
```

验收时记录编译器版本、完整命令、退出码和输出。13 组测试包括 UFSR 的 6 个有效位、VECTTBL/调试状态与精确错误混合、跨子域状态、无效帧仍保留地址、扩展/栈错误、空参数和保留位。`stacked_pc_valid` 只表示可读；`fault_instruction_valid` 仅表示本模型允许把该 PC 当候选，不是已经证明根因。只要有其他子域或 HFSR 冲突位，就保守拒绝该候选；即使全部断言通过，也只能证明 Fake 规则按代码工作。

### 8.2 STM32 参考实现轨道

以下实现分为声明、实现、实例化、组装和使用。公开数据只用固定宽度整数，不用动态内存。GNU 风格异常入口汇编与 `naked` 属性不是 ISO C11；它们是读取 handler LR/MSP/PSP 所必需的编译器边界。使用 Arm Compiler、IAR 或其他工具链时，必须按对应 ABI 与语法改写并检查反汇编。[S5][S6]

#### `fault_snapshot.h`：声明

```c
#ifndef FAULT_SNAPSHOT_H
#define FAULT_SNAPSHOT_H

#include <stdint.h>

#define FAULT_SNAPSHOT_EMPTY          ((uint8_t)0u)
#define FAULT_SNAPSHOT_WRITING        ((uint8_t)1u)
#define FAULT_SNAPSHOT_COMPLETE       ((uint8_t)2u)

#define FAULT_STACK_MSP               ((uint8_t)0u)
#define FAULT_STACK_PSP               ((uint8_t)1u)

typedef struct {
    uint32_t r0;
    uint32_t r1;
    uint32_t r2;
    uint32_t r3;
    uint32_t r12;
    uint32_t lr;
    uint32_t pc;
    uint32_t xpsr;
} fault_snapshot_frame_t;

typedef struct {
    uint32_t exc_return;
    uint32_t stack_pointer;
    uint32_t cfsr;
    uint32_t hfsr;
    uint32_t shcsr;
    uint32_t raw_mmfar;
    uint32_t raw_bfar;
    fault_snapshot_frame_t frame;
    uint8_t state;
    uint8_t stack_source;
    uint8_t basic_frame;
    uint8_t frame_valid;
    uint8_t mmfar_valid;
    uint8_t bfar_valid;
} fault_snapshot_t;

void FaultSnapshot_Capture(const uint32_t *stack_words,
                           uint32_t exc_return);
const volatile fault_snapshot_t *FaultSnapshot_Peek(void);

#endif
```

#### `fault_snapshot.c`：实现与静态实例

对象在本模块中静态实例化并由本模块唯一写入。下面位掩码来自 PM0214 Rev 10；移植到其他内核时必须重查。[S6]

```c
#include "fault_snapshot.h"

#include "stm32f4xx.h"
#include <stdint.h>

#define CFSR_MMARVALID_MASK           (UINT32_C(1) << 7)
#define CFSR_BFARVALID_MASK           (UINT32_C(1) << 15)
#define CFSR_FRAME_BAD_MASK           ((UINT32_C(1) << 3)  | \
                                       (UINT32_C(1) << 4)  | \
                                       (UINT32_C(1) << 5)  | \
                                       (UINT32_C(1) << 11) | \
                                       (UINT32_C(1) << 12) | \
                                       (UINT32_C(1) << 13))
#define EXC_RETURN_STACK_PSP_MASK     (UINT32_C(1) << 2)
#define EXC_RETURN_BASIC_FRAME_MASK   (UINT32_C(1) << 4)
#define F407_SRAM_START               UINT32_C(0x20000000)
#define F407_SRAM_END                 UINT32_C(0x20020000) /* exclusive */

_Static_assert(sizeof(fault_snapshot_frame_t) == 32u, "8-word core frame");

static volatile fault_snapshot_t g_fault_snapshot;

static uint8_t frame_address_in_internal_sram(uintptr_t address)
{
    /* 先用减法约束上界，避免 address + 32 溢出；不接受 CCM/外部 RAM。 */
    const uintptr_t frame_bytes = (uintptr_t)sizeof(fault_snapshot_frame_t);
    return (uint8_t)(((address & (uintptr_t)3u) == 0u) &&
                     (address >= (uintptr_t)F407_SRAM_START) &&
                     (address <= (uintptr_t)F407_SRAM_END - frame_bytes));
}

const volatile fault_snapshot_t *FaultSnapshot_Peek(void)
{
    return &g_fault_snapshot;
}

void FaultSnapshot_Capture(const uint32_t *stack_words,
                           uint32_t exc_return)
{
    uint32_t raw_mmfar;
    uint32_t raw_bfar;
    uint32_t cfsr;
    uint8_t pointer_in_sram;

    if (g_fault_snapshot.state != FAULT_SNAPSHOT_EMPTY) {
        for (;;) {
            __NOP();
        }
    }

    g_fault_snapshot.state = FAULT_SNAPSHOT_WRITING;
    g_fault_snapshot.exc_return = exc_return;
    g_fault_snapshot.stack_pointer = (uint32_t)(uintptr_t)stack_words;
    g_fault_snapshot.stack_source =
        (uint8_t)(((exc_return & EXC_RETURN_STACK_PSP_MASK) != 0u) ?
                  FAULT_STACK_PSP : FAULT_STACK_MSP);
    g_fault_snapshot.basic_frame =
        (uint8_t)((exc_return & EXC_RETURN_BASIC_FRAME_MASK) != 0u);

    /* PM0214 要求先保存地址寄存器，再检查 CFSR 的有效位。 */
    raw_mmfar = SCB->MMFAR;
    raw_bfar = SCB->BFAR;
    cfsr = SCB->CFSR;

    g_fault_snapshot.raw_mmfar = raw_mmfar;
    g_fault_snapshot.raw_bfar = raw_bfar;
    g_fault_snapshot.cfsr = cfsr;
    g_fault_snapshot.hfsr = SCB->HFSR;
    g_fault_snapshot.shcsr = SCB->SHCSR;
    g_fault_snapshot.mmfar_valid =
        (uint8_t)((cfsr & CFSR_MMARVALID_MASK) != 0u);
    g_fault_snapshot.bfar_valid =
        (uint8_t)((cfsr & CFSR_BFARVALID_MASK) != 0u);

    pointer_in_sram =
        frame_address_in_internal_sram((uintptr_t)stack_words);
    g_fault_snapshot.frame_valid =
        (uint8_t)((stack_words != (const uint32_t *)0) &&
                  (pointer_in_sram != 0u) &&
                  (g_fault_snapshot.basic_frame != 0u) &&
                  ((MPU->CTRL & UINT32_C(1)) == 0u) &&
                  ((cfsr & CFSR_FRAME_BAD_MASK) == 0u));

    if (g_fault_snapshot.frame_valid != 0u) {
        g_fault_snapshot.frame.r0 = stack_words[0];
        g_fault_snapshot.frame.r1 = stack_words[1];
        g_fault_snapshot.frame.r2 = stack_words[2];
        g_fault_snapshot.frame.r3 = stack_words[3];
        g_fault_snapshot.frame.r12 = stack_words[4];
        g_fault_snapshot.frame.lr = stack_words[5];
        g_fault_snapshot.frame.pc = stack_words[6];
        g_fault_snapshot.frame.xpsr = stack_words[7];
    }

    __DMB();
    g_fault_snapshot.state = FAULT_SNAPSHOT_COMPLETE;
    __DMB();

    for (;;) {
        __NOP();
    }
}
```

范围检查依据 RM0090 第 2.3 节及 Table 3：F407 的 SRAM1/SRAM2 合计为 `[0x20000000, 0x20020000)`。[S2] 只接受其中 4 字节对齐且完整 32 字节均在范围内的核心帧；不对 CCM、外部 RAM 或其他系列开放读取。地址在 RAM 内仍不能证明其内容未被破坏；代码还检查 MPU_CTRL.ENABLE：MPU 启用时直接不读帧，只保留状态，避免把物理 RAM 范围当作访问权限证明；若需支持保护区，应另行审计权限。[S6, 4.2.6] 该函数不是通用安全探测器。

另一个前置是 **handler 使用的 MSP 仍有可写空间，且快照对象可写**：普通 C 入口本身可能压栈。本实现没有紧急栈或栈损坏恢复协议，若 MSP 已损坏，可能尚未完成快照就 lockup；WRITING 状态只能视为部分证据。CCM/多栈迁移应使用目标链接符号和权限表单独扩展，不把后续 `stack` 课当作运行本参考路径的前置条件。

#### `stm32f4xx_it.c`：组装异常入口

```c
#include "fault_snapshot.h"

/* GNU Arm Embedded / armclang GNU-style assembly reference only. */
__attribute__((naked)) void HardFault_Handler(void)
{
    __asm volatile (
        "tst lr, #4\n"
        "ite eq\n"
        "mrseq r0, msp\n"
        "mrsne r0, psp\n"
        "mov r1, lr\n"
        "b FaultSnapshot_Capture\n"
    );
}
```

调用流为：向量表中的 `HardFault_Handler` 符号 -> 入口 veneer（薄入口）保留 LR 并选择 SP -> `FaultSnapshot_Capture(stack_words, exc_return)` -> 静态快照。应检查最终反汇编，确认编译器没有在读取 LR 之前生成压栈序言。若工具链不支持该属性/语法，必须使用其官方汇编入口机制，不能删掉检查后声称等价。

#### `main.c` / `bsp_clock.c`：HAL 初始化和参考时钟

```c
#include "main.h"
#include "fault_snapshot.h"

static void SystemClock_Config(void);
void Error_Handler(void);

int main(void)
{
    if (HAL_Init() != HAL_OK) {
        Error_Handler();
    }
    SystemClock_Config();

    /* 正常运行时只读接口可用于确认对象地址和初始状态。 */
    (void)FaultSnapshot_Peek();

    for (;;) {
        __WFI();
    }
}

static void SystemClock_Config(void)
{
    RCC_OscInitTypeDef osc = {0};
    RCC_ClkInitTypeDef clk = {0};

    osc.OscillatorType = RCC_OSCILLATORTYPE_HSI;
    osc.HSIState = RCC_HSI_ON;
    osc.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
    osc.PLL.PLLState = RCC_PLL_OFF;
    if (HAL_RCC_OscConfig(&osc) != HAL_OK) {
        Error_Handler();
    }

    clk.ClockType = RCC_CLOCKTYPE_SYSCLK |
                    RCC_CLOCKTYPE_HCLK |
                    RCC_CLOCKTYPE_PCLK1 |
                    RCC_CLOCKTYPE_PCLK2;
    clk.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
    clk.AHBCLKDivider = RCC_SYSCLK_DIV1;
    clk.APB1CLKDivider = RCC_HCLK_DIV1;
    clk.APB2CLKDivider = RCC_HCLK_DIV1;
    if (HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_0) != HAL_OK) {
        Error_Handler();
    }
}

void Error_Handler(void)
{
    __disable_irq();
    for (;;) {
        __NOP();
    }
}
```

`HAL_Init` 初始化 HAL 基础、优先级分组和 tick 边界；`SystemClock_Config` 的结构字段分别选择振荡源、HSI 状态、PLL 状态、系统时钟源和 AHB/APB 分频。[S4][S5] `HAL_Init` 和两个 RCC HAL 调用均检查返回值。该时钟片段仅适用于真实复位后仍由 HSI 供 SYSCLK、未被 bootloader 或定制 `SystemInit` 改成 PLL 的入口；PLL 正用作 SYSCLK 时不可直接关闭，HAL 会拒绝相应操作，迁移时应先设计切回 HSI 的顺序。[S4]`FLASH_LATENCY_0` 只属于本 16 MHz 参考配置，目标工程仍须按完整料号、供电范围和数据手册的 Flash 条件核对。`Error_Handler` 不是 HardFault callback，也不伪造 SCB 现场；它只处理显式初始化失败。目标构建必须核对 `HAL_RCC_ClockConfig` 后的 `SystemCoreClock` 与 HCLK 读回。

#### 受控故障注入边界

不要在未知板卡或生产固件中随意写非法地址。目标实验可以在专用调试构建中选择一项资料明确、可恢复靠复位的注入，并保留源码和反汇编。例如启用 divide-by-zero trap 后执行运行时除零，或访问经选定器件内存图确认的非法地址。具体注入方式、编译器是否优化、CCR 配置和期望 CFSR 位必须在目标工程中重新核对；本课不声称已执行。

#### 目标构建、烧录和观察步骤

1. 固定完整料号、板卡、探针、CubeMX/CubeF4 与编译器版本；
2. 生成工程并加入上述模块，检查 map 中只有一个强 `HardFault_Handler`；
3. 检查 handler 反汇编：首批指令必须在普通 C 序言前选择 MSP/PSP 并传递 LR；
4. 构建并保存命令、输出、ELF/Map 与 hash；
5. 烧录后先读回时钟树和快照初始状态；
6. 启用受控注入点，完整复位后仅触发一次；
7. 在 `FaultSnapshot_Capture` 的最终循环暂停，导出整个 `g_fault_snapshot`；
8. 保存 SCB 原始值、SP、帧、反汇编、外设暂停矩阵和复位方式；
9. 修改一个条件重新构建，尝试推翻假设；
10. 只有上述运行证据存在时，才能讨论硬件验证状态。本课未执行这些步骤。

## 9. 最小代码示例

如果暂时只记住一个判断流程，使用下面的伪代码；它不是寄存器实现的替代品：

```c
capture_raw_status_first();

if (frame_is_basic && frame_range_is_readable && !stacking_failed) {
    copy_basic_frame();
} else {
    mark_pc_unknown();
}

if (bfar_valid) {
    report_bfar_as_candidate_address();
} else {
    report_address_unknown();
}

if (imprecise_bus_fault) {
    do_not_call_stacked_pc_the_faulting_instruction();
}

bind_to_exact_elf();
write_hypothesis_and_disproof_condition();
```

最小原则是：**先保存事实，再判断字段是否可解释，最后才形成假设。**

## 10. 常见错误

### 10.1 把 handler 当前 PC 当作故障 PC

调试器暂停在 `FaultSnapshot_Capture` 时显示的当前 PC 属于 handler。原程序的候选 PC 在有效异常帧中，两者不可混用。

### 10.2 总是读取 MSP

Thread mode 可以使用 PSP。修正：在任何 C 函数序言改变 LR/SP 之前保存 `EXC_RETURN`，按 bit 2 选择 MSP/PSP。

### 10.3 忽略浮点扩展帧

启用 FPU 与自动保存后，异常帧可能扩展。修正：最小版本为限制支持范围，把非基本帧标为未支持；但 Figure 12 的核心 PC 仍在 SP[6]，不能因扩展帧就把核心帧指针加 18 字。完整浮点状态与懒保存按 FPCCR、ABI 和官方布局另行实现并测试。[S6]

### 10.4 无条件相信 BFAR/MMFAR

地址寄存器复位值未定义，某些 fault 不写地址。修正：保留 raw 值，但只有有效位为 1 时才向报告输出地址。

### 10.5 非精确错误仍用 stacked PC 定罪

`IMPRECISERR` 是异步报告。修正：把 PC 标为“异常返回位置，不是故障指令证据”，缩小实验、检查总线写缓冲和连续 trace 路径。

### 10.6 在 handler 中 `printf` 或重新初始化外设

这些路径依赖栈、时钟、锁和外设，可能再次 fault 或改变现场。修正：只做固定大小静态复制，然后停住。

### 10.7 清状态位后才保存

CFSR/HFSR 是写 1 清除类状态。修正：最小采集器只读并复制；清除属于经过设计的恢复流程，不在本课自动执行。

### 10.8 第二次异常覆盖第一次

后续故障常是 handler 自身或被破坏状态的结果。修正：状态先从 EMPTY 改为 WRITING，任何后续入口只停住，不覆盖首个对象。

### 10.9 使用错误 ELF

相同 PC 在另一次链接中可能对应不同指令。修正：记录固件 commit、ELF hash、优化/LTO 与链接脚本。

### 10.10 从核心现场推断 DMA 完整性

核心帧没有 DMA NDTR、stream flags 或缓冲区代次。修正：把它们作为独立、注明暂停时机的观察项，不拼接成同一原子快照。

## 11. 调试观察点

### 11.1 故障现场记录表

| 字段 | 必填内容 |
| --- | --- |
| 固件身份 | commit、ELF hash、Map、编译器、优化/LTO、FPU ABI、CubeF4 版本 |
| 目标身份 | 完整料号、板卡、探针、调试服务器、供电和时钟源 |
| 入口 | handler 当前 PC、`EXC_RETURN`、MSP/PSP 选择、原始 SP |
| 快照状态 | EMPTY/WRITING/COMPLETE；是否首错 |
| fault status | CFSR、HFSR、SHCSR 十六进制原值和逐位解释 |
| 地址 | raw MMFAR/BFAR、有效位、最终“有效/未知” |
| 帧 | basic/extended、栈错误位、R0-R3/R12/LR/PC/xPSR |
| 映射 | PC/LR 对应的 ELF 符号、反汇编、源位置和指令操作数 |
| 暂停矩阵 | core、SysTick、TIM、ADC、DMA、watchdog 分别继续/冻结/未知 |
| 外设补充 | HAL 状态、NDTR、flags、缓冲区代次及读取时机/副作用 |
| 假设 | 支持证据、不能推出、下一次反证条件 |
| 复位 | 停住、调试复位、软件复位或看门狗复位；RAM 是否重新初始化 |

### 11.2 推荐只读顺序

1. 确认快照对象状态，若 COMPLETE 则优先导出它；
2. 记录 handler 当前 PC 与原始 `EXC_RETURN`；
3. 记录 raw MMFAR/BFAR、CFSR、HFSR、SHCSR；
4. 检查帧格式和栈错误，再决定是否读取帧；
5. 保存当前 ELF/Map/hash 后再做地址映射；
6. 最后读取外设/DMA 补充状态，并标注其不与异常入口原子同步；
7. 保存完现场前不清位、不改变量、不复位、不单步离开 handler。

## 12. 实战实验

### 实验 A：Host Fake 的有效性边界

1. 建立第 8.1 节三个文件并严格告警构建；
2. 运行测试，记录五类路径的返回码；
3. 把 `BFARVALID` 去掉，确认 raw BFAR 保留而报告地址为未知；
4. 注入栈错误位，确认帧不被复制；
5. 连续采集两次，确认第二次返回 BUSY 且首个 PC 不变；
6. 注入保留位，确认报告为 UNKNOWN_STATUS；
7. 写出 Fake 能证明和不能证明的各三项。

验收：不是只记录“passed”，而是列出每种输入、返回码、store 状态和报告边界。

### 实验 B：静态审计 STM32 入口

不需要开发板，但需要目标工程：

1. 生成 F407 工程，找到向量表中 HardFault 条目；
2. 确认最终链接选择本课 handler；
3. 检查入口反汇编是否在任何普通压栈前测试 LR bit 2；
4. 检查 `FaultSnapshot_Capture` 没有调用 HAL、库 I/O 或动态内存；
5. 由 map 确认静态快照位于选定 RAM 区；
6. 将编译器、ABI、优化和反汇编写入记录。

这只能成为目标构建证据，仍不是异常实际发生或上板证据。

### 实验 C：受控精确故障

前提：完整器件、板卡、探针和注入方式已由资料核对。否则只完成设计。

1. 固定时钟、固件与 ELF 身份；
2. 选择一个会产生精确 fault 的专用调试注入；
3. 完整复位并触发一次；
4. 导出快照和反汇编；
5. 验证 PC 指令的有效地址计算是否与 BFAR 对应；
6. 在地址形成边界加入记录或断言，重新构建；
7. 若新证据不符合假设，明确写“被推翻”，不要改写第一次记录。

### 实验 D：非精确与跨外设边界设计

1. 不实际制造未知危险访问，先写出可控实验设计；
2. 列出核心、AHB/APB、目标外设、DMA 与调试 halt 的时序关系；
3. 说明为何 `IMPRECISERR` 下 stacked PC 不能定罪；
4. 选择下一条独立证据：缩小写路径、禁用一项链路、DWT/trace 或目标系列支持的总线观察；
5. 将 `NDTR`、DMA flags 和缓冲区代次列为非原子补充字段；
6. 说明什么结果会推翻“DMA 导致该 fault”的假设。

## 13. 自检题

1. 为什么 handler 当前 PC 与异常帧 PC 不同？
2. `EXC_RETURN` 在本课解决哪两个选择问题？
3. 为什么没有 `BFARVALID` 时必须报告地址未知，即使 BFAR 看起来合理？
4. PM0214 为什么要求先读 MMFAR/BFAR，再读有效位？
5. 哪些 CFSR 条件会让本课拒绝解析基本帧？
6. `PRECISERR` 与 `IMPRECISERR` 对 stacked PC 的解释有什么不同？
7. HFSR `FORCED=1` 为什么不是根因答案？
8. 谁持有首错快照，谁向它注入输入，谁只能只读使用？
9. Host Fake 通过为何不能证明 Cortex-M4 实际压栈顺序？
10. 为什么 DMA NDTR 与核心异常帧不是同一个原子现场？
11. 错误 ELF 会怎样破坏证据链？
12. `hardware_verified` 为什么仍为 false？

## 14. 面试题

### 14.1 如何排查一次 Cortex-M HardFault？

先固定固件身份并保存首个现场；由 `EXC_RETURN` 选择 MSP/PSP，检查帧格式和栈错误；保存 HFSR/CFSR 与地址寄存器，按有效位解释；区分精确/非精确；再用同一 ELF 的反汇编映射 PC/LR，检查数据流并写出可反驳假设。不能从单一 PC 直接宣布根因。

### 14.2 为什么 `FORCED` 要继续看 CFSR？

它表示可配置 fault 因未使能或优先级等原因升级为 HardFault，只说明升级路径，不说明最初是 MemManage、BusFault 还是 UsageFault。[S6]

### 14.3 如何选择 MSP 和 PSP？

异常入口 LR 保存 `EXC_RETURN`。本课 GNU veneer 测试 bit 2：0 选择 MSP，1 选择 PSP，然后把原始 LR 一并传给 C 采集器。必须在编译器生成普通函数序言之前完成。

### 14.4 为什么 HardFault handler 中不建议打印？

格式化、锁、堆栈、时钟和串行外设可能已不可靠，打印还会改变外设与时间现场。最小 handler 应静态复制固定字段并停住，输出由调试器或经单独设计的持久化通道完成。

### 14.5 非精确总线错误如何继续缩小？

不能把 stacked PC 当发起指令。应缩小可疑写路径、减少并发链路、记录写入边界，必要时使用目标支持的 DWT/trace 或总线证据，并验证写缓冲、缓存和外设状态。每次只改变一个条件。

### 14.6 如何避免“故障处理器又故障”？

入口尽量短，先占有首错对象，不使用动态内存/复杂 HAL/库 I/O，只读已核对的内核寄存器；解引用帧前检查整个范围、格式与栈错误，并确认 MSP 和目标记录区可用。若 HardFault/NMI 内再次发生 HardFault，处理器可能进入 lockup，只能由复位、NMI 或调试 halt 等资料规定路径处理；若从 NMI handler 进入 lockup，后续 NMI 不能让它退出。[S6]

## 15. 延伸思考

1. 如何用链接符号描述多个 SRAM/CCM 区域，同时在解引用前证明整个 8 字帧都在有效区间？
2. 快照处于 WRITING 时被调试器读到，应如何区分“部分有效”与“对象损坏”？
3. FPU lazy stacking 下，何时只分配空间，何时真正保存浮点寄存器？最小采集器应增加哪些状态字段？
4. 跨复位 crash dump 如何设计 magic、版本、长度、CRC 和固件 hash，避免把旧记录当新故障？
5. F7/H7 的缓存与写缓冲怎样改变非精确错误的定位策略？
6. H5 的安全/非安全状态和调试授权会怎样改变“调试器读不到快照”的解释？
7. 若 `PRECISERR` 和 `IMPRECISERR` 同时出现，怎样设计实验区分先后事件？
8. 看门狗在 handler 中继续运行时，是帮助系统恢复还是破坏现场？需要哪些产品级约束？

## 16. 本节总结

本课建立了两个核心机制。第一，异常入口快照有严格有效性边界：`EXC_RETURN` 决定栈来源和帧形态，栈错误决定帧是否可读，有效位决定 MMFAR/BFAR 是否能解释为当前地址，precise/imprecise 决定 PC 能否指认故障指令。第二，根因必须通过证据链形成：原始现场 -> 有效性条件 -> 当前 ELF/反汇编 -> 可证伪假设 -> 独立复现。

Host Fake 验证首错保留和错误路径；STM32F407xx 参考实现给出向量入口、静态对象、SCB 采集、HSI 时钟链、CubeMX/HAL/CMSIS 边界和目标实验步骤。两条轨道互相解释，但不能互相替代。当前 STM32 代码未编译、未烧录、未触发、未测量，`hardware_verified=false`。

## 17. 下一步

下一主题 `stack` 将从本课“已确认有效的基本异常帧”继续到调用栈、ABI、优化和链接边界，学习怎样恢复可验证的调用链。本课不提前实现 DWARF unwind，也不把一次 backtrace（回溯）输出当成根因。

## 18. 参考资料

- [S1] Arm，*Arm Cortex-M4 Processor Technical Reference Manual Revision r0p1*，document 100166，version `0001`，revision 04，15 May 2020。用于核对 Cortex-M4 exception model、fault handling、SCB 与 exception return 的体系结构边界。<https://developer.arm.com/documentation/100166/0001>，资料复核日期：2026-10-20。
- [S2] STMicroelectronics，*STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 advanced Arm-based 32-bit MCUs - Reference manual*，RM0090 Rev 22，May 2026。用于核对 F407 集成、RCC、系统复位和调试支持；不替代 Cortex-M4 fault 语义。<https://www.st.com/resource/en/reference_manual/dm00031020.pdf>，访问日期：2026-10-19。
- [S3] STMicroelectronics，*STM32F405xx STM32F407xx datasheet*，DS8626 Rev 12，March 2026。用于核对器件范围、Cortex-M4F、时钟与调试接口边界；不用于虚构板级连接。<https://www.st.com/resource/en/datasheet/stm32f407vg.pdf>，访问日期：2026-10-19。
- [S4] STMicroelectronics，*Description of STM32F4 HAL and low-layer drivers*，UM1725 Rev 8，March 2023。用于核对 HAL 初始化、RCC 结构和应用集成责任；没有据此虚构 HAL fault callback。<https://www.st.com/resource/en/user_manual/dm00105879.pdf>，访问日期：2026-10-19。
- [S5] STMicroelectronics，*STM32Cube MCU Package for STM32F4 series*，STM32CubeF4 v1.28.3（官方版本页的 Patch-CubeF4 条目；精确发行日期未核实）。CMSIS core/device headers、startup、HAL/LL 与生成文件是参考代码边界；仍需在目标包编译核对。<https://www.st.com/en/embedded-software/stm32cubef4.html>，访问日期：2026-10-19。
- [S6] STMicroelectronics，*STM32 Cortex-M4 MCUs and MPUs programming manual*，PM0214 Rev 10，March 2020。重点：2.3.7 exception entry/return、2.4 fault handling、4.4.10-4.4.18 CFSR/HFSR/MMFAR/BFAR 与读取顺序。<https://www.st.com/resource/en/programming_manual/dm00046982.pdf>，访问日期：2026-10-19。

结构化来源元数据见同目录 `lesson.json`。F407 结论不得外推到 F7、H5、H7；对应系列深化前必须加入目标系列第一方手册、勘误和 Cube 包版本。

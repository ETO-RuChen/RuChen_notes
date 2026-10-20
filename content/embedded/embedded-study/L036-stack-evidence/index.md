+++
title = "栈：从 SP（栈指针）与内存边界到可信的调用现场"
date = "2026-10-20T20:33:03+08:00"
lastmod = "2026-10-20T20:33:03+08:00"
summary = "核心目标：建立以 SP、栈边界和编译产物交叉验证栈使用量与调用现场的证据方法，并为 STM32F407xx 规划可核对但尚未上板的最小采样与调试路径。 新核心概念：栈边界与动态使用量的证据边界；调用现场重建的证据边界。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 36
tags = ["stack", "stack-bounds", "msp", "psp", "exception-frame", "evidence-boundary", "stm32f407", "cmsis", "hal", "host-fake", "c11"]
source_ids = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12", "S13", "S14"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L036"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 栈：从 SP（栈指针）与内存边界到可信的调用现场

> **L036 · debugging-verification / stack · 约 80 分钟**  
> 本课只有一个核心目标、两个新核心概念。Host Fake（主机替身）代码可以在主机运行；STM32F407xx 代码是**参考实现，待目标工程编译和上板验证**。本次未进行目标编译、烧录、调试器连接或波形/时序测量，`hardware_verified=false`。课程已通过 Reviewer 的文档与主机模型审查，`status=reviewed`；这不代表目标工程已验证或用户已掌握，审查记录见本次运行目录的 `review.md`。

## 1. 本节目标

**核心目标（与本次 plan.json 一致）：**建立以 SP、栈边界和编译产物交叉验证栈使用量与调用现场的证据方法，并为 STM32F407xx 规划可核对但尚未上板的最小采样与调试路径。

**新核心概念仅两个：**

1. **栈边界与动态使用量的证据边界**。
2. **调用现场重建的证据边界**。

学完后，应能对“SP 还在 RAM”“链接脚本给栈留了空间”“回溯里有三个函数”等说法补齐条件，并给出一项可能推翻当前判断的下一步观察。不会在本课实现通用栈展开器，也不会提前实现 RTOS（实时操作系统）任务栈、MPU（存储器保护单元）防护或 FPU（浮点单元）懒堆叠解析。

阅读路线：先看第 2～6 节及 8.1 的主机最小例，再看 7、8.2 和第 9 节的目标实现，最后做第 12～15 节。完整源码在本课 `host/`、`stm32/`；第 9 节展开关键文件，测试用例无需手工抄写。

## 2. 它解决什么问题

### 2.1 三个容易过度推断的现场

- 暂停后 SP 落在 SRAM（静态随机存取存储器）内，所以栈没问题？**不够。**一个地址在 SRAM 内，不等于它属于本构建为这个栈保留的区间，也不说明此前没有越界后又恢复。
- 链接脚本中的栈预留为 N 字节，所以运行只用了 N 字节以内？**不够。**静态预留描述空间安排，运行时 SP 描述一个时刻；链接器不负责持续检查 CPU 的每次压栈。[S1 §2.1.2；S2 §2；S10]
- 栈内有几个 Flash 地址，所以已找到调用链？**不够。**数据、旧帧和返回信息都可能长得像代码地址。需要该构建的指令、调试信息与可信现场互证，而不是在 SRAM 里“捡地址”。普通 C 函数的物理帧也不是异常自动帧；优化可以省略帧指针、内联函数或把末尾调用变为跳转。[S1 §2.3.7；S8]

本课把结论分为三类：**可判定**、**证据不足**、**输入无效**。这不是一个“是否溢出”的万能布尔值。例如 SP 越界可能是栈耗尽，也可能是错栈、错误链接符号或寄存器损坏；拒绝用它计算正常剩余量，不等于已经找到了根因。

### 2.2 先看一遍能够观察的流程

```text
同一构建的栈保留区间 [low, high)
        + 说明采样时刻和所属栈的 SP
        -> 先核对身份、范围与序列
        -> 才计算本次占用、剩余距离、最低已观测 SP
        -> 保存“当前证据能支持什么”
        -> 如需调用链，再与 PC（Program Counter，程序计数器）/LR（Link Register，链接寄存器）、异常帧、ELF（Executable and Linkable Format，可执行与可链接格式）/反汇编互证
```

主机最小例只注入三个数字地址，不访问这些地址处的内存。预期看到占用从 0 到 128 再到 64，而“已观测峰值”仍为 128。这先证明算法会保留历史，不证明真实 MCU 的峰值就是 128。

## 3. 必要前置知识

以下主题已在 `completed` 中出现，但“已授课”不等于“已掌握”。不熟悉时先回看对应课程：

| 前置主题 | 本课只唤回的用途 |
| --- | --- |
| pointer、storage-duration | 地址值不是可安全解引用的许可；诊断历史必须比单次采样活得更久 |
| compiler、linker-script、elf-map | 区间由实际链接安排决定；地址解释需要这次构建，而非另一个同名 ELF |
| stack-heap、memory-layout | 不把所有 RAM 都当作主栈，也不把堆和静态对象当成可用栈 |
| vector-table、startup | 初始 MSP（Main Stack Pointer，主栈指针）来自启动映射下的向量表首项；随后启动代码与 `main` 会继续消耗栈 |
| interrupt-priority、fault-analysis | 异常会建立有限现场；异常可嵌套，入栈失败时不能无条件信任帧 |
| clock-tree、register-view、breakpoint-watchpoint | 样本必须附带时钟、复位与暂停条件；读取动作也会扰动现场 |

没有“必须先会 RTOS”的隐藏要求。本课使用裸机、特权 Thread（线程）模式、MSP 的受控采样，不配置 PSP（Process Stack Pointer，进程栈指针）任务切换。

## 4. 核心原理

### 4.1 核心概念一：栈边界与动态使用量的证据边界

#### 4.1.1 先消除“栈顶/栈底”的语言歧义

本文不用“栈顶”代指固定的某个端点，而统一使用：

- `low`：为这个栈保留的最低地址。
- `high`：保留区的高地址开区间端点，也是本实验的初始空栈 SP。
- `sp`：**指定时刻**的活动栈指针。

Cortex-M4 使用满递减栈：压栈朝较低地址发展。普通编译代码怎样安排局部变量与保存寄存器，仍取决于编译器与构建；不能由 C 源码中的局部变量顺序推断。[S1 §2.1.2；S8]

```text
高地址  high ───────── 初始空 SP，不能把 high 当成可读栈字
                  已分配/曾保存的区域（具体内容需另证）
        sp   ───────── 本次样本边界
                  向下继续分配的地址距离
低地址  low  ───────── 保留区下界
```

只有确认 `low <= sp <= high`、所属栈一致、构建一致、样本有效后，才计算：

```text
本次从初始 high 向下占用的地址跨度 = high - sp
本次距下界的地址距离              = sp - low
已采样点中的最大占用跨度          = high - min(有效样本的 sp)
```

这些是**地址跨度**，不是逐字节“正在存活的 C 对象大小”，也不是保证下一条指令能安全调用多少层。`sp == low` 数学上可计算出剩余 0；这不是安全结论。`sp == high` 对空栈指针可接受，但读取 `*(uint32_t *)high` 仍越出区间。

例子（只是假地址，不是推荐 STM32 链接布局）：

| 时刻 | SP | 本次跨度 | 距下界 | 已观测最大跨度 |
| --- | --- | ---: | ---: | ---: |
| 1 | 0x20001400 | 0 | 1024 | 0 |
| 2 | 0x20001380 | 128 | 896 | 128 |
| 3 | 0x200013C0 | 64 | 960 | 128 |

最后一次 SP 上升，历史最小 SP 不能跟着上升。本课历史绑定 `{low, high, stack_id, build_tag}`；链接边界、所属栈或固件改变后，必须由调用者明确新建/清零历史，不能暗中把两组实验拼接。

#### 4.1.2 五种量不能互相冒充

| 证据 | 直接支持 | 不能直接支持 |
| --- | --- | --- |
| 链接保留区、向量首项 | 本构建计划把栈放在哪里、初始 MSP 取何值 | 运行峰值、已执行路径是否安全 |
| 某次有效 SP | 该栈在该时刻的占用跨度 | 过去/未来最低 SP，完整函数链 |
| 多次最低已观测 SP | **采样覆盖到的**最大跨度 | 两次采样间的瞬时峰值、未执行路径 |
| 填充图案扫描 | 扫描时哪些字节与原图案不同 | 没改变图案的区域从未被分配、真实最坏峰值 |
| 静态分析/压力实验与前述证据联合 | 在明确假设下扩大置信范围 | 不说明假设就宣称对所有输入、嵌套与库路径完成证明 |

例如，函数把 SP 减小 64 字节，却只向其中 8 字节写值，填充扫描可能看不到其余 56 字节的分配；若写入值恰好等于填充图案，也会漏计。扫描与 SP 采样测的是不同现象。最坏情况还取决于调用路径、编译优化、库函数、中断嵌套和受支持的浮点异常上下文，不能用一个观测量替代全部。[S1 §2.3.7；S8；本课模型反例]

#### 4.1.3 对象、所有权与调用流

| 对象 | 定义在哪里 | 谁持有 | 谁注入 | 调用如何流动 |
| --- | --- | --- | --- | --- |
| `StackBounds` | `host/stack_evidence.h`；目标值来自链接符号 | Host 测试夹具；目标模块的静态 `bounds` | 测试或 `StackProbe_Init` | 边界先到位，再允许观察 |
| `StackSample` | 同一头文件 | 一次调用的局部对象 | Fake 序列或汇编快照的适配代码 | `sample -> Observe`，不从地址读取内存 |
| `StackHistory` | 同一头文件 | 测试夹具或目标模块，跨采样保留 | 初始化时显式置零 | 所有核验通过后才更新最低 SP |
| `StackReport` | 同一头文件 | 调用者 | `Observe` 写入 | 先检查 status/has_numbers，再显示数值 |

`build_tag` 是调用者提供的 32 位索引，**不是唯一性证明或完整固件哈希**。实验记录必须把它映射到完整 ELF 哈希、构建选项与目标身份；发生冲突时这组历史不应继续合并。

### 4.2 核心概念二：调用现场重建的证据边界

#### 4.2.1 先问“哪个时刻、哪一种 LR”

SP（Stack Pointer，栈指针）不是调用链。PC（Program Counter，程序计数器）说明执行位置；LR（Link Register，链接寄存器）保存与返回有关的信息。普通 `BL`（Branch with Link，带链接的分支）调用会写 LR，而异常入口把 **EXC_RETURN（异常返回编码）**写入异常处理函数的 LR。异常帧里另有一个保存的 LR，它属于被打断的上下文。这三者不能混用。[S1 §2.1.3、§2.3.7]

| 来源 | 本课采用的准确称呼 | 使用限制 |
| --- | --- | --- |
| 调试器暂停读出的 PC/LR | 暂停现场的 PC/LR | 与暂停时刻的 SP 配对；工具显示细节按实际工具核对 |
| 本课汇编保存的 `pc_anchor` | 采样代码内的定位锚点 | 不是任意指令处暂停所得的完整 PC 快照 |
| 汇编入口的 `return_lr` | 返回 `StackProbe_Capture` 的信息 | 不是异常入口 EXC_RETURN，也不是业务函数完整调用链 |
| 原始异常入口 LR | EXC_RETURN | 必须在 C handler 覆盖/保存 LR 之前取得 |
| 有效基本异常帧中的 LR/PC | 被打断上下文的有限现场 | 不自动揭示更老的软件函数帧；PC 的故障语义回到 L035 分析 |

#### 4.2.2 MSP/PSP 的选择必须带上下文

MSP（Main Stack Pointer，主栈指针）和 PSP（Process Stack Pointer，进程栈指针）是两个 SP。复位后的 Thread 模式默认使用 MSP；Thread 模式可由 `CONTROL.SPSEL` 选择 PSP；Handler（异常处理）模式使用 MSP。`IPSR`（中断程序状态寄存器）为 0 表示 Thread，否则表示当前异常号。[S1 §2.1.2、§2.1.3]

```text
“此刻活动栈”：
    IPSR != 0                 -> MSP
    IPSR == 0 && CONTROL[1]=0 -> MSP
    IPSR == 0 && CONTROL[1]=1 -> PSP

“被异常打断时使用的帧”：
    由原始异常入口 EXC_RETURN 选择，而非由此刻 handler 的活动 MSP 猜测。
```

两者并不矛盾：Thread 用 PSP 时，异常自动保存 Thread 现场到 PSP，随后 handler 使用 MSP；更高优先级异常打断 handler 又会涉及 MSP。不能把 PSP 的帧和 MSP 的边界拿来相减，也不能把已经进入多层 C handler 后的 MSP 当作最早异常入口 SP。[S1 §2.3.7]

#### 4.2.3 只解析已经复制、来源明确的基本帧

Cortex-M4 的非浮点基本帧为 8 个 32 位字；在原始入口 SP 指向的基本帧内依次是 R0、R1、R2、R3、R12、保存的 LR、保存的 PC、xPSR（组合程序状态寄存器）。帧对齐还可能增加一个字，必须结合 CCR（配置与控制寄存器）的 `STKALIGN` 位与保存的 xPSR[9] 判断。完整依据见 PM0214 Figure 12、Table 18。[S1 §2.3.7、§4.4.7]

本课 `StackEvidence_BasicFrame` 的输入是**已经合法复制的定长数组**，不是一个让函数去盲读的裸 SRAM 地址。它只接受 `0xFFFFFFF1/F9/FD` 三种基本帧返回编码；对 `0xFFFFFFE1/E9/ED` 浮点扩展编码返回“证据不足”，本课不解释扩展帧布局或懒保存。其他编码、Thumb 状态不符、长度不够等返回“输入无效”。

还检查：

1. entry SP 的区间、构建与栈身份；确认这里的 SP 是入口 SP，不是后来 handler 的 SP。
2. CFSR（可配置故障状态寄存器）中的入栈、出栈、浮点懒保存错误；出现这些错误就不输出可信帧。
3. 用 `high - sp >= 所需字节` 核验，不先计算可能回绕的 `sp + 字节`；若 xPSR[9] 表示对齐填充，基本帧入口必须满足 8 字节对齐。
4. 返回 Handler/Thread 的编码与保存 xPSR 中的异常号是否自洽，并拒绝架构保留号；具体芯片是否实现某个外部 IRQ 仍须另查。
5. PC 是否满足本实验选定的同构建代码区间策略。合法的 RAM 执行代码若未纳入区间，会被本模型保守拒绝；这不证明硬件帧本身有错。

`has_frame=1` 只表示输入满足这些**必要条件**，不证明数组来自真实异常、不证明每个保存字未损坏，也不构成完整根因/调用链验证。SRAM 内的错误数据也可能凑巧满足所有检查。[S1 §2.3.7、§2.4、CFSR；本课支持范围]

#### 4.2.4 软件帧必须用同一构建解释

普通函数保存了哪些寄存器、局部区多大、有没有帧指针，要看实际反汇编、ABI（应用二进制接口）与展开信息，而不是套用异常帧的八字布局。

- **内联**：函数代码融入调用者，不一定存在独立物理帧。
- **尾调用/同级调用优化**：末尾调用可能变成跳转，不保留普通 `BL` 链式现场。
- **省略帧指针**：没有某个固定寄存器串起来的简单链；即使指定 `-fno-omit-frame-pointer`，也不能据此保证所有函数都有这种帧。
- **寄存器/栈损坏**：展开器可能停止，也可能输出貌似合理的错误结果。
- **调试信息不匹配**：相同地址用另一个 ELF 解释，可能得到完全不同的函数与行号。[S8]

ELF（Executable and Linkable Format，可执行与可链接格式）保存构建产物；DWARF（调试信息格式）帮助调试器关联源代码与机器状态；unwind（栈展开）是根据寄存器、栈内容及构建信息恢复调用者现场的过程。`.debug_*` 与 `.ARM.exidx` 等信息承担的职责并不相同，不能假定 `-g` 自动保证某一种展开表或目标工具总能完整回溯。**本次未核对实际 GNU Arm 编译器/GDB 的版本及展开算法，目标工具特定结论待核对。**本课只给出待执行的产物与工具检查路径，不制造展开保证。[S8、S9；S11 的访问边界]

该机制的对象关系：原始快照由采样模块持有；帧副本由合法采集方提供；ELF、链接脚本、反汇编和选项由构建方保存；分析者负责注入**匹配的构建身份**；解释流是 `原始证据 -> 有效性检查 -> 地址/指令对应 -> 带条件的判断`，不是“扫描出地址 -> 宣布调用链”。

## 5. 关键术语与直观模型

这些都是两个核心概念的辅助词汇，不是新增独立课题：

| 术语 | 本课中的准确含义 |
| --- | --- |
| 满递减栈（full descending stack） | 栈向低地址增长；不能因此推断所有 C 帧布局 |
| 栈边界 | 本构建明确保留给指定栈的区间，不是 RAM 总边界 |
| 最低已观测 SP | 有效采样集合中的最小值，非所有执行时刻的最小值 |
| 栈高水位（stack high-water mark） | 常用于指代峰值相关指标；本文每次明确是“采样峰值”还是“填充扫描改写范围” |
| EXC_RETURN | 异常入口 LR 中的返回编码，不是普通 Flash 返回地址 |
| map file（链接映射文件） | 链接安排的交叉检查材料；不测运行峰值，下一课再深入 |
| Host Fake | 在主机注入可控数据验证逻辑，不把主机调用帧当作 Cortex-M 的帧 |
| `NOLOAD` | 链接段的属性，不等于 CPU 运行时会保护它或启动代码绝不写它；实际 ld 版本与脚本语义须核对 [S10] |

## 6. 从输入到结果的完整流程

### 6.1 每条证据都走同一条判断链

1. **标定身份**：记录目标/复位会话、完整固件哈希、构建选项；将模块的 `build_tag` 对应到这份记录。
2. **建立边界**：从实际链接脚本、ELF 符号、Map、向量首项互证主栈区间，不从芯片总 RAM 猜区间。
3. **标定采样边界**：注明是调试器暂停、汇编采样入口还是原始异常入口；这些时刻不能互换。
4. **确定所属栈**：当前执行依据 IPSR/CONTROL，异常帧依据原始 EXC_RETURN。
5. **验证再算**：先检查范围与序列；拒绝输入时不更新历史，不沿用上一次“有效数值”。
6. **需要帧才核验帧**：入口可信、无对应堆栈错误、支持的帧格式、足够长度、状态自洽；越界地址不解引用。
7. **需要调用链才做展开**：关联同构建指令/调试信息，保留不确定性；裸内存候选仅是候选。
8. **写下一项反证实验**：增加一个未覆盖调用点、换优化等级、引入受控异常嵌套，或用 ELF/Map 纠正边界。

### 6.2 模块接口的三类输出

| 输出 | 典型输入 | 调用者应该做什么 |
| --- | --- | --- |
| `STACK_OK` | 区间、身份、序列和 SP 满足支持条件 | 看 `has_numbers/has_frame`，只陈述本模型支持的量 |
| `STACK_INSUFFICIENT` | 错栈/错构建、上下文未知、历史边界改变、旧序列、未支持的扩展帧 | 保留原始证据，补身份/上下文或换正确解析器，不假填数值 |
| `STACK_INVALID` | 上下界倒置、SP 越界/未对齐、帧截断、非法编码 | 拒绝正常计算；排查输入与现场，不把状态码直接当根因 |

输入结构和输出结构不得互相重叠；每个非空指针必须指向本调用期间有效的真实对象。C 函数不能替调用者证明这些基础内存契约。

## 7. 嵌入式系统中的对应位置

### 7.1 栈诊断能力地图

| 层级 | 解决什么问题、数据/控制链路 | 本课与后续落点 |
| --- | --- | --- |
| 基础 | 链接保留区 + 复位初始 MSP + 有效 SP -> 本次占用跨度与边界判断 | 本课深入；下一主题 `map-file` 交叉确认链接产物 |
| 进阶 | IPSR/CONTROL/EXC_RETURN 选择上下文；异常自动帧与软件压栈分层；采样历史保持最低观测 SP | 本课深入证据条件；异常细节沿用 L035，不重写 fault 课程 |
| 高级：优化与展开 | PC/LR + 同构建 ELF/DWARF + 指令语义 -> 有条件恢复调用者；内联/尾调用可能没有相应物理帧 | 本课用反例建立边界；在 `map-file`、`host-test` 中固定构建对照，不实现通用展开器 |
| 高级：填充、静态报告与防护 | 启动前受控填充 -> 执行路径 -> 停止后扫描；`.su` 函数级报告 -> 调用路径组合；MPU/栈限制 -> 访问/栈操作越界拦截，各测不同风险 | 本课给保守实验门槛；`rtos-concurrency/task、memory` 研究任务栈，`performance-power-reliability/mpu、fault-containment` 实做防护 |
| 跨外设联动 | 外设事件 -> IRQ（中断请求）-> HAL（Hardware Abstraction Layer，硬件抽象层）中断处理函数 -> 回调 -> 应用代码，嵌套会叠加主栈；DMA（直接存储器访问）完成事件可触发 IRQ，但搬运的数据缓冲区不是栈消耗量本身 | 这里只定义未来观测方案；到 `rtos-concurrency/isr` 比较 ISR 与任务栈，不为本课强加外设或猜回调 |
| 系列差异 | F4 的 M4F 基线 -> F7/H7 的 M7 内存/缓存观察 -> H5 的 M33 安全域与栈限制；不同芯片/内核必须换资料与采样器 | 见下表；核心依据分别为 [S1、S5、S6、S7] |

上表的高级能力不是“多几个名称”。例如栈保护解决的是**及早发现某类越界**，与事后读最低 SP 不同；必须把访问/异常信号、保护边界、handler 及记录路径连起来实验。本课不在缺少相应前置和资料配置时把这些能力硬塞进采样模块。

**迁移清单：通用的是证据方法，不是地址与汇编。**

| 参考系列 | 机制如何深化 | 必须重查/修改 | 后续可验证实验 |
| --- | --- | --- | --- |
| STM32F407xx / Cortex-M4F | 本课特权 Thread/MSP 的受控快照；浮点扩展帧主动拒绝 | 具体订货料号的 SRAM、CCM（内核耦合存储器）、启动/链接符号；不能把不连续 RAM 拼成一个栈区间 [S2、S3] | 对照向量首项、链接边界、两次快照 |
| STM32F7 / Cortex-M7 | MSP/PSP 的证据纪律仍可迁移；加入缓存、TCM（紧耦合存储器）与总线观察条件 | 具体 F7 的内存映射、缓存状态、调试可见性、工具与核心包；不能保证调试探针读到缓存中最新数据 [S5 的 memory/cache 章节] | `cache` 课比较内核读值与调试器读值，保留缓存状态；本课无测量结论 |
| STM32H5 / Cortex-M33 | 安全扩展涉及 Secure/Non-secure（安全/非安全）栈与异常上下文；栈限制寄存器扩大可观测/防护边界 | 当前安全状态、MSP/PSP 的安全域、MSPLIM/PSPLIM 支持和配置、目标 H5 手册与 CubeH5 头文件；不能只移植八字段汇编 [S6 的 stack、security extension、exception 章节] | `task/memory` 与 `fault-containment` 课在明确安全配置下比较不同栈/限制故障 |
| STM32H7，以 RM0433 覆盖的 H743 为对照 | 多总线/电源域、AXI SRAM 与 TCM 让“栈在哪里、何时可观察”变得更关键 | H743 的实际 SRAM 域、复位/供电、缓存及探针访问；RM0433 **不代表全部 H7，更不能证明双核型号的同步行为** [S5、S7] | `cache/mpu/low-power` 课比较不同 RAM 中的快照及复位后可见性；双核另选对应手册 |

### 7.2 参考目标与完整时钟/复位链

#### 7.2.1 资料与器件边界

参考器件为 **STM32F407xx / Cortex-M4F**，不选定开发板、完整订货料号、外部晶振、引脚或探针接线。架构依据 PM0214 Rev 10（2020-03）；器件集成依据 RM0090 Rev 22（2026-05）与 DS8626 Rev 12（2026-03）；HAL/LL 层级依据 UM1725 Rev 8（2023-03）。均已按本次可获取的文档封面核对，**不是声称它们永远为最新版**。

计划沿用 STM32CubeF4 **v1.28.3 作为拟复现包边界**。本次没有安装/解包该包，也没有从产品静态页取得这一补丁版本的发布记录，因此未核验其准确发布信息、CMSIS 子版本和实际启动模板。产品页 [S4] 仅支持包的定位；`v1.28.3` 不被伪装成已下载核对的包版本。目标开工前应核对实际包内 `Release_Notes.html`/包清单、CMSIS 头文件及启动文件，再决定是否继续使用该版本，并把结果写入目标实验记录。代码所依赖的内核寄存器行为由 [S1] 约束，不靠猜包补丁差异。

#### 7.2.2 时钟路径不是“给栈开一个外设时钟”

```text
AHB（高级高性能总线）、APB（高级外设总线）；HCLK 是本例的 AHB/内核标称时钟。

HSI（内部高速振荡源）或 HSE（外部高速时钟源，板级待填）
  ├─ 可直接选 SYSCLK（系统时钟）
  └─ 可进入主 PLL（锁相环）
         f_PLL_input = f_source / PLLM
         f_VCO       = f_PLL_input * PLLN
         f_PLL_SYS   = f_VCO / PLLP
                ↓ RCC_CFGR.SW 选择、SWS 反馈实际来源
             SYSCLK
                ↓ AHB 预分频 HPRE
             HCLK -> Cortex-M4 运行与相关 AHB/SRAM 访问路径
                ├─ APB1 预分频 PPRE1 -> PCLK1（本课无独立 APB1 外设）
                └─ APB2 预分频 PPRE2 -> PCLK2（本课无独立 APB2 外设）
```

上述为 F407 路径与字段，依据 RM0090 Rev 22 **第 7 章**针对 F405/407/415/417 的 RCC（复位与时钟控制）章节（p.214 起）；PLL 公式见 §7.3.2，SW/SWS、HPRE/PPRE 见 §7.3.3。第 6 章对应 F42/F43，不可替代本课 F407 的器件依据。[S2 §7]

- 若实际选择 PLL，必须从实际板级时钟频率和 PLLM/N/P 推出 SYSCLK，再由 HPRE 推出 HCLK；同时检查允许频率、电源条件和 Flash 等待周期。这里不填写假想晶振和运行频率。
- 最终工作频率应在实验单记录为 `HCLK = 实际 SYSCLK / HPRE`；`SystemCoreClock` 是软件维护的标称元数据，不是频率测量。示例保存 RCC 的 CR/PLLCFGR/CFGR 原始值辅助核对。
- **本课没有栈外设的内核时钟、预分频器、RCC 外设门控/复位位或 HAL 栈句柄。**不能为凑表格发明它们。SRAM 可访问条件按器件 RCC/存储器章节核对；本例不改动已启动系统的 SRAM 时钟策略。[S2 §2、§7]
- 示例由同步软件调用触发，不定义采样周期，也不利用定时器。若以后使用定时 IRQ 采样，必须另列该定时器的实际内核时钟与倍频条件、门控/复位、PSC/ARR，以及 `T=(PSC+1)(ARR+1)/f_TIM`，本课不拿 APB 时钟直接猜 `f_TIM`。
- HCLK 不进入本课的字节差值公式；它会影响函数执行时间、异步事件介入机会以及“多久采到一次”。本课没有时序测量，不能由两个 SP 样本反推执行时间。

#### 7.2.3 复位与启动链

```text
上电/引脚/软件/看门狗等实际复位来源
 -> 复位时钟及存储器启动映射（核对 BOOT 配置，不猜板级跳线）
 -> 向量表首字载入初始 MSP，复位向量确定入口
 -> 所选 startup / Reset_Handler
 -> SystemInit、数据段初始化、C 运行时初始化（实际顺序查启动文件）
 -> main
 -> HAL_Init
 -> CubeMX 生成并按真实板卡填写的 SystemClock_Config
 -> StackProbe_Init -> StackDemo_RunOnce
```

初始 MSP 的架构取值位置是启动映射下 `0x00000000` 的首字；后续 `VTOR`（向量表偏移寄存器）可能重定位向量表，不能把暂停时 VTOR 无条件当作复位最初映射。改变时钟、调试复位策略或重新加载程序，都会使采样属于不同时间段。本课快照只在 RAM 中，不跨复位保留，`RCC_CSR` 原始值读取不主动清复位标志；实际复位来源仍需结合工具操作记录判定。[S1 §2.1.3；S2 §2、§6]

### 7.3 CubeMX、HAL、CMSIS、LL 与寄存器对照

CMSIS（Cortex 微控制器软件接口标准）提供内核访问接口；LL（低层驱动）与 HAL（硬件抽象层）主要组织芯片外设访问。本课处理器栈寄存器属于 CMSIS/CPU 层，不是某个外设驱动。[S1 的 CMSIS 说明；S4、S12]

**CubeMX/CubeMX2 配置清单（配置意图，未实际生成工程）：**

| 项目 | 本课明确的设置/约束 | 目标开工前的必填内容 |
| --- | --- | --- |
| MCU Selector（器件选择） | 限定 STM32F407xx，不默认某块板 | 实际完整订货料号、封装、Flash/RAM 容量 |
| SYS/Debug | 选择 SWD（串行线调试）作为工程意图 | 板级连接、探针、供电/复位方式；本课不填引脚电路 |
| RCC/Clock Configuration | 用实际 HSI/HSE 与 PLL/AHB/APB 配置生成工程 | 时钟源、频率、分频、电源条件、Flash 等待周期；保留工程配置文件 |
| Middleware/外设 | 不新增定时器、DMA、UART 或 RTOS | 若现有工程已启用外设，登记它们是否影响采样，不擅改全局配置 |
| Firmware Package | 拟沿用 CubeF4 v1.28.3，下载/版本核对待执行 | 实际包版本、HAL/CMSIS 版本、生成器版本和启动模板 |
| 链接与启动文件 | 使用真实目标生成的脚本/启动文件 | RAM 区域、向量首项符号、所有静态段、保留栈大小；用实验明确选值，不填通用“推荐栈大小” |
| 工具链 | 目标参考代码含 GNU Arm 汇编/属性与 GNU ld 片段 | GNU Arm 编译器、汇编器、链接器、GDB 版本；其他工具链必须重写对应适配 |

**HAL 系统初始化的最小调用顺序：**

```c
/* 放入实际 Cube 生成工程相应 USER CODE 区，不是可单独链接的工程。 */
#include "main.h"           /* 由该目标工程真实生成 */
#include "stack_probe.h"    /* 本课自有文件 */

#ifndef STUDY_FIRMWARE_TAG
#error "Define a build tag and map it to the full ELF hash in the experiment record"
#endif

volatile uint32_t g_stack_demo_status;

/* main 内：保留生成器的其他必要初始化，不复制一个假的 SystemClock_Config。 */
/*
if (HAL_Init() != HAL_OK) {
    Error_Handler();
}
SystemClock_Config();
SystemCoreClockUpdate();
g_stack_demo_status = StackProbe_Init((uint32_t)STUDY_FIRMWARE_TAG);
if (g_stack_demo_status == STACK_OK) {
    g_stack_demo_status = StackDemo_RunOnce();
}
*/
```

这段是**集成位置说明**，不是注释掉代码后就有完整 `main`。实际工程必须保留生成的 `main`、`SystemClock_Config`、时基和 `Error_Handler`；只有第 9 节的本课模块作为新增编译单元。`HAL_Init`/HAL 的默认时基路径属于系统初始化；`SystemClock_Config` 是生成应用函数，不是 HAL 驱动内部栈接口。时钟配置失败应走生成工程的错误路径，不继续把未建立的频率标称写成实验条件。[S12 的 HAL configuration、HAL generic driver 与 RCC 章节]

| 配置对象/字段 | 所有者、生命周期 | 与本课有关的语义 |
| --- | --- | --- |
| `RCC_OscInitTypeDef`：`OscillatorType`、HSI/HSE 状态、`PLL.PLLState/PLLSource/PLLM/PLLN/PLLP/PLLQ` | 通常为生成的 `SystemClock_Config` 局部配置对象；不由采样模块持有 | 描述振荡源与 PLL；按真实器件/包头文件逐项复核，不为栈采样重新初始化 PLL |
| `RCC_ClkInitTypeDef`：`ClockType/SYSCLKSource/AHBCLKDivider/APB1CLKDivider/APB2CLKDivider` | 同上；配置调用后对象本身不再是硬件状态 | 选择系统/总线来源和分频，需结合 SWS/HPRE/PPRE 读回核对 |
| HAL 外设句柄 | **不适用** | 无独立外设，故无 `HAL_*_HandleTypeDef`、DMA 句柄所有权或 `HAL_*_...Callback` |
| `g_stack_probe`、`history`、`bounds` | 本课模块静态持有，从初始化到复位；main 单一写入路径 | 是诊断对象，不冒充 HAL 句柄 |

上表字段名的最终边界是所选 Cube 包头文件；本次没有编译该包，不能声称逐字段已经在 v1.28.3 验证。HAL 初始化顺序与层级由 [S12] 支持，具体包/生成器差异仍是目标开工门禁。

**HAL → CMSIS/LL/关键寄存器对照：**

| 操作意图 | 实际层与入口 | 关键字段/行为 | 明确不做什么 |
| --- | --- | --- | --- |
| 建立系统基础 | `HAL_Init`，生成工程时基 | HAL 基础初始化与时基；可能引入 SysTick（系统滴答）异常 | 不宣称它预留/保护了本课栈区 |
| 建立系统时钟 | 生成的 `SystemClock_Config` 调用 RCC HAL | RCC_CR、RCC_PLLCFGR、RCC_CFGR 的来源/分频状态 [S2、S12] | 不用 `SystemCoreClock` 代替硬件状态或频率测量 |
| 读两种 SP | CMSIS `__get_MSP`/`__get_PSP` 的意图；本课汇编 `MRS` | 处理器 MSP/PSP；不是内存映射外设寄存器 [S1] | 不发明 LL/HAL 栈采样 API |
| 判活动栈/模式 | `__get_CONTROL`、`__get_IPSR`；汇编保存同名寄存器 | CONTROL.SPSEL/nPRIV、IPSR 异常号 [S1] | 不拿当前 handler MSP 充当 Thread 的入口帧地址 |
| 有限屏蔽可配置异常 | 保存 PRIMASK、`cpsid i`、恢复 PRIMASK | 缩小普通 IRQ 对采样序列的扰动，但 NMI/HardFault 不因此被屏蔽 [S1] | 不声称得到原子全系统快照；不调用 HAL 来改 SP |
| 查看异常帧 | 原始入口 EXC_RETURN + 支持的帧副本 | 核心保存字、对齐、故障有效性 [S1] | 本课目标采样器不安装 fault handler，也不盲读 SP |
| 查看初始 MSP | 启动映射/向量首项 + `_estack` 等实际符号 | 启动和链接契约，不是 HAL 配置字段 [S1、S2] | 不把改一个 `_Min_Stack_Size` 数值当成保留区与运行保护全完成 |

**IRQ/DMA 回调：不适用，栈采样没有独立外设 HAL 回调。**保留生成工程已有的系统时基中断链即可；不要新增、替换或重复定义 `SysTick_Handler`。如果已有 IRQ 在两次采样间运行，它可能造成未被捕获的更低 MSP；本次 `observed_peak_bytes` 不覆盖那个未采样峰值。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道：先运行最小例

在仓库根目录用已安装的主机 GCC 执行，输出目录选 `.state/tmp/L036-stack-evidence`（临时且不进入课程发布）。这是主机编译器，不是 GNU Arm 编译器。

```powershell
New-Item -ItemType Directory -Force .state/tmp/L036-stack-evidence | Out-Null
$src = 'lessons/L036-stack-evidence/host'
$out = '.state/tmp/L036-stack-evidence'
gcc -std=c11 -Wall -Wextra -Werror -pedantic -O0 -g `
    "$src/stack_evidence.c" "$src/minimal.c" -o "$out/minimal.exe"
if ($LASTEXITCODE -ne 0) { throw 'minimal build failed' }
& "$out/minimal.exe"
if ($LASTEXITCODE -ne 0) { throw 'minimal run failed' }

foreach ($opt in @('O0', 'O2')) {
    gcc -std=c11 -Wall -Wextra -Werror -pedantic "-$opt" `
        "$src/stack_evidence.c" "$src/test_stack_evidence.c" -o "$out/test-$opt.exe"
    if ($LASTEXITCODE -ne 0) { throw "test build failed: $opt" }
    & "$out/test-$opt.exe"
    if ($LASTEXITCODE -ne 0) { throw "test run failed: $opt" }
}
```

最小例的确定性输出：

```text
used=0 remaining=1024 observed_peak=0
used=128 remaining=896 observed_peak=128
used=64 remaining=960 observed_peak=128
```

测试不使用 `-DNDEBUG`，否则 `assert`（断言）会被移除。完整用例文件是 `host/test_stack_evidence.c`，验证如下：

| 输入/反例 | 预期接受/拒绝及不变量 |
| --- | --- |
| 空栈、加深后回浅、恰在 low | 正确计算；历史最低值不回退；剩余 0 不改写为安全 |
| SP 在区间外/不对齐、空区间/倒置区间 | 输入无效，无无符号回绕，历史不变 |
| MSP/PSP 错配、构建不符、未知上下文 | 证据不足；不能继续显示旧数值为新结果 |
| 改边界继续用旧历史、重复或倒序 sequence | 拒绝混合证据；清零历史必须由调用方明确执行 |
| 破坏历史内部值、空指针 | 拒绝；输出指针为空时仅能返回状态 |
| 接近 UINT32_MAX 的数字区间 | 仍先验证后相减，不把主机真实地址塞进 32 位 MCU 地址模型 |
| 基本帧截断、aligner 需要第九字、错误状态/PC/EXC_RETURN | 拒绝解释；浮点扩展帧报“不支持”，不误读基本帧 |
| MSP/PSP 基本帧与 Handler 返回帧 | 支持条件下接受，但只表示必要条件通过 |

**本次主机证据（2026-10-20）：**主机 GCC 16.2.0，`-std=c11 -Wall -Wextra -Werror -pedantic`；最小例输出如上，完整测试在 `-O0` 与 `-O2` 下各通过 149 项断言。可复核命令、输出、退出码及源文件哈希见仓库运行记录 `.state/runs/20261020-203304522-42772/teacher-validation.log`，复现脚本为同目录 `teacher-check.py`。该记录不是硬件验证证据。

主机运行只证明这份数据模型的判断逻辑；不证明 ARM ABI、真实异常帧、实际链接范围、汇编代码、总线可读性或目标最坏峰值。

### 8.2 STM32 参考实现轨道：可操作但未执行

#### 8.2.1 先建立真实保留区，不猜一个栈大小

本课新增的文件都是自写教学代码，不包含完整厂商驱动、启动文件或完整第三方工程：

```text
host/stack_evidence.h, stack_evidence.c   可迁移判断模块
host/minimal.c, test_stack_evidence.c    只编译进主机程序
stm32/stack_probe.h, stack_probe.c       目标快照与生命周期
stm32/stack_probe_entry.S                无压栈的 GNU Arm 采样入口
stm32/stack_demo.c                       有限深度实验调用链
stm32/stack_reservation.ld.inc           需合并的 GNU ld 片段，不是完整链接脚本
```

实际目标工程只加入 `stack_evidence.c`、`stack_probe.c`、`stack_demo.c`、`.S`；include 路径加入本课 `host` 与 `stm32`。**不要把两个主机 `main` 文件一起编进目标**。

链接步骤：

1. 选真实 MCU 的生成脚本，核对 `MEMORY` 的 `RAM` 是否为预定连续可用主 SRAM，而非 CCM、别的内存域或拼接区。
2. 找实际向量首项符号、RAM 静态段、启动清零范围、堆/栈保留段。符号名 `_estack`、`_ebss` 是本片段的**集成契约**；若实际工程不同，必须同步改片段和对应检查，不创建一个同名但无真实约束的假符号。
3. 本课只给该工程增加一个专属保留段。将片段合入实际 `SECTIONS`，替代生成脚本原有的堆/栈占位段方案，避免双重保留。**本任务没有执行上述工程修改。**
4. 由目标工程显式提供 `STUDY_STACK_BYTES`（链接符号），根据构建/已知调用路径和异常预算选实验值；这里不写一个能误当通用建议的数字。保留 `_estack` 与专属段高端一致，并核对向量首项实际引用它。
5. 明确本实验无动态分配；若生成工程/库仍使用堆，必须为它保留独立且不重叠的真实区间。不能因为本课没调用 `malloc` 就把未知库的堆需求忽略。
6. 看实际链接错误、Map、段列表和 ELF 符号，确认所有 RAM 段与栈不重叠。`NOLOAD` 仅是段属性；检查启动代码究竟清哪些范围。片段本身不提供运行时越界保护。[S10]

若实际生成脚本只有 `_Min_Stack_Size` 占位检查，应核对它是否确实排除了其他段对主栈区的使用：本模块需要能命名的**实际区间**，不能只根据一个最小尺寸符号宣称整个高端区都已排除其他用途。后续 `map-file` 课会深入产物交叉确认。

#### 8.2.2 采样器的支持条件与时机

- 必须在有足够安全栈余量的**特权 Thread/MSP** 中调用，初始化在系统时钟建立之后。
- `StackProbe_Capture` 是 C 函数，有自己的编译器帧；它再调用不压栈的汇编入口。记录的是**汇编入口时**的 MSP，已经包括 wrapper 与调用链的用量，不是业务调用者进入 wrapper 之前的 SP。
- 汇编不使用额外栈，也不调用 C；仅临时使用 AAPCS（Arm 架构过程调用标准）允许调用者视为可破坏的 R1～R3，保存两种 SP、CONTROL、IPSR、原 PRIMASK、返回 LR、PC 锚点和活动 SP；不改写须由被调用者保留的寄存器。[S14 §4.4]PRIMASK 只在短窗口屏蔽可配置异常，恢复原值；不是永久关闭中断。[S1]
- 这不是原子的全寄存器快照。NMI/HardFault 仍可能打断，RCC 元数据在 C 侧稍后读取；这些异常路径不得调用此采样器或改快照对象。发生故障时回到 L035 的专用采集路径。
- 采样器不读 `*MSP`、不写栈填充图案、不改 MSP/PSP/CONTROL，不安装 HardFault，也不强迫 PSP 初始化。
- `Init`/`Capture` 的条件检查本身已经是 C 代码，可能消耗栈；它们**不是栈已溢出时的救命入口**。低余量系统不能期待“先进入诊断 C 函数再发现溢出”足够安全。

若需要业务函数“调用前”SP，用调试器在调用指令前暂停并独立保存那组现场。不要把其读数与本例汇编入口的读数当成同时发生。

#### 8.2.3 数据生命周期、错误路径与验证材料

`bounds/history/sequence` 由模块静态持有，`StackProbe_Init` 开始新一轮；`g_stack_probe_raw` 只为汇编与 C 交换本次数据；`g_stack_probe` 保存发布的快照，main 是唯一写者。状态为 `EMPTY -> WRITING -> COMPLETE`；调试器在 Capture 返回之后观察。`volatile`（易变限定）和 DMB（数据存储屏障）不等于并发读者拿到了原子完整快照，也不解决其他系列的缓存一致性。[S1 的 DMB；S5]

- `Init` 拒绝非法区间/模式时返回 `STACK_INVALID`，禁用后续采样。
- Capture 前置条件不符或序列耗尽时返回 `STACK_INSUFFICIENT`，**不产生新快照**；此前 COMPLETE 数据仍是历史。必须同时检查本次返回值与 sequence，不把旧快照当新结果。
- 若已经采样但诊断拒绝输入，快照仍以 COMPLETE 发布原始值与拒绝原因，`has_numbers=0`。COMPLETE 只表示写入完成，不表示诊断有效。
- API 不接收外部 writer，不支持 ISR、RTOS 多任务并发调用或 fault 重入。

目标实验记录至少保留：完整订货料号、板卡/探针/复位方式、生成器与 Cube/HAL/CMSIS 版本、编译/链接选项、ELF 与完整 SHA-256、链接脚本、Map、反汇编、原始寄存器、快照、时钟链计算和操作顺序。缺少这些材料时不把“看到了个数”升级为目标验证结论。

## 9. 最小代码示例与完整参考模块

本节先给声明/算法/调用，再给目标适配。公共算法是 C11、公开整数字段为固定宽度、无动态内存；CMSIS 内联/目标汇编和 GNU 属性是明确的平台适配边界，不宣称 ISO C11 能读 CPU 栈寄存器。所有目标文件仍是“参考实现，待目标工程编译和上板验证”。

五个动作在这里有具体落点：**声明**在头文件；**实现**在算法与目标 `.c/.S`；**实例化**是 Host 的局部 history 与目标模块的静态对象；**组装**由目标工程提供真实链接符号、构建身份和生成初始化；**使用**是 main 调用初始化及一次实验。它们不是新的架构课，也不引入函数指针/依赖注入框架。

### 9.1 接口声明：调用者持有输入、历史和输出

**文件：`host/stack_evidence.h`。** 依赖仅为 `<stdint.h>`；字段中的地址是 MCU 数字模型，不是可解引用许可。历史须以 `{0}` 初始化。

```c
#ifndef STACK_EVIDENCE_H
#define STACK_EVIDENCE_H
#include <stdint.h>

#define STACK_OK UINT32_C(0)
#define STACK_INSUFFICIENT UINT32_C(1)
#define STACK_INVALID UINT32_C(2)
#define STACK_MSP UINT32_C(1)
#define STACK_PSP UINT32_C(2)
#define STACK_REASON_NONE UINT32_C(0)
#define STACK_REASON_ARGUMENT UINT32_C(1)
#define STACK_REASON_BOUNDS UINT32_C(2)
#define STACK_REASON_CONTEXT UINT32_C(3)
#define STACK_REASON_IDENTITY UINT32_C(4)
#define STACK_REASON_SP UINT32_C(5)
#define STACK_REASON_HISTORY UINT32_C(6)
#define STACK_REASON_FRAME UINT32_C(7)
#define STACK_REASON_UNSUPPORTED UINT32_C(8)
#define STACK_REASON_STACKING UINT32_C(9)

typedef struct {
    uint32_t low, high;       /* [low, high); high is a valid EMPTY SP only. */
    uint32_t stack_id, build_tag;
} StackBounds;
typedef struct {
    uint32_t sp, stack_id, build_tag, sequence, context_known;
} StackSample;
typedef struct {
    uint32_t initialized;
    StackBounds bounds;
    uint32_t min_sp, last_sequence;
} StackHistory;
typedef struct {
    uint32_t status, reason, has_numbers;
    uint32_t used_bytes, remaining_bytes, observed_peak_bytes;
} StackReport;
typedef struct {
    uint32_t exc_return, cfsr, text_low, text_high, word_count;
    uint32_t words[9];        /* Copied input; NEVER an arbitrary SRAM pointer. */
} StackBasicFrameInput;
typedef struct {
    uint32_t status, reason, has_frame;
    uint32_t resume_pc, saved_lr, xpsr, occupied_bytes;
} StackFrameReport;

uint32_t StackEvidence_Observe(const StackBounds *bounds,
    const StackSample *sample, StackHistory *history, StackReport *report);
uint32_t StackEvidence_BasicFrame(const StackBounds *bounds,
    const StackSample *entry, const StackBasicFrameInput *input,
    StackFrameReport *report);
#endif
```

### 9.2 算法实现：先验证，后做减法，最后提交历史

**文件：`host/stack_evidence.c`。** 无硬件依赖，不持有调用者对象。错误路径清空输出有效性且不更改历史；帧函数只操作已经复制的定长对象。支持基本帧的依据为 [S1]，它不是展开器。

```c
#include "stack_evidence.h"
#include <stddef.h>

static uint32_t fail(StackReport *r, uint32_t status, uint32_t reason)
{
    r->status = status;
    r->reason = reason;
    return status;
}

static uint32_t valid_bounds(const StackBounds *b)
{
    return b->low < b->high && ((b->low | b->high) & UINT32_C(3)) == 0U
        && (b->stack_id == STACK_MSP || b->stack_id == STACK_PSP);
}

static uint32_t same_bounds(const StackBounds *a, const StackBounds *b)
{
    return a->low == b->low && a->high == b->high
        && a->stack_id == b->stack_id && a->build_tag == b->build_tag;
}

uint32_t StackEvidence_Observe(const StackBounds *b, const StackSample *s,
    StackHistory *h, StackReport *r)
{
    uint32_t min_sp;
    if (r == NULL) { return STACK_INVALID; }
    *r = (StackReport){0};
    if (b == NULL || s == NULL || h == NULL) {
        return fail(r, STACK_INVALID, STACK_REASON_ARGUMENT);
    }
    if (!valid_bounds(b)) { return fail(r, STACK_INVALID, STACK_REASON_BOUNDS); }
    if (s->context_known != 1U) {
        return fail(r, STACK_INSUFFICIENT, STACK_REASON_CONTEXT);
    }
    if (s->stack_id != b->stack_id || s->build_tag != b->build_tag) {
        return fail(r, STACK_INSUFFICIENT, STACK_REASON_IDENTITY);
    }
    if (s->sp < b->low || s->sp > b->high || (s->sp & 3U) != 0U) {
        return fail(r, STACK_INVALID, STACK_REASON_SP);
    }
    if (s->sequence == 0U || h->initialized > 1U) {
        return fail(r, STACK_INVALID, STACK_REASON_HISTORY);
    }
    if (h->initialized == 1U) {
        if (!same_bounds(b, &h->bounds)) {
            return fail(r, STACK_INSUFFICIENT, STACK_REASON_HISTORY);
        }
        if (h->min_sp < b->low || h->min_sp > b->high
            || (h->min_sp & 3U) != 0U || h->last_sequence == 0U) {
            return fail(r, STACK_INVALID, STACK_REASON_HISTORY);
        }
        if (s->sequence <= h->last_sequence) {
            return fail(r, STACK_INSUFFICIENT, STACK_REASON_HISTORY);
        }
    }
    min_sp = h->initialized == 0U || s->sp < h->min_sp ? s->sp : h->min_sp;
    /* All validation precedes state changes and unsigned subtraction. */
    h->bounds = *b;
    h->min_sp = min_sp;
    h->last_sequence = s->sequence;
    h->initialized = 1U;
    r->status = STACK_OK;
    r->has_numbers = 1U;
    r->used_bytes = b->high - s->sp;
    r->remaining_bytes = s->sp - b->low;
    r->observed_peak_bytes = b->high - min_sp;
    return STACK_OK;
}

static uint32_t frame_fail(StackFrameReport *r, uint32_t status, uint32_t why)
{
    r->status = status;
    r->reason = why;
    return status;
}

static uint32_t handler_number_possible(uint32_t n)
{
    /* Cortex-M4 architecture-level filter, not a device IRQ availability test. */
    return (n >= 2U && n <= 6U) || n == 11U || n == 12U || n == 14U
        || n == 15U || (n >= 16U && n <= 255U);
}

uint32_t StackEvidence_BasicFrame(const StackBounds *b, const StackSample *s,
    const StackBasicFrameInput *f, StackFrameReport *r)
{
    StackHistory history = {0};
    StackReport report;
    uint32_t expected_stack, bytes, mode;
    if (r == NULL) { return STACK_INVALID; }
    *r = (StackFrameReport){0};
    if (f == NULL) { return frame_fail(r, STACK_INVALID, STACK_REASON_ARGUMENT); }
    if (StackEvidence_Observe(b, s, &history, &report) != STACK_OK) {
        return frame_fail(r, report.status, report.reason);
    }
    switch (f->exc_return) {
    case UINT32_C(0xFFFFFFF1):
    case UINT32_C(0xFFFFFFF9):
    case UINT32_C(0xFFFFFFFD): break;
    case UINT32_C(0xFFFFFFE1):
    case UINT32_C(0xFFFFFFE9):
    case UINT32_C(0xFFFFFFED):
        return frame_fail(r, STACK_INSUFFICIENT, STACK_REASON_UNSUPPORTED);
    default: return frame_fail(r, STACK_INVALID, STACK_REASON_FRAME);
    }
    expected_stack = (f->exc_return & 4U) != 0U ? STACK_PSP : STACK_MSP;
    if (s->stack_id != expected_stack) {
        return frame_fail(r, STACK_INSUFFICIENT, STACK_REASON_IDENTITY);
    }
    /* MMFSR[5:3] and BFSR[5:3]: unstack/stack/lazy-state errors. */
    if ((f->cfsr & UINT32_C(0x00003838)) != 0U) {
        return frame_fail(r, STACK_INSUFFICIENT, STACK_REASON_STACKING);
    }
    if (b->high - s->sp < 32U || f->word_count < 8U || f->word_count > 9U) {
        return frame_fail(r, STACK_INVALID, STACK_REASON_FRAME);
    }
    bytes = (f->words[7] & (UINT32_C(1) << 9)) != 0U ? 36U : 32U;
    mode = f->words[7] & UINT32_C(0x1FF);
    if (b->high - s->sp < bytes || f->word_count < bytes / 4U
        || (bytes == 36U && (s->sp & 7U) != 0U)
        || (f->words[7] & (UINT32_C(1) << 24)) == 0U
        || (f->exc_return == UINT32_C(0xFFFFFFF1) ? !handler_number_possible(mode) : mode != 0U)
        || f->text_low >= f->text_high
        || ((f->text_low | f->text_high) & 1U) != 0U
        || (f->words[6] & 1U) != 0U || f->words[6] < f->text_low
        || f->words[6] >= f->text_high) {
        return frame_fail(r, STACK_INVALID, STACK_REASON_FRAME);
    }
    r->status = STACK_OK;
    r->has_frame = 1U;
    r->resume_pc = f->words[6];
    r->saved_lr = f->words[5]; /* No claim that this is a normal call return. */
    r->xpsr = f->words[7];
    r->occupied_bytes = bytes;
    return STACK_OK;
}
```

### 9.3 最小使用：三个样本即可观察到峰值不回退

**文件：`host/minimal.c`。** 主机测试入口持有所有对象，生命周期覆盖三次同步调用；printf 仅属于主机，不进入目标采样路径。

```c
#include "stack_evidence.h"
#include <assert.h>
#include <inttypes.h>
#include <stdio.h>

int main(void)
{
    const StackBounds bounds = {0x20001000U, 0x20001400U, STACK_MSP, 7U};
    const uint32_t sequence[] = {0x20001400U, 0x20001380U, 0x200013C0U};
    StackHistory history = {0};
    StackReport report;
    uint32_t i;
    for (i = 0U; i < 3U; ++i) {
        const StackSample s = {sequence[i], STACK_MSP, 7U, i + 1U, 1U};
        assert(StackEvidence_Observe(&bounds, &s, &history, &report) == STACK_OK);
        printf("used=%" PRIu32 " remaining=%" PRIu32 " observed_peak=%" PRIu32 "\n",
            report.used_bytes, report.remaining_bytes, report.observed_peak_bytes);
    }
    return 0;
}
```

### 9.4 目标声明与静态快照契约

**文件：`stm32/stack_probe.h`。** 目标适配层依赖公共算法。App 只调用 API，不写全局快照；快照由模块持有至复位。

```c
#ifndef STUDY_STACK_PROBE_H
#define STUDY_STACK_PROBE_H
#include "stack_evidence.h"
#include <stdint.h>

#define STACK_PROBE_EMPTY UINT32_C(0)
#define STACK_PROBE_WRITING UINT32_C(1)
#define STACK_PROBE_COMPLETE UINT32_C(2)

typedef struct {
    uint32_t msp, psp, control, ipsr, primask, return_lr, pc_anchor, active_sp;
} StackProbeRaw;
typedef struct {
    uint32_t state, status, build_tag, sequence;
    uint32_t hclk_nominal_hz, rcc_cr, rcc_pllcfgr, rcc_cfgr, rcc_csr;
    StackBounds bounds;
    StackProbeRaw raw;
    StackReport report;
} StackProbeSnapshot;

/* One privileged Thread-mode producer; debugger reads only after completion. */
extern volatile StackProbeSnapshot g_stack_probe;
uint32_t StackProbe_Init(uint32_t build_tag);
uint32_t StackProbe_Capture(void);
uint32_t StackDemo_RunOnce(void);
#endif
```

### 9.5 汇编采样入口：不额外压栈，但不是调用前 SP

**文件：`stm32/stack_probe_entry.S`。** GNU Arm/Thumb 的平台代码，通过固定偏移写模块私有 raw 对象。没有 push/pop、不调用 C、不遍历栈；PC 是 label 锚点。PRIMASK/MSP/PSP/CONTROL/IPSR 语义见 [S1]；调用约定中 R0～R3 的暂存用途见 [S14 §4.4]，实际 GNU Arm ABI 选项仍须按目标工程确认。

```asm
/* Original teaching code. GNU assembler, Cortex-M4/Thumb only.
 * Not a fault/exception entry and not a universal register snapshot.
 */
.syntax unified
.cpu cortex-m4
.thumb
.text
.align 2
.global StackProbe_Entry
.type StackProbe_Entry, %function
.thumb_func
StackProbe_Entry:
    mrs r3, PRIMASK
    cpsid i
    ldr r2, =g_stack_probe_raw
.Lsample:
    mrs r1, MSP
    str r1, [r2, #0]
    mrs r1, PSP
    str r1, [r2, #4]
    mrs r1, CONTROL
    str r1, [r2, #8]
    mrs r1, IPSR
    str r1, [r2, #12]
    str r3, [r2, #16]
    str lr, [r2, #20]
    adr r1, .Lsample
    str r1, [r2, #24]
    mov r1, sp
    str r1, [r2, #28]
    dmb
    msr PRIMASK, r3
    bx lr
.size StackProbe_Entry, .-StackProbe_Entry
```

### 9.6 目标实现：真实链接区间到判断模块

**文件：`stm32/stack_probe.c`。** 模块拥有静态区间、历史与快照，main 注入 build_tag；链接器注入两个边界符号。字段偏移由静态断言约束。使用 CMSIS/器件头文件，等待选定 Cube 包逐项编译核对。

```c
/* Reference only: pending compilation in the selected STM32CubeF4 project. */
#include "stack_probe.h"
#include "stm32f4xx_hal.h"
#include <stddef.h>
#include <stdint.h>

extern uint8_t __study_stack_low__[];
extern uint8_t __study_stack_high__[];
extern void StackProbe_Entry(void);
/* Link-visible to assembly; not a public mutable application object. */
volatile StackProbeRaw g_stack_probe_raw;
volatile StackProbeSnapshot g_stack_probe;
static StackBounds bounds;
static StackHistory history;
static uint32_t initialized;
static uint32_t sequence;

_Static_assert(sizeof(uintptr_t) == 4U, "STM32F407 address width required");
_Static_assert(sizeof(StackProbeRaw) == 32U, "assembly layout mismatch");
_Static_assert(offsetof(StackProbeRaw, msp) == 0U, "msp offset");
_Static_assert(offsetof(StackProbeRaw, psp) == 4U, "psp offset");
_Static_assert(offsetof(StackProbeRaw, control) == 8U, "control offset");
_Static_assert(offsetof(StackProbeRaw, ipsr) == 12U, "ipsr offset");
_Static_assert(offsetof(StackProbeRaw, primask) == 16U, "primask offset");
_Static_assert(offsetof(StackProbeRaw, return_lr) == 20U, "lr offset");
_Static_assert(offsetof(StackProbeRaw, pc_anchor) == 24U, "pc offset");
_Static_assert(offsetof(StackProbeRaw, active_sp) == 28U, "sp offset");

uint32_t StackProbe_Init(uint32_t build_tag)
{
    uint32_t low = (uint32_t)(uintptr_t)__study_stack_low__;
    uint32_t high = (uint32_t)(uintptr_t)__study_stack_high__;
    /* Policy: this module deliberately supports privileged Thread/MSP only. */
    if (__get_IPSR() != 0U || (__get_CONTROL() & 3U) != 0U
        || low >= high || ((low | high) & 7U) != 0U) {
        initialized = 0U;
        return STACK_INVALID;
    }
    bounds = (StackBounds){low, high, STACK_MSP, build_tag};
    history = (StackHistory){0};
    sequence = 0U;
    g_stack_probe = (StackProbeSnapshot){0};
    g_stack_probe.build_tag = build_tag;
    g_stack_probe.bounds = bounds;
    initialized = 1U;
    return STACK_OK;
}

uint32_t StackProbe_Capture(void)
{
    StackProbeRaw raw;
    StackSample sample;
    StackReport report;
    uint32_t result;
    if (initialized == 0U || __get_IPSR() != 0U || (__get_CONTROL() & 3U) != 0U
        || sequence == UINT32_MAX) {
        return STACK_INSUFFICIENT; /* No new snapshot; previous one stays historical. */
    }
    g_stack_probe.state = STACK_PROBE_WRITING;
    StackProbe_Entry(); /* Its MSP includes this function's existing C frame. */
    raw = g_stack_probe_raw;
    ++sequence;
    sample = (StackSample){raw.active_sp, STACK_MSP, bounds.build_tag, sequence,
        raw.ipsr == 0U && (raw.control & 3U) == 0U && raw.active_sp == raw.msp};
    result = StackEvidence_Observe(&bounds, &sample, &history, &report);
    g_stack_probe.raw = raw;
    g_stack_probe.report = report;
    g_stack_probe.status = result;
    g_stack_probe.sequence = sequence;
    /* Nominal metadata, not measured timing and not an atomic RCC snapshot. */
    g_stack_probe.hclk_nominal_hz = SystemCoreClock;
    g_stack_probe.rcc_cr = RCC->CR;
    g_stack_probe.rcc_pllcfgr = RCC->PLLCFGR;
    g_stack_probe.rcc_cfgr = RCC->CFGR;
    g_stack_probe.rcc_csr = RCC->CSR; /* Read only; do not clear reset flags. */
    __DMB();
    g_stack_probe.state = STACK_PROBE_COMPLETE;
    return result;
}
```

### 9.7 有限深度的目标调用：观察点而非帧大小承诺

**文件：`stm32/stack_demo.c`。** 应用实验层只依赖目标公开接口。pad 的 64 个字节不等于函数总帧大小；编译器还可能保存寄存器和对齐。`noinline`（禁止内联）是本实验采用的 GNU 属性，只限制内联，不冻结帧布局或禁止所有其他优化；实际结果看反汇编。[S13 的 noinline 条目]

```c
/* GNU Arm target experiment, not generic C11 frame-layout code. */
#include "stack_probe.h"

static volatile uint32_t demo_sink;

__attribute__((noinline)) static uint32_t sample_leaf(void)
{
    volatile uint32_t pad[16];
    uint32_t i, status;
    for (i = 0U; i < 16U; ++i) { pad[i] = i + 1U; }
    status = StackProbe_Capture();
    /* Work after capture, to discourage a sibling/tail call in this experiment. */
    for (i = 0U; i < 16U; ++i) { demo_sink ^= pad[i]; }
    return status;
}

uint32_t StackDemo_RunOnce(void)
{
    uint32_t first = StackProbe_Capture();
    uint32_t second;
    if (first != STACK_OK) { return first; }
    second = sample_leaf();
    return second;
}
```

### 9.8 链接保留区片段：尺寸必须由目标构建明确选择

**文件：`stm32/stack_reservation.ld.inc`。** 这不是完整脚本，也不是 Cube 默认脚本的已验证替代品。MEMORY/NOLOAD 的基础语义见 [S10]；ASSERT、ORIGIN/LENGTH 表达式与实际工具链版本兼容性仍须在目标工程核对。不得原样粘贴到未知位置后宣称链接/保护完成。

```ld
/* Integration FRAGMENT, not a standalone linker script.
 * Place inside the actual GNU ld SECTIONS block, after allocated RAM sections.
 * Replace the generated heap/stack-reservation SECTION, not the whole script.
 * STUDY_STACK_BYTES must be deliberately selected for the actual build.
 * RAM, _ebss and _estack must match the ACTUAL linker/startup symbols.
 */
.study_stack (ORIGIN(RAM) + LENGTH(RAM) - STUDY_STACK_BYTES) (NOLOAD) :
{
    __study_stack_low__ = .;
    . = . + STUDY_STACK_BYTES;
    __study_stack_high__ = .;
} > RAM
ASSERT(DEFINED(STUDY_STACK_BYTES), "STUDY_STACK_BYTES must be selected")
ASSERT(STUDY_STACK_BYTES > 0 && STUDY_STACK_BYTES <= LENGTH(RAM), "bad stack size")
ASSERT((__study_stack_low__ & 7) == 0 && (__study_stack_high__ & 7) == 0,
       "stack bounds must be 8-byte aligned")
ASSERT(_ebss <= __study_stack_low__, "BSS overlaps study stack")
ASSERT(_estack == __study_stack_high__, "vector initial MSP must match stack high")
```

## 10. 常见错误与纠正方式

| 错误 | 为什么不成立 | 本课的纠正动作 |
| --- | --- | --- |
| 把所有 SRAM 当栈 | 还可能有静态对象、堆或不连续存储区 | 使用专属保留段与对应符号，查 Map/向量/ELF |
| 从未验证的无符号减法得到“大剩余量” | SP 越界可能发生回绕 | 先做顺序/对齐/身份检查，再减法 |
| 在错栈中累计最低 SP | Handler 的 MSP 与 Thread 的 PSP 不属于同一条历史 | 每个真实栈/会话独立 history；未知身份报证据不足 |
| 一次最低 SP 就称峰值 | 采样外可能更深，尤其是 IRQ/库路径 | 改称“最低已观测”，补覆盖路径和采样时刻 |
| 扫描未改图案就是空闲栈 | 未写局部区、巧合图案、复用旧字都会影响扫描 | 同时保留 SP 观测与覆盖条件，不写成最坏保证 |
| 拿普通函数帧当八字异常帧 | 八字格式来自异常入口硬件，不是通用 C 布局 | 查原始 EXC_RETURN 和入口 SP；普通帧看机器码/展开信息 |
| handler 调了几个 C 函数后再读 LR/SP 当入口值 | 编译器和嵌套异常可能改变现场 | 在入口专用采集路径保存，或承认不是入口证据 |
| `pc_anchor` 就是任意故障 PC | 本课值是采样 label，不是被打断指令 | 字段名明确来源，不把它用于故障根因定位 |
| `COMPLETE` 就是有效/本次结果 | 写入完成不等于输入有效；拒绝前置条件会保留旧样本 | 同看本次返回值、sequence、status、has_numbers |
| 有 `-g` 或帧指针就必能完整回溯 | 编译、优化和展开器支持各有边界 | 保存完整选项与同构建信息，检查实际指令/表，而非承诺 |
| 用更大栈“修好”后就结案 | 可能掩盖越界写、错指针或异常嵌套问题 | 保留原始证据，提出能区分假设的实验 |

### 10.1 为什么不提供 main 内直接 memset 栈的代码

当前 main、C 运行时和中断可能正在使用同一区域。把整个保留区填成图案会破坏活动帧和返回信息。填充实验只能在已核对的启动/调试阶段，对明确未被使用、已从其他段排除的范围执行，并处理随后的初始化与异常；本任务不修改启动文件，也不提供可误粘贴执行的危险写栈示例。[S1 的 stack/exception；本课支持范围]

若将来做真实填充高水位实验，最低门槛为：

1. 在实际启动文件中确定执行填充的阶段及当时 MSP；确认未用 C 函数隐式压栈到要填的区域。
2. 指明哪些范围正在活跃、哪些范围允许填充；明确异常/复位/调试器是否可能介入。
3. 核对 `.bss`/`.data`/保留段的后续初始化，避免图案被启动代码改写后误算。
4. 执行记录中说明覆盖的输入、函数和异常路径；停止写入后再扫描合法范围。
5. 同时保留最低 SP、图案扫描结果与编译信息；承认未写区域、图案巧合与未覆盖路径的局限。

本课主机测试里的 `test_observation_limits` 用 16 字节普通数组演示两类漏计，不对真实栈做写入。

## 11. 调试观察点

### 11.1 目标调试前的产物门禁（均待执行）

1. 用实际工程构建；保存编译、汇编、链接器版本和完整命令行。优先建立一份容易观察的构建和一份原生产优化构建，不混用 ELF。
2. 可为实验构建评估 `-Og -g3 -fstack-usage -fno-omit-frame-pointer -fno-optimize-sibling-calls`；先由实际 GNU Arm 版本 `--help`/配套手册确认，再保留项目生成的 CPU、浮点和 ABI 选项。不可为了本课随意改浮点 ABI。[S8、S9]
3. `-fstack-usage` 产生的是函数级 `.su` 信息，含 `static/dynamic/bounded` 等限定，不是整条调用链的自动最坏峰值。动态且无 bounded 的记录尤其不能直接当总上界；组合函数路径还需考虑同时存活帧与异常。[S9]
4. 保留同一构建的 ELF、Map、链接脚本、`.su`、反汇编和 SHA-256。不要拿新代码解释旧快照。
5. 检查 `StackProbe_Entry` 没有被错误当作主机源处理、没有额外压栈；检查 C wrapper 的真实帧；核对调用链未意外变成预期外的内联/跳转。

下列只是**用户在真实目标构建完成后**的产物查看示例；本次未执行，`$elf` 必须选择真实构建产物，不是假文件名：

```powershell
$elf = (Resolve-Path -LiteralPath (Read-Host '输入本次实际构建的 ELF 路径')).Path
Get-FileHash -Algorithm SHA256 -LiteralPath $elf
arm-none-eabi-nm -n $elf
arm-none-eabi-objdump -d -S $elf
arm-none-eabi-readelf -S $elf
```

具体 binutils 工具参数须与目标安装版本核对；这里不把主机 GCC 或主机 ld 的成功当作这些目标工具已执行。

### 11.2 暂停在哪里，比“能看寄存器”更重要

| 观察点 | 应保存的东西 | 为什么选这里 |
| --- | --- | --- |
| 初始化完成、第一次 Capture 前 | 向量首项、实际区间符号、寄存器、RCC/频率计算、ELF 身份 | 把静态与初始假设先锁定 |
| `StackProbe_Entry` 入口 | 这次暂停时的 SP/LR/PC、CONTROL/IPSR（工具若可见） | 与编译后的 C wrapper 帧配对，不误当业务调用前 |
| Capture 返回之后 | `state=COMPLETE`、sequence、status、raw、report | 避免在 WRITING 中途把一半字段当完整快照 |
| `sample_leaf` 采样及返回后 | 第二次快照、实际反汇编、`.su`、调用位置 | 对比深入调用路径；不要求差值恰好为 pad 的 64 字节 |
| 任意现有 IRQ 路径 | handler 内观察与原始入口采集路径的区分 | 验证“当前 MSP”与“原始异常入口 SP”不是同一概念 |

GDB（GNU 调试器）的基础查看命令示意：

```text
info registers sp lr pc
p/x &__study_stack_low__
p/x &__study_stack_high__
p/x g_stack_probe
bt
info frame
disassemble StackProbe_Entry
```

命令基线参考 GNU 官方手册存档 [S11]；实际目标 GDB、远程调试服务器、寄存器描述与展开能力仍须用该版本 `help` 和官方手册核对。若工具未暴露 `$msp/$psp`，不要杜撰寄存器名字或把 `$sp` 同时叫 MSP 和 PSP；可先观察模块实际保存的两个字段。

**`bt` 显示的是当前暂停现场的展开，不是自动对 `g_stack_probe` 中过去的快照做离线展开。**把程序从采样点运行到 main 再看 `bt`，不能说那是刚才 leaf 内的调用链。若要保留那时的链，应在同一采样边界暂停并导出原始证据；离线重建需要额外工具支持，本课不实现。

### 11.3 构建、连接、用户烧录与观察步骤

本任务**不执行烧录**，也不改 IDE/CubeMX 全局设置。以下是将来由用户自行确认硬件后执行的参考流程，而非本次运行事实：

1. 在独立目标工程内选准 MCU、供电/调试连接和包版本，保存工程配置；构建失败先处理真实诊断，不套用主机测试结果。
2. 使用调试器只读连接，确认目标身份和复位方式；不认识芯片或连接失败时停止，不尝试擦除/解除保护。
3. 若用户决定加载固件，先按既有工程流程备份必要数据，再在其选定的 IDE/探针工具中选择本次 ELF 和已核对的 Flash 布局，执行该工程自己的下载/校验操作并保存日志。本课不生成通用擦除/写入地址命令。
4. 按 11.2 的位置设置断点，从可复现的复位/启动条件运行，导出两次快照及寄存器。暂停会改变实时行为；不要用它证明无中断扰动的实时峰值。
5. 对照边界、sequence 和构建身份填写结果；若首次都无法确认，不继续跑“压力实验”。

## 12. 实战实验

### 实验 A：主机的有效样本与拒绝路径

**输入：**8.1 的最小例和完整测试。**操作：**按命令编译运行 O0/O2，再阅读拒绝用例。**验收：**两种优化下所有断言通过；三个确定输出符合表格；拒绝样本不改变历史且新 report 不保留有效数值。

**反证：**把源码里的边界检查与减法顺序交换，或把历史最低值直接设为每次当前 SP。能否由现有用例抓住？只在复制出的个人实验分支/文件上做这种故意破坏，不改本课归档源码作为“修复”。

### 实验 B：观测不到的峰值与填充反例

阅读 `test_observation_limits`。序列只注入 `0x1380 -> 0x13C0`；设想两次间实际到过 `0x1100`，算法没有收到这次样本，所以不会凭空生成 768 字节峰值。

再看 16 字节图案数组：概念上分配至索引 4，只改写索引 12～15，扫描只能看到高端 4 字节改变。写入与图案相同值时可能完全看不出。

**验收：**分别写出“采样峰值”“图案改写范围”“假设中的最深分配”三个量，解释为何不相等。该数组实验不是测量主机真实栈，也不是测量 STM32 栈。

### 实验 C：基本异常帧的拒绝边界

使用 `test_frames` 的已复制数组：依次检查 F9、FD、F1 的栈/模式要求，再观察扩展编码、非法编码、CFSR 堆栈错误、截断、错误 xPSR/PC、对齐字不足的输出。

**验收：**能说明为何 `SP == high` 可作为空栈样本，却绝不能承载八字帧；为何“支持条件自洽”依然不能证明输入来自真实异常。没有写任何裸 SRAM 读循环。

### 实验 D：目标双采样（待实际目标工程执行）

**前置门禁：**8.2 的真实链接保留区、正确主栈、足够实验余量、所选包/工具链与构建身份齐全。**操作：**按 7.3 集成，分别在第一次 Capture 返回后和 leaf 中第二次 Capture 返回后暂停并导出快照；必要时修改个人目标工程观察位置，不改归档课程。

**预期但未测得：**在非内联的受控路径中，第二次快照可以体现更深调用的跨度；实际差值由机器码/保存寄存器/对齐决定，不承诺固定字节数。`observed_peak_bytes` 不应比同历史内已接受样本的 `used_bytes` 更小，且同历史中不递减。

**拒绝条件：**链接段不闭合、向量首项不匹配、包版本未核实、目标编译失败、采样不在支持模式、出现故障、无法确认 ELF 身份。停止并保存失败证据，不用手填“正常”数值补齐表格。

### 实验 E：优化与回溯的交叉检查（待执行）

在实际目标工程中分别构建易调试版本和原生产优化版本。每个版本各保存 ELF、选项、反汇编、`.su` 和暂停寄存器，独立重新初始化历史。比较有无内联/尾调用及回溯中的差异；没有出现差异也是有效结果，不强行生成预期截图。

**验收：**结论引用具体指令/帧证据，不是“优化开关越低就必定更真实”。不能跨版本累计高水位、用一个版本 ELF 解读另一个版本 PC，或把软件工具的回溯当作未损坏栈的证明。[S8、S9、S11]

**建议实验记录格式（空值表示待用户填写，不是已完成）：**目标身份；时钟/复位条件；构建哈希及 tag 对应；真实区间；采样边界；原始 SP/CONTROL/IPSR/PC/LR；是否原始异常入口及 EXC_RETURN；判定与不支持项；下一次反证。记录放入独立目标实验材料，而不是回填本课 `hardware_verified=true`。

## 13. 自检题

先独立回答，再对照提示；生成本节不会自动提高掌握度。

1. `low=0x20001000, high=0x20001400, sp=0x20001280` 时，占用跨度与距下界各多少？若此前采过 `0x20001200`，已观测峰值是多少？
2. 为什么 `sp==high` 可通过 Observe，却不能成为有效基本帧的入口？
3. Handler 中读到的当前 MSP，为什么不一定指向被中断 Thread 的自动帧？
4. 采样器拒绝新调用时，调试器仍看到上一次 COMPLETE 快照，怎样避免误当本次结果？
5. 同一 `stack_id` 但低边界改变，为什么不直接把旧 min_sp 与新边界组合？
6. 给出一个填充扫描低估栈分配深度的具体例子。
7. 普通 C 函数的 LR 与异常入口 EXC_RETURN 有什么本质不同？
8. 为什么 `-fno-omit-frame-pointer` 或一张完整 `bt` 截图都不能单独证明调用链可靠？
9. 本课目标快照中的 `pc_anchor` 与一个原始异常帧中的 PC，各能回答什么问题？
10. 什么证据到位后，你才愿意把一句“可能栈溢出”改成更精确的结论？

<details>
<summary>核对提示（不是掌握度评定）</summary>

1. 当前跨度 `0x180=384`，距下界 `0x280=640`；已观测峰值 `0x200=512` 字节。仍非最坏峰值证明。
2. high 是开区间端点；以它为 SP 的空栈没有可供该区间内读取的八字帧。
3. Thread 可能原用 PSP，且 handler 的 C 函数/嵌套异常也可能改变当前 MSP；需要原始入口信息。
4. 检查本次返回值和 sequence 是否推进，COMPLETE 只表示某次写完。
5. 区间与构建是历史身份的一部分；明确开启新历史而不是静默混合。
6. 预留 64 字节仅写 8 字节，或写入值与填充相同。
7. 普通 LR 与调用返回相关；入口 EXC_RETURN 编码返回模式、栈和帧类型，不能当普通 Flash 地址解析。
8. 优化、损坏、工具支持与构建匹配仍有条件；帧指针开关也非对所有函数的保证。
9. pc_anchor 定位本课采样代码；帧 PC 属于被打断的有限上下文，故障语义还需状态/指令互证。
10. 至少应能锁定真实栈区、构建、采样时机/所属栈、原始现场和可区分其他原因的反证实验，而不是只有一个 SP。

</details>

## 14. 面试题

**问：裸机系统的栈怎么定大小？**  
答题方向：先给具体构建/启动/区间约束，再组合函数级静态信息、可能同时存在的调用链、异常嵌套、库路径和受支持的浮点上下文预算，以运行覆盖补充验证并保留裕量依据。一次采样或图案扫描只能提供部分证据，不能给通用“某数字就够”的答案。

**问：HardFault 时看到 SP 越界，就一定是栈溢出吗？**  
答题方向：这支持“该候选 SP 不满足该区间”，还要排除错栈、错误链接界、损坏 SP、错误固件解释等；若堆栈故障位已置位，不应盲读八字帧。解释已经保存的原始状态，别先修改现场。

**问：为什么调用栈里没有某个源代码函数？**  
答题方向：区分源级调用、物理帧与工具展示，检查内联、尾调用、帧指针/展开信息、构建匹配和栈损坏；缺少一帧不是单一根因的证明。[S8、S11]

**问：为什么不能让栈监控函数自己证明“还有足够栈供我运行”？**  
答题方向：进入 C wrapper 本身已经使用栈；检查晚于部分风险。常规观测入口和越界后的安全故障入口属于不同契约，本课只实现前者。

**问：从 F407 迁到 H5/H7，要改哪些？**  
答题方向：保留“身份/边界/时机/构建互证”，重新查内核、安全域、栈限制/异常编码、真实 RAM 与缓存/调试可见性、启动链接和 Cube/工具版本，不能只换一个头文件。[S5、S6、S7]

## 15. 延伸思考

- 如果主循环每秒采一次，最深 IRQ 只持续几微秒，为什么增加采样日志不必然覆盖它？用哪个明确时机的新样本或专门实验更能反驳当前判断？
- 若同一数值地址在两版 ELF 中都位于 `.text`，怎样证明你选的是正确版本？考虑完整哈希与调试下载日志，而非 32 位 tag 本身。
- 一个合法基本帧的保存 LR 也可能是 EXC_RETURN：它提示了什么上下文层次，又为什么不足以拼出全部嵌套链？
- H5 的安全/非安全栈、H7 的缓存与内存域会分别挑战“地址值正确”“该地址可读”“读到的是同一时刻数据”哪一环？先列待查资料与实验，不凭 F4 经验填答案。
- 以后增加 RTOS 时，任务 PSP 历史和 handler MSP 历史如何分离、何时归属到特定任务？只写对象与证据需求，留到 `task/memory` 课程实现。

## 16. 本节总结

一个可信的栈判断至少同时说清楚：**哪个构建、哪个栈、哪个区间、哪个时刻、哪种现场、哪条可反驳的结论。**

本课两个核心概念贯穿同一证据闭环：

1. 静态保留、瞬时 SP、最低已观测 SP、填充改写范围与最坏使用量不可互换。
2. PC/LR、异常硬件帧、软件帧和工具回溯不可互换，必须与同构建产物互证。

主机已验证的是判断模型；目标参考代码没有对应构建/板级证据。未实现的能力被明确拒绝，尤其是浮点扩展帧、通用展开、并发调用和 fault 安全入口，而不是用未核对的猜测补齐。

## 17. 下一步

下一主题严格为 `debugging-verification / map-file`：用真实链接产物、段区间、符号和向量首项交叉确认本课栈边界，不把“链接脚本写了某个数”当作区间已证明。

随后按既有路线进入 `logic-analyzer`、`host-test`、`unit-test`；任务栈归属与并发留到 `rtos-concurrency/task、memory、isr`；缓存、MPU 和故障隔离分别留到 `performance-power-reliability/cache、mpu、fault-containment`。这些是能力地图的后续落点，不是本课新增概念或已完成能力。

Reviewer 通过后仅更新课程审查状态与按路线授课的进度：本主题记入 `completed`，下一主题为 `map-file`；`[mastery]` 保持不变。未修改既有课程、`.ai/`、`templates/` 或 `AGENTS.md`。用户实验/答案到位后，再按系统流程更新掌握度证据。

## 18. 参考资料

正文 `[S编号]` 与 `lesson.json.sources` 的编号一一对应。以下是本课选择的版本边界，不作“当前最新”保证。访问日期统一为 **2026-10-20**。ST 下载文档采用实际成功访问的完整官方地址；GNU 为项目官方资料，但按本仓库 `primary_domains` 规则不计入 primary 数量。

- **[S1] ST PM0214 Rev 10，2020-03，STM32 Cortex-M4 MCUs and MPUs programming manual。**重点：§2.1.2/2.1.3 的栈、处理器寄存器；§2.3.7、Figure 12、Table 18 的异常帧与返回；§4.4.7 CCR 与 §4.4.10～4.4.13 CFSR 的对齐及堆栈错误；MRS/MSR、DMB 与异常屏蔽说明。  
  `https://www.st.com/resource/en/programming_manual/dm00046982-stm32-cortexm4-mcus-and-mpus-programming-manual-stmicroelectronics.pdf`
- **[S2] ST RM0090 Rev 22，2026-05，STM32F405/415、F407/417、F427/437、F429/439 reference manual。**重点：§2 系统/存储器、§7 针对 F405/407/415/417 的 RCC、debug support。它规定器件集成，不替代处理器栈规则。  
  `https://www.st.com.cn/resource/en/reference_manual/dm00031020-stm32f405415-stm32f407417-stm32f427437-and-stm32f429439-advanced-armbased-32bit-mcus-stmicroelectronics.pdf`
- **[S3] ST DS8626 Rev 12，2026-03，STM32F405xx / STM32F407xx datasheet。**重点：器件范围、内存/容量、功能框图、时钟与电气边界；实际订货料号仍须补齐。  
  `https://www.st.com.cn/resource/en/datasheet/stm32f407vg.pdf`
- **[S4] ST STM32CubeF4 官方产品页，2026-10-20 页面快照。**只支持 CubeF4 软件包定位；计划拟用 v1.28.3，实际补丁发布信息与包内容未核验，不作为具体 CMSIS 子版本/模板的证据。  
  `https://www.st.com/en/embedded-software/stm32cubef4.html`
- **[S5] ST PM0253 Rev 6，2026-05，STM32F7/STM32H7 Cortex-M7 processor programming manual。**重点：处理器内存模型、缓存/TCM 和异常；这里只支撑迁移检查项，不从它推导所有具体 F7/H7 RAM 地址。  
  `https://www.st.com.cn/resource/en/programming_manual/dm00237416-stm32f7-series-and-stm32h7-series-cortexm7-processor-programming-manual-stmicroelectronics.pdf`
- **[S6] ST PM0264 Rev 8，2026-03，STM32 Cortex-M33 MCUs and MPUs programming manual。**重点：栈/栈限制、安全扩展与异常；H5 的器件安全配置需再查具体目标手册，不在此拼出所谓通用 H5 采集器。  
  `https://www.st.com.cn/resource/en/programming_manual/pm0264-stm32-cortexm33-mcus-programming-manual-stmicroelectronics.pdf`
- **[S7] ST RM0433 Rev 9，2026-10，STM32H742/H743/H753/H750 reference manual。**重点：系统/存储器、时钟/电源域和复位，仅作为选定 H7 子线的对照；不代表双核或全部 H7。  
  `https://www.st.com.cn/resource/en/reference_manual/dm00314099-stm32h742-stm32h743-753-and-stm32h750-value-line-advanced-armbased-32bit-mcus-stmicroelectronics.pdf`
- **[S8] GNU GCC 15.2.0 Manual，Optimize Options。**重点：frame-pointer、inline、sibling-call 优化的条件与限制；不是本次主机 GCC 或尚未选定的 GNU Arm 工具链的版本声明。  
  `https://gcc.gnu.org/onlinedocs/gcc-15.2.0/gcc/Optimize-Options.html`
- **[S9] GNU GCC 15.2.0 Manual，Developer Options。**重点：`-fstack-usage` 的函数级输出及 static/dynamic/bounded 限定。  
  `https://gcc.gnu.org/onlinedocs/gcc-15.2.0/gcc/Developer-Options.html`
- **[S10] GNU 官方 ld 文档存档，Command Language / MEMORY / Optional Section Attributes。**URL 位于 `ld-2.9.1` 目录，但本次缓存正文标题标记为 `ld version 2, January 1994`，不把路径名称当作已核实的正文版本。只用于稳定的区间安排、符号/段与 NOLOAD 基础说明；不拿旧存档证明现代工具所有表达式、ASSERT 或目标工程兼容性。目标脚本必须以实际 GNU ld 手册与构建诊断核验。  
  `https://ftp.gnu.org/old-gnu/Manuals/ld-2.9.1/html_mono/ld.html`
- **[S11] GNU 官方 GDB 手册存档（页面生成日期 2002-02-14），Stack frames / Backtrace / Frame Info。**仅作基础帧/命令语义依据，不对现代 GDB 或 Cortex-M 远程目标的展开实现作保证。当前在线手册本次访问返回 403；现代实现待选定目标工具后核对。  
  `https://ftp.gnu.org/old-gnu/Manuals/gdb/html_node/gdb_42.html`  
  同一存档的相邻阅读位置：node 41（Frames）、node 44（Frame Info）。
- **[S12] ST UM1725 Rev 8，2023-03，Description of STM32F4 HAL and low-layer drivers。**重点：HAL 初始化/配置、generic driver、RCC 和 HAL/LL 分工；具体 v1.28.3 包头文件/生成器模板仍待目标开工核验。  
  `https://www.st.com.cn/resource/en/user_manual/dm00105879-description-of-stm32f4-hal-and-ll-drivers-stmicroelectronics.pdf`

- **[S13] GNU GCC 15.2.0 Manual，Common Function Attributes，noinline 条目。**用于说明目标示例的禁止内联属性及其优化边界，不作实际 GNU Arm 版本声明。
  `https://gcc.gnu.org/onlinedocs/gcc-15.2.0/gcc/Common-Function-Attributes.html`
- **[S14] Arm Compiler v5.06 for µVision armlink User Guide，DUI0377H，2017，§4.4（pp.4-9～4-10）。**该官方资料中的 AAPCS 调用约定说明支持 R0～R3 的参数/结果/暂存用途和调用者保存责任；只用于这项 ABI 基础，不宣称本课选择了 Arm Compiler 5 或已验证 GNU Arm 的生成代码。
  `https://documentation-service.arm.com/static/5f4e134dca7b6a3399376bd3`

**证据纪律：**资料对行为提供约束，主机测试对模型提供证据，目标构建对具体代码集成提供证据，板级观察才对真实行为提供证据。这四层不能互相替代。未取得的包版本、目标编译、调试或测量结果均留为未验证，不在正文或元数据中补写成功。

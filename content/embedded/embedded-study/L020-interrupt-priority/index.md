+++
title = "中断优先级与服务顺序：从 Host Fake 到 Cortex-M 资料核对"
date = "2026-10-05T16:19:49+08:00"
lastmod = "2026-10-05T16:19:49+08:00"
summary = "把多个中断请求理解为由可比较的逻辑优先级规则决定服务顺序，并用静态 Host Fake 区分 pending、active、抢占、屏蔽和返回后的继续执行；主机模型不代表真实 Cortex-M 或 STM32 的编码、时序和上板结果。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 20
tags = ["interrupt-priority", "pending", "active", "preemption", "nvic", "isr", "host-fake", "c11", "beginner"]
source_ids = ["arm-ddi0403-latest", "st-pm0214"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L020"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 20 课：中断优先级与服务顺序

两个外部事件都已经形成请求时，处理器为什么不会“随机”选择一个？低优先级的中断服务例程（ISR，Interrupt Service Routine，中断服务例程）正在运行时，新来的高优先级请求为什么可能改变执行流，而另一个请求只保持 pending（挂起）？

本课只推进计划中的两个核心心智模型：

1. **中断请求通过可比较的优先级规则决定服务顺序**。
2. **抢占、挂起与返回后的继续执行是彼此分离的状态转换**。

先用普通 Windows 主机上的静态 C11 子集 Host Fake（主机伪实现）观察请求到达、pending、选择、抢占/不抢占、服务、清除/完成和返回；再把这条逻辑链迁移到 Cortex-M 与具体 STM32 资料的核对流程。Host Fake 只证明本文明确定义的模型逻辑，不证明真实 NVIC（Nested Vectored Interrupt Controller，嵌套向量中断控制器）寄存器编码、异常入口、指令时序、延迟或尾链行为。

## 1. 本节目标

本课核心目标与本次计划逐字一致：

> 学习者能把多个中断请求理解为由可比较的优先级规则决定服务顺序，并能区分抢占、挂起、活动和返回后继续执行这几个状态；学习者还应能用 Host Fake 解释同一时刻多个请求、服务中到达的新请求以及屏蔽期间累积请求的结果，而不把主机模型当作真实 Cortex-M 或 STM32 时序证据。

完成后应能：

- 用“逻辑优先级 + 比较规则”解释多个 pending 请求的选择顺序；
- 把优先级的逻辑排序和寄存器中的数值编码分开描述，不凭经验断言“数字越小/越大”；
- 在状态图中区分线程态、当前 active（活动）ISR、pending 请求和返回后恢复的上下文；
- 读懂一个不使用动态内存或函数指针的 C11 Host Fake，覆盖同时到达、服务中到达高优先级请求、同级请求、屏蔽累积和返回；
- 说明主机输出能证明什么、不能证明什么，并列出迁移到 F4、F7、H5、H7 时必须查的资料和证据。

本课不推进定时器、UART、SPI、I2C、ADC、DMA、RTOS、优先级反转或驱动架构。优先级分组、IRQ（Interrupt Request，中断请求）、exception（异常）、tail-chaining（尾链）只作为理解边界的辅助术语。

## 2. 它解决什么问题

上一课已经说明：输入变化经过 EXTI（External Interrupt/Event Controller，外部中断/事件控制器）的映射、触发和屏蔽后，可以形成一个持有到服务/清除的请求。现在问题变成：**如果不止一个请求同时处于可服务状态，下一步服务谁？**

还要处理第二个时间关系：**服务一个请求的过程中，新的请求可能到达。** 如果新请求具有更高的服务资格，执行流可能暂时离开当前 ISR；如果它没有更高资格，它只会保持 pending，等当前服务返回后再获得机会。

因此，下列说法必须分开：

| 观察到的事实 | 只说明什么 | 不能直接推出什么 |
| --- | --- | --- |
| 请求到达 | 某个来源提出了待处理事件 | 处理器已经进入 ISR |
| `pending=1` | 控制逻辑记录了尚未完成的请求 | 请求已经被服务或已经排队多次 |
| `active=1` | 某个请求对应的服务上下文正在执行 | 其他 pending 请求已消失 |
| 发生抢占 | 当前服务上下文被更高资格请求暂时打断 | 目标芯片的具体延迟或栈帧格式 |
| 返回 | 当前服务上下文结束，可能恢复前一个上下文或线程态 | 所有 pending 都已清除 |

本课的抽象关系如下：

```text
请求到达 -> pending
              |
              +-- 可服务且无 active：选择 -> active ISR
              |
              +-- 服务中有更高资格请求：抢占 -> 新 active ISR
              |
              +-- 被屏蔽或资格不足：继续 pending

active ISR -> 服务/完成 -> 返回 -> 恢复被抢占 ISR 或线程态
```

## 3. 必要前置知识

只把 `config/learning-state.toml` 的 `completed` 中明确记录的主题当作前置：

1. C 基本对象、固定宽度整数、指针、`const`/`volatile`、存储期和链接关系；能读懂简单结构体与状态变量。
2. 编译器、构建产物和静态分析的基本证据意识；知道主机程序输出只能证明模型逻辑。
3. 启动、向量表、异常入口、链接与存储器布局的基本证据意识；知道处理器行为要按架构和芯片资料核对。
4. GPIO：输入采样是外部状态进入软件的前置环节。
5. EXTI：事件经过映射、触发和屏蔽形成请求，并进入可持有的 pending 状态；服务和清除是不同动作。

本课不假定掌握具体开发板、STM32 型号、NVIC 优先级位宽、优先级分组复位值、IRQ 名称、HAL/LL 函数签名、异常延迟、尾链细节、调试器寄存器窗口或逻辑分析仪操作。

## 4. 核心原理

### 4.1 核心机制一：可比较的逻辑优先级决定服务顺序

**它解决什么问题？** 多个请求都 pending 时，系统需要稳定的选择规则，避免服务顺序依赖偶然的观察顺序。

**对象在哪里定义？** 在 Host Fake 中，逻辑优先级是每条请求的 `priority_rank` 字段，比较器规定“rank 较小者先选；rank 相同则请求 ID 较小者先选”。这是为了得到可复现输出而选的模型约定，不是对 Cortex-M 数值编码方向的通则。真实系统中的优先级字段、有效位数、分组和编码方向必须查 Arm 架构手册、目标系列参考手册及软件包版本。

**谁持有它？** Host Fake 的 `irq_fake_controller_t` 静态对象持有请求表；每个 `irq_fake_request_t` 持有自己的逻辑 rank 和 pending 标志。真实硬件由中断控制器和相关实现状态共同持有，不能用这个结构体的布局代替。

**谁建立它？** Host Fake 的测试代码调用 `irq_fake_configure()` 建立 rank。真实工程的初始化代码建立配置，但具体是哪个寄存器字段或 HAL/LL API，当前没有目标型号和版本，保持“待核对”。

**调用如何流动？** 请求到达把 pending 置 1；选择器遍历所有 pending 请求并使用比较器；选中者进入 active 服务上下文；服务完成后该请求结束，选择器再次处理剩余 pending。

这里有一个重要的语言纪律：**逻辑排序不是数值编码。** 课程模型可以用 `0`、`1`、`2` 表示 rank，但这只表达本模型的比较关系。Arm 与 STM32 资料需要分别核对优先级字段的解释；不能把主机的 `0` 直接翻译成任一系列的寄存器值。

### 4.2 核心机制二：抢占、挂起与返回后的继续执行是分离状态转换

**它解决什么问题？** 服务顺序不是一条简单队列：当前 ISR 可能仍在执行，新请求可能先被记录，再根据资格决定是否改变当前执行上下文。

**对象在哪里定义？** Host Fake 用 `pending` 表示已记录但尚未开始服务，用 `active` 和 `active_stack[]` 表示当前及被暂时挂起的服务上下文，用 `active_depth` 表示嵌套层数。真实 Cortex-M 的 pending/active 和异常返回语义必须以 Arm 架构资料及目标实现资料核对。

**谁持有它？** 模型控制器持有活动栈和屏蔽标志；请求对象持有本请求的 pending、active 和服务计数。控制器并不模拟真实硬件栈帧，只保存足以验证状态转换的 ID。

**谁建立它？** 测试代码注入到达事件和屏蔽状态；模型的 `irq_fake_dispatch()` 根据比较规则决定“抢占”或“不抢占”；服务代码调用 `irq_fake_service_current()` 和 `irq_fake_finish_current()` 表示服务与返回。

**调用如何流动？**

```text
线程态
  -> 请求到达，pending=1
  -> 选择并进入 ISR，active=1
  -> 服务中高资格请求到达
       -> 资格更高：旧 active 保留在模型栈，新请求 active（抢占）
       -> 资格不更高：新请求继续 pending（不抢占）
  -> 新 ISR 完成并返回
  -> 恢复旧 ISR；旧 ISR 完成后返回线程态
```

“pending”不是“低优先级正在运行”的同义词，“active”也不是“该请求永远不能再次 pending”的同义词。真实控制器可能对同一来源的重复请求有合并或其他语义，本模型只定义一个静态 pending 位，不能外推为事件计数器。

### 4.3 屏蔽是服务资格之外的边界

本课的 `mask_all` 表示模型暂时不进行新的选择。屏蔽期间到达的请求仍会把自己的 pending 置为 1；解除屏蔽时再调用选择器。这样可以观察“请求已经累积”和“当前没有立即进入服务”是两件事。

这不是对某个 STM32 全局屏蔽寄存器的具体断言。真实目标可能存在不同层级的屏蔽、优先级阈值或异常控制规则；字段、读写权限、复位值和作用范围均待核对。

### 4.4 声明、实现、实例化、组装和使用

虽然本课不是架构课，仍明确区分五个动作：

1. **声明**：定义 `irq_fake_request_t`、`irq_fake_controller_t`、状态码和函数原型。
2. **实现**：实现配置校验、比较、pending 置位、抢占判断、服务、完成和返回。
3. **实例化**：`main` 中的 `static irq_fake_controller_t controller` 是一个主机模型对象，不是 NVIC 外设地址。
4. **组装**：测试代码调用 `irq_fake_configure()` 写入请求 rank，并用 `irq_fake_set_mask()` 建立屏蔽状态。
5. **使用**：测试代码调用 `irq_fake_arrive()` 注入事件，调用服务/完成函数并读取输出。

这五个动作在真实工程中仍然有助于定位责任边界，但不能从函数名推断 STM32 的 IRQ 入口或 HAL 行为。

## 5. 关键术语与直观模型

| 术语 | 本课中的准确含义 |
| --- | --- |
| IRQ | Interrupt Request，中断请求；某个外设或系统源提出的待处理请求。 |
| exception | 异常；处理器统一异常模型中的事件类别，本课只观察与选择和返回有关的边界。 |
| priority | 优先级；用于比较服务资格的逻辑属性，编码方向和有效位数待按目标资料核对。 |
| NVIC | Nested Vectored Interrupt Controller，嵌套向量中断控制器；Cortex-M 侧接收、保持和选择外部中断请求的控制部分。具体实现范围待核对。 |
| pending | 挂起；请求已经被记录，但尚未完成本模型定义的服务。 |
| active | 活动；对应服务上下文当前正在执行，或在嵌套模型中仍位于活动栈上。 |
| ISR | Interrupt Service Routine，中断服务例程；处理已选择请求的代码入口。 |
| preemption | 抢占；当前可打断的服务上下文暂时让出执行流给更高服务资格的请求。 |
| priority grouping | 优先级分组；可能把优先级字段划分为抢占相关部分和同级排序部分的配置概念，具体支持和复位值待核对。 |
| tail-chaining | 尾链；异常返回路径上的连续异常服务优化术语，是否以及如何体现需按 Arm 与芯片资料核对。 |
| critical section | 临界区；暂时限制某些请求服务以保护共享状态的代码区。本课只用一个模型屏蔽标志，不展开 RTOS 语义。 |
| Host Fake | 主机伪实现；用静态 C11 状态机验证排序和状态转换，不模拟寄存器、指令周期、栈帧或硬件延迟。 |

直观地把请求想成带有两个独立标签的卡片：

```text
请求卡片 A: priority_rank=2, pending=0, active=1
请求卡片 B: priority_rank=1, pending=1, active=0

当前 A 正在服务，B 到达：
  比较器判断 B 的 rank 更有服务资格 -> B 抢占 A
  A 没有被“清除”，只是留在 active 栈中等待返回
  B 完成返回 -> A 继续
```

## 6. 从输入到结果的完整流程

### 6.1 同一时刻多个请求

假设请求 0 的 rank 为 2，请求 1 和 2 的 rank 都为 1。模型规定 rank 越小越早，rank 相同时 ID 越小越早：

```text
请求 0 到达 -> pending(0)=1
请求 1 到达 -> pending(1)=1
请求 2 到达 -> pending(2)=1
选择        -> 先选 1（rank=1，ID=1）
完成返回    -> 再选 2（同 rank，ID=2）
完成返回    -> 最后选 0
```

这只说明模型的确定性排序。它没有证明任何芯片采用相同的数值方向、同级排序或请求合并方式。

### 6.2 低优先级服务中到达高优先级请求

```text
线程态 -> 请求 0 到达 -> 选择 0 -> active(0)
服务 0 尚未完成
请求 1 到达 -> pending(1)
比较 rank(1) 与 rank(0)
       -> 1 更有资格：抢占，active 栈为 [0, 1]
服务 1 -> 完成 1 -> 返回并恢复 0
服务 0 -> 完成 0 -> 返回线程态
```

“抢占”在本模型中只是活动栈和输出的状态变化；它没有生成真实异常入口、保存真实寄存器或测量延迟。

### 6.3 低或同级请求在服务期间到达

如果请求 2 的 rank 与当前请求 0 相同，比较器按 ID 处理且本模型不允许同级抢占：请求 2 保持 pending。当前请求完成返回后，下一次 dispatch（分派/选择）才会选择请求 2。目标架构是否允许某类同级异常打断，必须按目标资料核对，不能由本模型推断。

### 6.4 屏蔽期间累积

```text
mask_all=1
请求 0/1/2 到达 -> 各自 pending=1，输出“屏蔽，不选择”
mask_all=0       -> 依据模型比较器逐个选择
```

屏蔽不等于清除。若某个目标实现规定屏蔽操作有额外副作用，必须在具体参考手册中记录；本文模型不模拟该副作用。

### 6.5 真实目标的证据流

```text
具体 MCU、封装、Cube 固件版本
    -> Arm 架构手册：异常优先级、pending/active、抢占与返回的一般语义
    -> STM32 系列编程/参考手册：实现字段、优先级分组、IRQ 来源和可见性
    -> HAL/LL 文档与生成工程：API 参数、IRQ 入口和版本差异
    -> 构建/调试/测量：确认配置进入目标、服务顺序和时间关系
```

本次没有具体型号，因此不写寄存器地址、优先级位数、IRQ 名称、复位值或 API 签名。Arm 手册可用于架构边界，PM0214 可用于 F4 主线的 Cortex-M4 编程资料范围；两者都不能自动证明 F7、H5、H7 或某个 HAL 版本的全部细节。[1][2]

## 7. 嵌入式系统中的对应位置

### 7.1 从 EXTI 请求到处理器选择

上一课的 EXTI 状态是本课的输入边界：外部事件被记录为某条请求的 pending。当前课再引入一个处理器侧选择层：多个 pending 请求依据可比较规则竞争服务机会。服务代码是被选择后的消费者，不负责决定全局排序。

一个不依赖具体寄存器名称的责任划分是：

| 责任 | 模型中的对象 | 真实目标要查什么 |
| --- | --- | --- |
| 产生请求 | `irq_fake_arrive()` | 外设/EXTI 的事件到 IRQ 请求路径 |
| 持有 pending | `request.pending` | pending 状态的置位、合并和清除语义 |
| 建立排序 | `irq_fake_configure()` | 优先级字段、分组和配置 API |
| 选择/抢占 | `irq_fake_dispatch()` | 控制器的服务资格、屏蔽和嵌套规则 |
| 执行服务 | `irq_fake_service_current()` | 向量入口、ISR 代码和共享状态访问 |
| 完成/返回 | `irq_fake_finish_current()` | 异常返回、恢复上下文和剩余 pending |

### 7.2 F4、F7、H5、H7 的可迁移方法

可迁移的不是某个寄存器数字，而是证据顺序：

1. 先确认具体 MCU、封装、架构资料和 Cube 固件版本；
2. 查该系列参考手册和编程手册，确认优先级字段、有效位数、分组、pending/active 读写语义；
3. 对照 HAL/LL 文档和生成工程，确认配置调用的参数范围与 IRQ 入口；
4. 用构建产物、调试器观察、事件时间戳或逻辑分析仪验证实际服务顺序；
5. 把“架构手册结论”“系列实现结论”“本次测量结论”分开记录。

F4、F7、H5、H7 在线路组织、控制器配置、优先级字段、软件包版本和调试可见性上可能不同。当前没有具体器件和证据，不把任一系列的位宽、复位值或 HAL 调用外推到其他系列。

### 7.3 五种动作在真实工程中的阅读方法

阅读一个中断配置时，可以按下面的问题定位代码，而不把层次混成一句“开中断”：

- **声明**：哪个头文件声明了配置对象、状态类型和接口？
- **实现**：哪个 C 文件实现了比较、服务和清除？
- **实例化**：哪个文件为具体外设或模型分配了存储？
- **组装**：哪个初始化路径把请求源、优先级和服务入口连起来？
- **使用**：哪个 ISR 或应用代码消费 pending 并报告完成？

本课的 Host Fake 只把这五种动作显式化，帮助阅读真实工程；它不替代 BSP（Board Support Package，板级支持包）和启动代码的资料核对。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 能证明什么

- 模型用固定比较器为多个 pending 请求产生确定顺序；
- 当前 active 请求服务期间，更高 rank 的请求会触发模型中的抢占；
- 同级请求按模型约定的 ID 规则处理且不抢占当前服务；
- 屏蔽期间到达的请求保持 pending，解除屏蔽后才进入选择；
- 完成一个嵌套服务后，模型能返回并恢复先前 active 请求；
- 非法请求 ID 返回确定错误码，未定义的数组访问不会发生。

### 8.2 Host Fake 不能证明什么

- 不能证明真实 Cortex-M 或 STM32 的优先级数值编码方向、有效位宽、分组复位值或 IRQ 名称；
- 不能证明真实异常入口、向量表查找、栈帧保存、尾链或抢占延迟；
- 不能证明同一外设重复事件在目标实现中是合并、计数、覆盖还是丢失；
- 不能证明 HAL/LL 的参数范围、寄存器写法、屏蔽副作用或具体清除时序；
- 不能证明主机输出等于真实电气波形、服务抖动或实时性指标。

因此本课的 `hardware_verified` 必须保持 `false`。生成课程和阅读代码都不会提高 mastery（掌握度）；掌握度要由学习者答案、实验记录或复习结果更新。

## 9. 最小代码示例

下面是完整 Host Fake。它使用静态数组、固定宽度整数和确定错误码，不使用动态内存、真实异常指令或函数指针。模型约定 `priority_rank` 越小越早，rank 相同时请求 ID 越小越早；代码中的 rank 不是 STM32 寄存器编码。输出中的标签刻意区分“请求到达”“pending”“选择”“抢占/不抢占”“服务”“完成/清除”和“返回”。

代码状态：**示例，待主机执行；迁移到具体目标后待构建、调试和上板验证。**

```c
#include <stdint.h>
#include <stdio.h>

#define IRQ_FAKE_MAX_REQUESTS (3U)
#define IRQ_FAKE_NO_ACTIVE    (-1)

typedef int32_t irq_fake_status_t;

enum {
    IRQ_FAKE_OK = 0,
    IRQ_FAKE_ERR_ARGUMENT = -1,
    IRQ_FAKE_ERR_ID = -2,
    IRQ_FAKE_ERR_NOT_CONFIGURED = -3,
    IRQ_FAKE_ERR_NO_ACTIVE = -4,
    IRQ_FAKE_ERR_STACK_FULL = -5,
    IRQ_FAKE_ERR_NO_PENDING = -6
};

typedef struct {
    uint8_t configured;
    uint8_t priority_rank;
    uint8_t pending;
    uint8_t active;
    uint32_t service_count;
} irq_fake_request_t;

typedef struct {
    irq_fake_request_t request[IRQ_FAKE_MAX_REQUESTS];
    int32_t active_stack[IRQ_FAKE_MAX_REQUESTS];
    uint8_t active_depth;
    uint8_t mask_all;
} irq_fake_controller_t;

static int32_t irq_fake_check_id(uint32_t id)
{
    return (id < IRQ_FAKE_MAX_REQUESTS) ? IRQ_FAKE_OK
                                        : IRQ_FAKE_ERR_ID;
}

static irq_fake_status_t irq_fake_init(irq_fake_controller_t *controller)
{
    uint32_t index;

    if (controller == NULL) {
        return IRQ_FAKE_ERR_ARGUMENT;
    }

    controller->active_depth = 0U;
    controller->mask_all = 0U;
    for (index = 0U; index < IRQ_FAKE_MAX_REQUESTS; ++index) {
        controller->request[index].configured = 0U;
        controller->request[index].priority_rank = 0U;
        controller->request[index].pending = 0U;
        controller->request[index].active = 0U;
        controller->request[index].service_count = 0U;
        controller->active_stack[index] = IRQ_FAKE_NO_ACTIVE;
    }
    return IRQ_FAKE_OK;
}

static irq_fake_status_t irq_fake_configure(
    irq_fake_controller_t *controller,
    uint32_t id,
    uint8_t priority_rank)
{
    if (controller == NULL) {
        return IRQ_FAKE_ERR_ARGUMENT;
    }
    if (irq_fake_check_id(id) != IRQ_FAKE_OK) {
        return IRQ_FAKE_ERR_ID;
    }

    controller->request[id].configured = 1U;
    controller->request[id].priority_rank = priority_rank;
    return IRQ_FAKE_OK;
}

static int32_t irq_fake_select_pending(
    const irq_fake_controller_t *controller)
{
    uint32_t index;
    int32_t selected = IRQ_FAKE_NO_ACTIVE;

    for (index = 0U; index < IRQ_FAKE_MAX_REQUESTS; ++index) {
        const irq_fake_request_t *candidate = &controller->request[index];

        if ((candidate->configured == 0U) || (candidate->pending == 0U)) {
            continue;
        }
        if (selected == IRQ_FAKE_NO_ACTIVE) {
            selected = (int32_t)index;
            continue;
        }

        {
            const irq_fake_request_t *current =
                &controller->request[(uint32_t)selected];
            const uint8_t better_rank =
                (candidate->priority_rank < current->priority_rank);
            const uint8_t same_rank_earlier_id =
                (candidate->priority_rank == current->priority_rank) &&
                (index < (uint32_t)selected);

            if ((better_rank != 0U) || (same_rank_earlier_id != 0U)) {
                selected = (int32_t)index;
            }
        }
    }
    return selected;
}

static irq_fake_status_t irq_fake_start(
    irq_fake_controller_t *controller,
    uint32_t id)
{
    irq_fake_request_t *request;

    if (controller->active_depth >= IRQ_FAKE_MAX_REQUESTS) {
        return IRQ_FAKE_ERR_STACK_FULL;
    }
    request = &controller->request[id];
    controller->active_stack[controller->active_depth] = (int32_t)id;
    controller->active_depth += 1U;
    request->active = 1U;
    request->pending = 0U;
    (void)printf("选择 id=%lu rank=%u -> active depth=%u\n",
                 (unsigned long)id,
                 (unsigned int)request->priority_rank,
                 (unsigned int)controller->active_depth);
    return IRQ_FAKE_OK;
}

static irq_fake_status_t irq_fake_dispatch(irq_fake_controller_t *controller)
{
    int32_t selected;

    if (controller == NULL) {
        return IRQ_FAKE_ERR_ARGUMENT;
    }
    selected = irq_fake_select_pending(controller);

    if (selected == IRQ_FAKE_NO_ACTIVE) {
        return IRQ_FAKE_ERR_NO_PENDING;
    }
    if (controller->mask_all != 0U) {
        (void)printf("选择 skipped: 屏蔽，pending 保持\n");
        return IRQ_FAKE_OK;
    }
    if (controller->active_depth == 0U) {
        return irq_fake_start(controller, (uint32_t)selected);
    }

    {
        const uint32_t current_id =
            (uint32_t)controller->active_stack[controller->active_depth - 1U];
        const uint8_t selected_rank =
            controller->request[(uint32_t)selected].priority_rank;
        const uint8_t current_rank =
            controller->request[current_id].priority_rank;

        if (selected_rank < current_rank) {
            (void)printf("抢占 current=%lu by=%ld\n",
                         (unsigned long)current_id,
                         (long)selected);
            return irq_fake_start(controller, (uint32_t)selected);
        }
        (void)printf("不抢占 current=%lu，pending id=%ld\n",
                     (unsigned long)current_id,
                     (long)selected);
    }
    return IRQ_FAKE_OK;
}

static irq_fake_status_t irq_fake_arrive(
    irq_fake_controller_t *controller,
    uint32_t id)
{
    if (controller == NULL) {
        return IRQ_FAKE_ERR_ARGUMENT;
    }
    if (irq_fake_check_id(id) != IRQ_FAKE_OK) {
        return IRQ_FAKE_ERR_ID;
    }
    if (controller->request[id].configured == 0U) {
        return IRQ_FAKE_ERR_NOT_CONFIGURED;
    }

    controller->request[id].pending = 1U;
    (void)printf("请求到达 id=%lu -> pending=1\n", (unsigned long)id);
    if (controller->mask_all != 0U) {
        (void)printf("不选择 id=%lu：屏蔽期间累积\n",
                     (unsigned long)id);
        return IRQ_FAKE_OK;
    }
    return irq_fake_dispatch(controller);
}

static irq_fake_status_t irq_fake_set_mask(
    irq_fake_controller_t *controller,
    uint8_t mask_all)
{
    if (controller == NULL) {
        return IRQ_FAKE_ERR_ARGUMENT;
    }
    controller->mask_all = (mask_all != 0U) ? 1U : 0U;
    (void)printf("mask_all=%u\n", (unsigned int)controller->mask_all);
    if (controller->mask_all == 0U) {
        (void)irq_fake_dispatch(controller);
    }
    return IRQ_FAKE_OK;
}

static irq_fake_status_t irq_fake_service_current(
    irq_fake_controller_t *controller)
{
    uint32_t id;

    if ((controller == NULL) || (controller->active_depth == 0U)) {
        return IRQ_FAKE_ERR_NO_ACTIVE;
    }
    id = (uint32_t)controller->active_stack[controller->active_depth - 1U];
    controller->request[id].service_count += 1U;
    (void)printf("服务 id=%lu count=%lu\n",
                 (unsigned long)id,
                 (unsigned long)controller->request[id].service_count);
    return IRQ_FAKE_OK;
}

static irq_fake_status_t irq_fake_finish_current(
    irq_fake_controller_t *controller)
{
    uint32_t id;

    if ((controller == NULL) || (controller->active_depth == 0U)) {
        return IRQ_FAKE_ERR_NO_ACTIVE;
    }
    id = (uint32_t)controller->active_stack[controller->active_depth - 1U];
    controller->request[id].active = 0U;
    (void)printf("完成/清除 id=%lu\n", (unsigned long)id);
    controller->active_depth -= 1U;
    controller->active_stack[controller->active_depth] = IRQ_FAKE_NO_ACTIVE;
    if (controller->active_depth == 0U) {
        (void)printf("返回 -> 线程态\n");
    } else {
        (void)printf("返回 -> 恢复 id=%ld\n",
                     (long)controller->active_stack[controller->active_depth - 1U]);
    }
    (void)irq_fake_dispatch(controller);
    return IRQ_FAKE_OK;
}

static int expect_status(const char *label,
                         irq_fake_status_t actual,
                         irq_fake_status_t expected)
{
    if (actual != expected) {
        (void)printf("FAIL %s actual=%ld expected=%ld\n",
                     label, (long)actual, (long)expected);
        return 1;
    }
    (void)printf("PASS %s\n", label);
    return 0;
}

int main(void)
{
    static irq_fake_controller_t controller;
    int failures = 0;

    failures += expect_status("init",
                              irq_fake_init(&controller), IRQ_FAKE_OK);
    failures += expect_status("configure 0",
                              irq_fake_configure(&controller, 0U, 2U),
                              IRQ_FAKE_OK);
    failures += expect_status("configure 1",
                              irq_fake_configure(&controller, 1U, 1U),
                              IRQ_FAKE_OK);
    failures += expect_status("configure 2",
                              irq_fake_configure(&controller, 2U, 1U),
                              IRQ_FAKE_OK);
    failures += expect_status("invalid id",
                              irq_fake_configure(&controller, 3U, 0U),
                              IRQ_FAKE_ERR_ID);

    /* 低 rank 数字是本模型的约定，不是硬件编码结论。 */
    (void)irq_fake_arrive(&controller, 0U);
    (void)irq_fake_arrive(&controller, 1U); /* 高资格请求抢占 0。 */
    (void)irq_fake_service_current(&controller);
    (void)irq_fake_finish_current(&controller);
    (void)irq_fake_service_current(&controller);
    (void)irq_fake_finish_current(&controller);

    /* 屏蔽期间三个请求累积，解除后按 rank、ID 依次选择。 */
    (void)irq_fake_set_mask(&controller, 1U);
    (void)irq_fake_arrive(&controller, 0U);
    (void)irq_fake_arrive(&controller, 1U);
    (void)irq_fake_arrive(&controller, 2U);
    (void)irq_fake_set_mask(&controller, 0U);
    (void)irq_fake_service_current(&controller);
    (void)irq_fake_finish_current(&controller);
    (void)irq_fake_dispatch(&controller);
    (void)irq_fake_service_current(&controller);
    (void)irq_fake_finish_current(&controller);
    (void)irq_fake_dispatch(&controller);
    (void)irq_fake_service_current(&controller);
    (void)irq_fake_finish_current(&controller);

    /* 改成同 rank，观察到达时不抢占当前服务。 */
    (void)irq_fake_configure(&controller, 2U, 2U);
    (void)irq_fake_arrive(&controller, 0U);
    (void)irq_fake_arrive(&controller, 2U);
    (void)irq_fake_service_current(&controller);
    (void)irq_fake_finish_current(&controller);
    (void)irq_fake_dispatch(&controller);
    (void)irq_fake_service_current(&controller);
    (void)irq_fake_finish_current(&controller);

    return (failures == 0) ? 0 : 1;
}
```

代码中有意使用 `irq_fake_finish_current()` 表示“完成并返回”，而 `irq_fake_service_current()` 只增加服务计数。这样可以看到：服务动作、pending/active 的状态变化和返回动作不是同一个调用。代码没有真实的异常指令，也没有把 `active_stack` 说成处理器真实栈帧。

## 10. 常见错误

1. **把“数字越小优先级越高”写成普遍规律。** 本课只在 Host Fake 中约定 rank 越小越早；真实编码方向和有效位数必须按 Arm、系列参考手册和软件包核对。
2. **把 pending 当成 FIFO（First In, First Out，先进先出）队列。** 本模型每个请求只有一个 pending 位，不能推出重复事件被计数或按到达次数排队。
3. **把 active 当成 pending 的同义词。** pending 表示尚未开始本模型定义的服务；active 表示服务上下文当前在活动栈中。
4. **把服务函数调用当成完成。** 代码明确分开 service、finish/clear 和 return；目标器件的清除语义还要查资料。
5. **认为同级请求必然可以抢占。** 本模型选择不允许同级抢占，只是示例规则；目标架构和实现需核对。
6. **把屏蔽理解为清空已有请求。** 本模型只阻止新选择，保留 pending；具体芯片若有不同副作用，必须引用其手册。
7. **用 Host Fake 输出声称硬件延迟、向量入口或尾链已经验证。** 主机只验证静态逻辑，不能替代目标构建、调试和测量。
8. **在没有型号时写寄存器地址、IRQ 名称或 HAL 签名。** 当前条件不足，统一标记为“待核对”。

## 11. 调试观察点

把一次问题拆成以下观察点，并在记录中注明观察来源：

| 观察点 | Host Fake 可观察内容 | 真实目标需要的证据 |
| --- | --- | --- |
| 请求到达 | `请求到达 id=...` 输出和 `pending=1` | 外设/EXTI 状态、事件注入或测量波形 |
| 选择 | `选择 id=... rank=...` | 控制器优先级字段、调试器状态或 ISR 入口记录 |
| 抢占 | `抢占 current=... by=...` | 嵌套异常状态、时间戳、目标调试观察 |
| 不抢占 | `不抢占 ... pending` | 当前屏蔽/优先级资格和待处理状态 |
| 服务 | 服务计数增加 | ISR 内可观测标记、日志或断点计数 |
| 完成/清除 | 模型的 `完成/清除` | 目标手册规定的清除动作及寄存器读回 |
| 返回 | `恢复 id=...` 或 `线程态` | 异常返回行为、栈和必要的时间测量 |

调试时先问“哪个状态没有发生”，再问“哪个寄存器写错了”：

- 有输入但没有 pending：先查 EXTI/外设请求形成和屏蔽边界；
- 有 pending 但没有选择：查模型/目标的服务资格和全局屏蔽；
- 选择了但没有服务：查向量入口、启动和 ISR 连接；
- 服务后仍有 pending：查清除语义、重复事件和服务边界；
- 低优先级没有恢复：查返回路径和是否仍有更高资格 pending。

这些是诊断顺序，不是对具体芯片寄存器的实现断言。

## 12. 实战实验

### 12.1 必做：Host Fake 逻辑验证

1. 将第 9 节代码保存为 `interrupt_priority_fake.c`。
2. 在普通 Windows 主机上使用已有的 C11 编译器构建；例如 GCC 可尝试：

   ```text
   gcc -std=c11 -Wall -Wextra -pedantic interrupt_priority_fake.c -o interrupt_priority_fake.exe
   .\interrupt_priority_fake.exe
   ```

   如果本机没有 `gcc`，可使用已有的其他 C11 编译器，记录实际命令和版本；不要为本课安装或修改全局工具链。
3. 记录每个场景的输入、输出标签、退出码和失败计数。至少圈出：
   - 请求 0 服务中请求 1 到达时的 `抢占`；
   - 同 rank 请求 2 到达时的 `不抢占`；
   - `mask_all=1` 期间三个请求保持 pending；
   - 完成高资格请求后 `返回 -> 恢复`；
   - 非法 ID 返回 `IRQ_FAKE_ERR_ID`。
4. 改变一个 `priority_rank`，先预测输出，再运行检查。写下这是模型排序的变化，不是 STM32 优先级编码实验。
5. 把 `irq_fake_finish_current()` 暂时改为不清除 `active` 或不减少 `active_depth`，观察为什么返回链会失真；恢复代码后再记录结论。

本次运行没有主机编译、测试或上板记录，所以课程元数据不填 `hardware_evidence`，`hardware_verified=false`。

### 12.2 通用 STM32 迁移步骤

得到具体开发板、调试器、MCU 型号和 Cube 固件版本后：

1. 保存型号、封装、工具链和固件包版本。
2. 先读 Armv7-M 架构手册，标出异常优先级、pending/active、抢占和返回的架构语义。[1]
3. 再读该系列 Reference Manual、Datasheet 和适用的编程手册；F4 主线可从 PM0214 开始，但不能把 F4 细节外推到 F7、H5、H7。[2]
4. 对照 HAL/LL 版本和生成工程，确认配置参数、优先级分组和 IRQ 入口；没有版本资料时写“待核对”。
5. 用调试器观察配置和状态，必要时用 GPIO 标记、事件时间戳或逻辑分析仪测量服务顺序和相对延迟。
6. 将“资料结论、构建证据、调试观察、测量结果”分别记录；任何缺失项都不能由 Host Fake 补足。

## 13. 自检题

1. 多个 pending 请求为什么需要可比较的规则？请用本模型的 `priority_rank` 和同 rank 的 ID 规则回答。
2. 为什么本课不把“rank=0”直接写成某个 STM32 的优先级寄存器值？
3. `pending=1`、`active=1` 和线程态分别表示什么？它们能否同时在不同请求上成立？
4. 低 rank 的请求在高 rank 请求服务期间到达时，模型发生了哪些状态变化？
5. 屏蔽期间到达的请求为什么没有立即进入 active？解除屏蔽后发生什么？
6. 为什么 `irq_fake_service_current()` 不直接承担 `finish/return`？
7. 同级请求在本模型中为什么不抢占？这能否当作所有 Cortex-M/STM32 的事实？
8. 列出 Host Fake 能证明的两点和不能证明的两点，并说明 `hardware_verified` 为什么仍为 `false`。

## 14. 面试题

1. **问：优先级数字越小是否一定表示优先级越高？**
   **答题要点：** 不能脱离架构和实现资料回答。应区分逻辑排序、字段编码方向、有效位宽和优先级分组；本课的数值仅是 Host Fake 的约定。

2. **问：一个低优先级 ISR 执行时，新的请求会发生什么？**
   **答题要点：** 请求先形成 pending；再根据服务资格、屏蔽和当前 active 判断。资格更高时可能抢占，资格不足时保持 pending，当前服务返回后才可能继续选择。

3. **问：pending 和 active 有什么区别？**
   **答题要点：** pending 是已记录、未完成服务的请求状态；active 是服务上下文正在执行或处于嵌套活动链中的状态，不能互换。

4. **问：为什么要记录“服务”和“清除/完成”两个观察点？**
   **答题要点：** 进入服务代码不自动证明请求状态已经被目标硬件清除；清除语义、读写顺序和副作用需查具体参考手册。

5. **问：如何验证一个优先级问题，而不是猜寄存器？**
   **答题要点：** 先固定 MCU、手册和软件版本，查架构与系列实现，再用构建产物、调试状态、时间戳或测量证据闭环；主机模型只验证抽象逻辑。

## 15. 延伸思考

1. 如果一个请求在自己 active 期间再次到达，本课的单个 pending 位会发生什么？真实器件可能有哪些不同语义？你需要查哪一类资料？
2. 如果把模型改成允许同 rank 抢占，需要新增哪条比较规则？这会如何改变 active 栈和返回顺序？
3. 如果屏蔽只阻止选择但不阻止 pending 置位，解除屏蔽瞬间可能出现怎样的服务突发？目标系统如何用证据确认这一点？
4. 对 F4、F7、H5、H7 迁移时，哪些结论可以从 Arm 架构层复用，哪些必须回到系列手册和 HAL/LL 版本？
5. 将来的 Device Framework（设备框架）BSP 组装层应如何表达“请求源、优先级配置、服务入口和清除责任”，才能让 Host Fake 替换真实外设而不改变应用测试？本问题留到驱动架构阶段，不在本课实现。

## 16. 本节总结

本课建立了两条心智模型：第一，多个中断请求需要可比较的逻辑优先级规则来决定服务顺序；第二，抢占、pending、active 和返回后的继续执行是分开的状态转换。Host Fake 用静态请求表和活动栈把这些状态写成可观察输出，同时明确声明它不模拟真实 Cortex-M/NVIC 的寄存器、异常入口、栈帧、时序或硬件延迟。

阅读真实 STM32 工程时，应沿着“请求到达 -> pending -> 选择 -> 服务/抢占 -> 完成/清除 -> 返回”的链条逐点找证据，先确认架构规则，再核对系列实现，最后用构建、调试和测量验证。没有具体型号和证据时，不填写寄存器地址、优先级位宽、复位值、IRQ 名称或 HAL 签名。

## 17. 下一步

下一课应在本阶段继续处理另一个独立外设机制，或按复习结果补强本课的 Host Fake 与调试证据。不要把本课的生成、阅读或主机模型输出当作掌握度更新；掌握度只能依据学习者的自检答案、实验记录或复习结果改变。

## 18. 参考资料

1. Arm，*Armv7-M Architecture Reference Manual*，DDI 0403，当前使用 `latest` 链接；用于核对异常优先级、pending/active、抢占与返回的一般架构边界。它不能单独证明任一 STM32 的优先级位宽、分组复位值、IRQ 名称或 HAL 行为。访问日期：2026-10-05。URL：<https://developer.arm.com/documentation/ddi0403/latest/>。
2. STMicroelectronics，*STM32F3 and STM32F4 series Cortex-M4 programming manual*，PM0214；用于 F4 主线 Cortex-M4 编程资料范围内的 NVIC/SCB 和异常控制边界。当前未固定修订版，不能把其中实现细节外推到 F7、H5 或 H7。访问日期：2026-10-05。URL：<https://www.st.com/resource/en/programming_manual/pm0214-stm32f3-and-stm32f4-series-cortexm4-programming-manual-stmicroelectronics.pdf>。

以上来源均来自 `config/source-policy.toml` 允许的第一方域名。目标系列 Reference Manual、Datasheet 和匹配 Cube 固件包的 HAL/LL 文档因没有具体型号和版本，留待硬件迁移时补充，不在本课猜测。

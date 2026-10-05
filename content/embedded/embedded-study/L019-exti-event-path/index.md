+++
title = "EXTI 外部事件如何变成可服务请求：从 Host Fake 到资料核对"
date = "2026-10-04T16:00:04+08:00"
lastmod = "2026-10-04T16:00:04+08:00"
summary = "把 EXTI 理解为外部输入经线路映射、触发条件和屏蔽后形成可观察请求，并由 pending 持有到服务和显式清除；Host Fake 只验证逻辑状态转换，不代表真实 STM32 寄存器、中断入口或上板结果。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 19
tags = ["exti", "external-interrupt", "source-mapping", "edge-trigger", "pending", "mask-enable", "host-fake", "c11", "beginner"]
source_ids = ["st-stm32-mcu-portal", "arm-ddi0403-latest"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L019"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 19 课：EXTI 外部事件如何变成可服务请求

输入脚上的电平发生变化，为什么不等于中断服务例程（ISR，Interrupt Service Routine）已经执行？如果事件发生在服务代码之前，它会不会丢失？服务代码为什么还要显式确认或清除？

本课只推进计划中的两条核心机制：

1. **外部事件经线路映射与使能形成可屏蔽的中断请求**。
2. **边沿检测产生可持有的挂起状态，服务后需要显式确认/清除**。

先在普通 Windows 主机上运行一个静态 C11 子集 Host Fake（主机伪实现），观察输入采样、请求形成、挂起、服务和清除的区别；再把这条逻辑链迁移到具体 STM32 的资料核对流程。Host Fake 不访问真实地址、不模拟电压、异常入口、时序或 NVIC（Nested Vectored Interrupt Controller，嵌套向量中断控制器）优先级，所以本文不声称已经构建、下载或上板验证。

## 1. 本节目标

本课核心目标与计划一致：

> 学习者能把 EXTI（External Interrupt/Event Controller，外部中断/事件控制器）理解为“外部输入经过线路映射、触发条件和屏蔽配置后形成可观察的请求；触发结果进入可持有的挂起状态，由服务代码读取并显式确认/清除”，并能用 Host Fake 判断一次或多次事件在配置、触发、挂起、服务和清除各阶段的状态变化。

完成后应能：

- 解释为什么“输入变化”“形成请求”“处理器进入 ISR”“清除 pending（挂起）”是不同观察点；
- 在模型中指出线路来源、触发配置、屏蔽状态、当前输入样本、pending、服务次数和清除次数分别在哪里定义、由谁持有；
- 运行或检查一个不使用动态内存的 C11 Host Fake，覆盖映射缺失、屏蔽、边沿不匹配、重复事件、服务不清除和非法线路等分支；
- 把 Host Fake 的结果与真实 STM32 的 Reference Manual（参考手册）、Datasheet（数据手册）和 HAL/LL 文档区分开；
- 面向 F4、F7、H5、H7 使用同一条“确认型号和版本 -> 查源映射与 pending 语义 -> 收集构建/调试/测量证据”的方法。

本课不推进中断优先级、定时器、UART、DMA、RTOS 或驱动架构。NVIC、ISR、去抖和电平触发只作为理解流程所需的辅助术语。

## 2. 它解决什么问题

GPIO 输入路径只能告诉软件“当前采样值是什么”。事件机制还要回答另一个问题：**某次变化是否值得被记录为一个可服务请求，以及软件是否已经处理过它**。

如果没有线路映射，系统不知道哪个输入源驱动哪条逻辑线；如果没有触发选择，系统不知道上升、下降还是其他变化算事件；如果没有 mask/enable（屏蔽/使能），软件无法暂时阻止请求进入服务路径；如果没有 pending，事件发生与服务执行之间就没有可观察的持有状态；如果没有显式 clear/acknowledge（清除/确认），服务代码无法表明“这次请求已经处理”。

因此不要把下列说法混在一起：

- “引脚从低变高”是输入变化，不是 ISR 已执行的证据；
- “pending 置位”是控制逻辑记录请求，不是处理器已经完成服务；
- “服务函数被调用”不必然代表 pending 已清除；具体芯片可能有独立的读取、确认或清除语义，必须查手册；
- “清除了模型中的 pending”只证明模型状态转换，不证明任何 STM32 寄存器写法。

本课把实际问题拆成一条可观察链：

```text
外部输入样本
    -> 线路来源是否匹配
    -> 边沿是否匹配
    -> 请求是否被屏蔽
    -> pending 是否置位并保持
    -> 服务代码是否观察到请求
    -> 服务后是否显式清除
```

## 3. 必要前置知识

只把 `config/learning-state.toml` 的 `completed` 中已有主题当作前置：

1. C 基本对象、固定宽度整数、指针、`const`/`volatile`、存储期和链接关系；能读懂简单结构体和状态变量。
2. 编译器、构建产物和静态分析的基本证据意识；知道主机程序可以用退出码和文本输出验证逻辑。
3. 启动、链接脚本、ELF/map 与存储器布局的基本证据意识；知道外设地址和异常入口必须由目标资料核对。
4. GPIO：知道输入采样是外部状态进入软件可见状态的前置环节，但 GPIO 读值不自动等于 EXTI pending。

本课不假定已经掌握具体 STM32 型号、EXTI 线路编号、端口到线路的选择表、寄存器地址、HAL/LL 函数签名、IRQ 名称、NVIC 优先级、开发板连线或示波器操作。

## 4. 核心原理

### 4.1 先看最小状态转换

假设有一条逻辑线，来源已经映射为 `source=3`，只启用上升沿且没有屏蔽，初始样本为低：

```text
配置：source=3, rising=1, falling=0, masked=0, last=LOW, pending=0

输入 LOW -> LOW       没有边沿，pending 仍为 0
输入 LOW -> HIGH      上升沿匹配，请求形成，pending 变为 1
服务一次               service_count 增加，pending 仍为 1
显式清除               clear_count 增加，pending 回到 0
```

这里至少有四个时刻：输入变化、请求形成、服务、清除。服务和清除被刻意分开，正是为了避免把“进入服务代码”误写成“请求状态已经消失”。

### 4.2 两条核心机制的对象边界

| 机制 | 解决的问题 | 对象在哪里定义 | 谁持有状态 | 谁建立或注入 | 调用/数据如何流动 |
| --- | --- | --- | --- | --- | --- |
| 线路映射与使能形成可屏蔽请求 | 多个潜在输入中，哪些变化可以进入请求通路 | 真实目标：参考手册的线路选择、触发和屏蔽字段；Host Fake：`exti_fake_line_t` | EXTI 控制逻辑；Host Fake 由 `exti_fake_controller_t` 持有 | 真实工程由初始化代码建立；Host Fake 由 `exti_fake_configure()` 写入 | 输入样本 -> 来源/边沿匹配 -> 未屏蔽时形成请求 |
| 边沿检测产生可持有 pending，服务后显式清除 | 让事件在“发生”和“服务”不同步时仍可被观察和确认 | 真实目标：pending 状态和清除语义待按型号核对；Host Fake：`last_sample`、`pending`、计数器 | EXTI 线的请求状态；Host Fake 由每条线持有 | 输入采样更新 `last_sample`；服务函数观察；清除函数显式修改 | 匹配事件 -> pending=1 -> service -> clear -> pending=0 |

“注入”在本课只是测试动作：测试代码把一个已知逻辑样本传给 Host Fake。它不是后续驱动架构课程中的依赖注入（Dependency Injection）模式。

### 4.3 线路映射、触发和屏蔽不是同一个状态

可以把一条 EXTI 线抽象为：

```text
source mapping     选择哪个输入源
trigger selection  选择哪种变化算事件
mask/enable        决定事件能否进入请求通路
pending            记录已经形成但尚未清除的请求
```

四者不能互相替代。屏蔽只改变“是否形成可服务请求”的路径；它不应被描述成清除了之前已经存在的 pending，除非具体器件手册明确规定了这种副作用。Host Fake 按这个保守边界建模：配置屏蔽不会自动修改既有 pending。

### 4.4 声明、实现、实例化、组装和使用

虽然本课不是架构课，仍把代码中的五个动作分开，避免把模型对象和真实外设混为一谈：

1. **声明**：定义 `exti_fake_line_t`、`exti_fake_controller_t`、状态码和函数原型。
2. **实现**：实现线路越界检查、配置校验、边沿判断、pending 置位、服务计数和清除。
3. **实例化**：`main` 中的 `static exti_fake_controller_t controller` 是一个主机模型实例，不是 STM32 外设地址。
4. **组装**：`exti_fake_init()` 建立线数量，`exti_fake_configure()` 将来源、触发和屏蔽写入指定线路。
5. **使用**：测试代码注入样本，检查请求结果，调用服务和清除并打印状态。

真实 STM32 工程中的寄存器字段、IRQ 入口和 HAL/LL 调用顺序不能由这五步的函数名推断，必须按具体型号和软件包版本核对。

## 5. 关键术语与直观模型

| 术语 | 本课中的准确含义 |
| --- | --- |
| EXTI | External Interrupt/Event Controller，外部中断/事件控制器；把选定输入变化转换为可配置请求的控制逻辑。不同 STM32 系列的线路数量和字段组织待核对。 |
| external interrupt line | 外部中断线；连接一个来源选择与请求状态的逻辑编号，不等同于 GPIO 封装管脚号。 |
| source mapping | 源映射；选择哪个输入源驱动某条逻辑线。 |
| edge trigger | 边沿触发；检测上升、下降或双边沿变化。采样与同步细节待核对。 |
| level trigger | 电平触发；按电平保持条件建立请求的对比模型。本课不假定目标 EXTI 一定支持它。 |
| mask/enable | 屏蔽/使能；允许或阻止新检测事件进入请求通路，不等同于清除既有 pending。 |
| pending | 挂起；已检测并被状态逻辑保存的请求。合并、排队或清除写法必须按型号核对。 |
| acknowledge/clear | 确认/清除；服务代码对请求状态作出的显式处理动作。 |
| ISR | Interrupt Service Routine，中断服务例程；处理器已经进入服务路径后执行的代码。 |
| NVIC | Nested Vectored Interrupt Controller，嵌套向量中断控制器；Cortex-M 处理器侧的请求分发部分，优先级留待后课。 |
| Host Fake | 主机伪实现；用静态数据结构模拟逻辑状态，不模拟寄存器、电压、异常入口或时序。 |

状态关系可以压缩为：

```text
输入样本(t-1) --与输入样本(t)比较--> 边沿结果
       |                                  |
       +---- 更新 last_sample            +--来源匹配、触发匹配、未屏蔽
                                                  |
                                                  v
                                            pending = 1
                                                  |
                                  service_count += 1（不自动清除）
                                                  |
                                            clear -> 0
```

## 6. 从输入到结果的完整流程

### 6.1 Host Fake 的调用流

1. `main` 持有静态控制器对象，记录可用线路数量。
2. `exti_fake_init()` 将所有线路置为未配置、无 pending、计数器为零。
3. `exti_fake_configure()` 检查线路、来源、触发位和初始样本，再建立配置状态。
4. `exti_fake_sample()` 接收一个新样本，比较前后值，更新 `last_sample`。
5. 如果边沿、来源和屏蔽条件都满足，函数把 `pending` 置为 1，并通过输出参数告诉测试“这次形成了请求”。
6. `exti_fake_service()` 只观察 pending 并增加服务次数；它不代替清除动作。
7. `exti_fake_clear()` 在 pending 存在时显式清零并增加清除次数；重复清除返回确定错误。

### 6.2 真实 STM32 的核对流

```text
具体 MCU/封装/软件包版本
    -> Reference Manual：确认线路来源、触发、mask 和 pending 语义
    -> Datasheet：确认引脚、输入条件和复用限制
    -> HAL/LL 文档与生成工程：确认 API 参数、IRQ 处理和版本差异
    -> 构建产物/调试器：观察配置是否进入目标
    -> 必要时用逻辑分析仪：观察真实输入变化和响应时序
```

没有具体 MCU 时，不写寄存器地址、位名、IRQ 名称或函数签名。Arm 的架构手册可以帮助理解处理器侧异常/中断的一般边界，但不能证明某颗 STM32 的 EXTI 线路和清除规则。[2]

### 6.3 一次事件与多次事件

本模型使用一个 `pending` 位，因此在清除前再次发生匹配边沿时，状态仍然是 1；它不会自动变成“排队了两个事件”。测试仍可以通过输入日志和 `service_count` 观察发生了几次服务动作。真实器件是合并、计数、丢失还是具有其他语义，必须以目标参考手册为准，不能从这个 Host Fake 外推。

## 7. 嵌入式系统中的对应位置

### 7.1 GPIO 与 EXTI 的边界

GPIO 负责把外部引脚状态带入输入采样路径；EXTI 进一步观察选定的变化并形成请求。一个输入读值可以是 `HIGH`，但如果没有正确源映射、触发配置或请求使能，仍然可能没有 pending。反过来，pending=1 也不告诉你当前引脚仍保持触发电平，因为它记录的是过去检测到的请求。

### 7.2 F4、F7、H5、H7 的可迁移方法

跨系列可迁移的是证据方法：

```text
确认型号和资料版本
  -> 查来源映射与触发字段
  -> 查 mask/pending 的读写和清除语义
  -> 对照 HAL/LL 版本和生成工程
  -> 用构建、调试和测量证据验证事件链
```

F4、F7、H5、H7 可能在线路组织、端口映射、寄存器布局、清除规则和软件包版本上不同。当前没有型号和资料版本，本文不列系列差异表，也不把任意系列的字段名称外推到其他系列。

### 7.3 复位、时钟和异常入口的边界

真实工程可能需要先满足外设时钟、GPIO 输入配置、系统异常使能和启动代码的条件；处理器还可能通过向量表和 NVIC 进入 ISR。这些步骤的具体先后、寄存器和 API 不属于本课目标，且必须从目标工程和第一方文档核对。Host Fake 只验证请求状态逻辑，不模拟这些硬件前提。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 能证明什么

- 未配置线路、无效触发位和越界线路会返回确定错误；
- 来源已配置且边沿匹配、未屏蔽时，输入变化会把 pending 置为 1；
- 被屏蔽的匹配边沿不会形成新请求；
- 服务动作可以被单独计数，且在模型中不会自动清除 pending；
- 有效清除会把 pending 变回 0，重复清除返回确定错误；
- 重复匹配边沿在未清除前保持同一个 pending 状态，模型没有隐含事件队列。

### 8.2 Host Fake 不能证明什么

- 不能证明任何 STM32 EXTI 寄存器的地址、位宽、复位值、写 1 清除或其他写法；
- 不能证明某个 GPIO 管脚能映射到某条 EXTI 线；
- 不能证明输入同步、亚稳态、边沿最小脉宽、抖动、响应延迟或 NVIC 优先级；
- 不能证明 ISR 真的从向量表进入，也不能证明清除动作与处理器异常返回的时序；
- 不能证明主机输出等于真实电压、波形或电气安全性。

## 9. 最小代码示例

下面的完整代码是课程逻辑模型，使用静态存储、固定宽度整数和确定错误码，不使用动态内存或函数指针。它是“示例，待目标构建与上板验证”。将代码保存为 `exti_fake.c` 后，可按实验部分给出的命令尝试在普通 Windows 主机上构建；本文没有预先声称该命令已经运行。

### 9.1 完整 Host Fake

```c
#include <stdint.h>
#include <stdio.h>

#define EXTI_FAKE_MAX_LINES (4U)
#define EXTI_FAKE_SOURCE_NONE (UINT8_MAX)

typedef uint8_t exti_fake_level_t;
typedef uint8_t exti_fake_trigger_t;
typedef int32_t exti_fake_status_t;

#define EXTI_FAKE_LOW  ((exti_fake_level_t)0U)
#define EXTI_FAKE_HIGH ((exti_fake_level_t)1U)

#define EXTI_FAKE_TRIGGER_NONE   ((exti_fake_trigger_t)0U)
#define EXTI_FAKE_TRIGGER_RISING ((exti_fake_trigger_t)1U)
#define EXTI_FAKE_TRIGGER_FALLING ((exti_fake_trigger_t)2U)
#define EXTI_FAKE_TRIGGER_BOTH ((exti_fake_trigger_t)3U)

#define EXTI_FAKE_OK              ((exti_fake_status_t)0)
#define EXTI_FAKE_ERR_ARGUMENT    ((exti_fake_status_t)-1)
#define EXTI_FAKE_ERR_LINE        ((exti_fake_status_t)-2)
#define EXTI_FAKE_ERR_SOURCE      ((exti_fake_status_t)-3)
#define EXTI_FAKE_ERR_TRIGGER     ((exti_fake_status_t)-4)
#define EXTI_FAKE_ERR_LEVEL       ((exti_fake_status_t)-5)
#define EXTI_FAKE_ERR_UNCONFIGURED ((exti_fake_status_t)-6)
#define EXTI_FAKE_ERR_NOT_PENDING ((exti_fake_status_t)-7)

typedef struct {
    uint8_t configured;
    uint8_t source;
    exti_fake_trigger_t trigger;
    uint8_t masked;
    exti_fake_level_t last_sample;
    uint8_t pending;
    uint32_t service_count;
    uint32_t clear_count;
} exti_fake_line_t;

typedef struct {
    uint8_t line_count;
    exti_fake_line_t lines[EXTI_FAKE_MAX_LINES];
} exti_fake_controller_t;

static int exti_fake_valid_level(exti_fake_level_t level)
{
    return (level == EXTI_FAKE_LOW) || (level == EXTI_FAKE_HIGH);
}

static int exti_fake_valid_trigger(exti_fake_trigger_t trigger)
{
    return (trigger == EXTI_FAKE_TRIGGER_RISING) ||
           (trigger == EXTI_FAKE_TRIGGER_FALLING) ||
           (trigger == EXTI_FAKE_TRIGGER_BOTH);
}

static int exti_fake_valid_line(const exti_fake_controller_t *controller,
                                uint8_t line)
{
    return (controller != NULL) && (line < controller->line_count);
}

static int exti_fake_is_rising(exti_fake_level_t old_level,
                               exti_fake_level_t new_level)
{
    return (old_level == EXTI_FAKE_LOW) && (new_level == EXTI_FAKE_HIGH);
}

static int exti_fake_is_falling(exti_fake_level_t old_level,
                                exti_fake_level_t new_level)
{
    return (old_level == EXTI_FAKE_HIGH) && (new_level == EXTI_FAKE_LOW);
}

static int exti_fake_trigger_matches(exti_fake_trigger_t trigger,
                                     exti_fake_level_t old_level,
                                     exti_fake_level_t new_level)
{
    const int rising = exti_fake_is_rising(old_level, new_level);
    const int falling = exti_fake_is_falling(old_level, new_level);

    if ((trigger == EXTI_FAKE_TRIGGER_RISING) && rising) {
        return 1;
    }
    if ((trigger == EXTI_FAKE_TRIGGER_FALLING) && falling) {
        return 1;
    }
    return (trigger == EXTI_FAKE_TRIGGER_BOTH) && (rising || falling);
}

static exti_fake_status_t exti_fake_init(exti_fake_controller_t *controller,
                                         uint8_t line_count)
{
    uint8_t line;

    if ((controller == NULL) ||
        (line_count == 0U) ||
        (line_count > EXTI_FAKE_MAX_LINES)) {
        return EXTI_FAKE_ERR_ARGUMENT;
    }

    controller->line_count = line_count;
    for (line = 0U; line < EXTI_FAKE_MAX_LINES; ++line) {
        controller->lines[line].configured = 0U;
        controller->lines[line].source = EXTI_FAKE_SOURCE_NONE;
        controller->lines[line].trigger = EXTI_FAKE_TRIGGER_NONE;
        controller->lines[line].masked = 1U;
        controller->lines[line].last_sample = EXTI_FAKE_LOW;
        controller->lines[line].pending = 0U;
        controller->lines[line].service_count = 0U;
        controller->lines[line].clear_count = 0U;
    }
    return EXTI_FAKE_OK;
}

static exti_fake_status_t exti_fake_configure(
    exti_fake_controller_t *controller,
    uint8_t line,
    uint8_t source,
    exti_fake_trigger_t trigger,
    uint8_t masked,
    exti_fake_level_t initial_sample)
{
    exti_fake_line_t *state;

    if (!exti_fake_valid_line(controller, line)) {
        return EXTI_FAKE_ERR_LINE;
    }
    if ((source == EXTI_FAKE_SOURCE_NONE) || (source > 31U)) {
        return EXTI_FAKE_ERR_SOURCE;
    }
    if (!exti_fake_valid_trigger(trigger)) {
        return EXTI_FAKE_ERR_TRIGGER;
    }
    if (!exti_fake_valid_level(initial_sample)) {
        return EXTI_FAKE_ERR_LEVEL;
    }

    state = &controller->lines[line];
    state->configured = 1U;
    state->source = source;
    state->trigger = trigger;
    state->masked = (masked != 0U) ? 1U : 0U;
    state->last_sample = initial_sample;
    state->pending = 0U;
    state->service_count = 0U;
    state->clear_count = 0U;
    return EXTI_FAKE_OK;
}

static exti_fake_status_t exti_fake_sample(exti_fake_controller_t *controller,
                                            uint8_t line,
                                            uint8_t source,
                                            exti_fake_level_t new_sample,
                                            uint8_t *request_formed)
{
    exti_fake_line_t *state;
    int matches;

    if (request_formed == NULL) {
        return EXTI_FAKE_ERR_ARGUMENT;
    }
    *request_formed = 0U;
    if (!exti_fake_valid_line(controller, line)) {
        return EXTI_FAKE_ERR_LINE;
    }
    if (!exti_fake_valid_level(new_sample)) {
        return EXTI_FAKE_ERR_LEVEL;
    }

    state = &controller->lines[line];
    if (state->configured == 0U) {
        return EXTI_FAKE_ERR_UNCONFIGURED;
    }

    matches = (source == state->source) &&
              exti_fake_trigger_matches(state->trigger,
                                         state->last_sample,
                                         new_sample);
    state->last_sample = new_sample;

    if (matches && (state->masked == 0U)) {
        state->pending = 1U;
        *request_formed = 1U;
    }
    return EXTI_FAKE_OK;
}

static exti_fake_status_t exti_fake_service(exti_fake_controller_t *controller,
                                             uint8_t line,
                                             uint8_t *serviced)
{
    exti_fake_line_t *state;

    if (serviced == NULL) {
        return EXTI_FAKE_ERR_ARGUMENT;
    }
    *serviced = 0U;
    if (!exti_fake_valid_line(controller, line)) {
        return EXTI_FAKE_ERR_LINE;
    }

    state = &controller->lines[line];
    if (state->configured == 0U) {
        return EXTI_FAKE_ERR_UNCONFIGURED;
    }
    if (state->pending == 0U) {
        return EXTI_FAKE_OK;
    }
    state->service_count += 1U;
    *serviced = 1U;
    return EXTI_FAKE_OK;
}

static exti_fake_status_t exti_fake_clear(exti_fake_controller_t *controller,
                                           uint8_t line)
{
    exti_fake_line_t *state;

    if (!exti_fake_valid_line(controller, line)) {
        return EXTI_FAKE_ERR_LINE;
    }
    state = &controller->lines[line];
    if (state->configured == 0U) {
        return EXTI_FAKE_ERR_UNCONFIGURED;
    }
    if (state->pending == 0U) {
        return EXTI_FAKE_ERR_NOT_PENDING;
    }
    state->pending = 0U;
    state->clear_count += 1U;
    return EXTI_FAKE_OK;
}

static void exti_fake_print(const exti_fake_controller_t *controller,
                            uint8_t line,
                            const char *label,
                            exti_fake_status_t status,
                            uint8_t request_formed,
                            uint8_t serviced)
{
    const exti_fake_line_t *state = &controller->lines[line];

    printf("%-18s status=%ld request=%u pending=%u service=%lu clear=%lu\n",
           label,
           (long)status,
           (unsigned)request_formed,
           (unsigned)state->pending,
           (unsigned long)state->service_count,
           (unsigned long)state->clear_count);
    if (serviced != 0U) {
        printf("  service action observed; pending remains until clear\n");
    }
}

int main(void)
{
    static exti_fake_controller_t controller;
    uint8_t request_formed;
    uint8_t serviced;
    exti_fake_status_t status;

    status = exti_fake_init(&controller, 2U);
    printf("init status=%ld\n", (long)status);

    status = exti_fake_configure(&controller, 0U, 3U,
                                 EXTI_FAKE_TRIGGER_RISING, 0U,
                                 EXTI_FAKE_LOW);
    printf("configure line0 status=%ld\n", (long)status);

    status = exti_fake_sample(&controller, 0U, 3U,
                              EXTI_FAKE_LOW, &request_formed);
    exti_fake_print(&controller, 0U, "same level", status,
                    request_formed, 0U);

    status = exti_fake_sample(&controller, 0U, 3U,
                              EXTI_FAKE_HIGH, &request_formed);
    exti_fake_print(&controller, 0U, "rising edge", status,
                    request_formed, 0U);

    status = exti_fake_service(&controller, 0U, &serviced);
    exti_fake_print(&controller, 0U, "service", status,
                    0U, serviced);

    status = exti_fake_clear(&controller, 0U);
    exti_fake_print(&controller, 0U, "clear", status, 0U, 0U);

    status = exti_fake_configure(&controller, 1U, 4U,
                                 EXTI_FAKE_TRIGGER_RISING, 1U,
                                 EXTI_FAKE_LOW);
    printf("configure masked line1 status=%ld\n", (long)status);
    status = exti_fake_sample(&controller, 1U, 4U,
                              EXTI_FAKE_HIGH, &request_formed);
    exti_fake_print(&controller, 1U, "masked rising", status,
                    request_formed, 0U);

    status = exti_fake_sample(&controller, 0U, 3U,
                              EXTI_FAKE_LOW, &request_formed);
    status = exti_fake_sample(&controller, 0U, 3U,
                              EXTI_FAKE_HIGH, &request_formed);
    status = exti_fake_sample(&controller, 0U, 3U,
                              EXTI_FAKE_LOW, &request_formed);
    status = exti_fake_sample(&controller, 0U, 3U,
                              EXTI_FAKE_HIGH, &request_formed);
    exti_fake_print(&controller, 0U, "repeated before clear", status,
                    request_formed, 0U);

    status = exti_fake_clear(&controller, 0U);
    exti_fake_print(&controller, 0U, "second clear", status, 0U, 0U);
    status = exti_fake_clear(&controller, 0U);
    exti_fake_print(&controller, 0U, "repeat clear", status, 0U, 0U);

    status = exti_fake_configure(&controller, 7U, 1U,
                                 EXTI_FAKE_TRIGGER_RISING, 0U,
                                 EXTI_FAKE_LOW);
    printf("invalid line status=%ld\n", (long)status);
    return 0;
}
```

### 9.2 代码阅读要点

- `exti_fake_line_t` 持有一条线路的全部模型状态；`controller` 持有线路数组和有效数量。
- `exti_fake_configure()` 是配置建立者，负责来源、触发、屏蔽和初始样本；它不是硬件寄存器写入的替代证明。
- `exti_fake_sample()` 只在“来源相同、边沿匹配、未屏蔽”时置 pending；无论是否形成请求，都会更新 `last_sample`，这样下一次边沿判断有确定基准。
- `exti_fake_service()` 只增加 `service_count`，保留 pending；这让服务和清除的责任边界可观察。
- `exti_fake_clear()` 需要已有 pending，重复清除返回 `EXTI_FAKE_ERR_NOT_PENDING`。
- `main` 中重复上升沿在清除前仍只显示一个 pending 位，说明模型选择的是合并语义；不要把它外推为所有 STM32 的硬件语义。

## 10. 常见错误

### 错误 1：把 GPIO 读高当作 EXTI 已触发

GPIO 读值只是一个采样结果。还要检查来源是否映射到该线路、边沿是否匹配、请求是否被屏蔽以及 pending 是否已经被清除。

### 错误 2：把 mask 当成 clear

屏蔽新请求和清除已有 pending 是两个不同动作。本课模型中，重新屏蔽不会偷偷抹掉已经置位的 pending；真实器件是否有副作用必须查手册。

### 错误 3：服务函数返回就认为 pending 消失

服务代码可能只是读取和处理请求。除非目标资料明确说明自动清除，否则要把确认/清除写成单独步骤并观察结果。

### 错误 4：把线路号当作封装管脚号

线路是逻辑编号，封装管脚是器件物理引出。映射表、复用限制和可用性由具体型号资料决定。

### 错误 5：从 Host Fake 推断写 1 清除等寄存器规则

Host Fake 的 `exti_fake_clear()` 是教学模型 API。真实目标可能使用读改写、写特定值或其他语义，不能凭模型函数名猜测。

### 错误 6：把重复事件说成一定排队

本模型只有一个 pending 位，因此重复事件可能被合并。是否计数、排队或丢失是硬件契约问题，必须取得对应参考手册证据。

## 11. 调试观察点

按下列顺序观察，能快速定位“输入变化但没有可服务请求”的原因：

1. **输入样本**：记录前一次和当前采样，确认确实发生了上升或下降；主机模型用 `last_sample`，硬件需要调试器或测量设备证据。
2. **来源映射**：确认测试/工程使用的来源与线路配置一致，不要只看 GPIO 端口名。
3. **触发选择**：确认所需边沿已启用；边沿不匹配时 pending 不应改变。
4. **屏蔽状态**：确认新请求没有被 mask；注意屏蔽不自动等于清除。
5. **pending**：在服务入口前后分别记录状态，区分“尚未服务”“已服务但未清除”和“已清除”。
6. **服务次数与清除次数**：如果服务次数增加而 pending 仍为 1，这是本模型预期的边界；如果清除次数增加但仍有新边沿，说明需要检查下一次事件，而不是把它当成清除失败。
7. **真实工程的证据分层**：构建日志证明代码进入目标，调试寄存器窗口证明某次观察到的寄存器状态，逻辑分析仪证明引脚时间波形；三者不能互相替代。

## 12. 实战实验

### 实验 A：主机最小路径

1. 将第 9 节代码保存为 `exti_fake.c`。
2. 使用已有 C11 编译器执行类似命令：

   ```text
   cc -std=c11 -Wall -Wextra -pedantic exti_fake.c -o exti_fake
   .\exti_fake.exe
   ```

   具体编译器名称和输出文件后缀以本机环境为准；本课没有预先记录构建成功证据。
3. 把输出按“输入变化 -> request -> pending -> service -> clear”五列抄成表格。
4. 检查 `service action observed` 行：服务计数增加，但 pending 仍为 1。

### 实验 B：覆盖边界分支

修改 `main` 或另写测试调用，至少验证：

- 来源不匹配：样本发生边沿但 `request_formed=0`；
- 下降沿不匹配上升沿配置：pending 不新增；
- masked=1：匹配边沿也不形成新请求；
- 未配置线路：返回 `EXTI_FAKE_ERR_UNCONFIGURED`；
- 非法线路号：返回 `EXTI_FAKE_ERR_LINE`；
- 重复清除：第一次有效，第二次返回 `EXTI_FAKE_ERR_NOT_PENDING`；
- 清除前重复匹配边沿：pending 仍为 1，不能声称模型排队了两个请求。

实验记录至少写出每次调用的输入、返回码、pending、服务次数和清除次数。只要没有目标板、下载和测量记录，实验结论都属于 Host Fake 逻辑验证，不能把 `hardware_verified` 改为 `true`。

### 实验 C：通用 STM32 迁移清单

取得具体 MCU、开发板、调试器和 Cube 固件包版本后，按此顺序填写待核对项：

1. 目标型号、封装和资料修订版；
2. GPIO 输入与 EXTI 线路来源映射表；
3. 上升/下降触发字段和屏蔽字段；
4. pending 的读取、确认和清除语义；
5. 对应 HAL/LL 版本的初始化、IRQ 处理和清除 API；
6. 构建日志、断点/寄存器窗口观察；
7. 若要证明物理边沿，再记录逻辑分析仪的连线、采样率和时间戳。

在资料缺失时保留“待核对”，不要用 F4 的字段替代 H5 或 H7 的字段。

## 13. 自检题

1. 为什么“输入从低变高”不等于“ISR 已执行”？请至少说出两个中间状态。
2. `source mapping`、`trigger`、`mask` 和 `pending` 各自解决什么问题？
3. 在本 Host Fake 中，服务后为什么 pending 仍然为 1？这是一条模型约定还是所有芯片的事实？
4. 如果来源不匹配但边沿匹配，`last_sample` 是否更新？为什么这样设计有助于下一次边沿判断？
5. 为什么重复事件在清除前不能被描述为“排队了两个事件”？
6. 线路号为什么不能直接当作 GPIO 封装管脚号？
7. 哪些结论可以由主机输出证明，哪些必须查具体参考手册或做物理测量？
8. 没有具体开发板时，为什么课程仍然可以学习 EXTI 的请求生命周期？

参考答案应回到状态表和调用流，而不是背寄存器名称。

## 14. 面试题

1. **输入边沿发生但中断没有进入，如何分层排查？** 期望按采样、源映射、触发、屏蔽、pending、处理器入口顺序给出证据，而不是直接改 ISR。
2. **为什么 pending 与当前引脚电平不能互相替代？** 期望说明 pending 是已检测请求的持有状态，当前电平是另一个采样时刻的状态。
3. **服务函数是否应该自动清除 pending？** 期望回答“由硬件契约决定；若没有明确证据，应把服务与清除分开建模并记录”，而不是给出无来源的统一规则。
4. **一个 pending 位遇到两次边沿会怎样？** 期望区分模型的合并语义与真实芯片可能存在的计数/丢失/其他语义，并说明需要查手册。
5. **Host Fake 测试通过后，为什么仍不能说 STM32 EXTI 已验证？** 期望列出寄存器、映射、电气、异常入口和时序等未覆盖证据。
6. **如何设计一个能迁移到 F4、F7、H5、H7 的 EXTI 适配步骤？** 期望强调先确认型号和版本，再建立来源、触发、mask、pending 的证据链，不复制某系列地址。

## 15. 延伸思考

1. 如果要把一个 pending 位扩展为事件计数器，哪些行为需要先定义？计数溢出如何观察？
2. 如果服务期间又到来一个边沿，模型应如何表达“旧请求已服务、新请求仍待处理”？这会不会需要两个时间点或计数状态？
3. 如何把输入抖动、最小脉宽和同步延迟加入模型，同时不把逻辑模型冒充成电气仿真？
4. 如果某系列把多个 GPIO 来源共享到一条逻辑线，BSP（Board Support Package，板级支持包）应在哪里记录资源占用冲突？
5. 调试器看到 pending 已清除但 ISR 又立即执行，哪些硬件和时序资料需要核对？
6. 在未来的 Device Framework 中，如何让 BSP 只组装来源和线路配置，而不让 App 直接依赖具体寄存器字段？本题只做思考，不提前引入函数指针或依赖注入实现。

## 16. 本节总结

EXTI 的可迁移模型不是某个寄存器地址，而是一条请求生命周期：

```text
输入样本
  -> 来源映射
  -> 边沿/触发匹配
  -> mask/enable 决定是否形成请求
  -> pending 持有请求
  -> 服务代码观察并处理
  -> 显式确认/清除
```

检查任何“外部变化没有得到预期响应”的问题时，依次问：

- 线路来源在哪里定义，谁持有，谁建立？
- 上一次样本和当前样本是否真的形成所需边沿？
- 触发配置与来源是否匹配？新请求是否被屏蔽？
- pending 是尚未置位、已置位未服务、已服务未清除，还是已清除后又被新事件置位？
- 结论来自 Host Fake、构建/调试观察，还是已经有目标手册和物理测量支持？

当前没有具体开发板、交叉构建、下载、调试或测量记录，因此 `lesson.json` 保持 `hardware_verified=false`；生成本课也不提高 mastery。

## 17. 下一步

先完成实验 A、B，并能不看正文说明：

1. 为什么 GPIO 输入变化和 EXTI 请求是两层状态；
2. 来源映射、触发选择、屏蔽和 pending 的责任边界；
3. 为什么服务与清除必须在模型中分开观察；
4. Host Fake、第一方资料、构建日志、调试窗口和测量设备各自能证明什么。

下一主题按 curriculum 进入中断优先级时，再讨论多个请求如何由处理器侧分发；不要把优先级规则提前塞回本课。

## 18. 参考资料

[1] STMicroelectronics, *STM32 32-bit Arm Cortex MCUs*，官方器件资料入口页；版本未单独标注，访问日期 2026-10-04。该页面用于说明应从具体型号资料进入 Reference Manual、Datasheet 和软件包文档；它不单独证明任意 STM32 的 EXTI 字段、映射或清除规则。
https://www.st.com/en/microcontrollers-microprocessors/stm32-32-bit-arm-cortex-mcus.html

[2] Arm, *Armv7-M Architecture Reference Manual*, DDI 0403，官方在线入口，`latest` 修订版未在本次运行中固定为具体发布日期，访问日期 2026-10-04。该资料只用于处理器侧异常/中断一般边界；它不替代具体 STM32 Reference Manual，也不证明 EXTI 线路或寄存器语义。
https://developer.arm.com/documentation/ddi0403/latest/

本课没有使用来源政策之外的博客或第三方完整源码。具体 STM32 型号、EXTI 线路映射、寄存器地址、HAL/LL API、清除写法和电气时序均保留为“待核对”。

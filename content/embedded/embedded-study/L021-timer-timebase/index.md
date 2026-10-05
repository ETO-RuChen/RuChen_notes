+++
title = "定时器时间基准与观察路径：从 Host Fake 到 STM32 资料核对"
date = "2026-10-05T17:02:39+08:00"
lastmod = "2026-10-05T17:02:39+08:00"
summary = "建立可迁移的定时器时间基准模型：学习者能从时钟、计数器和周期边界推导更新事件，并区分轮询、定时器中断与输出观察路径；能用 Host Fake 验证事件间隔和计数边界，但不把主机结果当作 STM32 硬件时序证据。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 21
tags = ["timer", "timebase", "counter", "prescaler", "update-event", "polling", "interrupt", "output-compare", "host-fake", "c11", "beginner"]
source_ids = ["st-an4776", "arm-ddi0403-latest"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L021"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 21 课：定时器时间基准与观察路径

软件为什么需要定时器（timer，按输入时钟推进计数并在条件满足时产生事件的外设）？因为“执行一段空循环”并不是稳定的时间基准：编译优化、等待的外设、时钟配置和中断都会改变循环花费的时间。本课先把问题收缩成一个可以在 Windows 主机上观察的离散模型，再说明迁移到 STM32 时哪些结论必须回到参考手册、编程手册和构建/测量证据。

本课只推进计划中的两个核心概念：

1. **定时器把时钟驱动的计数过程转换为可预测的离散时间事件**：它解决软件需要稳定时间基准而不能依赖忙等循环或主机墙钟的问题。模型中显式持有输入时钟、分频后的计数节拍、当前计数值、周期边界和事件标志；配置者建立分频与周期参数，定时器状态机推进计数并产生更新事件，观察者再读取标志或消费事件。实际频率公式、计数方向、边界是否包含端点及寄存器语义必须以目标系列资料核对。
2. **同一计数状态可通过轮询、更新中断或输出比较等不同观察路径暴露给软件与外部引脚**：它解决“同一时间基准如何服务不同消费者”的问题。定时器拥有计数和事件状态，应用或驱动选择观察路径；轮询由调用者读取状态，中断路径经控制器交给 ISR，输出比较路径由外设通道改变输出状态。三者共享时间来源但具有不同延迟、清除责任和证据边界，不能把某一路径的行为泛化为全部硬件行为。

## 1. 本节目标

本课核心目标与本次计划逐字一致：

> 建立可迁移的定时器时间基准模型：学习者能从时钟、计数器和周期边界推导更新事件，并区分轮询、定时器中断与输出观察路径；能用 Host Fake 验证事件间隔和计数边界，但不把主机结果当作 STM32 硬件时序证据。

完成后应能：

- 解释为什么输入时钟、分频后的计数节拍、当前计数值和周期边界必须分别建模；
- 根据本课明确的端点规则，手算若干输入时钟推进后的计数和更新事件；
- 区分“事件已经产生”“轮询读到标志”“中断请求已置位”“输出比较已改变状态”；
- 阅读一个无动态内存、使用固定宽度整数的 C11 Host Fake，并指出对象定义、状态持有、配置建立和调用流；
- 说明主机实验能证明什么、不能证明什么，以及迁移到 F4、F7、H5、H7 时应该查什么资料。

本课不推进 PWM、输入捕获、编码器、DMA、RTOS、驱动架构或具体型号的寄存器清单。预分频、自动重装载、更新事件、输出比较和 ISR 只作为理解本课两个核心概念的辅助术语；目标器件的字段、时钟树、清除语义和 API 版本均需核对。

## 2. 它解决什么问题

忙等循环只能描述“CPU 做了多少次循环”，不能稳定描述“经过了多少时间”。例如同一段 C 代码在不同优化级别、不同主频、插入日志或被中断打断后，循环次数与实际时间的关系会改变。定时器的可迁移模型把问题拆成四个可观察对象：

```text
输入时钟 -> 分频 -> 计数节拍 -> 当前计数值 -> 周期边界
                                              |
                                              +-> 更新事件/标志
                                              +-> 中断请求
                                              +-> 输出比较观察
```

这里的“可预测”不是指真实芯片一定没有误差，而是指：给定模型输入和端点规则，同一组输入会得到同一组离散事件。模型可以帮助我们检查边界推导和软件责任；它不能替代目标芯片的时钟误差、总线规则、IRQ 延迟或引脚电气波形测量。

必须区分以下事实：

| 观察 | 只说明什么 | 不能直接推出什么 |
| --- | --- | --- |
| 输入时钟推进 | 模型收到若干个时钟单位 | STM32 某条总线实际给定时器的频率 |
| 计数值改变 | 已产生一个或多个计数节拍 | 芯片真实计数方向、对齐方式或寄存器位宽 |
| 更新标志置位 | 本模型跨过了周期边界 | 目标器件所有更新源和清除副作用 |
| ISR 请求置位 | 本模型把更新事件转成了请求 | Cortex-M 异常入口和响应延迟 |
| 输出状态翻转 | 本模型的比较阈值命中 | 外部引脚的电平、驱动能力和波形质量 |

## 3. 必要前置知识

只把 `config/learning-state.toml` 的 `completed` 项视为已掌握前置：

1. C 基本对象、固定宽度整数、指针、`const`/`volatile`、存储期和链接关系；能阅读简单结构体、数组和状态变量。
2. 知道编译器、构建产物和静态分析提供的是证据，不把主机输出自动升级成硬件结论。
3. 了解启动、向量表、异常入口、链接和存储器布局的边界，知道架构行为要查资料。
4. GPIO：配置动作和数据观察动作不同，外部状态必须有明确观察路径。
5. EXTI：输入变化可以形成待处理事件，产生、挂起、服务和清除不是同一个动作。
6. 中断优先级：多个请求会竞争服务机会，pending、active、抢占和返回是不同状态；本课只把定时器更新事件接到“请求形成”这一边界。

不假定你已经知道某个 STM32 型号的定时器编号、时钟树倍频规则、预分频有效位宽、自动重装载端点、更新标志名称、IRQ 名称、HAL/LL 函数签名或具体 Cube 固件版本。

## 4. 核心原理

### 4.1 核心机制一：时钟驱动的计数转换为离散时间事件

**它解决什么问题？** 它把“过了多长时间”变成可以被软件复核的计数边界，而不是依赖 CPU 忙等的偶然耗时。

**对象在哪里定义？** 在本课 Host Fake 中，`timer_fake_t` 定义并持有 `input_hz`、`prescaler_div`、`prescaler_phase`、`period_ticks`、`counter`、`update_pending` 和 `update_count`。这些字段是模型对象，不是某个 STM32 外设寄存器的布局。

**谁持有它？** `static timer_fake_t timer` 由测试程序持有整个生命周期；模型内部状态只由 `timer_fake_*` 函数修改。真实硬件的计数值和标志由定时器外设持有，软件只能通过目标资料规定的访问路径观察或清除。

**谁建立它？** `timer_fake_init()` 建立初始状态，`timer_fake_configure()` 写入输入频率、分频和周期。真实系统中的配置者通常是初始化代码或生成代码，但具体时钟选择、预分频字段和自动重装载语义当前都待按目标系列资料核对。

**调用如何流动？** 测试代码注入输入时钟；分频阶段累积到边界后产生一个计数节拍；计数器推进；跨过周期边界时计数归零、更新标志置位并累计事件数。轮询者之后可以读取并清除标志。

本课的模型约定是：`prescaler_div` 表示“需要多少个输入时钟才产生一个计数节拍”；`period_ticks` 表示一个周期包含多少个计数节拍；计数器取值范围为 `0` 到 `period_ticks - 1`。每个计数节拍先把计数器推进一个位置，若原值已经是 `period_ticks - 1`，则本节拍跨过边界并把计数器回到 0。这个端点规则只属于模型，不能直接当作任意 STM32 定时器的公式。

如果模型使用 `prescaler_div=2`、`period_ticks=3`，输入时钟的观察可以写成：

```text
输入 1：分频阶段 1/2，计数不变
输入 2：产生计数节拍，0 -> 1
输入 4：产生计数节拍，1 -> 2
输入 6：产生计数节拍，2 -> 0，并产生更新事件
```

### 4.2 核心机制二：同一计数状态的三条观察路径

**它解决什么问题？** 一个时间基准可能同时服务低频主循环、需要及时响应的服务代码和外部测量。轮询、中断和输出比较应该共享事件来源，但不应混淆它们的延迟、清除责任和证据范围。

**对象在哪里定义？** 模型中，轮询使用 `update_pending`；中断路径使用 `interrupt_enabled` 和 `isr_pending`；输出比较使用 `compare_enabled`、`compare_tick`、`compare_pending` 和 `output_state`。这些字段都属于同一个 `timer_fake_t`。

**谁持有它？** 定时器模型持有“事件是否发生”的状态；调用者持有轮询读取的结果；模型只把更新事件转换为一个布尔 ISR 请求，不模拟真实异常栈或处理器时序；输出状态是模型里的可观察变量，不等于真实 GPIO 电平。

**谁建立它？** `timer_fake_enable_interrupt()` 和 `timer_fake_configure_compare()` 建立观察配置。真实工程需要由外设初始化、控制器配置和 ISR 代码共同组装；具体寄存器字段、IRQ 映射、清除顺序和 HAL/LL 函数签名待核对。

**调用如何流动？**

```text
计数边界 -> update_pending=1
          -> 若中断已启用，则 isr_pending=1 -> ISR（目标系统）
          -> 若调用者轮询，则 take_update() 读取并清除标志

计数值命中 compare_tick -> compare_pending=1、output_state 翻转
                          -> 轮询者可读取比较标志
                          -> 真实目标可能还有通道输出路径，必须查手册
```

本课把 `isr_pending` 作为“请求已形成”的终点，不把 `timer_fake_service_isr()` 的调用伪装成真正的 Cortex-M 异常入口。这样可以复用上一课的 pending 边界，同时保持证据诚实。

### 4.3 声明、实现、实例化、组装和使用

本课不是架构课程，但代码仍按五个动作阅读：

1. **声明**：定义 `timer_fake_t`、状态码、初始化/推进/观察函数原型；接口只暴露固定宽度整数和确定错误码。
2. **实现**：实现参数校验、分频阶段、计数边界、更新事件、轮询清除、中断请求和比较命中。
3. **实例化**：`main` 中的 `static timer_fake_t timer` 分配一个主机模型对象，不是外设基地址。
4. **组装**：测试代码依次调用初始化、周期配置、中断开关和比较配置，把状态机组装成一个场景。
5. **使用**：测试代码推进输入时钟、读取计数、轮询标志、服务模型 ISR 请求并观察输出状态。

这五个动作帮助定位责任：配置代码建立规则，定时器状态机产生事件，观察者决定如何消费事件。它们不意味着真实 STM32 必然有同名函数或同样的清除时序。

## 5. 关键术语与直观模型

| 术语 | 本课中的准确含义 |
| --- | --- |
| timer | 定时器；按输入时钟推进计数并在条件满足时产生事件的外设。 |
| clock source | 时钟源；驱动计数的输入来源，具体来自哪条总线或内部源待核对。 |
| prescaler | 预分频器；把输入时钟转换为计数节拍的配置部件。 |
| counter | 计数器；保存当前计数位置的状态字段或寄存器。 |
| auto-reload | 自动重装载；定义周期边界或下一轮计数起点的配置概念，字段语义待核对。 |
| update event | 更新事件；模型中表示跨过周期边界的事件类别，真实触发条件待核对。 |
| polling | 轮询；调用者主动读取标志或计数状态。 |
| ISR | Interrupt Service Routine，中断服务例程；处理已形成请求的代码入口。 |
| output compare | 输出比较；计数值命中比较值后产生软件或通道观察动作的路径。 |
| tick | 节拍；一次离散计数推进或累计的离散时间单位。 |
| period | 周期；重复更新事件之间包含的计数节拍数（本模型定义）。 |
| frequency | 频率；单位时间内重复事件的次数，真实换算需核对时钟与边界规则。 |
| Host Fake | 主机伪实现；用静态 C11 状态机验证已定义逻辑，不模拟寄存器、电气波形或硬件时钟误差。 |

可以把 `timer_fake_t` 想成一只带刻度的机械计数盒：输入时钟推动盒内的分频轮，分频轮积满后推动计数轮；计数轮转到边界时举起“更新”旗帜。旗帜可以被主循环看到，也可以变成一个待服务请求；另一根比较指针在计数轮到达指定刻度时改变输出状态。

## 6. 从输入到结果的完整流程

### 6.1 一个完整周期

假设模型配置为 `prescaler_div=2`、`period_ticks=4`，初始 `counter=0`：

```text
输入时钟 1：phase=1，counter=0
输入时钟 2：phase=0，产生节拍，counter=1
输入时钟 4：产生节拍，counter=2
输入时钟 6：产生节拍，counter=3
输入时钟 8：产生节拍，跨边界，counter=0，update_pending=1
```

所以在本模型里，一个更新事件需要 `2 * 4 = 8` 个输入时钟。这个乘法只说明模型的离散单位；真实芯片还可能有时钟树倍频、计数方向、重装载更新时机、触发源和其他配置影响，不能只拿这行乘法外推。

### 6.2 连续多个周期和轮询漏读

如果调用者在 8 个输入时钟后没有读取更新标志，又推进 16 个输入时钟，模型会产生三次更新事件：`update_count=3`，但 `update_pending` 仍然只是一个置位的布尔标志。此时调用一次 `timer_fake_take_update()` 只能得到“一次有事件”，并清除这个标志；它不会凭空返回三条事件记录。

这是轮询路径的重要边界：标志位表示“至少有一次事件尚未被观察”，不是通用事件队列。目标定时器是否合并、覆盖、计数或提供额外状态，必须查该器件手册。

### 6.3 更新事件到 ISR 请求

启用模型中断后，每次跨周期边界都会把 `isr_pending` 置为 1。`timer_fake_service_isr()` 只做两件事：确认请求存在、清除模型请求并增加服务计数。它没有执行异常入口、保存寄存器、判断优先级或测量延迟。

```text
更新事件 -> update_pending=1
         -> interrupt_enabled=1
         -> isr_pending=1
         -> 调用者决定何时 service_isr()
         -> isr_pending=0，isr_service_count 加一
```

因此“更新事件已产生”和“ISR 已运行”之间仍有一段路径。上一课的中断优先级模型可以在这个边界之后继续讨论请求如何竞争服务机会，但本课不重新展开优先级编码或异常时序。

### 6.4 输出比较命中

模型规定每次计数推进完成后，如果新的 `counter` 等于 `compare_tick`，则 `compare_pending=1` 并翻转 `output_state`。例如周期为 4、比较值为 2 时，每一轮从 1 推进到 2 都命中一次；回到 0 的更新事件不会自动等于比较命中，除非比较值被配置为 0。

这只是便于观察的 Host Fake 规则。真实输出比较可能连接到通道输出、产生匹配标志或触发其他事件，比较寄存器何时生效、边界值如何处理、输出模式如何选择，都要回到目标系列资料。

### 6.5 三条路径的责任对照

| 路径 | 事件状态由谁持有 | 谁触发观察 | 谁负责清除/消费 | 主要证据 |
| --- | --- | --- | --- | --- |
| 轮询 | 定时器的更新标志 | 主循环调用读取函数 | 读取函数清除模型标志 | 返回值、计数快照、日志 |
| 更新中断 | 定时器标志 + 模型请求位 | 更新事件形成请求，调用者服务 | ISR 服务函数清除模型请求；真实清除语义待核对 | 请求/服务计数、调试入口 |
| 输出比较 | 比较标志 + 输出状态 | 计数值命中阈值 | 比较读取函数或目标通道规则 | 输出状态、外部时间戳或测量 |

不能因为轮询读到了标志，就声称 ISR 也已经运行；也不能因为模型输出状态翻转，就声称某个 STM32 引脚已经输出同样波形。

## 7. 嵌入式系统中的对应位置

### 7.1 从时钟树到应用观察

在一个真实 STM32 工程中，建议按以下责任链阅读：

```text
时钟配置 -> 定时器计数节拍 -> 计数器推进 -> 更新/比较条件
                                      |             |
                              标志/请求形成       通道输出或标志
                                      |
                              轮询或 ISR 消费
```

“时钟配置”可能由系统初始化和外设时钟使能共同决定；“请求形成”还要经过中断控制器的资格判断；“通道输出”可能需要 GPIO 复用和电气连接。这些都是不同观察点，不应该被一句“启动定时器”合并。

### 7.2 F4、F7、H5、H7 的可迁移方法

可迁移的是证据顺序，而不是寄存器数字：

1. 先固定 MCU、封装、板卡、调试器和 Cube 固件版本；
2. 查该系列 Reference Manual（参考手册）和 Datasheet，确认定时器时钟源、总线规则、计数边界、预分频/自动重装载字段、更新/比较标志和清除语义；
3. 若要讨论 Cortex-M 异常请求，再用 Arm 架构资料核对 pending、active、异常入口和返回的一般边界；
4. 对照匹配版本的 HAL/LL 文档和生成工程，确认初始化、启动、标志清除和回调 API；
5. 用构建产物、寄存器窗口、断点、GPIO 时间戳或逻辑分析仪核对配置和周期；
6. 分开记录“资料结论”“Host Fake 结论”“构建证据”“调试/测量证据”。

F4、F7、H5、H7 可能在定时器实例、时钟域、总线倍频、寄存器组织、软件包版本和调试可见性上不同。当前没有具体器件，不能把任一系列的时钟频率、字段位宽、IRQ 名称或 HAL 签名外推到其他系列。

### 7.3 与前置 GPIO/EXTI/中断优先级的连接

- GPIO 提供“外部状态如何被观察”的前置模型；本课的输出比较只提供一个外部观察边界，不声称已完成引脚复用配置。
- EXTI 说明“变化如何形成请求”；本课把更新事件接到同样的请求形成概念，但不代替具体定时器到 IRQ 的实现资料。
- 中断优先级说明“多个请求如何竞争服务”；本课只负责产生一个模型 `isr_pending`，不重讲优先级排序。

这样可以保持每课一个主要机制：本课关注时间基准和观察路径，不跳到外设型号清单或 RTOS 节拍语义。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 能证明什么

- 给定 `prescaler_div`、`period_ticks` 和输入时钟序列，计数和更新事件序列是确定的；
- 周期边界的端点规则在代码中明确且可手算；
- 多个周期未及时轮询时，更新次数和单个标志位的差异可观察；
- 更新事件可以被模型转换为 ISR 请求，并由服务函数清除；
- 比较阈值命中可以改变模型输出状态；
- 非法参数返回确定错误码，不访问越界对象。

### 8.2 Host Fake 不能证明什么

- 不能证明真实 STM32 的时钟树、总线倍频、计数频率、预分频公式或自动重装载语义；
- 不能证明某个定时器编号、寄存器地址、字段位宽、复位值、更新源或 IRQ 名称；
- 不能证明 Cortex-M 异常入口、优先级、ISR 延迟、抖动、尾链或栈行为；
- 不能证明输出状态等于真实 GPIO 电平、通道波形、引脚复用或电气测量；
- 不能证明 HAL/LL 函数签名、清除顺序或 Cube 生成工程行为。

因此本课的 `hardware_verified` 必须保持 `false`。生成课程、阅读代码和执行逻辑推理都不会提高 mastery（掌握度）；只有学习者答案、实验记录或复习结果才可以推动掌握度。

### 8.3 通用 STM32 迁移步骤

拿到具体板卡后，保留以下证据链：

1. 记录 MCU 型号、封装、板卡、调试器、工具链和 Cube 固件版本。
2. 阅读匹配的 Reference Manual、Datasheet 和必要的编程手册；把“时钟源、分频、周期、更新、比较、清除、IRQ”逐项记入核对表。
3. 对照 HAL/LL 文档和生成工程，确认调用参数、启动顺序和回调入口；版本不明时标为“待核对”。
4. 构建工程并保存完整命令、工具版本、退出码和产物路径；没有记录就不要声称构建成功。
5. 用调试器观察计数/标志，必要时用 GPIO 时间戳或逻辑分析仪测量重复事件；把测量值与模型单位分开记录。
6. 只有在有目标构建、调试或测量证据时，才把对应结论升级为硬件证据；本课生成时没有这些记录。

## 9. 最小代码示例

下面是一份完整的、面向普通 Windows 主机的 C11 子集 Host Fake。它故意使用静态存储、固定宽度整数和确定错误码；没有动态内存、函数指针、真实异常指令或未定义的数组访问。代码中的 `input_hz` 只用于记录模型输入单位，模型推进函数接收的是“输入时钟个数”，不读取主机墙钟。

### 9.1 声明层

```c
#include <stdint.h>
#include <stdio.h>

#define TIMER_FAKE_OK             ((int32_t)0)
#define TIMER_FAKE_ERR_ARGUMENT   ((int32_t)-1)
#define TIMER_FAKE_ERR_CONFIG     ((int32_t)-2)
#define TIMER_FAKE_ERR_NO_EVENT   ((int32_t)-3)
#define TIMER_FAKE_ERR_NO_REQUEST ((int32_t)-4)

typedef struct {
    uint32_t input_hz;          /* 仅是模型的输入单位说明。 */
    uint32_t prescaler_div;     /* 输入时钟数 -> 一个计数节拍。 */
    uint32_t prescaler_phase;
    uint32_t period_ticks;      /* 本模型周期包含的计数节拍数。 */
    uint32_t counter;           /* 0 .. period_ticks - 1。 */

    uint8_t update_pending;
    uint32_t update_count;

    uint8_t interrupt_enabled;
    uint8_t isr_pending;
    uint32_t isr_service_count;

    uint8_t compare_enabled;
    uint32_t compare_tick;
    uint8_t compare_pending;
    uint8_t output_state;
} timer_fake_t;

static int32_t timer_fake_init(timer_fake_t *timer);
static int32_t timer_fake_configure(
    timer_fake_t *timer,
    uint32_t input_hz,
    uint32_t prescaler_div,
    uint32_t period_ticks);
static int32_t timer_fake_enable_interrupt(
    timer_fake_t *timer,
    uint8_t enabled);
static int32_t timer_fake_configure_compare(
    timer_fake_t *timer,
    uint8_t enabled,
    uint32_t compare_tick);
static int32_t timer_fake_advance_input(
    timer_fake_t *timer,
    uint32_t input_clocks);
static int32_t timer_fake_take_update(timer_fake_t *timer);
static int32_t timer_fake_service_isr(timer_fake_t *timer);
static int32_t timer_fake_take_compare(timer_fake_t *timer);
```

### 9.2 实现层

```c
static int32_t timer_fake_init(timer_fake_t *timer)
{
    if (timer == NULL) {
        return TIMER_FAKE_ERR_ARGUMENT;
    }
    *timer = (timer_fake_t){0};
    return TIMER_FAKE_OK;
}

static int32_t timer_fake_configure(
    timer_fake_t *timer,
    uint32_t input_hz,
    uint32_t prescaler_div,
    uint32_t period_ticks)
{
    if (timer == NULL) {
        return TIMER_FAKE_ERR_ARGUMENT;
    }
    if ((input_hz == 0U) || (prescaler_div == 0U) ||
        (period_ticks == 0U)) {
        return TIMER_FAKE_ERR_CONFIG;
    }
    timer->input_hz = input_hz;
    timer->prescaler_div = prescaler_div;
    timer->period_ticks = period_ticks;
    timer->prescaler_phase = 0U;
    timer->counter = 0U;
    timer->update_pending = 0U;
    timer->update_count = 0U;
    timer->isr_pending = 0U;
    timer->isr_service_count = 0U;
    timer->compare_pending = 0U;
    timer->output_state = 0U;
    return TIMER_FAKE_OK;
}

static int32_t timer_fake_enable_interrupt(
    timer_fake_t *timer,
    uint8_t enabled)
{
    if (timer == NULL) {
        return TIMER_FAKE_ERR_ARGUMENT;
    }
    timer->interrupt_enabled = (enabled != 0U) ? 1U : 0U;
    if ((timer->interrupt_enabled == 0U) &&
        (timer->isr_pending != 0U)) {
        timer->isr_pending = 0U;
    }
    return TIMER_FAKE_OK;
}

static int32_t timer_fake_configure_compare(
    timer_fake_t *timer,
    uint8_t enabled,
    uint32_t compare_tick)
{
    if (timer == NULL) {
        return TIMER_FAKE_ERR_ARGUMENT;
    }
    if ((enabled != 0U) &&
        ((timer->period_ticks == 0U) ||
         (compare_tick >= timer->period_ticks))) {
        return TIMER_FAKE_ERR_CONFIG;
    }
    timer->compare_enabled = (enabled != 0U) ? 1U : 0U;
    timer->compare_tick = compare_tick;
    timer->compare_pending = 0U;
    return TIMER_FAKE_OK;
}

static void timer_fake_one_tick(timer_fake_t *timer)
{
    uint8_t crossed_boundary = 0U;

    if (timer->counter >= (timer->period_ticks - 1U)) {
        timer->counter = 0U;
        crossed_boundary = 1U;
    } else {
        timer->counter += 1U;
    }

    (void)printf("[计数] counter=%lu\\n",
                 (unsigned long)timer->counter);

    if (crossed_boundary != 0U) {
        (void)printf("[边界判断] crossed=1\\n");
        timer->update_pending = 1U;
        timer->update_count += 1U;
        (void)printf("[事件产生] update count=%lu\\n",
                     (unsigned long)timer->update_count);
        if (timer->interrupt_enabled != 0U) {
            timer->isr_pending = 1U;
            (void)printf("[事件产生] isr_request=1\\n");
        }
    }

    if ((timer->compare_enabled != 0U) &&
        (timer->counter == timer->compare_tick)) {
        timer->compare_pending = 1U;
        timer->output_state ^= 1U;
        (void)printf("[事件产生] compare output=%u\\n",
                     (unsigned int)timer->output_state);
    }
}

static int32_t timer_fake_advance_input(
    timer_fake_t *timer,
    uint32_t input_clocks)
{
    uint32_t i;

    if (timer == NULL) {
        return TIMER_FAKE_ERR_ARGUMENT;
    }
    if ((timer->prescaler_div == 0U) || (timer->period_ticks == 0U)) {
        return TIMER_FAKE_ERR_CONFIG;
    }

    (void)printf("[时钟推进] input_clocks=%lu\\n",
                 (unsigned long)input_clocks);

    for (i = 0U; i < input_clocks; ++i) {
        timer->prescaler_phase += 1U;
        if (timer->prescaler_phase >= timer->prescaler_div) {
            timer->prescaler_phase = 0U;
            timer_fake_one_tick(timer);
        }
    }
    return TIMER_FAKE_OK;
}

static int32_t timer_fake_take_update(timer_fake_t *timer)
{
    if (timer == NULL) {
        return TIMER_FAKE_ERR_ARGUMENT;
    }
    if (timer->update_pending == 0U) {
        return TIMER_FAKE_ERR_NO_EVENT;
    }
    timer->update_pending = 0U;
    (void)printf("[观察/清除] update\\n");
    return TIMER_FAKE_OK;
}

static int32_t timer_fake_service_isr(timer_fake_t *timer)
{
    if (timer == NULL) {
        return TIMER_FAKE_ERR_ARGUMENT;
    }
    if (timer->isr_pending == 0U) {
        return TIMER_FAKE_ERR_NO_REQUEST;
    }
    timer->isr_pending = 0U;
    timer->isr_service_count += 1U;
    (void)printf("[观察/清除] isr service_count=%lu\\n",
                 (unsigned long)timer->isr_service_count);
    return TIMER_FAKE_OK;
}

static int32_t timer_fake_take_compare(timer_fake_t *timer)
{
    if (timer == NULL) {
        return TIMER_FAKE_ERR_ARGUMENT;
    }
    if (timer->compare_pending == 0U) {
        return TIMER_FAKE_ERR_NO_EVENT;
    }
    timer->compare_pending = 0U;
    (void)printf("[观察/清除] compare\\n");
    return TIMER_FAKE_OK;
}
```

`timer_fake_one_tick()` 是模型状态机的核心：先按照端点规则更新计数，再分别产生更新事件和比较事件。更新事件、ISR 请求和比较观察各有独立字段，所以可以观察它们不同时发生或不同时被消费。

### 9.3 实例化、组装和使用层

```c
int main(void)
{
    static timer_fake_t timer;
    int32_t status;

    status = timer_fake_init(&timer);
    if (status != TIMER_FAKE_OK) {
        return 1;
    }
    status = timer_fake_configure(&timer, 1000U, 2U, 4U);
    if (status != TIMER_FAKE_OK) {
        return 1;
    }
    status = timer_fake_enable_interrupt(&timer, 1U);
    if (status != TIMER_FAKE_OK) {
        return 1;
    }
    status = timer_fake_configure_compare(&timer, 1U, 2U);
    if (status != TIMER_FAKE_OK) {
        return 1;
    }

    /* 2 * 4 个输入时钟后跨过一次周期边界。 */
    (void)timer_fake_advance_input(&timer, 8U);
    (void)printf("counter=%lu updates=%lu update_pending=%u\\n",
                 (unsigned long)timer.counter,
                 (unsigned long)timer.update_count,
                 (unsigned int)timer.update_pending);

    if (timer_fake_take_update(&timer) == TIMER_FAKE_OK) {
        (void)printf("polling: observed update\\n");
    }
    if (timer_fake_service_isr(&timer) == TIMER_FAKE_OK) {
        (void)printf("interrupt model: serviced\\n");
    }
    if (timer_fake_take_compare(&timer) == TIMER_FAKE_OK) {
        (void)printf("compare: output=%u\\n",
                     (unsigned int)timer.output_state);
    }

    /* 再推进 16 个输入时钟，产生两个更新；不轮询就只保留一个标志位。 */
    (void)timer_fake_advance_input(&timer, 16U);
    (void)printf("events=%lu flag=%u\\n",
                 (unsigned long)timer.update_count,
                 (unsigned int)timer.update_pending);
    return 0;
}
```

这段 `main` 完成五个动作中的后三个：静态实例化、配置组装、调用使用。它只打印模型字段，不宣称任何 STM32 寄存器、IRQ 或引脚已经工作。若保存为 `timer_timebase_fake.c`，可以用已有 C11 编译器尝试：

```text
gcc -std=c11 -Wall -Wextra -pedantic timer_timebase_fake.c -o timer_timebase_fake.exe
.\\timer_timebase_fake.exe
```

这条命令是实验建议，不是本次运行的编译证据；课程元数据没有填入构建记录。

## 10. 常见错误

1. **用忙等循环当作周期公式。** 循环次数不是稳定的时间单位，应先定义输入时钟和计数边界。
2. **把输入时钟和计数节拍混为一谈。** 预分频阶段可能让多个输入时钟才产生一个计数推进；模型中由 `prescaler_phase` 明确隔开。
3. **把 `period_ticks=4` 理解成计数值一定经过 0、1、2、3、4。** 本模型取值为 0 到 3，3 到 0 时产生更新；目标硬件端点规则待核对。
4. **把更新事件和更新标志清除混为一谈。** 事件产生会置位标志；轮询读取才清除模型标志；真实清除语义必须查手册。
5. **认为 `update_count=3` 就意味着轮询一定能读到三次。** 单个布尔标志可以合并多个未读事件，本模型专门展示这一点。
6. **把 `isr_pending=1` 写成“ISR 已执行”。** 它只表示请求已经形成，服务函数何时被调用是另一动作。
7. **把输出状态翻转当作真实引脚波形。** Host Fake 没有 GPIO 复用、驱动器、电气负载或测量时间戳。
8. **凭经验写具体寄存器、IRQ 名称或 HAL 签名。** 没有 MCU、版本和官方资料时统一标为“待核对”。
9. **把模型频率直接等同于目标频率。** `input_hz / prescaler_div / period_ticks` 只在本模型的单位和端点规则下成立，不能替代时钟树核对。
10. **用未初始化的模型字段或越界比较值。** 先调用初始化和配置，检查固定错误码；不要用未定义行为“测试边界”。

## 11. 调试观察点

每个观察点都要记录来源，避免把模型打印和硬件证据混在一起：

| 观察点 | Host Fake 可观察内容 | 真实目标需要的证据 |
| --- | --- | --- |
| 时钟推进 | `advance_input()` 的输入单位和调用次数 | 时钟树配置、总线规则和实际时钟来源 |
| 分频 | `prescaler_phase` 何时归零 | 预分频字段、有效位宽和更新时机 |
| 计数 | `counter` 变化和端点回零 | 计数方向、对齐、寄存器读回和边界规则 |
| 更新 | `update_count`、`update_pending` | 参考手册的更新源、标志置位和清除语义 |
| 中断 | `isr_pending`、服务计数 | IRQ 映射、控制器状态、ISR 入口和延迟测量 |
| 比较 | `compare_pending`、`output_state` | 通道配置、复用、输出模式和示波/逻辑分析仪波形 |
| 漏读 | 多次事件对应一个未清标志 | 目标器件是否合并、覆盖、计数或提供额外状态 |

遇到“周期不对”时，按以下顺序排查：输入单位是否定义；分频阶段是否按模型推进；计数端点是否统一；事件是否产生但未被观察；观察者是否清除了标志；最后才去查目标实现的时钟树、寄存器和 API。这个顺序不能替代芯片手册，但能避免一开始就猜一个寄存器数字。

## 12. 实战实验

### 12.1 必做：Host Fake 逻辑验证

1. 将第 9 节代码保存为 `timer_timebase_fake.c`，使用本机已有的 C11 编译器；记录实际编译器版本、完整命令、退出码和输出。没有编译器时，按同样的输入序列手工记录状态转移，不声称已编译。
2. 对 `prescaler_div=2`、`period_ticks=4` 预测输入 1、2、4、6、8 个时钟后的 `counter`、`update_pending` 和 `update_count`。
3. 配置比较值 2，圈出每次 `counter` 到 2 时 `compare_pending` 和 `output_state` 的变化；说明这只是模型输出。
4. 在第一次更新后不调用 `timer_fake_take_update()`，再推进 16 个输入时钟，比较 `update_count` 与单个 `update_pending` 标志，解释“轮询漏读”。
5. 比较启用和禁用 `interrupt_enabled` 时 `isr_pending` 的差异；将 `timer_fake_service_isr()` 在没有请求时的固定错误码记下来。
6. 故意传入 `prescaler_div=0`、`period_ticks=0`、比较值等于周期的参数，确认函数返回确定错误码且没有继续推进状态。
7. 写一张证据表，至少分为“时钟推进、计数、边界判断、事件产生、观察/清除”五列，并在每行标记模型证据或硬件待核对。

实验输出只能证明本课定义的离散状态机。不要把主机运行时间、输出频率或 `output_state` 当作 STM32 周期、IRQ 延迟或引脚波形证据。

### 12.2 通用 STM32 适配练习

在获得具体 MCU 和板卡后再做以下练习：

1. 把型号、封装、调试器、Cube 固件版本写入实验记录。
2. 从该型号 Reference Manual 与 Datasheet 找到定时器时钟源、预分频、自动重装载、更新标志、比较通道和清除语义；每个结论附页码或章节位置。
3. 对照 Armv7-M 资料和匹配 HAL/LL 文档，核对“请求形成”和“ISR 服务”之间的边界；没有版本资料就写“待核对”。
4. 生成并构建最小工程，记录命令和产物；用寄存器窗口或断点观察计数与标志。
5. 若有可用引脚和逻辑分析仪，用时间戳测量周期，并与模型的计数单位分开报告。

本课没有这些硬件和测量记录，因此不会把练习写成已经完成的上板结果。

## 13. 自检题

1. 定时器模型为什么要把输入时钟、分频阶段、计数器和周期边界拆成不同字段？
2. 在本课的端点规则下，`prescaler_div=2`、`period_ticks=3` 时，输入 6 个时钟会发生什么？
3. `update_count=3` 而 `update_pending=1` 说明了什么？为什么一次轮询不能自动得到三条记录？
4. “更新事件产生”“更新标志被轮询清除”“ISR 请求被服务”分别由哪些动作表示？
5. 为什么 `isr_pending=1` 不能被写成“Cortex-M 已经进入 ISR”？
6. 输出比较路径和更新事件路径共享什么状态来源，又分别增加了什么观察状态？
7. 列出两条 Host Fake 可以证明的结论和两条不能证明的结论。
8. 没有具体开发板时，迁移定时器模型需要先向用户索取哪些信息？

## 14. 面试题

1. **问：为什么不建议用空循环实现 1 ms 定时？**  
   **答题要点：** 空循环耗时依赖编译器、主频、等待和中断；应使用可核对的时钟/计数边界。真实定时器的公式和端点仍需查目标资料。

2. **问：预分频器、计数器和自动重装载分别解决什么问题？**  
   **答题要点：** 预分频把输入时钟转成计数节拍，计数器保存当前位置，自动重装载/周期配置定义边界；具体字段和边界不能脱离系列手册回答。

3. **问：轮询和定时器中断是不是两种不同的时间来源？**  
   **答题要点：** 通常可以共享同一计数状态，区别在观察路径、延迟和清除责任；本课模型用同一更新事件分别设置标志和请求位。

4. **问：为什么一次更新事件可能没有对应一次轮询调用？**  
   **答题要点：** 标志位可能只是“至少有事件未观察”的状态，多个事件可能合并；是否计数、覆盖或保留要查具体器件。

5. **问：如何证明一个周期配置在 STM32 上真的成立？**  
   **答题要点：** 固定型号和软件版本，查时钟树/参考手册/数据手册，核对 HAL/LL 与生成工程，再用构建、调试和时间测量闭环；Host Fake 不能替代这些证据。

6. **问：输出比较和 PWM 是否等价？**  
   **答题要点：** 本课只使用“计数命中比较值”的观察模型；PWM 还涉及输出模式和持续波形配置，不在本课展开，不能由模型直接推出。

## 15. 延伸思考

1. 如果把 `update_pending` 从一个布尔位改成有限宽度事件计数器，轮询接口和溢出策略需要怎样变化？
2. 如果输入时钟在推进过程中改变，哪些字段需要重新配置，哪些历史状态应该保留？这在真实 MCU 上要查哪些时钟切换约束？
3. 如果比较值等于周期边界，模型为什么拒绝配置？目标器件是否允许等价设置，应该查哪一节手册？
4. F4、F7、H5、H7 迁移时，哪些判断可以复用“计数到事件”的方法，哪些必须重新核对时钟域、寄存器和软件版本？
5. 将来的 Device Framework 如何让应用只消费统一 tick，而把真实定时器和 Host Fake 的组装放在边界层？本问题留到驱动架构阶段，本课不实现依赖注入或组合根。

## 16. 本节总结

本课建立了两个可迁移模型：第一，定时器把输入时钟经分频后推进计数，并在周期边界产生可预测的离散更新事件；第二，同一计数状态可以通过轮询、更新中断请求或输出比较路径暴露给不同消费者。Host Fake 用静态 C11 状态机显式持有输入单位、分频阶段、计数器、周期、标志、请求和比较状态，能够验证边界、连续周期、轮询漏读和观察清除责任。

同时，模型的时间单位、端点规则和输出状态都只是主机逻辑约定。它不能证明 STM32 的时钟树、寄存器字段、IRQ、HAL/LL 签名、异常延迟或电气波形。迁移到 F4、F7、H5、H7 时，应遵循“先抽象计数与事件，再核对系列实现，最后用构建/调试/测量证据闭环”的方法，并保持 `hardware_verified=false`，直到有实际证据。

## 17. 下一步

先完成本课 Host Fake 实验并回答自检题，再根据错误类型决定是否复习 GPIO/EXTI/中断优先级的事件边界。下一阶段可以继续研究另一个外设机制，但不要把本课的生成、阅读或主机输出当作掌握度更新。只有用户答案、实验或复习结果才可以改变学习状态。

## 18. 参考资料

1. STMicroelectronics，*General-purpose timer cookbook for STM32 microcontrollers*，AN4776；用于核对通用定时器计数、更新事件、输出比较和跨系列差异。当前课程只采用其能覆盖的通用边界，不把示例器件当作学习者的目标型号。访问日期：2026-10-05。URL：<https://www.st.com/resource/en/application_note/an4776-generalpurpose-timer-cookbook-for-stm32-microcontrollers-stmicroelectronics.pdf>。
2. Arm，*Armv7-M Architecture Reference Manual*，DDI 0403 latest；仅用于核对定时器更新事件连接到 Cortex-M 异常请求时的 pending、active、异常入口和返回的一般架构边界；它不证明 STM32 的定时器寄存器、时钟或 HAL 行为。访问日期：2026-10-05。URL：<https://developer.arm.com/documentation/ddi0403/latest/>。

以上来源均来自 `config/source-policy.toml` 允许的域名，且至少包含一项 policy-primary 来源。由于没有具体 MCU、板卡和 Cube 固件版本，本课不虚构系列 Reference Manual、Datasheet、IRQ 名称、寄存器地址或 HAL/LL 签名；这些内容在硬件迁移时待核对。

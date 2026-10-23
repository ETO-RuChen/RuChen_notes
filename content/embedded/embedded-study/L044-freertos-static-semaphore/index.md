+++
title = "FreeRTOS 静态信号量：有界许可、等待与超时"
date = "2026-10-23T17:41:38+08:00"
lastmod = "2026-10-23T17:41:38+08:00"
summary = "能够用 STM32F407xx 上的静态计数信号量表示无数据载荷的有界许可，推演 give/take、计数上限、等待与超时，并区分信号量、消息队列及互斥所有权和两条验证轨道。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 44
tags = ["FreeRTOS", "静态计数信号量", "有界许可", "阻塞与超时", "STM32F407", "Host-Fake"]
source_ids = ["FREERTOS-COUNTING", "FREERTOS-STATIC-COUNTING", "FREERTOS-GIVE", "FREERTOS-TAKE", "ST-STM32CUBEF4", "ST-RM0090", "ST-DS8626", "ST-PM0214", "ST-UM1725", "ST-UM1718", "ST-ES0182", "ST-DS11532", "ST-DS14258", "ST-DS12110", "ST-STM32CUBEMX"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L044"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# L044 FreeRTOS 静态信号量：有界许可、等待与超时

阶段：`rtos-concurrency`（FreeRTOS 与并发）；主题：`semaphore`（信号量）。建议用时 60 分钟：15 分钟手推、20 分钟主机实验、20 分钟阅读目标实现、5 分钟自检。

本课固定到 **STM32F407xx、ST 打包 FreeRTOS V10.3.1、GCC ARM_CM4F 单核端口**。主机模型不是内核替身的正确性证明。目标代码是**参考实现，待目标工程编译；未烧录、未上板、未测量**；`hardware_verified=false`，课程审查状态以同目录 `lesson.json` 为准。没有假定开发板、外部晶振、外设引脚或调试器，也没有因生成课程提高掌握度。

## 1. 本节目标

核心目标与本次 `plan.json` 一致：

> 能够用 STM32F407xx 上的静态计数信号量表示无数据载荷的有界许可，推演 give/take、计数上限、等待与超时，并区分信号量、消息队列及互斥所有权和两条验证轨道。

唯一新核心概念：

> 信号量以有界许可计数表示可消费事件或资源份额；give/take 改变计数并决定任务等待，但不传递消息数据，也不表达互斥所有权。

学完应能手推最大计数 2、初始计数 0 的过程，指出满时 give、空时零等待 take 的失败；解释有限等待中的阻塞、就绪、真正执行三个时刻；找到静态控制块、句柄、任务上下文及注入位置。不要把本课当成互斥量、优先级继承或中断协议的完整课程。

## 2. 它解决什么问题

设想生产方产生“可以执行一次工作”的机会，消费方每次取走一个机会。此时只关心**还剩几次机会**，不关心机会携带哪一份数据。生产方先来两次，消费方稍后执行两次，系统应记住这两个许可；存储又不能无限增长，于是规定最多 2 个。[S1][S2]

这与 L043 的问题不同：若生产的是温度 11 和 22，消费方必须依次读到两份温度，就需要能保存消息的队列或另一个明确的数据缓冲协议。把两个温度都写入同一个 `latest_sample`，再 give 两次，最终仍只有最后一个温度；**两个许可不等于两份样本**。

本课先选“事件许可”语义：初始 0，生产时 give，消费时 take，处理完不自动归还。资源池是同一个计数模型的另一种用法：初始值可以等于资源份额数，取得资源 take，归还资源 give。但信号量本身既不记录哪一块资源被借走，也不记录谁有归还权；这些约束仍须应用协议建立。[S1][S2]

约束是：无动态内存、计数不能超过上限、每次调用必须检查结果、没有许可时不能无限空转、没有真实目标证据时不能宣称目标运行成功。

## 3. 必要前置知识

已记录前置：C 指针和静态存储期、L041 的静态任务、L042 的就绪/阻塞/节拍、L043 的按值消息队列，以及时钟树、中断优先级、主机测试。这里只回顾三点：

- 函数返回后仍被任务使用的对象，不能是已经失效的局部变量；本课控制块、任务栈和上下文均有整个程序的生存期。
- 阻塞任务暂不参与就绪任务的竞争；解除阻塞只是变为就绪，调度器仍须选择谁运行。
- `tick` 是内核节拍计数单位，等待 5 tick 不等于“从调用到返回必定恰好 5 ms”。[S4][S5]

`mutex`（互斥量）、任务通知、ISR（Interrupt Service Routine，中断服务程序）的专用 API、优先级继承都不是隐含前置；本课只给选择边界与后续落点，不要求先学会实现它们。

## 4. 核心原理

### 4.1 先看最小轨迹

`give` 表示释放一个许可，`take` 表示取得并消耗一个许可；`count` 是当前可用许可数，`maximum count` 是许可上限。[S1–S5]

| 顺序 | 输入 | 返回意义 | 调用结束后的 count |
| --- | --- | --- | --- |
| 0 | 静态创建，maximum=2、initial=0 | 得到长期有效句柄 | 0 |
| 1 | give | 成功 | 1 |
| 2 | give | 成功 | 2 |
| 3 | give | 已满，失败，不新增许可 | 2 |
| 4 | take，等待 0 tick | 成功 | 1 |
| 5 | take，等待 0 tick | 成功 | 0 |
| 6 | take，等待 0 tick | 无许可，立即失败 | 0 |

这张表假定操作之间没有另一个任务穿插，后文目标例用生产任务高于消费任务的优先级，让第一次连续三次 give 具备这个条件。不能把它外推成任意并发配置下的打印顺序。

计数守恒应写成：

```text
0 <= count <= maximum
count = initial + 成功 give 的次数 - 成功 take 的次数
```

失败的 give 不在增量里。只有当所有真实事件均成功入账、并且一项许可对应一次消费时，count 才代表尚未消费的真实事件数；忽略已满返回值会破坏这个前提。满时不是覆盖旧许可，更不是自动扩容。[S2][S3][S5]

### 4.2 空、等待、唤醒、超时

| 条件 | take 的行为 | 应用应如何解释 |
| --- | --- | --- |
| count>0 | 减 1，成功返回 | 已取得一个许可，不需要等满等待时间 |
| count=0，等待为 0 | 不阻塞，失败返回 | 此刻没有许可；不是系统故障 |
| count=0，有限等待 N tick | 进入等待；许可到来或等待到期后重新参与调度 | API 尚未返回，不能提前算一次消费 |
| 恢复执行后仍无许可且等待已到期 | 失败返回 | 本次没有取得许可，应处理超时路径 |

`xSemaphoreGive` 没有等待参数；此版本宏固定使用零阻塞时间，满了就失败。不要把“队列 send 可以等待空间”直接套到信号量 give 上。任务上下文 give/take 的应用判断使用 `pdTRUE` 成功、`pdFALSE` 失败；固定实现内部成功使用 `pdPASS`，满/空使用值为零的 `errQUEUE_FULL` / `errQUEUE_EMPTY`，这些值在 `projdefs.h` 可核对。[S3][S4][S5]

一次 give 会增加 count，必要时使等待者就绪，但**不会给该等待者预留这项许可**。固定版 `xQueueSemaphoreTake` 恢复后会再次检查计数；如果其他合法执行者先取得许可，该等待者可能继续等待，或在等待用尽时失败。它不是“被叫醒就必成功”的承诺。[S5]

另一个细节：tick 到期也只是解除阻塞，不是把失败返回值直接写进调用者。若任务真正恢复检查时已有许可，固定版本仍可能成功取得；因此不能规定“只要曾到期就绝对失败”。在无新许可的受控实验里，等待到期并恢复检查后才会返回失败。本课主机模型保留这个检查顺序，但不复制完整内核。[S5]

### 4.3 就绪与运行分开记

固定内核 `tasks.c:xTaskRemoveFromEventList` 从按优先级排序的等待链选择任务；正常事件唤醒路径比较等待者优先级是否**严格高于**当前任务。开启抢占时，高优先级等待者可能在 give 返回给生产方之前运行；低优先级等待者则通常要等更高优先级任务阻塞。相同优先级还受 tick 时间片等调度条件影响，不能承诺固定执行次序。[S5]

本课目标生产任务优先级 2、消费任务 1、Idle（空闲任务）0；这里任务优先级数值大者优先。不要混淆 NVIC（Nested Vectored Interrupt Controller，嵌套向量中断控制器）中通常数值小者更紧急的异常优先级。[S5][S8]

### 4.4 定义、持有、注入与调用

| 问题 | 本课的具体答案 |
| --- | --- |
| 对象在哪里定义 | `target/app_permits.c` 的 `static StaticSemaphore_t permit_storage` 提供控制存储；真实计数和等待链布局在固定内核 `queue.c`，不是应用自定义寄存器 |
| 谁持有 | 应用组装模块持有控制块、任务控制块、栈和两个静态上下文；内核使用这些长期有效的存储 |
| 谁实例化、谁注入 | `App_CreatePermitTasks` 调用 `xSemaphoreCreateCountingStatic` 创建对象，把返回的 `SemaphoreHandle_t`（信号量句柄）写进两个上下文，再经 `xTaskCreateStatic` 的参数传给任务 |
| 调用如何流动 | Producer/Consumer → 句柄 → `semphr.h` 宏 → `queue.c` 计数/等待链 → `tasks.c` 就绪/延时链 → 端口请求切换 → 任务继续执行 |
| 谁拥有资源 | 这里只持有“访问内核对象的句柄”；不等于拥有 UART、缓冲区或互斥锁的释放权 |

`StaticSemaphore_t` 是让应用为内核保留合适大小/对齐的静态控制存储类型，不应直接改其中字段。此包把它定义为 `StaticQueue_t` 的别名；信号量的队列项大小是 0，**没有独立消息项数组**。不要用手写 `uint8_t buffer[某个猜测大小]` 代替它。[S5]

## 5. 关键术语与直观模型

- **静态创建**：内存由应用预先提供，创建函数初始化对象，不从 FreeRTOS 堆分配；不表示对象“无需创建即可使用”。[S2][S5]
- **timeout（等待上限）**：允许等待的内核节拍数，不是“到期立刻获得 CPU”的保证；转换与真实时钟见 7.2。[S4][S5]
- **binary semaphore（二值信号量）**：本课可理解为上限为 1 的同类事件计数模型；空着时 give 一次变为 1，未被消费前再次 give 会失败。忽略失败时，多个事件在应用看来合成一次待处理状态；内核不会保存它们各自的数据。[S1][S5]
- **Host Fake（主机模拟依赖）**：用显式步骤模拟许可和一个等待者，目的是验证我们的推理和错误分支，不是运行真正的 FreeRTOS。
- **HAL（Hardware Abstraction Layer，硬件抽象层）/ LL（Low Layer，底层驱动）**：本课用于初始化/解释 STM32 时钟与内核异常，不存在 HAL 信号量 API。[S5][S9]

| 工具 | 保存什么 | 不提供什么 | 选择边界 |
| --- | --- | --- | --- |
| 本课计数信号量 | 有上限的许可数 | 消息内容、样本 FIFO（先进先出）数据顺序、互斥所有权与优先级继承 | 只需要可消费次数或资源份额 |
| L043 消息队列 | 固定大小消息项的副本 | 指针所指对象的自动生命周期管理 | 必须保留每条值或显式描述符 |
| 互斥量 | 面向任务的互斥获取/释放关系 | 本课不展开它的完整规则 | 共享资源独占和优先级继承留到 `mutex` / `priority-inversion` |

信号量控制块的“静态内存所有权”和共享资源的“互斥所有权”是两件事，不能用同一个“拥有”省略区别。[S1][S5]

## 6. 从输入到结果的完整流程

### 无等待者时

```text
真实复位 → HAL/时钟准备 → 创建 maximum=2, initial=0 的信号量
  → 创建并注入两个静态任务 → 启动调度器
  → Producer 优先运行：give 成功 → give 成功 → give 满额失败
  → Producer 延时阻塞
  → Consumer：take 成功 → take 成功 → 再 take 时计数为 0，等待
  → 没有新许可：到期就绪 → 获得 CPU → 失败返回并记录超时
```

### 有等待者时

```text
Consumer 在 count=0 时 take(5 tick)，加入等待链/延时链
  → Producer give：count 加 1，Consumer 变为就绪
  → Producer 仍有更高任务优先级，继续自己的工作
  → Producer 阻塞后，Consumer 才恢复检查并消耗一个许可
```

这里“5 tick 到期”“事件唤醒”和“任务执行”是三个独立的观察点；示例不依赖 `printf`、串口或延时循环来证明它们。程序中的统计变量供调试器观察，不是另一个任务的同步接口。[S5]

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

信号量是内核 RAM 对象，不是 STM32 外设；仍须把产生事件的硬件、时基和后续数据所有权放回系统中看。

| 层次 | 解决的问题与实际控制/数据路径 | 本课落点或后续实验 |
| --- | --- | --- |
| 基础 | 生产方 give 增加许可，消费方 take 减少许可；静态控制块不含载荷 | 本课完整实现初始 0、上限 2、0→1→2→1→0 |
| 进阶 | 已满拒绝新增；空时任务加入等待/延时链；事件或 tick 使其就绪，调度后重新检查 | 本课测试零等待、有限等待、到期、成功唤醒和就绪不等于执行 |
| 高级：速率失配 | 生产速度长期高于消费速度，有限计数终将饱和；失败 give 是损失/过载信号，不能靠无限扩大计数恢复样本数据 | 本课 `give_full` 观测；`race-condition` 后设计可审计的过载策略和缓冲协议 |
| 高级：多个等待者 | 内核事件等待链按任务优先级选择可唤醒者；被唤醒不保留许可，后续执行仍须重新检查 | 本课只解释风险；`scheduler` 机制已学，`race-condition` 后扩展多消费任务和饥饿实验，主机模型不声称支持此机制 |
| 高级：独占资源 | 许可数不记录持有者，也不替持有者提升优先级；高优先级任务等许可并不会自动提升低优先级工作者 | `mutex` / `priority-inversion` 专课落实互斥与继承；本课关闭互斥功能，不能当锁移植 |
| 高级：内存与多路等候 | 控制块、任务栈都占静态 RAM；多个事件源还需要说明谁消费哪一种事件，单一 count 不记录来源 | `memory` 核对真实 map/栈；需要多路等候时先核对官方队列集合等机制，不能靠 count 猜来源 |
| 跨外设联动 | Timer TRGO（触发输出）→ ADC（模数转换）→ DMA（直接存储器访问）→ 完成 IRQ/HAL 回调 → 合规 FromISR give → 任务 take；**样本另存在缓冲区** | `isr` 落实 ISR API、优先级、请求切换；`notification` 比较单任务事件通知；DMA 缓冲就绪/重用必须另有所有权协议 |
| 系列差异 | 内核许可模型可迁移，但异常端口、时钟、RAM/缓存/安全配置不能复制 F4 常量 | 8.2 给 F407 实现；迁移核对表逐项指出应改哪里，不把移植称为已验证 |

跨外设联动的关键不是“回调里加一个 give”这么短。要区分：触发链决定何时采样，DMA 数据链决定数据存在哪里，许可链只说明有多少次待处理机会。若 DMA 已覆盖旧缓冲区，即使还剩两个许可，也不能因此恢复两个旧数据块。UART（通用异步收发器）的 DMA 接收完成链也有同样问题；本课没有实现这些外设链。[S1][S5]

### 7.2 参考目标与时钟/复位链

**版本边界**：本次只读核对 `package.xml` 的基包 `FW.F4.1.28.0`、补丁 `FW.F4.1.28.3`；`task.h` 标记 `V10.3.1`；端口是 `portable/GCC/ARM_CM4F`。参考 RM0090 Rev 22、DS8626 Rev 12、PM0214 Rev 10、ES0182 Rev 19。它们是本次读取文件的版本，不宣称是所有网站的最新版本。[S5–S8][S11]

选从**真实复位、匹配厂商 startup/SystemInit（启动汇编/系统初始化）**进入 main 的情况，不支持任意 Bootloader 跳转后的残留状态。使用 HSI（High-Speed Internal，高速内部 RC 振荡源）的标称 16 MHz，不用 HSE（高速外部振荡源），也不用 PLL（Phase-Locked Loop，锁相环），不需要猜开发板晶振频率。[S5–S7]

```text
复位默认 HSI → HAL_Init 的启动时基
  → HSI ON，等待 HSIRDY，默认校准；PLL OFF
  → SYSCLK 源选 HSI，SW 请求 / SWS 确认
  → AHB /1：HCLK = 16 MHz，供内核/系统总线
      → APB1 /1：PCLK1 = 16 MHz
      → APB2 /1：PCLK2 = 16 MHz
      → SysTick 选 HCLK，内核 tick = 1000 Hz
           LOAD = 16000000 / 1000 - 1 = 15999
           5 tick 等待标称约 5 ms；20 tick 延时标称约 20 ms
```

`RCC`（Reset and Clock Control，复位和时钟控制）门控/复位边界：信号量没有独立 RCC 位，初始化信号量不是复位某个外设；其计数存在 RAM。SysTick 属于处理器内核，不走普通 APB 外设使能。最小例没有 UART/ADC/DMA/TIM 实例，所以没有它们的门控、复位、预分频或回调；不能编造“信号量时钟使能”。[S5][S6][S8]

本例不用普通定时器作为 HAL 时基。若后续改成 TIM 时基，F407 要重算 APB→TIM 的时钟关系：相关 APB 预分频为 1 时 TIM 时钟等于 PCLK，否则通常为对应 PCLK 的两倍；还必须配置门控/复位、PSC（预分频）、ARR（自动重装载）和 IRQ。不能把这里的 HCLK→SysTick 参数直接放进 TIM。[S6]

`SystemCoreClock` 是按时钟选择和标称源频率计算的软件值，不是实测频率。`pdMS_TO_TICKS` 此版按整数换算；在 1000 Hz 时 5 ms→5 tick、20 ms→20 tick。换为较低节拍率时小延时可能被截断为 0。连续理想 tick 下到期时刻还有约一个 tick 的相位量化误差，恢复执行还受调度影响；断点停机、中断屏蔽和 HSI 精度也影响墙钟时间，不能把失败返回当精密毫秒测量。[S4][S5][S7]

**HAL tick 与内核 tick 的单向交接**：[S5][S8]

1. 启动阶段：唯一 `SysTick_Handler` 调用 `HAL_IncTick`，让 HAL RCC 的有限等待有启动时基。固定 HAL 的 `HAL_Init` / `HAL_RCC_ClockConfig` 内部没有向外传播嵌套 `HAL_InitTick` 的失败；因此应用另显式调用并检查它。
2. 时钟准备后：关中断、暂停并关闭 SysTick、清当前计数及待处理 SysTick/PendSV，再创建静态对象；该阶段不调用需要 tick 推进的 HAL 操作。
3. 启动调度器：标记所有权交给内核，端口重新设置 SysTick，首个任务入口恢复中断；之后唯一 wrapper 只进入 `xPortSysTickHandler`。SVC（系统服务调用异常）和 PendSV（可挂起系统服务异常）由端口提供，不再生成重复实现。

**限制必须保留**：交接后 HAL 的 `uwTick` 不再推进，任务/回调中禁止 `HAL_Delay`、依赖 HAL tick 的超时操作、再次 `HAL_InitTick` 或动态改时钟。`HAL_GetTick` 也不能当运行时钟。本课选择的是最小双任务实验，不是可直接扩展所有 HAL 外设的生产级时基方案；后续外设整合应另建有版本约束的 HAL 时基，不能悄悄在同一个 SysTick 中调用两套处理者。[S5]

### 7.3 CubeMX、HAL、LL 与寄存器对照

CubeMX 是 STM32 配置/代码生成工具，CubeMX2 的实际菜单需按所用版本核对。本次读取的官方版本页缓存包含 **STM32CubeMX-Win 6.18.1**，界面文档是 UM1718 Rev 51；**未运行 GUI，未生成或声称存在 `.ioc` 工程，也未确认本机当前安装的 GUI 版本**。这张清单是新目标工程的配置要求，不是本次生成报告。[S10][S15]

| 项目 | 本课要求 | 集成时检查 |
| --- | --- | --- |
| MCU | STM32F407xx 参考；建立工程前填写真实完整料号 | 按真实封装和 Flash/RAM 容量选择 startup/linker，不能由数据手册 URL 推断板卡 |
| RCC/Clock Configuration | HSI ON、主 PLL OFF、SYSCLK=HSI、AHB/APB1/APB2 均 /1 | HCLK/PCLK1/PCLK2 标称均 16 MHz，HSE 不启用 |
| SYS/时基 | 默认启动 SysTick；不用 TIM 时基覆盖 | 不链接另一个 `HAL_InitTick` 或自动生成的 TIM 时基文件 |
| FreeRTOS 接口 | 本课用原生 API | 若工具只提供 CMSIS-RTOS（统一 RTOS 包装接口），本方案不启用该中间件生成项，而手动加入固定原生内核源；不混入 `osKernelStart` 等包装路径 |
| 静态分配 | `configSUPPORT_STATIC_ALLOCATION=1`、动态分配=0、计数信号量=1 | 不链接 `heap_1` 至 `heap_5`；任务/Idle 存储有供给；软件定时器关闭，不需 Timer 服务任务 |
| 信号量 | maximum=2、initial=0 | `permit_storage` 生命周期覆盖所有任务；不额外定义两项消息数组 |
| 任务 | Producer 优先级 2、Consumer 1、Idle 0；应用栈各 256 `StackType_t` 项 | 不是 256 字节；在 ARM_CM4F 上每项为 32 位，仍须用目标 map/水位核对实际预算 |
| tick | `configCPU_CLOCK_HZ=SystemCoreClock`、`configTICK_RATE_HZ=1000` | 32 位 TickType_t；本课不启用 tickless（抑制空闲节拍） |
| NVIC/系统异常 | Priority Group 4；SVC 优先级 0；内核设置 SysTick/PendSV 到最低逻辑优先级 15 | F407 实现 4 位优先级；本配置库阈值 5 编码为 `5<<4`。没有外设 IRQ 调内核，不能据此宣称所有 ISR 均可调用 API |
| handler 所有权 | 单一 SysTick wrapper；SVC/PendSV 来自端口别名 | 自己的新工程中排除生成的同名空函数；本次不修改既有工程/IDE 全局配置 |
| HAL 模块 | 核心、RCC、CORTEX、FLASH 定义及 GPIO 依赖 | 固定 RCC 源的 MCO（微控制器时钟输出）函数无条件使用 GPIO 类型，所以即使本例不输出引脚也要提供 GPIO 头/实现；编译模块不等于启用 GPIO 引脚 |

HAL 初始化字段逐项解释：[S5][S9]

- `RCC_OscInitTypeDef oscillator={0}` 是初始化函数内的临时配置，不是 HAL 外设句柄。`OscillatorType=HSI` 限定要处理的源；`HSIState=ON`；`HSICalibrationValue=DEFAULT` 使用默认校准；`PLL.PLLState=OFF`，因此 PLL 的 M/N/P/Q 字段在此不参与计算。
- `RCC_ClkInitTypeDef clocks={0}` 的 `ClockType` 位掩码说明本次配置 SYSCLK、HCLK 和两个 PCLK；`SYSCLKSource=HSI` 选系统源，三个分频参数均为 /1。`FLASH_LATENCY_0` 对应这里的低频参考条件；真实供电必须满足数据手册条件，换高频时必须重查等待周期，不能照抄 0。
- 检查 `HAL_RCC_OscConfig` / `HAL_RCC_ClockConfig` 返回值；更新并检查 `SystemCoreClock`；显式检查 HAL tick 配置。任何失败进入 `App_Fatal` 保存错误码/行号后停住，而不是继续启动内核。
- 本例没有 UART/TIM/ADC/DMA 的 HAL 句柄。长期持有的是信号量/任务的**内核**句柄及其静态存储；不要为了模板虚构一个 `HAL_SemaphoreHandle`。

| HAL/内核操作 | LL 或关键寄存器/状态 | 真正的含义与观察 |
| --- | --- | --- |
| `HAL_RCC_OscConfig` HSI ON | `LL_RCC_HSI_Enable`；`RCC_CR.HSION/HSIRDY`、HSITRIM | 开启、等待稳定、校准；不是测量实际频率 |
| PLL OFF / 系统源选择 | `RCC_CR.PLLON/PLLRDY`；`LL_RCC_SetSysClkSource`；`RCC_CFGR.SW/SWS` | 区分切换请求与实际状态，PLL 本例不倍频 |
| AHB/APB 分频 | `LL_RCC_SetAHBPrescaler` / `LL_RCC_SetAPB1Prescaler` / `LL_RCC_SetAPB2Prescaler`；CFGR 的 HPRE/PPRE1/PPRE2 | 决定 HCLK/PCLK，本例均 /1 |
| `HAL_RCC_ClockConfig(..., FLASH_LATENCY_0)` | `FLASH_ACR.LATENCY` | 与工作频率/供电条件匹配，不是信号量参数 |
| HAL 启动 tick / 内核 tick | SysTick `CTRL.ENABLE/TICKINT/CLKSOURCE`、`LOAD=15999`、`VAL` | 启动前后所有权只有一个；CTRL 的 COUNTFLAG 不等于超时函数已返回 |
| `HAL_NVIC_*` 与端口优先级 | SCB AIRCR 的分组、系统异常优先级字段；CMSIS（Cortex 微控制器软件接口标准）的异常定义 | 属于处理器异常控制；任务优先级不是这里的编码 |
| 内核请求任务切换 | SCB ICSR 的 PENDSVSET；端口的 SVC/PendSV 保存/恢复上下文 | 请求切换不等于刚刚唤醒的任务已经执行 |
| `xSemaphoreCreateCountingStatic/give/take` | **没有对应 LL/信号量寄存器**；`queue.c` 的 `uxLength/uxMessagesWaiting/uxItemSize` 和等待链 | 上限、计数、项大小零及任务状态由软件维护；内核临界区保证操作一致性，不应由应用直接写内部字段 |

寄存器/LL 是用于解释同一路径的对照，不要求运行 HAL 初始化后再执行一遍 LL。读取 SysTick CTRL 会影响 COUNTFLAG；连续调试器刷新也要考虑观察副作用。[S5][S6][S8]

**IRQ/DMA 回调与错误路径**：最小例没有外设 IRQ/DMA，故外设完成/错误回调不适用；唯一时基 IRQ 已在代码中实现。后续联动检查清单如下，本课不提供已实现该联动的暗示：[S1][S5]

1. 先明确完成事件来自哪个 IRQ、哪个 HAL handler、哪个完成/错误回调；分别描述数据有效与失败状态，不能在错误回调中伪发“成功数据就绪”。
2. 核对该 IRQ 是否位于内核允许调用的优先级范围；高于阈值的 ISR 即使换成 FromISR 名称也不能调用内核。
3. 选择并核对 `xSemaphoreGiveFromISR`、高优先级任务唤醒标记及端口的 `portYIELD_FROM_ISR` 请求；本课的 `xSemaphoreGive` 不能直接从 ISR 调用。
4. give 已满时记录丢事件/过载策略；同时证明 DMA 缓冲区在任务处理前不会被重用。后续 `isr` / `notification` / `race-condition` 课程完成代码和实验，不把此清单算作完成。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

模型由 `model/permit_model.h` / `model/permit_model.c` 定义，测试驱动持有一个 `PermitModel` 并显式注入 take/give/tick/dispatch（模拟获得 CPU）步骤。状态是 IDLE（尚无等待）、BLOCKED（等待）、READY（就绪）、DONE（本次请求已完成）。它**只有一个脚本化等待者，不运行线程，不自动调度，不模拟完整优先级/中断，不支持 tick 回绕**；超出可表示时长会返回 `PM_INVALID`，而真正内核另有超时/回绕处理。[S5]

调用含义：`PM_Take` 开始请求；已有许可时当场成功，空且等待为零时当场失败；有限等待时返回模型专用 `PM_PENDING`，不是 FreeRTOS 返回码。`PM_Give` / `PM_Advance` 只使等待者就绪；`PM_Dispatch` 才重新检查许可/剩余等待，决定成功、失败或继续阻塞。

从仓库根执行，不需要安装第三方 Python 包：

```powershell
python lessons/L044-freertos-static-semaphore/tools/test_host.py `
  --evidence .state/runs/20261023-174139239-24156/teacher-work/host
```

测试输入、判据与边界：

| 用例 | 受控输入与预期 | 能抓到的错误 |
| --- | --- | --- |
| 初值/饱和 | max=2、initial=0，give 三次为成功/成功/满，count 停在 2；take 两次回 0 | 错误上限比较、允许 count=3、漏减计数 |
| 空时零等待 | count=0，take(0) 立即失败，不改变 count | 把空当成功或无条件阻塞 |
| 提前事件 | take(3)，推进 2 tick，再 give：READY、result 仍 pending、count=1；dispatch 后成功且 count=0 | 在 give 中提前扣许可、把唤醒等同返回 |
| 无事件到期 | take(3)，2 tick 尚阻塞，第 3 tick 就绪；dispatch 后空失败 | 把截止比较写成严格大于、超时未执行仍提前完成 |
| 被抢先消费 | give 唤醒后，测试驱动把 count 设为 0，表示模型外的另一执行者先消费；dispatch 应继续等，再到期失败 | 假设许可已经预留；该注入不是多任务调度仿真 |
| 到期与可用重检 | 到期就绪后、dispatch 前 give；恢复检查时可成功 | 把超时唤醒硬编码为必失败 |
| 上限为一 | 两次 give 只有一次成功；只能 take 一次 | 把二值事件当任意累积计数 |
| 无载荷对照 | 两次样本写同一变量并 give 两次，两个 take 都只能看到末值 22；独立数组仍保存 11/22 | 错把许可当消息存储；数组仅用于对照，不是真实 FreeRTOS 队列测试 |
| 边界 | NULL、非法初值/上限、等待/时间溢出 | 失效参数造成状态污染或无符号回绕误判 |

本次实际结果（完整命令、编译器版本、哈希和退出码在 `teacher-work/host/host-tests.json`）：

```text
positive: PASS 63 checks: permits, saturation, wait, wake, timeout, no payload
red-full: FAIL ... PM_Give(&m) == PM_FULL && m.count == 2U
red-timeout: FAIL ... PM_Advance(&m, 1U) == PM_OK && m.state == PM_READY
red-reserve: FAIL ... m.state == PM_READY && m.result == PM_PENDING && m.count == 1U
PASS positive model and 3 rejected mutations; no hardware claims
```

三个 red 是在运行目录生成的故意错误副本，分别破坏满额比较、到期比较和不预留许可规则。脚本要求它们**编译成功后以预期断言失败并退出 1**，不能把编译器报错算作变异测试通过。正式模型未被覆盖。本次还先用独立空实现得到 `PM_Init` 的预期行为失败，再实现模型；记录为 `teacher-work/red-test.json`。

这些结果只说明教学模型与测试闭环有效，不证明 FreeRTOS 的全部并发语义，更不是 Cortex-M 或硬件证据。

### 8.2 STM32 参考实现轨道

**参考实现，待目标工程编译；未烧录、未上板、未测量。** 主机 GCC 仅用真实固定包头文件检查了 4 个应用 C 文件及 7 个 HAL/内核依赖 C 文件的语法；没有执行 ARM 指令生成、汇编、链接或目标运行，不能简写为“固件编译通过”。[S5]

最小调用闭环是：

```text
startup → SystemInit → main → HAL_Init / 启动 tick
  → SystemClock_Config / HSI / 总线 / 显式 tick 检查
  → SysTick 单向交接准备
  → App_CreatePermitTasks
       → 静态计数信号量(max=2, initial=0)
       → 两个静态上下文写入同一句柄
       → xTaskCreateStatic(Producer, priority=2)
       → xTaskCreateStatic(Consumer, priority=1)
  → vTaskStartScheduler → 端口 SysTick/SVC/PendSV
  → give/take/超时统计，参数或初始化错误则 App_Fatal
```

可直接复用的部分是这组应用 C 源/头文件、相应的固定内核配置和 HSI-only 时钟方案；仍须在新目标工程中集成。板级待填项包括完整 MCU 料号/容量、板卡/供电、调试接线、匹配的启动文件/链接脚本及工具链版本。HSE 未启用，故本例不需要板级 HSE 数字；也没有 LED/UART/MCO 引脚配方。启动不是无条件适用于未知 Bootloader 的跳转入口。

**参考构建步骤（说明，不代表本次已执行）**：

1. 在自己的新工程里确认真实器件，按 7.3 的 HSI 配置生成基础启动工程。保持 IDE/CubeMX 全局配置不变。确保只有本课一份 main、SysTick、FreeRTOSConfig，排除重复的生成任务/handler/CMSIS-RTOS 包装入口。
2. 加入本课 `target` 的 4 个 `.c` 及其头文件。采用匹配真实料号的厂商 `startup_stm32f407xx.s`、`system_stm32f4xx.c` 与容量正确的链接脚本；不从本课猜 Flash/RAM 末地址。
3. 从固定包引用原生内核 `Source/tasks.c`、`queue.c`、`list.c`、`portable/GCC/ARM_CM4F/port.c`，以及 include/端口目录；**不复制第三方完整源码到课程仓库**，不加入任何 `heap_n.c`，不加入 CMSIS-RTOS 包装源。此例关闭软件定时器，不需要 `timers.c`。
4. 从固定 HAL 引用 `stm32f4xx_hal.c`、`stm32f4xx_hal_rcc.c`、`stm32f4xx_hal_cortex.c`、`stm32f4xx_hal_gpio.c` 及其头文件；本例 Flash latency 只使用头文件宏，不调用 Flash 编程 API。GPIO 是 RCC 源文件编译依赖，不意味着本例调用 GPIO 初始化或输出 MCO。
5. 工程宏至少 `STM32F407xx`、`USE_HAL_DRIVER`。GCC ARM_CM4F 配套选项包括 `-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard -std=c11`；所有库/对象的浮点 ABI（应用二进制接口）必须一致，不能把主机 GCC 当 ARM 编译器。
6. 编译/链接并保存完整日志、编译器版本、Cube 包版本、源清单、预处理宏和 map（链接布局报告）。检查唯一异常入口、控制块/栈所在 RAM、无动态创建/heap 依赖、正确向量表、FPU（浮点单元）端口配置和栈余量。本文所附主机语法检查不能替代这些步骤。

可复现本课已做的窄范围检查（这条不是 ARM 构建命令）：

```powershell
python lessons/L044-freertos-static-semaphore/tools/check_reference.py `
  --cube 'C:\Users\25108\STM32Cube\Repository\STM32Cube_FW_F4_V1.28.3' `
  --evidence .state/runs/20261023-174139239-24156/teacher-work/reference-syntax
```

该包路径是本机本次实际读取位置，不是所有人的固定安装路径。检查器使用 `-fsyntax-only`，只为 64 位主机头文件解析屏蔽整数/指针宽度转换告警；不屏蔽普通应用警告，不检验 ARM 汇编、FPU ABI、链接或实际栈布局。记录见 `reference-syntax.json`。扩展依赖检查曾捕获缺少 GPIO 声明的问题，故新配置已包含 GPIO；没有修改既有课程。

**上板步骤（本次不执行烧录）**：先满足真实目标的供电、复位、SWD（串行线调试）接线、器件容量与调试器条件；仅在用户允许且目标固件构建成功后，用匹配工具下载 ELF，从真实复位运行，保存工具输出和目标标识。不要把本课文字预期写成观察结果。

**预期观察而非本次实测**：第一次高优先级 Producer 的 `first_give_ok` 为 `{1,1,0}`、`first_count` 为 `{1,2,2}`，消费任务随后取得两个许可，空时等待并出现超时；周期任务运行后 `give_ok/take_ok/give_full/take_timeout` 随各自路径增加。它们不是消息序号，也不保证所有字段构成原子一致快照；调试暂停后联合查看。不同循环的超时次数会受边界时序/断点影响，不能要求固定打印行数。

**逐系列迁移核对表**：仅能力范围由对应数据手册支持；具体端口/安全/缓存维护配方必须在新目标参考手册、勘误和固定 Cube 包中重查，以下未给已验证配方。[S12–S14]

| 具体范围 | 已有第一方依据 | 要重查并改变哪一部分 |
| --- | --- | --- |
| F4 / F407xx | Cortex-M4/FPU、HSI 标称 16 MHz；本课固定包含 ARM_CM4F [S5][S7] | 完整料号/硅版本、RAM/Flash 容量、启动/链接和 ES0182 适用性；决定控制块/栈可放哪里及能否安全启动 |
| F7 / F767ZI | Cortex-M7、一级指令/数据缓存和 TCM（紧耦合存储器）范围 [S12] | 换对应 M7 端口/浮点 ABI、CubeF7 配置、异常优先级与时基；重查链接段及 DMA 可达性。信号量不替另一个 DMA 缓冲自动维护缓存；具体清理范围待目标资料核对 |
| H5 / H563ZI | Cortex-M33、TrustZone（安全/非安全隔离）能力、缓存与 HSI 范围见 DS14258 [S13] | 选择安全状态对应的内核端口/启动；核对 IRQ 归属、SysTick 及控制块/栈的安全属性/可访问性，不拿 CM4F handler/config 直接用；具体属性位和端口待核对 |
| H7 / H743ZI | Cortex-M7 与缓存/存储能力范围 [S14] | 按实际内核/HCLK/分频和电源条件重算 tick；按 RAM 域/缓存/总线可达性重新布置对象与 DMA 缓冲；具体域与维护方法待相应 RM/勘误/CubeH7 核对，不将 H743 推成双核器件 |

可迁移的是有界许可、成功/失败计数及等待后的重检推理；不是 F407 的 16 MHz、优先级位数、寄存器地址或端口文件。纯任务间信号量对象不需要凭空加 DMA 缓存操作；真正接入硬件数据搬运后再证明数据链的一致性。

## 9. 最小代码示例

这里“最小”指完整解决本课问题所需的边界，不是省掉 Idle 存储、时基或错误路径。以下清单均为本课实际文件，代码与文件保持一致。应用公开状态字段使用固定宽度整数；`BaseType_t/UBaseType_t/StackType_t`、`void *` 等类型用于遵守上游内核 API，不重新定义它们的 ABI。

### 9.1 主机层：显式许可状态机

层次/依赖/生存期：`model` 只依赖 C 标准类型，不依赖 HAL/FreeRTOS；测试驱动持有对象并控制事件顺序，模型不持有任务或缓冲区地址。它的额外状态/返回值用于教学观察，不是公开 FreeRTOS 接口。

<!-- BEGIN CODE:model/permit_model.h -->
**`model/permit_model.h`**

```c
#ifndef L044_PERMIT_MODEL_H
#define L044_PERMIT_MODEL_H
#include <stdint.h>

#define PM_OK UINT32_C(0)
#define PM_FULL UINT32_C(1)
#define PM_EMPTY UINT32_C(2)
#define PM_PENDING UINT32_C(3)
#define PM_INVALID UINT32_C(4)
#define PM_IDLE UINT32_C(0)
#define PM_BLOCKED UINT32_C(1)
#define PM_READY UINT32_C(2)
#define PM_DONE UINT32_C(3)

/* One scripted waiter; no threads, payloads, tick wrap or automatic dispatch. */
typedef struct {
    uint32_t maximum;
    uint32_t count;
    uint32_t tick;
    uint32_t deadline;
    uint32_t state;
    uint32_t result;
} PermitModel;

uint32_t PM_Init(PermitModel *model, uint32_t maximum, uint32_t initial);
uint32_t PM_Give(PermitModel *model);
uint32_t PM_Take(PermitModel *model, uint32_t wait_ticks);
uint32_t PM_Advance(PermitModel *model, uint32_t ticks);
uint32_t PM_Dispatch(PermitModel *model);
#endif
```
<!-- END CODE:model/permit_model.h -->

<!-- BEGIN CODE:model/permit_model.c -->
**`model/permit_model.c`**

```c
#include "permit_model.h"
#include <stddef.h>

static uint32_t valid(const PermitModel *m)
{
    return m != NULL && m->maximum != 0U && m->count <= m->maximum;
}

uint32_t PM_Init(PermitModel *m, uint32_t maximum, uint32_t initial)
{
    if (m == NULL || maximum == 0U || initial > maximum) {
        return PM_INVALID;
    }
    *m = (PermitModel){maximum, initial, 0U, 0U, PM_IDLE, PM_PENDING};
    return PM_OK;
}

uint32_t PM_Give(PermitModel *m)
{
    if (!valid(m)) {
        return PM_INVALID;
    }
    if (m->count >= m->maximum) {
        return PM_FULL;
    }
    ++m->count;
    if (m->state == PM_BLOCKED) {
        m->state = PM_READY;
    }
    return PM_OK;
}

uint32_t PM_Take(PermitModel *m, uint32_t wait_ticks)
{
    if (!valid(m) || m->state == PM_BLOCKED || m->state == PM_READY) {
        return PM_INVALID;
    }
    if (m->count != 0U) {
        --m->count;
        m->state = PM_DONE;
        m->result = PM_OK;
        return PM_OK;
    }
    if (wait_ticks == 0U) {
        m->state = PM_DONE;
        m->result = PM_EMPTY;
        return PM_EMPTY;
    }
    if (wait_ticks > UINT32_MAX - m->tick) {
        return PM_INVALID;
    }
    m->deadline = m->tick + wait_ticks;
    m->state = PM_BLOCKED;
    m->result = PM_PENDING;
    return PM_PENDING;
}

uint32_t PM_Advance(PermitModel *m, uint32_t ticks)
{
    if (!valid(m) || ticks > UINT32_MAX - m->tick) {
        return PM_INVALID;
    }
    m->tick += ticks;
    if (m->state == PM_BLOCKED && m->tick >= m->deadline) {
        m->state = PM_READY;
    }
    return PM_OK;
}

uint32_t PM_Dispatch(PermitModel *m)
{
    if (!valid(m) || m->state != PM_READY) {
        return PM_INVALID;
    }
    /* Availability is rechecked; being ready did not reserve a permit. */
    if (m->count != 0U) {
        --m->count;
        m->result = PM_OK;
    } else if (m->tick >= m->deadline) {
        m->result = PM_EMPTY;
    } else {
        m->state = PM_BLOCKED;
        return PM_PENDING;
    }
    m->state = PM_DONE;
    return m->result;
}
```
<!-- END CODE:model/permit_model.c -->

完整测试在 [tests/test_permit_model.c](tests/test_permit_model.c)，编译/变异驱动在 [tools/test_host.py](tools/test_host.py)。测试中的“另一执行者取走许可”是明确的驱动注入，不是允许应用修改真实内核 count。主机 `uint32_t` 截止时间的溢出拒绝策略，也不是对 FreeRTOS tick 回绕行为的实现声明。

### 9.2 目标配置层：固定包与错误出口

层次/依赖/生存期：配置头由应用和内核共享、整个编译工程只选一份；故静态控制块类型与真正内核布局一致。错误接口依赖固定宽度整数，具体停机实现依赖 CMSIS。`App_Fatal` 只记码并停住，不调用日志、HAL_Delay 或动态分配；错误发生后不继续用半创建对象。

<!-- BEGIN CODE:target/app_fatal.h -->
**`target/app_fatal.h`**

```c
#ifndef L044_APP_FATAL_H
#define L044_APP_FATAL_H
#include <stdint.h>
#define APP_FATAL_ASSERT UINT32_C(1)
#define APP_FATAL_HAL_INIT UINT32_C(2)
#define APP_FATAL_HAL_TICK UINT32_C(3)
#define APP_FATAL_OSC UINT32_C(4)
#define APP_FATAL_CLOCK UINT32_C(5)
#define APP_FATAL_CREATE UINT32_C(6)
#define APP_FATAL_SCHED_RETURN UINT32_C(7)
#define APP_FATAL_TASK_RETURN UINT32_C(8)
#define APP_FATAL_STACK UINT32_C(9)
#define APP_FATAL_PARAMETER UINT32_C(10)
extern volatile uint32_t g_error_code;
extern volatile uint32_t g_error_line;
_Noreturn void App_Fatal(uint32_t code, uint32_t line);
_Noreturn void App_TaskReturned(void);
#endif
```
<!-- END CODE:target/app_fatal.h -->

<!-- BEGIN CODE:target/app_fatal.c -->
**`target/app_fatal.c`**

```c
#include "stm32f4xx.h"
#include "app_fatal.h"

volatile uint32_t g_error_code;
volatile uint32_t g_error_line;

_Noreturn void App_Fatal(uint32_t code, uint32_t line)
{
    __disable_irq();
    g_error_code = code;
    g_error_line = line;
    for (;;) {
        __NOP();
    }
}

_Noreturn void App_TaskReturned(void)
{
    App_Fatal(APP_FATAL_TASK_RETURN, (uint32_t)__LINE__);
}
```
<!-- END CODE:target/app_fatal.c -->

<!-- BEGIN CODE:target/FreeRTOSConfig.h -->
**`target/FreeRTOSConfig.h`**

```c
#ifndef L044_FREERTOS_CONFIG_H
#define L044_FREERTOS_CONFIG_H
#include "stm32f4xx.h"
#include "app_fatal.h"
#define configUSE_PREEMPTION 1
#define configUSE_TIME_SLICING 1
#define configUSE_PORT_OPTIMISED_TASK_SELECTION 1
#define configCPU_CLOCK_HZ (SystemCoreClock)
#define configTICK_RATE_HZ 1000U
#define configMAX_PRIORITIES 5U
#define configMINIMAL_STACK_SIZE 256U
#define configMAX_TASK_NAME_LEN 12U
#define configUSE_16_BIT_TICKS 0
#define configIDLE_SHOULD_YIELD 0
#define configUSE_TICKLESS_IDLE 0
#define configSUPPORT_STATIC_ALLOCATION 1
#define configSUPPORT_DYNAMIC_ALLOCATION 0
#define configUSE_COUNTING_SEMAPHORES 1
#define configUSE_TIMERS 0
#define configUSE_MUTEXES 0
#define configUSE_RECURSIVE_MUTEXES 0
#define configUSE_TASK_NOTIFICATIONS 0
#define configUSE_QUEUE_SETS 0
#define configUSE_CO_ROUTINES 0
#define configUSE_IDLE_HOOK 0
#define configUSE_TICK_HOOK 0
#define configCHECK_FOR_STACK_OVERFLOW 2
#define configUSE_MALLOC_FAILED_HOOK 0
#define configUSE_NEWLIB_REENTRANT 0
#define configUSE_TRACE_FACILITY 0
#define configGENERATE_RUN_TIME_STATS 0
#define configQUEUE_REGISTRY_SIZE 0U
#define INCLUDE_vTaskDelay 1
#define INCLUDE_vTaskDelete 0
#define INCLUDE_vTaskSuspend 0
#define INCLUDE_eTaskGetState 1
#define INCLUDE_uxTaskGetStackHighWaterMark 1
#define configPRIO_BITS __NVIC_PRIO_BITS
#define configLIBRARY_LOWEST_INTERRUPT_PRIORITY 15U
#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY 5U
#define configKERNEL_INTERRUPT_PRIORITY \
    (configLIBRARY_LOWEST_INTERRUPT_PRIORITY << (8U - configPRIO_BITS))
#define configMAX_SYSCALL_INTERRUPT_PRIORITY \
    (configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY << (8U - configPRIO_BITS))
#define configASSERT(expr) do { if ((expr) == 0) { \
    App_Fatal(APP_FATAL_ASSERT, (uint32_t)__LINE__); } } while (0)
#define configTASK_RETURN_ADDRESS App_TaskReturned
#define vPortSVCHandler SVC_Handler
#define xPortPendSVHandler PendSV_Handler
/* interrupts.c owns SysTick_Handler, so do not alias it to the port here. */
#endif
```
<!-- END CODE:target/FreeRTOSConfig.h -->

<!-- BEGIN CODE:target/stm32f4xx_hal_conf.h -->
**`target/stm32f4xx_hal_conf.h`**

```c
#ifndef L044_STM32F4XX_HAL_CONF_H
#define L044_STM32F4XX_HAL_CONF_H
#include "app_fatal.h"
#define HAL_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_FLASH_MODULE_ENABLED
#define HAL_GPIO_MODULE_ENABLED
#define HSI_VALUE 16000000U
#define HSE_VALUE 0U /* Unused: replace with actual board value before enabling. */
#define HSE_STARTUP_TIMEOUT 100U
#define LSI_VALUE 32000U
#define LSE_VALUE 32768U
#define LSE_STARTUP_TIMEOUT 5000U
#define EXTERNAL_CLOCK_VALUE 0U
#define TICK_INT_PRIORITY 15U
#define USE_RTOS 0U /* Reserved HAL option, not the FreeRTOS enable switch. */
#define PREFETCH_ENABLE 0U
#define INSTRUCTION_CACHE_ENABLE 0U
#define DATA_CACHE_ENABLE 0U
#include "stm32f4xx_hal_rcc.h"
#include "stm32f4xx_hal_cortex.h"
#include "stm32f4xx_hal_flash.h"
#include "stm32f4xx_hal_gpio.h"
#define assert_param(expr) do { if ((expr) == 0U) { \
    App_Fatal(APP_FATAL_ASSERT, (uint32_t)__LINE__); } } while (0)
#endif
```
<!-- END CODE:target/stm32f4xx_hal_conf.h -->

`USE_RTOS=0` 是固定 HAL 的保留选项，不是关闭 FreeRTOS；真正开关在本课内核配置。关闭动态分配、软件定时器、互斥量等是为了限定实验范围；它们不是对真实项目的统一推荐。栈溢出 hook（钩子回调）是错误观察手段，不保证发现所有越界。

### 9.3 应用层：声明、实例化、组装和任务使用

层次/依赖/生存期：`app_permits.h` 声明应用入口与调试统计；`app_permits.c` 的静态对象承载实例，`App_CreatePermitTasks` 完成组装，Producer/Consumer 使用已注入的上下文。依赖方向是应用→原生内核，不通过 HAL 传信号量。上下文只在调度前写入，之后保持不变；栈、TCB（任务控制块）、信号量控制块和 Idle 存储均终身存在。

<!-- BEGIN CODE:target/app_permits.h -->
**`target/app_permits.h`**

```c
#ifndef L044_APP_PERMITS_H
#define L044_APP_PERMITS_H
#include <stdint.h>

typedef struct {
    uint32_t give_ok;
    uint32_t give_full;
    uint32_t take_ok;
    uint32_t take_timeout;
    uint32_t producer_tick;
    uint32_t consumer_tick;
    uint32_t first_give_ok[3];
    uint32_t first_count[3];
    uint32_t first_burst_done;
} PermitStats;

/* Debugger observations only; not an inter-task synchronization protocol. */
extern volatile PermitStats g_permit_stats;
uint32_t App_CreatePermitTasks(void);
#endif
```
<!-- END CODE:target/app_permits.h -->

<!-- BEGIN CODE:target/app_permits.c -->
**`target/app_permits.c`**

```c
#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#include "app_permits.h"
#include "app_fatal.h"

#define APP_STACK_WORDS 256U
typedef struct {
    SemaphoreHandle_t permits;
} TaskContext;

static StaticSemaphore_t permit_storage;
static StaticTask_t producer_tcb;
static StaticTask_t consumer_tcb;
static StaticTask_t idle_tcb;
static StackType_t producer_stack[APP_STACK_WORDS];
static StackType_t consumer_stack[APP_STACK_WORDS];
static StackType_t idle_stack[configMINIMAL_STACK_SIZE];
static TaskContext producer_context;
static TaskContext consumer_context;
static uint32_t created;
volatile PermitStats g_permit_stats;

static const TaskContext *check_context(void *argument)
{
    const TaskContext *context = (const TaskContext *)argument;
    if (context == NULL || context->permits == NULL) {
        App_Fatal(APP_FATAL_PARAMETER, (uint32_t)__LINE__);
    }
    return context;
}

static void Producer(void *argument)
{
    const TaskContext *context = check_context(argument);
    uint32_t first = 1U;
    for (;;) {
        for (uint32_t i = 0U; i < 3U; ++i) {
            BaseType_t result = xSemaphoreGive(context->permits);
            if (result == pdTRUE) {
                ++g_permit_stats.give_ok;
            } else {
                ++g_permit_stats.give_full;
            }
            if (first != 0U) {
                g_permit_stats.first_give_ok[i] = (result == pdTRUE) ? 1U : 0U;
                g_permit_stats.first_count[i] =
                    (uint32_t)uxSemaphoreGetCount(context->permits);
            }
        }
        first = 0U;
        g_permit_stats.first_burst_done = 1U;
        g_permit_stats.producer_tick = (uint32_t)xTaskGetTickCount();
        /* Priority 2 producer yields by blocking; priority 1 consumer can run. */
        vTaskDelay(pdMS_TO_TICKS(20U));
    }
}

static void Consumer(void *argument)
{
    const TaskContext *context = check_context(argument);
    for (;;) {
        BaseType_t result = xSemaphoreTake(context->permits, pdMS_TO_TICKS(5U));
        if (result == pdTRUE) {
            ++g_permit_stats.take_ok;
        } else {
            ++g_permit_stats.take_timeout;
        }
        g_permit_stats.consumer_tick = (uint32_t)xTaskGetTickCount();
    }
}

uint32_t App_CreatePermitTasks(void)
{
    SemaphoreHandle_t permits;
    TaskHandle_t producer;
    TaskHandle_t consumer;
    if (created != 0U) {
        return 1U;
    }
    created = 1U;
    permits = xSemaphoreCreateCountingStatic(2U, 0U, &permit_storage);
    if (permits == NULL) {
        return 2U;
    }
    producer_context.permits = permits;
    consumer_context.permits = permits;
    producer = xTaskCreateStatic(Producer, "Give", APP_STACK_WORDS,
                                &producer_context, 2U, producer_stack,
                                &producer_tcb);
    consumer = xTaskCreateStatic(Consumer, "Take", APP_STACK_WORDS,
                                &consumer_context, 1U, consumer_stack,
                                &consumer_tcb);
    if (producer == NULL || consumer == NULL) {
        return 3U;
    }
    return 0U;
}

void vApplicationGetIdleTaskMemory(StaticTask_t **tcb, StackType_t **stack,
                                   uint32_t *words)
{
    *tcb = &idle_tcb;
    *stack = idle_stack;
    *words = configMINIMAL_STACK_SIZE;
}

void vApplicationStackOverflowHook(TaskHandle_t task, char *name)
{
    (void)task;
    (void)name;
    App_Fatal(APP_FATAL_STACK, (uint32_t)__LINE__);
}
```
<!-- END CODE:target/app_permits.c -->

生产方优先级较高，一口气 give 三次后延时 20 tick；消费方每次最多等待 5 tick。第一次“成功、成功、失败”的实验条件由优先级与无额外阻塞共同建立。如果把消费方改成更高优先级，它可能在 give 返回之前取走许可，第三次 give 不一定满，这不是信号量上限失效。[S5]

统计字段由各自任务更新，`volatile` 只为调试可见性，不为多个写者建立互斥；它们不参与任务行为决策，不可拿未同步的累计统计做生产级资源分配。`uxSemaphoreGetCount` 也只观察瞬时值，不可采用“先看 count>0 再假设 take 必成功”的检查/执行分离逻辑。[S5]

### 9.4 启动/硬件适配层：时钟、异常与内核入口

层次/依赖/生存期：启动依赖 HAL/CMSIS，组装入口依赖应用，内核不反向依赖 `SystemClock_Config`。两个 RCC 配置结构只在初始化调用期间使用，不需要静态保存；SysTick 所有权标记只在调度前从 0 变 1，不做动态来回切换。端口在启动首任务时处理异常/中断恢复，不在创建对象后擅自恢复旧 HAL SysTick。

<!-- BEGIN CODE:target/interrupts.h -->
**`target/interrupts.h`**

```c
#ifndef L044_INTERRUPTS_H
#define L044_INTERRUPTS_H
#include <stdint.h>
extern volatile uint32_t g_kernel_owns_systick;
void SysTick_Handler(void);
#endif
```
<!-- END CODE:target/interrupts.h -->

<!-- BEGIN CODE:target/interrupts.c -->
**`target/interrupts.c`**

```c
#include "stm32f4xx_hal.h"
#include "interrupts.h"
volatile uint32_t g_kernel_owns_systick;
extern void xPortSysTickHandler(void);

void SysTick_Handler(void)
{
    if (g_kernel_owns_systick == 0U) {
        HAL_IncTick();
    } else {
        xPortSysTickHandler();
    }
    __DSB(); /* ES0182 2.1.3: recheck applicability to the actual silicon. */
}
/* SVC_Handler/PendSV_Handler come from the single GCC ARM_CM4F port. */
```
<!-- END CODE:target/interrupts.c -->

<!-- BEGIN CODE:target/main.c -->
**`target/main.c`**

```c
#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"
#include "app_permits.h"
#include "app_fatal.h"
#include "interrupts.h"

volatile uint32_t g_main_phase;

/* Genuine reset and matching vendor SystemInit, not a bootloader handoff. */
static void SystemClock_Config(void)
{
    RCC_OscInitTypeDef oscillator = {0};
    RCC_ClkInitTypeDef clocks = {0};
    oscillator.OscillatorType = RCC_OSCILLATORTYPE_HSI;
    oscillator.HSIState = RCC_HSI_ON;
    oscillator.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
    oscillator.PLL.PLLState = RCC_PLL_OFF;
    if (HAL_RCC_OscConfig(&oscillator) != HAL_OK) {
        App_Fatal(APP_FATAL_OSC, (uint32_t)__LINE__);
    }
    clocks.ClockType = RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK |
                       RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    clocks.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
    clocks.AHBCLKDivider = RCC_SYSCLK_DIV1;
    clocks.APB1CLKDivider = RCC_HCLK_DIV1;
    clocks.APB2CLKDivider = RCC_HCLK_DIV1;
    if (HAL_RCC_ClockConfig(&clocks, FLASH_LATENCY_0) != HAL_OK) {
        App_Fatal(APP_FATAL_CLOCK, (uint32_t)__LINE__);
    }
    SystemCoreClockUpdate();
    if (SystemCoreClock != UINT32_C(16000000) ||
        HAL_NVIC_GetPriorityGrouping() != NVIC_PRIORITYGROUP_4) {
        App_Fatal(APP_FATAL_CLOCK, (uint32_t)__LINE__);
    }
    /* This fixed HAL does not propagate its nested HAL_InitTick return value. */
    if (HAL_InitTick(TICK_INT_PRIORITY) != HAL_OK) {
        App_Fatal(APP_FATAL_HAL_TICK, (uint32_t)__LINE__);
    }
}

int main(void)
{
    g_main_phase = 1U;
    if (HAL_Init() != HAL_OK) {
        App_Fatal(APP_FATAL_HAL_INIT, (uint32_t)__LINE__);
    }
    if (HAL_InitTick(TICK_INT_PRIORITY) != HAL_OK) {
        App_Fatal(APP_FATAL_HAL_TICK, (uint32_t)__LINE__);
    }
    SystemClock_Config();
    HAL_NVIC_SetPriority(SVCall_IRQn, 0U, 0U);
    g_main_phase = 2U;

    /* One-way SysTick handoff: no timed HAL calls after this point. */
    __disable_irq();
    HAL_SuspendTick();
    SysTick->CTRL = 0U;
    SysTick->VAL = 0U;
    SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk | SCB_ICSR_PENDSVCLR_Msk;
    __DSB();
    __ISB();
    if (App_CreatePermitTasks() != 0U) {
        App_Fatal(APP_FATAL_CREATE, (uint32_t)__LINE__);
    }
    g_kernel_owns_systick = 1U;
    g_main_phase = 3U;
    vTaskStartScheduler();
    App_Fatal(APP_FATAL_SCHED_RETURN, (uint32_t)__LINE__);
}
```
<!-- END CODE:target/main.c -->

`__DSB` 是数据同步屏障，此处结合 ES0182 的异常返回勘误边界保留；真实硅版本的适用条件仍须在集成时核对。它不是修复所有并发问题的万能指令。[S8][S11]

原生声明与实现的阅读链为：`include/semphr.h` 的宏 → `queue.c:xQueueCreateCountingSemaphoreStatic/xQueueGenericSend/xQueueSemaphoreTake` → `tasks.c` 等待/就绪/超时处理 → `portable/GCC/ARM_CM4F/port.c`。它们在厂商包里，只记录阅读位置和哈希，不把完整第三方源码复制进本课。[S5]

## 10. 常见错误

| 错误 | 为什么不对 | 改法 |
| --- | --- | --- |
| initial=0 却期待启动后 take 第一次就成功 | 没有预存许可 | 按事件需求等待 give；资源份额用法才按协议选择非零初值 |
| give 失败仍认为事件已经记录 | 已满拒绝新增，计数守恒只计算成功操作 | 记录过载并明确允许丢弃、回压或换数据协议 |
| 认为消费后必须归还一个事件许可 | 这会把已经消费的事件重新制造出来 | 先区分事件消耗与资源借还语义 |
| give 两次就能读到两次旧样本 | 信号量没有载荷存储 | 需要队列或有所有权约束的缓冲描述符 |
| 二值信号量等于互斥量 | 上限为 1 不会自动产生持有者/优先级继承 | 独占资源按 `mutex` 课选择正确机制 |
| 用局部 `StaticSemaphore_t` 创建后函数返回 | 内核仍在使用已经失效的控制存储 | 让控制块、任务栈、上下文拥有足够长的生存期 |
| 先读 count，再无条件访问资源 | 中间可能被别的执行者消费 | 检查真实 take 的返回值；计数读数只用于观察 |
| 在普通 give 中推断某个任务必立即运行 | 就绪、预留、执行不是一回事 | 查看优先级与调度，恢复后仍要重检 |
| 在 ISR 中复制本课任务 API | 调用上下文/优先级边界不满足 | 等 `isr` 专课核对 FromISR 链；本课不启用外设 IRQ |
| SysTick 同时被 HAL 和内核各自改写 | 频率、优先级和 handler 所有权混乱 | 保持本课单向交接及禁止运行期 HAL 超时的限制，或另设计独立 HAL 时基 |

官方网页与旧内核注释示例也需交叉核对：某些通用 give 示例讲的是互斥资源；不能把“必须先 take 才能 give”的资源场景注释套到初始 0 的事件计数信号量。静态创建的真实宏、参数和约束以本课固定包阅读结果对照，不逐字复制旧示例中的名称笔误。[S1–S5]

## 11. 调试观察点

| 停点/位置 | 看什么 | 如何区分问题 |
| --- | --- | --- |
| 进入 `main` | `g_main_phase=1`、真实复位路径、启动文件/向量表 | 若未进 main，先排启动/链接，不怪信号量 |
| 时钟准备结束 | RCC CR/CFGR、SystemCoreClock=16000000、PLL OFF、分组 | 确认配置与软件推算；不是 HSI 精度测量 |
| `App_CreatePermitTasks` | 静态存储地址、非 NULL 句柄、同一句柄注入两任务；max=2/initial=0 | 失效上下文、重复创建、错误配置头会破坏初始化 |
| 内核接管后 | `g_kernel_owns_systick=1`、LOAD=15999、tick 递增、唯一 SysTick/SVC/PendSV | tick 不动或频率错时先排所有权/中断屏蔽/频率，不以 HAL uwTick 判断内核 tick |
| 首次生产 burst | `first_give_ok={1,1,0}`、`first_count={1,2,2}`、`first_burst_done=1` | 高优先级生产者完成三次调用后，才看完整数组 |
| 消费路径 | 两次成功后计数归零，take 内进入等待链；随后就绪/恢复及超时统计 | 不以 `printf` 顺序代替任务状态；等待链不是载荷队列 |
| 任一错误出口 | `g_error_code/g_error_line`、调用栈、栈水位 | 初始化/断言/参数/栈错误与正常 full/timeout 分开；正常边界不进入死循环 |

调试器实时刷新不保证多字段一致快照，长期单步会严重改变时间；不得把断点间隔当 tick 精度证据。若研究真实时间，需要选择有来源的观测手段和板级条件，另保存测量证据。本课未作该测量。[S7][S8][S11]

## 12. 实战实验

### 实验 A：手推并运行两个许可

输入：max=2、initial=0，give 三次，take(0) 三次。先写出每步返回与计数，再运行主机测试。预期为成功/成功/满、成功/成功/空，count 始终 0..2。失败判据：第三次 give 被记成功、计数到 3、第三次 take 被记成功，任一项即失败。

### 实验 B：拆开事件、到期与执行

输入一：take(3)→推进 2→give→先看状态，再 dispatch。预期 give 后 READY 且 count=1、请求结果仍 pending；dispatch 才成功并归零。输入二：take(3)→推进 2→推进 1→dispatch，期间不 give。预期到期仅使就绪，dispatch 才失败。输入三：在到期就绪与 dispatch 之间 give，验证恢复时仍可取得许可。失败判据是任何“就绪即完成”或“到期绝不重检”的实现。

### 实验 C：证明测试能抓错

直接运行 `tools/test_host.py`，观察三份错误副本的编译退出码均为 0、测试退出码均为 1，并且失败表达式匹配预期。不修改正式源文件；如果错误副本也 PASS，说明对应行为没有被当前测试保护，不能报“全部正确”。

### 实验 D：目标静态集成（需另行具备条件）

按 8.2 先构建，不烧录也可以先检查源清单、重复入口和 map。只有具备真实板卡条件且得到允许后再下载运行。输入为原有优先级 2/1 与 burst=3；预期首轮三次 give 轨迹如 11 节。失败判据：目标构建/链接错误、重复 handler、启动后 tick 不动、静态对象布局错误、正常满额被当作成功。

变体：把消费任务提高到 3，**先预测**为什么第三次 give 不一定满，再在自己的实验工程中修改并保存新证据，不修改课程基线。这个实验只改变已学调度条件，不新增 ISR 或互斥量主题。任何主机日志都不能拿来填目标实验的观察结果。

## 13. 自检题

1. 为什么初始计数 0 的事件信号量可以先 give，不要求生产者先 take？
2. 三次真实事件但只有两次 give 成功，是否还能说 count 表示三个事件？应保存什么异常信息？
3. 任务被 give 唤醒之后，为什么 `xSemaphoreTake` 仍可能没有成功？
4. 最大计数 1 与互斥量的差别，能用“是否记录持有者/是否提供继承”解释吗？
5. 哪个对象一定要静态长期存在：局部 RCC 初始化结构，还是 `StaticSemaphore_t`？为什么？
6. 本课 HCLK=16 MHz、内核 1000 Hz 时，SysTick LOAD 和 `pdMS_TO_TICKS(5)` 分别是多少？这能证明真实 5 ms 吗？
7. 两次 sample 写入 `latest_sample` 并 give 两次，消费者为何可能读到两次相同末值？
8. 本课调度启动后，为什么不能在任务里调用 `HAL_Delay`？主机语法检查排除了哪些风险、又没有排除哪些风险？

参考检查点：1 是新增事件而非返还独占资源；2 只成功入账两个，必须观测 full/丢事件；3 就绪不预留许可，恢复仍重检；4 许可上限不产生互斥所有权；5 控制块由内核持续使用而 RCC 结构只用于调用；6 分别 15999 和 5，仅标称/节拍换算；7 许可不存样本；8 HAL tick 已交给内核，语法可查声明/配置，却不证明 ARM 汇编/链接/运行。请先独立作答，再对照；本次未据此改变学习状态。

## 14. 面试题

**问：用计数信号量代替消息队列，能节省 RAM 吗？**

答题要点：先问是否需要载荷；信号量没有消息项数组，不代表可丢掉本来必须保留的业务数据。若另加数据缓冲，就仍须预算缓冲、所有权和过载处理。控制块大小要按实际内核配置/目标编译结果核对，不能猜固定字节数。[S1][S2][S5]

**问：take 的等待上限 5 tick，为什么测到更久才返回？**

答题要点：等待的是许可可用/到期条件，解除阻塞后还要竞争 CPU；节拍相位、实际频率、断点/屏蔽中断都会影响墙钟时间，且恢复时会重检计数。分清输入超时、就绪时刻与函数返回时刻。[S4][S5]

**问：ISR 完成一次 DMA，give 一次，任务 take 一次，是否就能保证每块数据不丢？**

答题要点：不能；还缺合规 ISR API/优先级/切换请求、满额策略、缓冲身份、处理完成与重用边界。count 只记份数，不替 DMA 数据链建立所有权；本课没有实现该链。[S1][S5]

## 15. 延伸思考

- 如果持续每 20 tick 产生 3 次事件而计数只允许累计 2 个，应该报告“生产了 3 次”还是“成功入账 2 次、溢出 1 次”？后续过载策略必须围绕哪个事实设计？
- 如果资源池里两块缓冲区不同，take 一个许可后如何知道拿到哪一块？只加大 count 为什么不够？先画“资源身份数据”与“可用份数”的两条线，不在本课临时引入完整缓冲池实现。
- 初始值改成 2 时，系统究竟预存了两个事件，还是表示两份空闲资源？同一模型的初始化必须由业务语义解释，而非凭经验写一个常数。
- 移植 H563 时，为什么不能只把文件名的 F4 替换成 H5？指出端口/时基/安全属性三项待核对对象即可，不猜具体寄存器位。

## 16. 本节总结

信号量表示**可消费的有界许可数**：成功 give 增 1，成功 take 减 1，满时 give 失败，空时 take 可立即失败或有限等待。它没有消息载荷，也不自动表达互斥所有权。

等待者就绪、取得许可、真正运行不能合并；固定 FreeRTOS 版本恢复执行后重检计数。静态控制存储由应用长期持有，通过上下文注入任务；HAL/LL 只解释参考目标的时钟与异常，并不存在硬件“信号量寄存器”。主机模型、主机语法检查、目标固件构建和板上观察必须分别记证据。

## 17. 下一步

按当前课程路线，下一主要主题是 `mutex`：为什么“一个许可”不等于“具备所有权规则的锁”。任务通知、ISR 接口、内存预算、优先级继承与竞争问题在各自课程展开，不因本课提到名称就视为掌握。

本课只交付一篇 L044。Teacher 交付时未推进学习状态；本次 Reviewer 的过程与结论记录在 `.state/runs/20261023-174139239-24156/review.md` 和 `review-result.json`。只有通过审查才推进 `learning-state.toml` 的课程进度；不提高 mastery，不改变 Device Framework 项目状态，也未运行 Interviewer。生成或审查通过都不等于掌握。

## 18. 参考资料

编号与 `lesson.json.sources` 顺序一一对应，全部正式 URL 符合 `config/source-policy.toml`，访问/重读日期为 2026-10-23。四篇 FreeRTOS 文档正文是本次 HTTP 200 获取；ST PDF/版本页使用已有官方缓存，本次重新读取与校验 SHA-256，**不是声称本次重新下载最新版**。固定包源码只读核对，不复制完整源码。

本次来源证据为仓库相对路径 `.state/runs/20261023-174139239-24156/teacher-work/source-audit.json`，记录了实际文件、指纹与页/行阅读位置。Context7 仅作查找导航，当前主线片段不能代替固定 V10.3.1 的版本依据；下表是正式技术来源，不是 Reviewer 通过结论。

<!-- BEGIN SOURCES -->
- **[S1] FREERTOS-COUNTING — FreeRTOS Counting Semaphores**

  版本：Official live content 2026-10-23; checked against ST packaged FreeRTOS V10.3.1。访问/重读：2026-10-23；第一方：是。

  URL：https://www.freertos.org/Documentation/02-Kernel/02-Kernel-features/02-Queues-mutexes-and-semaphores/03-Counting-semaphores

  阅读位置/用途：Counting events / Resource management：事件计数与资源份额、数据不在许可内。

- **[S2] FREERTOS-STATIC-COUNTING — FreeRTOS xSemaphoreCreateCountingStatic**

  版本：Official live content 2026-10-23; checked against ST packaged FreeRTOS V10.3.1。访问/重读：2026-10-23；第一方：是。

  URL：https://www.freertos.org/Documentation/02-Kernel/04-API-references/10-Semaphore-and-Mutexes/05-xSemaphoreCreateCountingStatic

  阅读位置/用途：Parameters / Returns：uxMaxCount、uxInitialCount、StaticSemaphore_t 与静态分配开关；原型/宏另与固定包对照。

- **[S3] FREERTOS-GIVE — FreeRTOS xSemaphoreGive**

  版本：Official live content 2026-10-23; checked against ST packaged FreeRTOS V10.3.1。访问/重读：2026-10-23；第一方：是。

  URL：https://www.freertos.org/Documentation/02-Kernel/04-API-references/10-Semaphore-and-Mutexes/15-xSemaphoreGive

  阅读位置/用途：Returns、ISR 限制；通用资源示例不直接当作初始 0 的事件协议。

- **[S4] FREERTOS-TAKE — FreeRTOS xSemaphoreTake**

  版本：Official live content 2026-10-23; checked against ST packaged FreeRTOS V10.3.1。访问/重读：2026-10-23；第一方：是。

  URL：https://www.freertos.org/Documentation/02-Kernel/04-API-references/10-Semaphore-and-Mutexes/12-xSemaphoreTake

  阅读位置/用途：xTicksToWait、零等待、有限等待与返回；与打包内核超时重检路径对照。

- **[S5] ST-STM32CUBEF4 — STM32CubeF4 official package and local fixed middleware**

  版本：FW.F4.1.28.0 + patch FW.F4.1.28.3; packaged FreeRTOS V10.3.1; GCC ARM_CM4F; no target build。访问/重读：2026-10-23；第一方：是。

  URL：https://www.st.com/en/embedded-software/stm32cubef4.sw-versions.html

  阅读位置/用途：package.xml；include/task.h:46；semphr.h:289/447/1083；FreeRTOS.h:1204；queue.c:686/740/1418/2074；tasks.c:3138/3274；GCC/ARM_CM4F/port.c:679；HAL/RCC/CORTEX/GPIO、LL RCC、CMSIS 与启动文件。

- **[S6] ST-RM0090 — STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 reference manual**

  版本：Rev 22, May 2026。访问/重读：2026-10-23；第一方：是。

  URL：https://www.st.com/resource/en/reference_manual/dm00031020.pdf

  阅读位置/用途：PDF 页 217–231 的 RCC 时钟树、HSI/PLL、系统/总线分频及门控/复位；具体字段同时对照固定包 CMSIS/LL。

- **[S7] ST-DS8626 — STM32F405xx / STM32F407xx datasheet**

  版本：Rev 12, March 2026。访问/重读：2026-10-23；第一方：是。

  URL：https://www.st.com/resource/en/datasheet/stm32f407vg.pdf

  阅读位置/用途：PDF 页 1–3、81、105：器件范围、时钟/内存及运行条件；不据 URL 推断实际板卡或容量。

- **[S8] ST-PM0214 — STM32 Cortex-M4 MCUs and MPUs programming manual**

  版本：Rev 10, March 2020。访问/重读：2026-10-23；第一方：是。

  URL：https://www.st.com/resource/en/programming_manual/dm00046982.pdf

  阅读位置/用途：SysTick CTRL/LOAD/VAL、SCB ICSR/PendSV、异常优先级；本次读取 PDF 页 17–18、37–44、225–226、233–234、246–250、253。

- **[S9] ST-UM1725 — Description of STM32F4 HAL and low-layer drivers**

  版本：Rev 8, March 2023; exact HAL behavior checked in fixed package。访问/重读：2026-10-23；第一方：是。

  URL：https://www.st.com/resource/en/user_manual/dm00105879.pdf

  阅读位置/用途：文档版本/驱动结构；具体 HAL_Init、HAL_InitTick、HAL_RCC_* 字段及返回行为以固定包源码核对。

- **[S10] ST-UM1718 — STM32CubeMX for STM32 configuration and initialization C code generation**

  版本：Rev 51, May 2026; GUI not executed。访问/重读：2026-10-23；第一方：是。

  URL：https://www.st.com.cn/resource/en/user_manual/dm00104712-stm32cubemx-for-stm32-configuration-and-initialization-c-code-generation-stmicroelectronics.pdf

  阅读位置/用途：PDF 页 1–6、110–112：CubeMX 配置/生成及中间件边界；本次未执行 GUI。

- **[S11] ST-ES0182 — STM32F405/407xx and STM32F415/417xx device errata**

  版本：Rev 19, July 2026。访问/重读：2026-10-23；第一方：是。

  URL：https://www.st.com/resource/en/errata_sheet/dm00037591.pdf

  阅读位置/用途：PDF 页 1–2、6–9：硅版本、Cortex-M4 内核相关限制，尤其 2.1.3 的 DSB/异常返回边界；真实硅版本仍需核对。

- **[S12] ST-DS11532 — STM32F765xx / STM32F767xx / STM32F768Ax / STM32F769xx datasheet**

  版本：Rev 9, July 2025; F767 core/cache scope only。访问/重读：2026-10-23；第一方：是。

  URL：https://www.st.com/resource/en/datasheet/stm32f767zi.pdf

  阅读位置/用途：PDF 页 1–3：F767 的 M7、L1 I/D cache、TCM 能力范围；具体端口/RAM/DMA 配方不据此下结论。

- **[S13] ST-DS14258 — STM32H562xx and STM32H563xx datasheet**

  版本：Rev 6, May 2025; H563 core/TrustZone scope only。访问/重读：2026-10-23；第一方：是。

  URL：https://www.st.com/resource/en/datasheet/stm32h563zi.pdf

  阅读位置/用途：PDF 页 1–3：H563 的 M33、TrustZone、缓存及振荡源能力；具体安全/IRQ/端口配置仍待目标资料核对。

- **[S14] ST-DS12110 — STM32H742xI/G and STM32H743xI/G datasheet**

  版本：Rev 11, January 2026; H743 core/cache scope only。访问/重读：2026-10-23；第一方：是。

  URL：https://www.st.com/resource/en/datasheet/stm32h743zi.pdf

  阅读位置/用途：PDF 页 1–3：H743 的 M7、缓存/存储能力范围；不据 F4 外推 RAM 域或 DMA 可达性。

- **[S15] ST-STM32CUBEMX — STM32CubeMX official software versions**

  版本：Fixed GUI reference STM32CubeMX-Win 6.18.1 found in official cached page; GUI not run。访问/重读：2026-10-23；第一方：是。

  URL：https://www.st.com/en/development-tools/stm32cubemx.sw-versions.html

  阅读位置/用途：官方缓存页中的 STM32CubeMX-Win 6.18.1；只作界面版本参照，不是本次 GUI 执行或安装版本证据。
<!-- END SOURCES -->

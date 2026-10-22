+++
title = "FreeRTOS 任务：静态创建、独立上下文与存储生命周期"
date = "2026-10-21T18:52:34+08:00"
lastmod = "2026-10-21T18:52:34+08:00"
summary = "能够以静态存储定义并创建一个持续运行的 FreeRTOS 任务，解释任务入口、参数、控制块与栈的所有权及创建到首次执行的调用链，并严格区分主机逻辑验证与 STM32F407xx 目标验证。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 41
tags = ["FreeRTOS", "任务", "静态分配", "STM32F407", "Host-Fake", "所有权"]
source_ids = ["FREERTOS-STATIC-TASK", "FREERTOS-IMPLEMENT-TASK", "FREERTOS-STATIC-MEMORY", "FREERTOS-SCHED-START", "FREERTOS-DELAY", "ST-STM32CUBEF4", "ST-RM0090", "ST-DS8626", "ST-PM0214", "ST-ES0182", "ST-UM1722", "ST-UM1725", "ST-UM1718", "ST-DS11532", "ST-DS14258", "ST-DS12110", "ST-STM32CUBEMX"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L041"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# L041｜FreeRTOS 任务：静态创建、独立上下文与存储生命周期

> 阶段：`rtos-concurrency`（FreeRTOS 与并发）；主题：`task`（任务）；建议 60 分钟，代码与实验可分两轮完成。
> **主机逻辑实验已执行；STM32 为参考实现，未编译、未烧录、未测量，`hardware_verified=false`。** 本课已完成 Reviewer 审查，状态为 `reviewed`（已审查）；来源与验证记录见本次运行目录。

## 1. 本节目标

能够以静态存储定义并创建一个持续运行的 FreeRTOS 任务，解释任务入口、参数、控制块与栈的所有权及创建到首次执行的调用链，并严格区分主机逻辑验证与 STM32F407xx 目标验证。

两项新核心概念与本次 `plan.json` 完全一致：

1. 任务是拥有独立执行上下文的长期运行单元。
2. 静态创建任务时，应用提供的控制块与任务栈必须在任务存续期间保持有效。

学完应能画出入口、参数、控制块、任务栈、句柄之间的关系；指出每个对象的定义位置、持有者、谁把地址交给谁；写出静态创建到首次执行的完整链路。这里的“学完应能”不是系统已认定你掌握。

本课不展开调度策略、队列、互斥量、通知、ISR 内核 API、动态内存分配器或 OSAL（操作系统抽象层）。优先级、延时与异常名称只是走通最小工程的辅助词汇；调度规则留给下一主题 `scheduler`。

## 2. 它解决什么问题

先区分两个需求：

- 做一次工作：普通函数调用，得到结果，返回原调用者。
- 一直承担工作：以后还要继续，保留当时的执行位置和临时状态，暂停后能接着执行。

裸机主循环也能承担长期工作，RTOS（实时操作系统）不是所有程序的必选项。任务带来的变化，是内核管理“一项工作从哪里继续、使用哪片栈”，不是给普通函数换名字。单核心 MCU 创建多个任务不会产生多个同时执行的处理器；具体如何交错下一课再解释。[S2][S6][S9]

可以把上下文想成“练习册做到哪、继续需要哪份草稿”。这个比喻只帮助理解可恢复的执行位置与栈，不意味着内核会自动保存所有外设、全局变量或缓冲区所有权。

本课只做计数工作，不接 GPIO、串口或传感器：成功输入加一，失败保持状态，达到上限不回绕。STM32 上输入明确固定为“成功”，不声称读过真实设备。这样先把任务对象和生命周期看清，再接入复杂外设。

## 3. 必要前置知识

状态记录已包含指针、存储期、编译链接、启动、栈、中断优先级、时钟树、HAL/LL/寄存器对照及主机/单元测试。本课复用它们，但不假定你学过 RTOS。

| 已有知识 | 本课用途 |
| --- | --- |
| 指针、存储期 | 地址传递不是复制对象；地址数值还在不表示对象还活着。 |
| 链接与 `.bss` | 静态控制块和数组在启动时初始化，存储期覆盖程序运行。 |
| 栈 | 任务有自己的栈；还要为异常处理另留主栈空间。 |
| 向量表、中断优先级 | 向量要接到正确内核端口，不能让空 SVC/PendSV 函数占位。 |
| 时钟树 | tick（内核节拍）的周期由真实计数时钟和重装值决定，不由宏名字保证。 |
| 单元测试 | 用真实核心、可控输入、独立期望值和非零失败退出码验证逻辑。 |

Device Framework（设备框架）仍是规划态；本课只建立对象/所有权基础，不引入框架或更新其进度。

## 4. 核心原理

### 4.1 最小可运行形态：先做一次业务步进

先不加载 RTOS。`core/worker.h` 声明数据和固定宽度整数接口；`core/worker.c` 实现一步工作。可运行入口是 `host/test_worker.c`，复跑命令在 8.1，完整代码在第 9 节。

```c
/* one_step 用例中的关键动作，CHECK 定义在完整测试入口内。 */
WorkerState state;
CHECK(Worker_Init(&state, 3U) == WORKER_OK);
CHECK(Worker_Step(&state, WORKER_INPUT_OK) == WORKER_OK);
CHECK(state.count == 1U && state.limit == 3U);
```

`CHECK` 是测试断言：条件错误就打印位置并非零退出，定义 `NDEBUG` 也不会消除。同步调用中，局部 `state` 在测试函数执行期间有效；这不允许把同样的局部地址交给稍后执行的任务。

### 4.2 再把一步业务装进长期入口

STM32 适配层的 `Worker_Entry(void *argument)` 接收业务对象地址，在循环里调用同一个 `Worker_Step`、记录观察量、请求暂停若干 tick。业务函数返回状态；**任务入口不正常返回**。[S1][S2][S5]

执行上下文是恢复执行需要的处理器状态，例如接下来执行的位置、寄存器和当前栈位置，不是整个 C 程序的拷贝。所选 GCC `ARM_CM4F` 端口按 Cortex-M4 规则建立、保存和恢复上下文，应用不用手写切栈汇编。[S6][S9]

### 4.3 三片长期存储与一个引用

| 对象 | 定义/持有者 | 谁传给谁 | 生命周期与边界 |
| --- | --- | --- | --- |
| `s_worker_state` | app_task.c 的静态业务状态，应用持有 | App_CreateTask 经 pvParameters 交给内核，内核首次执行传回入口 | 不深拷贝；持续访问期间必须有效。 |
| `s_worker_tcb` | 同文件 StaticTask_t，应用提供存储 | pxTaskBuffer 参数交给内核 | TCB（任务控制块）内部布局由内核管理，应用不自行改字段。 |
| `s_worker_stack` | 同文件 StackType_t[256]，应用提供存储 | 栈地址及元素数交给内核/端口 | 用于初始上下文和任务执行，不复用成普通数据缓冲。 |
| `g_worker_handle` | 同文件 TaskHandle_t 变量，应用保存返回值 | 内核返回引用 | 不是第二个 TCB，也不拥有另一片栈；本课不删除任务。 |

静态创建意味着应用提供存储，不意味着任务固定时刻执行，也不意味着内核会检查你的真实数组长度。栈元素数、对齐、有效期和独占使用都要满足约束。[S1][S3][S6]

### 4.4 static 解决有效期，不自动解决所有问题

文件作用域 `static` 限制链接可见性并给予静态存储期；函数内 `static` 对象同样有长期存储期。Idle 回调中的静态对象因此能在回调返回后继续使用。普通自动数组则不能。[S1][S3]

以下为**故意错误的只读反例，不进入构建**：

```c
void CreateAndReturn(void)
{
    StaticTask_t tcb;
    StackType_t stack[256];
    WorkerState state;
    (void)xTaskCreateStatic(Worker_Entry, "bad", 256U, &state,
                           1U, stack, &tcb);
} /* 三个自动对象的生命周期结束，任务却仍引用它们。 */
```

错误是消费者存活更久，不是“函数内不能定义对象”。改为静态后仍须保证足够大小和独占使用；不能把一份栈/TCB 同时交给两个存续任务。[S1][S6]

## 5. 关键术语与直观模型

| 术语 | 准确含义 | 不要理解成 |
| --- | --- | --- |
| task（任务） | 内核管理的长期执行单元，具有独立上下文 | 普通函数、硬件线程或独占 MCU。 |
| Task entry（任务入口） | void entry(void*)，由内核/端口启动，不正常返回 | main 在创建接口内同步调用一次。 |
| StaticTask_t / TCB | 静态控制块存储类型 / 任务管理状态 | 应用可随意改私有字段的业务结构。 |
| StackType_t | 端口的栈元素类型，本课为 uint32_t | 所有 RTOS API 的栈深度都以字节计。 |
| TaskHandle_t（任务句柄） | 内核返回的任务引用 | 复制句柄等于创建新任务。 |
| FreeRTOSConfig.h | 编译内核时的一致配置 | 写一个频率宏就自动切换硬件时钟。 |
| xTaskCreateStatic | 用入口、参数、栈和 TCB 建立任务 | 自动检查真实数组长度或栈容量。 |
| vTaskStartScheduler | 创建所需后台任务，进入端口启动路径 | 正常返回后靠主循环运行业务。 |
| SysTick（系统节拍定时器） | 内核计数器/异常源 | 经 APB 倍频后的 TIM 外设。 |
| SVC（系统服务调用异常） | 本课端口首次恢复任务的异常入口 | 可以留空的回调。 |
| PendSV（可挂起系统服务异常） | 所选端口上下文切换入口 | HAL 的任务切换函数。 |
| HAL / LL | 硬件抽象层 / 底层驱动 | FreeRTOS 内核或创建任务接口。 |
| Host Fake（主机模拟依赖） | 用可控 I/O 结果调用真实业务核心 | 已模拟 Cortex-M4 或验证真实调度。 |

这些词只支持两项核心概念的闭环，不额外开设调度策略课程。[S1][S2][S4][S6][S9][S12]

## 6. 从输入到结果的完整流程

### 6.1 五个动作分别在哪里

| 动作 | 文件/位置 | 含义 |
| --- | --- | --- |
| 声明 | core/worker.h、target/app_task.h | 说明接口，不创建任务。 |
| 实现 | core/worker.c、app_task.c 的 Worker_Entry | 定义一步业务与长期入口，仍不等于实例已经存在。 |
| 实例化 | app_task.c 的静态对象及 xTaskCreateStatic | 先有真实存储，再登记任务。 |
| 组装 | main.c、App_CreateTask | 选择时钟/配置，把入口、业务地址、栈和 TCB 连起来。 |
| 使用 | 内核调用入口，入口调用 Worker_Step | core 不反向包含目标/RTOS 头。 |

“注入参数”只指 App_CreateTask 把已有对象地址明确交给创建接口，不引入依赖注入框架。公开应用接口用固定宽度整数；RTOS/HAL 固有 ABI（应用二进制接口）保留原签名，不把 void* 或 TaskHandle_t 擅自改成整数。

### 6.2 创建到首次执行

```text
复位向量 -> Reset_Handler -> SystemInit + C运行时 -> main
  -> HAL_Init / HAL_InitTick -> SystemClock_Config
  -> 停止HAL节拍，清除待处理异常
  -> App_CreateTask
       -> Worker_Init(&s_worker_state, UINT32_MAX)
       -> xTaskCreateStatic(入口,名称,256元素,业务地址,优先级1,静态栈,静态TCB)
            -> prvInitialiseNewTask初始化TCB，并调用ARM_CM4F端口在任务栈建立初始上下文
            -> prvAddNewTaskToReadyList加入可运行集合
            -> 返回句柄（尚不等于入口执行过）
  -> vTaskStartScheduler
       -> vApplicationGetIdleTaskMemory -> 静态创建Idle
       -> xPortStartScheduler -> 内核异常优先级和SysTick
       -> prvPortStartFirstTask -> SVC -> 恢复上下文
  -> Worker_Entry(原业务地址)
       -> Worker_Step -> 观察值 -> vTaskDelay -> 以后继续循环
```

这是本课“启动前创建一个应用任务”的流程，不是所有运行期创建行为的通则。实际装栈、浮点现场和异常返回由端口与 PM0214 约束，图不授权你自行重写汇编。[S1][S4][S6][S9]

### 6.3 错误链必须真实存在

V10.3.1 静态创建对栈/TCB 空指针先执行 configASSERT；开启断言时，可能先停在断言出口，不会先给你 NULL。代码保留空句柄检查用于防御，但它不证明数组容量足够。声明了比数组更大的元素数可能破坏内存，不能靠返回值检查防住。[S1][S6]

```text
业务参数/输入错误 -> Worker状态码 -> 适配层记录或停机
HAL/时钟失败、创建断言或空句柄 -> App_Fatal
调度器意外返回 -> APP_FATAL_SCHED_RETURN
任务误返回 -> configTASK_RETURN_ADDRESS -> App_TaskReturned
栈检查触发 -> vApplicationStackOverflowHook -> APP_FATAL_STACK
```

App_Fatal 禁中断、保存错误码/行号并停住，不做复杂打印或恢复内核。严重破坏时连故障出口都可能无法可靠执行；HardFault 仍需按前课检查现场。

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

任务不是外设；此地图说明它与内核、异常和外设协作的范围。高级项交代问题、链路、配置入口和后续落点，不要求本课掌握其完整机制。[S6][S9][S11]

| 层次 | 原理、触发/数据/中断链路 | 本课入口与后续课程 |
| --- | --- | --- |
| 基础（本课深入） | 应用供存储 -> 内核建立上下文 -> 从入口开始长期执行 | 参数有效期、静态创建、句柄与首次入口。 |
| 进阶 | 等待或事件改变哪个上下文可以继续，内核决定当前执行者；数据也需明确交接 | 本课只调用相对延时；scheduler 深入就绪/阻塞/优先级；queue、notification 深入数据/事件。 |
| 高级：栈与内存 | 调用/异常现场消耗栈；高水位扫描未改写填充值；溢出检查只在检查点发现部分破坏 | 本课给观察值但不证明容量；memory 课做最坏路径、栈预算和分配策略。 |
| 高级：资源竞争 | 低优先级持有资源可能阻碍高优先级工作；互斥实现可在竞争链上临时调整持有者有效优先级 | 当前 configUSE_MUTEXES=0；mutex、priority-inversion 用具体持有/等待时序深挖。 |
| 高级：并发修改 | 两条交错路径读改写同一状态可能丢更新，volatile 不提供访问保护 | 本课保持单写者；race-condition 课设计可复现交错。 |
| 跨外设联动 | Timer TRGO（触发输出）-> ADC -> DMA -> IRQ（中断请求）；未来在中断到任务边界发布“数据可处理”，任务消费缓冲 | 当前没有这条硬件链，不引入 FromISR 接口；isr、notification 讲优先级、交接、丢事件和缓冲所有权。 |
| 跨系统低功耗 | 没有任务需立即执行时，端口可暂停周期 tick，唤醒后补算时间，不能简单删中断 | 本课 configUSE_TICKLESS_IDLE=0；scheduler 建立前提，low-power 课核对恢复链和测量。 |
| 系列差异 | 入口/所有权可迁移，端口、内存、缓存和安全配置需重新核验 | 见下表；本课没有完成 F7/H5/H7 端口构建。 |

**按具体器件比较，不把系列名当证据：**

| 参考对象 | 可复用 | 必须重新核对 |
| --- | --- | --- |
| F407（本课） | 业务步进、静态对象存续、参数借用原则 | Cortex-M4F/GCC 端口、4 个优先级位、16 MHz 时钟与普通 SRAM、异常连接。[S6][S7][S8][S9] |
| F767（F7 对照） | core 逻辑、入口+独立存储原则 | DS11532 指定 Cortex-M7 与 L1 缓存。重新选 M7 端口，核对 RAM/缓存属性、链接位置与缓冲边界，不沿用 ARM_CM4F 或虚构 cache 操作。[S14] |
| H563（H5 对照） | 存储所有权和参数生命周期 | DS14258 指定 Cortex-M33/TrustZone（信任区安全扩展）。先明确安全/非安全工程，再选相应端口、向量与可访问栈/TCB；时钟和优先级位数另核，不声称已完成安全域迁移。[S15] |
| H743（H7 对照） | 同一业务核心与有效期约束 | DS12110 指定 Cortex-M7 与缓存等器件资源。按具体内存域、总线可达性、缓存属性和单核端口重做链接/时钟核验，不推广为所有 H7 都相同；不猜域地址或 DMA 可达性。[S16] |

迁移可先复跑 core 的主机测试；但主机回归与新芯片内核/硬件正确是两个验收项。这里没有把“查到系列特性”当成“移植完成”。

### 7.2 参考目标与时钟/复位链

**STM32F407xx 为参考器件，不指定开发板或封装引脚。** 固定资料为 RM0090 Rev 22（2026-05）、DS8626 Rev 12（2026-03）、PM0214 Rev 10（2020-03）、ES0182 Rev 19（2026-07）与 CubeF4 基包 1.28.0 + 补丁 1.28.3。实际包内内核为 V10.3.1，端口 portable/GCC/ARM_CM4F，不称它是最新版。[S6][S7][S8][S9][S10]

真实包位置、文件指纹与阅读行号见 `evidence/source-audit.json`。包中 CMSIS-RTOS（Cortex 微控制器软件接口标准的 RTOS 接口）v1 头标注 V1.02/API 0x10002，v2 目录兼容头标注 V2.1.0/API 0x20001；**存在不代表使用**。本课不编译这两套包装器；UM1722 的历史包装例子不能代替固定内核签名。[S6][S11]

#### 7.2.1 从真复位开始，避免未知外部晶振

```text
器件复位 -> 启动/SystemInit -> HSI（内部高速RC，标称16 MHz）
                            PLL关闭，不参与本课
HSI -> SYSCLK = 16 MHz
      -> AHB /1 -> HCLK/内核 = 16 MHz
           -> APB1 /1 -> PCLK1 = 16 MHz
           -> APB2 /1 -> PCLK2 = 16 MHz
           -> SysTick选择处理器时钟 -> 16 MHz
                LOAD = 16,000,000 / 1,000 - 1 = 15,999
                标称tick周期 = (15,999+1)/16,000,000 = 1 ms
```

以上是配置算术，不是测量；HSI 偏差由数据手册约束。`pdMS_TO_TICKS(10)` 是换算到节拍，也不保证任务精确每 10 ms 执行。[S5][S7][S8][S9]

本课**不定义 configSYSTICK_CLOCK_HZ**：固定 ARM_CM4F port.c 在未定义时默认取 configCPU_CLOCK_HZ，并设置处理器时钟选择位。额外定义这个宏可能改变端口的时钟选择分支，不能只看数值相同就推断硬件路径相同。[S6]

`SystemCoreClock` 只是频率记录，不是硬件开关；`SystemCoreClockUpdate` 读时钟选择/分频重算它；`configCPU_CLOCK_HZ` 引用该值，再与 `configTICK_RATE_HZ=1000` 一起决定重装值。硬件升到 84 MHz 却留 16 MHz 记录，会改变真实 tick，主机 Worker 测试看不到这个问题。[S6][S7]

#### 7.2.2 门控、复位、Flash 和主栈

- 没有任务的 `RCC_TASKEN`。SysTick 属于内核，不走 APB TIM 门控；由自身 ENABLE、TICKINT、CLKSOURCE 控制。[S7][S9]
- 本课不用 GPIO、TIM、DMA、串口，不虚构它们的时钟使能/复位。APB 链列出是为完整追踪，不代表 SysTick 经 TIM 倍频。[S7]
- 16 MHz 下选 FLASH_LATENCY_0；RM0090 §3.5.1 表 11 约束等待周期/供电。仍需确认实际供电符合 DS8626；本课关闭预取，不假定供电是 3.3 V。F4 Flash 加速器缓存不是 F7/H7 的通用 L1 D-cache。[S7][S8]
- 任务栈不替代 MSP（主栈指针）空间。固定端口恢复任务使用 PSP（进程栈指针），异常处理仍需主栈预算；嵌套异常、浮点现场、链接布局影响总 RAM。[S6][S9]

#### 7.2.3 HAL 与 FreeRTOS 的阶段交接

为不额外引入一个 TIM 课，本课只在启动阶段使用 HAL 时基：

1. 创建前，唯一 SysTick_Handler 调用 HAL_IncTick，RCC 初始化等待/超时可用。
2. 时钟完成，关全局中断，HAL_SuspendTick，停 SysTick，清 VAL 与待处理 SysTick/PendSV。
3. 创建任务，设 g_kernel_owns_systick=1，进入调度器。
4. 固定端口配置 SysTick，并在首次启动路径重开中断；此后包装只调用 xPortSysTickHandler。[S6][S9]

**接管后 HAL 的 uwTick 不再更新。** 当前任务仅使用纯业务与 RTOS API，所以此受限策略成立；此后禁止 HAL_Delay、RCC 重配及依赖 HAL_GetTick 超时退出的 HAL 调用。若以后需要运行期 HAL 超时，应另外选择 HAL 时基定时器并补齐初始化、门控、IRQ/回调、优先级、错误路径，或经完整核验设计共享时基；这不是本课已实现的功能。[S6][S11][S12]

固定 HAL 的 HAL_Init 与 HAL_RCC_ClockConfig 都调用 HAL_InitTick，但未直接把该内部返回值作为自身失败返回。因此代码另显式检查 HAL_InitTick；不能用一次 HAL_Init()==HAL_OK 推出所有内部步骤成功。[S6]

#### 7.2.4 勘误的部署检查边界

ES0182 Rev 19 §2.1.1–2.1.3 涉及核心异常限制，§2.1.2 包含浮点除法/开方与很短 ISR 的条件，§2.2.3 涉及 Stop 调试与 SysTick。本课不进入 Stop、不做业务浮点运算，但端口会开启浮点支持和延迟保存配置；不能据此宣布全部勘误不适用。取得实际芯片修订号后，应结合反汇编、异常序列和负载逐项判断条件/规避方法，本课不修改全局选项冒充已排除风险。[S6][S10]

### 7.3 CubeMX、HAL、LL 与寄存器对照

#### 7.3.1 CubeMX 配置清单

固定 GUI（图形界面）参考分支为 STM32CubeMX-Win 6.18.1；官方缓存确有该版本。UM1718 Rev 51 用于核对配置、时钟、NVIC 和生成页面。**本次没有启动 GUI 或生成 .ioc。** 菜单名按实际版本核对，不把 CubeMX2 混作同一界面。[S13][S17]

| 区域 | 参考输入 | 工程检查 |
| --- | --- | --- |
| MCU Selector | 按用户实际订货号选 F407，代码器件宏 STM32F407xx | 确认容量/封装/供电/启动文件/链接脚本，不杜撰板型。 |
| RCC / Clock Configuration | HSI开，HSE/LSE不用，PLL不用，SYSCLK=HSI，AHB/APB1/APB2都 /1 | HCLK/PCLK标称均16 MHz，不填写不存在的外部晶振。 |
| SYS / Debug | 按实际调试器选择项目调试方式 | 不虚构调试引脚或改板级电路。 |
| SYS timebase | 启动保留默认SysTick，不选TIM时基 | 排除覆盖HAL_InitTick的时基文件，按本课明确接管。 |
| Middleware / FreeRTOS | **主路径关闭自动RTOS包装生成，手工加入固定内核及本课配置** | 保证原生API，不同时编译默认CMSIS任务。若GUI用于查看参数，可静态开、动态关、定时器关，但不混入其生成包装。 |
| 静态内存 | configSUPPORT_STATIC_ALLOCATION=1、动态=0 | 应用与Idle都提供静态存储，不加heap文件。 |
| tick | 1000 Hz，取HCLK，tickless关 | 唯一SysTick包装，接管后LOAD=15999。 |
| NVIC（嵌套向量中断控制器） | Group 4，SVC初始逻辑优先级0，PendSV/SysTick逻辑15 | F407为4个优先级位；端口最终设置内核异常优先级。 |
| Project Manager | 固定包/补丁及工具链，项目内保留应用代码 | 不改全局设置，重生成后检查重复符号/第二份配置头。 |

这里排除 CMSIS 包装，是选择一条可审计路径，不声称每个 GUI 都有“原生 FreeRTOS”下拉项。改用其 CMSIS 生成路径要重新核对栈单位、属性、入口、启动及依赖，不能混贴两层 API 参数。[S6][S11][S13]

#### 7.3.2 HAL 初始化字段和所有权

main.c 的两个 RCC 结构是同步初始化参数，HAL 在调用期间读取，不是长期任务参数；这与内核保存 pvParameters 指针的有效期要求不同。[S1][S6]

| 实际字段 | 值与理由 |
| --- | --- |
| OscillatorType | 仅HSI，不根据未知板卡配置HSE/LSE。 |
| HSIState / HSICalibrationValue | HSI开、参考包默认微调；默认不表示零误差。 |
| PLL.PLLState | RCC_PLL_OFF，不填无用M/N/P/Q。 |
| ClockType | 同时选择SYSCLK/HCLK/PCLK1/PCLK2，不只是写SYSCLK来源。 |
| SYSCLKSource | RCC_SYSCLKSOURCE_HSI。 |
| AHBCLKDivider | RCC_SYSCLK_DIV1，SYSCLK传到HCLK。 |
| APB1CLKDivider / APB2CLKDivider | 都RCC_HCLK_DIV1，16 MHz处于对应总线限制内。 |
| HAL_RCC_ClockConfig等待周期参数 | FLASH_LATENCY_0，受实际HCLK/电压约束，不照搬升频工程。 |

没有 TIM/UART/DMA 外设句柄，因为本课不用它们。g_worker_handle 是 FreeRTOS 引用，不是 HAL 句柄；本实现没有可替代创建任务的 HAL_*Task_Init。[S6][S7][S12]

#### 7.3.3 HAL → LL/寄存器/事件对照

这是语义映射，不是第二套应接着执行的初始化代码。不要先 HAL 再照表改一次硬件。LL 名称在固定包头核对过；异常切换不是 LL 外设驱动的职责。[S6][S7][S9]

| 当前操作 | LL / 硬件对照 | 关键判断 |
| --- | --- | --- |
| HAL_RCC_OscConfig的HSI | LL_RCC_HSI_Enable、LL_RCC_HSI_IsReady、LL_RCC_HSI_SetCalibTrimming；RCC_CR.HSION/HSIRDY/HSITRIM | 使能、就绪、微调不同；LL不自动提供同样的超时错误链。 |
| HAL_RCC_ClockConfig | LL_RCC_SetSysClkSource、SetAHBPrescaler、SetAPB1Prescaler、SetAPB2Prescaler（均LL_RCC_前缀）；RCC_CFGR.SW/SWS/HPRE/PPRE1/PPRE2 | SW请求、SWS实际来源；同时核对FLASH_ACR.LATENCY。 |
| HAL_Init / HAL_InitTick | 异常分组、SysTick配置与优先级 | SysTick.LOAD/VAL/CTRL，显式检查返回值。 |
| HAL_SuspendTick | 清SysTick.CTRL.TICKINT | 只暂停中断；交接还须停计数、清VAL及待处理位。 |
| 清旧异常 | SCB_ICSR_PENDSTCLR_Msk / PENDSVCLR_Msk | 直接写清除位，不对混合写一置/清寄存器随便读改写。 |
| vPortSetupTimerInterrupt | 端口配置SysTick | CLKSOURCE/TICKINT/ENABLE均为1，LOAD=15999；由实际工程再核验。 |
| SysTick处理 | 包装 -> xPortSysTickHandler -> 内核推进tick，必要时挂PendSV | SCB_ICSR.PENDSVSET是请求异常，不是HAL直接切栈。 |
| SVC / PendSV | port.c经宏映射提供处理器；SCB系统异常优先级寄存器 | 不能用普通C空函数覆盖端口汇编。 |

configLIBRARY_* 用未移位编号；4 位实现时 15 左移 4 得 0xF0，5 左移 4 得 0x50。不要把 0x50 传给接收未移位编号的 HAL_NVIC_SetPriority。本课没有外设 ISR 调 RTOS API，阈值使用规则在 isr 课推演。[S6][S9]

#### 7.3.4 IRQ / DMA / 回调边界

- 实际异常是 SysTick_Handler 及端口SVC/PendSV；第9节给出唯一包装与映射。[S6][S9]
- 实际内核回调是 vApplicationGetIdleTaskMemory、vApplicationStackOverflowHook，不是HAL DMA完成回调。[S6]
- 没有DMA传输、外设缓冲或HAL外设句柄，因此不伪造DMA回调/通道/请求号。后续真实外设到任务的链要重新核对IRQ、错误与所有权，当前不声称验证过。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

从仓库根 `D:\Automation\EmbeddedStudy` 复跑：

```powershell
& .\lessons\L041-freertos-static-task\host\run-tests.ps1 `
  -EvidenceDirectory .\.state\runs\20261021-185234841-34624\teacher-host-evidence `
  -BuildDirectory .\.state\tmp\L041-host-20261021-185234841-34624
```

脚本调用 `gcc -std=c11 -Wall -Wextra -Werror -pedantic`。本次编译器记录为 MSYS2 GCC 16.2.0；只链接 core/worker.c 和 host/test_worker.c，没有内核，没有把 x86 程序当 ARM ELF。

| 用例 | 它要抓的真实错误 |
| --- | --- |
| initial_state | 初始化清零、保存上限，抓漏初始化。 |
| one_step | 成功一步结果为1，抓空实现或漏更新。 |
| fake_failure_preserves_state | Fake先失败后成功，失败状态仍0，成功变1，抓忽略错误输入。 |
| exact_limit | 上限2，第三步拒绝且仍2，抓边界晚一拍。 |
| maximum_does_not_wrap | 从UINT32_MAX-1到最大值后拒绝，抓回绕。 |
| invalid_init_preserves_state | 零上限拒绝且保留原状态，抓先写后判断。 |
| null_arguments | 返回参数错误而非解引用。 |
| corrupt_state_is_rejected | 零上限/超界状态拒绝且不继续修改。 |

Fake只替代输入结果，断言查真实Worker状态，不断言Fake自己返回了99。核心不知道Fake存在，目标也不链接Fake。

本次真实执行结果：

| 实验 | 编译退出码 | 测试退出码 | 证据含义 |
| --- | --- | --- | --- |
| 起始未实现占位 | 0 | 1 | initial_state失败，先看测试能红；占位仅在运行目录。 |
| green | 0 | 0 | 8项业务用例通过。 |
| red-input-guard-removed | 0 | 1 | 临时副本删错误输入保护，失败用例抓到。 |
| red-limit-too-late | 0 | 1 | 临时副本把>=改成>，精确边界用例失败。 |
| final-green | 0 | 0 | 原版再次通过8项。 |

故意错误只在被忽略的构建目录副本中，未修改实际核心。脚本把“预期错误版本非零”作为负向实验结果，不隐藏它或冒称错误版通过。

本次运行目录 `teacher-host-evidence/host-results.json` 保存命令参数、二进制指纹、输出及退出码；各 `*-build.log`、`*-test.log` 留原始记录，起始失败见 red-test.log。**这些证据不含 FreeRTOS 创建/上下文切换、目标栈容量、tick精度或实际板运行。**

### 8.2 STM32 参考实现轨道

可接入源码在 target/，详细清单为 target/BUILDING.md。包含真正的静态任务、Idle供存储、时钟、节拍接管、异常与错误路径，不是硬件迁移展望。

| 类别 | 当前状态 |
| --- | --- |
| core/应用逻辑 | 已在主机编译运行，可直接复用。 |
| target/原创参考代码 | 依赖固定包，**未在目标工程编译**。 |
| 板级/项目输入 | 实际订货号、供电、链接容量/布局、调试器、工程构建系统仍需确认。 |
| 不依赖的硬件 | 不接GPIO、传感器、外部晶振或DMA，不虚构引脚/电路。 |
| 待取得证据 | ARM工具链、构建/链接输出、芯片修订号、另行授权后的下载和观察记录。 |
| 不允许的推断 | 主机绿色、源码可读、官方包存在、返回句柄，均不代表目标已成功。 |

先按实际芯片建立项目级空工程，加入代码与 BUILDING.md 中外部源，排除默认任务/重复异常处理；通过真实构建入口记录命令、输出、退出码和map。**本任务不执行烧录。** 未来用户另行确认板卡与授权后再下载并记录。首次入口核参数，连续运行后短暂停住看计数；长时间单步不是时延测量。


## 9. 最小代码示例

本节均为本课原创代码，完整文件就在给定相对路径，无需从文中拼接；公开应用接口用固定宽度整数，不使用动态内存。目标部分统一标记：**参考实现，待目标工程编译；未上板验证。**

```text
core/worker.h, worker.c              应用逻辑及声明
host/test_worker.c, run-tests.ps1    Fake、断言、正/负向实验
 target/main.c                      启动、时钟、内核组装
 target/app_task.h, app_task.c       适配、静态实例、创建、使用、内核回调
 target/FreeRTOSConfig.h             内核配置与异常映射
 target/interrupts.h, interrupts.c   唯一SysTick包装与阶段所有权
 target/app_fatal.h, app_fatal.c     固定宽度故障接口和停机观察
 target/stm32f4xx_hal_conf.h          HAL模块配置
 target/BUILDING.md                  外部源清单与接入要求
 lesson.json                        单课元数据和来源
 evidence/source-audit.json          阅读位置、版本、指纹
```

前导空格只是排版；所有路径都相对本课程。依赖是 main -> app_task -> core；适配层依赖内核/HAL，core 不依赖目标。Host 直接复用同一核心。

### 9.1 业务核心：声明和一步实现

对象由调用者持有。函数只在同步调用期间借用指针，不保存、不分配、不创建任务。


**`core/worker.h`**

```c
#ifndef L041_WORKER_H
#define L041_WORKER_H
#include <stdint.h>

#define WORKER_OK        UINT32_C(0)
#define WORKER_BAD_ARG   UINT32_C(1)
#define WORKER_IO_ERROR  UINT32_C(2)
#define WORKER_AT_LIMIT  UINT32_C(3)
#define WORKER_INPUT_OK  UINT32_C(0)

typedef struct {
    uint32_t count;
    uint32_t limit;
} WorkerState;

uint32_t Worker_Init(WorkerState *state, uint32_t limit);
uint32_t Worker_Step(WorkerState *state, uint32_t input_result);
#endif
```


**`core/worker.c`**

```c
#include "worker.h"
#include <stddef.h>

uint32_t Worker_Init(WorkerState *state, uint32_t limit)
{
    if ((state == NULL) || (limit == 0U)) {
        return WORKER_BAD_ARG;
    }
    state->count = 0U;
    state->limit = limit;
    return WORKER_OK;
}

uint32_t Worker_Step(WorkerState *state, uint32_t input_result)
{
    if ((state == NULL) || (state->limit == 0U) ||
        (state->count > state->limit)) {
        return WORKER_BAD_ARG;
    }
    if (input_result != WORKER_INPUT_OK) {
        return WORKER_IO_ERROR;
    }
    if (state->count >= state->limit) {
        return WORKER_AT_LIMIT;
    }
    state->count++;
    return WORKER_OK;
}
```


count上限和防回绕复用已学C/测试方法，不是本课新并发机制。同步测试可用局部对象；跨入长期任务改为适配层静态对象。

### 9.2 配置：固定ABI与后台存储前提


**`target/FreeRTOSConfig.h`**

```c
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H
#include "stm32f4xx.h"
#include "app_fatal.h"

#define configUSE_PREEMPTION                    1
#define configUSE_TIME_SLICING                  0
#define configUSE_PORT_OPTIMISED_TASK_SELECTION 1
#define configCPU_CLOCK_HZ                      (SystemCoreClock)
/* Do NOT define configSYSTICK_CLOCK_HZ: this port then selects HCLK. */
#define configTICK_RATE_HZ                      1000U
#define configMAX_PRIORITIES                    5U
#define configMINIMAL_STACK_SIZE                256U
#define configMAX_TASK_NAME_LEN                 12U
#define configUSE_16_BIT_TICKS                  0
#define configIDLE_SHOULD_YIELD                 0
#define configUSE_TICKLESS_IDLE                 0
#define configSUPPORT_STATIC_ALLOCATION         1
#define configSUPPORT_DYNAMIC_ALLOCATION        0
#define configUSE_TIMERS                        0
#define configUSE_MUTEXES                       0
#define configUSE_RECURSIVE_MUTEXES             0
#define configUSE_COUNTING_SEMAPHORES           0
#define configUSE_TASK_NOTIFICATIONS            0
#define configUSE_CO_ROUTINES                   0
#define configUSE_IDLE_HOOK                     0
#define configUSE_TICK_HOOK                     0
#define configCHECK_FOR_STACK_OVERFLOW          2
#define configUSE_MALLOC_FAILED_HOOK            0
#define configUSE_NEWLIB_REENTRANT              0
#define configUSE_TRACE_FACILITY                0
#define configGENERATE_RUN_TIME_STATS           0
#define configQUEUE_REGISTRY_SIZE               0U
#define INCLUDE_vTaskDelay                      1
#define INCLUDE_vTaskDelete                     0
#define INCLUDE_vTaskSuspend                    0
#define INCLUDE_uxTaskGetStackHighWaterMark      1
#define configPRIO_BITS                         __NVIC_PRIO_BITS
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
/* No alias for xPortSysTickHandler: interrupts.c supplies one wrapper. */
#endif
```


本课关闭软件定时器、互斥、通知、协程、tickless等不用功能，不把这份配置当完整产品功能集。configUSE_PREEMPTION=1 与单个应用优先级只是固定工程路径，不展开策略；INCLUDE_vTaskDelay=1 是延时接口所需开关。[S5][S6]

只调用应用的 xTaskCreateStatic 不足以说明全工程零动态分配：还须核对 Idle、可选定时器、包装和库。当前静态支持=1、动态=0，关闭定时器，不编译包装/heap，不使用动态库接口；**最终工程**是否零动态分配仍需目标链接/map审计。[S3][S4][S6]

若以后 configUSE_TIMERS 改为1，固定V10.3.1还需要 vApplicationGetTimerTaskMemory 静态回调、定时器配置和构建输入，不能只改开关。本课未启用或验证该服务链。[S6]


**`target/stm32f4xx_hal_conf.h`**

```c
#ifndef STM32F4XX_HAL_CONF_H
#define STM32F4XX_HAL_CONF_H
/* Original restricted configuration. External oscillators are NOT selected. */
#define HAL_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_FLASH_MODULE_ENABLED
#define HAL_PWR_MODULE_ENABLED
#define HSI_VALUE              16000000U
#define HSE_VALUE              0U
#define HSE_STARTUP_TIMEOUT    100U
#define LSI_VALUE              32000U
#define LSE_VALUE              0U
#define LSE_STARTUP_TIMEOUT    5000U
#define EXTERNAL_CLOCK_VALUE   0U
#define TICK_INT_PRIORITY      15U
#define USE_RTOS               0U
#define PREFETCH_ENABLE        0U
#define INSTRUCTION_CACHE_ENABLE 1U
#define DATA_CACHE_ENABLE      1U
#include "stm32f4xx_hal_rcc.h"
#include "stm32f4xx_hal_cortex.h"
#include "stm32f4xx_hal_flash.h"
#include "stm32f4xx_hal_pwr.h"
#define assert_param(expr) ((void)0U)
#endif
```


HSE_VALUE/LSE_VALUE=0 表示不提供且不选外部频率，不是声称板上晶振为零；选择外部源时必须按板修改。HAL的 USE_RTOS=0 是该HAL预留配置，不是FreeRTOS支持开关，不要改它来替代FreeRTOSConfig.h。[S6]

### 9.3 任务适配：对象、参数、创建与回调


**`target/app_task.h`**

```c
#ifndef L041_APP_TASK_H
#define L041_APP_TASK_H
#include <stdint.h>
/* App API is independent of FreeRTOS typedefs. Call exactly once before start. */
void App_CreateTask(void);
extern volatile uint32_t g_task_entered;
extern volatile uint32_t g_task_count;
extern volatile uint32_t g_task_result;
extern volatile uint32_t g_task_tick;
extern volatile uint32_t g_task_stack_free_words;
#endif
```


**`target/app_task.c`**

```c
#include "FreeRTOS.h"
#include "task.h"
#include "worker.h"
#include "app_fatal.h"
#include "app_task.h"
#include <stddef.h>

#define APP_STACK_WORDS UINT32_C(256)
static StaticTask_t s_worker_tcb;
_Alignas(8) static StackType_t s_worker_stack[APP_STACK_WORDS];
static WorkerState s_worker_state;
TaskHandle_t g_worker_handle;
volatile uint32_t g_task_entered;
volatile uint32_t g_task_count;
volatile uint32_t g_task_result;
volatile uint32_t g_task_tick;
volatile uint32_t g_task_stack_free_words;
_Static_assert(sizeof(StackType_t) == 4U, "L041 selects GCC ARM_CM4F");

/* RTOS adapter: receives an address whose storage outlives this task. */
static void Worker_Entry(void *argument)
{
    WorkerState *state = (WorkerState *)argument;
    if (state != &s_worker_state) {
        App_Fatal(APP_FATAL_WORKER, (uint32_t)__LINE__);
    }
    g_task_entered = 1U;
    for (;;) {
        /* No physical I/O is claimed: OK is an explicit synthetic input. */
        uint32_t result = Worker_Step(state, WORKER_INPUT_OK);
        g_task_result = result;
        if ((result != WORKER_OK) && (result != WORKER_AT_LIMIT)) {
            App_Fatal(APP_FATAL_WORKER, (uint32_t)__LINE__);
        }
        g_task_count = state->count;
        g_task_tick = (uint32_t)xTaskGetTickCount();
        g_task_stack_free_words = (uint32_t)uxTaskGetStackHighWaterMark(NULL);
        /* Nominal ten ticks; NOT a precise 10 ms periodic execution contract. */
        vTaskDelay(pdMS_TO_TICKS(10U));
    }
}
void App_CreateTask(void)
{
    if (g_worker_handle != NULL) {
        App_Fatal(APP_FATAL_TASK_CREATE, (uint32_t)__LINE__);
    }
    if (Worker_Init(&s_worker_state, UINT32_MAX) != WORKER_OK) {
        App_Fatal(APP_FATAL_WORKER, (uint32_t)__LINE__);
    }
    g_worker_handle = xTaskCreateStatic(Worker_Entry, "worker", APP_STACK_WORDS,
        &s_worker_state, (UBaseType_t)1U, s_worker_stack, &s_worker_tcb);
    if (g_worker_handle == NULL) {
        App_Fatal(APP_FATAL_TASK_CREATE, (uint32_t)__LINE__);
    }
}
/* V10.3.1 callback signature. Storage persists even after this function returns. */
void vApplicationGetIdleTaskMemory(StaticTask_t **tcb, StackType_t **stack,
                                 uint32_t *words)
{
    static StaticTask_t idle_tcb;
    _Alignas(8) static StackType_t idle_stack[configMINIMAL_STACK_SIZE];
    *tcb = &idle_tcb;
    *stack = idle_stack;
    *words = configMINIMAL_STACK_SIZE;
}
void vApplicationStackOverflowHook(TaskHandle_t task, char *name)
{
    (void)task;
    (void)name; /* Do not dereference possibly corrupted data or call printf. */
    App_Fatal(APP_FATAL_STACK, 0U);
}
```


创建参数逐项解释：[S1][S6]

1. Worker_Entry是实现地址，由内核调用，不在创建接口里同步做一次业务。
2. worker字符串是调试名称，不决定谁获得CPU。
3. APP_STACK_WORDS=256是元素数。此端口StackType_t为4字节，数组为1024字节；不要把sizeof数组的字节数直接传入。
4. &s_worker_state为长期业务地址，内核不深拷贝或延长自动对象寿命。
5. 优先级1在配置允许范围内；不在本课比较多个应用任务调度。
6. 栈与TCB各提供独占存储，创建后不能另作普通缓冲。
7. 句柄保存引用；g_task_entered被入口写成1前，不能说入口执行过。

vApplicationGetIdleTaskMemory 的输出分别是静态TCB、静态栈、栈元素数。实际至少有两个任务：应用与Idle（空闲任务），不是只写一个入口就只有一个任务。[S4][S6]

_Alignas(8)明确数组对齐，_Static_assert锁定32位栈元素假设，不代替链接与容量核验。uxTaskGetStackHighWaterMark(NULL)是当前任务历史最小剩余栈估计，单位为栈单元；本课未在目标调用得到数值。[S6]

vTaskDelay(pdMS_TO_TICKS(10U))说明任务长期存在不等于始终占CPU；相对延时叠加执行时间、中断和调度影响，不承诺精确10ms周期。[S5]

g_task_*是单写者调试观察值；volatile不提供互斥、跨核同步或一组字段的原子快照。本课不让其他任务/ISR共同修改s_worker_state。

### 9.4 时钟与异常组装：先启动时基，再接管


**`target/interrupts.h`**

```c
#ifndef L041_INTERRUPTS_H
#define L041_INTERRUPTS_H
#include <stdint.h>
extern volatile uint32_t g_kernel_owns_systick;
#endif
```


**`target/interrupts.c`**

```c
#include "stm32f4xx_hal.h"
#include "interrupts.h"
volatile uint32_t g_kernel_owns_systick;
extern void xPortSysTickHandler(void);

/* Exactly one SysTick_Handler definition in the linked image. */
void SysTick_Handler(void)
{
    if (g_kernel_owns_systick == 0U) {
        HAL_IncTick();
    } else {
        xPortSysTickHandler();
    }
}
/* SVC and PendSV come from port.c via FreeRTOSConfig.h, not empty C stubs. */
```


阶段标记在全局屏蔽期间切换，再进入固定启动路径；不在未启动时调用内核tick，不靠查询猜启动状态。SVC/PendSV由端口宏映射直接实现；应排除重复实体，不是从空C ISR普通调用切栈汇编。[S6][S9]


**`target/main.c`**

```c
#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"
#include "app_task.h"
#include "app_fatal.h"
#include "interrupts.h"
volatile uint32_t g_main_phase;

/* From a genuine reset/SystemInit path, not an arbitrary bootloader handoff. */
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
    if (SystemCoreClock != UINT32_C(16000000)) {
        App_Fatal(APP_FATAL_CLOCK, (uint32_t)__LINE__);
    }
    /* This Cube HAL does not propagate its internal HAL_InitTick status. */
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

    /* End HAL time-base phase. No HAL_Delay or timed HAL API after this point. */
    __disable_irq();
    HAL_SuspendTick();
    SysTick->CTRL = 0U;
    SysTick->VAL = 0U;
    SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk | SCB_ICSR_PENDSVCLR_Msk;
    __DSB();
    __ISB();
    App_CreateTask();
    g_kernel_owns_systick = 1U;
    g_main_phase = 3U;
    vTaskStartScheduler(); /* Selected ARM_CM4F port re-enables interrupts. */
    App_Fatal(APP_FATAL_SCHED_RETURN, (uint32_t)__LINE__);
}
```


g_main_phase：1已进main，2时钟就绪，3准备进入调度器；正常业务不靠启动调用之后的主循环执行。创建/交接时PRIMASK屏蔽，固定prvPortStartFirstTask包含重新开中断和SVC路径，不要提前放开尚未就绪的内核节拍。[S6]

这里假定真复位/SystemInit，不是任意Bootloader（引导加载程序）跳入后的未知时钟/待处理异常/向量状态；后续引导交接课必须重建前提。[S6][S7][S9]

### 9.5 错误出口：明确不返回


**`target/app_fatal.h`**

```c
#ifndef L041_APP_FATAL_H
#define L041_APP_FATAL_H
#include <stdint.h>
#define APP_FATAL_ASSERT          UINT32_C(1)
#define APP_FATAL_HAL_INIT        UINT32_C(2)
#define APP_FATAL_HAL_TICK        UINT32_C(3)
#define APP_FATAL_OSC             UINT32_C(4)
#define APP_FATAL_CLOCK           UINT32_C(5)
#define APP_FATAL_TASK_CREATE     UINT32_C(6)
#define APP_FATAL_SCHED_RETURN    UINT32_C(7)
#define APP_FATAL_TASK_RETURN     UINT32_C(8)
#define APP_FATAL_STACK           UINT32_C(9)
#define APP_FATAL_WORKER          UINT32_C(10)
extern volatile uint32_t g_error_code;
extern volatile uint32_t g_error_line;
_Noreturn void App_Fatal(uint32_t code, uint32_t line);
_Noreturn void App_TaskReturned(void);
#endif
```


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
    for (;;) { __NOP(); }
}
_Noreturn void App_TaskReturned(void)
{
    App_Fatal(APP_FATAL_TASK_RETURN, 0U);
}
```


入口误返回时，初始上下文的返回地址进入App_TaskReturned；依赖本端口对configTASK_RETURN_ADDRESS的支持，不能外推未经核对的端口。configCHECK_FOR_STACK_OVERFLOW=2只在检查点发现部分破坏，不是硬件保护，也不能把小栈变安全。[S6][S9]

### 9.6 主机Fake与可执行断言

Host不编译target；每个测试有独立的真实行为期望。脚本host/run-tests.ps1负责复跑和临时故意错误，不需要新测试框架。


**`host/test_worker.c`**

```c
#include "worker.h"
#include <stdint.h>
#include <stdio.h>

/* Each CHECK is a test assertion; unlike assert(), NDEBUG cannot remove it. */
#define CHECK(expr) do { if (!(expr)) { \
    fprintf(stderr, "FAIL line %u: %s\n", (unsigned)__LINE__, #expr); \
    return 1; } } while (0)
#define RUN(fn) do { if ((fn)() != 0) { return 1; } \
    puts("PASS " #fn); } while (0)

typedef struct { uint32_t failures_left; } FakeInput;
static uint32_t Fake_Read(FakeInput *fake)
{
    if (fake->failures_left != 0U) {
        fake->failures_left--;
        return UINT32_C(99);
    }
    return WORKER_INPUT_OK;
}

/* Removing initialization or accepting a zero limit must fail these tests. */
static int initial_state(void)
{
    WorkerState state = {42U, 42U};
    CHECK(Worker_Init(&state, 3U) == WORKER_OK);
    CHECK(state.count == 0U && state.limit == 3U);
    return 0;
}
static int one_step(void)
{
    WorkerState state;
    CHECK(Worker_Init(&state, 3U) == WORKER_OK);
    CHECK(Worker_Step(&state, WORKER_INPUT_OK) == WORKER_OK);
    CHECK(state.count == 1U && state.limit == 3U);
    return 0;
}
/* Removing the input-error guard must let this test catch state corruption. */
static int fake_failure_preserves_state(void)
{
    WorkerState state;
    FakeInput fake = {1U};
    CHECK(Worker_Init(&state, 3U) == WORKER_OK);
    CHECK(Worker_Step(&state, Fake_Read(&fake)) == WORKER_IO_ERROR);
    CHECK(state.count == 0U && state.limit == 3U);
    CHECK(Worker_Step(&state, Fake_Read(&fake)) == WORKER_OK);
    CHECK(state.count == 1U);
    return 0;
}
/* Changing >= to > must be caught at the exact limit. */
static int exact_limit(void)
{
    WorkerState state;
    CHECK(Worker_Init(&state, 2U) == WORKER_OK);
    CHECK(Worker_Step(&state, 0U) == WORKER_OK);
    CHECK(Worker_Step(&state, 0U) == WORKER_OK);
    CHECK(state.count == 2U);
    CHECK(Worker_Step(&state, 0U) == WORKER_AT_LIMIT);
    CHECK(state.count == 2U && state.limit == 2U);
    return 0;
}
static int maximum_does_not_wrap(void)
{
    WorkerState state = {UINT32_MAX - 1U, UINT32_MAX};
    CHECK(Worker_Step(&state, 0U) == WORKER_OK);
    CHECK(state.count == UINT32_MAX);
    CHECK(Worker_Step(&state, 0U) == WORKER_AT_LIMIT);
    CHECK(state.count == UINT32_MAX);
    return 0;
}
static int invalid_init_preserves_state(void)
{
    WorkerState state = {7U, 9U};
    CHECK(Worker_Init(&state, 0U) == WORKER_BAD_ARG);
    CHECK(state.count == 7U && state.limit == 9U);
    return 0;
}
static int null_arguments(void)
{
    CHECK(Worker_Init(NULL, 1U) == WORKER_BAD_ARG);
    CHECK(Worker_Step(NULL, 0U) == WORKER_BAD_ARG);
    return 0;
}
static int corrupt_state_is_rejected(void)
{
    WorkerState zero = {0U, 0U};
    WorkerState beyond = {4U, 3U};
    CHECK(Worker_Step(&zero, 0U) == WORKER_BAD_ARG);
    CHECK(Worker_Step(&beyond, 0U) == WORKER_BAD_ARG);
    CHECK(zero.count == 0U && zero.limit == 0U);
    CHECK(beyond.count == 4U && beyond.limit == 3U);
    return 0;
}
int main(void)
{
    RUN(initial_state);
    RUN(one_step);
    RUN(fake_failure_preserves_state);
    RUN(exact_limit);
    RUN(maximum_does_not_wrap);
    RUN(invalid_init_preserves_state);
    RUN(null_arguments);
    RUN(corrupt_state_is_rejected);
    puts("PASS total=8; logic only; no FreeRTOS kernel or MCU executed");
    return 0;
}
```


主机栈/C运行时与MCU不同，测试里根本没有TCB。通过范围仅限Worker输入/状态/错误边界，不包含静态任务创建和调度。

## 10. 常见错误

| 错误 | 为什么错 | 检查方法 |
| --- | --- | --- |
| 直接Worker_Entry(&state) | 同步进入循环，没有内核创建的独立上下文 | 看App_CreateTask是否走静态创建，不直接调用入口。 |
| 创建函数里用普通局部栈/TCB/参数再返回 | 任务仍引用已结束生命周期的存储 | 按对象表逐个标出定义与有效期。 |
| 栈参数1024，数组却只有256元素 | 原生API按元素，不按字节；句柄非空不能保边界。[S1] | 对照APP_STACK_WORDS，不把sizeof字节数当元素数。 |
| 只给应用任务内存，遗漏Idle回调 | 固定静态启动路径还要创建Idle。[S4][S6] | 查启动到Idle回调和链接错误。 |
| 混用CMSIS和原生栈/API参数 | 包装层属性单位和生命周期需另核 | 只留一条路径，改包装要重新查源。 |
| 生成文件与port都定义SVC/PendSV | 重复定义或错误空处理器覆盖 | map核对唯一符号归属、向量地址。 |
| 两份SysTick或未启动先调内核tick | 时基归属/内核就绪状态错误 | 唯一包装、阶段标记、屏蔽期间明确交接。 |
| 接管后用HAL_Delay或超时型HAL | 本课HAL毫秒时基已经停 | 检查运行期调用边界，不能靠关闭超时掩盖。 |
| 把15和0xF0混填NVIC | 未移位编号和寄存器编码不同 | 对照宏、HAL入参、实际异常优先级。 |
| 以为static或volatile保证并发安全 | 存储期/可见性不保护读改写 | 当前保持一个写者，不使用未实现的同步。 |
| 任务return或等待main收尾 | 任务不是main普通调用的函数。[S2][S6] | 长期循环、误返回故障地址、启动后不应回main。 |
| 主机通过就设硬件验证true | 没运行目标内核/异常/时钟 | 两轨证据分开，当前保持false。 |

## 11. 调试观察点

以下均为**目标上的待执行步骤与预期检查**，不是本次观测记录：

1. main第一断点：启动文件、器件宏、SystemInit一致，g_main_phase从1开始，静态对象在.bss完成初始化。
2. 时钟后：RCC_CR.HSIRDY、RCC_CFGR.SWS/HPRE/PPRE1/PPRE2、SystemCoreClock=16000000；SW请求不能当成SWS实际状态。
3. 创建后：句柄有效、静态栈/TCB在链接预留区；栈范围256个本端口单元。不依赖TCB私有固定偏移。
4. Idle内存回调：输出静态对象与正确元素数，主机Worker测试不会跑到这里。
5. 首次SVC/入口：向量不是空函数；入口参数等于原业务对象地址，g_task_entered变1，任务开始使用自己的栈。
6. 接管后：SysTick.LOAD=15999，CLKSOURCE/TICKINT/ENABLE、内核异常优先级正确；连续运行后g_task_tick增长，HAL uwTick则刻意不再增长。
7. g_task_count增长只证明业务路径运行过，不要求与tick一一对应，也不把两次停机差值当精确周期。
8. g_task_stack_free_words只覆盖已走过路径；稀有异常、浮点现场、库调用、错误路径、Idle栈和MSP还须另核预算。
9. 故障先读g_error_code/line，再查PRIMASK、BASEPRI、向量及Fault现场，不先关断言或绕过返回值。

原理见端口、PM0214、RCC与勘误资料；具体观察必须和实际板/固件日志保存，不能靠猜补齐。[S6][S7][S9][S10]

## 12. 实战实验

### 实验A：先证明逻辑，再证明测试能抓错（主机可执行）

1. 执行8.1命令，检查正常8项与两项故意错误各有输出、退出码和二进制指纹。
2. 不读实现，口算上限2时前三步返回值/计数，再与exact_limit对照。
3. 解释Fake第一次失败为何还要检查状态不变，而不只看错误码。
4. 读两份临时故意错误，指出哪条断言抓到错误；不能把任意非零都当“负向实验成功”，要核对失败位置。

验收：正常版0；删错误输入保护与边界晚一拍两版均非零且命中预期断言；最终原版再0。仅验收业务逻辑。

### 实验B：存储生命周期纸面检查

把4.4错误例改成三份持久对象，指出创建传入的三个地址，回答：哪个是业务、TCB、栈？谁持有，谁借用？

如果以“main不返回”解释自动变量安全，固定端口启动时重设MSP又带来什么风险？为何本课统一静态，而非依赖原main栈碰巧未覆盖？[S6][S9]

验收：逐个解释有效期，不能拿地址数值不变作证。不要执行悬空对象的未定义行为来验证“好像能跑”。

### 实验C：目标创建到首次入口（待实际工程）

1. 按BUILDING.md接入，记录器件、包、工具链、链接脚本；先仅构建，检查异常符号唯一、静态存储落点和依赖。
2. 未获授权不下载。未来有实际板/调试器且获授权后，创建后断点记录入口标记尚未设置，再到入口核参数。
3. 连续运行后读观察值并保存真实日志，不将其当精确10ms周期测量。
4. 审计最终map是否引入malloc/pvPortMalloc、heap或第二套包装/内核；范围包括生成代码和库，不只本课源码。

验收：构建、下载、运行观察各有独立证据；没执行的格子写未执行。本次没有执行这些目标步骤，后续结果须由真实日志补入，课程审查通过不表示硬件验证通过。

### 实验D：受控故障出口（目标待执行，不做危险栈破坏）

可在未来独立实验副本/调试流程中检查App_TaskReturned或受控错误出口，确认错误码；若测试入口误返回，要保留配置的返回地址并记录真实行为。本次未执行。

不要把栈故意缩到极小来赌回调能救命，可能在检查前就破坏内核；memory课再按受控压力、链接边界和最坏路径规划容量实验。[S6][S9]

## 13. 自检题

先作答再看要点；答案/实验可作后续评估输入，生成本课不增加掌握度。

1. Worker_Step与Worker_Entry都是函数，为什么职责和返回约束不同？
2. 按“定义位置、持有者、谁传地址、有效期”解释业务参数、TCB、任务栈与句柄。
3. 此端口256栈元素多少字节？迁移先查什么？
4. 有效句柄为什么不证明入口执行、业务正确或栈足够？
5. Idle存储谁供给，为什么不能用回调普通局部数组？
6. 本课为什么没DMA回调？SysTick/SVC/PendSV实现分别在哪？
7. 接管后HAL_Delay为什么违反前提？可提出什么未实现的后续扩展？
8. Host Fake证明哪些逻辑，不能证明哪些目标行为？

<details>
<summary>核对要点（不是学习者已作答记录）</summary>

1. 同步一步业务可返回；任务入口由独立上下文启动，长期循环，不正常返回。
2. 三份长期存储由应用提供，组装函数把地址交内核；TCB/栈运行内容由内核/任务使用，参数对象仍由应用管理，句柄只是引用。
3. ARM_CM4F的StackType_t=uint32_t，因此1024字节；迁移先查端口类型和API单位，不猜包装层相同。
4. 本课在启动前创建，尚未首次执行；创建不验证真实数组容量或最坏路径。
5. 应用通过Idle静态回调提供，返回后仍须有效。
6. 没有DMA操作；interrupts.c唯一SysTick包装，port.c经宏映射提供SVC/PendSV。
7. HAL uwTick停止；未来可另设HAL定时器时基，但要补完整配置、IRQ/回调/错误链，不是本课已经实现。
8. 初始化、成功、失败保持、参数、边界/防回绕；不证明内核调度、异常现场、目标栈、真实时钟、下载或实机行为。

</details>

## 14. 面试题

**问1：任务与普通函数最重要差别？**

不要只说优先级。说明入口定义只是代码，实例还含内核管理状态、独立上下文与任务栈；内核负责启动，不正常返回。[S1][S2][S6]

**问2：不用动态内存为何仍可能启动/运行失败？**

静态不是自动正确。Idle存储、配置/断言、向量、栈大小/生命周期/链接位置都可能错误，创建返回值不能证明容量或端口正确。[S1][S4][S6]

**问3：传结构体指针时内核复制整个结构体吗？**

保存的是参数值，这里是地址；对象有效期和并发访问仍要应用负责，不是内核替你复制/续命。[S1][S6]

**问4：两套tick都叫1ms就能直接混用吗？**

不能从周期名称推断所有者、启动条件和策略相同。先说明本课HAL启动阶段、明确接管、接管后禁用超时HAL，再讨论需要另设计时基的真实场景。[S6][S9][S11]

**问5：说验证过时究竟是哪层证据？**

先报执行的程序、命令、输出/退出码，再列未覆盖。主机测试、目标编译、下载、实机观察、时序测量不是一个等级；本次只存在主机逻辑与来源核对证据。

## 15. 延伸思考

- 两个任务可复用同一入口时，为什么不能复用一份栈/TCB？能否共享参数对象还需哪些访问约束？本课不实现第二个任务。
- 无GPIO也能以入口标记/计数建立观察闭环，为什么仍不能证明实时性？
- core已适合主机测试，任务包装为何还需真内核/目标验证？列三个主机看不到的故障。
- 下一课画调度时间线应从哪个时刻开始？不要用“优先级高就永远先跑”代替条件分析。
- F407转H563仅改频率为何不够？先列端口、安全域和可访问存储的核对资料，不猜寄存器值。

这些是后续问题，不是额外要求本课一次掌握的概念。

## 16. 本节总结

只带走两点：

1. **任务是拥有独立执行上下文的长期运行单元。** 入口定义不是实例，创建不是首次执行，一步函数返回与长期入口不返回各有职责。
2. **静态创建任务时，应用提供的控制块与任务栈必须在任务存续期间保持有效。** 本课也把业务参数置于持久存储；地址传递、保存引用、拥有对象不能混为一谈。

现在已有可复跑的主机逻辑测试与具备版本/时钟/配置/异常/Idle/错误出口的F407参考实现。只有主机轨道有运行结果；目标仍未编译/未上板。课程审查通过仅登记内容完成并推进下一主题，不表示已掌握；项目进度与掌握度保持原值。

## 17. 下一步

下一主题按路线为scheduler：以能创建并进入的任务为对象，解释就绪/等待/运行条件、优先级和切换时刻；不是立刻添加队列、互斥、通知或外设中断业务。

本次 Reviewer 结果与审查过程保存在仓库根目录下 `.state/runs/20261021-185234841-34624/review-result.json` 和 `review.md`；通过后 `completed` 追加 `task`，下一主题为 `scheduler`，课程序号为 42。`[mastery]` 保持原值。

## 18. 参考资料

统一访问/复读日期：**2026年10月21日**。本课固定参考版本，不宣称最新。lesson.json.sources均为config/source-policy.toml允许域的第一方来源。

FreeRTOS正文通过其官方Gatsby资源读取；PM0214/UM1722/ES0182本次下载到系统临时目录；其余手册/系列数据手册复读既有官方缓存。evidence/source-audit.json只记录身份、读取位置、指纹，不提交厂商完整源码。本次 Reviewer 复用这些缓存并复核文件指纹和关键调用位置，详见本次运行目录 `source-evidence.md`；来源覆盖、主机验证与目标构建分别记录。


- **[S1] FREERTOS-STATIC-TASK — FreeRTOS xTaskCreateStatic API**。Official page snapshot 2026-10-21; cross-checked with packaged kernel V10.3.1。
  URL：`https://www.freertos.org/Documentation/02-Kernel/04-API-references/01-Task-creation/02-xTaskCreateStatic`；第一方：是。

- **[S2] FREERTOS-IMPLEMENT-TASK — FreeRTOS implementing a task**。Official page snapshot 2026-10-21; TaskFunction_t contract checked against V10.3.1。
  URL：`https://www.freertos.org/Documentation/02-Kernel/02-Kernel-features/01-Tasks-and-co-routines/05-Implementing-a-task`；第一方：是。

- **[S3] FREERTOS-STATIC-MEMORY — FreeRTOS Static Vs Dynamic Memory Allocation**。Official page snapshot 2026-10-21; config switches checked against V10.3.1。
  URL：`https://www.freertos.org/Documentation/02-Kernel/02-Kernel-features/09-Memory-management/03-Static-vs-Dynamic-memory-allocation`；第一方：是。

- **[S4] FREERTOS-SCHED-START — FreeRTOS vTaskStartScheduler API**。Official page snapshot 2026-10-21; exact static Idle path checked in V10.3.1 tasks.c。
  URL：`https://www.freertos.org/Documentation/02-Kernel/04-API-references/04-RTOS-kernel-control/03-vTaskStartScheduler`；第一方：是。

- **[S5] FREERTOS-DELAY — FreeRTOS vTaskDelay API**。Official page snapshot 2026-10-21; INCLUDE_vTaskDelay and relative tick units checked in V10.3.1。
  URL：`https://www.freertos.org/Documentation/02-Kernel/04-API-references/02-Task-control/01-vTaskDelay`；第一方：是。

- **[S6] ST-STM32CUBEF4 — STM32CubeF4 official package and local fixed middleware**。FW.F4.1.28.0 + patch FW.F4.1.28.3; packaged FreeRTOS V10.3.1; GCC ARM_CM4F; no target build。
  URL：`https://www.st.com/en/embedded-software/stm32cubef4.sw-versions.html`；第一方：是。

- **[S7] ST-RM0090 — STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 reference manual**。Rev 22, May 2026。
  URL：`https://www.st.com/resource/en/reference_manual/dm00031020.pdf`；第一方：是。

- **[S8] ST-DS8626 — STM32F405xx / STM32F407xx datasheet**。Rev 12, March 2026。
  URL：`https://www.st.com/resource/en/datasheet/stm32f407vg.pdf`；第一方：是。

- **[S9] ST-PM0214 — STM32 Cortex-M4 MCUs and MPUs programming manual**。Rev 10, March 2020。
  URL：`https://www.st.com/resource/en/programming_manual/dm00046982.pdf`；第一方：是。

- **[S10] ST-ES0182 — STM32F405/407xx and STM32F415/417xx device errata**。Rev 19, July 2026。
  URL：`https://www.st.com/resource/en/errata_sheet/dm00037591.pdf`；第一方：是。

- **[S11] ST-UM1722 — Developing applications on STM32Cube with RTOS**。Rev 3, October 2019; historical wrapper examples, not the fixed kernel API authority。
  URL：`https://www.st.com/resource/en/user_manual/dm00105262.pdf`；第一方：是。

- **[S12] ST-UM1725 — Description of STM32F4 HAL and low-layer drivers**。Rev 8, March 2023; exact HAL behavior checked in fixed package。
  URL：`https://www.st.com/resource/en/user_manual/dm00105879.pdf`；第一方：是。

- **[S13] ST-UM1718 — STM32CubeMX for STM32 configuration and initialization C code generation**。Rev 51, May 2026; GUI not executed。
  URL：`https://www.st.com.cn/resource/en/user_manual/dm00104712-stm32cubemx-for-stm32-configuration-and-initialization-c-code-generation-stmicroelectronics.pdf`；第一方：是。

- **[S14] ST-DS11532 — STM32F765xx / STM32F767xx / STM32F768Ax / STM32F769xx datasheet**。Rev 9, July 2025; F767 core/cache scope only。
  URL：`https://www.st.com/resource/en/datasheet/stm32f767zi.pdf`；第一方：是。

- **[S15] ST-DS14258 — STM32H562xx and STM32H563xx datasheet**。Rev 6, May 2025; H563 core/TrustZone scope only。
  URL：`https://www.st.com/resource/en/datasheet/stm32h563zi.pdf`；第一方：是。

- **[S16] ST-DS12110 — STM32H742xI/G and STM32H743xI/G datasheet**。Rev 11, January 2026; H743 core/cache scope only。
  URL：`https://www.st.com/resource/en/datasheet/stm32h743zi.pdf`；第一方：是。

- **[S17] ST-STM32CUBEMX — STM32CubeMX official software versions**。Fixed GUI reference STM32CubeMX-Win 6.18.1 found in official cached page; GUI not run。
  URL：`https://www.st.com/en/development-tools/stm32cubemx.sw-versions.html`；第一方：是。


包内重点位置（精确行号和指纹在审计文件）：

- Middlewares/Third_Party/FreeRTOS/Source/include/task.h：版本、签名、参数、栈单位和高水位接口。
- tasks.c：xTaskCreateStatic、prvInitialiseNewTask、vTaskStartScheduler和Idle静态回调。
- portable/GCC/ARM_CM4F/port.c、portmacro.h：栈单元、初始上下文、误返回地址、首次SVC、PendSV/SysTick、时钟源分支与重装值。
- HAL stm32f4xx_hal.c、stm32f4xx_hal_rcc.c：时基、返回值边界、HSI和分频。
- stm32f4xx_ll_rcc.h、stm32f407xx.h、core_cm4.h、系统/启动文件：LL、优先级位、异常清除位、向量与时钟记录。

补充上游身份：`https://github.com/FreeRTOS/FreeRTOS-Kernel`；本次git ls-remote核对tag `V10.3.1-kernel-only` -> `88e32327e975ddde97c390bc5b6c1f8e7d9d239e`。仅用于明确来源身份，不计入许可域来源数量，也不宣称ST本地包与上游提交逐字相同。实际输入以本次读取的ST包指纹为准，仓库未复制任何完整第三方内核实现。

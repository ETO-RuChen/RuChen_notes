+++
title = "FreeRTOS 调度器：状态、固定优先级与切换边界"
date = "2026-10-22T16:23:04+08:00"
lastmod = "2026-10-22T16:23:04+08:00"
summary = "能够根据任务的就绪、阻塞状态与固定优先级，预测单核 FreeRTOS 的运行任务和切换时机，并在 STM32F407xx 参考实现中追踪节拍、异常与任务切换链，区分主机模型验证和目标硬件验证。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 42
tags = ["FreeRTOS", "调度器", "任务状态", "固定优先级", "STM32F407", "Host-Fake"]
source_ids = ["FREERTOS-STATES", "FREERTOS-SCHEDULING", "FREERTOS-DELAY", "FREERTOS-STATIC-TASK", "ST-STM32CUBEF4", "ST-RM0090", "ST-DS8626", "ST-PM0214", "ST-UM1725", "ST-UM1718", "ST-ES0182", "ST-DS11532", "ST-DS14258", "ST-DS12110", "ST-STM32CUBEMX"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L042"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# L042 | FreeRTOS 调度器：状态、固定优先级与切换边界

阶段：`rtos-concurrency`（FreeRTOS 与并发）；主题：`scheduler`（调度器）。FreeRTOS 是实时操作系统内核，本课讨论其**固定版本、单核**调度，不讨论多核调度。

交付边界：一篇课程、一个 `lesson.json`。课程审核状态以同目录 `lesson.json` 的 `status` 为准，`hardware_verified=false`。已执行的主机模型测试与主机 C 语法检查见第 8 节；STM32 代码是**参考实现，待目标工程编译；未烧录、未测量**。没有开发板信息，不假定引脚、外部晶振或电路。

## 1. 本节目标

**核心目标：能够根据任务的就绪、阻塞状态与固定优先级，预测单核 FreeRTOS 的运行任务和切换时机，并在 STM32F407xx 参考实现中追踪节拍、异常与任务切换链，区分主机模型验证和目标硬件验证。**

本课只新增两项核心概念，与本次 `plan.json` 一致：

1. 任务状态决定它能否进入调度候选集合。
2. 固定优先级抢占调度在可运行任务中选择执行者。

验收不是背诵状态名称，而是对给定优先级、配置和事件逐行写出：谁可运行、谁正在运行、为什么此刻需要或不需要重新选择。时间片和异常链用于解释这两项概念，不各自扩成一门新课。

建议主线 60 分钟：10 分钟手推时间线，15 分钟状态与优先级，15 分钟主机实验，20 分钟 F407 的时基/异常/任务代码。完整代码和目标接入作为同一篇的可复查材料；没有硬件时不把目标实验标为完成。

## 2. 它解决什么问题

上一课已经能静态创建任务，但“任务存在”不能回答“CPU 下一刻执行谁”。例如：

- High 任务每做一步就等待 3 个节拍；Low 任务一直有工作。High 是否霸占处理器？
- High 到期后变得可以运行，是否必然立刻出现在任务入口断点？
- 两个相同优先级任务都不等待，是否会轮流运行？改掉一个配置后结果为何不同？
- High 不断 `taskYIELD()`，Low 为什么仍可能一次也没运行？

先不加队列、通知、互斥量，也不靠串口打印“看起来同时运行”。只给任务状态、固定优先级和明确事件，先预测，再用可观察数据核对。[S1][S2][S5]

**约束**：单核在任务执行期间只有一个运行任务；异常处理会暂时占用处理器，这不是又多了一个并行任务。调度选择、异常请求和真正恢复任务指令是不同层次的事情。[S1][S8]

## 3. 必要前置知识

已学内容：L041 的静态任务入口、参数、任务控制块与栈；C 指针、静态存储、函数调用；启动、异常、中断优先级、时钟树与主机测试。这里沿用这些知识，不重新推进课程路线。

本课不要求已经学会队列、信号量、互斥、任务通知、ISR 内核 API、优先级反转或操作系统抽象层。它们只在能力地图标出后续落点，不出现在最小任务的通信路径中。

准备两个层次的材料：

| 轨道 | 已具备与仍需具备的依赖 | 结果的含义 |
| --- | --- | --- |
| 主机 | C11 编译器、PowerShell、同目录原创模型和测试；不需要板卡 | 验证有限状态模型的规则和错误出口，不运行真实内核 |
| STM32 | 官方固定 CubeF4 包可只读核对；实际板卡、ARM 工程、链接脚本、供电、调试器尚未确定 | 本文给足参考代码与步骤；真实构建和运行另留证据 |

不要把“源码可以读到”“语法可以解析”“程序能链接”“板上运行符合预期”合并成同一个通过结论。

## 4. 核心原理

### 4.1 先手推最小双任务时间线

先约定：High 优先级 2、Low 优先级 1，数字越大，**任务**优先级越高；抢占开启，两个任务已经创建。`tick`（内核节拍）初值 0。为便于纸上推演，暂把“提出选择请求→执行切换”折叠成同一行，不计异常延迟。

High 每执行一轮，调用一次 `vTaskDelay(3)`；Low 暂不阻塞。`vTaskDelay` 的参数是相对节拍数，不是毫秒，也不是处理器忙等次数。[S3][S5]

| 事件完成后 | High | Low | 运行者 | 解释 |
| --- | --- | --- | --- | --- |
| 启动，tick=0 | Running（运行态） | Ready（就绪态） | High | 最高优先级的可运行任务 |
| High 调用 `vTaskDelay(3)` | Blocked（阻塞态），到期值 3 | Running | Low | High 离开候选集合；不是“把 High 优先级调低” |
| tick=1 | Blocked | Running | Low | 没有新的更优候选，tick 不必导致换任务 |
| tick=2 | Blocked | Running | Low | 同上 |
| tick=3，到期处理 | Ready，随后被选中为 Running | Ready | High | 到期先改变状态；抢占规则请求重新选择 |
| High 下一次再次延时 | Blocked | Running | Low | 新的到期值以这次调用时的 tick 为基准 |

主机测试用任务编号 0 表示 High，1 表示 Low，所以第一条预期轨迹是 `0 → 1 → 1 → 1 → 0`。先遮住“运行者”列自己填写，再运行第 8 节命令。

### 4.2 核心概念一：状态先于优先级

状态不是给调试器看的装饰标签，而是能否参加选择的门槛：

```text
Running --调用 vTaskDelay(N>0)--> Blocked
Blocked --到期条件满足---------> Ready
Ready   --调度选择并恢复上下文--> Running
Running --被更合适任务替代-----> Ready
```

这里的候选集合包含正在运行者和其他就绪任务；阻塞任务不在其中。概念上把 Running 单列，**不表示内核一定有独立的 Running 链表**：所核对内核的当前任务通常仍在对应优先级的就绪链表，`pxCurrentTCB` 指向当前任务，`eTaskGetState` 对该对象报告 `eRunning`。[S1][S5]

| 问题 | 本课的具体答案 |
| --- | --- |
| 它解决什么问题 | 等待中的任务不必占用处理器，也不应被误选中 |
| 对象在哪里定义 | 应用静态定义栈、`StaticTask_t` 与句柄；状态链表、当前 TCB 指针和到期管理在固定包 `tasks.c` |
| 谁持有 | 应用持有存储空间和句柄引用；内核管理已创建任务的链表关系和调度状态 |
| 谁传入 | `xTaskCreateStatic` 把入口、参数、栈和 TCB 交给内核；任务通过 `vTaskDelay` 提交等待时长 |
| 调用怎样流动 | 运行任务调用延时→从就绪链移入延时链→请求选择；后续 tick 到期→重入就绪链→依据配置决定是否请求切换 |

阻塞不是删除：栈、局部变量和返回位置都要保留。再次运行时，从原来的延时调用之后继续，而不是重新创建任务或从入口第一行重新执行。[S4][S5][S8]

### 4.3 核心概念二：在候选中选最高固定优先级

默认抢占配置的预测方法：

1. 先从所有任务中排除 Blocked。
2. 找出剩余候选的最高任务优先级。
3. 若最高优先级只有一个候选，就选它；若有多个，再结合本次选择事件、同级顺序和时间片配置判断。
4. 把“要求切换”交给端口和异常系统，不把内核 C 函数当成直接跳到另一个入口的普通调用。

“固定”表示本课不给任务动态改优先级，也不按已经等待多久自动加分。Low 即使等了很久，也不会因为 tick 增加而超过始终就绪的 High。[S2][S5]

| 问题 | 本课的具体答案 |
| --- | --- |
| 它解决什么问题 | 多个任务都能运行时，让较高优先级工作先获得执行机会 |
| 对象在哪里定义 | 优先级在 `app_tasks.c` 创建参数中给定；策略在 `FreeRTOSConfig.h`；选择实现位于 `tasks.c` |
| 谁持有 | 内核 TCB 保存优先级、就绪结构与当前指针；应用持有句柄而不改内核私有链表 |
| 谁传入 | 应用通过静态创建函数传入优先级，构建时统一注入抢占/时间片配置 |
| 调用怎样流动 | 事件改变候选→`xTaskIncrementTick` 或 API 路径提出请求→PendSV→`vTaskSwitchContext`→端口恢复所选上下文 |

任务优先级数字越大越高；Cortex-M 异常优先级却是**数值越小越紧急**。High 的任务优先级 2 与 SysTick 的逻辑异常优先级 15 不在同一个坐标系，不能拿来互比。[S5][S8]

### 4.4 到期就绪、请求切换、真正执行不能画等号

High 延时到期只说明它重新成为候选。以下情况都可能让“到期”与“立刻执行”不同：

- `configUSE_PREEMPTION=0`：关闭自动抢占，Low 不阻塞、不让出时可继续运行；High 已 Ready，却尚未 Running。
- 正在处理异常或暂时屏蔽了相关异常：可以出现切换请求尚未兑现的窗口。较长屏蔽还会影响 tick 记账，不能默认过去多久就补齐多少次 SysTick。
- 若还有更高优先级任务就绪，High 也不是最高候选。

本课最小例不在任务中手工挂起调度器、不加长临界区，不引入 ISR 通信 API；这里只划清预测条件和后续调试边界。[S2][S5][S8]

### 4.5 同优先级与让出的边界

`time slicing`（同优先级时间片轮转）只在抢占开启、时间片开启且当前优先级不止一个可运行任务时，由周期 tick 触发轮换；它不是“每个任务每毫秒都执行一次”。更高优先级候选可以让同级组根本拿不到运行时间。[S2][S5]

以下为两个同级任务 A/B 的受控主机输入，初始选 A，期间没有其他事件：

| 配置与事件 | 逐步运行者 | 不应误解为 |
| --- | --- | --- |
| 抢占=1，时间片=1，连续 4 个 tick | A→B→A→B→A | 每人恰好得到同样指令数或 CPU 百分比 |
| 抢占=1，时间片=0，两个普通 tick | A→A→A | 不可能发生任何同级切换 |
| 接上一行，A 调用 `taskYIELD()` | B | 让给任意低优先级任务 |
| 接上一行，B 调用 `vTaskDelay(0)` | A，B 仍可运行 | B 阻塞了一个 tick |

`taskYIELD`（任务主动让出处理器）提出重新选择请求，调用者仍然就绪；若自己仍是唯一最高优先级候选，选回自己完全正确。`vTaskDelay(0)` 在固定版本中走让出路径，不进入延时链。**让出不保证 Low 得到 CPU；真正等待必须退出可运行集合。**[S2][S3][S5]

**固定包特有的核对点**：本机 CubeF4 的 V10.3.1 `tasks.c:2804` 在 tick 到期移回就绪链时，用 `唤醒任务优先级 >= 当前任务优先级` 请求切换；`tasks.c:2821` 才是单独的周期时间片条件。因此即使时间片为 0，A 阻塞、B 运行后，A 以相同优先级到期，仍可产生切换请求。测试专门覆盖这条边界。不能拿当前网上另一版本的 `>` 条件覆盖这份已核对源码，也不能只看版本字符串便假定文件相同。[S5]

### 4.6 饥饿不由增加 tick 或更多 yield 自动解决

High 优先级 2、Low 优先级 1；High 一直 Ready/Running，不阻塞，即使每轮 `taskYIELD()`，重新选择时最高候选仍是 High。Low 一直 Ready，却拿不到执行机会，这叫 `starvation`（饥饿）。这不是任务没有创建，也不是 tick 坏了。[S2][S5]

修复思路是让高优先级任务只在有工作时可运行；本课先用有限延时演示，后续 `queue`、`notification` 再实现事件驱动等待。不要把任意增加延时当成生产系统的万能修复；等待什么、谁发事件、缓冲区谁拥有，要在后续课明确。

## 5. 关键术语与直观模型

把处理器想成一个工作台。Ready 是“材料齐备、可以上台”，Running 是“当前占用工作台”，Blocked 是“等待材料或时间条件，暂不排队”。优先级只决定可上台者之间的选择，不会让缺材料的人凭优先级开始工作。

| 术语 | 准确含义与本课边界 |
| --- | --- |
| Running / Ready / Blocked | 运行态/就绪态/阻塞态；本课不操作挂起态或删除状态 |
| tick | 内核的离散时间计数；不是天然毫秒，也不等于一次上下文切换 |
| time slicing | 同级任务由 tick 触发的轮换策略，不是跨优先级公平分配 |
| taskYIELD | 主动提出重新选择，自己不因此阻塞 |
| TCB，Task Control Block | 任务控制块；内核维护任务状态、栈位置等信息所需的对象 |
| context switch | 上下文切换，保存当前执行现场并恢复另一个现场；不是普通业务函数调用 |
| SysTick | 内核侧系统节拍定时器及其异常；不是 APB 上的 TIM 外设 |
| PendSV | 可挂起系统服务异常，本端口用来执行上下文切换 |
| SVC，Supervisor Call | 系统服务调用异常，本端口启动首次任务时使用；不表示每个 FreeRTOS API 都经 SVC |
| HAL，Hardware Abstraction Layer | 硬件抽象层，负责本课的时钟/启动时基，不负责选择任务 |
| LL，Low-Layer drivers | 底层驱动，帮助对照 RCC 等寄存器动作；没有一个 LL 函数能替代内核调度器 |
| Host Fake | 主机模拟依赖；本课注入离散事件，验证预测模型，不模拟完整 Cortex-M 或真实 FreeRTOS |

这些词都服务于第 1 节两项概念，不要求在本课实现自己的调度内核或手写 PendSV 汇编。[S1][S2][S5][S8][S9]

## 6. 从输入到结果的完整流程

### 6.1 应用行为、内核决定、端口执行

```text
HighEntry
  → vTaskDelay(3)
  → tasks.c 将当前任务从就绪链移到延时链
  → API 请求 PendSV
  → 端口保存现场 → vTaskSwitchContext 选 Low → 端口恢复 Low

SysTick 硬件到零
  → 向量表中的唯一 SysTick_Handler
  → xPortSysTickHandler → xTaskIncrementTick
  → tick 增加，High 到期：延时链 → 就绪链
  → 满足配置/优先级条件：设置 SCB.ICSR.PENDSVSET
  → PendSV_Handler（端口）保存现场
  → vTaskSwitchContext 选择最高优先级候选
  → 端口恢复任务栈和现场 → 异常返回 → High 从延时之后继续
```

SVC/PendSV 与硬件自动保存部分寄存器、端口保存其他现场共同完成这条链。这里只读定位，不复制完整第三方代码，不把汇编保存/恢复重新发明为本课新目标。[S5][S8]

### 6.2 五个动作与依赖方向

| 动作 | 具体位置 | 所有权与生命周期 |
| --- | --- | --- |
| 声明 | `target/app_tasks.h`、`interrupts.h`、`app_fatal.h` | 只承诺接口/观察符号，不创建内核任务 |
| 实现 | `app_tasks.c` 入口、`interrupts.c` 包装、`app_fatal.c` 错误出口 | 应用适配依赖原生 FreeRTOS/HAL；内核与 HAL 来自官方包 |
| 实例化 | `app_tasks.c` 的两个栈、两个静态 TCB、参数与句柄 | 静态存储持续到复位；句柄不拥有可释放的堆块 |
| 组装 | `main.c` 先配置时钟/异常，再调用 `App_CreateTasks` | 将已存在的入口/存储/优先级传给创建函数；不运行入口函数本身 |
| 使用 | 内核首次恢复任务后执行 High/Low 入口 | 入口内调用 tick 查询、状态查询与延时；不能从入口正常返回 |

主机模型是独立教学层：测试持有 `SchedulerModel`，通过 `Model_Delay`、`Model_Tick`、`Model_Yield` 注入事件，模型不依赖 HAL 或 FreeRTOS 头文件。不要把模型链接进目标替代内核。

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

本课是内核与 SoC（片上系统）异常机制课，不把调度器伪装成一个普通外设；仍按硬件策略给出能力全景与后续落点。

| 层次 | 解决的问题、触发/数据/异常链 | 本课深度与后续落点 |
| --- | --- | --- |
| 基础 | 任务阻塞→候选减少；tick 到期→重新就绪；最高固定优先级候选获得执行 | 本课完整预测、建模并给 F407 参考代码 |
| 进阶 | 同级 tick 轮换与主动让出，影响同级等待；相对延时从每次调用处计算，周期唤醒围绕既定时间基准推进 | 本课只核对前两者；固定包周期 API 为 `vTaskDelayUntil`，默认未启用，队列超时在 `queue` 课继续 |
| 高级：饥饿与资源阻塞 | 高优先级持续可运行会压住低优先级；以后资源持有者可能阻塞更高任务，需追踪等待对象与持有者的优先级关系 | 本课验证饥饿；`mutex` 与 `priority-inversion` 再研究优先级继承，不在这里给未经该课核对的配置配方 |
| 高级：栈/内存预算 | 创建时交付静态栈/TCB→切换保存现场→最深调用/浮点现场消耗栈；内存越界可能伪装成调度错误 | 本课提供栈观察与错误出口；`memory` 课再核算最坏需求，历史最低空余量不是完整证明 |
| 高级：低功耗 | Idle 可用窗口→内核估计空闲时间→抑制周期 tick→外部/定时唤醒→恢复时间记账 | 本课 `configUSE_TICKLESS_IDLE=0`；后续 `low-power` 核对唤醒源、时钟恢复及端口补偿，不能只打开开关 |
| 跨外设联动 | Timer 触发→ADC 转换→DMA 写缓冲→IRQ（中断请求）→合规内核接口使任务 Ready→必要时 PendSV→任务处理缓冲 | 本课止于“事件改变候选”的接口边界；`isr`/`notification` 核对 FromISR API、IRQ 优先级和缓冲区所有权；这里没有虚构 DMA 回调 |
| 系列差异 | F4/F407 用 M4F 端口；F7/F767ZI、H5/H563ZI、H7/H743ZI 分别重查内核端口、时钟、安全与内存属性 | 本文第 8.2 节逐项给影响与核对动作，不能只替换器件宏 |

前两列的通用任务语义据 [S1][S2][S5]；与浮点/异常相关边界据 [S8][S11]；迁移样本范围据 [S12][S13][S14]。后续课名是课程路线落点，不宣称这些后续功能已经实现或验证。

### 7.2 参考目标与时钟/复位链

#### 7.2.1 固定参考，不借用未知板卡参数

参考器件：`STM32F407xx`，并未指定 VG 或任何开发板。资料固定为 RM0090 Rev 22、DS8626 Rev 12、PM0214 Rev 10、ES0182 Rev 19；HAL/Cube 依赖为本机实际核对的 CubeF4 基包 `1.28.0` 加补丁 `1.28.3`，打包 FreeRTOS `V10.3.1`，`portable/GCC/ARM_CM4F` 端口。[S5][S6][S7][S8][S11]

这些是本次读到的版本，不声称是所有网站/安装环境中的最新版本。PDF 使用官方既有缓存重新读取封面和关键页；在线调度与状态正文于 2026-10-23 读取。来源指纹和位置在本次运行目录 `teacher-work/source-audit.json`；没有把完整厂商源码放进课程。

#### 7.2.2 从真复位到最终 tick

```text
芯片真复位 / 匹配 SystemInit 与 C 运行时
  → 内部 HSI RC 振荡源，标称 16 MHz，确认 HSIRDY
  → PLL 关闭，未参与频率生成；HSE 未选用
  → SYSCLK 选择 HSI：16 MHz（标称）
  → AHB /1：HCLK = 16 MHz（处理器/总线时钟）
     ├─ APB1 /1：PCLK1 = 16 MHz
     ├─ APB2 /1：PCLK2 = 16 MHz
     └─ SysTick 选处理器时钟，CLKSOURCE=1：16 MHz
         → LOAD = (16000000 / 1000) - 1 = 15999
         → 每 16000 个源时钟周期产生一次节拍请求
         → 标称 tick 频率 1000 Hz，标称周期 1 ms
```

HSI（内部高速时钟）是 RC（电阻电容）振荡源，标称值不是测量值；温度、电压、校准都会影响实际频率。`SystemCoreClock`、`configCPU_CLOCK_HZ` 是软件描述，写成 16000000 不会校准硬件。[S6][S7]

本例没有 APB 定时器。RM0090 的 APB 定时器倍频规则不能用到 SysTick：SysTick 由自身时钟源选择决定，F407 可选 HCLK 或 HCLK/8，本端口默认不定义 `configSYSTICK_CLOCK_HZ`，因此选择 HCLK。若误选 HCLK/8 却保留 LOAD=15999，实际 tick 变成标称 125 Hz，任务等待尺度会扩大 8 倍。[S5][S6][S8]

复位和门控也要追踪清楚：

- HSI 就绪看 `RCC_CR.HSIRDY`；时钟切换结果看 `RCC_CFGR.SWS`，不只看写入的 `SW`。
- AHB/APB 分频分别看 `HPRE`、`PPRE1`、`PPRE2`。PLL 关闭，本例不填没有用途的 PLL M/N/P/Q 数值。
- SysTick 在内核侧，没有 `RCC_TASKEN` 或 RCC 上的“任务外设复位位”；运行由 `CTRL.ENABLE/TICKINT/CLKSOURCE` 控制，计数由 `VAL` 清零。
- 本例未用 GPIO、DMA、TIM、UART，不给它们虚构门控、复位或句柄。
- 16 MHz 时参考 `FLASH_LATENCY_0`；仍须按真实供电核对 RM0090 §3.5.1 表 11 与 DS8626 运行条件。本例禁用 Flash 预取，不假设供电为 3.3 V。F4 Flash 加速器的缓存开关不是 F7/H7 通用 L1 数据缓存。[S6][S7][S8]

#### 7.2.3 延时的真实尺度

在上述标称 1 kHz 配置，`vTaskDelay(3)` 把唤醒 tick 设为调用时计数加 3，不承诺“精确睡眠 3 ms”。在理想 tick、无额外延迟的连续时间模型中，若调用发生在两个 tick 之间，进入 Ready 的等待约为大于 2 个、至多 3 个 tick 周期；真正再次执行还要受更高任务、异常和屏蔽窗口影响。[S3][S5][S8]

High 的一轮工作花费时间后再相对延时，因此不是严格周期任务。若以后需要围绕固定节拍基准推进，固定版本的 `vTaskDelayUntil` 是待深入的对照，须开启对应配置并重新核对接口；本课没有悄悄改成另一版本的 API。[S5]

### 7.3 CubeMX、HAL、LL 与寄存器对照

#### 7.3.1 项目级 CubeMX 清单

GUI（图形界面）阅读参考固定为官方缓存页面中的 CubeMX-Win 6.18.1；本次没有运行 GUI 或生成 `.ioc` 工程。下表给配置值与最终代码/符号验收点，若实际 CubeMX2 或包版本的菜单不同，以输出代码复核，不能声称已点击验证。[S10][S15]

| 项目 | 本课配置 | 生成后必须核对 |
| --- | --- | --- |
| MCU（微控制器） | 选择真实订货号；参考族 STM32F407xx | 封装、容量、启动文件和链接脚本由真实芯片决定；本课不填假引脚 |
| RCC（复位与时钟控制） | HSI 开，默认校准；不选 HSE；PLL 关 | `RCC_OscInitTypeDef` 的四个实际使用字段 |
| Clock Configuration | SYSCLK=HSI；AHB/APB1/APB2 全 /1 | 标称 16/16/16 MHz；核对 SWS 与分频字段 |
| SYS 时基 | 启动阶段默认 SysTick，不选择 TIM HAL 时基覆盖 | 只有官方默认 `HAL_InitTick`；不编译另一个 `stm32f4xx_hal_timebase_tim.c` |
| FreeRTOS 集成 | 仅使用原生 API 与静态内存 | GUI 若只生成 CMSIS 包装，最终接入本课原生配置，不链接包装、默认任务或第二个调度启动入口 |
| 分配方式 | 静态=1，动态=0；软件定时器=0 | 两个静态应用任务、静态 Idle 回调；无 `heap_*.c` |
| 内核策略 | 默认抢占=1、时间片=1；tickless=0 | 核对唯一 `FreeRTOSConfig.h` 和完整重建后的宏；变体见第 12 节 |
| 任务优先级 | 范围 0..4；High=2、Low=1、Idle=0 | 与异常优先级分开；没有“每毫秒必跑 Low”的承诺 |
| tick | 1000 Hz、默认处理器时钟源 | `SystemCoreClock` 一致；内核启动后 LOAD=15999 |
| NVIC（嵌套向量中断控制器） | Group 4；SVC 逻辑优先级 0；PendSV/SysTick 逻辑优先级 15 | F407 实现 4 个优先级位；端口最终设置最低内核异常优先级 |
| 异常所有者 | SVC/PendSV=端口宏映射；SysTick=本课唯一包装 | 不保留生成文件中的同名强定义，不用空函数截走向量 |
| 板级参数 | 供电、订货号/容量、复位、调试器、实际构建入口待用户确定 | 没有板级 I/O 依赖，不需要虚构 LED/UART/晶振 |

GUI 的“启用 FreeRTOS”不等于自动生成了这里要求的原生静态工程；最终输入、宏和处理器归属比菜单截图更有约束力。[S5][S10]

#### 7.3.2 HAL 字段、顺序与句柄所有权

`RCC_OscInitTypeDef`、`RCC_ClkInitTypeDef` 是 `SystemClock_Config` 内的临时配置值，不是需要长期持有的外设句柄。任务句柄和栈/TCB 才由 `app_tasks.c` 长期持有。本例不需要 `TIM_HandleTypeDef` 或 `DMA_HandleTypeDef`，也没有 `HAL_Schedule` 之类的 API。[S5][S9]

| 字段/操作 | 值、意义与失败检查 |
| --- | --- |
| `OscillatorType` | `RCC_OSCILLATORTYPE_HSI`，只配置本例选定振荡源 |
| `HSIState`、`HSICalibrationValue` | 开 HSI，使用 HAL 默认校准常量；不承诺实际频率无误差 |
| `PLL.PLLState` | `RCC_PLL_OFF`，真复位路径下不把 SYSCLK 切到 PLL |
| `ClockType` | SYSCLK/HCLK/PCLK1/PCLK2 四项都配置，避免只改部分分频 |
| `SYSCLKSource` | HSI；HAL 等待切换状态，失败进时钟错误出口 |
| `AHBCLKDivider`、`APB1CLKDivider`、`APB2CLKDivider` | 全 /1，对应本课完整频率链 |
| `HAL_Init` | 设 Flash 相关开关、NVIC 分组、默认 HAL tick 并调用 MSP（底层硬件初始化）钩子；不能因为返回 `HAL_OK` 就认为内部时基检查通过 |
| 显式 `HAL_InitTick` | 本固定 HAL 的 `HAL_Init` 和 `HAL_RCC_ClockConfig` 忽略嵌套时基返回值，故本课在关键阶段显式调用并检查结果 |
| `HAL_RCC_OscConfig`、`HAL_RCC_ClockConfig` | 分别检查状态，失败记录振荡源或时钟错误；不继续启动内核 |
| `SystemCoreClockUpdate` | 依据时钟寄存器更新软件变量，不是测量频率；本课检查值及异常分组 |

这些行为按实际包中的 HAL 源码核对，不能把“同名 HAL 函数在其他版本也如此”当成事实。[S5][S9]

#### 7.3.3 SysTick 的单向交接

本课选择**先 HAL、再内核，交接后不再提供 HAL 毫秒时基**的最小方案，避免为了调度课引入另一个 TIM 外设。不是生产系统一律适用的时基方案。

| 阶段 | 唯一 SysTick 路径 | 能做什么 |
| --- | --- | --- |
| 真复位到 RCC 配置完成 | 包装检查阶段标记=0，调用 `HAL_IncTick` | HAL 初始化等待/超时有时基；尚不调用内核 tick |
| 关中断后的交接窗口 | `HAL_SuspendTick` 后再停计数、清 `VAL`，写 ICSR 清 SysTick/PendSV 挂起；创建静态任务，置阶段标记 | 没有窗口让旧 HAL tick 错跑进未初始化内核；此后不调用耗时 HAL API |
| `vTaskStartScheduler` 与首次任务 | 端口配置 SysTick 与异常优先级，首次启动路径重开中断并用 SVC 恢复任务 | 包装只调用 `xPortSysTickHandler`，内核自己的 tick 前进 |
| 任务运行期间 | 内核独占 SysTick | HAL 的 `uwTick` 刻意停止；禁止 `HAL_Delay` 和依赖 HAL 超时的外设调用 |

`HAL_SuspendTick` 只关闭 tick 中断请求，不等于已经完成停表、清计数、清挂起与所有权交接。`g_kernel_owns_systick` 是初始化阶段标记，不是一般同步原语，也不是通过轮询猜测内核是否启动。[S5][S8][S9]

若实际项目需要任务内使用 HAL 超时，应另选经过核对的独立 HAL 时基或完整协调方案，重新追踪其时钟/IRQ；不能在本例上直接加 `HAL_Delay`，也不要简单在包装内无条件同时调用两个 tick 处理器。

#### 7.3.4 HAL → LL/寄存器/内核事件对照

| 上层动作 | LL 或关键寄存器/状态 | 控制流与检查意义 |
| --- | --- | --- |
| HAL 配置 HSI | `LL_RCC_HSI_Enable`、`LL_RCC_HSI_IsReady`；`RCC_CR.HSION/HSIRDY/HSITRIM` | 开源、等就绪；LL 片段若单独使用仍需超时和错误处理，不可与 HAL 配置随意叠加 |
| 选择系统时钟 | `LL_RCC_SetSysClkSource`、`RCC_CFGR.SW/SWS` | 写选择，读实际切换结果 |
| 配置总线分频 | `LL_RCC_SetAHBPrescaler/SetAPB1Prescaler/SetAPB2Prescaler`；`HPRE/PPRE1/PPRE2` | 决定 HCLK/PCLK 与软件频率计算 |
| HAL 启动时基 | `SysTick.LOAD/VAL/CTRL`、SysTick 的 SHPR（系统异常优先级寄存器）字段 | 建立 HAL 1 ms tick；检查初始化返回值 |
| `HAL_SuspendTick` | 清 `CTRL.TICKINT` | 仅停中断；本课额外清计数和挂起位 |
| 端口 `vPortSetupTimerInterrupt` | `LOAD=15999`；`CTRL` 的 CLKSOURCE/TICKINT/ENABLE 都为 1 | 建立内核 1 kHz 节拍；不是 HAL 任务调度 |
| `xTaskIncrementTick` | `tasks.c` 的延时链、就绪链和切换请求返回值 | tick 增加与任务重新就绪；没有某个 RCC 寄存器能表示任务 Ready |
| 请求切换 | `SCB_ICSR.PENDSVSET` | 置位是请求，不是已经恢复另一个任务 |
| 执行切换 | `port.c` 的 PendSV、PSP（进程栈指针）、`pxCurrentTCB` 与 `vTaskSwitchContext` | 端口保存/恢复，内核选择对象；硬件异常返回继续任务 |
| 首次任务 | SVC、MSP（主栈指针）、PSP、向量表 | 按端口启动路径核对，不用空 C 函数替换 SVC |

本表的 LL 名称、源码行为据 [S5][S9]，寄存器/异常字段据 [S6][S8]；它是对照，不是要求把 HAL、LL 和直接寄存器操作连续执行三遍。

#### 7.3.5 IRQ、DMA 与勘误边界

实际使用的异常只有 SysTick、SVC、PendSV；本实验没有启用外设 IRQ、DMA 传输或 DMA 句柄，因此不存在需要实现的 DMA 完成/错误回调。静态 Idle 内存回调和栈溢出钩子在代码中给出，但它们不是 DMA 回调。后续的外设唤醒任务链必须在 `isr`/`notification` 课核对 FromISR 接口、异常优先级和数据所有权。[S5][S8]

F407 的 `configPRIO_BITS=4`，本例逻辑最低异常优先级 15、可调用内核的优先级边界常量 5，分别编码成 `0xF0`、`0x50`。这些常量用于所选端口校验与屏蔽，不授权本课不存在的 ISR 去调用任意内核 API。[S5][S8]

ES0182 Rev 19 §2.1.1–2.1.3 列出内核异常相关限制，§2.1.2 涉及浮点除法/开方与短 ISR，§2.1.3 涉及存储与异常返回组合；§2.2.3 涉及 Stop 调试和 SysTick。本例不进入 Stop、不做应用浮点运算，但端口会启用浮点支持与惰性保存，不能因此宣称排除了全部勘误。`interrupts.c` 在 C 包装返回前加 DSB（数据同步屏障），不等于审核了所有异常路径；实际修订号、端口反汇编、负载和规避条件仍需目标工程核对。[S5][S11]

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

#### 输入与独立预期

测试先写出字面量预期，再实现模型，不从模型函数计算“正确答案”。`CHECK` 失败打印表达式并返回 1，不依赖可能被关闭的 C `assert`。

| 测试 | 输入 | 独立预期/失败判据 |
| --- | --- | --- |
| 阻塞与到期抢占 | 优先级 2/1；0 延时 3；3 次 tick | `0→1→1→1→0`；阻塞期间选中 0 就失败 |
| 同级时间片开 | 优先级 1/1，连续 tick | 初始 0 后 `1,0,1,0`；不轮换失败 |
| 同级时间片关 | 普通 tick、yield、delay(0) | 普通 tick 保留当前者；yield/零延时切到同级另一任务，调用者仍就绪 |
| 关闭抢占 | High 延时 2，Low 运行，2 次 tick 后 Low yield | High 到期为 Ready，但 yield 之前仍运行 Low |
| 固定包同级到期边界 | 同级、抢占开、时间片关；0 延时 2 | `0→1→1→0`；覆盖本包 tick 唤醒 `>=` 条件 |
| 饥饿 | 高低优先级 2/1；高任务持续就绪；8 次 tick 和 yield | 每次仍选 0，1 一直 Ready；yield 意外让给低优先级就失败 |
| 低优先级到期 | 高任务先短暂等待，低任务进入更长等待，再推进 tick | 低任务到期不抢走已经运行的高任务 |
| 全部应用任务阻塞 | 单任务延时 2 | 模型返回 `MODEL_NONE`；不是让 Blocked 任务运行 |
| 输入/范围错误 | 空指针、容量越界、无效优先级/开关、tick 溢出边界 | 返回明确错误；溢出前拒绝操作，不静默伪造环绕结果 |

模型容量固定为 3，但本课调度轨迹只刻画上述单任务/双任务案例；它以固定数组顺序做同级轮换，不复刻内核链表插入历史。`MODEL_NONE` 表示没有应用候选；真实 FreeRTOS 会运行其 Idle（空闲）任务，**不是没有任何任务可调度**。本模型在无应用运行者时立即选择新就绪者，也不能据此外推关闭抢占时真实 Idle 的行为。

模型主动拒绝 32 位 tick 环绕；真实 V10.3.1 使用延时/溢出延时链表处理环绕，本课不模拟该实现。模型也不模拟中断屏蔽、挂起请求、异常开销、浮点保存、内核调度锁、动态创建、挂起、删除、SMP（对称多处理）。它是预测练习的有限模型，不是经过验证的 FreeRTOS 替身。[S5]

#### 可复现命令

在仓库根目录执行，构建/日志均落在本次运行目录，不改既有课程：

```powershell
& ./lessons/L042-freertos-scheduler/host/run-tests.ps1 `
  -EvidenceDirectory '.state/runs/20261022-162304649-8840/teacher-work/host-evidence' `
  -BuildDirectory '.state/runs/20261022-162304649-8840/teacher-work/build'
```

编译选项为 `-std=c11 -Wall -Wextra -Werror -pedantic`。本次实际编译器为 MSYS2 UCRT64 GCC 16.2.0；正向 9 项测试通过。还执行了独立错误预期，以及“反转优先级比较”“把固定包同级到期条件误写为严格大于”两个模型变异，全部编译成功并以测试退出码 1 被抓住，随后原代码再次通过。

```text
green                    build=0 test=0
wrong-expected           build=0 test=1  (expected failure)
red-reversed-priority    build=0 test=1  (expected failure)
red-equal-unblock-strict build=0 test=1  (expected failure)
final-green              build=0 test=0
PASS 9 scheduling-model tests; not FreeRTOS or target execution
```

详细命令、退出码、输出与指纹在 `teacher-work/host-evidence/host-results.json`。最初缺实现的桩已先被测试以退出码 1 拒绝，记录为 `teacher-work/red-test.log`。这些结果只证明原创模型和测试门禁，不证明内核或目标时序。

### 8.2 STM32 参考实现轨道

参考实现不依赖主机模型，也不是一句迁移展望：第 9 节给出全部应用/配置文件，同目录 `target/BUILDING.md` 给固定包输入清单、启动/链接要求、变体与实际工程步骤。

| 证据层 | 本次实际状态 | 不能推出的结论 |
| --- | --- | --- |
| 官方包/资料 | 读取版本、关键页、API 与源码位置，核对指纹 | 不能推出已经生成 `.ioc` 或得到最新在线包 |
| 主机 C 语法 | 用主机 GCC 对原创 target C 及固定包真实头文件做 `-fsyntax-only` 检查 | 不校验 ARM 指令、启动文件、链接脚本、向量、ABI 或板卡 |
| ARM 目标构建 | 未执行 | 不能说参考代码已在 CubeF4 目标工程编译/链接成功 |
| 下载与硬件观察 | 未执行，板卡与调试器未提供 | 没有波形、真实 tick 频率、实时延迟或板上结果；`hardware_verified=false` |

目标实验输入：实际 F407 芯片对应工程、明确供电与真复位路径、固定包/端口、统一编译宏；默认只有两个应用任务加 Idle。预期：High 每轮延时 3 tick，Low 在其阻塞期间增长；到期后 High 抢占 Low；关键寄存器和异常归属与第 7 节一致。失败：错误出口非零、tick 不前进、错误向量、Low 永不运行且不符合当前变体、栈/链接异常或配置不一致。不要用“看见计数在变”跳过这些检查。

迁移时只保留可迁移机制，不把 F407 的常量当成全系列事实：

| 样本 | 已由数据手册限定的事实 | 必须逐目标重查的动作 | 影响哪项证据 |
| --- | --- | --- | --- |
| F4 / F407xx | 本课 Cortex-M4F、HSI 标称 16 MHz 路径 | 实际订货号、修订号、供电、内存、工具链与对应勘误 | 本文目标构建和观察仍待做，不能由主机通过替代 |
| F7 / F767ZI | Cortex-M7；缓存/存储层次不同于 F407 [S12] | 适用 FreeRTOS M7 端口及内核修订、FPU/ABI、完整时钟、RAM 属性、缓存/调试行为；具体寄存器与配置待对应 RM/勘误/Cube 包核对 | 栈可达性、上下文正确性、真实 tick 和计数观察；不能照搬 ARM_CM4F 或 HSI 常量 |
| H5 / H563ZI | Cortex-M33，具有 TrustZone（可信安全隔离）及不同缓存范围 [S13] | 安全/非安全运行模型、适用端口、异常目标状态、向量、栈与内存安全属性；具体构建组合待专门资料核对 | 是否进入正确异常处理器、能否恢复任务、内存是否可访问；不能只换 MCU 宏 |
| H7 / H743ZI | 本样本为 Cortex-M7，具有 L1 指令/数据缓存 [S14] | 对应单核端口、时钟域和频率、各 RAM 域、链接放置、缓存与调试可见性；具体 RCC/缓存设置待 RM/勘误/Cube 包核对 | tick 标尺、栈/TCB 的有效访问和观察解释；不能把 H743 推广为全部 H7 的核数/存储配置 |

本课不用 DMA 缓冲，不因此声称“换到有缓存芯片也完全不受影响”。若以后接入 ADC/DMA，内存域、缓存一致性和缓冲区所有权须进入后续 `dma-coherency` 等课程证据。上述系列表只给已核实的器件范围与需要重新核对的动作，不提供未核实的移植配方。

## 9. 最小代码示例

本节展开同目录原创文件，以保证单页阅读也能追完整调用链。主机模型与目标实现是两套独立轨道，不能互相链接替代。代码默认静态存储、无动态内存；应用公开接口用固定宽度整数，官方回调保留固定版本要求的签名。

```text
model/scheduler_model.h, scheduler_model.c   有限调度预测模型
host/test_scheduler.c, run-tests.ps1         独立预期与正/负验证
target/FreeRTOSConfig.h                     唯一内核配置
target/stm32f4xx_hal_conf.h                  最小 HAL 配置
target/app_tasks.h, app_tasks.c             静态任务对象与入口
target/interrupts.h, interrupts.c           唯一 SysTick 包装
target/main.c                              时钟、交接与内核启动
target/app_fatal.h, app_fatal.c              可观察且不返回的错误出口
target/BUILDING.md                          参考构建/下载/观察检查单
```

<!-- L042-INLINE-BEGIN -->

### 9.1 主机模型：声明与完整实现

测试层持有静态容量的模型对象。接口用固定宽度整数，调用者先成功初始化再注入事件；同级次序仅覆盖已说明的受控案例。下列代码不是 FreeRTOS 源码。

**`model/scheduler_model.h`**

```c
#ifndef L042_SCHEDULER_MODEL_H
#define L042_SCHEDULER_MODEL_H

#include <stdint.h>

#define MODEL_CAPACITY UINT32_C(3)
#define MODEL_NONE UINT32_MAX
#define MODEL_READY UINT32_C(1)
#define MODEL_RUNNING UINT32_C(2)
#define MODEL_BLOCKED UINT32_C(3)
#define MODEL_OK UINT32_C(0)
#define MODEL_BAD_ARGUMENT UINT32_C(1)
#define MODEL_NO_CURRENT UINT32_C(2)
#define MODEL_RANGE UINT32_C(3)

typedef struct {
    uint32_t priority;
    uint32_t state;
    uint32_t wake_tick;
} ModelTask;

typedef struct {
    ModelTask tasks[MODEL_CAPACITY];
    uint32_t count;
    uint32_t current;
    uint32_t tick;
    uint32_t preemption;
    uint32_t time_slicing;
} SchedulerModel;

uint32_t Model_Init(SchedulerModel *model, const uint32_t *priorities,
                    uint32_t count, uint32_t preemption, uint32_t time_slicing);
uint32_t Model_Yield(SchedulerModel *model);
uint32_t Model_Delay(SchedulerModel *model, uint32_t ticks);
uint32_t Model_Tick(SchedulerModel *model);

#endif
```

**`model/scheduler_model.c`**

```c
#include "scheduler_model.h"
#include <stddef.h>

/* Bounded teaching model: no kernel lists, interrupts, tick wrap, or Idle task. */
static void SelectNext(SchedulerModel *m)
{
    uint32_t i;
    uint32_t best = MODEL_NONE;
    uint32_t start = m->current == MODEL_NONE ? 0U : (m->current + 1U) % m->count;
    if (m->current != MODEL_NONE) {
        m->tasks[m->current].state = MODEL_READY;
    }
    for (i = 0U; i < m->count; ++i) {
        uint32_t candidate = (start + i) % m->count;
        if (m->tasks[candidate].state == MODEL_READY &&
            (best == MODEL_NONE ||
             m->tasks[candidate].priority > m->tasks[best].priority)) {
            best = candidate;
        }
    }
    m->current = best;
    if (best != MODEL_NONE) {
        m->tasks[best].state = MODEL_RUNNING;
    }
}

uint32_t Model_Init(SchedulerModel *m, const uint32_t *priorities,
                    uint32_t count, uint32_t preemption, uint32_t time_slicing)
{
    uint32_t i;
    if (m == NULL || priorities == NULL || count == 0U ||
        count > MODEL_CAPACITY || preemption > 1U || time_slicing > 1U) {
        return MODEL_BAD_ARGUMENT;
    }
    for (i = 0U; i < count; ++i) {
        if (priorities[i] >= 5U) {
            return MODEL_BAD_ARGUMENT;
        }
    }
    *m = (SchedulerModel){0};
    m->count = count;
    m->current = MODEL_NONE;
    m->preemption = preemption;
    m->time_slicing = time_slicing;
    for (i = 0U; i < count; ++i) {
        m->tasks[i].priority = priorities[i];
        m->tasks[i].state = MODEL_READY;
    }
    SelectNext(m);
    return MODEL_OK;
}

uint32_t Model_Yield(SchedulerModel *m)
{
    if (m == NULL) {
        return MODEL_BAD_ARGUMENT;
    }
    if (m->current == MODEL_NONE) {
        return MODEL_NO_CURRENT;
    }
    SelectNext(m);
    return MODEL_OK;
}

uint32_t Model_Delay(SchedulerModel *m, uint32_t ticks)
{
    uint32_t old;
    if (m == NULL) {
        return MODEL_BAD_ARGUMENT;
    }
    if (m->current == MODEL_NONE) {
        return MODEL_NO_CURRENT;
    }
    if (ticks == 0U) {
        return Model_Yield(m);
    }
    if (ticks > UINT32_MAX - m->tick) {
        return MODEL_RANGE;
    }
    old = m->current;
    m->tasks[old].state = MODEL_BLOCKED;
    m->tasks[old].wake_tick = m->tick + ticks;
    m->current = MODEL_NONE;
    SelectNext(m);
    return MODEL_OK;
}

uint32_t Model_Tick(SchedulerModel *m)
{
    uint32_t i;
    uint32_t request = 0U;
    uint32_t peers = 0U;
    if (m == NULL) {
        return MODEL_BAD_ARGUMENT;
    }
    if (m->tick == UINT32_MAX) {
        return MODEL_RANGE;
    }
    ++m->tick;
    for (i = 0U; i < m->count; ++i) {
        if (m->tasks[i].state == MODEL_BLOCKED && m->tasks[i].wake_tick <= m->tick) {
            m->tasks[i].state = MODEL_READY;
            /* Characterizes the inspected CubeF4 V10.3.1 tick-unblock path. */
            if (m->current != MODEL_NONE && m->preemption != 0U &&
                m->tasks[i].priority >= m->tasks[m->current].priority) {
                request = 1U;
            }
        }
        if (m->current != MODEL_NONE && m->tasks[i].state != MODEL_BLOCKED &&
            m->tasks[i].priority == m->tasks[m->current].priority) {
            ++peers;
        }
    }
    if (m->preemption != 0U && m->time_slicing != 0U && peers > 1U) {
        request = 1U;
    }
    if (request != 0U || m->current == MODEL_NONE) {
        SelectNext(m);
    }
    return MODEL_OK;
}
```

### 9.2 主机测试：字面量预期与不变量

独立手推预期先于实现。每步检查运行者，并在主要轨迹检查只有一个 Running、Blocked 不被选中；负向入口故意给出错误答案，必须返回非零。

**`host/test_scheduler.c`**

```c
#include "scheduler_model.h"
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define CHECK(expr) do { if (!(expr)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #expr); return 1; \
} } while (0)
#define RUN(fn) do { if ((fn)() != 0) { return 1; } \
    puts("PASS " #fn); } while (0)

static int Invariant(const SchedulerModel *m)
{
    uint32_t running = 0U;
    uint32_t i;
    for (i = 0U; i < m->count; ++i) {
        if (m->tasks[i].state == MODEL_RUNNING) {
            ++running;
            CHECK(m->current == i);
        }
        if (m->tasks[i].state == MODEL_BLOCKED) {
            CHECK(m->current != i);
        }
    }
    CHECK(running == (m->current == MODEL_NONE ? 0U : 1U));
    return 0;
}

static int Test_BlockWakePreempt(void)
{
    SchedulerModel m;
    const uint32_t p[] = {2U, 1U};
    const uint32_t want[] = {1U, 1U, 0U};
    uint32_t i;
    CHECK(Model_Init(&m, p, 2U, 1U, 1U) == MODEL_OK);
    CHECK(m.current == 0U);
    CHECK(Model_Delay(&m, 3U) == MODEL_OK);
    CHECK(m.current == 1U && m.tasks[0].state == MODEL_BLOCKED);
    for (i = 0U; i < 3U; ++i) {
        CHECK(Model_Tick(&m) == MODEL_OK);
        CHECK(m.current == want[i]);
        CHECK(Invariant(&m) == 0);
    }
    CHECK(m.tasks[1].state == MODEL_READY);
    puts("TRACE block/wake: 0 -> 1 -> 1 -> 1 -> 0");
    return 0;
}

static int Test_EqualSliceOn(void)
{
    SchedulerModel m;
    const uint32_t p[] = {1U, 1U};
    const uint32_t want[] = {1U, 0U, 1U, 0U};
    uint32_t i;
    CHECK(Model_Init(&m, p, 2U, 1U, 1U) == MODEL_OK);
    CHECK(m.current == 0U);
    for (i = 0U; i < 4U; ++i) {
        CHECK(Model_Tick(&m) == MODEL_OK);
        CHECK(m.current == want[i]);
        CHECK(Invariant(&m) == 0);
    }
    puts("TRACE equal slice on: 0 -> 1 -> 0 -> 1 -> 0");
    return 0;
}

static int Test_EqualSliceOffYield(void)
{
    SchedulerModel m;
    const uint32_t p[] = {1U, 1U};
    CHECK(Model_Init(&m, p, 2U, 1U, 0U) == MODEL_OK);
    CHECK(Model_Tick(&m) == MODEL_OK && m.current == 0U);
    CHECK(Model_Tick(&m) == MODEL_OK && m.current == 0U);
    CHECK(Model_Yield(&m) == MODEL_OK && m.current == 1U);
    CHECK(Model_Tick(&m) == MODEL_OK && m.current == 1U);
    CHECK(Model_Delay(&m, 0U) == MODEL_OK && m.current == 0U);
    CHECK(m.tasks[1].state == MODEL_READY);
    CHECK(Invariant(&m) == 0);
    puts("TRACE equal slice off + yield/delay0: 0 -> 0 -> 0 -> 1 -> 1 -> 0");
    return 0;
}

static int Test_CooperativeReadyNotRunning(void)
{
    SchedulerModel m;
    const uint32_t p[] = {2U, 1U};
    CHECK(Model_Init(&m, p, 2U, 0U, 1U) == MODEL_OK);
    CHECK(Model_Delay(&m, 2U) == MODEL_OK && m.current == 1U);
    CHECK(Model_Tick(&m) == MODEL_OK && m.current == 1U);
    CHECK(Model_Tick(&m) == MODEL_OK && m.current == 1U);
    CHECK(m.tasks[0].state == MODEL_READY);
    CHECK(Model_Yield(&m) == MODEL_OK && m.current == 0U);
    CHECK(Invariant(&m) == 0);
    puts("TRACE cooperative: 0 -> 1 -> 1 -> 1(0 Ready) -> 0(yield)");
    return 0;
}

static int Test_EqualWakeSliceOffPackagedBoundary(void)
{
    SchedulerModel m;
    const uint32_t p[] = {1U, 1U};
    CHECK(Model_Init(&m, p, 2U, 1U, 0U) == MODEL_OK);
    CHECK(Model_Delay(&m, 2U) == MODEL_OK && m.current == 1U);
    CHECK(Model_Tick(&m) == MODEL_OK && m.current == 1U);
    CHECK(Model_Tick(&m) == MODEL_OK && m.current == 0U);
    CHECK(Invariant(&m) == 0);
    puts("TRACE packaged >= unblock, slice off: 0 -> 1 -> 1 -> 0");
    return 0;
}

static int Test_HigherReadyStarvesLowerEvenOnYield(void)
{
    SchedulerModel m;
    const uint32_t p[] = {2U, 1U};
    uint32_t i;
    CHECK(Model_Init(&m, p, 2U, 1U, 1U) == MODEL_OK);
    for (i = 0U; i < 8U; ++i) {
        CHECK(Model_Tick(&m) == MODEL_OK && m.current == 0U);
        CHECK(Model_Yield(&m) == MODEL_OK && m.current == 0U);
    }
    CHECK(m.tasks[1].state == MODEL_READY);
    CHECK(Invariant(&m) == 0);
    puts("TRACE starvation: 8 ticks + 8 yields, only task 0 selected");
    return 0;
}

static int Test_LowerWakeCannotPreempt(void)
{
    SchedulerModel m;
    const uint32_t p[] = {2U, 1U};
    CHECK(Model_Init(&m, p, 2U, 1U, 1U) == MODEL_OK);
    CHECK(Model_Delay(&m, 1U) == MODEL_OK && m.current == 1U);
    CHECK(Model_Delay(&m, 2U) == MODEL_OK && m.current == MODEL_NONE);
    CHECK(Model_Tick(&m) == MODEL_OK && m.current == 0U);
    CHECK(Model_Tick(&m) == MODEL_OK && m.current == 0U);
    CHECK(m.tasks[1].state == MODEL_READY);
    CHECK(Invariant(&m) == 0);
    return 0;
}

static int Test_OnlyBlockedMeansNoApplicationCandidate(void)
{
    SchedulerModel m;
    const uint32_t p[] = {1U};
    CHECK(Model_Init(&m, p, 1U, 1U, 1U) == MODEL_OK);
    CHECK(Model_Delay(&m, 2U) == MODEL_OK && m.current == MODEL_NONE);
    CHECK(Model_Delay(&m, 1U) == MODEL_NO_CURRENT);
    CHECK(Model_Yield(&m) == MODEL_NO_CURRENT);
    CHECK(Model_Tick(&m) == MODEL_OK && m.current == MODEL_NONE);
    CHECK(Model_Tick(&m) == MODEL_OK && m.current == 0U);
    CHECK(Invariant(&m) == 0);
    return 0;
}

static int Test_InputAndRangeErrors(void)
{
    SchedulerModel m;
    const uint32_t p[] = {2U, 1U, 0U};
    const uint32_t bad[] = {5U};
    CHECK(Model_Init(NULL, p, 2U, 1U, 1U) == MODEL_BAD_ARGUMENT);
    CHECK(Model_Init(&m, NULL, 2U, 1U, 1U) == MODEL_BAD_ARGUMENT);
    CHECK(Model_Init(&m, p, 0U, 1U, 1U) == MODEL_BAD_ARGUMENT);
    CHECK(Model_Init(&m, p, 4U, 1U, 1U) == MODEL_BAD_ARGUMENT);
    CHECK(Model_Init(&m, p, 2U, 2U, 1U) == MODEL_BAD_ARGUMENT);
    CHECK(Model_Init(&m, p, 2U, 1U, 2U) == MODEL_BAD_ARGUMENT);
    CHECK(Model_Init(&m, bad, 1U, 1U, 1U) == MODEL_BAD_ARGUMENT);
    CHECK(Model_Tick(NULL) == MODEL_BAD_ARGUMENT);
    CHECK(Model_Yield(NULL) == MODEL_BAD_ARGUMENT);
    CHECK(Model_Delay(NULL, 1U) == MODEL_BAD_ARGUMENT);
    CHECK(Model_Init(&m, p, 3U, 1U, 1U) == MODEL_OK);
    m.tick = UINT32_MAX - 1U;
    CHECK(Model_Delay(&m, 2U) == MODEL_RANGE);
    CHECK(m.current == 0U && m.tasks[0].state == MODEL_RUNNING);
    CHECK(Model_Tick(&m) == MODEL_OK);
    CHECK(Model_Tick(&m) == MODEL_RANGE && m.tick == UINT32_MAX);
    CHECK(Invariant(&m) == 0);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc == 2 && strcmp(argv[1], "--wrong-expected") == 0) {
        SchedulerModel m;
        const uint32_t p[] = {2U, 1U};
        CHECK(Model_Init(&m, p, 2U, 1U, 1U) == MODEL_OK);
        CHECK(m.current == 1U); /* Deliberately false: a test of the test gate. */
        return 0;
    }
    CHECK(argc == 1);
    RUN(Test_BlockWakePreempt);
    RUN(Test_EqualSliceOn);
    RUN(Test_EqualSliceOffYield);
    RUN(Test_CooperativeReadyNotRunning);
    RUN(Test_EqualWakeSliceOffPackagedBoundary);
    RUN(Test_HigherReadyStarvesLowerEvenOnYield);
    RUN(Test_LowerWakeCannotPreempt);
    RUN(Test_OnlyBlockedMeansNoApplicationCandidate);
    RUN(Test_InputAndRangeErrors);
    puts("PASS 9 scheduling-model tests; not FreeRTOS or target execution");
    return 0;
}
```

### 9.3 可复现主机执行器

这是主机工具层，只构建本课原创模型。变异副本与二进制写入调用者指定的构建目录，原课程文件不变；完整命令、指纹和结果写入证据目录。

**`host/run-tests.ps1`**

```powershell
param(
    [Parameter(Mandatory=$true)][string]$EvidenceDirectory,
    [Parameter(Mandatory=$true)][string]$BuildDirectory
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$lesson = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force -Path $EvidenceDirectory,$BuildDirectory | Out-Null
$evidence = (Resolve-Path -LiteralPath $EvidenceDirectory).Path
$build = (Resolve-Path -LiteralPath $BuildDirectory).Path
$source = Join-Path $lesson 'model/scheduler_model.c'
$test = Join-Path $PSScriptRoot 'test_scheduler.c'
$include = Join-Path $lesson 'model'
$records = [Collections.Generic.List[object]]::new()
& gcc --version 2>&1 | Set-Content -LiteralPath (Join-Path $evidence 'compiler-version.log')
if ($LASTEXITCODE -ne 0) { throw 'gcc unavailable' }

function Invoke-Case([string]$Name, [string]$ModelSource, [string[]]$RunArguments,
                     [bool]$ExpectPass, [string]$Failure = '') {
    $binary = Join-Path $build "$Name.exe"
    $arguments = @('-std=c11','-Wall','-Wextra','-Werror','-pedantic',
                   '-I',$include,$ModelSource,$test,'-o',$binary)
    & gcc @arguments 2>&1 | Set-Content -LiteralPath (Join-Path $evidence "$Name-build.log")
    $buildExit = $LASTEXITCODE
    if ($buildExit -ne 0) { throw "$Name build failed: $buildExit" }
    $output = @(& $binary @RunArguments 2>&1 | ForEach-Object { $_.ToString() })
    $testExit = $LASTEXITCODE
    $output | Set-Content -LiteralPath (Join-Path $evidence "$Name-test.log")
    $met = if ($ExpectPass) { $testExit -eq 0 } else {
        $testExit -ne 0 -and ($output -join "`n").Contains($Failure)
    }
    $records.Add([pscustomobject]@{
        name=$Name; compiler='gcc'; arguments=$arguments; run_arguments=$RunArguments
        model_source=$ModelSource; model_sha256=(Get-FileHash -LiteralPath $ModelSource).Hash.ToLowerInvariant()
        build_exit=$buildExit; test_exit=$testExit; expected_pass=$ExpectPass
        expected_failure=$Failure; expectation_met=$met; output=$output
    })
    Write-Output "$Name build=$buildExit test=$testExit expectation_met=$met"
    if (-not $met) { throw "Unexpected result: $Name" }
}

Invoke-Case 'green' $source @() $true
Invoke-Case 'wrong-expected' $source @('--wrong-expected') $false 'm.current == 1U'
$original = Get-Content -Raw -LiteralPath $source
$mutations = @(
    @{Name='red-reversed-priority'; Old='m->tasks[candidate].priority > m->tasks[best].priority';
      New='m->tasks[candidate].priority < m->tasks[best].priority'; Failure='m.current == 0U'},
    @{Name='red-equal-unblock-strict'; Old='m->tasks[i].priority >= m->tasks[m->current].priority';
      New='m->tasks[i].priority > m->tasks[m->current].priority';
      Failure='Model_Tick(&m) == MODEL_OK && m.current == 0U'}
)
foreach ($mutation in $mutations) {
    if (-not $original.Contains($mutation.Old)) { throw "Mutation anchor missing: $($mutation.Name)" }
    $path = Join-Path $build "$($mutation.Name).c"
    $original.Replace($mutation.Old, $mutation.New) | Set-Content -LiteralPath $path -Encoding utf8
    Invoke-Case $mutation.Name $path @() $false $mutation.Failure
}
Invoke-Case 'final-green' $source @() $true
[pscustomobject]@{
    recorded_at=(Get-Date -Format o)
    scope='Bounded C11 scheduling-model logic only; not tasks.c, Cortex-M exceptions, timing, or hardware'
    model_sha256=(Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant()
    tests_sha256=(Get-FileHash -LiteralPath $test).Hash.ToLowerInvariant()
    records=$records
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'host-results.json') -Encoding utf8
```

### 9.4 唯一内核配置与最小 HAL 配置

这是目标适配层的构建输入，应用、内核、端口必须看到同一份配置。默认关闭动态内存、软件定时器与未学通信机制；Idle 静态内存回调仍必需。`configUSE_*` 是本课策略，官方 API/回调签名不改写。[S5][S9]

**`target/FreeRTOSConfig.h`**

```c
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H
#include "stm32f4xx.h"
#include "app_fatal.h"

#ifndef APP_USE_PREEMPTION
#define APP_USE_PREEMPTION 1
#endif
#ifndef APP_USE_TIME_SLICING
#define APP_USE_TIME_SLICING 1
#endif
#define configUSE_PREEMPTION APP_USE_PREEMPTION
#define configUSE_TIME_SLICING APP_USE_TIME_SLICING
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
#define configUSE_TIMERS 0
#define configUSE_MUTEXES 0
#define configUSE_RECURSIVE_MUTEXES 0
#define configUSE_COUNTING_SEMAPHORES 0
#define configUSE_TASK_NOTIFICATIONS 0
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
/* No xPortSysTickHandler alias: interrupts.c supplies the unique wrapper. */
#endif
```

**`target/stm32f4xx_hal_conf.h`**

```c
#ifndef STM32F4XX_HAL_CONF_H
#define STM32F4XX_HAL_CONF_H

#define HAL_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_FLASH_MODULE_ENABLED
#define HAL_PWR_MODULE_ENABLED
#define HSI_VALUE 16000000U
/* External clocks are intentionally not selected in this reference. */
#define HSE_VALUE 0U
#define HSE_STARTUP_TIMEOUT 100U
#define LSI_VALUE 32000U
#define LSE_VALUE 0U
#define LSE_STARTUP_TIMEOUT 5000U
#define EXTERNAL_CLOCK_VALUE 0U
#define TICK_INT_PRIORITY 15U
#define USE_RTOS 0U
#define PREFETCH_ENABLE 0U
#define INSTRUCTION_CACHE_ENABLE 1U
#define DATA_CACHE_ENABLE 1U

#include "stm32f4xx_hal_rcc.h"
#include "stm32f4xx_hal_cortex.h"
#include "stm32f4xx_hal_flash.h"
#include "stm32f4xx_hal_pwr.h"
#define assert_param(expr) ((void)0U)
#endif
```

### 9.5 目标任务：静态实例、组装接口与使用

`app_tasks.c` 拥有两份静态栈/TCB、句柄与 High 的长期参数。创建只传引用，不调用入口，也不申请堆。参数为只读配置，因官方 API 接收 `void *` 而转型，入口不写它。每个计数只有其对应任务写，供调试器读；不把 volatile 当作任务间同步。Low 忙循环只用于显示选择边界，会压住 Idle，不是生产应用模式。[S4][S5]

**`target/app_tasks.h`**

```c
#ifndef L042_APP_TASKS_H
#define L042_APP_TASKS_H
#include <stdint.h>

#ifndef APP_EQUAL_PRIORITIES
#define APP_EQUAL_PRIORITIES 0
#endif
#ifndef APP_HIGH_ALWAYS_READY
#define APP_HIGH_ALWAYS_READY 0
#endif
#ifndef APP_HIGH_DO_YIELD
#define APP_HIGH_DO_YIELD 0
#endif
#ifndef APP_LOW_DO_YIELD
#define APP_LOW_DO_YIELD 0
#endif

extern volatile uint32_t g_high_passes;
extern volatile uint32_t g_low_iterations;
extern volatile uint32_t g_high_last_tick;
extern volatile uint32_t g_low_last_tick;
extern volatile uint32_t g_high_state_from_low;
extern volatile uint32_t g_high_stack_free_words;
extern volatile uint32_t g_low_stack_free_words;
uint32_t App_CreateTasks(void);
#endif
```

**`target/app_tasks.c`**

```c
#include "FreeRTOS.h"
#include "task.h"
#include "app_tasks.h"
#include "app_fatal.h"
#include <stddef.h>

#define APP_STACK_WORDS UINT32_C(256)
#define APP_HIGH_PRIORITY ((UBaseType_t)(APP_EQUAL_PRIORITIES ? 1U : 2U))

static StackType_t s_high_stack[APP_STACK_WORDS];
static StackType_t s_low_stack[APP_STACK_WORDS];
static StaticTask_t s_high_tcb;
static StaticTask_t s_low_tcb;
static TaskHandle_t s_high_handle;
static TaskHandle_t s_low_handle;
static const uint32_t s_high_delay_ticks = 3U;
static uint32_t s_create_attempted;

volatile uint32_t g_high_passes;
volatile uint32_t g_low_iterations;
volatile uint32_t g_high_last_tick;
volatile uint32_t g_low_last_tick;
volatile uint32_t g_high_state_from_low;
volatile uint32_t g_high_stack_free_words;
volatile uint32_t g_low_stack_free_words;

static void HighEntry(void *argument)
{
    const uint32_t *delay = (const uint32_t *)argument;
    if (delay == NULL || *delay == 0U) {
        App_Fatal(APP_FATAL_PARAMETER, (uint32_t)__LINE__);
    }
    for (;;) {
        ++g_high_passes;
        g_high_last_tick = (uint32_t)xTaskGetTickCount();
        g_high_stack_free_words = (uint32_t)uxTaskGetStackHighWaterMark(NULL);
#if APP_HIGH_ALWAYS_READY
#if APP_HIGH_DO_YIELD
        taskYIELD();
#endif
#else
        vTaskDelay((TickType_t)*delay);
#endif
    }
}

static void LowEntry(void *argument)
{
    (void)argument;
    for (;;) {
        ++g_low_iterations;
        g_low_last_tick = (uint32_t)xTaskGetTickCount();
        g_high_state_from_low = (uint32_t)eTaskGetState(s_high_handle);
        g_low_stack_free_words = (uint32_t)uxTaskGetStackHighWaterMark(NULL);
#if APP_LOW_DO_YIELD
        taskYIELD();
#endif
    }
}

uint32_t App_CreateTasks(void)
{
    if (s_create_attempted != 0U) {
        return 1U;
    }
    s_create_attempted = 1U;
    s_high_handle = xTaskCreateStatic(HighEntry, "High", APP_STACK_WORDS,
                                    (void *)&s_high_delay_ticks, APP_HIGH_PRIORITY,
                                    s_high_stack, &s_high_tcb);
    if (s_high_handle == NULL) {
        return 1U;
    }
    s_low_handle = xTaskCreateStatic(LowEntry, "Low", APP_STACK_WORDS,
                                   NULL, (UBaseType_t)1U,
                                   s_low_stack, &s_low_tcb);
    return s_low_handle == NULL ? 1U : 0U;
}

void vApplicationGetIdleTaskMemory(StaticTask_t **tcb, StackType_t **stack,
                                   uint32_t *depth)
{
    static StaticTask_t idle_tcb;
    static StackType_t idle_stack[configMINIMAL_STACK_SIZE];
    *tcb = &idle_tcb;
    *stack = idle_stack;
    *depth = configMINIMAL_STACK_SIZE;
}

void vApplicationStackOverflowHook(TaskHandle_t task, char *name)
{
    (void)task;
    (void)name;
    App_Fatal(APP_FATAL_STACK, (uint32_t)__LINE__);
}
```

### 9.6 唯一 SysTick 包装

阶段标记由 main 在中断屏蔽窗口单次设置；包装据此选 HAL 或端口，绝不在创建任务前进入内核 tick。SVC/PendSV 不在这里另写函数，而由端口经配置宏提供。末尾屏障需结合实际芯片勘误继续核对。[S5][S8][S11]

**`target/interrupts.h`**

```c
#ifndef L042_INTERRUPTS_H
#define L042_INTERRUPTS_H
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

void SysTick_Handler(void)
{
    if (g_kernel_owns_systick == 0U) {
        HAL_IncTick();
    } else {
        xPortSysTickHandler();
    }
    __DSB(); /* Review ES0182 section 2.1.3 with the actual target revision. */
}
/* SVC/PendSV are supplied by the selected port, not empty application stubs. */
```

### 9.7 main：时钟、静态创建、单向交接

这是应用启动组装层，依赖 HAL、内核与上面的应用接口。RCC 配置结构只在函数内暂存，静态任务存储不在 main 栈。假定真复位路径，不支持未经核对的 Bootloader（引导加载程序）任意跳转。`HAL_InitTick` 显式检查补足固定 HAL 的嵌套返回值缺口。[S5][S6][S9]

**`target/main.c`**

```c
#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"
#include "app_tasks.h"
#include "app_fatal.h"
#include "interrupts.h"

volatile uint32_t g_main_phase;

/* Assumes a genuine reset and matching SystemInit, not a bootloader handoff. */
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
    /* This HAL version ignores its nested HAL_InitTick return value. */
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

    /* One-way HAL-to-kernel handoff: no timed HAL calls after this point. */
    __disable_irq();
    HAL_SuspendTick();
    SysTick->CTRL = 0U;
    SysTick->VAL = 0U;
    SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk | SCB_ICSR_PENDSVCLR_Msk;
    __DSB();
    __ISB();
    if (App_CreateTasks() != 0U) {
        App_Fatal(APP_FATAL_TASK_CREATE, (uint32_t)__LINE__);
    }
    g_kernel_owns_systick = 1U;
    g_main_phase = 3U;
    vTaskStartScheduler(); /* This port enables interrupts on first-task entry. */
    App_Fatal(APP_FATAL_SCHED_RETURN, (uint32_t)__LINE__);
}
```

### 9.8 错误出口：记录后不返回

错误编号 1..10 依次为断言、HAL 初始化、HAL 时基、振荡源、时钟/分组、任务创建、调度器意外返回、任务意外返回、栈溢出、参数。0 表示尚未记录错误，不等于全部层面通过。栈钩子只能尽力记录，不保证内存已损坏时仍安全；这不是内存保护机制。[S5]

**`target/app_fatal.h`**

```c
#ifndef L042_APP_FATAL_H
#define L042_APP_FATAL_H
#include <stdint.h>

#define APP_FATAL_ASSERT UINT32_C(1)
#define APP_FATAL_HAL_INIT UINT32_C(2)
#define APP_FATAL_HAL_TICK UINT32_C(3)
#define APP_FATAL_OSC UINT32_C(4)
#define APP_FATAL_CLOCK UINT32_C(5)
#define APP_FATAL_TASK_CREATE UINT32_C(6)
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

<!-- L042-INLINE-END -->

## 10. 常见错误

| 错误 | 为什么错 | 修正与观察 |
| --- | --- | --- |
| 只按任务优先级挑任务 | 把阻塞任务也算入候选 | 先写状态，再比较优先级 |
| tick 每增加一次必定换任务 | 无更合适候选时当前任务可继续 | 看 `xTaskIncrementTick` 的请求条件及实际 `pxCurrentTCB` |
| 到期 Ready 就等于已经运行 | 请求/异常/恢复之间有条件与延迟 | 逐层观察 tick、状态、PendSV 与入口后的数据 |
| 用 `taskYIELD` 解决低优先级饥饿 | 高优先级调用者仍就绪，可能选回自身 | 明确等待条件，使任务真正阻塞；不要靠盲目改优先级掩盖设计 |
| 时间片关后同级永不切换 | 主动让出、阻塞、固定包 tick 唤醒都可能引发选择 | 用第 4.5 节固定版本事件判断，不能只背配置名 |
| 任务优先级与 NVIC 数字方向混淆 | 两种优先级空间相反且含义不同 | 单独列出任务 0..4 与异常逻辑 0..15 |
| 在两个文件中定义 SysTick/SVC/PendSV | 可能重复链接，或空函数劫走真正端口 | 看链接符号/向量，不靠函数名存在就算正确 |
| 交接后继续 `HAL_Delay` | HAL `uwTick` 已停止，可能永不结束 | 只用本课核对的内核延时；需 HAL 时基时重新设计并审查 |
| `volatile` 自动保证共享计数正确 | 它不是互斥、原子复合操作或任务间通信 | 本课每个计数只有一个任务写、供调试读取，不扩展成同步方案 |
| 凭计数比例声称公平或实时达标 | 循环内工作量不同，调试还会扰动 | 只用于“是否获得运行机会”的定性验证，性能需独立测量设计 |
| 把 Host Fake 通过写成目标通过 | 没有运行真实内核/异常/时钟 | 两轨分列，维持硬件验证为 false |

上述内核边界据 [S2][S3][S5]；硬件时基与异常边界据 [S6][S8][S9]。

## 11. 调试观察点

按层排查，不从“任务没运行”直接猜端口有 bug（缺陷）：

1. **启动与错误出口**：`g_main_phase` 从 1→2→3；`g_error_code/g_error_line`。若在 `App_Fatal`，先定位错误编号，不继续猜调度结果；函数不返回以保留故障现场。
2. **RCC 与软件描述**：`HSIRDY`、`SWS`、HPRE/PPRE1/PPRE2、PLL 状态、`SystemCoreClock`、唯一配置的 `configCPU_CLOCK_HZ`。软件变量吻合并不证明真实 HSI 准确。
3. **静态创建**：两个句柄非空，栈/TCB/参数地址在有效长期存储；栈深是 `StackType_t` 元素数，不是字节数。256 只是初始预算；实际 M4F 元素宽度为 32 位，应用栈各 1024 字节，不包括 TCB 和 MSP。[S4][S5]
4. **交接**：关中断窗口前 HAL tick 可用，窗口后没有重复 SysTick；清挂起后才交内核。检查 PRIMASK（全局可配置异常屏蔽）与 BASEPRI（优先级阈值屏蔽），不要自行提前开中断掩盖顺序错误。
5. **节拍与异常**：内核阶段 `LOAD=15999`，CTRL 三个控制位正确，SysTick/PendSV 最低逻辑优先级 15；唯一 SVC/PendSV 来自固定端口。`VAL` 变化不等于 ISR 已执行，PendSV 挂起也不等于任务已切换。[S5][S8]
6. **任务获得机会**：默认 High 的 `g_high_passes` 和 Low 的 `g_low_iterations` 在连续运行后都应增长；Low 的 `g_high_state_from_low` 默认多见 `eBlocked`。该状态是 Low 调用时的采样值，不是调试暂停瞬间的实时全局真相。
7. **配置边界**：关闭抢占且 Low 不让出时，High 到期后可被 Low 采样为 `eReady`；这不是创建失败。同级不切换时先确认时间片、yield、阻塞/唤醒事件及初始当前任务。
8. **内存与勘误**：高水位观察只能反映已走过路径；栈溢出钩子不是 MPU（内存保护单元），溢出可能先损坏内核。需要最坏调用分析与对应修订号勘误审查，不能用一次运行宣布安全。[S5][S11]

FreeRTOS 函数/链表是源码观察点，SysTick/SCB 是硬件观察点，不能互相替代。长断点会停止 SysTick 计数；逐步运行不能测实际毫秒延迟，读取 CTRL 也会影响 COUNTFLAG（到零标记）的观察。[S8]

## 12. 实战实验

### 实验 A：先预测，再证明主机测试能抓错（已执行轨道）

输入：第 8.1 节九组事件和独立预期表。先在纸上推导第一条轨迹，再运行完整脚本，核对正向 9 项结果。

故意错误：单独运行脚本生成的 `wrong-expected.exe` 会期待 Low 在初始高低优先级场景被选中，应打印失败表达式且返回 1；脚本已自动验证这一点。两个变异源码只落在构建目录，不修改课程原模型。失败判据是负向测试反而退出 0，或者原模型在最终 green 不再通过。

报告边界：可以写“主机模型逻辑通过正向/负向检查”，不能写“FreeRTOS 已通过或 STM32 时钟正确”。

### 实验 B：默认双任务参考工程（目标待执行）

输入：`target/BUILDING.md` 的真实目标依赖清单；无附加实验宏。按第 7 节配置，使用真实工程入口构建，保存完整日志和退出码。检查 map 中栈/TCB 与向量归属，然后由用户另行确认后走其正式人工下载流程；本任务不执行烧录。

预期：High 优先级 2，入口执行一轮后延时 3 tick；Low 优先级 1，在 High 阻塞期间运行。观察 `g_high_last_tick`、`g_high_passes`、`g_low_iterations`、错误出口和节拍配置。不要要求任意两次计数之间精确相差某个墙钟时间。

失败判据：错误出口非零、内核 tick 不前进、向量重复/错指、High 没有阻塞、Low 得不到与默认配置相符的机会、栈或 ABI 问题。先按第 11 节逐层定位，再考虑改代码。

### 实验 C：同级轮换、关时间片与主动让出（目标待执行）

每次更改下表宏都对整个目标完整重建，并真复位；未列宏恢复默认，不把上一变体残留宏带进下一变体。

| 变体 | 附加工程宏 | 预期 |
| --- | --- | --- |
| B 同级时间片 | `APP_EQUAL_PRIORITIES=1`、`APP_HIGH_ALWAYS_READY=1` | Low 后创建而先运行；时间片开启，连续运行时两计数增长 |
| C 关时间片 | B 再加 `APP_USE_TIME_SLICING=0` | 两者都不阻塞、不让出；初始 Low 持续运行，High 无机会 |
| D 主动交替 | C 再加 `APP_HIGH_DO_YIELD=1`、`APP_LOW_DO_YIELD=1` | 双方都显式让出，同级都能获得机会 |

为什么主机测试初始为任务 0，目标同级时却从 Low 开始？主机刻意定义了初始锚点；固定包在调度启动前创建同级任务时可用新创建者替换当前指针，Low 后创建。**对比“从已知当前者开始如何轮换”，不伪造相同启动顺序。**[S5]

C 的无事件场景不能证明“时间片关闭就绝无同级切换”；固定包 tick 同级到期边界已由源码与独立主机测试分别约束，目标若验证需保留唤醒事件与异常请求观察，不能只看计数。

### 实验 D：饥饿与 Ready 不等于 Running（目标待执行）

先用变体 E：`APP_HIGH_ALWAYS_READY=1`、`APP_HIGH_DO_YIELD=1`，其他默认。预期 High 不断计数，Low 不增长。失败不是“Low 创建坏了”，先看它是否 Ready，以及 High 是否一直为唯一最高候选。

再恢复默认，只设 `APP_USE_PREEMPTION=0`。High 首次执行后等待，Low 开始运行；High 到期 Ready 后，Low 不让出便继续运行。Low 的状态采样可以显示 `eReady`，High 计数停在首次循环。再完整重建并加 `APP_LOW_DO_YIELD=1`，观察 Low 让出后 High 获得执行机会。这个对照展示的是选择条件，不是建议生产系统关闭抢占。

### 实验 E：可控错误与证据分层（目标待执行）

不做故意破坏栈、乱改返回地址或伪造空 TCB 的危险实验。可在实际工程的受控调试分支中重复调用 `App_CreateTasks()`，其第二次返回错误，再由已有主线进入创建错误出口；完成后还原实验分支并保存差异。静态创建的断言也可能先于空句柄返回触发，不能把 `NULL` 检查当成栈容量保护。[S4][S5]

错误报告至少区分：配置/创建检查、C 语法、ARM 编译、链接、下载、板上观察。按证据逐层填写，不因前一层通过自动勾选后一层。

## 13. 自检题

先独立作答，再查看参考要点；生成本课不提升掌握度。

1. High 优先级 4 但处于 Blocked，Low 优先级 1 为 Ready；谁可运行？为什么不能只选数字最大者？
2. High 在 tick=20 调用 `vTaskDelay(3)`；本课简化时间线上哪次 tick 使它重新 Ready？是否保证那一刻已经执行任务指令？
3. High 一直就绪，每轮 `taskYIELD()`；Low 是否必然运行？`vTaskDelay(0)` 能替代真正等待吗？
4. 同级任务、时间片关闭，何种输入下普通 tick 不切换？为什么不能推出任何同级切换都被禁止？
5. 关闭抢占后，High 到期 Ready，Low 仍运行；这是调度器错误吗？什么受控事件可让 High 被重新选中？
6. SysTick、PendSV、SVC 分别由谁提供处理器，谁推进 tick，谁选择 TCB，谁恢复上下文？
7. 若时钟实际用 HCLK/8，软件却仍按 16 MHz 计算 LOAD=15999，标称 tick 频率如何变化？
8. 本课 HAL 时基在什么阶段停止？为什么不能在任务中加一行 `HAL_Delay(10)`？
9. 模型返回 `MODEL_NONE` 时，真实内核是否也没有任何任务？模型对哪些行为故意不做保证？
10. 通过主机语法检查和九个测试后，为什么 `hardware_verified` 仍必须为 false？

参考要点：

1. 排除阻塞者，Low 可运行；任务存在、优先级高都不能越过状态门槛。
2. 简化为 tick=23 到期；随后还需选择/异常/恢复条件，不保证立即执行。
3. 不必；High 仍是最高可运行候选，零延时只是重新选择。
4. 没有阻塞/唤醒/主动让出等其他触发时可不切；固定包同级到期使用 `>=`，主动 yield 也不由时间片开关禁止。
5. 不是；Low 主动 yield 或进入阻塞后重新选择即可展示差异。
6. SysTick 为应用唯一包装、随后进端口；SVC/PendSV 为所选端口；`xTaskIncrementTick` 记账、`vTaskSwitchContext` 选择，端口保存恢复。
7. 源时钟 2 MHz，tick 为 2 MHz/16000=125 Hz；任务等待标尺扩大 8 倍。
8. 关中断的单向交接窗口；其后 HAL 的 tick 不前进，依赖超时的调用可能卡住。
9. 真实内核有 Idle；模型不保证 tick 环绕、真实就绪链历史、异常/屏蔽时序、动态创建、多核等。
10. 既未完成实际 ARM 工程构建/链接，也没有实际板卡、下载与观察证据；主机检查不运行内核端口或硬件。

## 14. 面试题

### 题一：任务一直没运行，如何区分阻塞与饥饿？

参考回答：先看任务是否存在以及状态。Blocked 说明在等待条件，不应参加选择；Ready 却长时间未运行，需检查更高优先级候选是否持续可运行，再核对抢占/同级事件与异常切换链。不能先盲目提高优先级。

评分点：状态先行；区分创建失败、等待、饥饿；说明观察证据不是单个打印结果。能指出 Ready 不一定立即 Running 为加分。

### 题二：SysTick 中断是不是每次都做上下文切换？

参考回答：不是。所选端口调用 `xTaskIncrementTick`，根据到期唤醒、同级时间片等条件得到请求；需要时才挂起 PendSV。实际保存/恢复在 PendSV，内核选择在 `vTaskSwitchContext`。重新选择甚至可能仍选原任务。

评分点：分开 tick、请求、选择与恢复；指出固定配置/版本边界，不声称所有芯片所有内核都一样。[S5][S8]

### 题三：如何审查“关闭时间片，同级任务不会切换”这句话？

参考回答：先问“没有其他什么事件、哪份内核、是否允许 yield/阻塞/唤醒”。关闭时间片只去掉周期 tick 轮换条件。本固定包的 tick 到期路径用 `>=` 请求切换，主动 yield 也仍存在，因此原命题缺条件。

评分点：不只背配置；能定位固定包两个不同条件并给独立反例，不直接用网上 main 的实现替代。[S5]

### 题四：主机测试已经过，为什么还要检查时钟、向量和静态内存？

参考回答：主机只证明有限状态模型的输入输出。实际 tick 由时钟/LOAD 决定，异常向量决定能否进入端口，栈/TCB/ABI 决定能否安全保存恢复；这些都没有被主机模型执行。每层要自己的日志与观察，不能越级作结论。

评分点：分清证据类型；能说出至少三项具体目标依赖；不把编译和上板混为一谈。

## 15. 延伸思考

- High 每 3 tick 重新 Ready 就意味着严格 333.3 Hz 周期吗？把一轮工作时间、调用相位和响应延迟分别放回时间线；后续再比较固定包周期唤醒接口。
- 若未来 IRQ 在两个 tick 之间使高优先级任务 Ready，它是否一定要等下一个 tick？从“事件触发请求”和“tick 到期事件”区分思考；FromISR 代码与优先级约束留给后续课。
- 如果 DMA 缓冲已产生数据，但任务 Ready 后仍被更高任务长期压住，数据所有权与覆盖风险如何记录？后续把输入速率、等待时间、缓冲容量和通知设计一起验证，不用“RTOS 实时”四字替代预算。
- Low 忙循环让 Idle 没机会运行时，为什么本实验仍可能展示正确选择，却不是好的生产低功耗设计？将能力地图中的等待、内存清理和低功耗路径分别列出，不在本课新增实现。

## 16. 本节总结

先由任务状态确定候选，再在候选里按固定优先级和本次事件选择执行者。`vTaskDelay(N>0)` 让任务离开候选，tick 到期使它重新就绪；抢占决定是否自动提出新的选择。时间片只约束同级的一种周期触发，yield 不保证低优先级机会，持续就绪的高优先级任务可以使低优先级饥饿。

F407 的真实落点是：HSI/HCLK→SysTick→内核 tick/就绪结构→PendSV 请求→内核选择/端口恢复。HAL 初始化、内核规则与硬件异常各有职责；唯一处理路径与时基所有权不能省略。

本课已留下主机正/负逻辑证据；STM32 参考实现仍待实际目标工程构建和硬件验证。课程生成、测试模型或阅读代码都不自动改变掌握度。

## 17. 下一步

按既定路线进入 `queue`（队列）：把“等一段时间”演进为“等实际数据/事件或超时”，继续追踪任务何时离开和重返候选集合。任务通知、互斥、ISR 内核 API、优先级反转和 OSAL（操作系统抽象层）分别在后续主题展开，不提前改写当前学习状态或项目进度。

## 18. 参考资料

所有正式来源域均在 `config/source-policy.toml` 许可范围，均为第一方。正文编号对应 `lesson.json.sources` 的文档 ID；访问日期均为 2026-10-23。现有官方缓存重新读取不等于当日重新下载最新版；版本固定到实际取得文件/包。技术阅读、主机运行与目标验证分别记录，本节不是 Reviewer 结论。

<!-- L042-REFERENCES-BEGIN -->

- **[S1] FREERTOS-STATES — FreeRTOS Task states**。版本：Official dynamic page body retrieved 2026-10-23; single-core scope only。
  URL：`https://www.freertos.org/Documentation/02-Kernel/02-Kernel-features/01-Tasks-and-co-routines/02-Task-states`；访问：2026-10-23；第一方：是。
  阅读位置/用途：任务状态正文，Running/Ready/Blocked；只使用单核部分。

- **[S2] FREERTOS-SCHEDULING — FreeRTOS Task scheduling**。版本：Official dynamic page body retrieved 2026-10-23; single-core scope only。
  URL：`https://www.freertos.org/Documentation/02-Kernel/02-Kernel-features/01-Tasks-and-co-routines/04-Task-scheduling`；访问：2026-10-23；第一方：是。
  阅读位置/用途：单核固定优先级、抢占、时间片、yield 与饥饿；不采用 SMP 配置。

- **[S3] FREERTOS-DELAY — FreeRTOS vTaskDelay API**。版本：Official page snapshot 2026-10-21; INCLUDE_vTaskDelay and relative tick units checked in V10.3.1。
  URL：`https://www.freertos.org/Documentation/02-Kernel/04-API-references/02-Task-control/01-vTaskDelay`；访问：2026-10-23；第一方：是。
  阅读位置/用途：相对 tick 延时；具体实现另按本次固定包核对。

- **[S4] FREERTOS-STATIC-TASK — FreeRTOS xTaskCreateStatic API**。版本：Official page snapshot 2026-10-21; cross-checked with packaged kernel V10.3.1。
  URL：`https://www.freertos.org/Documentation/02-Kernel/04-API-references/01-Task-creation/02-xTaskCreateStatic`；访问：2026-10-23；第一方：是。
  阅读位置/用途：入口/参数/优先级/栈/静态 TCB，栈深单位与存储生命周期。

- **[S5] ST-STM32CUBEF4 — STM32CubeF4 official package and local fixed middleware**。版本：FW.F4.1.28.0 + patch FW.F4.1.28.3; packaged FreeRTOS V10.3.1; GCC ARM_CM4F; no target build。
  URL：`https://www.st.com/en/embedded-software/stm32cubef4.sw-versions.html`；访问：2026-10-23；第一方：是。
  阅读位置/用途：实际 package.xml、tasks.c:1341/2707/2804/2821/2989、创建前当前指针、ARM_CM4F port.c、HAL/RCC 与 CMSIS 头；固定文件指纹见本次 source-audit.json。

- **[S6] ST-RM0090 — STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 reference manual**。版本：Rev 22, May 2026。
  URL：`https://www.st.com/resource/en/reference_manual/dm00031020.pdf`；访问：2026-10-23；第一方：是。
  阅读位置/用途：§3.5.1 表 11，RCC §7.2 时钟树/HSI，§7.3 RCC_CR/CFGR；本次读取 PDF 第 80–81、98、217–231 页。

- **[S7] ST-DS8626 — STM32F405xx / STM32F407xx datasheet**。版本：Rev 12, March 2026。
  URL：`https://www.st.com/resource/en/datasheet/stm32f407vg.pdf`；访问：2026-10-23；第一方：是。
  阅读位置/用途：器件范围、运行条件和内部 HSI 电气特性；PDF 第 1–3、81、105 页。不把 VG 文件名当作板级信息。

- **[S8] ST-PM0214 — STM32 Cortex-M4 MCUs and MPUs programming manual**。版本：Rev 10, March 2020。
  URL：`https://www.st.com/resource/en/programming_manual/dm00046982.pdf`；访问：2026-10-23；第一方：是。
  阅读位置/用途：异常/优先级与返回，ICSR/SHPR，§4.5 SysTick 的 CTRL/LOAD/VAL；PDF 第 37–44、225–226、233–234、246–250 页。

- **[S9] ST-UM1725 — Description of STM32F4 HAL and low-layer drivers**。版本：Rev 8, March 2023; exact HAL behavior checked in fixed package。
  URL：`https://www.st.com/resource/en/user_manual/dm00105879.pdf`；访问：2026-10-23；第一方：是。
  阅读位置/用途：HAL/LL 文档范围；精确 HAL_Init/InitTick/RCC 返回路径与 LL 名称另读固定包源码。

- **[S10] ST-UM1718 — STM32CubeMX for STM32 configuration and initialization C code generation**。版本：Rev 51, May 2026; GUI not executed。
  URL：`https://www.st.com.cn/resource/en/user_manual/dm00104712-stm32cubemx-for-stm32-configuration-and-initialization-c-code-generation-stmicroelectronics.pdf`；访问：2026-10-23；第一方：是。
  阅读位置/用途：项目级时钟、代码生成与中间件集成阅读参考；没有操作 GUI 或生成工程。

- **[S11] ST-ES0182 — STM32F405/407xx and STM32F415/417xx device errata**。版本：Rev 19, July 2026。
  URL：`https://www.st.com/resource/en/errata_sheet/dm00037591.pdf`；访问：2026-10-23；第一方：是。
  阅读位置/用途：§2.1.1–2.1.3 内核异常限制、§2.2.3 Stop 调试/SysTick；实际修订号仍待目标确定。

- **[S12] ST-DS11532 — STM32F765xx / STM32F767xx / STM32F768Ax / STM32F769xx datasheet**。版本：Rev 9, July 2025; F767 core/cache scope only。
  URL：`https://www.st.com/resource/en/datasheet/stm32f767zi.pdf`；访问：2026-10-23；第一方：是。
  阅读位置/用途：F767ZI 的 Cortex-M7 与缓存/存储范围；不作为具体端口/寄存器移植配方。

- **[S13] ST-DS14258 — STM32H562xx and STM32H563xx datasheet**。版本：Rev 6, May 2025; H563 core/TrustZone scope only。
  URL：`https://www.st.com/resource/en/datasheet/stm32h563zi.pdf`；访问：2026-10-23；第一方：是。
  阅读位置/用途：H563ZI 的 Cortex-M33、TrustZone 和缓存范围；安全端口/异常配置另核。

- **[S14] ST-DS12110 — STM32H742xI/G and STM32H743xI/G datasheet**。版本：Rev 11, January 2026; H743 core/cache scope only。
  URL：`https://www.st.com/resource/en/datasheet/stm32h743zi.pdf`；访问：2026-10-23；第一方：是。
  阅读位置/用途：H743ZI 的 Cortex-M7、L1 缓存与器件范围；不推广到全部 H7。

- **[S15] ST-STM32CUBEMX — STM32CubeMX official software versions**。版本：Fixed GUI reference STM32CubeMX-Win 6.18.1 found in official cached page; GUI not run。
  URL：`https://www.st.com/en/development-tools/stm32cubemx.sw-versions.html`；访问：2026-10-23；第一方：是。
  阅读位置/用途：官方既有缓存的 CubeMX-Win 6.18.1 项；不声称本次已运行或它是在线最新版本。

<!-- L042-REFERENCES-END -->

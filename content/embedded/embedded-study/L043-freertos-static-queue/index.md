+++
title = "FreeRTOS 静态有界队列：消息复制、满空等待与超时"
date = "2026-10-23T16:31:48+08:00"
lastmod = "2026-10-23T16:31:48+08:00"
summary = "能够用静态有界队列在两个任务间按值传递固定大小消息，预测满/空等待、超时及唤醒后的调度，并说明 STM32F407xx 参考实现与主机验证的证据边界。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 43
tags = ["FreeRTOS", "静态队列", "按值复制", "阻塞与超时", "STM32F407", "Host-Fake"]
source_ids = ["FREERTOS-QUEUES", "FREERTOS-STATIC-QUEUE", "FREERTOS-SEND", "FREERTOS-RECEIVE", "ST-STM32CUBEF4", "ST-RM0090", "ST-DS8626", "ST-PM0214", "ST-UM1725", "ST-UM1718", "ST-ES0182", "ST-DS11532", "ST-DS14258", "ST-DS12110", "ST-STM32CUBEMX"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L043"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# L043 | FreeRTOS 静态有界队列：消息复制、满空等待与超时

阶段：`rtos-concurrency`（FreeRTOS 与并发）；主题：`queue`（队列）。FreeRTOS 是实时操作系统内核；本课固定到单核、打包内核 **V10.3.1**，不讨论多核。

建议先用 60 分钟完成两条核心轨迹，再按实验继续。全文是一节课程、一个课程 ID，不因代码和实验较长拆成多课。代码使用 C11 子集，应用消息使用固定宽度整数，默认不分配动态内存。

**验证边界**：Host Fake（主机模拟依赖）只验证原创模型；STM32F407xx 代码是**参考实现，待目标工程编译**，未执行 ARM 构建/链接、烧录或板上测量，`hardware_verified=false`。后文的主机 C 前端语法检查不等于目标编译。没有指定板卡，不假设晶振、LED、串口引脚或外部电路。

## 1. 本节目标

**核心目标：能够用静态有界队列在两个任务间按值传递固定大小消息，预测满/空等待、超时及唤醒后的调度，并说明 STM32F407xx 参考实现与主机验证的证据边界。**

本课恰好引入两个新核心概念，与本次 `plan.json` 一致：

1. 静态有界队列按值复制消息，隔离生产者与消费者的存储生命周期。
2. 队列满/空时任务按超时阻塞，由空间/消息事件唤醒并重新参与调度。

完成后应能画出两次复制、确定存储归属，手推容量 2 的 FIFO（First In First Out，先进先出）轨迹，检查发送/接收返回值，并区分“消息到达”“任务就绪”“任务运行”“API 返回”。信号量、互斥量、通知、指针消息协议和中断服务程序专课不是隐含前置。

## 2. 它解决什么问题

假设一个生产任务每次生成 `{sequence, value}` 样本，另一个消费任务处理样本。把一个全局变量作为交接点，会遇到两个问题：

- 生产者写了 A、紧接着写 B，消费者只读到 B；没有位置保存未处理的 A。
- 消费者不知道该等什么，只能不断检查变量；检查得太慢丢数据，忙等又浪费可运行时间。

先选最小方案：**两个槽位、每项 8 字节、发送到队尾、从队头取走；满了不覆盖，空了不编造消息**。槽位属于长期存在的队列；生产者和消费者各有自己的局部记录。任务缺的是消息或空间时，可以暂时阻塞，而不是反复轮询。[S1][S2][S3][S4]

这里的“有界”是**最多暂存两个尚未取走的记录**，不是无限吸收流量。消费者长时间跟不上，最终仍会填满；发送者必须选择有限等待、立即失败及应用丢弃/重试策略。本课采用“有限等待，失败计数后放弃本次消息”，不偷偷覆盖旧消息，也不把队列当永久存储。

## 3. 必要前置知识

本次 `learning-state.toml` 的 `completed` 已包含指针、静态存储期、工具链、时钟树、中断优先级、主机测试、`task` 和 `scheduler`，可以复用：

| 已有知识 | 本课用在哪里 | 快速检查 |
| --- | --- | --- |
| 静态存储与局部变量 | 队列控制块/槽位和任务栈长期存活；消息局部变量短期复用 | 函数返回后，其普通局部数组还能保存队列吗？不能 |
| 指针与 `sizeof` | 传入源/目标缓冲地址；创建时指定复制字节数 | `&message` 是地址，复制长度由创建参数决定 |
| 任务状态与固定优先级 | 满/空等待进入阻塞；事件/超时后重新就绪 | 高优先级阻塞任务不能挡住低优先级就绪任务 |
| tick（内核节拍）与异常 | 用 tick 数表示最长阻塞等待；异常完成调度 | 就绪不自动等于已经运行 |
| C11 编译和测试退出码 | 主机模型正向、错误预期与变异检查 | 测试失败必须非零退出 |

前两项检查不清楚，先回看 L006 静态存储相关课程；任务/调度不清楚，先看 `lessons/L041-freertos-static-task` 与 `lessons/L042-freertos-scheduler`。这里不要求会信号量、互斥量、RTOS 内存管理、操作系统抽象层或 ISR 专用 API。

## 4. 核心原理

### 4.1 先观察两次复制，再命名对象

```text
生产任务局部 message             队列长期持有的两个槽位            消费任务局部 received
{10,110} --send 成功复制 8 字节--> [ {10,110} | 空 ] --receive 成功复制--> {10,110}
     随后改成 {999,-1}              旧消息仍为 {10,110}                 接收后槽位释放
```

发送成功后，源记录可以修改/离开其有效期；消费任务得到的不是生产者局部变量的别名。接收成功后，接收者也能独立修改自己的副本。但**只有成功完成复制**才取得这种隔离：若发送因满而阻塞，调用还未返回，源缓冲必须一直有效且不能被其他执行者改写；阻塞接收时目标缓冲也必须保持有效。[S1][S3][S4][S5]

创建静态队列需要分清三个对象：[S2][S5]

| 对象 | 本例定义位置 | 谁持有、谁传入、谁使用 |
| --- | --- | --- |
| `StaticQueue_t`（静态队列控制块类型） | `target/app_queue.c` 的 `s_queue_control` | 组装模块持有永久对象；创建函数把地址交给内核，内核维护读写位置、数量、等待信息 |
| 项存储区 | 同文件 `s_queue_storage[2 * sizeof(SampleMessage)]` | 应用提供 RAM；内核在其中复制消息，应用不绕过 API 直接改槽位 |
| `QueueHandle_t`（队列句柄类型） | 同文件 `s_queue` | 它标识内核队列，不是消息地址；组装处写入两个静态任务上下文，由任务参数传入两个入口 |

容量 2、项大小 8，因此**槽位区是 16 字节**；总 RAM 还要加 `sizeof(StaticQueue_t)`、任务控制块、栈和上下文，不能把 16 字节说成整个系统的内存开销。控制块尺寸依赖内核版本和配置，不硬编码。[S2][S5]

公开消息只有 `uint32_t sequence`、`int32_t value`。创建项大小用 `sizeof(SampleMessage)`，并用 `_Static_assert` 检查本例布局；不要把 C 结构体内存布局当跨设备通信协议。如果消息改为含指针，复制的是那个**指针值**，不会复制指针指向的数组；何时允许复用外部缓冲要另订协议，本课不实现。[S1][S5]

### 4.2 四种返回与两个等待条件

以下为本例使用的任务上下文原生 API，不适用于中断；V10.3.1 的 `xQueueSend` 等价于 `xQueueSendToBack`，最终进入 `xQueueGenericSend`。[S3][S4][S5]

| 操作与当时条件 | 等待参数 | 结果与消息变化 |
| --- | --- | --- |
| send，有空位 | 任意非负 tick 数 | 立即复制入队，返回 `pdPASS`；可能使等待接收任务就绪 |
| send，满 | 0 | 返回 `errQUEUE_FULL`，旧数据不变，本次未入队 |
| send，满 | 有限正值 N | 等空间或超时；恢复执行后重查条件，成功才复制；最终失败返回 `errQUEUE_FULL` |
| receive，有记录 | 任意非负 tick 数 | 复制队头到目标并移除，返回 `pdPASS`；可能使等待发送任务就绪 |
| receive，空 | 0 | 返回 `errQUEUE_EMPTY`，不能拿旧目标值当新消息 |
| receive，空 | 有限正值 N | 等消息或超时；恢复执行后重查，成功才取走；最终失败返回 `errQUEUE_EMPTY` |

**等待参数是条件不满足时允许阻塞的上限，不是每次固定延时 N tick。** 条件已经满足就直接尝试复制。真实 API 不会返回“正在阻塞”；调用暂停，任务以后恢复才从同一次调用返回。后文模型为了展示中间状态，才额外暴露 `QM_BLOCKED` 与 `QM_Resume`，它们不是 FreeRTOS API/返回码。[S3][S4][S5]

本版 `pdPASS=1`，`errQUEUE_FULL` 与 `errQUEUE_EMPTY` 都是 0。因此先知道你调用的是哪个 API，再检查是否 `== pdPASS`；不能靠返回的数字 0 区分所有故障。参数非法可能触发 `configASSERT`（内核配置断言），不是一个可通用依赖的“参数错误返回码”。[S5]

### 4.3 事件唤醒不是替等待者完成整次调用

```text
Consumer: 空 -> 记入接收等待信息并阻塞
Producer: send 复制 -> 队列已有数据 -> Consumer 移到就绪集合
调度规则: 在所有就绪任务中选择
Consumer 真正运行: 回到尚未完成的 receive -> 重查 -> 复制到自己的缓冲 -> 返回成功
```

同理，消费成功释放槽位，使等待发送者就绪，不表示第三条消息已经自动入队。被唤醒者要运行，原来的发送调用才有机会完成。多个任务竞争时，唤醒也不保证条件一直为它保留；内核循环重查条件和剩余超时，而不是每次唤醒都重新赠送完整 N tick。[S5：`queue.c` 的发送/接收循环、`tasks.c:xTaskCheckForTimeOut`]

固定 V10.3.1 的 `tasks.c:xTaskRemoveFromEventList` 在正常事件路径比较 `等待者优先级 > 当前任务优先级`，`queue.c` 再在开启抢占时请求切换。更高优先级接收者可能**在发送者的 `xQueueSend` 返回之前就运行**；更低优先级接收者只是就绪。相同优先级的队列事件本身不靠这条分支要求立即抢占，但之后仍可能发生 tick 时间片切换；不要许诺谁必定先打印。L042 讨论的 tick 超时解除阻塞路径包含 `>=`，它与这里不是同一条路径，不能把一个符号套到另一处。[S5]

### 4.4 tick 超时不是严格的墙上时间保证

本例 `configTICK_RATE_HZ=1000`，名义上每 tick 1 ms，`pdMS_TO_TICKS(10U)` 得 10 tick。若在下一个 tick 到来前发起等待，计数边界会带来量化误差；十个 tick 的到期通常对应约 9 到 10 个 tick 周期，而任务真正获得 CPU 并返回还可能更晚。更高优先级任务持续占用 CPU 时，**超时到期也不能保证调用及时返回**。[S5][S8]

本版默认 `pdMS_TO_TICKS` 做整数乘除：非整 tick 的毫秒数向下截断，大参数还可能在乘法时溢出。这里仅使用 0～1000 ms 的小常量、32 位 tick，且对必须让出的任务间隔检查非零；若更改节拍频率，须重新计算，不能直接照搬 `portTICK_PERIOD_MS` 整数换算。无限等待和 tick 环绕的内核实现不在本课模型范围；不用 `portMAX_DELAY` 隐藏这条边界。[S5：`projdefs.h:41`、配置与超时逻辑]

## 5. 关键术语与直观模型

| 术语 | 准确含义与本例对应 |
| --- | --- |
| producer / consumer | 生产者 / 消费者；分别调用 send / receive 的任务，不是两个中断 |
| bounded queue | 有界队列；容量上限固定，装满不会自动增加 RAM |
| FIFO | 先进先出；本课只用队尾发送、队头接收，不用插到队首/覆盖 |
| item size | 项大小；创建时固定的每次复制字节数，不是队列长度 |
| queue handle | 队列句柄；不透明对象标识，不是最新消息的指针 |
| static allocation | 静态分配；应用长期提供控制块和槽位，并不表示队列内容只读 |
| block / ready / running | 阻塞 / 就绪 / 运行；就绪是可以竞争 CPU，尚不等于 API 已完成 |
| timeout | 超时；条件一直不满足时解除等待，不是自动修复丢消息 |
| HAL | Hardware Abstraction Layer，硬件抽象层；本课配置 RCC/时基，不创建队列 |
| LL | Low-Layer driver，底层驱动；用它与寄存器解释 HAL 背后的动作 |
| ISR / FromISR | Interrupt Service Routine，中断服务程序 / 供中断上下文使用的 API 后缀；这里只作后续接线检查词汇 |

把队列看成“只收固定规格包裹、只有两个格子的中转柜”即可。但柜子的比喻不能替代两次字节复制、控制块寿命和调度推理，也不表示有一个额外的“队列线程”。

## 6. 从输入到结果的完整流程

### 6.1 容量 2 的手推轨迹

以下是人为安排的操作顺序，只验证复制和 FIFO，不假称每一种优先级配置都会自然产生这个顺序：

| 步骤 | 输入/操作 | 逻辑队列（队头在左） | 可观察结果 |
| --- | --- | --- | --- |
| 0 | 静态创建 | `[]` | 控制块、槽位、句柄存活，数量 0 |
| 1 | send A=`{10,110}`，等待 0 | `[A]` | 成功，复制了 8 字节 |
| 2 | 源变量改成 `{999,-1}` | `[A]` | 队列 A 仍为 `{10,110}` |
| 3 | send B=`{20,220}` | `[A,B]` | 成功，数量 2 |
| 4 | send C=`{30,330}`，等待 0 | `[A,B]` | 满，失败，没有覆盖 A |
| 5 | receive 到 `received` | `[B]` | 成功，得到 A；之后修改 received 不改 B |
| 6 | receive | `[]` | 成功，得到 B |
| 7 | receive，等待 0 | `[]` | 空，失败，不能消费旧 received |

### 6.2 满、空、超时的任务轨迹

| 场景 | 时间/事件 | 等待者状态 | 成功/失败的判断时刻 |
| --- | --- | --- | --- |
| 空等消息 | C 调用 receive，等待 8；P 随后发送 A | C：阻塞→就绪→按优先级得到 CPU | C 真正继续 receive 后复制 A 并返回成功 |
| 满等空间 | `[A,B]`；P 发送 C 等待 9；C 取走 A | P：阻塞→就绪 | P 继续原 send 后才把 C 入队，此后为 `[B,C]` |
| 空等超时 | 当前 tick=10；C 等 3，期间没有 send | tick=12 仍阻塞，tick=13 可变就绪 | C 实际运行且仍空，返回失败；不是在 tick=13 无条件立刻执行 |
| 满等超时 | `[A,B]`；P 等 4，期间无人 receive | 到期后 P 就绪 | P 实际继续且仍满，失败，旧 FIFO 不变 |

课堂超时轨迹刻意不安排“到期与消息/空间同时发生”，也不模拟多个等待者争用。真实内核需要重查条件；不能从模型外推同 tick 边界的固定胜负。[S5]

两个机制都可回答“谁定义、持有、传入、调用流动”：应用定义消息规格和永久存储；组装处持有队列并传入任务参数；生产者和消费者各自持有局部记录；内核维护控制信息、复制和等待；端口与已学的调度器决定何时继续调用。超时数字在上下文中定义，等待链在内核中维护，tick 事件由时基送到内核，不是由应用另写一个轮询线程。

## 7. 嵌入式系统中的对应位置

队列位于**应用任务与内核之间**。HAL 配时钟，内核提供队列与调度，Cortex-M 异常完成进入任务和切换。不存在 `HAL_Queue_Init`，也没有“队列 RCC 门控寄存器”。[S5][S6][S8][S9]

| 动作 | 本课文件/对象 | 依赖方向与寿命 |
| --- | --- | --- |
| 声明 | `target/app_queue.h` 的消息与 `App_CreateQueueTasks`；官方 `queue.h` | 应用只知道消息结构/入口；任务适配使用原生内核类型 |
| 实现 | `target/app_queue.c` 的两个入口；固定包 `queue.c` 的复制/等待 | 应用依赖内核 API，内核不依赖本课的任务名称或 HAL |
| 实例化 | `s_queue_control`、`s_queue_storage`、两个任务控制块/栈 | 全为文件静态对象，持续整个程序；不是创建函数临时数组 |
| 组装 | `App_CreateQueueTasks` 创建队列，填两个 context（上下文），再创建任务 | 组装处持有句柄，用 `pvParameters`（任务参数）把上下文地址传入 |
| 使用 | ProducerEntry / ConsumerEntry 调用 send / receive | 各自局部消息只需在该调用期间有效；本例不删除队列或任务 |

这不是 Device Framework 架构课程，不引入新的框架层或操作表。这里分开五个动作只为了避免“声明了句柄就等于创建了队列”的误解。即使静态内存仍在，删除对象后旧句柄也不能继续使用；本例禁用删除，不展开删除协议。[S5]

### 7.1 外设能力地图

本主题是内核通信机制，不是硬件外设。仍按能力层次展示边界，避免把“两任务发一个整数”误当全部能力：

| 层次 | 解决的问题、触发/数据路径与配置入口 | 本课与后续落点 |
| --- | --- | --- |
| 基础 | 发送任务→按项复制到固定槽位→接收任务；长度/项大小/静态控制块限定存储 | 本课实现静态 FIFO、两次复制、满不覆盖与空不造数据 |
| 进阶 | 满/空条件→内核等待信息→消息/空间或 tick 事件→就绪→调度→重查并返回 | 本课深入零等待、有限等待、返回值和调度边界 |
| 高级：多生产/消费 | 多个任务送同一队列，等待集合按优先级选择可唤醒者；谁先成功复制决定入队先后，不等于传感器物理发生顺序 | 配置入口为任务优先级、数量、长度；在 `race-condition` 分析竞争和饥饿，本课不增加多等待者模型 [S1][S5] |
| 高级：容量/速率预算 | 短暂突发占用空位，持续到达多于处理能力则最终满；增大长度只推迟拥塞，并增加 RAM 与排队延迟 | `memory` 用“长度×项大小+控制块+栈”作预算；在 `race-condition` 配合负载实验决定丢弃/背压策略；不把长度 2 说成最优 |
| 高级：指针项/队列集合 | 指针项只复制地址，实际数据仍需所有权协议；队列集合把成员可读事件交给一个等待者，再从已选成员读取，不合并成员消息 | 入口分别是项大小/生命周期协议、`configUSE_QUEUE_SETS` 和集合 API；本课关闭集合，不给未核对的配置配方；`memory`/`race-condition` 后再做协议与多路等候实验 [S1][S5] |
| 跨外设联动 | UART/ADC→DMA 写缓冲→IRQ（中断请求）→HAL 回调→合规 FromISR 发送小记录→任务处理 | `isr` 深挖优先级/请求切换/溢出；`notification` 比较只需事件的通知；先前 `peripheral-integration-lab` 仅作前置，不冒充本课硬件证据 |
| F4/F7/H5/H7 | 队列复制机制通用，端口、时基、异常优先级、RAM 放置和安全属性按目标重查 | 本课只完成 F407xx 单核参考；具体迁移表在 8.2，不直接外推到其他系列 |

表中的高级项是解释风险与后续入口，不把信号量、集合或零拷贝另立成本课核心机制；没有给出它们的完整实现或测试。

### 7.2 参考目标与时钟/复位链

**固定边界**：STM32F407xx；RM0090 Rev 22（2026-05）、DS8626 Rev 12（2026-03）、PM0214 Rev 10（2020-03）、ES0182 Rev 19（2026-07）。本机实际只读核对的 STM32CubeF4 基包 `FW.F4.1.28.0`、补丁 `FW.F4.1.28.3`，打包 FreeRTOS `V10.3.1`，端口 `portable/GCC/ARM_CM4F`。这些是取得文件的版本，不宣称是全网最新。[S5][S6][S7][S8][S11]

从**真实复位、正确的厂商启动文件/SystemInit**开始；不假定这是另一个 Bootloader 跳转后的任意状态。选用内部 HSI（High-Speed Internal，高速内部 RC 振荡源），不用外部晶振或 PLL（Phase-Locked Loop，锁相环），避免虚构板级条件。[S5][S6][S7]

```text
复位/匹配的 SystemInit
  -> HSI 标称 16 MHz，HSION=1，等 HSIRDY
  -> 主 PLL 关闭，不进入倍频链；HSE 不参与
  -> SYSCLK 选择 HSI：16 MHz
  -> AHB（高速总线）分频 /1：HCLK = 16 MHz
       -> Cortex-M4 内核 = 16 MHz
       -> SysTick 使用 HCLK，端口默认 CLKSOURCE=1
            LOAD = 16000000 / 1000 - 1 = 15999
            名义内核 tick = 1000 Hz，1 tick = 1 ms
  -> APB1（外设总线 1）/1：PCLK1 = 16 MHz
  -> APB2（外设总线 2）/1：PCLK2 = 16 MHz
```

最终与队列等待有关的是**内核 tick**，不是 PCLK1 或某个 Timer 预分频。静态队列在 RAM 中，无独立时钟/复位位。RAM/CPU 的访问条件来自系统启动和内核执行，不能为队列编造 `__HAL_RCC_QUEUE_CLK_ENABLE()`。本例不启用 UART/ADC/DMA/普通定时器，也无需为它们增加 RCC 门控或复位代码；SysTick 属于内核，不走 APB 外设使能。[S5][S6][S8]

若后续改为 TIM 维持 HAL 时基，必须独立追踪所选 TIM 的总线、APB 分频导致的定时器时钟关系、RCC 门控/复位、PSC（预分频器）和 ARR（自动重装寄存器），核对 HAL 中断是否能及时运行；这不是本例的隐藏配置。此处 APB /1 时适用定时器输入为 16 MHz，但没有初始化任何一个 TIM，不能把它当已实现的 HAL 定时器时基。[S6]

`SystemCoreClock` 是软件按寄存器和标称输入算出的 HCLK 数值，**不是频率测量值**。HSI 有温度/电压相关误差，1 ms 是标称推算，需外部基准才可验证真实时长。[S5][S7]

**时基所有权只交接一次**：[S5][S8]

1. 启动阶段，`HAL_Init` 和显式 `HAL_InitTick` 使用默认 SysTick，`SysTick_Handler` 调用 `HAL_IncTick`；RCC 的有限等待可以使用 HAL tick。
2. 完成时钟配置后关中断、停 SysTick，清当前值以及已挂起的 SysTick/PendSV；创建静态队列/任务，置 `g_kernel_owns_systick=1`，再启动调度器。
3. 端口重新配置 SysTick，首次任务入口恢复中断；之后 SysTick 只调用 `xPortSysTickHandler`。本课的 HAL `uwTick` 此后不再推进，所以**不得在任务/中断中调用 `HAL_Delay` 或依赖 HAL tick 的超时操作，也不得再次调用 `HAL_InitTick` 或改时钟**。

这是专门为“无外围 HAL 运行时调用”的最小队列例选择的单向交接，不是通用 HAL+RTOS 集成配方。将来接外设，需选择经验证的独立 HAL 时基或审计过的共享时基方案，不能悄悄在本例增加阻塞 HAL 调用。

### 7.3 CubeMX、HAL、LL 与寄存器对照

CubeMX 是 STM32 配置/代码生成工具；本课参考官方版本页中已取得的 **STM32CubeMX-Win 6.18.1** 与 UM1718 Rev 51；**没有启动 GUI 或生成 `.ioc` 工程**，实际操作时还要记录你机器上的完整版本。菜单不是验证证据，最终工程的文件/宏/中断处理者才是约束。[S10][S15]

| 配置位置 | 本课明确值/选择 | 必须核对的输出 |
| --- | --- | --- |
| MCU / Board | MCU 为实际完整 F407 料号；不选一个未经确认的板型 | CMSIS 宏 `STM32F407xx`；Flash/RAM/封装由真实完整料号生成，不能从 xx 推测 |
| RCC / Clock Configuration | HSI ON、主 PLL OFF、SYSCLK=HSI；AHB/APB1/APB2 均 /1 | HCLK/PCLK1/PCLK2 标称均 16 MHz；无板级 HSE 频率假设 |
| SYS / Debug | 仅为真实调试器配置调试接口 | 引脚占用由实际板卡决定，本课不指定引脚 |
| SYS / Timebase Source | 启动采用默认 SysTick，不生成 TIM 时基覆盖 | 不链接 `stm32f4xx_hal_timebase_tim.c`；只保留一个 `HAL_InitTick` 实现 |
| FreeRTOS / API | 原生 FreeRTOS API，固定本课内核/端口 | 不混入 `osThreadNew`、`osMessageQueueNew` 等 CMSIS 包装或默认任务；若 GUI 只有包装选项，手工接原生文件 |
| 分配与队列 | 静态=1、动态=0；长度 2；项大小 `sizeof(SampleMessage)` | 一个 StaticQueue_t、16 字节槽位；不链接 heap_*.c |
| 调度与任务 | 抢占=1，时间片=1，tickless=0，tick=1000；P 优先级 1，C 优先级 2 | 两个应用任务，各 256 个 StackType_t；Idle 另有静态存储；数值大者任务优先级高 |
| NVIC（嵌套向量中断控制器） | Priority Group 4；SVC 优先级 0；端口将 SysTick/PendSV 设最低逻辑优先级 15 | F407 实现 4 位优先级；供将来内核 API 中断使用的库阈值 5，编码值 `5 << 4`；不可把任务优先级与 NVIC 数值方向混淆 |
| 中断处理者 | 唯一 SysTick wrapper；SVC/PendSV 由本端口提供 | 删除重复的生成空处理函数时只在自己的新目标工程中操作；本次未修改任何既有工程 |
| HAL 配置 | 仅 RCC、CORTEX、FLASH 与 HAL 核心；无外设句柄 | 本课 `stm32f4xx_hal_conf.h` 只用于这份 HSI-only 参考，不覆盖其他工程配置 |

**HAL 字段与错误顺序**：[S5][S9]

- `RCC_OscInitTypeDef` 是临时配置结构，不是外设句柄。`OscillatorType=HSI` 指定处理 HSI；`HSIState=ON`；`HSICalibrationValue=DEFAULT` 使用默认校准；`PLL.PLLState=OFF`，所以不把未使用的 PLL M/N/P/Q 当必填配置。
- `RCC_ClkInitTypeDef.ClockType` 指定本次写哪些时钟域；`SYSCLKSource=HSI`；AHB 与两个 APB 分频均 /1；`FLASH_LATENCY_0` 与这里 16 MHz 条件对应，不能照搬给更高频率/未知供电条件。
- `HAL_RCC_OscConfig` 或 `HAL_RCC_ClockConfig` 不成功进入 `App_Fatal`。本固定 HAL 的 `HAL_Init`、`HAL_RCC_ClockConfig` 内部调用 `HAL_InitTick` 没有转发其返回值，因此参考代码另作显式检查，不以外层 `HAL_OK` 冒充全部时基检查通过。
- `App_Fatal` 保存错误码和代码行、关闭中断后停在循环，不再打印、不等待 HAL tick。队列/任务创建也检查返回值；发送/接收的满空超时则走普通计数路径，不把可预期的拥塞一律当系统崩溃。

| HAL / 内核入口 | LL 或关键寄存器、RAM 状态 | 应如何解释 |
| --- | --- | --- |
| `HAL_RCC_OscConfig` 的 HSI ON | `LL_RCC_HSI_Enable`；`RCC_CR.HSION/HSIRDY`，校准字段 | 开源、等稳定，不是“写一个频率整数” |
| SYSCLK=HSI，PLL OFF | `LL_RCC_SetSysClkSource`；`RCC_CFGR.SW/SWS`；`RCC_CR.PLLON/PLLRDY` | SW 是请求，SWS 是实际切换状态；PLL 此例旁路而非倍频 |
| AHB/APB 分频 | `LL_RCC_SetAHBPrescaler`、`LL_RCC_SetAPB1Prescaler`、`LL_RCC_SetAPB2Prescaler`；`RCC_CFGR.HPRE/PPRE1/PPRE2` | 决定 HCLK/PCLK，不能只记 SYSCLK |
| `FLASH_LATENCY_0` | `FLASH_ACR.LATENCY` | 控制 Flash 等待周期，不是队列参数 |
| HAL 启动 tick / 端口 tick | `SysTick_CTRL` 的 ENABLE/TICKINT/CLKSOURCE、`LOAD=15999`、`VAL` | 先 HAL、再内核，只有一个 SysTick_Handler；COUNTFLAG 是计数器事件，不等于“队列超时处理已完成” |
| `xQueueCreateStatic` | RAM 中 Queue_t 的长度/项大小、读写位置和等待集合 | 没有 LL 队列初始化寄存器；StaticQueue_t 由官方头文件保证适配 |
| send / receive | `queue.c` 复制助手、`uxMessagesWaiting`、读写位置、等待信息 | 所谓“原子队列操作”由内核维护临界边界，不由给数据加 volatile 实现 |
| 事件/到期解除阻塞 | `tasks.c` 从事件/延时信息转入就绪集合；可能请求 PendSV | PendSV（可挂起的系统服务异常）负责切换；`SCB_ICSR.PENDSVSET` 是切换请求，不是队列数据本身 |
| 首次任务运行 | SVC（系统服务调用异常）和 ARM_CM4F 端口 | 不应另写空 SVC/PendSV 覆盖端口，也不是每次 send 都通过 SVC |

表格用于解释对应动作，不要求同时运行 HAL 和 LL 两套时钟初始化。[S5][S6][S8]

**IRQ/DMA 回调边界**：最小例只有两个任务，不采集真实外设，故 UART/ADC/DMA 句柄、IRQ 及完成/错误回调**不适用**，并非遗漏实现。SysTick 是内核时基，不是 DMA 回调。对于后续 `UART/ADC → DMA → HAL 回调 → 任务` 链，本课仅保留下面的接口检查清单，不提供/宣称完成该链：[S3][S5][S8]

1. 找到真实外设实例、DMA 请求/流映射和触发源，另列时钟、复位、板级输入与错误来源；DMA 完成并不自动说明接收者已处理数据。
2. 确认回调运行在中断上下文；只能用匹配的 FromISR API，不能用本例带等待参数的任务 API，也不能在回调里等待队列空间。
3. 核对实际 NVIC 编码/优先级组与 `configMAX_SYSCALL_INTERRUPT_PRIORITY`，不是“所有 IRQ 都能调用内核”；不能把未移位的库优先级与寄存器编码直接比较。
4. 复制小记录还是复制 DMA 缓冲地址必须明确；若只复制地址，DMA 何时覆盖、消费者何时释放都要有协议，队列成功不保证 DMA 缓冲仍有效。
5. 检查发送返回值，计数满队列导致的丢记录；按所用端口要求处理 `pxHigherPriorityTaskWoken`（是否唤醒更高优先级任务）并请求切换，不能从中断直接调用普通 taskYIELD。
6. 完成回调、DMA/外设错误回调和恢复流程分别观察；F7/H7 的缓存/内存可达性、H5 的安全边界留到对应目标资料和 `isr`、`dma-coherency` 实验核实。

这些是阅读和接线检查项，不把尚未完成的 `isr` 专课设为本课实验前置。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

模型只有一个生产者、一个消费者、容量 2、按值消息和有限 tick 事件。测试驱动注入操作、tick 推进与“继续原调用”的事件；`QM_Pick` 仅从就绪候选选最高优先级，不实现上下文切换。对同优先级固定选择较小编号是**模型限定**，不是 FreeRTOS 的公平性结论；本课调度断言使用不同优先级。

`QM_Resume` 显式分开“被唤醒”和“继续复制”，从而可以观察中间态。模型不要求每次注入都由当前最高优先级任务发起，因此测试是受控队列事件脚本，不是完整运行时间线。例如低优先级接收者已在先前时刻阻塞，再注入高优先级生产者发送，才能讨论它为何只就绪而未先运行；不解释为低优先级任务任意抢占了正在运行的高优先级任务。

模型主动拒绝 tick 加法环绕；内核真实的环绕/超时实现、临界区、调度挂起、待处理就绪、多等待者、同 tick 竞争、时间片、异常、硬件时钟与 HAL 全部不模拟。`QM_Init` 的调用者必须提供有效对象；模型参数错误返回 `QM_INVALID`，也不等于真实内核的参数错误策略。**模型通过不证明内核、端口或芯片行为已经验证。**

在仓库根目录运行，产物写入本次运行目录，不写已有课程：

```powershell
$work = '.state/runs/20261023-163148887-24156/teacher-work'
& ./lessons/L043-freertos-static-queue/tools/test-host.ps1 `
    -BuildDir "$work/build" -EvidenceDir "$work/host-evidence"
```

测试使用 C11、`-Wall -Wextra -Werror -pedantic`，不是只看打印的演示。9 组独立预期覆盖：[源码和日志均在本课及本次运行目录]

| 测试 | 输入和必要断言 | 故障判据 |
| --- | --- | --- |
| CopyAndFifo | A=10/B=20；修改发送源后仍依次收到 10/20；接收缓冲也独立 | 指针别名或顺序反转立即失败 |
| FullKeepsOldMessages | 两项已满，第三项零等待发送失败，旧两项顺序不变 | 覆盖、数量变成 3 失败 |
| EmptyPreservesOutput | 空接收失败，目标保留 `{77,-77}` | 凭空给数据或把旧值当成功失败 |
| ReceiveWakeAndResume | 先空阻塞，发送后接收者就绪，但目标尚未复制；继续调用才成功 | 把唤醒当复制完成失败 |
| LowerPriorityWakeDoesNotWin | 被唤醒接收者优先级低，最高就绪仍是生产者 | 把就绪等同先运行失败 |
| SendWakeAndResume | 满等待第三项，释放一个位置后发送者就绪；继续才入队 | 提前复制/未解除阻塞失败 |
| ReceiveTimeout | tick 10 开始等 3；12 仍等，13 就绪；继续后空失败 | 过早/过晚解除或伪造数据失败 |
| SendTimeout | 满队列等 4，无消费，到期继续失败 | 超时仍入队或损坏 FIFO 失败 |
| RejectInvalidEvents | 空指针、重复未完成调用、无待继续操作、计数环绕 | 接受模型不支持事件失败 |

实际已执行正向测试，输出为：

```text
PASS 9 queue-model tests; not FreeRTOS or STM32 execution
```

脚本还运行错误预期 `--wrong-expected`（故意声称接收旧消息为 999），以及复制破坏、FIFO 反转、漏唤醒三个变异副本；四种情况都必须以断言和非零码失败，最后重新运行原版为 0。变异只发生在 BuildDir 副本，不改课程模型。完整编译器版本、参数、退出码、源码/测试 SHA-256（文件指纹）见本次运行 `teacher-work/host-evidence/host-results.json`；初次未实现 stub（占位实现）在 `teacher-work/red-test.json` 记录了正确的行为断言失败，不能把编译报错冒充红灯测试。

### 8.2 STM32 参考实现轨道

原生内核调用流是完整的：

```text
Reset_Handler -> SystemInit / C 运行时初始化 -> main
  -> HAL_Init / 明确检查 HAL_InitTick
  -> SystemClock_Config：HSI / SYSCLK / AHB / APB / nominal HCLK 检查
  -> HAL 时基单向交接准备
  -> App_CreateQueueTasks
       xQueueCreateStatic -> 两个永久 context -> 两个 xTaskCreateStatic
  -> vTaskStartScheduler -> 静态 Idle -> ARM_CM4F 首次任务启动
  -> Consumer 优先级 2：空队列 receive，阻塞
  -> Producer 优先级 1：send -> 内核复制/唤醒 Consumer
  -> Consumer 按调度得到 CPU，receive 完成，检查消息，任务延时
  -> Producer 完成 send，计数并修改局部消息，任务延时
```

这条初始化和任务/队列路径已全部提供原创应用代码；但 vendor（厂商/官方）启动文件、内核、HAL、CMSIS 与实际料号链接脚本应从你自己的固定 Cube 工程引用，**不复制厂商完整源码进教程仓库**。[S5]

**目标集成/构建步骤（未执行）**：

1. 确认实际完整 MCU 料号、供电范围、复位启动方式、调试器和 Flash/RAM 规格。用匹配工具/包建立本课专用工程，记录 CubeMX、编译器、包版本；现阶段不涉及传感器、HSE 或外部引脚。
2. 将本课 `target/` 的 4 个 `.c` 和全部头文件加入这个**新工程**，替换重复的 main/配置/中断包装；不要改任何 IDE/CubeMX 全局配置。禁止把这份最小 HAL 配置覆盖到已有外围工程。
3. 官方固定包的内核输入只需 `tasks.c`、`queue.c`、`list.c` 与 `portable/GCC/ARM_CM4F/port.c`；包含 `Source/include` 和该端口目录。静态分配开、动态分配关，不加入 heap_*.c、CMSIS_RTOS 包装、默认 freertos.c 任务、软件定时器或第二个调度入口。
4. 官方硬件输入为匹配的 `system_stm32f4xx.c`、`gcc/startup_stm32f407xx.s` 和 CMSIS 头；HAL 使用 `stm32f4xx_hal.c`、`stm32f4xx_hal_rcc.c`、`stm32f4xx_hal_cortex.c`、`stm32f4xx_hal_flash.c`。实际工程若有额外 MSP 文件，核查它是否引入了新外设和模块依赖；本课只需要默认弱 MSP 入口。
5. 对 Cortex-M4F 使用与固定端口一致的 ARM 工具链，例如 `-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard -std=c11`；浮点 ABI（应用二进制接口）须对整个工程一致。链接脚本由实际完整料号生成，不能随便用另一个 F407 封装/容量；核对 `.data/.bss`、任务栈、控制块是否放入可用 RAM。不得把主机 gcc 当 ARM 工具链。
6. 编译并保存完整编译/链接日志、版本、宏定义、源清单与 map（链接布局报告）；核查唯一 SVC/PendSV/SysTick、唯一 FreeRTOSConfig、无动态创建/heap 符号依赖。`StaticTask_t`、`StaticQueue_t` 必须与内核使用同一配置头，不能来自两套 include 搜索路径。
7. 本任务**不执行烧录**。若以后由用户另行安排板上实验，须先确认板卡/供电与现有固件保护，另行授权操作并记录下载、复位和观察证据；本课没有下载命令或既成硬件结果。

在这之前可运行下列**主机前端语法检查**，它使用本机真实官方头文件，但不生成 ARM 指令、汇编端口或链接镜像：

```powershell
& ./lessons/L043-freertos-static-queue/tools/check-reference-syntax.ps1 `
    -CubeF4Root 'C:\Users\25108\STM32Cube\Repository\STM32Cube_FW_F4_V1.28.3' `
    -EvidenceDir '.state/runs/20261023-163148887-24156/teacher-work/reference-syntax'
```

实际结果为 4 个应用 C 文件语法检查通过；仅因主机/目标指针宽度不同，明确豁免 CMSIS 地址转换的两类警告，其他选定警告按错误处理。它没有汇编 `port.c`，也没有核对真实链接脚本、ABI 或中断向量落点，**不写成“STM32 代码已编译成功”**。

| 证据层 | 本次实际情况 | 不能推出什么 |
| --- | --- | --- |
| 第一方资料 | 15 项正式来源、固定包相关文件已阅读/指纹记录 | 阅读不等于代码运行 |
| Host 模型 | 9 组正向、1 个错误预期、3 个变异失败及最终正向已执行 | 不证明 FreeRTOS 内核或时钟 |
| 目标应用 C 语法 | 主机前端读取真实包头文件，4 个 C 文件通过 | 不证明 ARM 编译、汇编、链接或硬件 |
| ARM 完整工程构建 | 未执行 | 不声称产出可下载镜像 |
| 板上观察/测量 | 无板卡、无烧录、无测量 | `hardware_verified=false` |

**F4/F7/H5/H7 迁移核对表**：只断言本次第一方资料已覆盖的器件范围；没有对应 RM/勘误/端口核查的配置细节标为“待目标资料核对”，不提供猜测式移植代码。

| 目标样本 | 已核实事实 | 必须重查及其对本例的影响 |
| --- | --- | --- |
| F4 / F407xx | Cortex-M4F、HSI 标称 16 MHz；本次固定包有 ARM_CM4F 端口 [S5][S7] | 完整料号容量/链接布局、实际系统时钟/优先级、硅版本勘误和可用 RAM；影响静态对象、时基与异常入口，仍未构建/上板 |
| F7 / F767ZI | Cortex-M7，数据手册列 L1 指令/数据缓存 [S12] | 对应 CubeF7/FreeRTOS 版本和适用 M7 端口、FPU/ABI、具体 RAM/缓存属性、时钟与异常要求均待目标 RM/勘误核对；影响栈/队列放置及观察，不能照搬 ARM_CM4F。若后来共享 DMA 缓冲，再补缓存维护协议 |
| H5 / H563ZI | Cortex-M33，具 TrustZone（安全/非安全隔离）；数据手册区分指令缓存与外部存储数据缓存 [S13] | 选择匹配的 M33 安全/非安全端口与完整配置；RAM/中断安全属性、跨边界参数指针是否可访问、tick 所属域均待 RM/安全指南/内核端口核对。不能把 H5 全部 RAM 当 H7 式缓存区，也不假设队列可跨域共享 |
| H7 / H743ZI | 本样本为 Cortex-M7，有 L1 指令/数据缓存 [S14] | 对应 CubeH7/端口、时钟树、内存域/主机可达性和缓存规则待对应 RM/勘误核对；先把队列/栈放进已经核实可由所选 CPU 访问的存储。将来 DMA 数据区还需单独证明 DMA 可达及一致性；不把其他 H7 双核变种外推到 H743 |

可迁移的是固定大小按值复制、容量/返回值、缓冲寿命及就绪推理；不变的是**需要重新验证**，不是“任意 STM32 都能复制这份时钟/端口配置”。本例无 DMA，因而不靠额外 cache clean/invalidate（缓存清理/失效）装饰代码；接入 DMA 后那会成为真实的所有权与一致性问题，不是队列 API 自动解决的问题。

## 9. 最小代码示例

以下代码同时保存在所标路径；README 中展示完整可检查的原创应用/模型代码，不复制厂商实现。主机模型只链接到测试；`target/` 只集成到匹配 MCU 工程，两套数据类型相似但不交叉链接。

### 9.1 文件职责与生命周期

```text
model/queue_model.h, queue_model.c      原创教学机制模型，测试持有对象
tests/test_queue_model.c               手写预期、失败退出码
tools/test-host.ps1                    编译、负向/变异检查，输出指定目录
tools/check-reference-syntax.ps1       真正厂商头文件上的主机语法检查
target/app_queue.h, app_queue.c        消息声明、静态队列/任务实例与组装、两个任务使用
target/FreeRTOSConfig.h                唯一内核配置
target/stm32f4xx_hal_conf.h             HSI-only 最小 HAL 配置
target/app_fatal.h, app_fatal.c         固定宽度错误接口、停机观察点
target/interrupts.h, interrupts.c       SysTick 所有权交接包装
target/main.c                         HAL 时钟、组装顺序与启动调度器
```

### 9.2 主机模型与测试

层次：测试→模型；模型不依赖 HAL/FreeRTOS。`QueueModel` 在每个测试函数中定义，存活到该测试结束；任何等待操作的源/目标也必须存活到 `QM_Resume` 返回最终结果。`QM_Init` 后先有两名就绪候选；测试显式注入操作。代码中的 operation 是“尚未完成的 send/receive”，state 是“等待/就绪”，result 在唤醒时仍可为 `QM_BLOCKED`，三者不是同一件事。

<!-- BEGIN CODE:model/queue_model.h -->
**`model/queue_model.h`**

```c
#ifndef L043_QUEUE_MODEL_H
#define L043_QUEUE_MODEL_H
#include <stdint.h>

#define QM_CAPACITY UINT32_C(2)
#define QM_PRODUCER UINT32_C(0)
#define QM_CONSUMER UINT32_C(1)
#define QM_NONE UINT32_C(2)
#define QM_OK UINT32_C(0)
#define QM_FULL UINT32_C(1)
#define QM_EMPTY UINT32_C(2)
#define QM_BLOCKED UINT32_C(3)
#define QM_INVALID UINT32_C(4)
#define QM_READY UINT32_C(0)
#define QM_WAIT_SEND UINT32_C(1)
#define QM_WAIT_RECEIVE UINT32_C(2)

typedef struct {
    uint32_t sequence;
    int32_t value;
} QueueMessage;

typedef struct {
    uint32_t priority;
    uint32_t state;
    uint32_t operation;
    uint32_t deadline;
    uint32_t result;
    const QueueMessage *source;
    QueueMessage *destination;
} ModelTask;

typedef struct {
    QueueMessage slots[QM_CAPACITY];
    uint32_t head;
    uint32_t count;
    uint32_t tick;
    ModelTask tasks[2];
} QueueModel;

void QM_Init(QueueModel *model, uint32_t producer_priority,
             uint32_t consumer_priority);
uint32_t QM_Send(QueueModel *model, const QueueMessage *source,
                 uint32_t wait_ticks);
uint32_t QM_Receive(QueueModel *model, QueueMessage *destination,
                    uint32_t wait_ticks);
uint32_t QM_Resume(QueueModel *model, uint32_t task);
uint32_t QM_Tick(QueueModel *model, uint32_t elapsed);
uint32_t QM_Pick(const QueueModel *model);
#endif
```
<!-- END CODE:model/queue_model.h -->
<!-- BEGIN CODE:model/queue_model.c -->
**`model/queue_model.c`**

```c
#include <stddef.h>
#include <string.h>
#include "queue_model.h"

#define OP_NONE UINT32_C(0)
#define OP_SEND UINT32_C(1)
#define OP_RECEIVE UINT32_C(2)

static uint32_t Finish(ModelTask *task, uint32_t result)
{
    task->state = QM_READY;
    task->operation = OP_NONE;
    task->source = NULL;
    task->destination = NULL;
    task->result = result;
    return result;
}

void QM_Init(QueueModel *q, uint32_t producer_priority,
             uint32_t consumer_priority)
{
    memset(q, 0, sizeof(*q));
    q->tasks[QM_PRODUCER].priority = producer_priority;
    q->tasks[QM_CONSUMER].priority = consumer_priority;
}

uint32_t QM_Resume(QueueModel *q, uint32_t id)
{
    ModelTask *task;
    if (q == NULL || id >= QM_NONE) {
        return QM_INVALID;
    }
    task = &q->tasks[id];
    if (task->operation == OP_NONE || task->state != QM_READY) {
        return QM_INVALID;
    }
    if (task->operation == OP_SEND && q->count < QM_CAPACITY) {
        uint32_t tail = (q->head + q->count) % QM_CAPACITY;
        q->slots[tail] = *task->source;
        ++q->count;
        if (q->tasks[QM_CONSUMER].state == QM_WAIT_RECEIVE) {
            q->tasks[QM_CONSUMER].state = QM_READY;
        }
        return Finish(task, QM_OK);
    }
    if (task->operation == OP_RECEIVE && q->count > 0U) {
        *task->destination = q->slots[q->head];
        q->head = (q->head + 1U) % QM_CAPACITY;
        --q->count;
        if (q->tasks[QM_PRODUCER].state == QM_WAIT_SEND) {
            q->tasks[QM_PRODUCER].state = QM_READY;
        }
        return Finish(task, QM_OK);
    }
    if (q->tick >= task->deadline) {
        uint32_t result = task->operation == OP_SEND ? QM_FULL : QM_EMPTY;
        return Finish(task, result);
    }
    task->state = task->operation == OP_SEND ? QM_WAIT_SEND : QM_WAIT_RECEIVE;
    task->result = QM_BLOCKED;
    return QM_BLOCKED;
}

uint32_t QM_Send(QueueModel *q, const QueueMessage *source,
                 uint32_t wait_ticks)
{
    ModelTask *task;
    if (q == NULL || source == NULL || wait_ticks > UINT32_MAX - q->tick) {
        return QM_INVALID;
    }
    task = &q->tasks[QM_PRODUCER];
    if (task->operation != OP_NONE) {
        return QM_INVALID;
    }
    task->source = source;
    task->operation = OP_SEND;
    task->deadline = q->tick + wait_ticks;
    return QM_Resume(q, QM_PRODUCER);
}

uint32_t QM_Receive(QueueModel *q, QueueMessage *destination,
                    uint32_t wait_ticks)
{
    ModelTask *task;
    if (q == NULL || destination == NULL || wait_ticks > UINT32_MAX - q->tick) {
        return QM_INVALID;
    }
    task = &q->tasks[QM_CONSUMER];
    if (task->operation != OP_NONE) {
        return QM_INVALID;
    }
    task->destination = destination;
    task->operation = OP_RECEIVE;
    task->deadline = q->tick + wait_ticks;
    return QM_Resume(q, QM_CONSUMER);
}

uint32_t QM_Tick(QueueModel *q, uint32_t elapsed)
{
    uint32_t id;
    if (q == NULL || elapsed > UINT32_MAX - q->tick) {
        return QM_INVALID;
    }
    q->tick += elapsed;
    for (id = 0U; id < QM_NONE; ++id) {
        ModelTask *task = &q->tasks[id];
        if (task->state != QM_READY && q->tick >= task->deadline) {
            task->state = QM_READY;
        }
    }
    return QM_OK;
}

uint32_t QM_Pick(const QueueModel *q)
{
    uint32_t best = QM_NONE;
    uint32_t id;
    if (q == NULL) {
        return best;
    }
    for (id = 0U; id < QM_NONE; ++id) {
        if (q->tasks[id].state == QM_READY &&
            (best == QM_NONE || q->tasks[id].priority > q->tasks[best].priority)) {
            best = id;
        }
    }
    return best;
}
```
<!-- END CODE:model/queue_model.c -->
<!-- BEGIN CODE:tests/test_queue_model.c -->
**`tests/test_queue_model.c`**

```c
#include <stdio.h>
#include <string.h>
#include "queue_model.h"

#define CHECK(expr) do { if (!(expr)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #expr); return 1; \
} } while (0)

/* Break caught: aliased storage, missing second copy, or FIFO changed to LIFO. */
static int CopyAndFifo(int wrong_expected)
{
    QueueModel q;
    QueueMessage a = {10U, 110};
    QueueMessage b = {20U, 220};
    QueueMessage out = {0U, 0};
    QM_Init(&q, 1U, 2U);
    CHECK(QM_Send(&q, &a, 0U) == QM_OK);
    a.sequence = 999U;
    a.value = -1;
    CHECK(QM_Send(&q, &b, 0U) == QM_OK);
    CHECK(QM_Receive(&q, &out, 0U) == QM_OK);
    CHECK(out.sequence == (wrong_expected ? 999U : 10U));
    CHECK(out.value == 110);
    out.value = -2;
    CHECK(QM_Receive(&q, &out, 0U) == QM_OK);
    CHECK(out.sequence == 20U && out.value == 220);
    CHECK(q.count == 0U);
    return 0;
}

/* Break caught: full queue overwrites an existing record. */
static int FullKeepsOldMessages(void)
{
    QueueModel q;
    QueueMessage a = {1U, 11}, b = {2U, 22}, c = {3U, 33}, out;
    QM_Init(&q, 1U, 2U);
    CHECK(QM_Send(&q, &a, 0U) == QM_OK);
    CHECK(QM_Send(&q, &b, 0U) == QM_OK);
    CHECK(QM_Send(&q, &c, 0U) == QM_FULL);
    CHECK(q.count == 2U);
    CHECK(QM_Receive(&q, &out, 0U) == QM_OK && out.sequence == 1U);
    CHECK(QM_Receive(&q, &out, 0U) == QM_OK && out.sequence == 2U);
    return 0;
}

/* Break caught: failure changes the receive buffer or fabricates an item. */
static int EmptyPreservesOutput(void)
{
    QueueModel q;
    QueueMessage out = {77U, -77};
    QM_Init(&q, 1U, 2U);
    CHECK(QM_Receive(&q, &out, 0U) == QM_EMPTY);
    CHECK(out.sequence == 77U && out.value == -77);
    CHECK(q.count == 0U && q.tasks[QM_CONSUMER].state == QM_READY);
    return 0;
}

/* Break caught: wake completes a receive before the task actually resumes. */
static int ReceiveWakeAndResume(void)
{
    QueueModel q;
    QueueMessage in = {7U, 70}, out = {99U, -99};
    QM_Init(&q, 1U, 2U);
    CHECK(QM_Receive(&q, &out, 8U) == QM_BLOCKED);
    CHECK(q.tasks[QM_CONSUMER].state == QM_WAIT_RECEIVE);
    CHECK(QM_Pick(&q) == QM_PRODUCER);
    CHECK(QM_Send(&q, &in, 0U) == QM_OK);
    CHECK(q.tasks[QM_CONSUMER].state == QM_READY);
    CHECK(q.tasks[QM_CONSUMER].result == QM_BLOCKED);
    CHECK(q.count == 1U && out.sequence == 99U);
    CHECK(QM_Pick(&q) == QM_CONSUMER);
    CHECK(QM_Resume(&q, QM_CONSUMER) == QM_OK);
    CHECK(out.sequence == 7U && out.value == 70 && q.count == 0U);
    return 0;
}

/* Break caught: waking a lower-priority task is treated as immediate running. */
static int LowerPriorityWakeDoesNotWin(void)
{
    QueueModel q;
    QueueMessage in = {8U, 80}, out = {0U, 0};
    QM_Init(&q, 2U, 1U);
    CHECK(QM_Receive(&q, &out, 8U) == QM_BLOCKED);
    CHECK(QM_Send(&q, &in, 0U) == QM_OK);
    CHECK(q.tasks[QM_CONSUMER].state == QM_READY);
    CHECK(QM_Pick(&q) == QM_PRODUCER);
    CHECK(out.sequence == 0U && q.count == 1U);
    return 0;
}

/* Break caught: a blocked send copies early or fails to resume after space. */
static int SendWakeAndResume(void)
{
    QueueModel q;
    QueueMessage a = {1U, 11}, b = {2U, 22}, c = {3U, 33}, out;
    QM_Init(&q, 2U, 1U);
    CHECK(QM_Send(&q, &a, 0U) == QM_OK);
    CHECK(QM_Send(&q, &b, 0U) == QM_OK);
    CHECK(QM_Send(&q, &c, 9U) == QM_BLOCKED);
    CHECK(q.tasks[QM_PRODUCER].state == QM_WAIT_SEND);
    CHECK(QM_Receive(&q, &out, 0U) == QM_OK && out.sequence == 1U);
    CHECK(q.tasks[QM_PRODUCER].state == QM_READY);
    CHECK(q.count == 1U && q.tasks[QM_PRODUCER].result == QM_BLOCKED);
    CHECK(QM_Pick(&q) == QM_PRODUCER);
    CHECK(QM_Resume(&q, QM_PRODUCER) == QM_OK && q.count == 2U);
    CHECK(QM_Receive(&q, &out, 0U) == QM_OK && out.sequence == 2U);
    CHECK(QM_Receive(&q, &out, 0U) == QM_OK && out.sequence == 3U);
    return 0;
}

/* Break caught: timeout is early/late or changes an unsuccessful output. */
static int ReceiveTimeout(void)
{
    QueueModel q;
    QueueMessage out = {55U, -55};
    QM_Init(&q, 1U, 2U);
    CHECK(QM_Tick(&q, 10U) == QM_OK);
    CHECK(QM_Receive(&q, &out, 3U) == QM_BLOCKED);
    CHECK(QM_Tick(&q, 2U) == QM_OK);
    CHECK(q.tasks[QM_CONSUMER].state == QM_WAIT_RECEIVE);
    CHECK(QM_Tick(&q, 1U) == QM_OK);
    CHECK(q.tasks[QM_CONSUMER].state == QM_READY);
    CHECK(q.tasks[QM_CONSUMER].result == QM_BLOCKED);
    CHECK(QM_Resume(&q, QM_CONSUMER) == QM_EMPTY);
    CHECK(out.sequence == 55U && out.value == -55);
    return 0;
}

/* Break caught: expired send adds a message or damages existing FIFO data. */
static int SendTimeout(void)
{
    QueueModel q;
    QueueMessage a = {1U, 11}, b = {2U, 22}, c = {3U, 33}, out;
    QM_Init(&q, 2U, 1U);
    CHECK(QM_Send(&q, &a, 0U) == QM_OK);
    CHECK(QM_Send(&q, &b, 0U) == QM_OK);
    CHECK(QM_Send(&q, &c, 4U) == QM_BLOCKED);
    CHECK(QM_Tick(&q, 4U) == QM_OK);
    CHECK(QM_Resume(&q, QM_PRODUCER) == QM_FULL && q.count == 2U);
    CHECK(QM_Receive(&q, &out, 0U) == QM_OK && out.sequence == 1U);
    CHECK(QM_Receive(&q, &out, 0U) == QM_OK && out.sequence == 2U);
    return 0;
}

/* Break caught: null input, double call, or unsupported tick wrap is accepted. */
static int RejectInvalidEvents(void)
{
    QueueModel q;
    QueueMessage out = {0U, 0};
    QM_Init(&q, 1U, 2U);
    CHECK(QM_Send(&q, NULL, 0U) == QM_INVALID);
    CHECK(QM_Receive(&q, NULL, 0U) == QM_INVALID);
    CHECK(QM_Resume(&q, QM_NONE) == QM_INVALID);
    CHECK(QM_Resume(&q, QM_CONSUMER) == QM_INVALID);
    CHECK(QM_Receive(&q, &out, 3U) == QM_BLOCKED);
    CHECK(QM_Receive(&q, &out, 3U) == QM_INVALID);
    CHECK(QM_Tick(&q, UINT32_MAX) == QM_OK);
    CHECK(QM_Tick(&q, 1U) == QM_INVALID);
    CHECK(QM_Resume(&q, QM_CONSUMER) == QM_EMPTY);
    CHECK(QM_Receive(&q, &out, 1U) == QM_INVALID);
    return 0;
}

int main(int argc, char **argv)
{
    int wrong = argc == 2 && strcmp(argv[1], "--wrong-expected") == 0;
    if (CopyAndFifo(wrong) || FullKeepsOldMessages() || EmptyPreservesOutput() ||
        ReceiveWakeAndResume() || LowerPriorityWakeDoesNotWin() ||
        SendWakeAndResume() || ReceiveTimeout() || SendTimeout() ||
        RejectInvalidEvents()) {
        return 1;
    }
    puts("PASS 9 queue-model tests; not FreeRTOS or STM32 execution");
    return 0;
}
```
<!-- END CODE:tests/test_queue_model.c -->

### 9.3 目标配置与错误接口

层次：配置供内核/HAL 读取，错误出口依赖 CMSIS 的关中断/空操作。应用接口使用固定宽度整数；FreeRTOS 原生 API 的 `BaseType_t/UBaseType_t/TickType_t` 按固定端口使用，不私自改内核 ABI。禁止动态分配，软件定时器关闭，Idle 任务仍须静态提供内存。

HAL 配置里的 `HSE_VALUE=0`、`EXTERNAL_CLOCK_VALUE=0` 是**未使用的外部时钟哨兵值**，不是对板卡频率的断言。后续若启用 HSE/外部时钟，必须先按真实板卡替换，并重新审计整条时钟链。LSI/LSE 常量也不表示本例启动了它们。`USE_RTOS=0` 是该 HAL 保留选项，不是把 FreeRTOS 关掉；F4 HAL 的 Flash 加速配置也不是 F7/H7 的内核数据缓存策略。[S5]

<!-- BEGIN CODE:target/app_fatal.h -->
**`target/app_fatal.h`**

```c
#ifndef L043_APP_FATAL_H
#define L043_APP_FATAL_H
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
#define APP_FATAL_MESSAGE UINT32_C(11)

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
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H
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
#define configUSE_TIMERS 0
#define configUSE_MUTEXES 0
#define configUSE_RECURSIVE_MUTEXES 0
#define configUSE_COUNTING_SEMAPHORES 0
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
/* interrupts.c owns the only SysTick wrapper; do not alias it here. */
#endif
```
<!-- END CODE:target/FreeRTOSConfig.h -->
<!-- BEGIN CODE:target/stm32f4xx_hal_conf.h -->
**`target/stm32f4xx_hal_conf.h`**

```c
#ifndef STM32F4XX_HAL_CONF_H
#define STM32F4XX_HAL_CONF_H
#include "app_fatal.h"

#define HAL_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_FLASH_MODULE_ENABLED
#define HSI_VALUE 16000000U
#define HSE_VALUE 0U /* Unused. Set from the real board before ever enabling HSE. */
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
#define assert_param(expr) do { if ((expr) == 0U) { \
    App_Fatal(APP_FATAL_ASSERT, (uint32_t)__LINE__); } } while (0)
#endif
```
<!-- END CODE:target/stm32f4xx_hal_conf.h -->

### 9.4 目标消息、对象、组装和使用

层次：本应用适配依赖 FreeRTOS API，不依赖具体外设。`s_queue_control/storage`、两组栈/控制块、上下文和句柄全部为文件静态对象；组装只调用一次。两个 context 在启动前写好、启动后只读，task 参数指向这些永久上下文，而不是创建函数栈上的对象。Idle 的控制块和栈也在回调内 `static` 定义，不能省略。

默认 P 每次操作后 `vTaskDelay(20 tick)`，C 每次操作后延时 5 tick；P 发送最长等 10，C 接收最长等 100，都是小常量经 `pdMS_TO_TICKS` 换算。**这是相对延时，不是硬件周期采样，更不是吞吐率保证**。局部样本成功复制后改成其他值，消费者仍应检查原副本；优化编译器可能消除无后续观察的局部改写，不以调试器总能看到这两次赋值为验收条件。

发送失败时本课计数并放弃本次序号，所以下次成功接收可能出现序号间隙；不能把间隙一律判为内存损坏。`g_send_ok` 在 send 返回后才递增，而消费者可能已在该调用内抢占并接收，因此断点瞬间 `g_receive_ok > g_send_ok` 并不自动是队列错误。多字段调试变量不是原子快照；`volatile` 仅方便观察，不是并发同步协议。

<!-- BEGIN CODE:target/app_queue.h -->
**`target/app_queue.h`**

```c
#ifndef L043_APP_QUEUE_H
#define L043_APP_QUEUE_H
#include <stdint.h>

typedef struct {
    uint32_t sequence;
    int32_t value;
} SampleMessage;

uint32_t App_CreateQueueTasks(void);
#endif
```
<!-- END CODE:target/app_queue.h -->
<!-- BEGIN CODE:target/app_queue.c -->
**`target/app_queue.c`**

```c
#include "FreeRTOS.h"
#include "task.h"
#include "queue.h"
#include "app_queue.h"
#include "app_fatal.h"

#define APP_QUEUE_LENGTH 2U
#define APP_STACK_WORDS 256U
#ifndef APP_PRODUCER_MS
#define APP_PRODUCER_MS 20U
#endif
#ifndef APP_CONSUMER_MS
#define APP_CONSUMER_MS 5U
#endif
#ifndef APP_SEND_WAIT_MS
#define APP_SEND_WAIT_MS 10U
#endif
#ifndef APP_RECEIVE_WAIT_MS
#define APP_RECEIVE_WAIT_MS 100U
#endif

_Static_assert(sizeof(SampleMessage) == 8U, "Check target message layout");

typedef struct {
    QueueHandle_t queue;
    TickType_t wait_ticks;
    TickType_t pause_ticks;
} QueueTaskContext;

static StaticQueue_t s_queue_control;
static uint8_t s_queue_storage[APP_QUEUE_LENGTH * sizeof(SampleMessage)];
static QueueHandle_t s_queue;
static StaticTask_t s_producer_control, s_consumer_control;
static StackType_t s_producer_stack[APP_STACK_WORDS];
static StackType_t s_consumer_stack[APP_STACK_WORDS];
static TaskHandle_t s_producer_handle, s_consumer_handle;
static QueueTaskContext s_producer_context, s_consumer_context;
static uint32_t s_create_attempted;

volatile uint32_t g_send_ok;
volatile uint32_t g_send_timeout;
volatile uint32_t g_receive_ok;
volatile uint32_t g_receive_timeout;
volatile uint32_t g_last_sequence;
volatile int32_t g_last_value;

static const QueueTaskContext *CheckedContext(void *argument)
{
    const QueueTaskContext *context = argument;
    if (context == NULL || context->queue == NULL || context->pause_ticks == 0U) {
        App_Fatal(APP_FATAL_PARAMETER, (uint32_t)__LINE__);
    }
    return context;
}

static void ProducerEntry(void *argument)
{
    const QueueTaskContext *context = CheckedContext(argument);
    uint32_t sequence = 0U;
    for (;;) {
        SampleMessage message = {sequence, (int32_t)(sequence % 1000U)};
        if (xQueueSend(context->queue, &message, context->wait_ticks) == pdPASS) {
            ++g_send_ok;
        } else {
            ++g_send_timeout;
        }
        message.sequence = UINT32_MAX;
        message.value = -1;
        ++sequence;
        vTaskDelay(context->pause_ticks);
    }
}

static void ConsumerEntry(void *argument)
{
    const QueueTaskContext *context = CheckedContext(argument);
    for (;;) {
        SampleMessage message = {0U, 0};
        if (xQueueReceive(context->queue, &message, context->wait_ticks) == pdPASS) {
            if (message.value != (int32_t)(message.sequence % 1000U)) {
                App_Fatal(APP_FATAL_MESSAGE, (uint32_t)__LINE__);
            }
            g_last_sequence = message.sequence;
            g_last_value = message.value;
            ++g_receive_ok;
        } else {
            ++g_receive_timeout;
        }
        vTaskDelay(context->pause_ticks);
    }
}

uint32_t App_CreateQueueTasks(void)
{
    if (s_create_attempted != 0U) {
        return 1U;
    }
    s_create_attempted = 1U;
    s_queue = xQueueCreateStatic(APP_QUEUE_LENGTH, sizeof(SampleMessage),
                                 s_queue_storage, &s_queue_control);
    if (s_queue == NULL) {
        return 1U;
    }
    s_producer_context.queue = s_queue;
    s_producer_context.wait_ticks = pdMS_TO_TICKS(APP_SEND_WAIT_MS);
    s_producer_context.pause_ticks = pdMS_TO_TICKS(APP_PRODUCER_MS);
    s_consumer_context.queue = s_queue;
    s_consumer_context.wait_ticks = pdMS_TO_TICKS(APP_RECEIVE_WAIT_MS);
    s_consumer_context.pause_ticks = pdMS_TO_TICKS(APP_CONSUMER_MS);
    if (s_producer_context.pause_ticks == 0U || s_consumer_context.pause_ticks == 0U) {
        return 1U;
    }
    s_producer_handle = xTaskCreateStatic(ProducerEntry, "Producer", APP_STACK_WORDS,
                                        &s_producer_context, 1U,
                                        s_producer_stack, &s_producer_control);
    s_consumer_handle = xTaskCreateStatic(ConsumerEntry, "Consumer", APP_STACK_WORDS,
                                        &s_consumer_context, 2U,
                                        s_consumer_stack, &s_consumer_control);
    return s_producer_handle == NULL || s_consumer_handle == NULL ? 1U : 0U;
}

void vApplicationGetIdleTaskMemory(StaticTask_t **control, StackType_t **stack,
                                   uint32_t *depth)
{
    static StaticTask_t idle_control;
    static StackType_t idle_stack[configMINIMAL_STACK_SIZE];
    *control = &idle_control;
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
<!-- END CODE:target/app_queue.c -->

### 9.5 目标时钟与异常归属

层次：启动/硬件适配依赖 HAL/CMSIS，组装入口依赖应用，内核不依赖应用时钟函数。`RCC_*InitTypeDef` 只在初始化函数中临时存在，HAL 使用后无需保持；真正长期存在的对象是队列/任务内存。SysTick 所有权标记只在启动前从 0 变 1，调度启动后不来回切换。

`interrupts.c` 的末尾 `__DSB`（Data Synchronization Barrier，数据同步屏障）对应 ES0182 2.1.3 的异常返回注意事项；仍须按实际硅版本审计适用勘误，不能以一个屏障宣称所有异常勘误都已验证。[S11] SVC/PendSV 从端口映射到启动向量名，不再加同名的应用空函数。

<!-- BEGIN CODE:target/interrupts.h -->
**`target/interrupts.h`**

```c
#ifndef L043_INTERRUPTS_H
#define L043_INTERRUPTS_H
#include <stdint.h>
extern volatile uint32_t g_kernel_owns_systick;
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
    __DSB(); /* ES0182 2.1.3: check actual silicon revision during integration. */
}
/* The GCC ARM_CM4F port supplies SVC_Handler and PendSV_Handler. */
```
<!-- END CODE:target/interrupts.c -->
<!-- BEGIN CODE:target/main.c -->
**`target/main.c`**

```c
#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"
#include "app_queue.h"
#include "app_fatal.h"
#include "interrupts.h"

volatile uint32_t g_main_phase;

/* Genuine reset + matching SystemInit only; no bootloader handoff is assumed. */
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
    /* This fixed HAL ignores the return from its nested HAL_InitTick calls. */
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

    /* One-way handoff: never use timed HAL operations after this point. */
    __disable_irq();
    HAL_SuspendTick();
    SysTick->CTRL = 0U;
    SysTick->VAL = 0U;
    SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk | SCB_ICSR_PENDSVCLR_Msk;
    __DSB();
    __ISB();
    if (App_CreateQueueTasks() != 0U) {
        App_Fatal(APP_FATAL_CREATE, (uint32_t)__LINE__);
    }
    g_kernel_owns_systick = 1U;
    g_main_phase = 3U;
    vTaskStartScheduler();
    App_Fatal(APP_FATAL_SCHED_RETURN, (uint32_t)__LINE__);
}
```
<!-- END CODE:target/main.c -->

### 9.6 可重复的主机运行脚本

层次：开发工具→主机编译器→原创模型测试。脚本只新建/写入调用者指定的输出目录，无递归删除；变异副本与可执行文件不进入既有课程。第二个脚本只作语法检查，不产生目标固件。请用独立输出目录保存每次实验，避免把旧日志当新日志。

<!-- BEGIN CODE:tools/test-host.ps1 -->
**`tools/test-host.ps1`**

```powershell
param(
    [Parameter(Mandatory=$true)][string]$BuildDir,
    [Parameter(Mandatory=$true)][string]$EvidenceDir,
    [string]$Compiler = 'gcc'
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$lesson = Split-Path -Parent $PSScriptRoot
$build = [IO.Path]::GetFullPath($BuildDir)
$evidence = [IO.Path]::GetFullPath($EvidenceDir)
New-Item -ItemType Directory -Force $build,$evidence | Out-Null
$compilerPath = (Get-Command $Compiler -ErrorAction Stop).Source
$version = & $compilerPath --version
if ($LASTEXITCODE -ne 0) { throw 'Compiler version command failed' }
$version | Set-Content -Encoding utf8 (Join-Path $evidence 'compiler-version.log')
$model = Join-Path $lesson 'model/queue_model.c'
$tests = Join-Path $lesson 'tests/test_queue_model.c'
$results = [Collections.Generic.List[object]]::new()

function Invoke-Case([string]$Name, [string]$Source, [string[]]$TestArgs,
                     [bool]$ShouldPass, [string]$FailureText = '') {
    $exe = Join-Path $build "$Name.exe"
    $flags = @('-std=c11','-Wall','-Wextra','-Werror','-pedantic',
               '-I',(Join-Path $lesson 'model'),$Source,$tests,'-o',$exe)
    $compileOutput = & $compilerPath @flags 2>&1
    $compileExit = $LASTEXITCODE
    $compileOutput | Set-Content -Encoding utf8 (Join-Path $evidence "$Name-compile.log")
    if ($compileExit -ne 0) { throw "$Name compilation failed: $compileOutput" }
    $output = & $exe @TestArgs 2>&1
    $testExit = $LASTEXITCODE
    $text = $output -join "`n"
    $text | Set-Content -Encoding utf8 (Join-Path $evidence "$Name-test.log")
    if (($ShouldPass -and $testExit -ne 0) -or
        (-not $ShouldPass -and ($testExit -eq 0 -or -not $text.Contains($FailureText)))) {
        throw "$Name unexpected exit/output: $testExit $text"
    }
    $results.Add([pscustomobject]@{
        name=$Name; compiler=$compilerPath; arguments=$flags; compile_exit=$compileExit
        test_arguments=$TestArgs; test_exit=$testExit; expected_pass=$ShouldPass
        source_sha256=(Get-FileHash -LiteralPath $Source).Hash.ToLowerInvariant()
        test_sha256=(Get-FileHash -LiteralPath $tests).Hash.ToLowerInvariant()
    })
    Write-Host "$Name : expected result observed (exit $testExit)"
}

Invoke-Case 'green' $model @() $true
Invoke-Case 'wrong-expected' $model @('--wrong-expected') $false 'out.sequence =='
$original = Get-Content -Raw -LiteralPath $model
$mutations = @(
    @('red-copy', 'q->slots[tail] = *task->source;',
       'q->slots[tail] = *task->source; q->slots[tail].sequence = 999U;', 'out.sequence =='),
    @('red-fifo', '*task->destination = q->slots[q->head];',
       '*task->destination = q->slots[(q->head + q->count - 1U) % QM_CAPACITY];', 'out.sequence =='),
    @('red-wake', 'q->tasks[QM_CONSUMER].state = QM_READY;',
       'q->tasks[QM_CONSUMER].state = QM_WAIT_RECEIVE;', 'q.tasks[QM_CONSUMER].state == QM_READY')
)
foreach ($mutation in $mutations) {
    if (-not $original.Contains($mutation[1])) { throw "Mutation anchor missing: $($mutation[0])" }
    $mutant = Join-Path $build "$($mutation[0]).c"
    [IO.File]::WriteAllText($mutant, $original.Replace($mutation[1],$mutation[2]))
    Invoke-Case $mutation[0] $mutant @() $false $mutation[3]
}
Invoke-Case 'final-green' $model @() $true
[pscustomobject]@{
    recorded_at=(Get-Date).ToString('o'); scope='Host teaching model only; not kernel/target execution'
    model_sha256=(Get-FileHash -LiteralPath $model).Hash.ToLowerInvariant()
    results=@($results.ToArray())
} | ConvertTo-Json -Depth 7 | Set-Content -Encoding utf8 (Join-Path $evidence 'host-results.json')
```
<!-- END CODE:tools/test-host.ps1 -->
<!-- BEGIN CODE:tools/check-reference-syntax.ps1 -->
**`tools/check-reference-syntax.ps1`**

```powershell
param(
    [Parameter(Mandatory=$true)][string]$CubeF4Root,
    [Parameter(Mandatory=$true)][string]$EvidenceDir,
    [string]$Compiler = 'gcc'
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$lesson = Split-Path -Parent $PSScriptRoot
$package = (Resolve-Path -LiteralPath $CubeF4Root).Path
$kernel = Join-Path $package 'Middlewares/Third_Party/FreeRTOS/Source'
$evidence = [IO.Path]::GetFullPath($EvidenceDir)
New-Item -ItemType Directory -Force $evidence | Out-Null
$compilerPath = (Get-Command $Compiler -ErrorAction Stop).Source
$includes = @(
    (Join-Path $lesson 'target'),
    (Join-Path $kernel 'include'),
    (Join-Path $kernel 'portable/GCC/ARM_CM4F'),
    (Join-Path $package 'Drivers/STM32F4xx_HAL_Driver/Inc'),
    (Join-Path $package 'Drivers/CMSIS/Include'),
    (Join-Path $package 'Drivers/CMSIS/Device/ST/STM32F4xx/Include')
)
$flags = @('-std=c11','-fsyntax-only','-Wall','-Wextra','-Werror',
           '-Wno-int-to-pointer-cast','-Wno-pointer-to-int-cast',
           '-DSTM32F407xx','-DUSE_HAL_DRIVER')
foreach ($include in $includes) {
    if (-not (Test-Path -LiteralPath $include -PathType Container)) { throw "Missing include: $include" }
    $flags += @('-I',$include)
}
$results = foreach ($file in Get-ChildItem -LiteralPath (Join-Path $lesson 'target') -Filter '*.c' -File) {
    $arguments = $flags + @($file.FullName)
    $output = & $compilerPath @arguments 2>&1
    $code = $LASTEXITCODE
    $output | Set-Content -Encoding utf8 (Join-Path $evidence "$($file.BaseName)-syntax.log")
    if ($code -ne 0) { throw "Host syntax check failed: $($file.Name): $output" }
    [pscustomobject]@{file=$file.Name;sha256=(Get-FileHash -LiteralPath $file.FullName).Hash.ToLowerInvariant();arguments=$arguments;exit=$code}
}
[pscustomobject]@{
    recorded_at=(Get-Date).ToString('o');compiler=$compilerPath;package=$package
    scope='Host GCC C front-end syntax only with real vendor headers; no ARM code generation, assembly, link or target execution'
    waived_warnings=@('int-to-pointer-cast','pointer-to-int-cast')
    results=@($results)
} | ConvertTo-Json -Depth 7 | Set-Content -Encoding utf8 (Join-Path $evidence 'reference-syntax.json')
Write-Host 'PASS 4 application C files: host syntax only, NOT an ARM build'
```
<!-- END CODE:tools/check-reference-syntax.ps1 -->

## 10. 常见错误

| 错误 | 为什么错 | 应改为 |
| --- | --- | --- |
| 项大小写 `sizeof(QueueHandle_t)` 或发送时误传 `&pointer` | 实际复制规格与消息对象不符，可能只复制地址或越界读取 | 本例创建用 `sizeof(SampleMessage)`，发送 `&message` |
| 在创建函数里定义非 static 槽位/控制块/context | 创建返回后内核/任务仍使用失效地址 | 永久静态对象，或经证明的整个使用期对象 |
| 忽略 send 返回值，假设第三项覆盖第一项 | 普通 send 满不会覆盖；业务记录可能已丢弃 | 检查 `==pdPASS`，把失败计数与策略写清 |
| receive 失败还处理上次数据 | 没有新消息却使用旧缓冲 | 只在成功分支使用本次记录 |
| 以为 N tick 就必须等满 N | 条件满足可立即完成 | 分开条件、阻塞上限、返回和调度 |
| 以为任务一就绪就在运行 | 高优先级其他任务/切换时机影响运行 | 检查等待者状态及所有就绪者优先级 |
| 用 100 ms 直接作为 100 tick | 节拍频率不一定 1000 Hz | 明确换算并检查截断/溢出 |
| 认为按值复制包含深拷贝 | 消息含指针时只复制指针 | 本课只用自包含小结构；指针协议以后学 |
| 临时把消费延时调大却不观察发送失败 | 长度有限不能吞掉持续速率差 | 实验同时看两个计数与队列深度 |
| 在本例任务中加入 HAL_Delay/有超时 HAL 操作 | HAL tick 已单向移交，不再推进 | 本例只用内核等待；外设集成另建经核对的 HAL 时基 |
| 用主机语法日志宣称 ARM 编译成功 | 没有目标代码生成、端口汇编和链接 | 按证据分层报告 |

## 11. 调试观察点

目标观察均为**待执行**，不是本课已测结果：

| 观察位置 | 看什么 | 能排除/不能排除什么 |
| --- | --- | --- |
| `main` 的阶段标记 | `g_main_phase` 依次 1/2/3；`g_error_code/line` | 区分 HAL、时钟、创建、调度返回；3 只代表到调度调用附近，不证明任务已运行 |
| 时钟切换后 | RCC CR/CFGR、SystemCoreClock=16000000；PLL OFF | 确认选择/软件推算，不是实测 HSI 精度 |
| 调度启动后 | SysTick LOAD=15999，CTRL 时钟/使能位；唯一处理者；tick 前进 | 排查 tick 不动、错误时基和重复 handler；读取 CTRL 会影响 COUNTFLAG 的观察 [S8] |
| 队列控制块 | 固定版 `queue.c` 的 `uxMessagesWaiting` 在 0～2；项大小 8，长度 2 | 在正确内核调试类型上下文观察，不把 StaticQueue_t 的占位字段当稳定 ABI，不直接修改它们 |
| 消息复制前后 | 发送源、内部项、接收目标的值/地址 | 三者不应混为一个地址；高优化下局部变量可能不可见 |
| 等待路径 | `queue.c` send/receive 的条件分支、`xTasksWaitingToSend/Receive`；`tasks.c:xTaskRemoveFromEventList` | 分清正在等消息/空间还是已就绪未运行，不根据单次计数判断全部时序 |
| 应用使用 | `g_send_ok/timeout`、`g_receive_ok/timeout`、`g_last_sequence/value` | 计数各有任务写入，组合值不是同时刻快照；不要在热循环 printf 改变调度 |
| 栈与错误 | 两个静态任务句柄、`uxTaskGetStackHighWaterMark` 与 stack overflow hook（栈溢出钩子） | 高水位是辅助证据，不证明所有路径不会溢出；256 words 不是普适栈预算 |

长断点会停止或严重扰动 tick、生产/消费速率，无法据此精确测量毫秒；调试器读取和表达式调用也可能改变状态。优先在自然运行后暂停读取存储，再用独立基准验证时长，而不是靠单步耗时。[S8]

## 12. 实战实验

### 实验 A：主机复制、FIFO、满与空（已执行，可重复）

- 输入：9 组测试中的固定消息和 tick 事件；命令见 8.1。
- 预期：原版 9 组通过，错误预期和三个变异都非零失败；最后原版重新通过。
- 观察：`host-results.json` 的每条命令/退出码与对应测试日志，核对源码指纹。
- 失败判据：任何原版失败、任一变异错误地通过、变异因编译错误而非预期断言失败，或日志指纹不匹配，均不能报告全部通过。

### 实验 B：逐事件解释就绪与调用完成（主机可执行）

- 输入：`ReceiveWakeAndResume` 与 `SendWakeAndResume` 的事件序列；在模型源码断点停在唤醒赋值后、`QM_Resume` 前后。
- 预期：接收者已就绪时，目标仍是哨兵记录且队列仍有 1 项；继续后目标变成新消息、数量减 1。发送者已就绪时，第三项还未入队；继续后才增加。
- 观察：`state/operation/result/count` 四类信息；用一句话解释每次变化的原因。
- 失败判据：把 `QM_BLOCKED` 当 FreeRTOS 的实际返回值，或以模型暂存源指针推断真实队列始终只保存指针。

### 实验 C：F407 默认双任务（目标待执行）

- 输入：目标完整料号/真实构建环境及 8.2 的工程，默认宏 20/5/10/100 ms。
- 预期：消费者启动后先等空队列；生产者发送小结构；成功接收的 `value=sequence%1000`；运行一段时间后计数前进。正常负载下通常不会持续满，但这不是无丢包或固定吞吐率保证。
- 命令/步骤：按 8.2 新目标工程构建，记录完整日志；本任务不烧录。之后仅在用户另行安排并取得板上证据时进行自然运行观察。
- 失败判据：进入 fatal、tick 不前进、队列数量越界、成功分支的数据不一致，或参考工程仍混用两套内核/包装层。

### 实验 D：满等与空等（目标待执行，一次改一个因素）

1. 变慢消费者：新构建配置中设 `APP_CONSUMER_MS=100U`，其他默认；预计初期排队增加，持续输入后 `g_send_timeout` 可能增长，成功记录顺序不倒退但可有被放弃的序号间隙。先说明预测依据，再记录实际轨迹，不能把公式当已测结果。
2. 变慢生产者：恢复默认，单独设 `APP_PRODUCER_MS=1000U`；预计消费者的 100 ms 等待有机会超时，`g_receive_timeout` 增长；失败分支不消费旧记录。
3. 零等待：在第一个负载变体上再设 `APP_SEND_WAIT_MS=0U`；满时立即失败，不阻塞等空间；数据没有因此变可靠。

每个变体保存独立的编译宏、日志、自然运行计数与观察窗口；调试停机或重载会改变节拍，不比较不可比的窗口。不要直接修改官方 `queue.c` 制造故障，也不拿本次主机变异当目标固件版本。

### 实验 E：有限超时与低优先级就绪（目标待执行）

用源码断点观察原 receive/send 正在等待的任务，在事件和超时后分别如何进入就绪集合；结合 `tasks.c` 的固定版比较条件回答“谁能请求抢占”。如果要设计“低优先级接收者被唤醒但暂不运行”变体，先写出可行的先阻塞再唤醒顺序，不能仅交换任务优先级却仍声称同一条启动轨迹必定发生。实验报告区分实际运行顺序、断点扰动和源码推理；禁止从一次断点命中时间推出严格超时上限。

## 13. 自检题

1. 容量 2、项大小 8，槽位占多少字节？为什么不是总 RAM？
2. 成功 send 后立即把源结构体清零，消费者应得到什么？若 send 正在阻塞，源缓冲何时才可复用？
3. 满队列做零等待 send，哪一项被覆盖？
4. receive 失败后目标仍含上次数据，能再处理一次吗？
5. 等待 10 tick，条件一开始已满足时会发生什么？到期后是否保证那一毫秒执行完？
6. 消费者在 send 返回前已处理完一项，是否违背 FIFO？
7. 队列句柄、静态控制块、槽位存储、生产者局部消息、接收目标分别由谁持有？
8. 为什么没有“队列时钟使能”或本例的 DMA 完成回调？
9. 本课 HAL tick 交接后，为什么不能直接追加一个带 HAL 超时的外设调用？
10. 9 组主机测试与目标代码语法检查分别不能证明什么？

**核对要点**：1）16 字节槽位，另计控制块/上下文/任务存储；2）成功复制前值，阻塞调用最终完成前源一直有效且稳定；3）不覆盖，本次失败；4）不可以，只有成功才有新项；5）立即尝试，解除阻塞和返回存在调度延迟；6）不违背，接收者可能在发送调用中抢占；7）组装模块永久持有内核对象并传入上下文，任务各持局部消息；8）队列为 RAM 内核对象，最小例无外设采集；9）HAL uwTick 不再推进；10）不能证明内核/时基正确，也不能证明 ARM 构建、链接或硬件。答题和实验是否掌握另由用户反馈决定，不因阅读/生成就提高 mastery。

## 14. 面试题

### 题 1：静态队列是否“零拷贝”？

应答先说“不”。静态说明存储提供方式；发送/接收仍按项大小复制。要说清控制块与槽位各由谁提供、两次复制的时刻、消息生命周期。若换成指针项，只是复制地址，额外所有权协议不会自动出现。评分重点是把内存分配方式和数据搬运方式分开。[S1][S2][S5]

### 题 2：高优先级消费者已经唤醒，为何发送者还可能继续？

先澄清它是否真的比**当前运行任务**优先级高、抢占是否开启、是否处在可切换边界/调度受限情形；同级或低级并非该事件分支的立即抢占对象。再说明本课固定版事件路径与 tick 路径不同，不能只背“唤醒立即切换”。评分重点是状态、优先级、请求与实际运行的边界，而不是某一次 printf 顺序。[S5]

### 题 3：把队列从 2 改为 200 能解决丢消息吗？

只能吸收更长突发，不保证长期处理能力足够。应同时说明内存增加、排队延迟、输入/处理速率、满时应用策略与失败计数；不能把队列当资源锁、无限存储或固定速率保证。无需提前讲互斥量实现。[S1][S5]

### 题 4：主机测试通过，为什么仍 `hardware_verified=false`？

指出没有执行真实内核端口/ARM 完整工程/烧录/实际板卡观察，且主机模型拒绝环绕、不实现异常。列出真正需要的目标身份、固定包/工具链、构建与链接日志、下载及观察证据；不能把 C 前端语法通过换一种说法当已构建成功。

## 15. 延伸思考

- 如果只关心“发生了几次事件”而不需要逐条数据，为什么可能不该排队小结构？先写需求，留到 `semaphore`（信号量）/`notification`（任务通知）比较，不在本课实现。
- 如果消费者处理顺序不能被打乱，仅调高优先级能否保证及时？区分顺序正确、等待延迟与系统整体可调度性。
- 如果消息扩展为指针+长度，复制那 8 个字节后谁能复用原缓冲？画所有权链，不用“反正队列线程安全”作答。
- 如果把样本来源改为 DMA，中断发送成功后原缓冲何时被 DMA 覆盖？这是 `isr`/`dma-coherency` 要求补上的证据，而不是再套一次 send API。

这些问题只标示后续落点，不要求本课同时掌握第三个新核心机制。

## 16. 本节总结

静态有界队列用永久控制块/槽位承载有限记录，**成功发送和成功接收各完成一次按值复制**，从而分开两个任务的局部消息存储。条件不满足时，零等待立即失败，有限等待先阻塞；消息、空间或到期事件让等待者重新就绪，只有真正运行并继续原调用才得到最终结果。

本课已经留下主机模型正/负证据和应用 C 主机语法记录；F407 参考代码、时钟链、配置与集成步骤齐全，但目标完整构建和硬件验证仍未执行，`hardware_verified=false`。Teacher 交付时为 `status=draft`；只有 Reviewer 真正通过后才改为 `reviewed` 并推进课程路线状态。审核表示学习资产满足交付要求，不表示用户已经掌握；Teacher 自检不替代 Reviewer 结论，生成或审核也都不提高掌握度。

## 17. 下一步

课程路线下一主题为 `semaphore`：比较“传递每条消息数据”和“记录事件/资源许可”的需求，不把队列句柄误当资源所有权。之后 `notification` 比较无需排队数据时的唤醒，`memory` 核算长度/项大小/控制块/栈，`isr` 实现合规 UART/ADC DMA 回调传递及请求切换，`race-condition` 分析多任务竞争，`mutex`/`priority-inversion` 讨论资源所有权；本课不提前调用这些原语。

先提交 13 节的自检答案或 A/B 实验记录，再根据实际回答判断掌握情况。生成这一课本身不等于完成了 `queue` 学习，不推进长期 Device Framework 项目。

## 18. 参考资料

正式来源域均符合 `config/source-policy.toml`，以下编号与 `lesson.json.sources` 一一对应。访问日期为 2026-10-23；**官方网页正文是本次 HTTP 200 取得的内容，PDF/软件版本页是既有官方缓存本次重读并校验指纹**，不声称本次下载了全部最新版本。具体本机路径、阅读页/文件位置、SHA-256 见本次运行 `teacher-work/source-audit.json`；这不是 Reviewer 审核结果。

<!-- BEGIN SOURCES -->
- **[S1] FREERTOS-QUEUES — FreeRTOS Queues**。版本：Official live document body 2026-10-23; API semantics cross-checked with packaged V10.3.1。

  URL：https://www.freertos.org/Documentation/02-Kernel/02-Kernel-features/02-Queues-mutexes-and-semaphores/01-Queues；访问：2026-10-23；第一方：是。

  阅读位置/用途：FIFO、按值复制、小结构与指针项边界；多个等待者与队列集合入口。静态存储的具体约束另以 S2/S5 为准。

- **[S2] FREERTOS-STATIC-QUEUE — FreeRTOS xQueueCreateStatic**。版本：Official live document body 2026-10-23; API semantics cross-checked with packaged V10.3.1。

  URL：https://www.freertos.org/Documentation/02-Kernel/04-API-references/06-Queues/02-xQueueCreateStatic；访问：2026-10-23；第一方：是。

  阅读位置/用途：API 参数、length × item size 的字节区、独立 StaticQueue_t 与 configSUPPORT_STATIC_ALLOCATION。

- **[S3] FREERTOS-SEND — FreeRTOS xQueueSend**。版本：Official live document body 2026-10-23; API semantics cross-checked with packaged V10.3.1。

  URL：https://www.freertos.org/Documentation/02-Kernel/04-API-references/06-Queues/03-xQueueSend；访问：2026-10-23；第一方：是。

  阅读位置/用途：任务 API、按值发送、零/有限阻塞等待、pdPASS/errQUEUE_FULL；固定版宏和实现以 S5 核对。

- **[S4] FREERTOS-RECEIVE — FreeRTOS xQueueReceive**。版本：Official live document body 2026-10-23; API semantics cross-checked with packaged V10.3.1。

  URL：https://www.freertos.org/Documentation/02-Kernel/04-API-references/06-Queues/09-xQueueReceive；访问：2026-10-23；第一方：是。

  阅读位置/用途：目标缓冲大小、复制并移除队头、空队列零/有限等待、pdPASS/errQUEUE_EMPTY。

- **[S5] ST-STM32CUBEF4 — STM32CubeF4 official package and local fixed middleware**。版本：FW.F4.1.28.0 + patch FW.F4.1.28.3; packaged FreeRTOS V10.3.1; GCC ARM_CM4F; no target build。

  URL：https://www.st.com/en/embedded-software/stm32cubef4.sw-versions.html；访问：2026-10-23；第一方：是。

  阅读位置/用途：本机 package.xml；Source/include/queue.h:152/232/395/868，queue.c:310/740/1277/2074/2153，tasks.c:xTaskRemoveFromEventList/xTaskCheckForTimeOut/xTaskIncrementTick；include/projdefs.h:41/49/50；GCC/ARM_CM4F/port.c；HAL/RCC、LL RCC、CMSIS/SystemInit/启动文件。完整指纹在 source-audit.json，不复制厂商完整源码。

- **[S6] ST-RM0090 — STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 reference manual**。版本：Rev 22, May 2026。

  URL：https://www.st.com/resource/en/reference_manual/dm00031020.pdf；访问：2026-10-23；第一方：是。

  阅读位置/用途：PDF 页 217–231 的 RCC 章节：HSI/PLL、系统和总线分频、门控/复位、定时器时钟关系；Flash 等待与启动条件须配合具体器件。

- **[S7] ST-DS8626 — STM32F405xx / STM32F407xx datasheet**。版本：Rev 12, March 2026。

  URL：https://www.st.com/resource/en/datasheet/stm32f407vg.pdf；访问：2026-10-23；第一方：是。

  阅读位置/用途：封面与器件范围、内部 HSI 和运行条件；不从 URL 的 VG 名称假设实际封装或开发板。

- **[S8] ST-PM0214 — STM32 Cortex-M4 MCUs and MPUs programming manual**。版本：Rev 10, March 2020。

  URL：https://www.st.com/resource/en/programming_manual/dm00046982.pdf；访问：2026-10-23；第一方：是。

  阅读位置/用途：SysTick CTRL/LOAD/VAL、SCB ICSR/PendSV、异常优先级与异常处理；读取 COUNTFLAG 的副作用。

- **[S9] ST-UM1725 — Description of STM32F4 HAL and low-layer drivers**。版本：Rev 8, March 2023; exact HAL behavior checked in fixed package。

  URL：https://www.st.com/resource/en/user_manual/dm00105879.pdf；访问：2026-10-23；第一方：是。

  阅读位置/用途：HAL/LL 的层次和适用范围；具体 API 返回/内部时基调用按 S5 的固定源码核对。

- **[S10] ST-UM1718 — STM32CubeMX for STM32 configuration and initialization C code generation**。版本：Rev 51, May 2026; GUI not executed。

  URL：https://www.st.com.cn/resource/en/user_manual/dm00104712-stm32cubemx-for-stm32-configuration-and-initialization-c-code-generation-stmicroelectronics.pdf；访问：2026-10-23；第一方：是。

  阅读位置/用途：工具配置/生成流程与时钟配置章节；本次没有运行 GUI 或生成工程。

- **[S11] ST-ES0182 — STM32F405/407xx and STM32F415/417xx device errata**。版本：Rev 19, July 2026。

  URL：https://www.st.com/resource/en/errata_sheet/dm00037591.pdf；访问：2026-10-23；第一方：是。

  阅读位置/用途：2.1.3 异常返回/存储时序勘误和 DSB 注意事项；实际器件修订适用性仍须板卡核对。

- **[S12] ST-DS11532 — STM32F765xx / STM32F767xx / STM32F768Ax / STM32F769xx datasheet**。版本：Rev 9, July 2025; F767 core/cache scope only。

  URL：https://www.st.com/resource/en/datasheet/stm32f767zi.pdf；访问：2026-10-23；第一方：是。

  阅读位置/用途：封面与前 3 页 Cortex-M7、L1 缓存、样本范围；不据此推断具体 M7 端口或 DMA/RAM 映射。

- **[S13] ST-DS14258 — STM32H562xx and STM32H563xx datasheet**。版本：Rev 6, May 2025; H563 core/TrustZone scope only。

  URL：https://www.st.com/resource/en/datasheet/stm32h563zi.pdf；访问：2026-10-23；第一方：是。

  阅读位置/用途：封面与前 3 页 Cortex-M33/TrustZone、指令缓存/外部存储数据缓存边界；具体安全属性和端口待对应资料核对。

- **[S14] ST-DS12110 — STM32H742xI/G and STM32H743xI/G datasheet**。版本：Rev 11, January 2026; H743 core/cache scope only。

  URL：https://www.st.com/resource/en/datasheet/stm32h743zi.pdf；访问：2026-10-23；第一方：是。

  阅读位置/用途：封面与前 3 页 H743 Cortex-M7/L1 缓存范围；内存可达性和 DMA 一致性配置待对应参考手册核对。

- **[S15] ST-STM32CUBEMX — STM32CubeMX official software versions**。版本：Fixed GUI reference STM32CubeMX-Win 6.18.1 found in official cached page; GUI not run。

  URL：https://www.st.com/en/development-tools/stm32cubemx.sw-versions.html；访问：2026-10-23；第一方：是。

  阅读位置/用途：既有官方软件版本页中的 STM32CubeMX-Win 6.18.1；不是本机 GUI 运行或最新版本证据。
<!-- END SOURCES -->

+++
title = "UART 异步收发闭环：从帧状态机到软件缓冲"
date = "2026-10-05T17:52:01+08:00"
lastmod = "2026-10-05T17:52:01+08:00"
summary = "建立可迁移的 UART 异步串行收发模型：学习者能解释帧边界与接收状态机，区分外设事件、软件缓冲和应用消费，并用 Host Fake 验证正常流、分段到达、缓冲溢出、帧错误恢复和 TX 捕获；不把主机逻辑当作 STM32 硬件证据。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 22
tags = ["uart", "usart", "serial-frame", "rx-state-machine", "ring-buffer", "polling", "interrupt", "host-fake", "c11", "beginner"]
source_ids = ["st-rm0090", "st-an3109", "st-um1725"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L022"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 22 课：UART 异步收发闭环：从帧状态机到软件缓冲

UART（Universal Asynchronous Receiver/Transmitter，通用异步收发器）解决的是一个很具体的问题：两个没有共享时钟的设备，如何把字节可靠地变成串行电平，再在接收端恢复成字节。它同时也是嵌入式系统里最容易观察的一条数据路径：外设产生接收事件，软件把数据放入缓冲区，应用在合适的时机消费数据，发送方向再把应用数据编码成串行帧。

本课不假定开发板、调试器、USB-UART、示波器或逻辑分析仪存在。主线是一个 Host Fake（主机伪实现）：它用静态 C11（ISO C 2011 语言标准）状态机模拟一帧 UART 数据、接收缓冲和发送捕获。主机实验只能验证我们明确写下的逻辑规则，不能证明某个 STM32 型号的引脚、时钟、寄存器位或 HAL 行为。

本课只推进计划中的两个核心概念：

1. **UART 异步串行帧与收发状态机**：把起始位、数据位、可选校验位和停止位组织成有边界的传输单元，并明确接收状态如何从等待起始位走到完成或错误恢复。
2. **外设事件到软件缓冲再到应用消费的收发闭环**：把“收到一个字节”与“应用处理这个字节”分开，用缓冲区吸收两者的速度差，并沿发送方向回到可观察的输出帧。

本课核心目标（与 `plan.json` 一致）是：

> 规划一课以可迁移的 UART 异步串行收发闭环为主线：在不依赖具体开发板的前提下，学习者能解释帧边界、收发状态与软件缓冲之间的关系，并用 Host Fake 逻辑验证从字节输入到可观察输出的完整流程。

两个新核心概念的正式标签为：

- `UART 异步串行帧与收发状态机`
- `外设事件到软件缓冲再到应用消费的收发闭环`

波特率、USART（Universal Synchronous/Asynchronous Receiver/Transmitter，同步/异步收发器）与 UART 的名称差异、轮询、中断、环形缓冲区、帧错误、溢出，以及 HAL（Hardware Abstraction Layer，硬件抽象层）UART API（Application Programming Interface，应用程序编程接口）都是辅助术语；LL（Low-Layer，低层驱动）只在迁移边界中作为对照。它们帮助我们描述闭环，但不在本课中扩展为独立课程。DMA（Direct Memory Access，直接存储器访问）、RTOS（Real-Time Operating System，实时操作系统）、具体寄存器编程和复杂驱动架构留到后续主题。

## 1. 本节目标

完成本课后，你应能：

- 用自己的话说明异步串行为什么需要帧边界，以及状态机在正常、分段到达和错误情况下如何转移；
- 区分“外设已经产生接收事件”“字节已经进入软件缓冲”“应用已经消费字节”三个时刻；
- 阅读 Host Fake 中的对象定义、状态持有、注入点和消费点，解释数据从输入到输出的完整流动；
- 指出固定容量环形缓冲区满时的错误策略，并说明错误标志如何保留到应用观察；
- 在没有板卡时用可重复的输入序列验证正常接收、分段到达、缓冲溢出、帧错误和恢复；
- 迁移到 STM32F4、F7、H5 或 H7 时，知道哪些事实必须回到目标系列参考手册、数据手册、匹配版本 HAL/LL 文档和构建/调试证据中核对。

本课的成功标准是“能解释并验证模型”，不是“已经编译、下载或上板”。本课 `hardware_verified` 保持 `false`。

## 2. 它解决什么问题

### 2.1 没有共享时钟时，字节边界从哪里来

同步总线可以用共享时钟指出每一位什么时候采样；异步串行没有这根共享时钟，因此发送端和接收端必须预先约定位时间，并用一个不在空闲电平中的起始变化来标出一帧的开始。一个抽象帧可以画成：

```text
空闲电平 | 起始位 | 数据位 0 ... 数据位 n | 可选校验位 | 停止位 | 空闲电平
             <----------- 一帧 ------------>
```

接收端不能只问“总线上来了多少个电平”，它还要回答“我现在正在等待起始位、读取第几个数据位，还是等待停止位”。这就是本课第一个核心概念的边界。数据位数量、校验方式、停止位数量和具体采样实现由目标外设决定；本课只在 Host Fake 中使用一套显式规则，实际 STM32 选项必须查目标资料。[S1]

### 2.2 外设接收速度与应用处理速度不一致

即使每个字节都能被外设正确恢复，应用也可能暂时没有时间处理它。例如主循环正在做计算，或者一次调试输出阻塞了消费路径。如果接收事件直接调用应用逻辑，应用延迟会被硬塞进外设服务路径；如果完全不保存数据，后来的字节只能丢失。

软件缓冲区提供了一个有限的时间窗口：接收侧尽快写入，应用侧稍后读取。这个窗口不是无限队列。容量固定时，必须明确“满了之后丢新数据、覆盖旧数据、阻塞接收，还是只置错误标志”。本课选择**保留已有数据、拒绝新字节并置溢出标志**，因为这种策略容易在 Host Fake 中观察，也不会悄悄改变已经排队的数据。

### 2.3 先固定约束，再谈抽象

本课约束如下：

- 使用 C11 子集、固定宽度整数和静态数组；不使用动态内存；
- Host Fake 的“注入”以完整帧为单位，压缩掉真实位级采样时间；它验证状态和错误路径，不模拟电气波形；
- 接收缓冲区容量是 4，故意设置一个很小的边界，便于实验触发溢出；
- 接收错误不会把错误帧的数据写入缓冲区；错误计数和锁存标志保留到应用通过 `uart_print_status()` 或测试断言观察；
- 发送方向只捕获已经生成的帧，捕获结果不是 TX 引脚电平测量；
- 不假定 F4、F7、H5、H7 的 USART 实例、引脚复用、时钟树、IRQ 名称或 HAL 函数签名。

## 3. 必要前置知识

只把 `config/learning-state.toml` 的 `completed` 列表视为已学前置。与本课最相关的是：

1. **固定宽度整数**：`uint8_t`、`uint16_t`、`uint32_t` 的宽度是接口契约的一部分；不能用“主机上看起来一样”替代这个契约。
2. **数组和指针**：数组容量、索引和越界条件必须显式检查。环形缓冲区的 `head`、`tail` 和 `count` 都是有边界的状态。
3. **`const` 与 `volatile`**：本课 Host Fake 不需要把普通内存伪装成寄存器。真实硬件中，外设状态访问是否需要 `volatile`、由哪一层封装，必须按生成代码和编译器接口核对。
4. **轮询与中断的差异**：轮询是调用者主动读取；中断是外设事件形成请求后，由处理器在满足条件时进入服务路径。两者都不能跳过“事件状态由谁持有、谁负责清除”的问题。
5. **GPIO、EXTI 和中断优先级的边界**：GPIO 让状态可观察，EXTI 把变化形成请求，中断优先级决定多个请求竞争服务时的规则；本课只把 UART 接收事件接到“请求/消费”这条链上，不重新讲优先级编码。

不假定你已经知道某一型号的波特率计算公式、状态位清除顺序、RXNE/TC 等具体字段名称、HAL 回调签名或 CubeMX 生成文件布局。没有来源支持的具体断言均标为“待核对”。

## 4. 核心原理

### 4.1 核心机制一：UART 帧与收发状态机

**它解决什么问题？**

它把连续的串行电平切成有边界的传输单元，并让接收端在错误发生后有明确的恢复点。没有状态机，接收代码很容易把一个错误停止位后的电平误当成下一字节的第一位，造成后续数据全部错位。

**对象在哪里定义？**

Host Fake 中，`uart_rx_fsm_t` 定义接收状态、暂存数据和错误计数；`uart_wire_frame_t` 定义一帧输入的抽象字段。它们是教学模型，不是 STM32 寄存器映射。真实硬件的采样、移位寄存器和状态标志由 USART 外设持有，软件只能通过目标资料规定的访问路径观察。[S1]

**谁持有它？**

`uart_link_t` 持有一个接收状态机和一个接收环形缓冲区。接收状态机只由接收适配函数修改；应用不能直接改 `state`、`head` 或 `tail`。真实系统中，外设持有位级接收状态，软件驱动持有软件缓冲和错误统计。

**谁注入它？**

实验代码调用 `uart_host_inject_frame()` 注入一帧，模拟外部发送端和硬件接收路径已经把输入整理成字段。这个注入点让测试可以重复制造正常帧、坏停止位和坏校验位。真实系统的注入点应替换为目标 HAL/LL 或寄存器适配层；函数名、回调时机和清除顺序待核对。[S3]

**调用/事件如何流动？**

```text
Host Fake 输入帧
  -> 检查起始位
  -> READ_DATA 暂存数据并检查校验
  -> WAIT_STOP 检查停止位
  -> 正常：写入 RX ring；错误：置错误标志并回到 WAIT_START
```

状态机的关键不是枚举值本身，而是每个状态的责任：

| 状态 | 等待/检查什么 | 成功后的动作 | 失败后的动作 |
| --- | --- | --- | --- |
| `WAIT_START` | 起始位是否符合约定 | 暂存数据，进入 `READ_DATA` | 置帧错误，仍留在 `WAIT_START` |
| `READ_DATA` | 数据位和可选校验 | 进入 `WAIT_STOP` | 置校验错误，丢弃暂存字节，回到 `WAIT_START` |
| `WAIT_STOP` | 停止位是否符合约定 | 尝试写入 RX ring，回到 `WAIT_START` | 置帧错误，丢弃暂存字节，回到 `WAIT_START` |

真实外设可能以不同的硬件状态机和标志组合实现相同目标，不能从这个枚举推导寄存器位布局。

### 4.2 核心机制二：外设事件→软件缓冲→应用消费的闭环

**它解决什么问题？**

它把“外设必须快速响应”和“应用按自己的节奏处理”分开。缓冲区是两种速度之间的有限隔离层，发送捕获则让应用处理结果重新进入另一条帧路径。

**对象在哪里定义？**

`uart_ring_t` 定义固定容量、元素数组、读写位置和当前数量；`uart_status_t` 定义帧错误、校验错误和溢出等可观察状态；`uart_link_t` 把接收状态、缓冲、错误状态和 TX 捕获放在一个 Host Fake 对象中。真实工程通常由驱动对象持有环形缓冲，应用只通过读写接口访问。

**谁持有它？**

接收适配层持有并写入 RX ring；应用通过 `uart_app_read_byte()` 读取并推进 `tail`。这是一种单生产者、单消费者的教学模型。若真实工程由中断和主循环同时访问共享状态，还要按目标编译器、内存访问宽度和临界区策略核对并发安全性；本课不把“静态数组”误认为自动线程安全。

**谁注入它？**

`uart_host_inject_frame()` 模拟外设事件到达，成功解析后调用 `ring_push()`；`uart_app_write_byte()` 模拟应用把结果交给发送适配层，`uart_tx_encode()` 生成可观察的 TX 帧。真实系统的注入者是 USART 接收路径和应用调用者，HAL 回调或寄存器读取的具体边界待核对。[S3]

**调用/事件如何流动？**

```text
外部串行帧
  -> USART/Host Fake 接收状态机
  -> RX 事件与错误标志
  -> ring_push（满则 overflow）
  -> 应用 uart_app_read_byte
  -> 应用处理/决定回应
  -> uart_app_write_byte
  -> TX 帧捕获（真实系统再交给 TX 数据寄存器/发送路径）
```

必须区分三个时刻：

1. `frame accepted`：帧格式通过，字节已经从接收状态机进入缓冲区（若缓冲区有空间）；
2. `byte available`：缓冲区 `count > 0`，应用可以读取，但尚未消费；
3. `byte consumed`：应用成功读取并决定下一步处理。

轮询可以让应用主动检查 `count`；中断可以让外设事件形成待服务请求。两者都最终需要一个明确的缓冲所有权和错误观察点。标志位通常只能表示“至少有事件”，不自动变成无限事件队列；目标器件是否提供计数、FIFO 或额外状态，必须查手册。[S1][S2]

### 4.3 五个动作：声明、实现、实例化、组装、使用

本课不是完整架构课，但阅读代码时仍按五个动作分开：

1. **声明**：定义 `uart_wire_frame_t`、`uart_link_t`、状态码和函数原型，说明边界和返回值。
2. **实现**：实现奇偶校验、帧检查、环形缓冲读写、错误标志和 TX 编码。
3. **实例化**：`main` 中的 `static uart_link_t link` 分配一个 Host Fake 对象；它不是外设基地址。
4. **组装**：`uart_link_init()` 建立空状态，实验代码把输入帧、应用消费次数和输出捕获连接成场景。
5. **使用**：测试代码注入帧、读取错误、消费字节和检查 TX 捕获。

把五个动作写在同一个文件里是为了便于实验，不代表真实工程也必须如此组织。迁移到长期项目时，可把声明放到接口头文件、实现放到驱动模块、实例化放到 BSP（板级支持包）、组装放到启动代码、使用放到应用层；依赖方向应保持“应用依赖接口，BSP 提供实现”。

## 5. 关键术语与直观模型

| 术语 | 准确含义 | 本课观察点 |
| --- | --- | --- |
| USART/UART | USART 是更广义的同步/异步串行外设名称；UART 通常指异步工作方式。具体实例命名待按系列资料核对。 | 目标资料中的外设章节和实例表 |
| baud rate（波特率） | 约定串行符号速率。异步接收双方必须使用相容的位时间配置；本课不推导目标时钟公式。 | 迁移时核对时钟、分频和误差 |
| start bit（起始位） | 标记一帧开始的约定电平变化。 | `WAIT_START` |
| data bits（数据位） | 承载要传输的有效载荷。 | `data` 字段 |
| parity bit（校验位） | 可选的简单错误检测位。 | `parity_error` |
| stop bit（停止位） | 标记一帧结束并提供恢复空闲的边界。 | `WAIT_STOP` |
| TX/RX | transmit（发送）/receive（接收）方向。 | `uart_tx_encode` 与 `uart_host_inject_frame` |
| polling（轮询） | 调用者主动查询状态或缓冲。 | `uart_app_read_byte` 返回 0 |
| interrupt（中断） | 外设事件形成请求后进入服务路径。 | 本课只描述请求边界，不模拟异常入口 |
| ring buffer（环形缓冲区） | 固定数组配合读写位置形成的 FIFO（先进先出）结构。 | `head`、`tail`、`count` |
| frame error（帧错误） | 帧边界约定不满足，例如停止位不符合模型。具体标志名和清除顺序待核对。 | `frame_error` |
| overflow（溢出） | 新字节到达时缓冲区没有可用槽位。 | `overflow`，拒绝新字节 |
| Host Fake | 在主机上用可控代码替代硬件接口，只验证显式规则。 | 可重复的输入和断言 |

直观地想象两只盒子：左盒子是“外设接收盒”，只负责把合格帧交给右边的四格“软件邮箱”；应用是取信人，可能一次只取一格。邮箱满时，新的信件被拒收并留下“溢出”标签，旧信件不被覆盖。

## 6. 从输入到结果的完整流程

### 6.1 正常帧

Host Fake 使用 8 位数据、偶校验可选、一个停止位的抽象格式。这里的“8 位”和“一个停止位”只属于示例配置，不能当作所有 STM32 默认值。发送 `'A'` 的流程是：

```text
make_frame('A')
  -> start=0, data=0x41, parity=按约定计算, stop=1
  -> feed frame
  -> WAIT_START -> READ_DATA -> WAIT_STOP -> WAIT_START
  -> ring.count 从 0 变成 1
  -> app_read_byte 得到 0x41，ring.count 回到 0
```

### 6.2 分段到达

“分段”在本课里有两个层次：

- 位级分段由状态机顺序表达，但 Host Fake 把一次完整帧作为一个注入事件；
- 字节流分段由多次调用 `uart_host_inject_frame()` 表达，例如先注入 `'O'`，应用稍后消费，再注入 `'K'`。

因此实验可以验证“应用没有在每个接收事件后立即运行，数据仍然保留在 ring 中”。它不能验证真实 UART 的采样中心、过采样倍率或电平边沿，这些必须回到目标 USART 资料。[S1]

### 6.3 缓冲区满与溢出

容量为 4 时，连续注入 4 个合法帧会得到 `count=4`。第五个合法帧仍然可以通过帧检查，但 `ring_push()` 返回满，字节不进入队列、`overflow` 计数加一、`overflow_latched` 置位。应用消费一个字节后，下一次注入才有空间。

这个选择把“帧格式正确”和“软件容量足够”分成两个结果：一个帧可以格式正确，却因为软件来不及消费而丢失。真实外设若有硬件 FIFO、DMA 或不同的溢出语义，不能从本模型直接推导。[S2]

### 6.4 帧错误后的恢复

若停止位为 0，状态机置 `frame_error_latched`，丢弃暂存数据并回到 `WAIT_START`。下一次注入合法帧应再次从 `WAIT_START` 开始并成功进入 ring。错误标志不等于状态机永久卡死；恢复动作是“丢弃当前坏帧、回到可找下一帧边界的状态”。

目标系列可能同时报告多个错误，或要求按特定顺序读取状态和数据寄存器以清除标志。没有针对具体型号和 HAL 版本的来源时，只能把“检查错误、保存证据、按手册清除、继续接收”作为迁移步骤，不能写死清除代码。[S1][S3]

### 6.5 发送方向

应用读取一个字节后可以决定回显。Host Fake 的 `uart_app_write_byte()` 调用 `uart_tx_encode()`，把字节包装成 `uart_wire_frame_t` 并放入 TX 捕获数组。捕获数组只是“准备发送的帧”日志；真实系统还需要 TX 数据寄存器可写、发送完成状态和可能的中断/轮询路径，这些不是本课 Host Fake 已验证的内容。[S3]

## 7. 嵌入式系统中的对应位置

一个不绑定型号的责任链是：

```text
外部引脚电平
  -> USART 接收逻辑
  -> 状态/错误事件
  -> 驱动读取数据
  -> 软件 RX ring
  -> 应用消费
  -> 应用生成 TX 数据
  -> 驱动发送路径
  -> USART TX 逻辑
  -> 外部引脚电平
```

在真实工程中，每一层都有不同的证据：

| 层 | 谁持有状态 | 可以观察什么 | 不能凭空推出什么 |
| --- | --- | --- | --- |
| 引脚/电气 | 芯片引脚和外部连接 | 电平、边沿、波形 | 软件是否正确消费 |
| USART 外设 | 接收/发送移位逻辑、状态位、数据寄存器 | 寄存器窗口、调试事件、目标手册规定的状态 | 应用缓冲是否没有溢出 |
| 驱动 | 软件 ring、错误统计、服务入口 | 计数器、日志、断点 | 外部实际波特率和波形质量 |
| 应用 | 消费位置、协议状态、业务结果 | 返回值、协议日志 | 硬件标志已经按预期清除 |

### F4、F7、H5、H7 的迁移顺序

先迁移机制，再核对系列差异：

1. 固定具体 MCU、封装、板卡、调试器、Cube 固件和工具链版本；
2. 查目标系列 Reference Manual（参考手册）USART 章节，确认帧格式选项、状态/错误标志、接收和发送数据寄存器、请求形成条件；
3. 查 Datasheet（数据手册）确认引脚复用、电气限制和可用 USART 实例；
4. 查匹配版本的 HAL/LL 用户手册和生成工程，确认初始化、轮询、IT（中断）接口、回调和错误返回边界；
5. 用构建产物和调试器核对实际配置，再用串口终端、逻辑分析仪或示波器观察外部证据；
6. 把“资料结论”“Host Fake 结论”“构建证据”“测量证据”分开记录。

F4、F7、H5、H7 可能在 USART 实例、FIFO/缓冲组织、时钟域、复用矩阵、软件包版本和错误标志细节上不同。当前没有具体开发板和构建/测量记录，因此本课不选择某个实例、不写引脚号、不写时钟数值，也不声称 HAL API 已在目标上验证。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 能证明什么

- 给定本课定义的帧字段，合法帧会按固定状态顺序进入软件 ring；
- 坏停止位或坏校验位不会把暂存数据交给应用，并会留下可观察错误标志；
- ring 满时拒绝新字节而不覆盖已有数据，应用消费后容量恢复；
- 应用读取字节后，TX 捕获中出现对应的发送帧。

### 8.2 Host Fake 不能证明什么

- 不能证明目标 MCU 的波特率计算、时钟误差容限、采样点或电气电平；
- 不能证明某个 USART 实例的寄存器位、IRQ 名称、标志清除顺序或 HAL 回调签名；
- 不能证明中断延迟、DMA/FIFO 行为、缓存一致性、板上连线或外部串口设备兼容性。

### 8.3 通用 STM32 适配清单

把 Host Fake 的三个注入点替换为目标实现时，逐项留下证据：

```text
[ ] 目标 Reference Manual 版本和 USART 章节已记录
[ ] Datasheet 的实例、引脚复用和电气条件已记录
[ ] 时钟源、分频和波特率计算依据已记录
[ ] 帧格式、状态/错误标志和清除顺序已核对
[ ] 轮询/中断 HAL 或 LL API 与软件包版本匹配
[ ] RX 数据进入软件 ring 的所有权和临界区已说明
[ ] 构建日志、寄存器快照或测量记录与课程结论分开保存
```

若其中任何一项没有来源或证据，结论应写“待核对”，不要用 Host Fake 输出补齐。

## 9. 最小代码示例

下面代码可以复制到一个主机 C11 文件中作为实验起点。它故意把位级采样压缩为“注入一帧”，但保留状态机、缓冲所有权、错误标志和 TX 捕获的完整路径。代码是教学示例；本运行没有交叉编译、下载或上板证据。

### 9.1 声明：数据对象和接口

```c
#include <assert.h>
#include <stdint.h>
#include <stdio.h>

#define UART_RING_CAP 4u
#define UART_TX_LOG_CAP 8u

typedef enum {
    UART_OK = 0,
    UART_EMPTY = 1,
    UART_RING_FULL = 2,
    UART_FRAME_ERROR = 3,
    UART_PARITY_ERROR = 4,
    UART_BAD_ARGUMENT = 5
} uart_result_t;

typedef enum {
    UART_RX_WAIT_START = 0,
    UART_RX_READ_DATA = 1,
    UART_RX_WAIT_STOP = 2
} uart_rx_state_t;

typedef struct {
    uint8_t start_bit;
    uint8_t data;
    uint8_t parity_enabled;
    uint8_t parity_bit;
    uint8_t stop_bit;
} uart_wire_frame_t;

typedef struct {
    uint8_t data[UART_RING_CAP];
    uint8_t head;
    uint8_t tail;
    uint8_t count;
} uart_ring_t;

typedef struct {
    uart_rx_state_t state;
    uint8_t staging_byte;
    uint32_t frame_error_count;
    uint32_t parity_error_count;
    uint32_t overflow_count;
    uint8_t frame_error_latched;
    uint8_t parity_error_latched;
    uint8_t overflow_latched;
} uart_rx_fsm_t;

typedef struct {
    uart_rx_fsm_t rx;
    uart_ring_t rx_ring;
    uart_wire_frame_t tx_log[UART_TX_LOG_CAP];
    uint8_t tx_count;
} uart_link_t;

void uart_link_init(uart_link_t *link);
uart_wire_frame_t uart_make_frame(uint8_t data, uint8_t parity_enabled);
uart_result_t uart_host_inject_frame(uart_link_t *link,
                                     uart_wire_frame_t frame);
uint8_t uart_app_read_byte(uart_link_t *link, uint8_t *out);
uart_result_t uart_app_write_byte(uart_link_t *link, uint8_t data);
void uart_print_status(const uart_link_t *link);
```

这里的公开接口只使用固定宽度整数、指针和返回码。`uart_link_t` 是 Host Fake 的组合对象；真实工程可以把相同责任拆成驱动接口、BSP 实现和应用调用，但不要让应用直接写 ring 的内部字段。

### 9.2 实现：帧、状态机和环形缓冲

```c
static uint8_t uart_even_parity_bit(uint8_t data)
{
    uint8_t ones = 0u;
    uint8_t bit;

    for (bit = 0u; bit < 8u; ++bit) {
        ones = (uint8_t)(ones + (uint8_t)((data >> bit) & 1u));
    }
    return (uint8_t)(ones & 1u);
}

uart_wire_frame_t uart_make_frame(uint8_t data, uint8_t parity_enabled)
{
    uart_wire_frame_t frame;

    frame.start_bit = 0u;
    frame.data = data;
    frame.parity_enabled = parity_enabled;
    frame.parity_bit = uart_even_parity_bit(data);
    frame.stop_bit = 1u;
    return frame;
}

static uart_result_t uart_ring_push(uart_ring_t *ring, uint8_t data)
{
    if (ring == NULL) {
        return UART_BAD_ARGUMENT;
    }
    if (ring->count >= UART_RING_CAP) {
        return UART_RING_FULL;
    }
    ring->data[ring->head] = data;
    ring->head = (uint8_t)((ring->head + 1u) % UART_RING_CAP);
    ring->count = (uint8_t)(ring->count + 1u);
    return UART_OK;
}

static uart_result_t uart_ring_pop(uart_ring_t *ring, uint8_t *out)
{
    if ((ring == NULL) || (out == NULL)) {
        return UART_BAD_ARGUMENT;
    }
    if (ring->count == 0u) {
        return UART_EMPTY;
    }
    *out = ring->data[ring->tail];
    ring->tail = (uint8_t)((ring->tail + 1u) % UART_RING_CAP);
    ring->count = (uint8_t)(ring->count - 1u);
    return UART_OK;
}

void uart_link_init(uart_link_t *link)
{
    if (link == NULL) {
        return;
    }
    *link = (uart_link_t){0};
    link->rx.state = UART_RX_WAIT_START;
}

uart_result_t uart_host_inject_frame(uart_link_t *link,
                                     uart_wire_frame_t frame)
{
    uart_result_t result;

    if (link == NULL) {
        return UART_BAD_ARGUMENT;
    }

    link->rx.state = UART_RX_WAIT_START;
    if (frame.start_bit != 0u) {
        link->rx.frame_error_count++;
        link->rx.frame_error_latched = 1u;
        return UART_FRAME_ERROR;
    }

    link->rx.state = UART_RX_READ_DATA;
    link->rx.staging_byte = frame.data;
    if ((frame.parity_enabled != 0u) &&
        (frame.parity_bit != uart_even_parity_bit(frame.data))) {
        link->rx.parity_error_count++;
        link->rx.parity_error_latched = 1u;
        link->rx.state = UART_RX_WAIT_START;
        return UART_PARITY_ERROR;
    }

    link->rx.state = UART_RX_WAIT_STOP;
    if (frame.stop_bit != 1u) {
        link->rx.frame_error_count++;
        link->rx.frame_error_latched = 1u;
        link->rx.state = UART_RX_WAIT_START;
        return UART_FRAME_ERROR;
    }

    result = uart_ring_push(&link->rx_ring, link->rx.staging_byte);
    link->rx.state = UART_RX_WAIT_START;
    if (result == UART_RING_FULL) {
        link->rx.overflow_count++;
        link->rx.overflow_latched = 1u;
    }
    return result;
}

uint8_t uart_app_read_byte(uart_link_t *link, uint8_t *out)
{
    if ((link == NULL) || (out == NULL)) {
        return 0u;
    }
    if (uart_ring_pop(&link->rx_ring, out) != UART_OK) {
        return 0u;
    }
    return 1u;
}

uart_result_t uart_app_write_byte(uart_link_t *link, uint8_t data)
{
    if (link == NULL) {
        return UART_BAD_ARGUMENT;
    }
    if (link->tx_count >= UART_TX_LOG_CAP) {
        return UART_RING_FULL;
    }
    link->tx_log[link->tx_count] = uart_make_frame(data, 1u);
    link->tx_count = (uint8_t)(link->tx_count + 1u);
    return UART_OK;
}

void uart_print_status(const uart_link_t *link)
{
    if (link == NULL) {
        return;
    }
    printf("rx_count=%u frame_errors=%lu parity_errors=%lu "
           "overflows=%lu tx_count=%u\n",
           (unsigned)link->rx_ring.count,
           (unsigned long)link->rx.frame_error_count,
           (unsigned long)link->rx.parity_error_count,
           (unsigned long)link->rx.overflow_count,
           (unsigned)link->tx_count);
}
```

注意几个边界：

- `uart_host_inject_frame()` 在每次调用开始时回到 `WAIT_START`，因此坏帧不会把下一次实验输入留在半帧状态；
- `uart_ring_push()` 只在容量检查通过后推进 `head` 和 `count`；
- 溢出不是帧错误。前者说明软件容器没有空间，后者说明帧边界不符合模型；
- `uart_app_read_byte()` 是应用消费点；它不读取或清除硬件寄存器，只操作 Host Fake 的软件 ring；
- `uart_app_write_byte()` 的 TX 日志不是电平测量。

### 9.3 实例化、组装和使用

```c
int main(void)
{
    static uart_link_t link;
    uint8_t byte;
    uart_wire_frame_t frame;

    uart_link_init(&link);

    /* 正常帧：注入后数据在 ring 中，应用随后消费。 */
    frame = uart_make_frame((uint8_t)'A', 1u);
    assert(uart_host_inject_frame(&link, frame) == UART_OK);
    assert(link.rx_ring.count == 1u);
    assert(uart_app_read_byte(&link, &byte) == 1u);
    assert(byte == (uint8_t)'A');
    assert(uart_app_write_byte(&link, byte) == UART_OK);

    /* 错误帧：坏停止位被拒绝，之后的合法帧仍能恢复。 */
    frame = uart_make_frame((uint8_t)'!', 1u);
    frame.stop_bit = 0u;
    assert(uart_host_inject_frame(&link, frame) == UART_FRAME_ERROR);
    assert(link.rx_ring.count == 0u);
    frame = uart_make_frame((uint8_t)'B', 1u);
    assert(uart_host_inject_frame(&link, frame) == UART_OK);

    /* 应用暂不消费，连续四帧占满 ring，第五帧触发溢出。 */
    uart_link_init(&link);
    assert(uart_host_inject_frame(&link, uart_make_frame('1', 1u)) == UART_OK);
    assert(uart_host_inject_frame(&link, uart_make_frame('2', 1u)) == UART_OK);
    assert(uart_host_inject_frame(&link, uart_make_frame('3', 1u)) == UART_OK);
    assert(uart_host_inject_frame(&link, uart_make_frame('4', 1u)) == UART_OK);
    assert(uart_host_inject_frame(&link, uart_make_frame('5', 1u)) == UART_RING_FULL);
    assert(link.rx_ring.count == UART_RING_CAP);
    assert(link.rx.overflow_count == 1u);

    assert(uart_app_read_byte(&link, &byte) == 1u);
    assert(byte == (uint8_t)'1');
    assert(uart_host_inject_frame(&link, uart_make_frame('5', 1u)) == UART_OK);
    uart_print_status(&link);
    return 0;
}
```

这段 `main` 依次展示实例化、组装和使用：先建立 `link`，再注入正常帧和坏帧，最后在应用不及时消费时制造满队列。代码中的 `assert` 是逻辑断言，不是编译或上板证据。若你在主机执行，应把实际编译器、命令、输出和返回码单独记录；本课程仓库没有把生成课程自动标记为已编译。

## 10. 常见错误

### 10.1 把一帧当成一个“永远有效的字节”

接收路径必须保留边界和错误结果。只把 `data` 直接写入应用变量，会丢失“坏帧是否被接受”的证据。先检查帧，再决定是否进入 ring。

### 10.2 用 `head == tail` 同时表示空和满

如果只保存两个位置，某些环形缓冲实现需要保留一个空槽或额外的满标志。本课使用 `count`，并让 `0` 表示空、`UART_RING_CAP` 表示满。真实工程可以选择别的表示，但必须写出不变量和边界测试。

### 10.3 在中断服务路径里做完整协议解析

本课只把接收字节放入 ring；应用稍后消费。若把慢日志、复杂解析或阻塞发送放进中断路径，会扩大事件延迟和溢出风险。是否可以在特定目标使用 FIFO/DMA，需要另有来源和测量，不能由本课推断。

### 10.4 把错误标志清除当成“随便读一下就行”

状态寄存器、数据寄存器、清除寄存器之间的关系是型号相关的硬件契约。没有 RM0090 或目标系列等价资料的明确阅读位置时，只能写“待核对”。不要把某一 HAL 版本的经验推广到所有 F4/F7/H5/H7。

### 10.5 把 `printf` 输出当成串口测量

Host Fake 的 `printf` 只说明主机程序观察到了模型状态。它不说明 TX 引脚电平、波特率误差、线缆连接或另一端设备已经收到数据。

## 11. 调试观察点

按数据路径设置观察点，而不是只在 `main` 末尾看一个结果：

1. **帧入口**：记录 `start_bit`、`data`、`parity_bit`、`stop_bit`，确认输入是否符合实验场景。
2. **状态转移**：观察 `WAIT_START -> READ_DATA -> WAIT_STOP -> WAIT_START`；坏帧应在错误点回到 `WAIT_START`。
3. **ring 不变量**：每次 push 后检查 `0 <= count <= UART_RING_CAP`，`head`/`tail` 始终落在数组范围内。
4. **错误计数**：分开观察 `frame_error_count`、`parity_error_count` 和 `overflow_count`，不要用一个“接收失败”计数掩盖原因。
5. **消费延迟**：注入四帧后暂不调用 `uart_app_read_byte()`，观察 `count` 增长到容量；注入第五帧后确认已有四个字节未被覆盖。
6. **恢复路径**：坏停止位后立即注入合法帧，确认合法帧可以进入 ring；若不能，先检查状态机回到等待起始位的路径。
7. **发送边界**：观察 `tx_log[0].data` 和 `tx_log[0].stop_bit`，确认应用回显的是消费到的字节，而不是仍在输入暂存区的旧值。

迁移到硬件时，把同样的观察点映射到寄存器窗口、HAL 返回值、断点、GPIO 时间戳或逻辑分析仪。每个观察点都要注明证据类型：资料、构建、调试或测量。

## 12. 实战实验

### 实验 A：正常字节流和分段消费

**输入**：依次注入 `'O'`、`'K'`，在两次注入之间只消费一次。

**预期观察**：第一次消费得到 `'O'`；第二个字节在 ring 中等待，随后消费得到 `'K'`；`frame_error_count`、`parity_error_count` 和 `overflow_count` 均为 0。

**记录**：写出每次调用后的 `count/head/tail`，并说明哪个函数拥有写入权、哪个函数拥有读取权。

### 实验 B：应用不及时消费

**输入**：连续注入 `'1'`、`'2'`、`'3'`、`'4'`、`'5'`，期间不读取 ring。

**预期观察**：前四帧进入 ring，第五帧返回 `UART_RING_FULL`；`overflow_count` 增加 1；先消费时仍按 `'1'`、`'2'`、`'3'`、`'4'` 顺序读到，说明本课策略没有覆盖旧数据。

**变化题**：把策略改成“覆盖最旧数据”，需要修改哪个不变量？要增加哪些断言，才能证明覆盖发生而不是越界？

### 实验 C：帧错误后的恢复

**输入**：先注入停止位为 0 的坏帧，再注入合法 `'R'`。

**预期观察**：坏帧返回 `UART_FRAME_ERROR` 且不进入 ring；合法 `'R'` 成功进入 ring；错误计数保留，状态机回到 `UART_RX_WAIT_START`。

**调试要求**：在错误返回点和下一次成功 push 点各记录一次状态快照，解释恢复不是“清零所有状态”，而是丢弃当前坏帧并重新寻找边界。

### 实验 D：回显 TX 帧

**输入**：注入 `'A'`，应用读取后调用 `uart_app_write_byte()`。

**预期观察**：`tx_log[0].data == 'A'`，`start_bit == 0`，`stop_bit == 1`；这只能证明 Host Fake 的编码函数被调用。

**边界声明**：不要把这个结果写成“STM32 TX 引脚已输出 8N1 波形”。要得到后者，必须有目标配置、构建记录和外部测量证据。

## 13. 自检题

1. 为什么异步串行需要起始位和停止位？如果只有数据位，接收端会缺少什么信息？
2. `frame accepted`、`byte available` 和 `byte consumed` 分别发生在调用流的哪三个位置？
3. 为什么一个合法帧仍可能导致 `UART_RING_FULL`？这两个结果分别属于哪个对象？
4. 本课为什么把坏停止位后的状态设为 `WAIT_START`，而不是继续尝试解释当前帧？
5. 如果 `count` 已经等于容量，`head` 是否可以先推进再判断？请从数组边界和数据完整性说明原因。
6. 轮询和中断都需要谁负责清除/消费？为什么“用了中断”不等于“应用已经处理数据”？
7. Host Fake 的 `tx_log` 能证明哪些逻辑，不能证明哪些硬件事实？

参考答案应至少包含：帧边界、状态机恢复、固定容量不变量、事件与消费的时间差，以及证据边界五个关键词。

## 14. 面试题

1. 设计一个无动态内存的 UART RX ring。你会选择 `head/tail/count` 还是保留一个空槽？请说出空、满、push、pop 的不变量。
2. 如果接收中断每 100 微秒到一次，而应用最坏每 150 微秒消费一个字节，容量为 4 的 ring 能吸收多长时间的持续差速？你的计算依赖哪些假设？
3. 帧错误和溢出错误有什么不同？为什么把它们合并成一个错误码会降低调试价值？
4. 你如何把 Host Fake 的 `uart_host_inject_frame()` 替换成一个具体 STM32 HAL/LL 适配层，同时保持应用不改？请区分声明、实现、实例化、组装、使用。
5. 状态寄存器和数据寄存器的读取顺序为什么不能凭经验猜？你会查哪些第一方资料和哪些运行证据？
6. 当应用处理很慢时，除了增大 ring，还能从哪三个方向降低丢包风险？回答中要区分协议、驱动和硬件层。

## 15. 延伸思考

- 如果把 ring 的元素从单字节改成“字节 + 时间戳 + 错误快照”，哪些结构和所有权会变化？
- 如果协议有明确的消息长度或分隔符，帧状态机与应用协议解析器应如何分层，才能不把“串口帧边界”误认为“业务消息边界”？
- 在有硬件 FIFO 或 DMA 的目标上，哪个状态仍然属于外设，哪个状态转移到软件？如何为每一次转移定义可观察证据？
- 如果要支持半双工、RS-485 或低功耗唤醒，收发闭环的哪一段会增加方向控制或唤醒状态？这些变化需要哪些新来源，为什么不应在本课凭空展开？
- 当 F4、F7、H5、H7 的软件包 API 看起来相似时，怎样避免“能编译”被误当成“标志清除语义相同”？

## 16. 本节总结

UART 的第一性问题是：没有共享时钟时，接收端如何找到字节边界并判断这一帧是否有效。帧状态机用起始位、数据位、可选校验位和停止位组织边界；错误路径必须回到可恢复的等待状态。

系统级问题是：外设事件和应用消费速度不一致。软件 ring 把两者解耦，但容量有限，满时的策略必须显式定义。Host Fake 展示了“外部帧→状态机→RX ring→应用读取→TX 帧捕获”的闭环，也把帧错误、校验错误和溢出分成可观察结果。

代码中的结构体、计数器和状态枚举只属于模型。STM32 的实例、时钟、引脚、寄存器、HAL/LL API、清除顺序和中断入口必须回到目标系列第一方资料与构建/调试/测量记录中核对。本课没有具体板卡，`hardware_verified=false`。

## 17. 下一步

下一课仍应沿本阶段顺序推进到计划允许的相邻机制。对本课的个人复习建议是：先独立画出“事件→ring→消费”的所有权图，再在主机上完成四个实验，最后选择一个具体 STM32 目标补齐 USART 章节、Datasheet 和匹配 HAL 版本的证据。只有用户答案、实验结果或复习记录才能提高掌握度；课程生成本身不会修改学习状态。

## 18. 参考资料

正文用 `[S1]`、`[S2]`、`[S3]` 标出需要回到第一方资料核对的结论。来源元数据也写入同目录 `lesson.json`。

### [S1] STMicroelectronics RM0090

*RM0090 STM32F405/415/427/437/529/537/539/543/547/549 advanced Arm-based 32-bit MCUs reference manual*，Rev 19（本运行按计划记录；具体目标器件和实际页面版本仍需核对），USART 章节及状态/中断寄存器描述。用于核对帧配置、状态事件和寄存器语义，不把 Host Fake 字段当作寄存器布局。

### [S2] STMicroelectronics AN3109

*Communication peripheral FIFO emulation with DMA*，Rev 2（本运行按计划记录）。用于理解数据流与缓冲关系的官方背景；DMA 不是本课核心，正文不把该应用笔记推广成当前目标器件的 DMA 配置结论。

### [S3] STMicroelectronics UM1725

*Description of STM32F4 HAL and low-layer drivers*，Rev 9（本运行按计划记录；具体软件包版本仍需核对），UART HAL API 与回调/错误语义相关章节。用于核对 HAL 调用边界，不把函数名外推到 F7、H5 或 H7。

### 来源边界

以上 URL 都来自 `config/source-policy.toml` 允许的 `st.com` 域，且均为第一方来源。若目标系列、软件包版本或访问页面的 revision 与记录不同，应在迁移笔记中更新版本并重新核对，不得用未验证的记忆替代来源。

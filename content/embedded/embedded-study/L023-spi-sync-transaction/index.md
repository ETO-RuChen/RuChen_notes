+++
title = "SPI 同步事务闭环：全双工交换与片选边界"
date = "2026-10-05T21:57:44+08:00"
lastmod = "2026-10-05T21:57:44+08:00"
summary = "建立可迁移的 SPI 同步事务模型：解释时钟驱动的全双工字节交换与片选定义的事务边界和设备选择，并用 Host Fake 验证发送、接收、片选和完成状态的完整流动；不把主机逻辑当作 STM32 硬件证据。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 23
tags = ["spi", "synchronous-serial", "full-duplex", "chip-select", "transaction", "host-fake", "c11", "beginner"]
source_ids = ["st-rm0090", "st-um1725"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L023"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 23 课：SPI 同步事务闭环：全双工交换与片选边界

SPI（Serial Peripheral Interface，串行外设接口）解决的是一个与 UART 不同的问题：当两个设备需要共享明确的位级时序时，谁提供时钟、每一位何时移动、一次设备访问从哪里开始又在哪里结束。本课不把 SPI 当成一组 HAL（Hardware Abstraction Layer，硬件抽象层）函数名，而是先建立一个可以迁移到不同 STM32 系列的同步事务模型。

本课不假定开发板、调试器、传感器、示波器或逻辑分析仪存在。主线是一个 Host Fake（主机伪实现）：测试代码注入模拟的输入字节和片选事件，适配层按一个字节一次的时钟步进完成交换，并记录发送序列、接收序列、片选状态和事务完成状态。主机逻辑验证只能证明我们写下的状态流动，不能证明某个 STM32 型号的引脚、时钟、寄存器位、电平或 HAL 行为。

本课只推进计划中的两个核心概念：

1. **时钟驱动的全双工移位交换**：SPI 用时钟边沿推动发送端与接收端同步移位；一次交换同时产生发送和接收结果。
2. **片选定义的事务边界与设备选择**：片选（CS/NSS）把若干字节组织成一次设备事务，并在多设备总线上选择目标从设备。

CPOL（Clock Polarity，时钟极性）、CPHA（Clock Phase，时钟相位）、时钟分频、轮询、中断、DMA（Direct Memory Access，直接存储器访问）、HAL、LL（Low-Layer，低层驱动）和 F4/F7/H5/H7 的外设差异都是辅助术语。本课用它们描述核对边界，不把它们扩展成第三个核心概念。

## 1. 本节目标

完成本课后，你应能：

- 用自己的话解释为什么 SPI 需要一根由主设备驱动的 SCK（Serial Clock，串行时钟），以及“发送一个字节同时接收一个字节”的含义；
- 区分 MOSI（Master Out, Slave In，主出从入）、MISO（Master In, Slave Out，主入从出）、SCK 和 CS/NSS 的角色；
- 解释片选拉低、连续传输、片选拉高如何构成一个事务，并说明片选如何选择多个从设备中的一个；
- 读出 Host Fake 中对象的定义、持有者、注入点和调用流：应用请求怎样进入适配层，时钟步进怎样产生接收字节，结果怎样回到应用；
- 用固定数组验证单字节交换、多字节事务、片选中途释放、两个设备片选互斥、缓冲边界和错误恢复；
- 迁移到 STM32F4、F7、H5 或 H7 时，知道哪些寄存器、HAL/LL API、FIFO 或片选语义必须回到目标系列第一方文档核对。

成功标准是“能解释并验证模型”，不是“已经编译、下载或上板”。本课 `hardware_verified` 保持 `false`。

## 2. 它解决什么问题

### 2.1 UART 的字节流为什么还不够

UART 是异步串行链路：发送端和接收端预先约定速率，各自用本地时钟恢复帧。SPI 则把时钟线带到总线上，由主设备明确指出每一个移位时刻。这样做适合寄存器设备、显示控制器、存储器等需要“命令、地址、数据必须按同一节拍排列”的场景。

如果只把 SPI 想成“更快的 UART”，会漏掉两个边界：

- SPI 的每个时钟周期都同时推动输出位和输入位，发送路径与接收路径不能被概念上拆成两个互不相关的字节流；
- 一个设备通常要把多个字节看成一个命令或读写操作，设备需要知道这组字节何时开始、何时结束。

因此本课先回答两件事：时钟怎样驱动一次交换，片选怎样包住一组交换。

### 2.2 约束先于抽象

本课的约束如下：

- 使用 C11（ISO C 2011 语言标准）子集、固定宽度整数和静态数组；不使用动态内存；
- Host Fake 把一个“字节交换”作为一个可观察步进，省略真实的 8 个电气边沿；它验证数据和状态的逻辑，不模拟波形、电压或建立保持时间；
- 应用不能在未开始事务时发送，也不能在一次事务中间偷偷改变目标设备；
- 片选状态和事务完成状态都必须被保存，便于测试在调用返回后观察；
- 不假定任何具体 SPI 实例、引脚复用、时钟树、频率、FIFO 深度、IRQ 名称或 HAL 函数签名。

### 2.4 先看最小 Host Fake 闭环

先暂时不背寄存器名，只看一次可观察的主机逻辑：

```text
注入从设备响应 [A5, 5A]
        |
spi_begin(设备 0)       -> CS_0 变低，CS_1 保持高
spi_transfer([9F, 00])  -> TX 记录 [9F, 00]，RX 得到 [A5, 5A]
spi_end()               -> CS_0 变高，completed=true
```

最小闭环的结果可以直接比较：TX 和 RX 各有两个字节，抽象时钟步进为 2，两个片选最终都为高。后面的核心原理只是回答“为什么一次传输必须有一进一出”和“为什么这些字节必须被片选包在同一事务内”。

## 3. 必要前置知识

只把 `config/learning-state.toml` 的 `completed` 列表视为已学前置。与本课最相关的是：

1. **固定宽度整数**：`uint8_t`、`uint16_t`、`uint32_t` 的宽度是接口契约的一部分；总线上的一个字节应使用 `uint8_t` 表达。
2. **数组和指针**：缓冲区容量、索引和越界条件必须显式检查；本课的接收数组不会自动扩容。
3. **`const` 与 `volatile`**：Host Fake 的数组是普通内存。真实硬件中的寄存器访问是否需要 `volatile`，由目标 SDK、生成代码和编译器接口共同决定，不能从本课代码直接推断。
4. **轮询与中断的差异**：轮询是调用者主动推进交换；中断是外设事件形成请求后进入服务路径。本课先用轮询式 Host Fake 固定数据流，中断和 DMA 只作为替换时需要重新核对的服务方式。
5. **GPIO、EXTI 和 UART 缓冲**：GPIO 提供电平输出，EXTI 可把边沿形成请求，UART 已经展示过发送/接收缓冲的基本思想；本课把这些知识收束到 SPI 的时钟、数据线和片选角色中。

没有完成的具体前置包括：某型号寄存器位、SPI 实例编号、引脚复用、时钟树、HAL/LL 版本、DMA 配置和外设电气时序。没有第一方证据的内容在迁移段落中均标为“待核对”。

## 4. 核心原理

### 4.1 核心机制一：时钟驱动的全双工移位交换

#### 它解决什么问题

异步字节流无法告诉接收端“这一位现在应该采样”，也不能自然表达一个设备访问中命令与响应的对应关系。SPI 由主设备输出 SCK，双方按照约定的时钟极性和相位，在时钟边沿移动或采样一位。经过固定数量的边沿后，发送移位寄存器推出一个字节，同时接收移位寄存器收进一个字节。

“全双工”不是“发送和接收各自拥有独立时钟”，而是**同一组时钟边沿同时服务两条数据方向**。即使应用只想读，也通常要由主设备发送占位字节来产生时钟；占位字节的具体值由目标设备协议决定，不能在没有资料时猜测。

#### 对象在哪里定义、谁持有、谁注入

- **交换对象**：Host Fake 中是 `SpiHostFake` 的 `tx_log`、`rx_queue`、`rx_log` 和 `clock_steps`；真实适配层中对应发送/接收数据寄存器、状态和软件缓冲。
- **持有者**：适配对象持有当前事务状态和已捕获数据；应用只持有自己要发送的输入数组和接收数组，不直接持有外设状态。
- **注入者**：测试代码注入从设备返回的 `rx_queue`，并调用 `spi_fake_exchange()` 推进时钟步进。真实系统中，主设备外设产生 SCK，外部从设备在数据线上提供 MISO 位。
- **调用流**：应用调用 `spi_transfer()` → 适配层检查事务和缓冲边界 → 每个字节执行一次交换 → 适配层记录 TX/RX → 应用读取接收数组和完成状态。

可以把一个字节的抽象过程画成：

```text
主设备 tx[0] --按 SCK 边沿移位--> MOSI 线
主设备 rx[0] <--按同一组边沿采样-- MISO 线
                  8 个边沿后
               rx[0] 成为完整字节
```

Host Fake 将 8 个边沿压缩成一次调用，但仍保留“一个 TX 字节对应一个 RX 字节”的不变量。如果输入和输出计数不相等，就不是这个抽象模型的合法结果。

#### CPOL 与 CPHA 只是什么

CPOL 描述 SCK 空闲时的电平，CPHA 描述在一个周期的哪一类边沿采样或改变数据。它们共同构成常说的 SPI mode 0 到 mode 3。这里的作用是说明“双方必须采用同一采样约定”，不是要背模式编号。具体边沿、寄存器位名称和默认值必须按目标系列参考手册核对。[S1]

### 4.2 核心机制二：片选定义的事务边界与设备选择

#### 它解决什么问题

从设备不能只看见“总线上来了几个字节”，还要知道这些字节是否属于同一次命令。CS/NSS 拉低可以表示事务开始，连续的时钟和数据构成事务内容，CS/NSS 拉高表示事务结束。多个从设备共享 SCK、MOSI 和 MISO 时，主设备通常为每个设备提供独立片选；一次只允许目标设备驱动 MISO，其他设备保持不参与状态。

片选边界因此解决两个问题：

1. 设备如何把命令、地址、数据归为一组；
2. 主设备如何在共享总线上选择当前目标。

#### 对象在哪里定义、谁持有、谁注入

- **片选对象**：Host Fake 用 `selected_device` 和 `cs_level[DEVICE_COUNT]` 表示目标与电平；真实系统中可能由 GPIO、硬件 NSS 管理或外部片选逻辑承担。
- **持有者**：组装层持有每个设备的片选配置；SPI 适配层只接收“选择设备/释放设备”的操作，不自行猜测某个 GPIO 编号。
- **注入者**：应用或更高层设备驱动请求 `spi_begin(device)`、`spi_transfer(...)`、`spi_end()`；Host Fake 立即记录片选变化。硬件适配层把这三个动作映射到 HAL/LL 或寄存器流程，具体接口待核对。
- **调用流**：应用设备驱动选择目标 → 片选拉低 → 发送命令/地址/数据并接收响应 → 片选拉高 → 事务完成；任何中途错误都必须先结束或恢复片选状态，再允许下一次事务。

事务边界不是“调用函数的边界”这么简单。若调用者把 3 个字节拆成两次传输，而适配层在两次调用之间自动拉高片选，目标设备可能把第二次调用当作新命令。是否允许跨调用保持片选，取决于接口契约；本课的最小接口规定一次 `spi_transfer()` 完成一整个事务，避免隐藏的跨调用状态。

## 5. 关键术语与直观模型

| 术语 | 直观含义 | 本课中的观察点 |
| --- | --- | --- |
| SPI | 有共享时钟的同步串行接口 | `spi_transfer()` 的一进一出 |
| SCK | 主设备提供的节拍 | `clock_steps` 每次增加 1 |
| MOSI | 主设备送给从设备的数据线 | `tx_log` |
| MISO | 从设备送回主设备的数据线 | `rx_queue` 被消费并进入 `rx_log` |
| CS/NSS | 选择设备并包住事务的控制线 | `cs_level[]` 和 `selected_device` |
| 主设备 | 负责产生 SCK、发起事务的一方 | Host Fake 的适配对象 |
| 从设备 | 响应时钟、返回 MISO 数据的一方 | 测试注入的 `rx_queue` |
| 全双工 | 一次时钟步进同时移动两个方向 | TX 与 RX 数量相等 |
| 事务 | 从片选开始到片选结束的一组交换 | `active` 到 `completed` |
| Host Fake | 在主机上替代真实外设的逻辑实现 | 可比较的数组和状态 |

“移位寄存器”是硬件实现术语：它把待发送位逐位推出，也把采样位逐位收入。本课不假定目标芯片寄存器的字段布局；只把它抽象为“每个时钟步进都会更新发送和接收侧”。

## 6. 从输入到结果的完整流程

一次两字节事务的状态流动如下：

```text
应用 tx = [命令, 参数]
        |
        v
spi_begin(设备 A)
        |  CS_A: 高 -> 低；CS_B 保持高
        v
spi_transfer(tx, rx, 2)
        |  第 1 次时钟：记录命令，注入并取得响应 0
        |  第 2 次时钟：记录参数，注入并取得响应 1
        v
spi_end()
        |  CS_A: 低 -> 高；active=false; completed=true
        v
应用读取 rx = [响应 0, 响应 1] 和状态
```

每一步都有可观察结果：

1. `spi_begin()` 后只能有一个片选为低；否则设备选择不明确。
2. `spi_transfer()` 返回 `SPI_OK` 时，`tx_log_count == rx_log_count == length`，并且 `clock_steps == length`。
3. `spi_end()` 后 `active == false` 且目标片选回到高电平。
4. 可恢复的传输错误不能遗留低片选和“仍在事务中”的状态；忙状态错误则保留当前事务，调用者必须先结束或取消它。恢复动作必须可被下一次事务观察。

## 7. 嵌入式系统中的对应位置

### 7.1 五个动作必须分开

本课用一个小型 Device Framework（设备框架）示例区分五个动作，但不把框架本身变成新的学习目标：

1. **声明**：在头文件中声明 `SpiBus`、`spi_begin`、`spi_transfer` 和 `spi_end` 的接口。声明只描述调用契约，不分配硬件资源。
2. **实现**：在适配层实现这些函数。Host Fake 的实现使用静态数组；真实 STM32 实现需要访问目标系列的 SPI 外设和片选 GPIO，细节待核对。
3. **实例化**：在一个 `.c` 文件中定义一个 `SpiHostFake` 对象或一个具体硬件适配对象。实例化决定谁持有状态和缓冲。
4. **组装**：BSP（Board Support Package，板级支持包）或应用组装处把设备 A/B 的片选控制注入总线对象，把总线对象交给设备驱动。
5. **使用**：应用只调用设备驱动或总线接口，传入自己的 TX/RX 数组；它不直接改 `cs_level[]`，也不直接写外设寄存器。

依赖方向应保持为：

```text
App 使用 -> 设备驱动 -> SPI 公共声明 -> Host Fake/STM32 适配实现
                                         ^
                                         |
                               BSP 组装片选与实例
```

### 7.2 迁移到 STM32 的边界

通用迁移步骤是：

1. 从目标系列参考手册确认 SPI 实例、时钟源、主从模式、数据宽度、CPOL/CPHA、状态/错误语义和数据寄存器访问规则；
2. 从目标芯片数据手册确认候选引脚的复用功能、电气限制和片选连接；
3. 若使用 HAL/LL，锁定具体 STM32Cube 包版本，核对阻塞、轮询、中断和 DMA API 的参数、返回值、忙闲状态和回调边界；
4. 让适配层保留本课的接口不变量：一进一出、事务边界显式、错误可恢复；
5. 用逻辑分析仪或目标调试器验证真实 SCK/MOSI/MISO/CS 波形，再把证据记录到运行目录。

RM0090 用于核对 F4 的 SPI/I2S 功能描述、控制/状态/数据寄存器和通信流程；UM1725 用于核对 STM32CubeF4 的 SPI HAL/LL 驱动接口与阻塞/中断边界。[S1][S2] 这两份资料不能自动证明 F7、H5 或 H7 的同名 API、FIFO、片选管理或状态位完全相同。没有本课目标系列对应的第一方手册时，F7/H5/H7 的差异一律写作“待核对”，不得把 F4 细节外推。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证什么

Host Fake 能验证：

- 每个 TX 字节恰好消耗一个注入的 RX 字节；
- 片选开始、传输和结束的顺序；
- 多设备片选互斥；
- 长度为 0、达到容量和超过容量时的边界行为；
- 错误后片选释放、状态复位和下一次事务恢复。

Host Fake 不能验证：

- 实际 SCK 边沿、CPOL/CPHA 的电气时序和信号完整性；
- 某型号寄存器位、FIFO 深度、状态位清除顺序；
- HAL/LL 版本之间的阻塞、中断、DMA 语义；
- 目标设备对命令字节、占位字节和片选最小高电平时间的协议要求。

### 8.2 通用迁移记录格式

迁移时至少记录：目标系列和具体芯片、SPI 实例、SCK/MOSI/MISO/CS 引脚复用、主从模式、CPOL/CPHA、数据宽度、分频、API/寄存器来源、构建日志、波形或寄存器观察证据。缺少具体板卡和证据时，课程状态保持 `hardware_verified=false`。

## 9. 最小代码示例

下面的完整示例可保存为 `spi_host_fake.c` 后在普通 Windows 主机上用任意 C11 编译器尝试构建；本仓库没有为本次课程生成或运行构建记录，所以这里必须视为“示例，待主机执行验证”。代码故意把声明、实现、实例化、组装和使用标在不同区域。

### 9.1 声明：公共接口和状态

```c
#include <stdint.h>
#include <stddef.h>

#define SPI_MAX_BYTES 8u
#define SPI_DEVICE_COUNT 2u

typedef enum {
    SPI_OK = 0,
    SPI_ERR_ACTIVE = 1,
    SPI_ERR_NOT_ACTIVE = 2,
    SPI_ERR_LENGTH = 3,
    SPI_ERR_DEVICE = 4,
    SPI_ERR_CS = 5
} SpiStatus;

typedef struct {
    uint8_t tx_log[SPI_MAX_BYTES];
    uint8_t rx_queue[SPI_MAX_BYTES];
    uint8_t rx_log[SPI_MAX_BYTES];
    uint8_t tx_log_count;
    uint8_t rx_queue_count;
    uint8_t rx_queue_index;
    uint8_t rx_log_count;
    uint8_t cs_level[SPI_DEVICE_COUNT]; /* 1 = high/inactive, 0 = low/selected */
    uint8_t selected_device;
    uint8_t active;
    uint8_t completed;
    uint8_t error;
    uint32_t clock_steps;
} SpiHostFake;

static SpiStatus spi_begin(SpiHostFake *bus, uint8_t device);
static SpiStatus spi_transfer(SpiHostFake *bus,
                              const uint8_t *tx,
                              uint8_t *rx,
                              uint8_t length);
static SpiStatus spi_end(SpiHostFake *bus);
```

这里的公共接口只公开固定宽度整数和数组指针。`SpiHostFake` 是示例中的状态对象；实际项目可以把它隐藏在适配层，只暴露不透明句柄，但本课为了让初学者看见“谁持有状态”而直接展示结构体。

### 9.2 实现：片选与全双工交换

```c
static void spi_set_all_cs_high(SpiHostFake *bus)
{
    uint8_t i;
    for (i = 0u; i < SPI_DEVICE_COUNT; ++i) {
        bus->cs_level[i] = 1u;
    }
}

static void spi_abort(SpiHostFake *bus)
{
    spi_set_all_cs_high(bus);
    bus->active = 0u;
    bus->completed = 0u;
}

static SpiStatus spi_begin(SpiHostFake *bus, uint8_t device)
{
    if (bus == NULL || device >= SPI_DEVICE_COUNT) {
        return SPI_ERR_DEVICE;
    }
    if (bus->active != 0u) {
        bus->error = (uint8_t)SPI_ERR_ACTIVE;
        return SPI_ERR_ACTIVE;
    }
    spi_set_all_cs_high(bus);
    bus->selected_device = device;
    bus->cs_level[device] = 0u;
    bus->active = 1u;
    bus->completed = 0u;
    bus->error = (uint8_t)SPI_OK;
    return SPI_OK;
}

static SpiStatus spi_transfer(SpiHostFake *bus,
                              const uint8_t *tx,
                              uint8_t *rx,
                              uint8_t length)
{
    uint8_t i;
    if (bus == NULL) {
        return SPI_ERR_LENGTH;
    }
    if (bus->active == 0u) {
        bus->error = (uint8_t)SPI_ERR_NOT_ACTIVE;
        return SPI_ERR_NOT_ACTIVE;
    }
    if (tx == NULL || rx == NULL || length == 0u ||
        length > SPI_MAX_BYTES ||
        (uint16_t)bus->rx_queue_index + (uint16_t)length >
            (uint16_t)bus->rx_queue_count) {
        bus->error = (uint8_t)SPI_ERR_LENGTH;
        spi_abort(bus);
        return SPI_ERR_LENGTH;
    }
    for (i = 0u; i < length; ++i) {
        /* One abstract byte step represents eight real SCK edges. */
        bus->tx_log[i] = tx[i];
        bus->rx_log[i] = bus->rx_queue[bus->rx_queue_index];
        rx[i] = bus->rx_log[i];
        bus->rx_queue_index++;
        bus->tx_log_count++;
        bus->rx_log_count++;
        bus->clock_steps += 1u;
    }
    return SPI_OK;
}

static SpiStatus spi_end(SpiHostFake *bus)
{
    if (bus == NULL || bus->active == 0u) {
        return SPI_ERR_NOT_ACTIVE;
    }
    if (bus->cs_level[bus->selected_device] != 0u) {
        bus->error = (uint8_t)SPI_ERR_CS;
        spi_abort(bus);
        return SPI_ERR_CS;
    }
    bus->cs_level[bus->selected_device] = 1u;
    bus->active = 0u;
    bus->completed = 1u;
    return SPI_OK;
}
```

实现中的 `rx_queue` 是测试注入点，代表从设备在 MISO 上准备好的字节。`clock_steps` 只记录抽象交换次数；它不是实际频率，也不能用来推导波特率。`spi_set_all_cs_high()` 体现了本课的互斥规则：开始事务时先让所有设备不参与，再拉低目标设备片选。

`spi_abort()` 是 Host Fake 的恢复路径：传输参数、响应队列或片选状态不合法时，先释放全部片选并清除 `active`，再由调用者开始下一笔事务。忙状态错误不会自动取消已有事务，避免把一个并发调用错误误当成总线恢复。

### 9.3 实例化与组装

```c
static SpiHostFake fake_bus;

static void spi_fake_reset(SpiHostFake *bus,
                           const uint8_t *responses,
                           uint8_t response_count)
{
    uint8_t i;
    *bus = (SpiHostFake){0};
    spi_set_all_cs_high(bus);
    bus->rx_queue_count = (response_count > SPI_MAX_BYTES) ?
                          SPI_MAX_BYTES : response_count;
    for (i = 0u; i < bus->rx_queue_count; ++i) {
        bus->rx_queue[i] = responses[i];
    }
}
```

`fake_bus` 是实例化：它分配了一个静态状态对象。`spi_fake_reset()` 是组装辅助函数：测试把某个“从设备响应序列”注入这个实例。真实 BSP 组装层会在这里连接片选控制和具体外设适配，而不是让应用散落地写 GPIO。

### 9.4 使用：应用发起一个事务

```c
int main(void)
{
    static const uint8_t responses[2] = {0xA5u, 0x5Au};
    static const uint8_t tx[2] = {0x9Fu, 0x00u};
    uint8_t rx[2] = {0u, 0u};
    SpiStatus status;

    spi_fake_reset(&fake_bus, responses, 2u);
    status = spi_begin(&fake_bus, 0u);
    if (status == SPI_OK) {
        status = spi_transfer(&fake_bus, tx, rx, 2u);
    }
    if (status == SPI_OK) {
        status = spi_end(&fake_bus);
    }

    /* 逻辑验证时应观察：
       rx == {0xA5, 0x5A}
       tx_log == {0x9F, 0x00}
       cs_level[0] == 1, cs_level[1] == 1
       clock_steps == 2, completed == 1, active == 0
    */
    return (status == SPI_OK && rx[0] == 0xA5u && rx[1] == 0x5Au) ? 0 : 1;
}
```

这段使用代码没有直接访问移位寄存器或片选数组。应用只提供 TX/RX 缓冲，并按“开始、传输、结束”的调用流检查状态。示例中的 `main()` 返回值是可比较的逻辑结果，不是硬件证据。

### 9.5 一个实现细节必须在实验中暴露

示例把 `tx_log_count` 和 `rx_log_count` 递增，但没有在每次新事务开始时清零，也没有记录事务起始偏移。这是刻意留下的练习：如果多次事务共用同一个对象，测试必须明确是比较“本次片段”还是“累计日志”，并在接口契约中决定是否提供 `spi_fake_reset()` 或环形日志。不要把一个教学示例未经检查地当作生产驱动。

## 10. 常见错误

### 错误一：只准备 TX，不为读取准备时钟

SPI 的接收由时钟推动。主设备想读数据时，通常仍需发送占位字节；占位字节的值和读命令格式必须查目标设备数据手册。不能调用一个“只读函数”就假设总线上没有 MOSI 活动。

### 错误二：把片选当成普通 GPIO，忘记事务边界

若命令、地址和数据之间片选被意外拉高，目标设备可能重新解释后续字节。适配接口应让事务边界显式可见，并在错误路径恢复片选。

### 错误三：两个设备同时被选中

共享 MISO 时，两个从设备同时驱动会造成冲突。Host Fake 的 `spi_set_all_cs_high()` 和实验断言用于暴露这个错误；真实硬件还要检查外部上拉/下拉和未选中设备的输出状态，资料不足时待核对。

### 错误四：把 CPOL/CPHA 当成“速度设置”

CPOL/CPHA 决定采样和改变数据的边沿，时钟分频决定速度。两者必须匹配，但含义不同。具体模式编号和寄存器位以目标手册为准。[S1]

### 错误五：缓冲区长度来自不可信输入

`uint8_t length` 也不等于自动安全。调用者仍需保证 TX/RX 数组至少有 `length` 个元素，适配层需拒绝超过静态容量的长度。真实 HAL 的长度类型和最大值待核对。

### 错误六：错误后留下低片选

如果错误处理让 `active` 仍为 1 或片选仍为低，下一次事务会得到“已忙”或让设备误把新命令接在旧命令后面。正确实现应通过可观察的释放和复位路径避免这种残留。

## 11. 调试观察点

在主机上，按以下顺序打印或断言：

1. `spi_begin()` 返回后：`selected_device`、所有 `cs_level[]`、`active`；
2. 每次 `spi_transfer()` 后：TX/RX 索引、`clock_steps`、接收队列剩余量；
3. `spi_end()` 后：`completed`、`active`、片选是否全为高；
4. 错误路径：`error` 是否保留错误码，下一次 `spi_begin()` 是否能成功；
5. 多设备路径：设备 A 事务期间设备 B 的片选是否始终为高；
6. 边界路径：长度 0、长度 1、长度 `SPI_MAX_BYTES`、长度 `SPI_MAX_BYTES + 1` 的返回值和日志计数。

在真实目标上，逻辑分析仪应按时间顺序观察 `CS low -> SCK/MOSI/MISO activity -> CS high`；但没有设备和测量记录时不能写成已观察。寄存器视图中的忙闲、溢出、模式错误等字段必须引用目标参考手册并记录清除顺序，不能把 Host Fake 的 `error` 字段直接映射成某个硬件位。

## 12. 实战实验

以下实验只需要一个普通 Windows 主机和一个 C11 编译器。可将第 9 节代码保存为 `spi_host_fake.c`，自行运行；本课程不声称已经编译或执行。

### 实验 1：单字节交换

输入：`responses = {0x3C}`，`tx = {0x80}`，设备 0。

预期：`rx = {0x3C}`，`tx_log_count = 1`，`rx_log_count = 1`，`clock_steps = 1`，事务结束后两个片选都为高。

### 实验 2：多字节事务

输入：`responses = {0x11, 0x22, 0x33}`，`tx = {0x9F, 0x00, 0x00}`，设备 0。

预期：接收数组逐项为 `11 22 33`；片选只在整个三字节调用前后变化一次；`clock_steps = 3`。说明连续字节共享同一事务边界。

### 实验 3：片选中途错误释放

在 `spi_transfer()` 之前把 `cs_level[selected_device]` 手动改为高，再调用 `spi_end()`。

预期：返回 `SPI_ERR_CS`，`error` 被锁存，`active` 变为 0；修改实现使错误路径也显式确保所有片选为高，然后验证下一次 `spi_begin()` 可以成功。这里的手动改写只用于制造故障，应用代码不应绕过接口。

### 实验 4：两个设备互斥

先对设备 0 做一字节事务，再对设备 1 做一字节事务；在每次 `spi_begin()` 后断言目标片选为低且另一个为高。

预期：不存在两个片选同时为低；每次 `spi_end()` 后所有片选回到高。若断言失败，检查组装层是否把两个设备错误地绑定到同一状态槽。

### 实验 5：缓冲边界

为每一种长度分别重置实例、开始一笔新事务，再尝试长度 0、1、8、9。为长度 8 注入 8 个响应；长度 9 只用于验证静态容量拒绝，不要求提供 9 字节队列。

预期：长度 1 和 8 成功；长度 0 和 9 返回 `SPI_ERR_LENGTH`，随后 `active == 0` 且所有片选为高，日志和时钟计数不增加。调用者还应自行保证传入数组真实拥有足够元素。

### 实验 6：错误恢复

先在未 `spi_begin()` 时调用 `spi_transfer()`，再制造一次已开始事务中的长度错误，最后调用 `spi_begin()` 并完成一笔合法事务。

预期：第一次返回 `SPI_ERR_NOT_ACTIVE`；长度错误返回 `SPI_ERR_LENGTH` 后 `active == 0` 且片选全为高；最后一笔事务仍能成功，说明错误不会永久污染总线状态。若不能恢复，检查错误路径是否只设置错误码而没有调用 `spi_abort()`。

实验报告只记录输入数组、返回状态、TX/RX 数组、片选数组、计数器和恢复结果。报告应标注“主机逻辑验证”，不得把它描述成目标板实测结果。

## 13. 自检题

1. 为什么主设备即使只想读，也通常需要发送一个字节？请用 SCK、MOSI、MISO 三者的关系回答。
2. `spi_transfer()` 成功后，为什么 TX 字节数和 RX 字节数必须相等？
3. 片选拉低和拉高分别解决什么边界问题？如果三字节事务在第二字节后片选被拉高，设备可能如何解释？
4. 在 Host Fake 中，谁注入了 `rx_queue`，谁持有了当前事务状态，应用能否直接修改 `cs_level[]`？为什么？
5. 两个设备共享 MISO 时，为什么一次只能选择一个设备？Host Fake 用哪一个断言观察这个规则？
6. CPOL/CPHA 与时钟分频的区别是什么？哪些细节必须回到目标参考手册核对？
7. 错误恢复后，至少需要观察哪些状态才能证明下一次事务不是“带着旧片选继续”？

## 14. 面试题

1. 请画出一次两字节 SPI 事务的 CS、SCK、MOSI、MISO 关系，并指出主设备在哪些边沿改变或采样数据。若没有指定 CPOL/CPHA，不要假定具体边沿。
2. SPI 是全双工接口，但很多驱动 API 看起来像“发送”或“接收”。你会如何设计公共接口，避免调用者忘记接收字节或忘记为读取提供时钟？
3. 多个从设备共用一条 SPI 总线时，片选由谁持有、谁注入、谁保证互斥？请区分声明、实现、实例化、组装和使用。
4. 一个事务在 DMA 完成中断前不能拉高片选。你会把“完成”状态放在哪里，如何让错误路径也释放片选？本题只讨论状态流，不要求本课实现 DMA。
5. F4 上验证过的 SPI 状态处理能否直接复制到 H7？请给出需要重新核对的第一方资料和证据类型。

## 15. 延伸思考

- 如果一个设备协议要求“命令和响应之间片选保持低”，公共接口是否应该允许分段传输？怎样让片选保持成为显式契约，而不是隐藏的全局状态？
- 如果应用速度低于总线速度，接收数组应由谁持有？固定长度事务、环形缓冲区和 DMA 各自改变了哪一层的责任？
- 如果两个设备要求不同 CPOL/CPHA，组装层切换模式时需要保存和恢复哪些总线状态？切换期间如何保证片选全部释放？
- 片选由硬件 NSS 自动管理时，软件仍需观察哪些边界？如果目标系列提供 FIFO 或不同的状态清除规则，哪些 Host Fake 不变量仍然保持不变？
- 为这段 Host Fake 增加一个“累计日志”和一个“单事务视图”，你会怎样修改对象生命周期和测试断言？

## 16. 本节总结

SPI 的第一条主线是**时钟驱动的全双工移位交换**：主设备提供 SCK，每个交换步同时产生一个 TX 和一个 RX 结果；应用的读取请求也必须通过时钟获得数据。第二条主线是**片选定义的事务边界与设备选择**：片选把命令、地址和数据包在一起，并在共享总线上选出唯一目标。

Host Fake 把这两条主线变成可观察状态：响应队列是输入注入点，发送/接收日志是结果，片选数组是事务边界，计数器和完成标志是逻辑证据。它没有证明任何真实芯片寄存器或波形。迁移到 STM32 时，适配层应保持调用流和边界不变量，再依据目标系列参考手册、匹配版本 HAL/LL 文档、构建记录和波形/寄存器观察逐项核对。

## 17. 下一步

下一课应在 SPI 的事务模型上继续一个相邻机制，例如比较轮询与中断服务如何推进同一笔事务；在引入 DMA、RTOS 或复杂设备驱动前，先用本课实验结果证明片选边界和错误恢复已经清楚。学习状态不会因为本课生成而自动提高，只有你的自检答案、实验记录或复习结果才能改变掌握度。

## 18. 参考资料

- [S1] STMicroelectronics，*RM0090 STM32F405/415/407/417/427/437/429/439 advanced Arm-based 32-bit MCUs reference manual*，Rev 22，首页与目录页 1、26，SPI/I2S 章节页 868-895：功能描述、MISO/MOSI/SCK/NSS、主从通信流程、控制/状态/数据寄存器。URL：<https://www.st.com/resource/en/reference_manual/dm00031020.pdf>。访问日期：2026-10-05。该手册的系列适用范围仅限其首页列出的 STM32F4 型号；不能直接证明 F7、H5 或 H7 的差异。
- [S2] STMicroelectronics，*UM1725 Description of STM32F4 HAL and low-layer drivers*，Rev 8，SPI Generic Driver 章节页 1030-1048：`SPI_InitTypeDef`、句柄状态、阻塞/中断/DMA 收发、Abort、状态/错误 API。URL：<https://www.st.com/resource/en/user_manual/dm00105879.pdf>。访问日期：2026-10-05。该资料描述 STM32CubeF4 HAL/LL 包；其他系列或其他包版本必须重新核对。

本课没有引用第三方完整源码，也没有使用上述资料推断 F7、H5、H7 的未核对寄存器或 API 行为。

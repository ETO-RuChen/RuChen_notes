+++
title = "I2C 共享双线事务：主机发起与从机响应的状态机"
date = "2026-10-06T16:00:06+08:00"
lastmod = "2026-10-06T16:00:06+08:00"
summary = "建立平台无关的 I2C 共享双线事务模型：主机取得总线、发送地址和读写方向、处理 ACK/NACK、完成写入或读取并以 STOP 释放总线；通过 Host Fake 的开漏线路模型、事件日志、断言和故障注入验证调用流，不把逻辑验证当作 STM32 硬件证据。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 24
tags = ["i2c", "sda", "scl", "open-drain", "ack-nack", "transaction", "state-machine", "host-fake", "c11", "beginner"]
source_ids = ["st-rm0090", "st-um1725"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L024"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 24 课：I2C 共享双线事务：主机发起与从机响应的状态机

I2C（Inter-Integrated Circuit，内部集成电路）常被描述成“只有两根线的串行总线”。这个说法还不够：真正需要掌握的是，多个设备怎样共享 SDA（Serial Data，串行数据线）和 SCL（Serial Clock，串行时钟线），又怎样把一串电平组织成一次有边界、可确认、可失败的事务。

本课只推进一个核心概念：**I2C 共享双线总线上的主机发起、从机响应事务状态机**。开漏、上拉、START、STOP、7 位地址、读写方向、ACK/NACK（应答/非应答）都是帮助读懂这个状态机的支撑术语，不把它们扩展为额外课程目标。

没有指定开发板、调试器、示波器或逻辑分析仪，所以主线是可以在普通 Windows 主机上阅读和运行的 Host Fake（主机伪实现）。它验证线路所有权、事务边界、地址方向、应答、重复 START、读写结果和错误恢复的逻辑；它不验证电压、电阻、引脚复用、时序裕量、寄存器位、某个 STM32 实例或真实 HAL 行为。因此本课的 `hardware_verified` 为 `false`，所有硬件迁移结论都必须回到课程末尾列出的第一方资料逐项核对。

## 1. 本节目标

完成本课后，你应能：

- 用“谁驱动哪根线、当前处于哪一个状态、下一步由谁注入”描述一次 I2C 主机事务；
- 解释开漏与上拉模型为什么适合共享线路，并区分“驱动低电平”和“释放线路”；
- 从地址帧中分辨 7 位设备地址与读写方向位，说明地址不匹配为什么表现为 NACK；
- 画出单字节写、重复 START 后读取、ACK 后继续和最后一个字节 NACK 的状态转移；
- 读懂 Host Fake 中对象的定义、持有者、注入点和调用流，并用日志和断言定位失败；
- 把平台无关状态转移映射到 STM32 的轮询、事件/错误处理或 HAL/LL 适配层，同时列出仍需核对的硬件事实。

成功标准是“能解释并验证模型”，不是“已经编译、下载或上板”。

## 2. 它解决什么问题

### 2.1 两根共享线如何承载多个设备

UART（通用异步收发器）通常连接一个发送端和一个接收端，SPI（串行外设接口）通常用片选指出当前从设备。I2C 需要在少量共享信号线上同时解决三件事：

1. 谁在当前时刻发起时钟和事务；
2. 哪个设备应该响应当前地址；
3. 一个字节是否已经被对方接收，事务何时结束。

I2C 用 SCL 携带时钟，用 SDA 携带数据；主机发起 START（开始条件），发送地址帧和读写方向，接收方在每个字节后用 ACK 或 NACK 表示是否继续，最后由主机发出 STOP（停止条件）释放事务。这里的“发出”不是简单地把一个 `uint8_t` 写进数组，而是状态机在共享线路上交替完成控制和确认。

### 2.2 先规定约束，再做抽象

- 代码采用 C11 子集；公开接口使用 `uint8_t`、`uint16_t`、`uint32_t` 等固定宽度整数；
- 使用静态对象和固定容量数组，不使用动态内存；
- Host Fake 把一个完整字节压缩成一个可观察的逻辑步进，保留字节顺序、ACK/NACK 和状态转移，不模拟真实的 8 个时钟边沿、电压或建立保持时间；
- 线路的抽象规则是：参与者可以拉低线路或释放线路，线路上没有人拉低时由上拉模型得到高电平；任何一个参与者拉低时，读取结果都是低电平；
- 没有具体开发板，因此不假设 I2C 实例、引脚、GPIO 复用、上拉阻值、速率、时序寄存器、标志位或 HAL（Hardware Abstraction Layer，硬件抽象层）函数签名；这些必须按目标系列第一方手册核对。[S1][S2]

### 2.3 最小闭环先看结果

下面的例子是“向地址 `0x50` 写入寄存器 `0x10` 的值 `0xA5`”。左侧是调用流，右侧是可观察结果：

```text
应用：i2c_write(0x50, [0x10, 0xA5])
  |
  +--> START                 -> 总线从 idle 进入 busy
  +--> 地址 0x50 + W         -> 从机匹配并 ACK
  +--> 数据 0x10             -> 从机 ACK
  +--> 数据 0xA5             -> 从机 ACK
  +--> STOP                  -> SDA/SCL 释放，回到 idle

事件日志：START, ADDR_W_ACK, DATA_ACK, DATA_ACK, STOP, IDLE
结果：I2C_OK
```

读取通常需要两个阶段。主机先写入待读取的寄存器地址，然后不发 STOP，直接发重复 START（Repeated START，重复开始条件），再发送同一 7 位地址和读方向：

```text
START -> ADDR_W + ACK -> REGISTER + ACK
      -> REPEATED_START -> ADDR_R + ACK
      -> DATA + ACK     -> DATA + NACK -> STOP
```

最后一个字节后的 NACK 不是“错误”，而是主机告诉从机“我不再请求下一个字节”。地址不匹配时的 NACK 则是失败路径；必须结合当前状态和产生者解释。

## 3. 必要前置知识

只把 `config/learning-state.toml` 的 `completed` 列表视为已完成前置。与本课直接相关的前置包括：

1. 固定宽度整数、数组、指针、`const` 和 `volatile` 的基本含义；本课用 `uint8_t` 表示一个总线字节，用数组表达固定容量缓冲区。
2. GPIO（通用输入输出）与电平观察；本课把“输出低电平”和“释放输出”抽象成线路参与者的两种动作。
3. UART、SPI 的事务和帧边界；I2C 的差异在于共享线路、地址选择和每字节应答，而不是片选或全双工交换。
4. 编译器、Make/CMake 和静态分析的基本使用；实验只给出主机命令和可观察断言，不把未执行的命令当作构建证据。

如果你还不能解释 C 结构体、枚举或 `assert`，先用代码中的字段和断言做小练习；本课不会把它们扩展为新的嵌入式架构概念。中断、DMA、RTOS 和具体寄存器编程仅作为后续演化方向，不是本课前置或目标。

## 核心原理

本节以共享双线事务状态机为主线，说明 I2C 的线路控制、地址应答和事务边界。

### 4.1 它解决什么问题

字节本身没有事务边界，也没有“对方是否接收”的信息。状态机把一次请求拆成可以观察的阶段：总线空闲、开始、地址、数据、应答、重复开始、停止和错误。每个阶段规定：

- 当前谁可以改变 SDA 或 SCL；
- 下一步期望看到什么线路结果；
- 如果看到 NACK、超时或非法顺序，结果如何终止；
- 哪一个对象保存状态，调用返回后如何让测试读取它。

因此状态机不是给 API 起名字，而是给共享线路上的控制权和事务边界建立可审计契约。

### 4.2 对象在哪里定义、谁持有、谁注入

在 Host Fake 中，`I2cBus` 定义两根线和每个参与者的驱动意图，`I2cMaster` 持有当前状态、日志和错误结果，`I2cSlaveScript` 持有地址、读数据和故障注入开关。

- **线路对象**：`I2cBus`。它不属于应用；测试创建一个静态实例，主机和从机都通过它读写线路意图。
- **事务状态**：`I2cMaster`。它由调用者持有，保存当前状态、目标地址、读写方向、已读写字节数和最后错误。
- **从机响应**：`I2cSlaveScript`。测试在事务开始前注入地址匹配、读数据、地址 NACK 或保持 SDA 低等脚本；主机代码不能凭空制造从机响应。
- **事件日志**：由 `I2cMaster` 持有，记录状态转移和结果；测试通过日志检查调用流，而不是猜测内部变量。
- **调用流**：应用请求 → 主机适配函数 → 总线状态更新 → 从机脚本决定 ACK/NACK 或数据 → 主机保存状态和日志 → 应用读取 `I2cResult`。

真实 MCU 中，这些对象会分别落在应用缓冲区、I2C 外设寄存器/状态、GPIO 电气配置和驱动上下文里；具体归属取决于所选系列和驱动版本，不能由 Host Fake 直接推断。

### 4.3 开漏与上拉的直观模型

“开漏”（open-drain）在本课中只需要一个可迁移的抽象：参与者主动可靠地把线拉低，或者释放线路让上拉把线带到高电平。它不是“一个人输出 1、另一个人输出 0 时做普通推挽冲突”，而是多个参与者共享“是否有人拉低”的结果。

```text
master_drive_low  slave_drive_low  线路读取值
       0                 0              1（上拉）
       1                 0              0
       0                 1              0
       1                 1              0
```

这就是 Host Fake 的线与（wired-AND）规则。真实硬件仍需核对 GPIO 输出类型、外部或内部上拉、速度和电气时序；RM0090 的 GPIO/I2C 章节与 UM1725 的 GPIO 配置说明是 STM32F4 适配时的第一方入口。[S1][S2]

### 4.4 地址帧和读写方向

本课统一把设备地址保存为 7 位 `uint8_t`，要求范围是 `0x00` 到 `0x7F`。在逻辑模型中，地址帧由：

```text
7 位设备地址 + 1 位方向
方向 0：主机写（ADDR_W）
方向 1：主机读（ADDR_R）
```

具体线上位序和目标外设寄存器字段仍需按目标手册核对；不要把已经左移一位的“地址字节”再当成 7 位地址保存。Host Fake 显式使用 `address_7bit` 和 `read` 两个字段，避免把位移约定藏在调用者里。

### 4.5 ACK/NACK 的产生者和意义

一个字节传输完成后，接收方通过 ACK 或 NACK 表明是否接受/继续：

- 地址阶段：匹配地址的从机注入 ACK；没有匹配设备时注入 NACK；
- 写数据阶段：从机可以对每个数据字节 ACK，也可以因容量或协议拒绝而 NACK；
- 读数据阶段：主机在收到数据后 ACK 表示继续，最后一个字节发送 NACK 表示结束，然后发送 STOP。

因此“看到 NACK”不能直接等于“硬件坏了”。要同时观察当前状态、方向、字节索引和 NACK 的预期产生者。

## 5. 关键术语、直观模型与状态转移

| 术语 | 本课中的直观含义 |
| --- | --- |
| SDA | 承载地址、数据和应答的共享数据线；主机或从机可以拉低或释放 |
| SCL | 主机推动事务节拍的共享时钟线；本课只把它作为线路状态观察对象 |
| 主机 | 发起 START、地址、时钟和 STOP 的事务参与者 |
| 从机 | 按地址响应、提供 ACK/NACK 或读数据的事务参与者 |
| 开漏 | 参与者主动拉低或释放，不直接争抢高电平的线路驱动抽象 |
| 上拉 | 没有参与者拉低时，使线路读值回到高电平的抽象来源 |
| START/STOP | 一次事务的开始/释放边界；重复 START 在同一事务意图内切换方向 |
| ACK/NACK | 接收方对当前字节的继续/结束或拒绝信号 |

可以把总线想成两条由多个参与者共同观察的“请求线”：主机负责推进阶段，从机只有在地址匹配和允许响应时才注入拉低动作。这个模型解释了为什么总线状态、参与者动作和事务状态必须同时记录。

| 当前状态 | 动作/观察 | 下一状态 | 失败观察点 |
| --- | --- | --- | --- |
| `IDLE` | SDA、SCL 都为高，主机发 START | `STARTED` | 任一线仍为低：总线忙或被占用 |
| `STARTED` | 发送 7 位地址和写方向 | `ADDR_W_ACK` 或 `ERROR` | 地址 NACK |
| `STARTED` | 发送 7 位地址和读方向 | `ADDR_R_ACK` 或 `ERROR` | 地址 NACK |
| `ADDR_W_ACK` | 发送寄存器/数据字节，收到 ACK | `WRITE_BYTE` | 数据 NACK、容量拒绝 |
| `ADDR_W_ACK` | 不发 STOP，发重复 START | `RESTARTED` | 重复 START 前状态不完整 |
| `RESTARTED` | 发送同一地址和读方向 | `ADDR_R_ACK` 或 `ERROR` | 读地址 NACK |
| `ADDR_R_ACK` | 收到数据并发送 ACK | `READ_BYTE` | 数据未准备好或超时 |
| `READ_BYTE` | 收到最后数据并发送 NACK | `READ_LAST` | 把 ACK/NACK 方向写反 |
| `WRITE_BYTE`/`READ_LAST` | 主机发 STOP，双方释放线路 | `IDLE` | STOP 后仍有线被拉低 |
| 任意事务态 | 超时或非法顺序 | `ERROR` | 必须记录原因，并尝试 STOP/恢复 |

`RESTARTED` 是逻辑边界，不是第三条线。它表示主机在同一个事务意图中重新取得控制，而没有先让从机看到 STOP。具体 MCU 外设如何报告事件或状态，属于 STM32 适配阶段的待核对内容。[S1][S2]

## 6. 从输入到结果的完整流程

以“读取地址 `0x50` 的寄存器 `0x10`，取得一个字节”为例：

1. 应用准备 `device=0x50`、寄存器 `0x10` 和一个接收缓冲区，调用高层的 `i2c_read_register` 逻辑。
2. 主机检查状态是否为 `IDLE`，读取 SDA/SCL；若任一为低，返回 `I2C_ERR_BUS_BUSY`，不静默覆盖别人的事务。
3. 主机让 SDA 从高变低，同时保持 SCL 为高，记录 `START`，进入 `STARTED`。
4. 主机发送地址 `0x50` 和写方向。`I2cSlaveScript` 比较 7 位地址，匹配则让自己的 SDA 驱动意图为低一个应答时隙，主机读到 ACK。
5. 主机发送寄存器编号 `0x10`，从机脚本 ACK，并在测试模型中记录最后收到的写入字节；真实器件的内部寄存器游标属于器件协议，必须按该器件数据手册核对。
6. 主机释放 SDA、保持 SCL 的协议动作，发出重复 START；状态仍属于同一个高层读取请求。
7. 主机发送地址 `0x50` 和读方向，从机 ACK 并提供预先注入的 `read_data`。
8. 主机读取第一个字节；因为这是最后一个字节，主机注入 NACK，表示不再请求更多数据。
9. 主机发 STOP，释放 SDA/SCL；总线解析结果回到高电平，状态回到 `IDLE`，应用得到 `I2C_OK` 和接收字节。

任何一步失败都必须保留“在哪一个状态、哪一个字节、谁预期产生 ACK/NACK”的信息。只返回一个布尔值会丢掉最有用的诊断上下文。

## 7. 嵌入式系统中的对应位置

把 Host Fake 搬到 MCU 时，可以按以下顺序寻找对应物：

```text
应用请求
  -> I2C 事务适配层（检查地址、长度、状态）
  -> STM32 I2C 外设/驱动（产生 START、地址、数据、STOP）
  -> GPIO 复用与电气配置（SDA/SCL 线路）
  -> 外部从设备
  -> 事件/错误状态映射
  -> 应用结果与诊断日志
```

Host Fake 的 `I2cBus` 对应“线路电平的抽象”，`I2cMaster.state` 对应“软件事务上下文”，`I2cSlaveScript` 对应“测试替身或真实外部器件的响应”。它们不是 STM32 寄存器的同名替代品。真实 MCU 中，这些对象会分别落在应用缓冲区、I2C 外设寄存器/状态、GPIO 电气配置和驱动上下文里；具体归属取决于所选系列和驱动版本，不能由 Host Fake 直接推断。

## 8. 主机实验与硬件迁移边界

主机实验只验证状态流、日志和错误结果；没有开发板、测量工具或运行记录时，`hardware_verified` 必须保持 `false`。迁移到 STM32F4、F7、H5 或 H7 时，逐项完成以下核对，并把证据记录在具体硬件运行目录：

1. 选定系列和具体器件，确认 I2C 实例、SDA/SCL 可用引脚和复用编号；本课没有指定实例或引脚。
2. 回到目标参考手册，核对 I2C 外设在 START、地址、数据、ACK/NACK、STOP、错误和超时时的状态/标志语义。[S1]
3. 回到目标 GPIO 章节，核对开漏、上拉、速度和复用配置；外部上拉阻值和总线电容属于硬件设计，不由 Host Fake 推导。[S1]
4. 若使用 HAL 或 LL，核对目标 STM32Cube 包版本的轮询/中断接口、缓冲区生命周期、超时参数和返回值；UM1725 只能作为 STM32F4 HAL/LL 文档入口，不能自动证明 F7/H5/H7 API 相同。[S2]
5. 把本课状态表中的每个转移映射到适配层事件，并为地址 NACK、总线忙、超时、错误 STOP 和恢复路径保留日志。
6. 用逻辑分析仪或示波器观察真实 START、地址位序、ACK/NACK 和 STOP；没有测量记录时保持 `hardware_verified=false`。

“时钟拉伸”（clock stretching）和“多主机仲裁”（arbitration）是 I2C 规范中重要的进一步行为。本课只保留 `hold_sda_low` 和超时错误作为故障注入，不对具体 STM32 支持、标志位或仲裁策略作未经核对的结论；它们应在后续按目标系列第一方资料单独验证。

## 9. 最小代码示例

下面是一份单文件、静态存储的 C11 子集示例。它刻意把真实边沿压缩为逻辑步骤，但保留开漏线路、地址方向、ACK/NACK、重复 START、STOP、日志和故障注入。代码属于**主机逻辑验证层**，不是 STM32 驱动，也没有编译或硬件运行证据。

```c
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define I2C_LOG_CAPACITY 48U
#define I2C_DATA_CAPACITY 8U

typedef enum {
    I2C_LINE_RELEASED = 0,
    I2C_LINE_LOW = 1
} I2cLineDrive;

typedef enum {
    I2C_STATE_IDLE = 0,
    I2C_STATE_STARTED,
    I2C_STATE_ADDR_W_ACK,
    I2C_STATE_ADDR_R_ACK,
    I2C_STATE_WRITE_BYTE,
    I2C_STATE_RESTARTED,
    I2C_STATE_READ_BYTE,
    I2C_STATE_READ_LAST,
    I2C_STATE_ERROR
} I2cState;

typedef enum {
    I2C_OK = 0,
    I2C_ERR_BUS_BUSY,
    I2C_ERR_ADDRESS_NACK,
    I2C_ERR_DATA_NACK,
    I2C_ERR_TIMEOUT,
    I2C_ERR_PROTOCOL
} I2cResult;

typedef struct {
    I2cLineDrive master_sda;
    I2cLineDrive slave_sda;
    I2cLineDrive master_scl;
    I2cLineDrive slave_scl;
} I2cBus;

typedef struct {
    uint8_t address_7bit;
    uint8_t read_data[I2C_DATA_CAPACITY];
    uint8_t read_length;
    uint8_t last_write;
    bool reject_address;
    bool reject_data;
    bool hold_sda_low;
} I2cSlaveScript;

typedef struct {
    I2cBus *bus;
    I2cSlaveScript *slave;
    I2cState state;
    I2cResult result;
    uint8_t address_7bit;
    uint8_t log_count;
    const char *log[I2C_LOG_CAPACITY];
    uint8_t rx[I2C_DATA_CAPACITY];
    uint8_t rx_count;
} I2cMaster;

static bool i2c_sda_high(const I2cBus *bus)
{
    return bus->master_sda == I2C_LINE_RELEASED &&
           bus->slave_sda == I2C_LINE_RELEASED;
}

static bool i2c_scl_high(const I2cBus *bus)
{
    return bus->master_scl == I2C_LINE_RELEASED &&
           bus->slave_scl == I2C_LINE_RELEASED;
}

static void i2c_log(I2cMaster *master, const char *event)
{
    assert(master->log_count < I2C_LOG_CAPACITY);
    master->log[master->log_count] = event;
    master->log_count++;
}

static void i2c_release_lines(I2cMaster *master)
{
    master->bus->master_sda = I2C_LINE_RELEASED;
    master->bus->master_scl = I2C_LINE_RELEASED;
    master->bus->slave_sda = master->slave->hold_sda_low
                           ? I2C_LINE_LOW : I2C_LINE_RELEASED;
    master->bus->slave_scl = I2C_LINE_RELEASED;
}

static I2cResult i2c_start(I2cMaster *master)
{
    if (!i2c_sda_high(master->bus) || !i2c_scl_high(master->bus)) {
        master->state = I2C_STATE_ERROR;
        master->result = I2C_ERR_BUS_BUSY;
        i2c_log(master, "BUS_BUSY");
        return master->result;
    }
    master->bus->master_sda = I2C_LINE_LOW;
    master->state = I2C_STATE_STARTED;
    i2c_log(master, "START");
    return I2C_OK;
}

static bool i2c_slave_ack_address(I2cMaster *master, bool read)
{
    const bool address_matches = !master->slave->reject_address &&
                                 master->address_7bit == master->slave->address_7bit;
    if (!address_matches) {
        i2c_log(master, read ? "ADDR_R_NACK" : "ADDR_W_NACK");
        return false;
    }
    master->bus->slave_sda = I2C_LINE_LOW;
    i2c_log(master, read ? "ADDR_R_ACK" : "ADDR_W_ACK");
    master->bus->slave_sda = I2C_LINE_RELEASED;
    master->state = read ? I2C_STATE_ADDR_R_ACK : I2C_STATE_ADDR_W_ACK;
    return true;
}

static I2cResult i2c_send_address(I2cMaster *master, uint8_t address_7bit, bool read)
{
    if (master->state != I2C_STATE_STARTED &&
        master->state != I2C_STATE_RESTARTED) {
        master->state = I2C_STATE_ERROR;
        master->result = I2C_ERR_PROTOCOL;
        i2c_log(master, "BAD_ADDRESS_STATE");
        return master->result;
    }
    master->address_7bit = address_7bit;
    if (!i2c_slave_ack_address(master, read)) {
        master->state = I2C_STATE_ERROR;
        master->result = I2C_ERR_ADDRESS_NACK;
        return master->result;
    }
    return I2C_OK;
}

static I2cResult i2c_write_byte(I2cMaster *master, uint8_t value)
{
    if (master->state != I2C_STATE_ADDR_W_ACK &&
        master->state != I2C_STATE_WRITE_BYTE) {
        master->state = I2C_STATE_ERROR;
        master->result = I2C_ERR_PROTOCOL;
        i2c_log(master, "BAD_WRITE_STATE");
        return master->result;
    }
    master->slave->last_write = value;
    if (master->slave->reject_data) {
        master->state = I2C_STATE_ERROR;
        master->result = I2C_ERR_DATA_NACK;
        i2c_log(master, "DATA_NACK");
        return master->result;
    }
    master->state = I2C_STATE_WRITE_BYTE;
    i2c_log(master, "DATA_ACK");
    return I2C_OK;
}

static I2cResult i2c_repeated_start(I2cMaster *master)
{
    if (master->state != I2C_STATE_ADDR_W_ACK &&
        master->state != I2C_STATE_WRITE_BYTE) {
        master->state = I2C_STATE_ERROR;
        master->result = I2C_ERR_PROTOCOL;
        i2c_log(master, "BAD_RESTART_STATE");
        return master->result;
    }
    master->bus->master_sda = I2C_LINE_RELEASED;
    master->bus->master_sda = I2C_LINE_LOW;
    master->state = I2C_STATE_RESTARTED;
    i2c_log(master, "REPEATED_START");
    return I2C_OK;
}

static I2cResult i2c_read_last_byte(I2cMaster *master, uint8_t *out)
{
    if (out == NULL || master->state != I2C_STATE_ADDR_R_ACK) {
        master->state = I2C_STATE_ERROR;
        master->result = I2C_ERR_PROTOCOL;
        i2c_log(master, "BAD_READ_STATE");
        return master->result;
    }
    if (master->slave->read_length == 0U || master->slave->hold_sda_low) {
        if (master->slave->hold_sda_low) {
            master->bus->slave_sda = I2C_LINE_LOW;
        }
        master->state = I2C_STATE_ERROR;
        master->result = I2C_ERR_TIMEOUT;
        i2c_log(master, "READ_TIMEOUT");
        return master->result;
    }
    if (master->rx_count >= I2C_DATA_CAPACITY) {
        master->state = I2C_STATE_ERROR;
        master->result = I2C_ERR_PROTOCOL;
        i2c_log(master, "RX_OVERFLOW");
        return master->result;
    }
    *out = master->slave->read_data[0];
    master->rx[master->rx_count] = *out;
    master->rx_count++;
    master->state = I2C_STATE_READ_LAST;
    i2c_log(master, "READ_BYTE_NACK");
    return I2C_OK;
}

static I2cResult i2c_stop(I2cMaster *master)
{
    const I2cResult prior_result = master->result;
    const bool was_error = master->state == I2C_STATE_ERROR;

    if (master->state == I2C_STATE_IDLE) {
        return I2C_OK;
    }
    master->bus->master_sda = I2C_LINE_RELEASED;
    i2c_release_lines(master);
    master->state = I2C_STATE_IDLE;
    i2c_log(master, "STOP");
    if (!i2c_sda_high(master->bus) || !i2c_scl_high(master->bus)) {
        master->result = I2C_ERR_TIMEOUT;
        i2c_log(master, "STOP_NOT_IDLE");
        return master->result;
    }
    if (!was_error) {
        master->result = I2C_OK;
    } else {
        master->result = prior_result;
    }
    i2c_log(master, "IDLE");
    return master->result;
}

static void test_read_with_repeated_start(void)
{
    I2cBus bus = { I2C_LINE_RELEASED, I2C_LINE_RELEASED,
                   I2C_LINE_RELEASED, I2C_LINE_RELEASED };
    I2cSlaveScript slave = { 0x50U, { 0xA5U }, 1U, 0U, false, false, false };
    I2cMaster master = { &bus, &slave, I2C_STATE_IDLE, I2C_OK,
                         0U, 0U, { 0 }, { 0 }, 0U };
    uint8_t value = 0U;

    assert(i2c_start(&master) == I2C_OK);
    assert(i2c_send_address(&master, 0x50U, false) == I2C_OK);
    assert(i2c_write_byte(&master, 0x10U) == I2C_OK);
    assert(i2c_repeated_start(&master) == I2C_OK);
    assert(i2c_send_address(&master, 0x50U, true) == I2C_OK);
    assert(i2c_read_last_byte(&master, &value) == I2C_OK);
    assert(value == 0xA5U);
    assert(i2c_stop(&master) == I2C_OK);
    assert(master.state == I2C_STATE_IDLE);
    assert(i2c_sda_high(&bus) && i2c_scl_high(&bus));
}

static void test_address_nack_and_recovery(void)
{
    I2cBus bus = { I2C_LINE_RELEASED, I2C_LINE_RELEASED,
                   I2C_LINE_RELEASED, I2C_LINE_RELEASED };
    I2cSlaveScript slave = { 0x50U, { 0 }, 0U, 0U, true, false, false };
    I2cMaster master = { &bus, &slave, I2C_STATE_IDLE, I2C_OK,
                         0U, 0U, { 0 }, { 0 }, 0U };

    assert(i2c_start(&master) == I2C_OK);
    assert(i2c_send_address(&master, 0x50U, false) == I2C_ERR_ADDRESS_NACK);
    assert(i2c_stop(&master) == I2C_ERR_ADDRESS_NACK);
    assert(master.result == I2C_ERR_ADDRESS_NACK);
    assert(master.state == I2C_STATE_IDLE);
    assert(i2c_sda_high(&bus) && i2c_scl_high(&bus));
}

static void test_single_byte_write(void)
{
    I2cBus bus = { I2C_LINE_RELEASED, I2C_LINE_RELEASED,
                   I2C_LINE_RELEASED, I2C_LINE_RELEASED };
    I2cSlaveScript slave = { 0x50U, { 0 }, 0U, 0U, false, false, false };
    I2cMaster master = { &bus, &slave, I2C_STATE_IDLE, I2C_OK,
                         0U, 0U, { 0 }, { 0 }, 0U };

    assert(i2c_start(&master) == I2C_OK);
    assert(i2c_send_address(&master, 0x50U, false) == I2C_OK);
    assert(i2c_write_byte(&master, 0xA5U) == I2C_OK);
    assert(slave.last_write == 0xA5U);
    assert(i2c_stop(&master) == I2C_OK);
    assert(master.state == I2C_STATE_IDLE);
}

static void test_data_nack_and_recovery(void)
{
    I2cBus bus = { I2C_LINE_RELEASED, I2C_LINE_RELEASED,
                   I2C_LINE_RELEASED, I2C_LINE_RELEASED };
    I2cSlaveScript slave = { 0x50U, { 0 }, 0U, 0U, false, true, false };
    I2cMaster master = { &bus, &slave, I2C_STATE_IDLE, I2C_OK,
                         0U, 0U, { 0 }, { 0 }, 0U };

    assert(i2c_start(&master) == I2C_OK);
    assert(i2c_send_address(&master, 0x50U, false) == I2C_OK);
    assert(i2c_write_byte(&master, 0xA5U) == I2C_ERR_DATA_NACK);
    assert(i2c_stop(&master) == I2C_ERR_DATA_NACK);
    assert(master.state == I2C_STATE_IDLE);
    assert(i2c_sda_high(&bus) && i2c_scl_high(&bus));
}

int main(void)
{
    test_single_byte_write();
    test_read_with_repeated_start();
    test_address_nack_and_recovery();
    test_data_nack_and_recovery();
    puts("Host Fake assertions passed in the example model.");
    return 0;
}
```

代码中有几个刻意的教学取舍：

- `i2c_sda_high` 和 `i2c_scl_high` 只解析“是否有人拉低”，体现共享线与和上拉，不声称模拟实际电气波形；
- `I2cSlaveScript` 是测试注入点，地址 NACK、数据 NACK、返回数据和保持 SDA 低都由测试配置；
- `i2c_read_last_byte` 只演示一个待读字节。多字节读取需要在中间字节发送 ACK、最后字节发送 NACK，并继续检查缓冲区边界；
- `i2c_stop` 在错误路径仍尝试释放线路，便于下一次事务观察是否回到 `IDLE`；真实总线被外部设备持续拉低时，恢复动作和超时策略必须按平台资料与硬件设计补充；
- 代码没有使用函数指针、依赖注入框架、RTOS、DMA 或具体寄存器，避免把本课的事务模型和后续架构概念混在一起。

课程生成阶段没有编译或上板证据；本次审查已在临时目录用 GCC C11 编译并运行该代码，输出为 `Host Fake assertions passed in the example model.`。这只证明主机逻辑模型，仍不构成 STM32 上板或电气验证。

## 10. 常见错误

### 9.1 把 8 位地址常量当成 7 位地址

有些 API 接受已经左移并带方向位的地址字节，有些接口接受裸 7 位地址。若调用者和驱动各自移位一次，就会访问错误设备。课程代码把 `address_7bit` 单独命名，适配时必须先读目标 API 契约。

### 9.2 把所有 NACK 都当作同一种失败

地址 NACK 说明当前地址阶段没有得到匹配响应；最后一个读字节后的 NACK 是主机主动结束读取。调试时至少记录方向、阶段和字节索引。

### 9.3 读操作先 STOP 再重新开始

某些器件协议要求写寄存器地址后保持事务意图，用重复 START 切换到读方向。是否允许 STOP 后再开始是目标器件协议问题；不能把两种序列当成等价。

### 9.4 只在软件里释放 SDA，不检查实际线路

软件写入“释放”并不代表线路已经回高。外部器件保持低、上拉缺失或配置错误都会让实际读取继续为低；真实适配层必须有超时和可观察错误路径。

### 9.5 错误后直接复用忙状态对象

如果错误路径没有 STOP、恢复或明确地回到可重试状态，下一次调用可能从 `WRITE_BYTE` 等旧状态开始。Host Fake 的测试专门检查 NACK 后 STOP 和 `IDLE`。

### 9.6 把 Host Fake 通过断言当成硬件证据

断言只证明抽象状态流满足测试输入。它不能证明引脚复用、上拉、电气速度、时序寄存器、外设标志或 HAL 实现正确。

## 11. 调试观察点

按下面的观察顺序，能把“没有读到数据”拆成更小的问题：

1. **总线前置状态**：事务开始前 SDA/SCL 是否都高？若不是，记录 `BUS_BUSY`，不要立即覆盖线路。
2. **START 边界**：SCL 高时 SDA 是否从高变低？Host Fake 只记录逻辑事件，真实系统需用测量工具确认。
3. **地址和方向**：日志应显示 7 位地址、写/读方向和地址阶段 ACK/NACK；不要只打印一个十六进制地址字节。
4. **每字节应答**：写入时检查从机是否对寄存器和数据 ACK；读取时检查主机是否在最后一个字节发送 NACK。
5. **重复 START**：读取寄存器的写阶段结束后，状态是否进入 `RESTARTED`，是否意外发出了 STOP？
6. **停止后的线路**：STOP 后读取线路是否回到高？若从机保持 SDA 低，记录超时并区分“软件未释放”和“外部仍占用”。
7. **日志与结果一致性**：返回 `I2C_OK` 必须同时满足状态为 `IDLE`、接收长度正确、STOP 已记录；错误结果必须带最后状态和错误原因。

## 实战实验

以下实验在 Windows 主机上验证状态机；章节中的具体步骤保留在对应实验小节中。

### 实验 A：正常重复 START 读取

1. 将代码保存为临时的 `i2c_host_fake.c`，使用本机 C11 编译器构建；仓库不把临时构建物当作课程资产。
2. 运行程序，观察两个测试函数都没有触发断言，并检查日志顺序包含 `START`、`ADDR_W_ACK`、`DATA_ACK`、`REPEATED_START`、`ADDR_R_ACK`、`READ_BYTE_NACK`、`STOP`、`IDLE`。
3. 手工解释：为什么读取最后一个字节是 NACK，而不是 ACK？如果把它改成 ACK，状态机还缺少哪一个“继续请求/结束”决策？

预期是“逻辑断言通过”；如果实际执行，请把命令、编译器版本和输出另存为运行证据。本课当前没有该证据。

### 实验 B：地址不匹配 NACK

1. 把 `slave.reject_address` 保持为 `true`，运行 `test_address_nack_and_recovery`。
2. 确认日志包含 `ADDR_W_NACK`，结果为 `I2C_ERR_ADDRESS_NACK`，随后 `STOP` 和 `IDLE` 仍出现。
3. 把恢复用的 `i2c_stop` 删除或注释，观察下一次事务为什么会从错误状态开始；用状态字段说明“错误被记录”和“线路被释放”是两个不同动作。

### 实验 C：数据 NACK

1. 运行 `test_data_nack_and_recovery`，保持 `slave.reject_address=false`、`slave.reject_data=true`。
2. 确认地址阶段先出现 `ADDR_W_ACK`，数据阶段出现 `DATA_NACK`，结果为 `I2C_ERR_DATA_NACK`，随后 `STOP` 和 `IDLE` 仍出现。
3. 说明为什么这个故障不能再用“地址不匹配”解释。

### 实验 D：从机保持 SDA 低导致超时

1. 将 `slave.hold_sda_low` 设为 `true`，执行正常读取。
2. 确认结果为 `I2C_ERR_TIMEOUT`，而不是成功返回全零数据。
3. 讨论真实硬件中还应观察什么：SDA/SCL 实际电平、超时计数、外设错误标志和是否需要总线恢复。不要在没有目标系列资料时填写寄存器位名称。

### 实验 E：扩展到多字节读

在不引入新架构概念的前提下，把 `read_length` 扩展为 3：前两个接收字节由主机发送 ACK，最后一个发送 NACK。为 `rx_count` 增加容量断言，并在日志中记录 `READ_BYTE_ACK` 与 `READ_BYTE_NACK`。这一步用于验证“ACK 表示继续，最后 NACK 表示结束”的不变量。

## 13. 自检题

1. 为什么本课的线路模型只允许“拉低”或“释放”，而不让主机和从机分别输出高/低再做普通逻辑或？
2. 一次写事务中，地址阶段 NACK 与第二个数据字节 NACK 的诊断信息有什么不同？
3. `I2cSlaveScript` 为什么是注入点？如果把从机响应直接写死在主机函数里，测试会失去什么能力？
4. 读取一个字节时，为什么主机在收到最后一个字节后发送 NACK？
5. `STOP` 后软件字段显示 `IDLE`，但实际 SDA 仍为低，为什么不能返回成功？
6. 哪些信息是 Host Fake 能验证的，哪些信息必须等到具体 STM32 板卡和测量证据？

参考答案要点：共享线路需要可组合的拉低/释放语义；地址 NACK 发生在设备选择阶段，数据 NACK 发生在内容阶段；脚本注入使响应和故障可控；最后 NACK 表示不再请求；实际线低说明事务边界没有真正释放；Host Fake 只证明逻辑状态流，不证明电气、引脚、时序和外设实现。

## 14. 面试题

1. 请画出一次“写寄存器后重复 START 读数据”的 I2C 时序，并说明每个 ACK/NACK 的产生者。
2. I2C 的 7 位地址和带读写位的地址字节有什么区别？如何避免驱动和调用者重复移位？
3. 如果总线一直忙，软件应该立即重试、发送 STOP，还是报告错误？请从线路所有权、超时和恢复证据说明决策条件。
4. 在 Host Fake 中，怎样证明一次成功事务一定以 STOP 和 `IDLE` 结束？请指出断言和日志中的证据。
5. 为什么“能在主机上通过断言”不能作为“STM32 I2C 已经工作”的结论？至少列出三类需要重新核对或测量的事实。

## 15. 延伸思考

- 如何在不改变高层事务状态机的情况下，把轮询式 `i2c_send_address` 换成中断驱动？哪些对象的生命周期和调用返回时机必须重新定义？
- 多字节读取、设备内部地址宽度和页写入会增加哪些输入约束，但为什么仍可复用 START、地址、ACK/NACK、STOP 的主状态机？
- 若从机在 SCL 被拉低时延长等待，Host Fake 应增加哪一种“线路观察”和超时事件？哪些 STM32 标志语义必须先查手册？
- 当总线上存在多个主机时，谁可能在同一时间改变 SDA？“仲裁”会怎样影响本课的单主机假设？本课为什么把它留作待核对扩展？
- 选择 F4、F7、H5、H7 中的一个具体系列后，如何把本课每一条适配清单变成带文档页码、代码版本和测量结果的证据表？

## 16. 本节总结

I2C 的可迁移核心不是某个 HAL 函数，而是一个由共享 SDA/SCL 线路承载的事务状态机：主机用 START 取得边界，发送 7 位地址和方向，从机或主机在每个字节后用 ACK/NACK 表达继续或结束，读写可以用重复 START 连接，最后用 STOP 释放总线。Host Fake 通过“拉低/释放”的线路模型、可注入的从机脚本、事件日志、断言和故障注入，把这条调用流变成可观察证据。

真实 STM32 适配时，必须把状态表逐项映射到目标系列的 I2C、GPIO 和 HAL/LL 文档，并用实际线路测量补足 Host Fake 无法证明的电气事实。本课没有板卡、构建日志或测量记录，所以不提高硬件验证状态，也不把课程生成视为掌握证据。

## 17. 下一步

先完成本课的 Host Fake 实验并能解释每条日志，再进入下一项计划主题。若要上板，先补充具体 STM32 系列、器件、开发板、调试器和测量工具，再建立一个只包含目标实例、引脚、上拉和时序证据的适配记录；在此之前保持 `hardware_verified=false`。

## 18. 参考资料

- [S1] STMicroelectronics，*STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 advanced Arm-based 32-bit MCUs - Reference manual*，RM0090 Rev 22，重点：I2C 外设、GPIO 和错误/状态描述。https://www.st.com/resource/en/reference_manual/dm00031020.pdf
- [S2] STMicroelectronics，*UM1725 Description of STM32F4 HAL and low-layer drivers*，Rev 8，重点：STM32F4 I2C HAL/LL 驱动接口与调用契约。https://www.st.com/resource/en/user_manual/dm00105879.pdf

来源访问日期和第一方属性已写入同目录 `lesson.json`。RM0090/UM1725 的 STM32F4 范围不能直接证明 F7、H5 或 H7 的寄存器和 API 相同；跨系列结论均需重新核对。

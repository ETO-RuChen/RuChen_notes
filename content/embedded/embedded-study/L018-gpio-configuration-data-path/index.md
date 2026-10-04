+++
title = "GPIO 配置状态与引脚数据通路：从 Host Fake 到 STM32 资料核对"
date = "2026-10-04T14:55:13+08:00"
lastmod = "2026-10-04T14:55:13+08:00"
summary = "把 GPIO 理解为配置状态决定数据通路、数据访问读取输入采样或更新输出锁存的外设边界，并用静态 Host Fake 区分输入、推挽输出、开漏释放和非法配置；结果不代表真实 STM32 寄存器、电气测量或上板验证。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 18
tags = ["gpio", "configuration", "input-sampling", "output-latch", "push-pull", "open-drain", "host-fake", "c11", "beginner"]
source_ids = ["st-an4899-2026-pdf", "st-pm0214-rev10"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L018"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 18 课：GPIO 配置状态与引脚数据通路

同一个引脚为什么有时能读到外部输入，有时却读回自己写入的输出值？为什么写一个数据位不能把引脚变成输出？为什么开漏输出写入“1”时，不能直接把它说成引脚上出现了高电平？

本课只推进一个核心概念：**GPIO 配置状态与引脚数据通路的分离**。先用普通 Windows 主机上的 Host Fake（主机伪实现）观察确定结果，再把结果迁移到 STM32 的资料核对流程。Host Fake 不访问真实地址、不模拟电压、时序、同步器或寄存器副作用；没有具体开发板、目标构建、下载和测量记录，因此 `hardware_verified=false`。

## 1. 本节目标

本课的核心目标与学习计划一致：

> 学习者能把 GPIO（General-Purpose Input/Output，通用输入输出）理解为“配置状态决定引脚数据通路、数据访问读取或更新当前通路状态”的外设边界，并能用受控的 Host Fake 判断输入采样、输出锁存和非法配置之间的可观察差异。

完成后应能：

- 区分配置动作和数据动作，不把“写数据”误认为“配置方向”；
- 区分输入采样、输出锁存、开漏释放和外部电平；
- 说明端口、引脚、模式、上下拉、复用选择等对象在模型中的定义位置与持有者；
- 运行或检查一个无动态内存的 C11 子集 Host Fake，观察有效输入、推挽输出、开漏限制、非法模式和越界引脚；
- 说明 Host Fake 能证明哪些逻辑关系，不能证明哪些 STM32 电气或寄存器事实；
- 面向 F4、F7、H5、H7 使用同一套“先查资料、再看配置/数据路径、最后收集构建与测量证据”的方法。

本课唯一的新核心概念是：

> **GPIO 配置状态与引脚数据通路的分离**

`.MODER`、`.OTYPER`、`.OSPEEDR`、`.PUPDR`、复用选择、输入数据寄存器、输出数据寄存器、BSRR、推挽、开漏、上拉、下拉、采样延迟和去抖，都是服务上述模型的辅助术语，不是额外的课程目标。具体字段、复位值、读写限制和电气含义必须按目标器件资料核对。

## 2. 它解决什么问题

GPIO 不是只有一个“电平变量”。至少要分别追踪两组状态：

| 状态 | 回答的问题 | Host Fake 中的表示 |
| --- | --- | --- |
| 配置状态 | 这条引脚数据通路是什么模式？谁能驱动它？是否有内部偏置？ | `mode`、`pull` |
| 数据访问状态 | 软件写入的保持值是什么？输入路径最近采样到什么？ | `output_latch`、`input_sample` |

因此下面这些说法都不完整：

- “写 `1` 就把引脚变成高电平”：没有说明模式，也没有区分输出锁存和外部电平。
- “读到了 `0`，所以外部一定是低电压”：没有说明当前是输入采样、推挽回读，还是开漏释放后的未知外部状态。
- “配置成输出后写一次就够了”：没有说明输出级是推挽还是开漏，以及外部上拉、负载和电气限制。
- “端口的第 3 位一定能复用成某个外设”：复用表和封装限制由具体数据手册决定。

可迁移的问题拆成四步：

1. 当前配置对象允许哪条数据通路？
2. 软件正在访问输入采样、输出锁存，还是原子置位/清除等等价数据接口？
3. 这个访问结果是否代表外部引脚电平，还是只代表模型内部状态？
4. 哪一份参考手册、数据手册、HAL/LL 文档或测量记录能证明结论？

ST 的 AN4899 介绍 STM32 GPIO 的配置方式以及推挽、开漏、上下拉等硬件设置，并强调 GPIO 设置会影响外部接口和功耗。[1] 该资料不是某个具体型号的参考手册，不能单独给出端口地址、位字段、复位值、输入阈值或某个封装的复用表。

## 3. 必要前置知识

本课只承接 `config/learning-state.toml` 中已完成的内容：

1. C 基本对象、整数、指针、`const`/`volatile`、存储期和链接关系；能读懂固定宽度整数和简单结构体。
2. 编译器、构建产物和静态分析的基本闭环；知道 Host C11 程序可以用退出码和文本输出验证逻辑。
3. 启动、链接脚本、ELF/map 与存储器布局的证据意识；知道真实外设地址和字段必须由目标资料核对，不能从主机地址猜测。

本课不假定已经掌握具体 STM32 型号、GPIO 端口地址、寄存器位定义、CubeMX 生成代码、HAL/LL 函数签名、开发板连线、时钟树、示波器或逻辑分析仪。也不进入 EXTI、中断优先级、定时器、UART、DMA、RTOS 或驱动架构。

## 4. 核心原理

### 4.1 先看最小可观察结果

把一个端口想成四个引脚，初始都处于 `UNCONFIGURED`：

```text
pin 0: 配置 INPUT       -> 注入外部采样 HIGH -> 读取 HIGH
pin 1: 配置 PUSH_PULL   -> 写输出锁存 HIGH   -> 读取锁存 HIGH
pin 2: 配置 OPEN_DRAIN  -> 写入 HIGH（释放） -> 外部电平 UNKNOWN
pin 3: 未配置           -> 尝试写入          -> 拒绝
pin 4: 不存在           -> 尝试配置          -> 拒绝越界
```

这几行已经说明核心分离：配置先决定允许哪一类访问；数据动作只能沿已建立的通路运行。模型中的 `HIGH` 是逻辑状态，不是电压测量。

### 4.2 配置状态和数据访问状态

可以把 GPIO 抽象成两层：

```text
配置层：mode / output_type / pull / alternate_function / 其他器件字段
             |
             v
数据通路：外部引脚 -> 输入采样 -> 软件读取
                         ^
软件写入 -> 输出锁存 -> 输出级 -> 外部引脚
```

推挽输出通常可以主动驱动低和高；开漏输出常见的抽象是“主动拉低，写高表示释放”，释放后外部电平取决于外部上拉、其他驱动者和器件电气规则。这里的“通常”和“常见”不是对所有 STM32 系列的无条件承诺，具体行为必须以目标器件资料为准。[1]

输入采样是外部引脚经过输入路径后的软件可见值。采样同步、延迟、施密特输入、输入阈值和模拟模式下的行为都可能随器件和配置改变；本课只把它们标成待核对，不用 Host Fake 代替电气测量。

### 4.3 解决什么问题、对象在哪里、谁持有、谁建立、怎样流动

| 对象 | 在哪里定义 | 谁持有 | 谁建立/注入 | 调用或数据流动 |
| --- | --- | --- | --- | --- |
| 端口和引脚编号 | 目标器件资料；Host Fake 的类型定义 | 外设实例；Host Fake 由端口对象持有 | 目标硬件固定；测试代码创建 Host Fake 端口 | 上层选择端口和引脚编号 |
| 配置字段 | 具体参考手册/HAL 文档；Host Fake 的 `gpio_fake_pin_t` | GPIO 外设或模型端口 | 复位后软件配置；Host Fake 由 `gpio_fake_configure()` 写入 | 配置动作建立允许的数据通路 |
| 输入采样 | 目标输入路径；Host Fake 的 `input_sample` | GPIO 输入路径或模型引脚 | 外部电平经过硬件采样；Host Fake 测试调用 `gpio_fake_set_external_sample()` 注入 | 读取动作从采样状态返回逻辑值 |
| 输出锁存 | 目标数据寄存器/等价机制；Host Fake 的 `output_latch` | GPIO 输出路径或模型引脚 | 软件写数据接口；Host Fake 由 `gpio_fake_write_latch()` 更新 | 锁存值经过输出级影响外部引脚 |
| 外部电平 | 由真实连线、负载和电气状态决定；Host Fake 不保存真实电压 | 目标电路网络 | 外部电路、上拉或其他驱动者共同决定 | 测量设备或输入路径观察它 |

在真实工程里，调用流可以写成：

```text
应用意图
  -> 项目 GPIO 包装或 HAL/LL 调用（版本待核对）
  -> 外设配置/数据寄存器（字段和地址待核对）
  -> GPIO 输入/输出路径
  -> 真实引脚与外部电路
  -> 输入采样或测量结果
```

Host Fake 只实现这条链中“配置约束 + 状态转换”的逻辑部分，不声称执行了寄存器访问，也不声称测得了电压。

### 4.4 声明、实现、实例化、组装和使用

本课不是架构课，但为了保持边界清楚，把示例中的五个动作分开：

1. **声明**：代码声明 `gpio_fake_pin_t`、`gpio_fake_port_t`、状态码和函数原型；真实工程中的寄存器字段和 HAL 参数则由目标资料定义。
2. **实现**：代码实现模式检查、边界检查、输入读取和输出锁存更新；真实工程由 HAL/LL 或直接寄存器代码实现对应动作，具体方式待核对。
3. **实例化**：`main` 中的 `static gpio_fake_port_t port` 是一个具体端口模型实例；它不是某个 STM32 端口地址。
4. **组装**：`gpio_fake_port_init(&port, 4U)` 把四个引脚纳入模型，并由测试依次注入配置和外部采样。
5. **使用**：测试代码调用配置、写入、读取函数并检查状态码。真实 App 使用时，应先完成目标器件要求的时钟和引脚配置，再调用对应数据接口；具体顺序和 API 待核对。

这里的“注入”只表示测试把已知采样值放入 Host Fake；不是后续驱动架构课程中的依赖注入模式。

## 5. 关键术语与直观模型

| 术语 | 本课中的准确含义 |
| --- | --- |
| GPIO | 可按配置承担数字输入、数字输出或复用功能的外设接口；“通用”不表示所有引脚能力相同。 |
| 端口（port） | 一组相关数字通道的外设边界；数量、宽度和可用性由器件资料决定。 |
| 引脚（pin） | 端口中的一个数字通道编号；编号不等于封装管脚号。 |
| 配置状态 | 决定数据通路和电气行为的字段集合，不等同于当前逻辑电平。 |
| 输入采样 | 外部引脚状态经过输入路径后可被软件读取的抽象值。 |
| 输出锁存 | 软件写入并保持在输出路径中的逻辑值；不自动等同于外部测得的电压。 |
| 推挽（push-pull） | 常见的主动驱动高、低两种逻辑状态的输出级语义；驱动能力和限制待按器件核对。 |
| 开漏（open-drain） | 常见的主动拉低、释放高电平路径的输出级语义；释放后的电平需要外部上拉或其他电路条件。 |
| 上拉/下拉（pull-up/pull-down） | 输入或输出路径上的内部偏置选项；阻值、启用条件和默认状态待核对。 |
| 复用功能（alternate function） | 把引脚数据通路交给片上其他外设；具体选择表待按型号核对。 |
| HAL | Hardware Abstraction Layer，硬件抽象层；具体 API、参数检查和寄存器顺序需按版本核对。 |
| Host Fake | 用静态 C11 数据结构模拟逻辑状态和错误分支，不模拟真实寄存器、电压、时序或波形。 |
| 去抖（debounce） | 针对机械输入短时抖动的过滤策略，本课只把它作为后续可靠性问题。 |

模型状态可以压缩为：

```text
配置状态       数据访问状态               真实世界边界
-----------    ----------------------    -------------------------
mode           input_sample              外部电压/负载/上拉
pull           output_latch              引脚复用与封装限制
output type    读取权限与写入权限         采样时序与电气额定值
```

## 6. 从输入到结果的完整流程

### 6.1 Host Fake 流程

1. `main` 持有静态端口模型，端口记录可用引脚数量。
2. `gpio_fake_configure` 检查引脚编号和模式，再写入配置状态。
3. 输入测试通过 `gpio_fake_set_external_sample` 注入一个逻辑采样值；这相当于测试替代了真实外部电路。
4. 读取函数根据当前模式选择输入采样、输出锁存或拒绝分支。
5. 输出测试先更新锁存值，再读取模型中的输出逻辑状态。
6. 开漏释放、未配置、非法模式和越界引脚都返回确定错误；错误码不是电压。

### 6.2 真实 STM32 工程的核对流程

1. 记录完整 MCU 型号、封装、开发板、工具链和 Cube 固件包版本。
2. 查该型号 Reference Manual（参考手册），确认 GPIO 时钟、端口寄存器、模式字段、复位值、数据访问和复用选择；没有型号时不填写寄存器地址。
3. 查该型号 Datasheet（数据手册），确认输入阈值、输出能力、上拉/下拉限制、复用管脚和绝对最大额定值；AN4899 的一般建议不能替代型号数据。
4. 查同一版本的 HAL/LL 文档和生成工程，确认初始化参数、读写 API、错误返回和是否使用置位/清除等机制；版本未知时不写死函数签名。
5. 检查构建产物和调试器观察，确认配置代码确实进入目标工程；这仍是构建/调试证据，不是电压测量。
6. 若要证明边沿、上拉、抖动或波形，再记录探头、连线、采样率和示波器/逻辑分析仪数据。

### 6.3 模型状态和真实测量的边界

| 观察结果 | Host Fake 能证明 | Host Fake 不能证明 |
| --- | --- | --- |
| 输入返回 `HIGH` | 给定配置下，注入的 `input_sample` 被返回 | 真实引脚达到了 VIH，或采样时序满足目标要求 |
| 推挽写入后返回 `HIGH` | `output_latch` 被更新并可回读 | 真实引脚驱动了高电平、负载未超限或波形正确 |
| 开漏释放返回未知 | 模型拒绝把释放状态宣称为外部高电平 | 外部上拉阻值、总线竞争和实际电压 |
| 非法模式/引脚返回错误 | 边界检查是确定的 | 芯片是否也用相同错误码，或总线是否产生异常 |

## 7. 嵌入式系统中的对应位置

### 7.1 可迁移的方法

面对 STM32F4、F7、H5 或 H7，可迁移的是方法，不是某组地址：

```text
确定型号和版本
  -> 读 Reference Manual / Datasheet
  -> 分离配置字段与数据访问
  -> 检查初始化和调用流
  -> 用构建、调试和测量证据闭环
```

F4、F7、H5、H7 的端口数量、字段组织、复位值、复用表、电气限制和 HAL/LL 包版本可能不同。当前来源和输入条件不足以给出这些系列差异的具体表格，均标为“待核对”。不能把 F4 的某个寄存器名称、地址或默认状态外推到 F7、H5、H7。

### 7.2 复位、时钟和复用的责任边界

真实 GPIO 往往还需要外设时钟处于可用状态，并按器件要求完成模式、输出类型、速度、电阻和复用选择。是否必须先做哪一步、时钟门控在哪个总线、某些引脚能否在低功耗下保持状态，必须从对应参考手册和数据手册核对。这里不提供虚构的时钟位、寄存器地址或引脚号。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 能证明什么

- 端口只接受已声明的引脚编号；越界访问进入确定错误分支；
- 模式值经过白名单检查，未允许模式不会改变配置状态；
- 输入模式读取的是注入的 `input_sample`；
- 推挽模式写入后更新 `output_latch` 并可回读；
- 开漏模式写入“释放”后不把外部高电平作为已知事实返回；
- 未配置或输入模式下的非法写入被拒绝；
- 模型使用静态存储和固定宽度整数，不申请动态内存，也不解引用虚拟地址。

### 8.2 Host Fake 不能证明什么

- 不能证明任何 STM32 GPIO 寄存器地址、位宽、复位值或 HAL 内部顺序；
- 不能证明某个封装上的管脚存在或支持某个复用功能；
- 不能证明内部上拉/下拉的阻值、输入阈值、输出驱动能力或功耗；
- 不能证明真实采样延迟、同步、竞争、去抖、边沿或波形；
- 不能替代交叉编译、下载、调试器观察、示波器或逻辑分析仪记录。

## 9. 最小代码示例

下面的代码是一个单文件 Host Fake 示例，遵循 C11 子集；它是课程中的逻辑模型，**示例，待目标构建与上板验证**。为便于普通 Windows 主机运行，`main` 只使用 `stdio.h` 输出结果；模型本身不访问地址、不使用动态内存。

### 9.1 完整代码

```c
#include <stdint.h>
#include <stdio.h>

#define GPIO_FAKE_MAX_PINS (8U)

typedef uint8_t gpio_fake_mode_t;
typedef uint8_t gpio_fake_pull_t;
typedef uint8_t gpio_fake_level_t;
typedef int32_t gpio_fake_status_t;

#define GPIO_FAKE_MODE_UNCONFIGURED ((gpio_fake_mode_t)0U)
#define GPIO_FAKE_MODE_INPUT        ((gpio_fake_mode_t)1U)
#define GPIO_FAKE_MODE_PUSH_PULL    ((gpio_fake_mode_t)2U)
#define GPIO_FAKE_MODE_OPEN_DRAIN   ((gpio_fake_mode_t)3U)

#define GPIO_FAKE_PULL_NONE         ((gpio_fake_pull_t)0U)
#define GPIO_FAKE_PULL_UP           ((gpio_fake_pull_t)1U)
#define GPIO_FAKE_PULL_DOWN         ((gpio_fake_pull_t)2U)

#define GPIO_FAKE_LOW  ((gpio_fake_level_t)0U)
#define GPIO_FAKE_HIGH ((gpio_fake_level_t)1U)

#define GPIO_FAKE_OK                         ((gpio_fake_status_t)0)
#define GPIO_FAKE_ERR_ARGUMENT               ((gpio_fake_status_t)-1)
#define GPIO_FAKE_ERR_INVALID_PIN            ((gpio_fake_status_t)-2)
#define GPIO_FAKE_ERR_INVALID_MODE           ((gpio_fake_status_t)-3)
#define GPIO_FAKE_ERR_UNCONFIGURED           ((gpio_fake_status_t)-4)
#define GPIO_FAKE_ERR_NOT_INPUT              ((gpio_fake_status_t)-5)
#define GPIO_FAKE_ERR_NOT_OUTPUT             ((gpio_fake_status_t)-6)
#define GPIO_FAKE_ERR_OPEN_DRAIN_EXTERNAL    ((gpio_fake_status_t)-7)
#define GPIO_FAKE_ERR_INVALID_PULL           ((gpio_fake_status_t)-8)
#define GPIO_FAKE_ERR_INVALID_LEVEL          ((gpio_fake_status_t)-9)

typedef struct {
    gpio_fake_mode_t mode;
    gpio_fake_pull_t pull;
    gpio_fake_level_t output_latch;
    gpio_fake_level_t input_sample;
} gpio_fake_pin_t;

typedef struct {
    uint8_t pin_count;
    gpio_fake_pin_t pins[GPIO_FAKE_MAX_PINS];
} gpio_fake_port_t;

static int gpio_fake_valid_mode(gpio_fake_mode_t mode)
{
    return (mode == GPIO_FAKE_MODE_UNCONFIGURED) ||
           (mode == GPIO_FAKE_MODE_INPUT) ||
           (mode == GPIO_FAKE_MODE_PUSH_PULL) ||
           (mode == GPIO_FAKE_MODE_OPEN_DRAIN);
}

static int gpio_fake_valid_pull(gpio_fake_pull_t pull)
{
    return (pull == GPIO_FAKE_PULL_NONE) ||
           (pull == GPIO_FAKE_PULL_UP) ||
           (pull == GPIO_FAKE_PULL_DOWN);
}

static int gpio_fake_valid_level(gpio_fake_level_t level)
{
    return (level == GPIO_FAKE_LOW) || (level == GPIO_FAKE_HIGH);
}

static int gpio_fake_valid_pin(const gpio_fake_port_t *port, uint8_t pin)
{
    return (port != NULL) && (pin < port->pin_count) &&
           (pin < GPIO_FAKE_MAX_PINS);
}

gpio_fake_status_t gpio_fake_port_init(gpio_fake_port_t *port,
                                       uint8_t pin_count)
{
    uint8_t i;

    if ((port == NULL) || (pin_count == 0U) ||
        (pin_count > GPIO_FAKE_MAX_PINS)) {
        return GPIO_FAKE_ERR_ARGUMENT;
    }

    port->pin_count = pin_count;
    for (i = 0U; i < GPIO_FAKE_MAX_PINS; ++i) {
        port->pins[i].mode = GPIO_FAKE_MODE_UNCONFIGURED;
        port->pins[i].pull = GPIO_FAKE_PULL_NONE;
        port->pins[i].output_latch = GPIO_FAKE_LOW;
        port->pins[i].input_sample = GPIO_FAKE_LOW;
    }
    return GPIO_FAKE_OK;
}

gpio_fake_status_t gpio_fake_configure(gpio_fake_port_t *port,
                                       uint8_t pin,
                                       gpio_fake_mode_t mode,
                                       gpio_fake_pull_t pull)
{
    if (!gpio_fake_valid_pin(port, pin)) {
        return GPIO_FAKE_ERR_INVALID_PIN;
    }
    if (!gpio_fake_valid_mode(mode)) {
        return GPIO_FAKE_ERR_INVALID_MODE;
    }
    if (!gpio_fake_valid_pull(pull)) {
        return GPIO_FAKE_ERR_INVALID_PULL;
    }
    port->pins[pin].mode = mode;
    port->pins[pin].pull = pull;
    return GPIO_FAKE_OK;
}

/* 测试代码用它替代真实外部电路；只允许在输入模式下注入采样。 */
gpio_fake_status_t gpio_fake_set_external_sample(gpio_fake_port_t *port,
                                                 uint8_t pin,
                                                 gpio_fake_level_t level)
{
    if (!gpio_fake_valid_pin(port, pin)) {
        return GPIO_FAKE_ERR_INVALID_PIN;
    }
    if (!gpio_fake_valid_level(level)) {
        return GPIO_FAKE_ERR_INVALID_LEVEL;
    }
    if (port->pins[pin].mode != GPIO_FAKE_MODE_INPUT) {
        return GPIO_FAKE_ERR_NOT_INPUT;
    }
    port->pins[pin].input_sample = level;
    return GPIO_FAKE_OK;
}

gpio_fake_status_t gpio_fake_write_latch(gpio_fake_port_t *port,
                                         uint8_t pin,
                                         gpio_fake_level_t level)
{
    gpio_fake_mode_t mode;

    if (!gpio_fake_valid_pin(port, pin)) {
        return GPIO_FAKE_ERR_INVALID_PIN;
    }
    if (!gpio_fake_valid_level(level)) {
        return GPIO_FAKE_ERR_INVALID_LEVEL;
    }
    mode = port->pins[pin].mode;
    if (mode == GPIO_FAKE_MODE_UNCONFIGURED) {
        return GPIO_FAKE_ERR_UNCONFIGURED;
    }
    if (mode == GPIO_FAKE_MODE_INPUT) {
        return GPIO_FAKE_ERR_NOT_OUTPUT;
    }
    if ((mode != GPIO_FAKE_MODE_PUSH_PULL) &&
        (mode != GPIO_FAKE_MODE_OPEN_DRAIN)) {
        return GPIO_FAKE_ERR_INVALID_MODE;
    }
    port->pins[pin].output_latch = level;
    return GPIO_FAKE_OK;
}

/* 读取的是模型中的逻辑结果，不是主机电压，也不是 STM32 寄存器读回。 */
gpio_fake_status_t gpio_fake_read_logic(const gpio_fake_port_t *port,
                                        uint8_t pin,
                                        gpio_fake_level_t *level)
{
    gpio_fake_mode_t mode;

    if (level == NULL) {
        return GPIO_FAKE_ERR_ARGUMENT;
    }
    if (!gpio_fake_valid_pin(port, pin)) {
        return GPIO_FAKE_ERR_INVALID_PIN;
    }
    mode = port->pins[pin].mode;
    if (mode == GPIO_FAKE_MODE_UNCONFIGURED) {
        return GPIO_FAKE_ERR_UNCONFIGURED;
    }
    if (mode == GPIO_FAKE_MODE_INPUT) {
        *level = port->pins[pin].input_sample;
        return GPIO_FAKE_OK;
    }
    if (mode == GPIO_FAKE_MODE_PUSH_PULL) {
        *level = port->pins[pin].output_latch;
        return GPIO_FAKE_OK;
    }
    if (mode == GPIO_FAKE_MODE_OPEN_DRAIN) {
        if (port->pins[pin].output_latch == GPIO_FAKE_LOW) {
            *level = GPIO_FAKE_LOW;
            return GPIO_FAKE_OK;
        }
        /* 写入 HIGH 只表示释放；外部网络未建模，所以不能宣称 HIGH。 */
        return GPIO_FAKE_ERR_OPEN_DRAIN_EXTERNAL;
    }
    return GPIO_FAKE_ERR_INVALID_MODE;
}

static const char *gpio_fake_status_name(gpio_fake_status_t status)
{
    switch (status) {
    case GPIO_FAKE_OK:                      return "OK";
    case GPIO_FAKE_ERR_INVALID_PIN:         return "INVALID_PIN";
    case GPIO_FAKE_ERR_INVALID_MODE:        return "INVALID_MODE";
    case GPIO_FAKE_ERR_UNCONFIGURED:        return "UNCONFIGURED";
    case GPIO_FAKE_ERR_NOT_INPUT:           return "NOT_INPUT";
    case GPIO_FAKE_ERR_NOT_OUTPUT:          return "NOT_OUTPUT";
    case GPIO_FAKE_ERR_OPEN_DRAIN_EXTERNAL: return "OPEN_DRAIN_EXTERNAL_UNKNOWN";
    case GPIO_FAKE_ERR_INVALID_PULL:        return "INVALID_PULL";
    case GPIO_FAKE_ERR_INVALID_LEVEL:       return "INVALID_LEVEL";
    default:                                return "ARGUMENT_OR_OTHER_ERROR";
    }
}

static const char *gpio_fake_level_name(gpio_fake_level_t level)
{
    return (level == GPIO_FAKE_HIGH) ? "HIGH" : "LOW";
}

static int expect_status(const char *label,
                         gpio_fake_status_t actual,
                         gpio_fake_status_t expected)
{
    if (actual != expected) {
        printf("FAIL %s actual=%s expected=%s\n",
               label, gpio_fake_status_name(actual),
               gpio_fake_status_name(expected));
        return 1;
    }
    printf("PASS %s status=%s\n", label, gpio_fake_status_name(actual));
    return 0;
}

int main(void)
{
    static gpio_fake_port_t port;
    gpio_fake_level_t level = GPIO_FAKE_LOW;
    gpio_fake_status_t status;
    int failures = 0;

    failures += expect_status("port_init", gpio_fake_port_init(&port, 4U),
                             GPIO_FAKE_OK);

    failures += expect_status("input_config",
        gpio_fake_configure(&port, 0U, GPIO_FAKE_MODE_INPUT,
                            GPIO_FAKE_PULL_UP), GPIO_FAKE_OK);
    failures += expect_status("input_sample_injection",
        gpio_fake_set_external_sample(&port, 0U, GPIO_FAKE_HIGH),
        GPIO_FAKE_OK);
    status = gpio_fake_read_logic(&port, 0U, &level);
    failures += expect_status("input_read", status, GPIO_FAKE_OK);
    if ((status == GPIO_FAKE_OK) && (level != GPIO_FAKE_HIGH)) {
        printf("FAIL input_read level=%s expected=HIGH\n",
               gpio_fake_level_name(level));
        ++failures;
    }

    failures += expect_status("push_pull_config",
        gpio_fake_configure(&port, 1U, GPIO_FAKE_MODE_PUSH_PULL,
                            GPIO_FAKE_PULL_NONE), GPIO_FAKE_OK);
    failures += expect_status("push_pull_write",
        gpio_fake_write_latch(&port, 1U, GPIO_FAKE_HIGH), GPIO_FAKE_OK);
    status = gpio_fake_read_logic(&port, 1U, &level);
    failures += expect_status("push_pull_read", status, GPIO_FAKE_OK);
    if ((status == GPIO_FAKE_OK) && (level != GPIO_FAKE_HIGH)) {
        printf("FAIL push_pull_read level=%s expected=HIGH\n",
               gpio_fake_level_name(level));
        ++failures;
    }

    failures += expect_status("open_drain_config",
        gpio_fake_configure(&port, 2U, GPIO_FAKE_MODE_OPEN_DRAIN,
                            GPIO_FAKE_PULL_NONE), GPIO_FAKE_OK);
    failures += expect_status("open_drain_release_write",
        gpio_fake_write_latch(&port, 2U, GPIO_FAKE_HIGH), GPIO_FAKE_OK);
    failures += expect_status("open_drain_external_level",
        gpio_fake_read_logic(&port, 2U, &level),
        GPIO_FAKE_ERR_OPEN_DRAIN_EXTERNAL);

    failures += expect_status("unconfigured_write",
        gpio_fake_write_latch(&port, 3U, GPIO_FAKE_HIGH),
        GPIO_FAKE_ERR_UNCONFIGURED);
    failures += expect_status("invalid_pin",
        gpio_fake_configure(&port, 4U, GPIO_FAKE_MODE_INPUT,
                            GPIO_FAKE_PULL_NONE), GPIO_FAKE_ERR_INVALID_PIN);
    failures += expect_status("invalid_mode",
        gpio_fake_configure(&port, 0U, (gpio_fake_mode_t)99U,
                            GPIO_FAKE_PULL_NONE), GPIO_FAKE_ERR_INVALID_MODE);
    failures += expect_status("invalid_pull",
        gpio_fake_configure(&port, 0U, GPIO_FAKE_MODE_INPUT,
                            (gpio_fake_pull_t)99U), GPIO_FAKE_ERR_INVALID_PULL);
    failures += expect_status("invalid_level",
        gpio_fake_write_latch(&port, 1U, (gpio_fake_level_t)2U),
        GPIO_FAKE_ERR_INVALID_LEVEL);

    printf("logical verification: %s\n",
           (failures == 0) ? "PASS" : "FAIL");
    return (failures == 0) ? 0 : 1;
}
```

### 9.2 代码如何体现核心模型

- `gpio_fake_pin_t` 同时保存配置字段和数据访问状态，但字段语义仍然分开；修改 `mode` 不会自动修改 `output_latch`，写 `output_latch` 也不会修改 `mode`。
- `gpio_fake_configure` 是配置动作；`gpio_fake_set_external_sample` 是测试对输入采样的注入；`gpio_fake_write_latch` 是数据动作；`gpio_fake_read_logic` 根据模式决定读取来源或拒绝访问。
- `static gpio_fake_port_t port` 是实例的持有者；函数只通过显式指针访问它，不保存全局动态资源。
- `GPIO_FAKE_MAX_PINS`、`pin_count`、`gpio_fake_valid_pin` 以及 mode/pull/level 白名单共同构成 Host Fake 的边界契约。数值 `4U` 和 `8U` 只是模型容量，不是 STM32 端口宽度。
- 开漏写入 `HIGH` 的意义是释放输出级；因为模型没有外部上拉和总线参与者，读取返回 `GPIO_FAKE_ERR_OPEN_DRAIN_EXTERNAL`，而不是伪造 `HIGH`。

### 9.3 Windows 主机运行方式

把代码保存为 `gpio_fake.c` 后，可使用本机已有的 GCC 或 Clang：

```powershell
gcc -std=c11 -Wall -Wextra -Wpedantic -Werror gpio_fake.c -o gpio_fake.exe
./gpio_fake.exe
```

或：

```powershell
clang -std=c11 -Wall -Wextra -Wpedantic -Werror gpio_fake.c -o gpio_fake.exe
./gpio_fake.exe
```

只有实际记录了编译器版本、命令、编译退出码、程序退出码和完整输出，才能声称这次主机构建成功。本课程文件没有附带本次运行的构建记录，因此代码应视为“示例，待运行”；即使主机构建成功，也只证明模型逻辑，不证明 STM32 硬件。

## 10. 常见错误

### 10.1 只写数据，不先配置模式

输入模式、推挽输出、开漏输出和复用功能的通路不同。应先确认配置状态，再执行数据访问；若配置仍是未配置或输入，Host Fake 会拒绝输出写入。

### 10.2 把输出锁存当成外部电平

锁存值是软件写入的保持状态。外部电平还受到输出类型、负载、上拉、其他驱动者和电气限制影响。尤其在开漏释放状态，锁存值为 `HIGH` 不等于外部网络为高电平。

### 10.3 把读回值都叫作输入采样

模型中输入模式读取 `input_sample`，推挽模式读取 `output_latch`。真实器件的数据寄存器读语义、回读路径和复用行为必须按参考手册核对，不能凭寄存器简称猜测。

### 10.4 把编号当成封装管脚

`port=某端口、pin=3` 是逻辑编号；封装上的具体管脚、复用能力和电气限制来自数据手册。Host Fake 的 `pin_count` 不代表某颗芯片的端口宽度。

### 10.5 把内部上拉/下拉当成精密电阻

内部偏置是配置选项，不是无条件的外部电阻替代品。阻值范围、启用条件、功耗和低功耗保持行为必须查具体型号资料。[1]

### 10.6 从一个系列外推另一个系列

F4 的参考手册、HAL 版本或复用表不能直接证明 F7、H5、H7 的行为。可迁移的是证据链：型号、版本、字段、调用、构建、测量逐项对应。

### 10.7 把 Host Fake 输出称为示波器结果

`PASS push_pull_read status=OK` 只表示模型状态转移符合预期，不表示探头测得某个电压、边沿或时序。

## 11. 调试观察点

### 11.1 先看配置，再看数据

在 `gpio_fake_read_logic` 设置断点，按以下顺序观察：

1. `pin` 是否越界；
2. `mode` 是 `INPUT`、`PUSH_PULL`、`OPEN_DRAIN` 还是 `UNCONFIGURED`；
3. 输入模式下 `input_sample` 是否由测试明确注入；
4. 输出模式下 `output_latch` 是否在写入动作后改变；
5. 开漏释放时是否走到 `GPIO_FAKE_ERR_OPEN_DRAIN_EXTERNAL`。

不要先看 `level` 再猜模式；调用流的先后关系正是本课要建立的观察习惯。

### 11.2 错误分支观察

- 把 `pin=4` 保持不变：端口只有四个有效引脚 `0..3`，应在访问数组前返回 `INVALID_PIN`。
- 把模式改为 `99U`：应在写入配置前返回 `INVALID_MODE`，原来的输入配置不应被破坏。
- 把 pull 改为 `99U` 或把逻辑值改为 `2U`：应分别返回 `INVALID_PULL` 或 `INVALID_LEVEL`，不能把未定义枚举静默写入状态。
- 对未配置的 pin 3 写入：应返回 `UNCONFIGURED`，不能因为锁存字段存在就宣称已经驱动引脚。
- 对开漏 pin 2 写入 `HIGH`：应允许更新“释放”状态，但读取外部逻辑时返回未知错误；再写 `LOW` 可观察模型把主动拉低作为确定状态。

### 11.3 迁移到真实目标的四份证据

拿到目标工程后，把同一次构建的以下证据放在一起：

1. 参考手册中的 GPIO 寄存器字段和数据通路图；
2. 数据手册中的管脚复用与电气限制；
3. 初始化代码、HAL/LL 版本和生成工程设置；
4. 调试器寄存器观察以及需要时的示波器/逻辑分析仪记录。

若只拥有 Host Fake 输出，结论停留在逻辑模型层；若没有测量记录，不报告真实电压、边沿或抖动。

## 12. 实战实验

### 实验 A：正常输入与推挽输出

目标：确认配置动作和数据动作是两个阶段。

1. 按第 9 节保存代码，记录本机编译器版本。
2. 用 `-std=c11 -Wall -Wextra -Wpedantic -Werror` 构建。
3. 运行程序，记录完整输出和两个退出码。
4. 解释为什么 pin 0 的 `HIGH` 来自 `input_sample`，pin 1 的 `HIGH` 来自 `output_latch`。

验收：能在代码中指出配置函数、采样注入函数、锁存写入函数和读取分支；不把结果称为电压测量。

### 实验 B：开漏释放与主动拉低

目标：观察“写高”与“外部高电平”之间的边界。

1. 保持 pin 2 为 `OPEN_DRAIN`。
2. 写入 `HIGH`，确认得到 `OPEN_DRAIN_EXTERNAL_UNKNOWN`。
3. 再写入 `LOW`，确认读取返回 `LOW`。
4. 解释模型为什么能对主动拉低给出确定逻辑，却不能替外部上拉作出高电平结论。

验收：答案包含“释放”“外部网络未建模”“不能宣称高电平”三个关系。

### 实验 C：非法配置和越界

目标：验证错误分支在状态改变前发生。

1. 把配置模式改为 `(gpio_fake_mode_t)99U`，确认返回 `INVALID_MODE`。
2. 把 pull 改为 `(gpio_fake_pull_t)99U`，确认返回 `INVALID_PULL`。
3. 把写入值改为 `(gpio_fake_level_t)2U`，确认返回 `INVALID_LEVEL`。
4. 把 pin 改为 `4U`，确认返回 `INVALID_PIN`。
5. 在调试器中观察 `port.pins[0].mode` 没有因非法模式或 pull 调用而被覆盖。
6. 说明为什么数组容量、有效引脚数量和枚举白名单都必须检查。

验收：没有越界访问；错误码和状态保持可重复。

### 实验 D：写一个自己的状态表

目标：把抽象模型用于新场景，而不引入真实芯片假设。

填写下表，值只允许使用“确定”“未知”“拒绝”：

| 配置 | 数据动作 | 预期模型结果 | 原因 |
| --- | --- | --- | --- |
| 输入 | 注入采样后读取 |  |  |
| 推挽输出 | 写入低后读取 |  |  |
| 开漏输出 | 写入高后读取外部电平 |  |  |
| 未配置 | 写入高 |  |  |
| 不存在的 pin | 配置输入 |  |  |

验收：每行都能分别指出配置状态、数据对象和拒绝/返回的理由。

### 实验 E：通用 STM32 适配纸面流程

只有在已有具体工程时执行，不烧录、不修改 IDE/CubeMX 全局配置：

1. 记录完整 MCU 型号、封装、开发板、调试器和 Cube 固件包版本。
2. 在该型号 Reference Manual 中找到 GPIO 章节，记录配置字段和数据访问路径的章节号；没有找到就标记待核对。
3. 在 Datasheet 中记录所用封装的复用表和电气限制；不把 AN4899 的一般说明当作数字替代。
4. 对照实际初始化代码和 HAL/LL 文档，画出“应用意图 -> 配置 -> 数据访问 -> 引脚”的调用流。
5. 若要声称外部电平，补充测量仪器、探头、采样率、接线和时间戳；否则结论只到构建/调试层。

验收：每个具体地址、字段、引脚和电气数字都有第一方资料或测量证据；没有证据的地方写“待核对”。

## 13. 自检题

1. 为什么写一个数据位不能替代 GPIO 模式配置？
2. 输入模式下软件读取的 `input_sample` 与推挽输出模式下回读的 `output_latch` 有什么不同？
3. 开漏输出写入 `HIGH` 为什么可能只表示释放？
4. `pin_count=4` 时，为什么 pin 3 合法而 pin 4 越界？
5. Host Fake 的 `HIGH` 能否证明真实引脚已经达到某个电压阈值？为什么？
6. 配置状态、输出锁存、输入采样分别由谁持有、谁更新？
7. 复用功能为什么不能只靠端口和引脚编号推断？
8. 要核对某个 STM32 型号的 GPIO 复位值，应该查哪份第一方资料？
9. 如果 HAL API 的函数名看起来相同，为什么仍要记录固件包版本？
10. 生成本课后，为什么 `mastery` 不能自动提高？

参考要点：

1. 模式决定数据通路和写入权限，数据位只影响已经建立的锁存或等价数据状态。
2. 前者是输入路径注入/采样的状态，后者是输出路径保持的状态；真实器件的回读语义仍需参考手册核对。
3. 开漏常见语义是主动拉低、释放高；释放后的电平由外部网络决定。
4. 有效范围是半开区间 `[0, 4)`，包含 0、1、2、3，不包含 4。
5. 不能；Host Fake 没有电压、负载、阈值和时序模型。
6. 端口对象持有配置和模型数据；配置函数建立模式，采样注入更新输入状态，写函数更新输出锁存。
7. 复用能力受器件型号、封装和复用表约束。
8. 该型号的 Reference Manual，并交叉看 Datasheet 的管脚/电气限制；不能用 Host Fake 推断。
9. 参数、错误语义、寄存器顺序和生成代码可能随版本变化。
10. 掌握度只能由用户答案、实验或复习结果提高，课程生成不是掌握证据。

## 14. 面试题

### 14.1 如何解释“GPIO 配置”和“GPIO 数据访问”不是一回事？

建议答案：配置状态决定输入、推挽输出、开漏输出或复用等数据通路及访问约束；数据访问是在该通路上读取输入采样或更新输出锁存。先前者、后者才能有意义。写一个位不能改变模式，读一个位也不能自动证明外部电压。

### 14.2 为什么开漏总线常常需要外部上拉？

建议答案：开漏输出通常主动拉低或释放，释放状态本身不主动驱动高电平；外部上拉或其他电路提供高电平来源。上拉阻值、速度、功耗和竞争限制要查具体器件和系统设计资料。本课不把“需要”扩展成某个固定阻值建议。

### 14.3 你会如何审查一个 GPIO 读写 bug？

建议答案：先记录型号和版本，再确认时钟、模式、输出类型、上下拉和复用选择；区分读的是输入采样还是输出锁存；检查引脚编号、状态更新顺序和 HAL/LL 实现；最后用调试寄存器观察与测量记录验证。没有具体资料时不猜地址或默认状态。

### 14.4 Host Fake 通过了，能否宣布板上 GPIO 正常？

建议答案：不能。它只证明定义好的状态机和错误分支。板上结论还需要目标构建、下载/调试证据、器件资料和必要的电气测量；本课的 `hardware_verified` 保持 `false`。

### 14.5 为什么输入去抖不是本课的核心概念？

建议答案：去抖处理的是输入随时间变化的可靠性，而本课先建立“配置决定通路、数据访问观察状态”的边界。把时间过滤提前会混淆第一层模型；后续输入可靠性课程再处理。

## 15. 延伸思考

1. 如果把 Host Fake 扩展为“外部上拉存在/不存在”，需要增加哪些状态？怎样避免把它误称为真实电阻或电压模型？
2. 复用功能把数据通路交给另一个外设后，GPIO 数据寄存器的写入应当如何被标记为“待核对”？
3. 同一个引脚在复位、配置完成和低功耗前后的状态可能不同；要建立怎样的时间线才能避免把“默认状态”当成“运行状态”？
4. 当调试器读到一个 GPIO 数据寄存器值时，怎样判断它代表输入采样、输出锁存还是其他器件定义的读回语义？
5. 未来 Device Framework 把端口和引脚放入 BSP（板级支持包）时，怎样保持配置对象与数据操作的边界，而不提前引入函数指针或依赖注入？
6. 如果两个软件模块同时认为自己拥有同一引脚，除了模式和数据寄存器，还需要哪些构建期或运行期证据发现冲突？

## 16. 本节总结

GPIO 的可迁移模型是：

```text
配置状态
  -> 决定输入/输出/复用数据通路与访问约束
数据访问
  -> 读取输入采样或更新输出锁存
数据通路
  -> 才可能影响/观察真实引脚
外部电路与测量
  -> 决定能否对电平、波形和电气性能下结论
```

检查任何 GPIO 问题时，依次问：

- 配置对象在哪里定义、由谁持有、谁建立？
- 当前数据动作访问的是输入采样、输出锁存还是复用路径？
- 开漏释放、上下拉和外部负载是否改变了“写入值”和“外部电平”的关系？
- 引脚编号、复用表、字段和电气限制是否来自具体器件资料？
- 结论属于 Host Fake、构建/调试证据，还是已经有测量支持？

Host Fake 让这些逻辑关系在普通 Windows 主机上可观察，但不生成真实寄存器访问、不模拟电压，也不能提高 mastery。当前没有具体开发板或上板记录，`hardware_verified=false`。

## 17. 下一步

先完成实验 A、B、C，并能不看正文说明：

1. 配置状态为什么必须先于数据访问；
2. 输入采样和输出锁存为什么是不同对象；
3. 开漏释放为什么不能直接宣称外部高电平；
4. Host Fake、器件资料、调试观察和测量各自能证明什么。

下一门课程可在不改变本课模型的前提下进入 EXTI（外部中断）或其他事件机制；届时再讨论输入变化如何触发事件，不把事件机制提前塞进本课。

## 18. 参考资料

[1] STMicroelectronics, *STM32 microcontroller GPIO hardware settings and low-power consumption*, Application note AN4899，官方 PDF；修订标签未在本次元数据检查中独立确认，重点参阅 GPIO 配置、推挽/开漏、上下拉和功耗相关章节。该资料用于一般机制说明，不替代具体型号 Reference Manual 或 Datasheet。
https://www.st.com/resource/en/application_note/an4899-stm32-microcontroller-gpio-hardware-settings-and-lowpower-consumption-stmicroelectronics.pdf

[2] STMicroelectronics, *STM32F3 and STM32F4 series Cortex-M4 programming manual*, PM0214 Rev 10, March 2020，重点用于限定 Cortex-M4 软件编程背景和“不能从通用背景外推具体 GPIO 地址”的证据边界；不用于证明 F7、H5、H7 或具体型号 GPIO 字段。
https://www.st.com/resource/en/programming_manual/pm0214-stm32f3-and-stm32f4-series-cortexm4-programming-manual-stmicroelectronics.pdf

来源访问日期：2026-10-04。Arm DDI0403 官方入口本次请求返回 403，未用于支撑正文结论。本文没有使用来源政策之外的博客或第三方完整源码。

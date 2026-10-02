+++
title = "启动代码：把复位入口变成可运行的 C 环境"
date = "2026-10-01T21:27:03+08:00"
lastmod = "2026-10-01T21:27:03+08:00"
summary = "用 Host Fake 观察复位入口经过启动代码、栈使用条件和 C 运行时初始化后再进入 main 的顺序，并区分主机逻辑验证与真实 Cortex-M 行为边界。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 13
tags = ["startup", "startup-code", "reset-handler", "c-runtime", "data-bss", "host-fake", "c11", "beginner"]
source_ids = ["st-pm0214-cortex-m4-programming-manual", "st-pm0253-cortex-m7-programming-manual", "gnu-c-file-scope-variables"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L013"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 13 课：启动代码：把复位入口变成可运行的 C 环境

复位后，处理器已取得执行入口和向量表提供的初始栈指针，但这不等于 C 程序的运行前提已成立。启动代码（startup code，启动代码）使用该栈条件，准备 C 运行时静态数据，最后交给 `main`。本课用 Windows 主机上的 Host Fake（主机伪实现）观察顺序；它不是 Cortex-M 仿真，也没有开发板或上板证据。

## 1. 本节目标

完成本课后，你应能：

- 按时间顺序描述“向量表中的复位入口 -> 复位处理函数 -> 启动阶段初始化 -> `main`”的调用流；
- 解释启动代码为何不能被简化成“复位后直接调用 `main`”；
- 区分启动代码负责的运行时边界与应用 `main` 负责的业务控制流；
- 用 Host Fake 的事件日志验证 `main` 只能在运行时初始化完成后进入，并发现重复初始化或漏掉初始化步骤的问题；
- 明确主机逻辑验证不能证明真实 Cortex-M 的内存地址、启动文件布局或板上执行。

本课引入两个新核心概念：

1. **启动代码把复位入口转换为可执行的 C 运行环境**：它在应用开始前完成一组有顺序的准备动作。
2. **启动阶段的运行时初始化与 `main` 之间的责任边界**：启动阶段准备静态对象的可用状态，`main` 在此前提上开始应用控制流。

## 2. 它解决什么问题

上一课已经建立“复位 -> 入口 -> 复位处理程序”的模型，向量表说明了入口信息如何按编号组织。本课继续追问：复位处理程序转入 `main` 之前，为什么还需要一段启动实现？

主机由操作系统和 C 运行环境先准备进程，再调用 `main`；裸机复位会按处理器启动约定取得初始栈指针和复位入口，但静态对象仍须在进入应用前满足 C 的初始状态约定。[1][2][3]

这里只讨论责任边界；具体实现必须回到目标型号资料核对。

## 3. 必要前置知识

必要前置：`reset-sequence`（入口到复位处理函数）、`vector-table`（编号到入口的查表）、`first-c-program` 和 `storage-duration`（`main` 与静态对象）。

本课不假定你掌握启动文件、链接脚本、ELF/map 文件、寄存器或开发板。

## 4. 核心原理

### 4.1 从入口到 `main` 的最小抽象

可迁移的控制流可以画成：

```text
复位事件
  -> 向量表提供复位入口
  -> reset_handler（复位处理函数）开始执行
  -> 使用处理器已装载的初始栈指针（是否另行调整待核对）
  -> 准备已赋值静态数据（目标工程常映射为 .data，具体映射待核对）
  -> 准备零初始化静态数据（目标工程常映射为 .bss，具体映射待核对）
  -> 调用 main
```

这是一条责任顺序，不是对某个启动文件逐行转录。ST 的 STM32F4/F7 编程手册提供对应内核的启动与异常背景。[1][2] 具体芯片的额外步骤和实现语言仍待核对。

### 4.2 启动代码解决什么问题

启动代码主要解决两个问题：

1. **把处理器控制流接到 C 控制流**。复位入口不是应用业务入口；复位处理函数要执行启动阶段动作，再转入 `main`。
2. **让静态对象满足 C 程序的初始状态约定**。文件作用域静态对象在程序执行期间保持其存储期，并按 C 规则获得初始值；启动实现需要在进入应用前使这些状态可用。[3] 目标工程常用 `.data` 表示带初值数据、`.bss` 表示零初始化数据，但段名、符号、地址和拷贝实现属于工具链/启动文件映射，必须另行核对，不能从本课抽象直接推出。

“初始栈指针的装载”是处理器复位动作；栈的后续使用和静态对象准备依赖启动文件与构建产物，地址安排属于后续课程。[1][2][3]

### 4.3 每个对象由谁定义、持有、提供和调用

| 对象 | 定义与持有 | 触发与调用流 |
| --- | --- | --- |
| 复位入口 | 架构/启动约定定义，处理器取得 | 复位 -> `reset_handler` |
| `reset_handler` | 启动实现提供，映像持有 | 入口 -> 栈就绪 |
| 初始栈、静态数据映射 | 初始栈由处理器按向量表装载；启动实现使用栈并准备静态数据；段边界待核对 | 初始栈可用 -> 带初值状态 -> 零初始化状态 |
| `main` | 应用源文件实现，映像持有 | `.bss` 完成 -> `main` |

“持有”表示负责提供代码或状态；示例只有静态数组。

### 4.4 五个动作的边界

五个动作分别是：**声明**接口；**实现**启动顺序和 `main`；**实例化**静态日志/状态；**组装**启动文件、构建产物与应用映像；**使用**由复位触发并调用 `main`。初始栈指针属于处理器复位语义，不是 Host Fake 中的 C 函数设置。

## 5. 关键术语与直观模型

| 术语 | 本课中的含义 |
| --- | --- |
| 启动代码（startup code） | 复位入口到 C 应用入口之间的工程实现。 |
| 复位处理函数（reset handler） | 负责启动阶段并最终调用 `main` 的入口代码。 |
| C 运行时初始化 | 使静态对象和调用环境满足 C 约定的准备动作。 |
| 栈指针（stack pointer） | 当前调用栈位置；本课只抽象为“处理器已提供初始栈、启动代码可以使用”，不声称示例修改了硬件栈。 |
| `.data` / `.bss` | 常见的带初值/零初始化段名；本课只把它们作为待核对的工程映射，不断言具体地址或符号。 |
| Host Fake | 主机上的显式 C 事件模型，不模拟处理器或硬件复位。 |

## 6. 从输入到结果的完整流程

Host Fake 的输入是实验驱动对 `reset_handler()` 的一次显式调用；结果是事件日志和断言：

```text
实验驱动 main
  -> reset_handler
  -> mark_stack_available
  -> init_data
  -> clear_bss
  -> app_main
  -> main 检查日志顺序和状态
```

- **对象在哪里定义**：事件编号、日志和启动状态在示例文件中定义；每个步骤是一个静态函数。
- **谁持有**：静态日志和状态由示例程序持有；启动函数负责推进状态，`app_main` 只读取前置条件并记录进入。
- **谁注入/提供**：实验驱动显式提供一次调用；真实目标中入口由复位和向量表机制提供，不是 `main` 的参数注入。
- **调用流**：`main -> reset_handler -> mark_stack_available -> init_data -> clear_bss -> app_main -> main 的断言`。

## 7. 嵌入式系统中的对应位置

在真实 STM32 工程中，启动实现连接处理器约定、构建产物和应用代码，不是业务层；具体顺序须按系列启动文件核对。没有板卡证据时不填写地址、寄存器、引脚、时钟树、外设实例或 HAL 调用。

## 8. 主机实验与硬件迁移边界

Host Fake 可验证抽象事件按序完成、步骤调换/缺失时断言失败，以及应用只在初始化完成后进入；它不能验证 Cortex-M 的向量表读取、初始栈装载、段地址、启动汇编或板上运行。

本次无开发板、调试器、构建日志或测量记录，`hardware_verified=false`；代码待主机执行，迁移后待上板验证。

## 9. 最小代码示例

这是 C11 子集的逻辑模型。它不使用函数指针、动态内存、寄存器或具体地址；事件日志只是为了让顺序可观察。

```c
#include <assert.h>
#include <stdint.h>

enum startup_event {
    EVENT_STACK_AVAILABLE = 1U,
    EVENT_DATA_READY = 2U,
    EVENT_BSS_CLEARED = 3U,
    EVENT_MAIN_ENTERED = 4U
};

enum startup_state {
    STATE_RESET = 0U,
    STATE_STACK_AVAILABLE = 1U,
    STATE_DATA_READY = 2U,
    STATE_BSS_CLEARED = 3U,
    STATE_MAIN_ENTERED = 4U
};

static uint32_t event_log[4];
static uint32_t event_count;
static uint32_t startup_state = STATE_RESET;

static void record_event(uint32_t event)
{
    if (event_count < 4U) {
        event_log[event_count] = event;
        event_count += 1U;
    }
}

static void mark_stack_available(void)
{
    assert(startup_state == STATE_RESET);
    startup_state = STATE_STACK_AVAILABLE;
    record_event(EVENT_STACK_AVAILABLE);
}

static void init_data(void)
{
    assert(startup_state == STATE_STACK_AVAILABLE);
    startup_state = STATE_DATA_READY;
    record_event(EVENT_DATA_READY);
}

static void clear_bss(void)
{
    assert(startup_state == STATE_DATA_READY);
    startup_state = STATE_BSS_CLEARED;
    record_event(EVENT_BSS_CLEARED);
}

static void app_main(void)
{
    assert(startup_state == STATE_BSS_CLEARED);
    startup_state = STATE_MAIN_ENTERED;
    record_event(EVENT_MAIN_ENTERED);
}

static void reset_handler(void)
{
    mark_stack_available();
    init_data();
    clear_bss();
    app_main();
}

int main(void)
{
    reset_handler();

    assert(event_count == 4U);
    assert(event_log[0] == EVENT_STACK_AVAILABLE);
    assert(event_log[1] == EVENT_DATA_READY);
    assert(event_log[2] == EVENT_BSS_CLEARED);
    assert(event_log[3] == EVENT_MAIN_ENTERED);
    assert(startup_state == STATE_MAIN_ENTERED);
    return 0;
}
```

代码边界如下：

- `enum`、静态日志和状态属于教学示例层，模拟可观察结果，不是目标内存段内容。
- `reset_handler` 是启动实现的抽象；`mark_stack_available()` 只记录处理器已经提供初始栈的模型前提，不模拟设置 MSP；`app_main` 是为了避免把主机测试驱动的 `main` 误认为目标应用入口。
- `main` 只负责显式触发一次 Host Fake 并检查结果；真实目标中复位触发路径由处理器和向量表提供。
- 若把 `clear_bss()` 调到 `init_data()` 前，或在 `app_main()` 前重复一步，状态断言会失败；这只证明模型顺序被破坏。

## 10. 常见错误

- 说“复位后直接调用 `main`”，遗漏复位处理函数和运行时初始化边界。
- 把 Host Fake 中的 `reset_handler()` 显式调用写成“模拟了真实硬件复位”。
- 把 `.data` 或 `.bss` 当成固定地址，或从示例数组推断目标存储器布局；这些段名与符号必须由具体构建产物核对。
- 认为启动代码自动完成全部时钟、外设、RTOS 或板级初始化；这些取决于具体工程，必须待核对。
- 仅凭主机断言通过，声称已经交叉编译、下载、运行或上板。

## 11. 调试观察点

1. 在 `reset_handler`、`mark_stack_available`、`init_data`、`clear_bss`、`app_main` 分别设置断点，观察主机调用栈是否符合预期。
2. 逐项查看 `event_log`，确认日志顺序，而不是只看最终返回值。
3. 暂时删除 `clear_bss()`，运行并记录失败位置；这模拟“缺少前置步骤”的逻辑错误，不是硬件故障证据。
4. 暂时把 `app_main()` 放到 `clear_bss()` 前，确认状态断言阻止应用提前进入。
5. 将调试记录分成 Host Fake 证据和真实目标待核对项。

## 12. 实战实验

把代码保存为 `startup-fake.c`，在普通 Windows 主机上执行：

```powershell
gcc -std=c11 -Wall -Wextra -Wpedantic .\startup-fake.c -o .\startup-fake.exe
if ($LASTEXITCODE -eq 0) { .\startup-fake.exe; $LASTEXITCODE }
```

按以下顺序记录实验：

1. 先纸面预测四个事件，再执行并记录编译器版本、命令和退出状态。
2. 将 `app_main()` 移到 `clear_bss()` 之前，重新执行，确认断言失败的位置与状态不满足相符。
3. 恢复顺序后，删除 `init_data()` 调用，再执行一次，说明哪一个前置条件首先被破坏。
4. 写出 Host Fake 能证明和不能证明的各两点，并说明为何 `hardware_verified=false`。

没有编译器时可纸面追踪，但不得把未执行命令或主机退出状态当作上板证据。

## 13. 自检题

1. 为什么向量表已经提供复位入口，仍不能说明 C 运行环境已经准备好？
2. `reset_handler`、`.data` 准备、`.bss` 清零和 `main` 的责任边界分别是什么？
3. 示例中的日志和状态由谁定义、谁持有、谁推进、谁检查？
4. 为什么 `app_main` 需要在 `STATE_BSS_CLEARED` 成立后才能进入？
5. Host Fake 的顺序断言不能证明哪些真实 Cortex-M 行为？
6. 如果具体 STM32 启动文件还做了其他早期步骤，本课应如何处理这些未知信息？

## 14. 面试题

**问：MCU 复位后为什么不能直接跳到 `main`？没有开发板时如何验证？**

答题要点：处理器先取得初始栈指针和入口，启动代码准备静态对象状态后才调用 `main`；`main` 负责应用控制流。Host Fake 只能断言抽象顺序，具体段映射要回到一手资料和构建证据。

## 15. 延伸思考

- 启动某一步失败时，哪些最小证据能区分“未进入 `main`”与“进入后应用失败”？
- 为什么把“运行时初始化完成”作为 `main` 的前置条件，比在 `main` 内部随意补做初始化更容易审计？
- 后续学习链接脚本时，你需要哪些符号或地址证据，才能把本课的 `.data`/`.bss` 抽象映射到具体工程？
- 比较 F4、F7、H5、H7 时，哪些控制流可迁移，哪些必须逐系列核对？

## 16. 本节总结

启动代码使用处理器已装载的初始栈，让静态对象满足 C 初始状态，再进入 `main`；`.data/.bss` 是待构建产物核对的常见映射。Host Fake 可检查顺序，但不能代替真实复位、内存布局或上板证据；生成本课不提高掌握度。

## 17. 下一步

用目标型号手册、启动文件和构建产物核对 `.data`/`.bss` 映射，保持待核对和 `hardware_verified=false`。

## 18. 参考资料

1. [STMicroelectronics, *STM32F3 and STM32F4 Series Cortex-M4 programming manual*](https://www.st.com/resource/en/programming_manual/pm0214-stm32f3-and-stm32f4-series-cortexm4-programming-manual-stmicroelectronics.pdf)，`PM0214`，访问日期：2026-10-01；核对复位与异常背景，器件细节待核对。
2. [STMicroelectronics, *STM32F7 series programming manual*](https://www.st.com/resource/en/programming_manual/pm0253-stm32f7-series-programming-manual-stmicroelectronics.pdf)，`PM0253`，访问日期：2026-10-01；交叉核对启动模型边界。
3. [GNU Project, *GNU C Language Manual: File-Scope Variables*](https://www.gnu.org/software/c-intro-and-ref/manual/html_node/File_002dScope-Variables.html)，第 20.6 节，访问日期：2026-10-02；支撑静态对象语义，不支撑 `.data/.bss` 布局。

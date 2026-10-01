+++
title = "向量表：按编号找到处理程序入口"
date = "2026-10-01T20:53:30+08:00"
lastmod = "2026-10-01T20:53:30+08:00"
summary = "用一个不冒充硬件的 Host Fake 验证异常或中断编号如何查找向量表项并选择抽象处理程序，同时区分该模型与主机普通函数调用。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 12
tags = ["startup", "vector-table", "exception", "interrupt", "host-fake", "c11", "beginner"]
source_ids = ["arm-dui0646-cortex-m7", "st-pm0253-programming-manual"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L012"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 12 课：向量表：按编号找到处理程序入口

## 1. 本节目标

完成本课后，你应能：

- 解释异常或中断发生后，处理器为什么需要按编号查找入口信息；
- 用“编号 -> 查表 -> 入口信息 -> 处理程序”的模型描述控制流；
- 区分目标硬件的向量表查表与主机程序的普通函数调用；
- 在 Windows 主机上用 Host Fake（主机替身）验证有效编号和越界编号的逻辑结果。

本课只引入一个新核心概念：**向量表**，即按异常/中断编号组织入口信息、供处理器查表转移控制的有序表。预计用时 30 分钟。

## 2. 它解决什么问题

处理器可能遇到复位、系统异常或外部中断。每一种事件都需要不同的处理程序；如果只知道“发生了事件”，还不知道应把控制权交给哪段代码。向量表把事件编号和入口信息放在有序关系中，使查找规则可重复，而不是在每个事件处手写一串条件。

这里的“查表”是架构控制流模型，不等同于主机的 `main()` 调用。Arm 的 Cortex-M 文档将异常入口和向量表作为处理器启动/异常模型的一部分；ST 的 PM0253 用 STM32F7 工程背景说明该模型的目标实现。本文只采用两份资料共同支持的抽象，不推断具体地址、条目宽度、重定位寄存器或启动文件名。

## 3. 必要前置知识

你需要知道：复位后处理器先取得规定入口，再进入复位处理程序；C 程序可以用固定宽度整数、静态数组和条件分支表达数据流。本课不要求预先知道异常分类、启动文件、链接脚本、ELF、寄存器、HAL/LL API 或任何开发板信息。

## 4. 核心原理

### 4.1 编号让入口选择可重复

事件到来时，处理器得到一个异常号或中断号。向量表按这个编号排列入口信息。抽象流程如下：

```text
异常/中断事件
  -> 得到异常号或中断号
  -> 以编号查向量表
  -> 取得对应入口信息
  -> 转入对应处理程序
```

复位也有自己的复位向量；它与其他异常/中断入口共同属于启动约定的背景。本课不规定编号从哪里开始、每项占多少字节或表放在哪个地址，这些必须由具体处理器资料核对。

### 4.2 对象由谁定义、持有和触发

| 对象 | 解决的问题 | 定义位置 | 谁持有/提供 | 谁触发 | 调用如何流动 |
| --- | --- | --- | --- | --- | --- |
| 异常/中断编号 | 区分本次事件 | 处理器架构和事件来源 | 处理器启动/异常机制提供 | 复位、异常或外部事件 | 事件 -> 编号 |
| 向量表 | 把编号关联到入口信息 | 目标映像的启动约定和工程实现 | 处理器可查阅，映像提供内容 | 处理器响应事件 | 编号 -> 表项 |
| 入口信息 | 指明下一段处理路径 | 向量表的表项 | 向量表保存 | 查表动作取得 | 表项 -> 入口 |
| 处理程序 | 处理具体事件 | 目标工程代码 | 程序映像包含代码 | 处理器转入入口后执行 | 入口 -> 处理程序 |

“持有”在这里表示负责保存或提供信息，不表示动态内存所有权。真实硬件的查表和转入由处理器机制完成；Host Fake 只能把这条关系写成普通 C 控制流。

## 5. 关键术语与直观模型

| 术语 | 中文解释和边界 |
| --- | --- |
| 向量表（vector table） | 按编号排列入口信息的有序表。 |
| 复位向量（reset vector） | 与复位事件对应的入口信息名称；本课不讲其具体布局。 |
| 异常号（exception number） | 用于识别处理器异常的编号。 |
| 中断号（interrupt number） | 用于识别外部或系统中断来源的编号；具体编号分配依芯片资料。 |
| 处理程序入口（handler entry） | 查表得到的、用于转入处理程序的信息。 |
| 向量表基址（vector-table base） | 向量表起始位置的概念名称；本课不指定地址或重定位方式。 |
| 异常与中断 | 本课将二者都视为需要“编号 -> 入口”的事件，不展开优先级等其他机制。 |
| Host Fake（主机替身） | 用主机上的普通 C 代码验证抽象关系，不模拟处理器读取内存。 |

## 6. 从输入到结果的完整流程

Host Fake 的输入是一个模拟编号，结果是处理程序 ID 和事件日志：

```text
main 提供编号
  -> lookup_handler_id 检查编号边界
  -> 读取静态向量表中的表项
  -> run_handler 按处理程序 ID 记录结果
  -> main 检查成功或拒绝
```

表和编号在示例文件中定义；静态数组由示例程序持有；实验驱动提供模拟编号；查找函数负责边界检查；处理程序分派函数记录结果。真实硬件中，事件触发来自处理器异常机制，而不是 `main` 的参数。

## 7. 嵌入式系统中的对应位置

向量表位于“处理器启动约定”和“工程提供的入口代码”交界处。它先于具体处理程序的业务逻辑发生作用，因此能把“发生了什么事件”和“谁来处理”分开。后续课程可以再讨论启动文件、链接脚本、存储器布局和向量表重定位；这些不是本课的结论。

从 F4、F7、H5 到 H7，系列实现细节应分别回到对应 Arm/STM32 一手资料核对。没有目标芯片和构建记录时，本课不填写基址、寄存器值、条目格式、引脚、时钟树或外设实例。

## 8. 主机实验与硬件迁移边界

Host Fake 能验证：编号是否被正确检查、有效编号是否选择预期表项、未定义编号是否被拒绝。它不能验证：处理器是否真的读取某个内存地址、真实入口信息的编码、异常优先级、启动映像布局、交叉编译、下载或板上运行。

本课没有开发板、调试器、构建日志或测量记录，因此 `hardware_verified=false`。示例仅作逻辑验证，迁移到具体 STM32 工程后仍待上板验证。

## 9. 最小代码示例

下面是 C11 子集示例。表项保存教学用的处理程序 ID，而不是目标处理器实际入口地址；这样可以在不使用函数指针的前提下观察查表顺序。

```c
#include <assert.h>
#include <stdint.h>

enum handler_id {
    HANDLER_RESET = 10U,
    HANDLER_FAULT = 20U,
    HANDLER_EXTERNAL = 30U
};

struct vector_entry {
    uint32_t handler_id;
};

static const struct vector_entry vector_table[] = {
    { HANDLER_RESET }, { HANDLER_FAULT }, { HANDLER_EXTERNAL }
};
static uint32_t last_handler;
static uint32_t rejected_count;

static uint32_t lookup_handler_id(uint32_t number)
{
    const uint32_t count = (uint32_t)(sizeof(vector_table) / sizeof(vector_table[0]));
    if (number >= count) {
        rejected_count += 1U;
        return 0U;
    }
    return vector_table[number].handler_id;
}

static void run_handler(uint32_t handler_id)
{
    if (handler_id == HANDLER_RESET || handler_id == HANDLER_FAULT ||
        handler_id == HANDLER_EXTERNAL) {
        last_handler = handler_id;
    }
}

int main(void)
{
    run_handler(lookup_handler_id(2U));
    assert(last_handler == HANDLER_EXTERNAL);

    run_handler(lookup_handler_id(99U));
    assert(rejected_count == 1U);
    assert(last_handler == HANDLER_EXTERNAL);
    return 0;
}
```

代码层次只有教学示例层：`vector_table` 是静态表，`lookup_handler_id` 执行边界检查和查表，`run_handler` 用 ID 记录结果，`main` 是主机实验驱动。真实硬件可能使用不同的入口信息表示；本代码不冒充其布局，也没有编译或上板证据。

## 10. 常见错误

- 说“中断发生后直接调用某个 C 函数”，忽略编号和入口查表边界。
- 把示例数组中的 `handler_id` 当成真实地址或完整向量表格式。
- 把 `main` 传入编号写成硬件异常触发。
- 未检查编号就访问数组，导致未定义行为。
- 仅凭主机断言通过，声称目标已交叉编译、下载或运行。

## 11. 调试观察点

1. 在 `lookup_handler_id` 入口观察 `number`，确认有效值为 0、1、2，99 被拒绝。
2. 逐步查看 `vector_table[number].handler_id`，把“表项”与“处理程序”分开记录。
3. 观察 `rejected_count`，确认越界输入没有改变 `last_handler`。
4. 暂时把表中第二项改成 `HANDLER_EXTERNAL`，确认测试能暴露表内容变化，再恢复。
5. 在笔记中分别标注“主机函数调用证据”和“硬件行为待核对”，不要混写。

## 12. 实战实验

把示例保存为 `vector-table-fake.c`，用普通 Windows C 编译器执行：

```powershell
gcc -std=c11 -Wall -Wextra -Wpedantic .\vector-table-fake.c -o .\vector-table-fake.exe
if ($LASTEXITCODE -eq 0) { .\vector-table-fake.exe; $LASTEXITCODE }
```

记录编译器版本、命令和退出状态。然后依次完成：

1. 把 `lookup_handler_id(2U)` 改成 `lookup_handler_id(1U)`，预测并观察 `last_handler`；
2. 把编号改成 `3U`，确认它被拒绝；
3. 在不改变表长度的情况下新增一个表项和对应 ID，说明你改动了哪些定义；
4. 写下 Host Fake 能证明和不能证明的各两点。

没有编译器时可以纸面追踪，但不得把未执行的命令写成已验证。

## 13. 自检题

1. 向量表解决了“事件发生后还缺什么信息”的问题？
2. 异常号/中断号、表项和处理程序三者如何连接？
3. 示例中的数组由谁定义和持有，谁触发查找？
4. 为什么编号 99 不能直接用于数组访问？
5. 主机的 `run_handler` 调用为什么不等于真实硬件异常入口？

## 14. 面试题

**问：异常或中断发生后，处理器如何找到对应处理程序？**

答题要点：事件带来异常号或中断号；处理器按编号查向量表；取得入口信息后转入相应处理程序。具体表基址、条目编码、重定位和系列差异必须引用目标处理器资料，不能从 Host Fake 推断。

## 15. 延伸思考

- 如果两个编号意外指向同一个处理程序，调试时需要记录哪些证据来区分事件来源？
- 为什么边界检查在“查表”模型中是必要的，即使真实处理器不会执行这段 C 代码？
- 下一课若讨论启动文件，你希望从向量表模型补充哪个实现证据？

## 16. 本节总结

向量表是按异常/中断编号组织入口信息的有序表。可迁移的控制流是“事件 -> 编号 -> 查表 -> 入口信息 -> 处理程序”。Host Fake 用静态数组和 ID 验证这个逻辑及越界边界，但不模拟真实处理器、地址布局或硬件异常，因此本课没有硬件验证结论。

## 17. 下一步

完成实验并回答自检题后，再学习启动实现如何提供向量表内容。生成本课不会提高掌握度，也不会修改 `completed` 或 mastery。

## 18. 参考资料

1. [Arm, *Cortex-M7 Devices Generic User Guide*](https://developer.arm.com/documentation/dui0646/latest)，文档 `DUI0646`，latest；访问日期：2026-10-01。用于核对 Cortex-M7 异常入口和向量表概念。[1]
2. [ST, *STM32F7 Series programming manual*](https://www.st.com/resource/en/programming_manual/pm0253-stm32f7-series-programming-manual-stmicroelectronics.pdf)，编程手册 `PM0253`；访问日期：2026-10-01。用于核对 STM32F7 工程中的复位/异常入口背景，不据此推广未说明的地址或布局。[2]

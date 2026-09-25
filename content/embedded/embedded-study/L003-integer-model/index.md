+++
title = "32 位整数：先按范围选类型"
date = "2026-09-21T22:07:26+08:00"
lastmod = "2026-09-21T22:07:26+08:00"
summary = "依据需求的最小值、最大值和是否需要负数，在主机逻辑验证中选择 int32_t 或 uint32_t，并识别超出范围的设计风险。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 3
tags = ["embedded-c", "integer-model", "c11", "host-verification", "beginner"]
source_ids = ["gnu-c-intro-ref-0-1", "gcc-c-implementation-15-2", "arm-ihi0042-2025q4", "glibc-reference-2-42"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L003"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 3 课：32 位整数：先按范围选类型

本课只学习两个核心概念：**整数类型的有限表示范围**，以及**有符号与无符号整数对同一位模式的不同数值解释**。先看可观察结果：一个需求允许负数时，检查它能否放进 `int32_t`；只允许零和正数时，检查它能否放进 `uint32_t`；超过上界就拒绝，而不是先存进去再看结果。

## 1. 本节目标

面对一个小范围数值需求，你能用“类型可表示的范围”判断选用 `int32_t` 还是 `uint32_t`，并在主机逻辑验证中看到超出范围的设计风险；还能说明主机结果不等于目标板运行或硬件验证。

预计用时 30 分钟。本课不学习类型转换、指针、寄存器或具体 STM32 型号。

## 2. 它解决什么问题

上一课用 `int` 保存了 `4` 和 `7`，但没有回答：如果数值可能为负，或者可能大到几十亿，容器是否装得下？整数类型的容量有限。选错类型会让需求中的合法值无法表示；若等到计算已经越界才检查，检查也可能太晚。

本课采用以下最小流程：

1. 先写需求的最小值和最大值。
2. 再查候选类型的范围。
3. 范围完整覆盖需求，才定义该类型的变量。
4. 超过范围的需求直接报告 `rejected`（拒绝）。

## 3. 必要前置知识

已完成的前两课提供了：主机与嵌入式目标不同；源文件要经过构建、运行和观察；`main` 中的简单语句按顺序执行。

本课从零解释整数规则。实验需要 Windows、PowerShell 和支持 C11 的 GCC。本次运行记录已确认当前主机可调用 GCC 16.2.0，并留下了示例的主机构建与运行证据；这仍不等于 STM32 构建或硬件验证。

## 4. 核心原理

### 4.1 有限表示范围

位（bit）是只能取 `0` 或 `1` 的二进制一位；位宽是一个整数使用的位数。位数有限，可区分的组合就有限，所以整数类型不可能容纳任意大的数。

在实现提供这些精确宽度类型时：

| 类型 | 能表示的范围 | 适合本课中的需求 |
| --- | --- | --- |
| `int32_t` | -2,147,483,648 到 2,147,483,647 | 可能为负，且上下界都落在此范围 |
| `uint32_t` | 0 到 4,294,967,295 | 不允许负数，且最大值落在此范围 |

`int32_t` 中的 `int` 表示整数，`32` 表示恰好 32 位；`uint32_t` 开头的 `u` 表示 unsigned（无符号）。它们由标准头文件 `stdint.h` 声明。GNU C Library 手册明确说明：若编译器和目标机不能提供某个宽度的整数，对应的精确宽度类型就不存在；因此使用前必须以实际工具链为准。[4]

- **解决什么问题**：在存值之前证明候选类型覆盖需求。
- **对象在哪里定义**：定宽整数类型名由 `stdint.h` 声明，范围宏由该头文件定义；本例的需求边界和变量在 `main.c` 的 `main` 中定义。
- **谁持有它**：本例变量直接属于 `main`；本课不展开变量存储期规则。
- **谁注入它**：没有外部输入和硬件依赖，因此没有注入者；初始值直接写在示例中。
- **调用如何流动**：主机进入 `main`，程序先比较需求与类型上下界，再输出选择结果，最后返回成功或失败状态。

### 4.2 同一位模式的两种解释

位模式是按固定顺序排列的一组 `0` 和 `1`。32 位全为 `1` 时，无符号解释把它看作 `4,294,967,295`；精确 32 位的二进制补码有符号解释把它看作 `-1`。位没有改变，改变的是类型给出的解释规则。[1]

因此，“数值非负”不是把变量改名这么简单；它会改变可表示范围以及运算规则。GNU 手册说明，无符号运算越界按模 `2^n` 保留低 `n` 位；有符号溢出则产生未定义行为，程序不能依赖某个固定结果。[1] 本课不触发有符号溢出，也不把无符号回绕当作范围检查。

## 5. 关键术语与直观模型

| 术语 | 直观含义 |
| --- | --- |
| 可表示范围 | 一种类型能无歧义保存的最小值到最大值。 |
| signed（有符号） | 可表示负数、零和正数的解释方式。 |
| unsigned（无符号） | 只表示零和正数的解释方式。 |
| overflow（溢出） | 数学结果超出目标类型的可表示范围。 |
| `INT32_MIN` / `INT32_MAX` | `int32_t` 的下界和上界宏。 |
| `UINT32_MAX` | `uint32_t` 的上界宏；下界固定为 0。 |

把类型想成带刻度的量杯：先看需求刻度是否都在量杯范围内。把已经溢出的结果再拿来检查，好比液体已经溢出后才判断杯子是否够大。

## 6. 从输入到结果的完整流程

以温度需求 `-40..125` 为例：需要负数，先选有符号候选；两个边界都在 `int32_t` 范围内，所以可选 `int32_t`。计数需求 `0..4,000,000,000` 不需要负数，并且上界不超过 `UINT32_MAX`，所以可选 `uint32_t`。若计数上界变成 `5,000,000,000`，它超过 `UINT32_MAX`，程序应拒绝 `uint32_t`，而不是把该值强行赋给变量。

完整调用流为：`需求边界 -> 与范围宏比较 -> 定义候选变量 -> 输出 fit/rejected -> main 返回退出状态`。

## 7. 嵌入式系统中的对应位置

范围先行的选择方法可迁移到传感器数值、计数器和通信字段。真正接入 STM32 时，还要核对接口定义、工具链和目标 ABI（Application Binary Interface，应用二进制接口）。AAPCS32 的基础数据类型表规定其 Arm 32 位 ABI 中 signed word 和 unsigned word 都占 4 字节，但这是特定目标约定，不能反推所有 C 实现都相同。[3]

本课不罗列 F4、F7、H5、H7 特性；选定具体平台后再核对实际接口。

## 8. 主机实验与硬件迁移边界

本例没有硬件依赖，因此是主机逻辑验证，不是 Host Fake（主机替身）。Host Fake 要替代一个真实硬件依赖，而这里没有对象可替代。

主机实验只能证明当前构建产物中的范围判断符合预期。它不能证明代码已为 STM32 构建、下载或运行，也不能证明任一寄存器、引脚或外设状态。没有开发板和证据，`hardware_verified=false`。

## 9. 最小代码示例

将以下内容保存为 `main.c`：

```c
#include <stdint.h>
#include <stdio.h>

int main(void)
{
    long long temperature_min = -40LL;
    long long temperature_max = 125LL;
    unsigned long long pulse_max = 4000000000ULL;
    unsigned long long oversized_max = 5000000000ULL;

    int signed_range_ok =
        (temperature_min >= INT32_MIN) && (temperature_max <= INT32_MAX);
    int unsigned_range_ok = pulse_max <= UINT32_MAX;
    int oversized_rejected = oversized_max > UINT32_MAX;

    int32_t temperature = 25;
    uint32_t pulse_count = 0U;

    puts(signed_range_ok ? "temperature: int32_t fits" : "temperature: rejected");
    puts(unsigned_range_ok ? "pulse-count: uint32_t fits" : "pulse-count: rejected");
    puts(oversized_rejected ? "oversized-count: uint32_t rejected"
                            : "oversized-count: unsafe choice");

    return (signed_range_ok && unsigned_range_ok && oversized_rejected &&
            (temperature == 25) && (pulse_count == 0U)) ? 0 : 1;
}
```

这是主机逻辑层的单文件 C11 示例，不使用动态内存。`long long` 和 `unsigned long long` 只作为能先写下需求边界的“尺子”，`LL` / `ULL` 后缀让这些字面量分别采用对应类型；本课要选择的存储类型仍是 `int32_t` 和 `uint32_t`。比较成立时结果为非零，不成立时为零；`&&` 要求两侧都成立，`条件 ? A : B` 则根据条件选择 `A` 或 `B`。这些只是完成范围检查所需的辅助语法，不在本课展开类型转换或控制流规则。依赖方向为 `示例程序 -> C 标准头文件/库 -> 主机运行环境`。没有公开接口，也没有对象注入。

## 10. 常见错误

- 看到“32 位”就忽略正负需求：同样 32 位，有/无符号范围不同。
- 先赋值再检查：值必须先能被目标类型表示，赋值后的检查不能补救错误设计。
- 用有符号溢出来观察“回绕”：有符号溢出没有可依赖的固定结果。[1]
- 把无符号回绕理解为安全：规则可预测不等于符合业务需求。
- 把 Arm ABI 当作 C 的普遍规则：GCC 也明确列出许多由具体 C 实现决定的行为。[2]

## 11. 调试观察点

1. 构建时若编译器报告 `int32_t`、`uint32_t` 或对应范围宏不存在，说明当前实现不能直接运行本例，应停止并按工具链文档选择可用类型。
2. 运行后核对三行依次为两个 `fits` 和一个 `rejected`。
3. 立即读取 `$LASTEXITCODE`，预期为 `0`。
4. 若用调试器，观察比较发生前的四个需求边界、三个判断结果，以及 `temperature`、`pulse_count` 的十进制值。
5. 十六进制显示格式由具体调试器决定；未实际观察时不要虚构结果。

## 12. 实战实验

在含 `main.c` 的目录中逐条运行：

```powershell
gcc -std=c11 -Wall -Wextra -pedantic main.c -o lesson.exe
.\lesson.exe
$LASTEXITCODE
```

预期输出：

```text
temperature: int32_t fits
pulse-count: uint32_t fits
oversized-count: uint32_t rejected
0
```

然后把 `pulse_max` 改成 `5000000000ULL`，先预测第二行和退出状态，再重新构建运行。预期第二行变为 `rejected`，退出状态为 `1`。不要改成一次真的有符号溢出来“测试”。请记录 GCC 版本、命令、实际输出和时间；在记录产生前，上述均为预期而非成功证据。

## 13. 自检题

1. 需求 `-20..300` 为什么不能选 `uint32_t`？
2. 需求 `0..4,000,000,000` 为什么可选 `uint32_t` 而不可选 `int32_t`？
3. 为什么范围检查应发生在把需求值存入目标类型之前？
4. 同一组 32 位全 `1`，有/无符号解释为何不同？
5. 为什么主机实验通过仍不能设置 `hardware_verified=true`？

## 14. 面试题

**问：嵌入式 C 中怎样为一个整数业务量选择类型？**

答题要点：先写业务最小值和最大值；判断是否需要负数；用目标实现提供的范围宏检查完整覆盖；接口边界优先使用明确宽度类型；运算前检查越界风险；区分 C 规则、编译器实现和目标 ABI；保留主机与目标验证证据。

## 15. 延伸思考

- 若计数器要求 `0..5,000,000,000`，应改变存储类型还是收紧需求？需要哪些额外证据？
- 一个值语义上永不为负，仍选择 `int32_t` 会损失哪部分正数范围？
- 通信协议字段已经规定 32 位时，除了范围，还要核对哪些解释约定？

## 16. 本节总结

整数类型是有限容器。先根据需求范围判断是否需要负数，再用范围宏证明 `int32_t` 或 `uint32_t` 能完整覆盖。相同位模式可以因有/无符号规则而得到不同数值；有符号溢出不可依赖，无符号回绕也不能代替业务范围检查。

## 17. 下一步

下一课由课程规划决定是否进入 `pointer`。本课生成不提高掌握度；只有你的答案、实验记录或复习结果才能改变状态。

## 18. 参考资料

1. [GNU Project, *GNU C Language Introduction and Reference Manual*, version 0.1, 5 May 2025](https://ftp.gnu.org/gnu/c-intro-and-ref/c-intro-and-ref-0.1.tar.gz)，访问日期：2026-09-21。核对位置：`Integer Data Types`、`Signed and Unsigned Types`、`Integer Overflow`、`Maximum and Minimum Values`；用于支撑精确宽度类型、范围、位模式解释和溢出规则。
2. [GNU Project, *Using the GNU Compiler Collection (GCC): C Implementation-Defined Behavior*, GCC 15.2.0](https://gcc.gnu.org/onlinedocs/gcc-15.2.0/gcc/C-Implementation.html)，访问日期：2026-09-21。用于限定 GCC 实现行为不能泛化为全部 C 实现。
3. [Arm, *Procedure Call Standard for the Arm Architecture (AAPCS32)*, 2025Q4, 23 January 2026](https://developer.arm.com/documentation/ihi0042/latest/)，访问日期：2026-09-21。核对位置：`Fundamental Data Types`；仅用于 Arm 32 位目标适配背景。
4. [GNU Project, *The GNU C Library Reference Manual*, glibc 2.42](https://ftp.gnu.org/gnu/glibc/glibc-2.42.tar.xz)，访问日期：2026-09-21。核对位置：`manual/arith.texi` 的 `Integers`；用于支撑精确宽度整数类型在编译器或目标机不支持相应宽度时不存在。

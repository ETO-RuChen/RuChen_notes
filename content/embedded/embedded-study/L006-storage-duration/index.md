+++
title = "用存储期判断对象地址何时有效"
date = "2026-09-26T16:05:49+08:00"
lastmod = "2026-09-26T16:05:49+08:00"
summary = "用最小 C11 主机程序区分自动存储期和静态存储期，并据此判断对象及其地址何时仍可安全使用。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 6
tags = ["embedded-c", "storage-duration", "object-lifetime", "c11", "host-fake", "beginner"]
source_ids = ["gnu-c-manual-local-variables-20-5", "gnu-c-manual-file-scope-variables-20-6", "arm-101458-2024-04-04", "st-um2609-rev18"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L006"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 6 课：用存储期判断对象地址何时有效

函数可以把局部对象的地址交出去，但函数返回后，那个对象已经不再存在；旧地址不能让对象“继续活着”。本课只在普通 Windows 主机上建立这条判断规则，不推断 STM32 的栈、RAM 分区或指令。

## 1. 本节目标

使学习者能用最小 C11 主机程序区分自动存储期与静态存储期，并据此判断对象与其地址在何时仍可安全使用。预计用时 30 分钟。

本课只有两个新核心概念：

1. 对象的存储期（storage duration，决定对象存在时间的规则）。
2. 自动存储期与静态存储期的生命周期差异。

## 2. 它解决什么问题

上一课已经能用指针传递对象地址，但“地址还在”不等于“地址所指对象还存在”。如果函数返回了局部对象地址，调用者拿到的是旧地址；继续解引用会访问生命周期已经结束的对象，这是未定义行为，程序结果没有可靠保证。

存储期解决的是时间边界问题：对象何时开始存在，何时结束存在。它让我们在传递地址前先问：“接收者使用这个地址时，对象仍在生命周期内吗？”

## 3. 必要前置知识

本课沿用已学内容：单文件 C 程序、`main`、函数调用、`uint32_t`、对象、`&`、`*` 和 `const uint32_t *` 只读借用。这里的对象（object）是具有类型并占据存储位置的程序实体。

不假定已经知道栈、链接、启动过程或内存布局。本课也不讲这些主题。

## 4. 核心原理

### 4.1 存储期决定生命周期

生命周期（lifetime）是对象可被合法访问的时间范围。对象开始存在后才能读取或修改；生命周期结束后，旧指针即使仍保存某个数值，也不能再用来访问原对象。

### 4.2 自动存储期

本课函数或块内定义的普通局部对象具有自动存储期（automatic storage duration）。对本例而言，每次调用 `run_once` 都会产生该次调用的 `local_calls`；离开它所在的块时，这个对象的生命周期结束。下一次调用得到新的对象生命周期，而不是继续使用上一次的对象。[1]

这是 C 语言层的时间规则。局部对象常被实现到运行时栈中，但语言规则不保证它必须位于某个物理“栈地址”，优化也可能改变实际分配方式。[1]

### 4.3 静态存储期

本课在所有函数外定义的 `program_calls` 具有静态存储期（static storage duration）：它在整个程序执行期间存在。连续调用函数时，同一个对象仍然存活，所以前一次写入的值可被下一次调用继续读取。[2]

这里不展开 `static` 关键字、文件内外可见性、链接或初始化顺序。示例中的文件作用域定义只用于建立生命周期对照。

## 5. 关键术语与直观模型

| 术语 | 直观问题 | 本课答案 |
| --- | --- | --- |
| 存储期 | 对象存在多久 | 由声明位置等语言规则决定 |
| 自动存储期 | 每次进入块是否是新对象 | 是；离开块后该次对象结束 |
| 静态存储期 | 是否贯穿程序执行 | 是 |
| 作用域（scope） | 名字能在哪里直接写出来 | 是源码可见范围，不是对象存在时间 |
| 悬空指针（dangling pointer） | 旧地址还指向有效对象吗 | 否；所指对象生命周期已结束 |

作用域管“名字在哪里可见”，存储期管“对象何时存在”。两者相关但不能互相替代：看到一个名字离开可见区域，不能据此编造物理内存变化；保存了一个地址，也不能据此延长对象生命周期。

## 6. 从输入到结果的完整流程

1. 程序开始后，文件作用域对象 `program_calls` 在整个执行期间存在，程序持有它。
2. `main` 第一次调用 `run_once`。
3. `run_once` 定义并持有本次调用的自动对象 `local_calls`，从 `0U` 加到 `1U`；同时把长期存在的 `program_calls` 从 `0U` 加到 `1U`。
4. `run_once` 按值返回 `local_calls` 的数值，然后返回；该次 `local_calls` 生命周期结束，返回的整数副本仍可使用。
5. 第二次调用产生新的 `local_calls`，所以局部结果再次是 `1U`；同一个 `program_calls` 则累加为 `2U`。
6. `main` 检查结果应为局部 `1, 1`，程序级 `1, 2`。

对象定义者同时是持有者：每次 `run_once` 调用持有自己的 `local_calls`，程序静态存储持有 `program_calls`。正常示例不传递对象地址，也没有依赖注入者、板级对象或硬件对象。调用流是 `main -> run_once -> main`。

## 7. 嵌入式系统中的对应位置

可迁移规则仍是先检查对象生命周期，再保存或传递地址。以后驱动或回调需要长期保存某个地址时，必须确认所指对象活得足够久；不能保存一次短暂函数调用中的局部对象地址。

F4、F7、H5、H7 的具体内存区域、启动过程、寄存器和工具链代码生成均未在本课核对。本课不把“自动存储期”直接等同于某段 RAM，也不把“静态存储期”直接等同于某个链接区段。Arm 的 C/C++ 编译器指南与 STM32CubeIDE 手册都是工具链资料，不能替代 C 对象生命周期规则。[3][4]

## 8. 主机实验与硬件迁移边界

这里的 `program_calls` 是 Host Fake（主机替身）中的长期存在对象，只用于和短期局部对象对照。实验能验证受控程序输出与调用流程，不能证明 MCU 内存布局、启动代码、硬件时序或寄存器行为。

没有开发板、构建日志、测量或上板记录，因此本课 `hardware_verified=false`。代码是待学习者执行的主机示例，也是“示例，待上板验证”。

## 9. 最小代码示例

```c
#include <stdint.h>
#include <stdio.h>

uint32_t program_calls = 0U;

uint32_t run_once(void)
{
    uint32_t local_calls = 0U;

    local_calls += 1U;
    program_calls += 1U;
    return local_calls;
}

int main(void)
{
    uint32_t first_local = run_once();
    uint32_t first_program = program_calls;
    uint32_t second_local = run_once();
    uint32_t second_program = program_calls;

    printf("local: %u, %u\n",
           (unsigned int)first_local,
           (unsigned int)second_local);
    printf("program: %u, %u\n",
           (unsigned int)first_program,
           (unsigned int)second_program);

    if ((first_local != 1U) || (second_local != 1U) ||
        (first_program != 1U) || (second_program != 2U)) {
        puts("FAIL");
        return 1;
    }

    puts("PASS");
    return 0;
}
```

这是应用逻辑层的单文件示例，依赖方向为 `示例程序 -> C 标准头文件与主机 C 库`。没有动态内存；公开的计数函数使用固定宽度整数。`local_calls` 生命周期只覆盖一次调用，`program_calls` 生命周期覆盖整个程序执行。

## 10. 常见错误

以下片段只用于阅读或静态诊断，不得放进正常运行路径：

```c
#include <stdint.h>

uint32_t *bad_address(void)
{
    uint32_t local_value = 7U;
    return &local_value;
}
```

`bad_address` 返回时，`local_value` 的生命周期结束，返回值成为悬空指针。调用者不得解引用它。编译器可能给出警告，但警告不是唯一安全机制，也不保证不同编译器具有相同诊断。

其他常见错误：

- 认为保存地址就能延长对象生命周期。
- 认为第二次调用会沿用上一次的普通局部对象。
- 把按值返回的整数副本误认为返回局部对象本身。
- 把自动存储期硬说成“必定位于栈”，或从静态存储期猜测芯片地址。
- 故意解引用悬空指针并把某次输出当成规律。

## 11. 调试观察点

1. 在 `run_once` 入口观察 `local_calls` 每次都由受控初值 `0U` 开始。
2. 在函数返回前观察 `local_calls == 1U`、`program_calls` 依次为 `1U` 和 `2U`。
3. 返回后只观察 `main` 收到的整数副本，不尝试寻找或读取已经结束的局部对象。
4. 若查看地址或汇编，只记录当前编译器的实际现象，不把它提升为 C 语言或 STM32 的普遍保证。

## 12. 实战实验

把第 9 节保存为 `main.c`，在装有 GCC 的 Windows PowerShell 中执行：

```powershell
gcc -std=c11 -Wall -Wextra -pedantic main.c -o lesson.exe
.\lesson.exe
$LASTEXITCODE
```

预期可观察结果：

```text
local: 1, 1
program: 1, 2
PASS
```

退出状态应为 `0`。请记录编译器版本、完整命令、输出和时间；课程文件本身不代表已经执行成功。若找不到 `gcc`，先确认工具是否安装及 `PATH` 是否包含其目录。若结果不同，从四个受控初值和每次调用后的变量值开始检查，不要用危险片段制造“现象”。

## 13. 自检题

1. 存储期解决什么问题？
2. `local_calls` 和 `program_calls` 分别在哪里定义、由谁持有、何时结束生命周期？
3. 为什么两次局部结果都是 `1U`，程序级结果却是 `1U`、`2U`？
4. 作用域和存储期分别回答什么问题？
5. 为什么 `bad_address` 的返回值不能解引用？

## 14. 面试题

**问：函数能否返回局部对象的地址？为什么？**

答题要点：语法上可以写出这种返回，但普通局部对象具有自动存储期；函数离开对应块后，其生命周期结束。返回的旧地址不能延长生命周期，调用者解引用它会产生未定义行为。应改为按值返回结果，或让调用者提供一个在使用期间仍存活的对象；后者只点到为止，不在本课展开架构设计。

## 15. 延伸思考

- 如果只把 `local_calls` 的数值按值返回，为什么调用者仍能安全使用这个结果？
- 将来某模块需要长期保存地址时，你会先向对象拥有者确认哪两个时间点？
- 具体 MCU 上的地址分区为什么必须等待启动、链接与器件资料课程再判断？

## 16. 本节总结

对象的存储期决定其生命周期。普通局部对象通常在每次进入块时开始一次新生命周期，离开块后结束；文件作用域对象具有贯穿程序执行的静态存储期。地址只是定位手段，不拥有对象，也不能延长对象生命周期。

## 17. 下一步

先完成主机实验并回答自检题。课程生成本身不表示已掌握，也不会更新 `completed` 或 mastery（掌握度）。下一主题应由后续计划决定，本课不提前引入链接规则。

## 18. 参考资料

1. [GNU Project, *GNU C Language Manual: Local Variables*](https://www.gnu.org/software/c-intro-and-ref/manual/html_node/Local-Variables.html)，手册说明其覆盖约 2017 年的 GNU C；核对位置：20.5；访问日期：2026-09-26。支撑局部自动对象的存储边界，并提醒实际分配可受优化影响。
2. [GNU Project, *GNU C Language Manual: File-Scope Variables*](https://www.gnu.org/software/c-intro-and-ref/manual/html_node/File_002dScope-Variables.html)，手册说明其覆盖约 2017 年的 GNU C；核对位置：20.6；访问日期：2026-09-26。支撑文件作用域对象的长期存储与初始化概述；本课不采用其链接分类作为教学内容。
3. [Arm, *Arm C/C++ Compiler Developer and Reference Guide*, document 101458](https://developer.arm.com/documentation/101458/latest/)，当前网页版本发布日期：2024-04-04；访问日期：2026-09-26。只支撑 Arm 编译器资料的工具链边界；本课不据此声称具体语言模式、代码生成或 STM32 存储布局。
4. [STMicroelectronics, *STM32CubeIDE user guide*, UM2609 Rev 18, June 2026](https://www.st.com/resource/en/user_manual/um2609-stm32cubeide-user-guide-stmicroelectronics.pdf)，访问日期：2026-09-26。核对 PDF 标题、官方作者、日期及 C/C++ 开发工具定位；只支撑工具环境和硬件迁移边界，不支撑 C 对象生命周期语义。

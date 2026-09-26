+++
title = "用指针修改调用者的对象"
date = "2026-09-26T14:48:38+08:00"
lastmod = "2026-09-26T14:48:38+08:00"
summary = "用主机 C11 示例理解对象地址的保存与传递，并通过有效指针让函数修改调用者持有的同一 uint32_t 对象。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 4
tags = ["embedded-c", "pointer", "c11", "host-verification", "beginner"]
source_ids = ["gnu-c-intro-ref-pointers-0-1", "gnu-c-intro-ref-function-parameters-0-1", "arm-ihi0042-2025q4", "arm-ihi0055-2025q1"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L004"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 4 课：用指针修改调用者的对象

本课只学习两个核心概念：**对象地址可以作为数据保存和传递**，以及**解引用通过地址访问原对象**。先看直观结果：`main` 中的计数值原来是 `7`；函数收到它的地址后把同一个对象改成 `42`；回到 `main`，检查得到 `42` 并报告 `PASS`。

## 1. 本节目标

通过主机上的最小 C11 示例，学习者能说明对象的地址如何被指针保存，并能安全地通过指针让被调用函数修改调用者持有的 `uint32_t` 对象，同时说明这只是逻辑验证而非硬件验证。

预计用时 30 分钟。本课不展开数组、动态内存、指针运算、函数指针、寄存器、HAL（Hardware Abstraction Layer，硬件抽象层）或具体 STM32 型号。

## 2. 它解决什么问题

函数形参（parameter）是函数定义中用来接收调用方传入值的对象。若函数只收到计数值 `7`，它只能处理自己收到的值，无法据此定位 `main` 中那个需要修改的对象。我们需要传递“对象在哪里”，让函数访问同一块存储，而不是另一个无关对象。

本课的约束是：没有具体开发板，也没有可假定的硬件地址；不用动态内存；只操作一个仍然存在的局部 `uint32_t` 对象；无效指针绝不用于解引用实验。

## 3. 必要前置知识

前三课已经提供了主机与嵌入式目标的区别、单文件 C 程序的运行闭环，以及 `uint32_t` 是由 `stdint.h` 提供的 32 位无符号整数类型。

本课从零解释地址和指针。地址（address）是定位对象存储位置的值；对象（object）是程序运行期间具有存储空间和类型的实体；指针（pointer）是保存某类对象地址的值。不要把 `uint32_t` 当作地址类型，也不要猜地址的数字形式或位宽。

## 4. 核心原理

### 4.1 对象地址可以保存和传递

取地址运算符（address-of operator）`&` 从可取地址的对象得到指向该对象的指针。[1] 若有 `uint32_t counter`，表达式 `&counter` 的类型是 `uint32_t *`，读作“指向 `uint32_t` 的指针”。

指针变量也有自己的存储空间。执行 `uint32_t *saved = &counter;` 时，`saved` 保存的是定位 `counter` 的地址值，不是 `counter` 当前保存的整数值。GNU 手册说明，函数形参变量用于存放调用时传入的值。[2] 因此，把 `saved` 传给函数时，函数的指针形参收到地址值的副本；两者仍然指向同一个 `counter`。

### 4.2 解引用通过地址访问原对象

解引用运算符（indirection operator）`*` 通过有效指针指定它所指向的对象。GNU 手册给出的关系是：在 `&counter` 有效时，`*&counter` 指定的就是 `counter`。[1] 因此 `*target = 42U;` 改的是 `target` 指向的对象。

空指针（null pointer）不指向任何对象。示例先比较 `target != NULL`，只有成立才执行 `*target`。GNU 手册明确指出，解引用空指针或其他无效指针是错误；本课不靠触发这种错误观察结果。[1]

这两个核心概念的机制映射如下：

- 解决的问题：让被调用函数定位并修改调用者拥有的同一对象。
- 对象在哪里定义：`counter` 在 `main` 内定义。
- 谁持有对象：`main` 持有 `counter`；调用期间它一直存在。
- 谁传入地址：`main` 用 `&counter` 取得地址并传给 `set_counter`。这里没有硬件对象，也不存在依赖注入者。
- 调用如何流动：`main` 定义对象 -> `&counter` 产生地址 -> 地址值进入指针形参 -> 函数判空 -> `*target` 修改原对象 -> 返回 `main` 检查结果。

## 5. 关键术语与直观模型

| 术语 | 本课中的直观含义 |
| --- | --- |
| 对象 | `main` 中实际占用存储空间的 `counter`。 |
| 地址 | 用于找到 `counter` 存储位置的值。 |
| 指针 | 保存地址值的对象，如形参 `target`。 |
| `&counter` | 取得 `counter` 的地址。 |
| `*target` | 访问 `target` 指向的原对象。 |
| `NULL` | 不指向任何对象的空指针值。 |

可把门牌号类比为地址，把写有门牌号的纸条类比为指针；根据纸条找到房间，才类似解引用。类比只解释“定位”，不说明真实地址的格式。

## 6. 从输入到结果的完整流程

1. `main` 定义 `counter`，初值为 `7U`。
2. `main` 检查初值并调用 `set_counter(&counter, 42U)`。
3. `&counter` 产生指向 `counter` 的地址值。
4. 形参 `target` 保存该地址值的副本，`value` 保存 `42U`。
5. 函数确认 `target` 不是空指针，再执行 `*target = value`。
6. 函数返回成功标志；`main` 检查自己的 `counter` 已为 `42U`，输出 `PASS` 并返回 `0`。

## 7. 嵌入式系统中的对应位置

“传入对象地址，让函数读写调用者存储”是可迁移的 C 机制，以后可用于状态对象、缓冲区和驱动上下文。本课不把这些后续用途展开为新概念。

通用 C 语义没有规定本例地址值在机器上占多少字节，也没有规定函数参数一定放在哪个寄存器。AAPCS32 2025Q4 把其数据指针规定为 4 字节，并说明基础调用约定可用 `r0-r3` 或栈传参；AAPCS64 则存在 32 位和 64 位数据指针的数据模型，并有自己的传参规则。[3][4] 这些是特定 Arm ABI（Application Binary Interface，应用二进制接口）的约定，不是可泛化到所有 C 实现的规则。

## 8. 主机实验与硬件迁移边界

本例没有真实硬件依赖，所以它是主机逻辑验证，不是 Host Fake（主机替身）。Host Fake 应替代某个硬件依赖，本课没有这样的对象。

主机实验只能验证当前主机构建产物中“有效地址传入后，同一对象被更新”的逻辑。它不能证明代码已为 STM32 构建、下载或运行，也不能证明寄存器、HAL、引脚、时钟或外设行为。没有板卡与上板证据，因此 `hardware_verified=false`。

## 9. 最小代码示例

```c
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

uint32_t set_counter(uint32_t *target, uint32_t value)
{
    if (target == NULL) {
        return 0U;
    }

    *target = value;
    return 1U;
}

int main(void)
{
    uint32_t counter = 7U;

    if (counter != 7U) {
        puts("FAIL: unexpected initial value");
        return 1;
    }

    puts("before: counter == 7");

    if (set_counter(&counter, 42U) == 0U) {
        puts("FAIL: address was not accepted");
        return 1;
    }

    if (counter != 42U) {
        puts("FAIL: counter was not updated");
        return 1;
    }

    puts("after: counter == 42");
    puts("PASS");
    return 0;
}
```

这是应用逻辑层的单文件 C11 示例，不是 BSP（Board Support Package，板级支持包）或硬件驱动。依赖方向为 `示例程序 -> C 标准头文件与主机 C 库`。`counter` 从进入 `main` 后开始存在，在调用 `set_counter` 的整个过程中都有效；`target` 只在该次函数调用期间保存地址值，不拥有也不延长 `counter` 的存在时间。代码不使用动态内存。以上代码是待学习者执行的主机示例，不代表已经上板验证。

## 10. 常见错误

- 写成 `set_counter(counter, 42U)`：传入的是整数值，不是 `uint32_t *` 地址。
- 忘记 `&`：函数无法从普通整数值定位原对象。
- 忘记解引用，写成 `target = NULL` 或给 `target` 重新赋地址：改变的是局部指针，不是 `counter`。
- 未初始化指针就解引用：它没有已知的有效目标。
- 判空后仍在错误分支解引用：检查必须真正保护 `*target`。
- 保存局部对象地址并在对象不再存在后使用：该地址不再指向可安全访问的原对象。
- 把主机上的指针大小或传参位置当作 STM32 结论：这些细节要按目标 ABI 和工具链资料核对。

## 11. 调试观察点

1. 调用前观察 `counter == 7U`。
2. 进入 `set_counter` 后，观察 `target` 非空；不要依赖地址的具体数字。
3. 单步执行 `*target = value`，观察 `main` 中的 `counter` 同步变为 `42U`。
4. 返回后确认成功标志为 `1U`，最后三行输出符合预期。
5. 若编译器报告“整数与指针类型不兼容”，优先检查调用处是否漏写 `&`。

## 12. 实战实验

当前主机可找到 GCC 16.2.0。将第 9 节代码保存为 `main.c` 后，在普通 Windows PowerShell 中逐条执行：

```powershell
gcc -std=c11 -Wall -Wextra -pedantic main.c -o lesson.exe
.\lesson.exe
$LASTEXITCODE
```

预期输出为：

```text
before: counter == 7
after: counter == 42
PASS
0
```

再把调用改为 `set_counter(NULL, 42U)`。先预测：函数返回 `0U`，程序打印 `FAIL: address was not accepted`，退出状态为 `1`；`counter` 不会被解引用修改。重新构建运行，并记录编译器版本、命令、实际输出与时间。不要删除判空后尝试解引用 `NULL`。

## 13. 自检题

1. `counter` 在哪里定义，谁持有它？
2. `&counter` 产生什么，`target` 保存什么？
3. 为什么函数内的 `*target` 能修改 `main` 中的 `counter`？
4. 为什么指针形参不是 `counter` 的新拥有者？
5. 判空能否证明一个非空指针一定有效？为什么本例仍可安全使用？
6. 为什么主机输出 `PASS` 仍不能令 `hardware_verified=true`？

## 14. 面试题

**问：怎样让 C 函数修改调用者的一个 `uint32_t` 对象？**

答题要点：调用者保证对象在调用期间仍存在；用 `&` 取得地址；以 `uint32_t *` 形参接收地址值；函数先检查空指针，再以 `*` 访问原对象；调用者检查返回状态和对象结果。还要说明，非空只是必要检查，不自动证明任意来源的指针都有效。

## 15. 延伸思考

- 若两个指针都保存 `&counter`，通过其中一个写入后，另一个再读取会看到哪个对象？
- 若函数只需要读取、不应修改对象，接口还缺少什么约束？这个问题留给后续 `const-volatile` 主题。
- 将来用主机对象替代硬件状态时，怎样区分“指针机制通过”和“真实硬件行为已验证”？

## 16. 本节总结

`&` 取得对象地址，类型匹配的指针可以保存并传递这个地址；对仍指向有效对象的指针使用 `*`，访问的是原对象。示例中 `main` 定义并持有 `counter`，传入地址，函数判空后修改同一对象。地址的机器表示和传参位置属于目标 ABI，不能从主机结果猜测。

## 17. 下一步

先完成实验并回答自检题，再由课程规划决定后续主题。本课生成本身不提高掌握度，也不修改 `completed` 或 mastery（掌握度）状态。

## 18. 参考资料

1. [GNU Project, *GNU C Language Introduction and Reference Manual*, version 0.1](https://www.gnu.org/software/c-intro-and-ref/manual/html_node/Pointers.html)，访问日期：2026-09-26。核对位置：`Pointers`、`Address of Data`、`Pointer-Variable Declarations`、`Dereferencing Pointers`、`Null Pointers`、`Dereferencing Null or Invalid Pointers`；用于支撑通用 C 指针、`&`、`*`、判空与无效解引用边界。
2. [GNU Project, *GNU C Language Introduction and Reference Manual: Function Parameter Variables*, version 0.1](https://www.gnu.org/software/c-intro-and-ref/manual/html_node/Function-Parameter-Variables.html)，访问日期：2026-09-26。核对位置：22.1.1 `Function Parameter Variables`；用于支撑形参变量存放调用时传入的值。
3. [Arm, *Procedure Call Standard for the Arm Architecture (AAPCS32)*, 2025Q4, 23 January 2026](https://developer.arm.com/documentation/ihi0042/latest/)，访问日期：2026-09-26。核对位置：5.1 `Fundamental Data Types`、6.5 `Parameter Passing`、8.1.2 `Pointer Types`；仅用于 Arm 32 位 ABI 边界。
4. [Arm, *Procedure Call Standard for the Arm 64-bit Architecture (AAPCS64)*, 2025Q1, 7 April 2025](https://developer.arm.com/documentation/ihi0055/latest/)，访问日期：2026-09-26。核对位置：5.8 `Pointers`、6.8 `Parameter passing`、10.1.2 `Types varying by data model`；用于说明指针表示与传参细节依赖 ABI 和数据模型。

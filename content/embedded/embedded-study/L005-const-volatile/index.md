+++
title = "用 const 与 volatile 表达访问约束"
date = "2026-09-26T15:35:47+08:00"
lastmod = "2026-09-26T15:35:47+08:00"
summary = "用主机 C11 示例区分 const 限定访问路径与 volatile 保留易变对象访问，并明确二者的能力边界。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 5
tags = ["embedded-c", "const", "volatile", "c11", "host-fake", "beginner"]
source_ids = ["gnu-c-intro-const-0-1", "gnu-c-intro-volatile-0-1", "gcc-16-2-volatiles", "arm-ihi0042-2025q4", "arm-ihi0055-2025q4"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L005"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 5 课：用 `const` 与 `volatile` 表达访问约束

本课只学习一个目标下的两个核心概念：`const` 限制通过某条访问路径修改对象；`volatile` 让对易变对象的访问具有必须保留的可观察意义。先看结果：同一个普通对象仍可由拥有者修改，但只读函数不能经 `const` 指针修改它；另一个主机对象用 `volatile` 模拟“值可能在程序控制之外改变”的存储形态，读取函数每次都通过易变访问取得值。

## 1. 本节目标

在主机最小 C11 例子中，为“只读借用”选择 `const uint32_t *`，为“可能由程序外部改变、每次访问都必须保留”的模拟存储位置选择 `volatile uint32_t`；说明两者约束什么、不保证什么，并区分主机逻辑验证与硬件验证。预计用时 30 分钟。

## 2. 它解决什么问题

上一课的 `uint32_t *` 能让函数修改调用者对象，但接口没有表达“这里只允许读”。另一方面，普通对象的读写可能在不改变普通程序结果时被编译器优化；这种模型不适合表达每次访问都可能与程序外部交互的存储位置。[2]

本课没有开发板、异步硬件或并发执行证据，只能验证类型约束和受控顺序下的逻辑。不能据此推断 STM32 寄存器、缓存、总线、HAL（Hardware Abstraction Layer，硬件抽象层）或指令行为。

## 3. 必要前置知识

已完成课程提供了单文件 C 程序、`uint32_t`、对象地址、有效指针、`&` 和 `*`。本课新增类型限定符（type qualifier）：附加在类型上的访问约束，只讨论 `const` 与 `volatile`。

左值（lvalue）是表示某个对象存储位置的表达式。这里只用它解释：经 `const uint32_t *` 解引用得到的左值不能作为赋值目标，不展开更复杂规则。

## 4. 核心原理

### 4.1 `const` 约束限定访问路径

`const uint32_t *config` 表示 `config` 指向的 `uint32_t` 经这条路径只读。GNU 手册明确说明，这类指针不能在赋值左侧解引用，并把它用于表达函数不修改传入地址所指数据。[1]

限制落在访问路径，不是给对象加上“全局永不变化”的证明。若原对象本来不是 `const`，拥有者仍可经其他有效的非 `const` 路径修改它；之后只读函数再次读取会得到新值。本课不使用强制类型转换绕过限定。

### 4.2 `volatile` 保留易变对象访问

`volatile uint32_t fake_status` 表示该对象的值可能因程序控制之外的原因被观察或改变。对它的读写需要按当前实现规定的易变访问规则处理；这就是本课所说的可观察访问（observable access，可被程序外部观察到的访问）。GNU 手册说明 GNU C 会实际执行易变对象的读写，但同一顺序点（sequence point，可理解为此前求值必须完成的边界）之间仍可能进行有限合并，`volatile` 也不会补足表达式本来未规定的求值次序。[2]

GCC（GNU Compiler Collection，GNU 编译器套件）16.2.0 文档进一步说明，什么构成一次易变访问由实现规定，同一顺序点之间的易变访问可能被重排或合并，`volatile` 也不能作为非易变内存访问的内存屏障。[3] 本例每次调用 `read_status` 只求值一次 `*status`，目标是练习按该接口读取，不据此承诺具体指令。

AAPCS32 与 AAPCS64 2025Q4 的 “Volatile Data Types” 进一步规定了各自 Arm ABI（Application Binary Interface，应用二进制接口）下的易变访问边界。[4][5] 这些约束不能泛化成所有 C 实现的固定指令数、访问时序或硬件效果。

因此，不能仅凭 `volatile` 推导出原子性（一次访问不可被拆分或交错）、线程同步、内存顺序、内存屏障、缓存维护或硬件协议保证；其中 GCC 已明确否定把它当作普通内存访问的内存屏障。[3] 其他性质需要各自的机制和目标平台资料，本课不展开。

## 5. 关键术语与直观模型

| 写法 | 直观含义 | 不保证 |
| --- | --- | --- |
| `const uint32_t *p` | 经 `p` 只能读取所指对象 | 对象不会经其他路径改变 |
| `volatile uint32_t x` | 对 `x` 的易变访问具有可观察意义 | 原子性、同步或硬件正确性 |
| Host Fake（主机替身） | 用主机对象练习硬件接口需要的形态 | 真实寄存器副作用或异步变化 |

## 6. 从输入到结果的完整流程

1. `main` 定义并持有普通对象 `config` 和易变 Host Fake 对象 `fake_status`。
2. `main` 把 `&config` 传给 `read_config`；形参把它视为 `const uint32_t *` 并只读。
3. `main` 可直接把非 `const` 的 `config` 改为新值，再次调用得到新值。
4. `main` 给 `fake_status` 写入受控值，再把地址传给 `read_status`。
5. `read_status` 经 `volatile uint32_t *` 读取一次并返回，`main` 检查结果。

两个对象都位于 `main`，生命周期覆盖全部调用。地址的传入者就是 `main`；函数只借用地址，不持有、不释放对象。这里没有额外的组装对象或硬件对象。调用流均为 `main -> 读取函数 -> main`。

## 7. 嵌入式系统中的对应位置

可迁移机制是：接口用类型说明允许的访问方式。以后读取配置可用指向 `const` 的参数；与设备交互的存储位置常需要易变限定，但必须以目标芯片和工具链文档为准。

F4、F7、H5、H7 的具体寄存器定义、访问宽度、缓存和总线差异尚未核对，也没有板卡信息，本课不猜测。迁移时应先查所选器件参考手册、勘误和工具链文档，再决定接口与验证方法。

## 8. 主机实验与硬件迁移边界

本课的 `fake_status` 只模拟类型和调用形态。由 `main` 顺序写入再读取，只能证明受控逻辑结果；它不会自行变化，也不模拟寄存器读写副作用、中断或 DMA（Direct Memory Access，直接内存访问）。

因此示例是“待学习者执行的主机逻辑验证”，不是 STM32 构建或上板证据，`hardware_verified=false`。

## 9. 最小代码示例

```c
#include <stdint.h>
#include <stdio.h>

uint32_t read_config(const uint32_t *config)
{
    return *config;
}

uint32_t read_status(volatile uint32_t *status)
{
    return *status;
}

int main(void)
{
    uint32_t config = 42U;
    volatile uint32_t fake_status = 0U;

    if (read_config(&config) != 42U) {
        puts("FAIL: initial config");
        return 1;
    }

    config = 9U;
    if (read_config(&config) != 9U) {
        puts("FAIL: updated config");
        return 1;
    }

    fake_status = 7U;
    if (read_status(&fake_status) != 7U) {
        puts("FAIL: fake status");
        return 1;
    }

    puts("PASS");
    return 0;
}
```

这是应用逻辑层的单文件示例，依赖方向为 `示例程序 -> C 标准头文件与主机 C 库`。整数接口使用固定宽度类型，不使用动态内存。示例待主机验证，待上板验证。

## 10. 常见错误

- 把 `const uint32_t *` 解释成对象永远不变：它只限制经该指针修改。
- 把 `uint32_t * const` 与本课写法混为一谈：前者涉及指针自身的限定，本课不展开。
- 用 `volatile` 代替原子操作、锁、内存屏障或缓存维护：它不提供这些保证。
- 看到主机 `PASS` 就声称硬件正确：Host Fake 没有真实硬件副作用。
- 从一次汇编输出推断全部编译器和优化级别：Arm ABI 也不是所有 C 实现的统一指令承诺。

## 11. 调试观察点

1. 在 `read_config` 入口确认指针指向 `main` 的 `config`，但函数只读取。
2. 观察 `config` 由 `main` 从 `42U` 改为 `9U`，说明 `const` 不等于全局不变。
3. 观察 `fake_status` 由 `main` 写成 `7U`，`read_status` 返回 `7U`。
4. 可选查看当前 GCC 的优化汇编，但只记录实际结果，不预设指令数量、宽度或时序。

## 12. 实战实验

当前环境可找到 GCC 16.2.0，但本课程文件不把工具探测当成构建证据。将第 9 节保存为 `main.c`，在普通 Windows PowerShell 中运行：

```powershell
gcc -std=c11 -Wall -Wextra -pedantic main.c -o lesson.exe
.\lesson.exe
$LASTEXITCODE
```

预期输出为 `PASS`，退出状态为 `0`。记录编译器版本、命令、实际输出和时间。

再单独创建预期失败的 `const_fail.c`，不要合入正常程序：

```c
#include <stdint.h>

void overwrite(const uint32_t *config)
{
    *config = 1U;
}
```

执行 `gcc -std=c11 -Wall -Wextra -pedantic-errors -c const_fail.c`。预期 GCC 给出诊断且命令失败；诊断原文依工具链而异。这个失败用例验证“不能经该 `const` 路径赋值”，不是运行实验。

失败排查：

- 若提示找不到 `gcc`，先运行 `gcc --version`；仍找不到时需要安装 GCC 或把其目录加入 `PATH`，不要把工具缺失误判为代码错误。
- 若正常示例编译失败，先确认文件内容与第 9 节一致，并从第一条诊断开始处理；不要先忽略警告选项。
- 若程序没有输出 `PASS`，在三个 `if` 处观察实际值，并确认运行的是刚生成的 `lesson.exe`。
- 若 `const_fail.c` 反而编译成功，确认命令包含 `-pedantic-errors`，且形参仍是 `const uint32_t *`；记录编译器版本和完整命令后再判断工具链差异。

## 13. 自检题

1. 两个对象在哪里定义，谁持有，谁传入地址？
2. 为什么 `read_config` 不能执行 `*config = 1U`？
3. 为什么 `main` 仍能执行 `config = 9U`？
4. `volatile` 保留什么，又不保证哪四类事情？
5. 为什么 `fake_status` 不能证明真实寄存器行为？

## 14. 面试题

**问：`const` 和 `volatile` 分别解决什么问题？**

答题要点：`const` 表达通过限定访问路径不修改对象，改善接口约束，但不证明对象处处不变；`volatile` 表达对象可能在程序控制之外被观察或改变，使相应访问具有可观察意义，但不等于原子、同步、屏障、缓存维护或硬件协议。

## 15. 延伸思考

- 若读取函数既不应写对象，又必须保留易变访问，两个限定符可能如何组合？先写出猜想，留待后续核对。
- 迁移到具体 STM32 时，哪些结论必须从器件参考手册和勘误重新确认？

## 16. 本节总结

`const uint32_t *` 给函数一条只读访问路径；对象若原本非 `const`，仍可经其他有效路径变化。`volatile` 让易变对象访问具有必须保留的意义，但不提供并发与硬件层保证。示例中对象由 `main` 定义、持有并传址，函数只借用和读取。

## 17. 下一步

先完成正常运行和预期失败编译两个实验，再回答自检题。课程生成本身不提高掌握度，也不修改 `completed` 或 mastery（掌握度）状态。

## 18. 参考资料

1. [GNU Project, *GNU C Language Introduction and Reference Manual: const Variables and Fields*, Edition 0.1](https://www.gnu.org/software/c-intro-and-ref/manual/html_node/const.html)，访问日期：2026-09-26。核对位置：21.1；支撑指向 `const` 的访问限制与只读函数参数。
2. [GNU Project, *GNU C Language Introduction and Reference Manual: volatile Variables and Fields*, Edition 0.1](https://www.gnu.org/software/c-intro-and-ref/manual/html_node/volatile.html)，访问日期：2026-09-26。核对位置：21.2；支撑 GNU C 中易变对象访问、有限合并和求值次序边界。
3. [GNU Project, *Using the GNU Compiler Collection (GCC): When is a Volatile Object Accessed?*, GCC 16.2.0](https://gcc.gnu.org/onlinedocs/gcc-16.2.0/gcc/Volatiles.html)，访问日期：2026-09-26。核对位置：6.10；支撑 GCC 对易变访问的实现边界、顺序点之间可能重排或合并，以及 `volatile` 不能充当普通内存访问的内存屏障。
4. [Arm, *Procedure Call Standard for the Arm Architecture (AAPCS32)*, 2025Q4](https://developer.arm.com/documentation/ihi0042/latest/)，发布日期：2026-01-23；访问日期：2026-09-26。核对位置：8.1.5 `Volatile Data Types`；仅用于 Arm 32 位 ABI 边界。
5. [Arm, *Procedure Call Standard for the Arm 64-bit Architecture (AAPCS64)*, 2025Q4](https://developer.arm.com/documentation/ihi0055/latest/)，发布日期：2026-01-23；访问日期：2026-09-26。核对位置：`Volatile data types`；仅作 ABI 范围对照，不代表 STM32 硬件验证。

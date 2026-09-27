+++
title = "用链接属性判断名字能否跨源文件使用"
date = "2026-09-27T16:13:22+08:00"
lastmod = "2026-09-27T16:13:22+08:00"
summary = "用最小两源文件 C11 主机程序区分外部链接与内部链接，并判断另一翻译单元能否引用同一对象。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 7
tags = ["embedded-c", "linkage", "translation-unit", "c11", "host-fake", "beginner"]
source_ids = ["gnu-c-manual-file-scope-variables-20-6", "gnu-c-manual-extern-declarations-20-8", "gcc-online-link-options-3-16-2026", "st-um2609-rev18"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L007"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 7 课：用链接属性判断名字能否跨源文件使用

程序拆成多个 `.c` 文件后，一个文件里的名字不一定能被另一个文件引用。本课只学习标识符的链接属性（linkage）：它回答不同翻译单元中的同名标识符能否表示同一实体。实验在普通 Windows 主机完成，不讨论链接脚本、符号表或 MCU 内存布局。

## 1. 本节目标

能在最小两源文件 C11 程序中，根据外部链接或内部链接判断另一个源文件能否引用同一对象，并说明链接属性不等于存储期或物理地址。预计用时 30 分钟。

本课只有一个新核心概念：标识符的链接属性。

## 2. 它解决什么问题

上一课用存储期判断“对象何时存在”。当程序拆成 `counter.c` 和 `main.c`，还要回答另一个问题：`main.c` 写下 `shared_count` 时，它能否指向 `counter.c` 定义的那个对象？

链接属性解决名字跨翻译单元关联的问题。它不决定对象放在哪段 RAM，也不决定对象活多久。

## 3. 必要前置知识

沿用已学的 `main`、函数调用、`uint32_t`、对象和静态存储期。翻译单元（translation unit）是一个 `.c` 文件经过预处理后交给编译器的一份输入；本课把它当作跨源文件边界的观察单位，不展开预处理器细节。

声明（declaration）告诉当前翻译单元名字和类型；定义（definition）真正引入对象或函数体。一个定义也属于声明，但仅有声明不一定创建对象。

## 4. 核心原理

### 4.1 外部链接

外部链接（external linkage）允许不同翻译单元中的相应声明表示同一实体。文件作用域下未写 `static` 的对象定义在本例中具有外部链接。[1] 头文件中的 `extern uint32_t shared_count;` 只声明它，让使用者知道名字和类型，并引用其他位置的全局对象。[2]

共享对象只定义一次。`extern` 声明不是对象副本，也不会把对象从一个文件搬到另一个文件。

### 4.2 内部链接

内部链接（internal linkage）把名字的关联限制在当前翻译单元。文件作用域的 `static uint32_t private_count` 是本课的最小写法：其他翻译单元即使写下同名的外部声明，也不能借此引用这个私有对象。[1]

### 4.3 不要与存储期混淆

下面两个对象都具有静态存储期，都会在整个程序执行期间存在；但链接属性不同：

```c
uint32_t shared_count = 0U;        /* 静态存储期，外部链接 */
static uint32_t private_count = 0U; /* 静态存储期，内部链接 */
```

因此，存储期回答“对象何时存在”，链接属性回答“不同翻译单元中的名字能否表示同一实体”。两者都不能直接推出物理内存位置。

## 5. 关键术语与直观模型

| 术语 | 它回答的问题 | 本课直观模型 |
| --- | --- | --- |
| 翻译单元 | 编译器这次看到哪份输入 | 预处理后的一个 `.c` 文件 |
| 外部链接 | 名字能否跨翻译单元关联同一实体 | 对外的门牌 |
| 内部链接 | 名字是否只在当前翻译单元关联 | 文件内部的门牌 |
| 声明 | 当前文件如何认识名字 | 类型说明 |
| 定义 | 实体在哪里真正出现 | 唯一对象或函数体 |

“门牌”只帮助理解名字的关联范围，不代表真实地址或链接器内部实现。

## 6. 从输入到结果的完整流程

1. `counter.c` 定义 `shared_count`；`counter` 模块持有这唯一对象。
2. `counter.h` 声明对象和公开函数。它不持有对象。
3. `counter.c` 与 `main.c` 各自包含该头文件，形成两个翻译单元。
4. 编译 `main.c` 时，`extern` 声明让编译器知道共享对象的名字和类型。
5. 最终链接步骤接收多个输入，并把可关联的外部引用连接到唯一的外部定义。[3]
6. 运行时调用流为 `main -> counter_next -> shared_count -> 返回值 -> main`。

本例没有依赖注入者：没有对象被运行时“塞给”模块。组装发生在构建命令把两个源文件纳入同一程序时，不能把这误称为依赖注入。

## 7. 嵌入式系统中的对应位置

模块通常在头文件公开声明，在一个 `.c` 文件提供定义，再由应用使用。这个 C 语言边界可迁移到 STM32 工程；STM32CubeIDE 也包含代码编译与链接功能。[4]

F4、F7、H5、H7 的具体工程选项、启动文件和内存布局未在本课核对。链接属性不因芯片系列而变成寄存器或地址规则；具体工具链配置留到后续课程。

## 8. 主机实验与硬件迁移边界

Host Fake（主机替身）只验证两个主机翻译单元能否共享同一 C 对象，以及受控错误能否在构建时暴露。它不能验证开发板、启动代码、时钟、外设或 MCU 地址。

没有开发板、构建日志、测量或上板记录，因此 `hardware_verified=false`。以下代码是待学习者在主机执行的示例；主机结果不能替代上板验证，也不能据此声称硬件已验证。

## 9. 最小代码示例

`counter.h`（模块公开声明层；被模块实现与应用共同依赖；不持有对象）：

```c
#ifndef COUNTER_H
#define COUNTER_H

#include <stdint.h>

extern uint32_t shared_count;
uint32_t counter_next(void);

#endif
```

`counter.c`（模块实现与实例层；定义并持有程序全程存在的对象）：

```c
#include "counter.h"

uint32_t shared_count = 0U;

uint32_t counter_next(void)
{
    shared_count += 1U;
    return shared_count;
}
```

`main.c`（应用使用层；依赖公开声明，不定义共享对象）：

```c
#include "counter.h"
#include <stdio.h>

int main(void)
{
    uint32_t first = counter_next();
    uint32_t second = counter_next();

    printf("first=%u second=%u shared=%u\n",
           (unsigned int)first,
           (unsigned int)second,
           (unsigned int)shared_count);

    if ((first != 1U) || (second != 2U) || (shared_count != 2U)) {
        puts("FAIL");
        return 1;
    }

    puts("PASS");
    return 0;
}
```

依赖方向是 `main.c -> counter.h <- counter.c`；应用不依赖模块内部细节。代码使用 C11 子集、固定宽度公开接口且不使用动态内存。

## 10. 常见错误

- 在头文件写 `uint32_t shared_count = 0U;`，被多个 `.c` 包含后产生多个定义。
- 只写 `extern` 声明，却忘记把唯一定义所在的 `.c` 文件加入构建。
- 认为 `extern` 会创建或复制对象。
- 认为文件作用域 `static` 只是“延长寿命”，忽略它还赋予名字内部链接。
- 从链接属性猜测对象位于栈、堆、Flash 或某个 RAM 地址。

内部链接的受控对照只用于诊断。`private.c` 定义：

```c
#include <stdint.h>
static uint32_t private_count = 0U;
```

若 `bad_main.c` 写 `extern uint32_t private_count;` 并读取它，这个外部名字不会指向 `private.c` 的内部链接对象；生成可执行文件时应无法解析该外部引用。不同工具链的诊断文本可能不同，不要背错误原句。

## 11. 调试观察点

1. 先检查头文件中是声明，`counter.c` 中是唯一的定义。
2. 检查构建命令是否同时包含两个正常源文件。
3. 在 `counter_next` 前后观察 `shared_count` 从 `0U` 到 `1U`、`2U`。
4. 若构建失败，先区分“缺少定义”和“重复定义”，不要立即猜测芯片或地址问题。

## 12. 实战实验

在同一空目录创建第 9 节的三个文件，然后在 PowerShell 执行：

```powershell
gcc --version
gcc -std=c11 -Wall -Wextra -Wpedantic counter.c main.c -o linkage-demo.exe
.\linkage-demo.exe
$LASTEXITCODE
```

预期输出为 `first=1 second=2 shared=2`、`PASS`，退出状态为 `0`。请记录编译器版本、完整命令、输出、退出状态和时间；课程生成不等于实验成功。

对照实验：另建空目录放入第 10 节的两个文件，让 `bad_main.c` 在 `main` 中返回 `(int)private_count`，再尝试生成可执行文件。先预测失败原因，再记录实际诊断；不要把失败样例混入正常目录。

失败排查：

- 找不到 `gcc`：先确认 GCC 已安装且其目录已加入 `PATH`，重新打开 PowerShell 后再执行 `gcc --version`。
- 正常示例构建失败：确认三个文件位于同一目录、文件名和 `#include "counter.h"` 一致，并确认命令同时包含 `counter.c` 与 `main.c`。
- 正常程序输出不是预期值：确认只在 `counter.c` 定义一次 `shared_count`，且初值、递增次数和判断条件没有被改动。
- 故意失败用例反而成功：确认 `bad_main.c` 确实读取 `private_count`、构建命令同时包含两个反例源文件，且没有另一个非 `static` 的 `private_count` 定义参与链接。

## 13. 自检题

1. 链接属性解决什么问题？与存储期有什么不同？
2. `shared_count` 在哪里声明、在哪里定义、由谁持有？
3. 谁使用 `extern` 声明？本例是否存在依赖注入者？
4. 为什么文件作用域 `static` 对象仍可活到程序结束，却不能由另一翻译单元引用？
5. 写出正常路径的调用与访问流。

## 14. 面试题

**问：在头文件写 `extern uint32_t count;`，是否已经定义了对象？**

答题要点：这里是声明，使当前翻译单元知道外部链接名字及类型；对象仍需在一个 `.c` 文件中有唯一定义。[2] 使用者通过外部链接关联同一实体。链接属性管名字关联，静态存储期管对象存在时间，两者不可混为一谈。

## 15. 延伸思考

- 若两个 `.c` 文件各自定义同名的文件作用域 `static` 对象，它们是一个对象还是两个对象？
- 为什么把私有对象留在实现文件，可以减少模块之间的名字耦合？
- 将来把主机示例迁入 STM32 工程时，应如何确认两个源文件都参与了构建？

## 16. 本节总结

外部链接让不同翻译单元中的相应声明表示同一实体；文件作用域 `static` 让名字具有内部链接，只在当前翻译单元内关联。声明让名字可被认识，唯一的定义提供实体。链接属性不回答对象寿命或物理位置。

## 17. 下一步

先完成正常与失败对照实验并回答自检题。课程生成本身不会更新 `completed` 或 mastery（掌握度）；下一主题由后续计划决定。

## 18. 参考资料

1. [GNU Project, *GNU C Language Manual: File-Scope Variables*](https://www.gnu.org/software/c-intro-and-ref/manual/html_node/File_002dScope-Variables.html)，在线版第 20.6 节；访问日期：2026-09-27。支撑文件作用域变量、跨编译模块共享以及文件作用域 `static` 的边界。[1]
2. [GNU Project, *GNU C Language Manual: Extern Declarations*](https://www.gnu.org/software/c-intro-and-ref/manual/html_node/Extern-Declarations.html)，在线版第 20.8 节；访问日期：2026-09-27。支撑 `extern` 声明引用在其他位置定义的全局对象，且该声明本身不分配对象空间。[2]
3. [GNU Project, *Using the GNU Compiler Collection: Link Options*](https://gcc.gnu.org/onlinedocs/gcc/Link-Options.html)，2026 在线版第 3.16 节；访问日期：2026-09-27。支撑 GCC 最终链接步骤接收对象文件等输入；不把 GCC 选项当成 C11 语言定义。[3]
4. [STMicroelectronics, *STM32CubeIDE user guide*](https://www.st.com/resource/en/user_manual/um2609-stm32cubeide-user-guide-stmicroelectronics.pdf)，UM2609 Rev 18，June 2026；访问日期：2026-09-27。支撑 STM32CubeIDE 提供代码编译和链接能力；不支撑 C 语言链接属性定义。[4]

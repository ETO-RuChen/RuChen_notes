+++
title = "调用栈与堆：从函数返回和资源归还判断存储何时可用"
date = "2026-10-02T23:55:49+08:00"
lastmod = "2026-10-02T23:55:49+08:00"
summary = "用固定调用深度和静态资源池 Host Fake 区分自动对象的生命周期、调用栈的常见实现模型，以及动态资源的显式释放责任。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 16
tags = ["stack", "heap", "stack-frame", "storage-duration", "resource-ownership", "host-fake", "c11", "beginner"]
source_ids = ["st-pm0214-rev10", "gnu-gcc-internals-17-frame-layout", "gnu-c-language-manual-dynamic-memory", "gnu-c-manual-local-variables-20-5", "gnu-c-manual-file-scope-variables-20-6"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L016"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 调用栈与堆：从函数返回和资源归还判断存储何时可用

> 阶段：`startup-linking-memory`（启动、链接与存储器）  
> 主题：`stack-heap`（调用栈与堆）  
> 预计用时：核心阅读约 45 分钟；完成主机实验约 45-75 分钟  
> 验证状态：Host Fake（主机伪实现）已在 Windows 主机编译并运行通过；未上板，`hardware_verified=false`

## 1. 本节目标

本课的唯一核心目标是：

> 学习者能基于函数调用和显式资源管理，判断自动对象何时结束可用、堆块由谁负责释放，并说明在资源受限嵌入式软件中为何默认优先使用确定的静态或调用栈存储。

本课只引入两个新核心概念，名称与学习计划保持一致：

1. **调用栈的帧式占用**。
2. **堆的显式分配与释放责任**。

学完后，你应能面对一段代码回答三类问题：函数返回后，某个普通局部对象是否仍存在；申请到的资源由谁归还；为什么一个“总内存看起来够”的系统仍可能在运行过程中申请失败。

本课不讨论分配器算法、递归、可变长数组、RTOS（实时操作系统）堆、DMA（直接存储器访问）、异常入栈、缓存、MPU（内存保护单元）或具体 STM32 的 RAM 地址。它们都需要后续课程和具体资料。

## 2. 它解决什么问题

先看两个常见但性质不同的问题。

### 2.1 函数已经返回，为什么保存的局部变量地址不能再用

```c
static const uint32_t *bad_address(void)
{
    uint32_t local_value = 42U;
    return &local_value; /* 错误示意：不要运行或解引用这个返回值。 */
}
```

`local_value` 是普通局部对象，具有自动存储期。离开它所在的块时，对象生命周期结束。返回地址只是复制了一个数值，并不能延长对象的生命周期。之后通过该地址访问对象属于未定义行为：C 语言不承诺会发生什么。本课的可运行实验不会这样做。[4]

“局部对象生命周期结束”是 C 语言层面的规则；“编译器通常怎样用调用栈承载活动调用状态”是实现模型。二者有关，但不能直接说“每个局部变量必然在物理栈中”。优化器可能把值保存在寄存器中，也可能消除对象；具体布局由目标 ABI（应用二进制接口）、编译器和优化选项决定。[1][2]

### 2.2 函数已经返回，为什么申请的资源可能仍被占用

动态分配得到的块遵循另一种责任：它不会仅因申请函数返回而自动归还。成功取得块的代码必须明确谁是所有者，以及正常、失败和提前退出路径最终由谁释放。遗漏释放会使可用资源逐渐减少；申请本身也可能失败。

本课不用真实 `malloc`/`free`。我们用一个静态数组模拟三个固定资源槽，并主动定义以下 Host Fake 契约：

- `pool_acquire` 成功时交付一个槽编号，失败时返回无效编号；
- 获得槽的所有者负责调用 `pool_release`；
- 释放后槽可再次申请；
- 暂时不释放一个槽，可以安全观察“账本仍显示占用”，最后再清理。

这不是通用堆分配器，也不模拟某个 C 运行库；它只把“取得、持有、失败、归还”的责任变成可观察结果。

### 2.3 先看最小可观察结果

运行第 9 节程序时，预期输出的关键顺序如下：

```text
== nested calls ==
enter level_1 depth=1 token=11
enter level_2 depth=2 token=22
enter level_3 depth=3 token=33
leave level_3 depth=3 token=33
leave level_2 depth=2 token=22
leave level_1 depth=1 token=11
after calls depth=0

== fixed pool ledger ==
acquire owner=101 slot=0 used=1
acquire owner=102 slot=1 used=2
acquire owner=103 slot=2 used=3
acquire owner=104 failed used=3
release owner=102 slot=1 used=2
acquire owner=104 slot=1 used=3
leave owner=103 allocated used=1
cleanup complete used=0
PASS
```

这里观察到的不是内存地址，而是两个安全指标：活动调用深度随嵌套调用先增加、再随返回减少；资源槽只有经过显式释放才从账本中恢复可用。

## 3. 必要前置知识

本课只复核已经完成的内容，不引入新的前置主题。

### 3.1 自动存储期和静态存储期

- 普通块内局部对象通常具有自动存储期：执行到定义时取得本次对象的存储，离开块后该次生命周期结束。[4]
- 文件作用域对象和带 `static` 的对象具有静态存储期：在整个程序执行期间存在。[5]
- 指针保存地址，不拥有被指对象，也不会延长其生命周期。

这三点是语言规则。它们不等价于某个具体地址、链接段或处理器寄存器。

### 3.2 函数调用

调用者把控制交给被调用函数；被调用函数完成后返回调用点。嵌套调用意味着：`main` 尚未结束时进入 `level_1`，`level_1` 尚未结束时又进入 `level_2`。这些尚未返回的调用称为活动调用。

### 3.3 ELF、map 与运行期证据的边界

链接脚本决定构建输入如何放入输出布局，ELF（可执行与可链接格式）和 map 文件能提供构建期的段、符号、地址与大小证据。但它们单独不能证明一次运行实际经过了多少层调用，也不能证明动态资源的峰值占用。运行期问题还需要调试记录、计数、水位或测量证据。

## 4. 核心原理

### 4.1 核心概念一：调用栈的帧式占用

调用栈（call stack）解决的问题是：当函数 A 尚未完成便调用函数 B 时，系统必须保留足够的活动调用状态，使 B 返回后 A 能继续。把与一次活动调用相关的状态抽象成一层调用帧（stack frame），就得到一个直观模型：

```text
main 调用 level_1       活动调用：main -> level_1
level_1 调用 level_2    活动调用：main -> level_1 -> level_2
level_2 调用 level_3    活动调用：main -> level_1 -> level_2 -> level_3
level_3 返回            活动调用：main -> level_1 -> level_2
level_2 返回            活动调用：main -> level_1
level_1 返回            活动调用：main
```

“帧式”强调的是活动状态随调用嵌套累积、随返回撤销的关系，不承诺每个 C 局部对象都在一块连续物理内存中。ST 的 Cortex-M4 编程手册给出了该处理器的栈指针等核心寄存器定义；GCC 内部手册则把栈方向、帧增长方向、局部槽偏移和返回地址位置都作为目标后端相关事项。这正说明实际帧布局必须结合目标 ABI、工具链和编译选项核对，不能由一次主机地址打印推导所有平台。[1][2]

#### 这个机制的五个问题

| 问题 | 本课答案 |
| --- | --- |
| 它解决什么问题 | 保存尚未返回的调用所需状态，使被调用函数返回后，调用者能继续执行。 |
| 对象或记录在哪里定义 | C 源码定义函数、参数和自动对象；实际帧规则由 ABI、编译器后端和优化共同决定。 |
| 谁持有它 | 某次调用活动期间，由该调用的执行上下文持有；源码通常不直接拥有或管理物理帧。 |
| 谁产生或注入它 | 调用者发起调用；编译器按目标规则生成进入、调用和返回代码。这里没有业务层“依赖注入”。 |
| 调用如何流动 | 调用者进入被调用者，活动深度增加；被调用者返回，相关活动状态撤销，控制回到调用者。 |

#### 自动对象和调用帧不能画等号

初学时可用“局部变量常由调用帧承载”建立直觉，但判断代码正确性必须先用语言生命周期：

- 在函数返回前，仍处于生命周期内的自动对象可以按规则访问；
- 离开对象所在块后，对象生命周期结束，即使旧地址的数字看起来没变也不能再访问；
- 是否真的给某个对象分配栈槽，要看这一次目标代码；
- 调用帧里具体保存参数、局部槽、寄存器还是返回信息，不能只凭 C 源码猜测。

### 4.2 核心概念二：堆的显式分配与释放责任

堆（heap）在本课中指由动态分配器管理、通过显式请求取得并通过显式操作归还的存储资源。它解决的问题是：当所需数量或寿命不能仅靠固定静态对象和函数块边界表达时，程序可以在运行期请求一块存储。

灵活性带来三个必须正面处理的约束：

1. 请求可能失败，调用者必须检查结果，不能假定总会成功。
2. 函数返回不会自动归还已分配块，必须指定所有者和释放路径。
3. 长期交错申请、释放不同大小的块可能产生内存碎片（memory fragmentation）：空闲空间分散后，总空闲量可能不小，但无法满足某次连续块请求。实际表现取决于分配器实现，不能从本课固定槽模型推断具体程度。

GNU 项目的 *GNU C Language Introduction and Reference Manual* 在“Dynamic Memory Allocation”一节说明：`malloc` 无法取得存储时返回空指针，取得的对象通过 `free` 显式释放。[3] 这只用于核对通用接口层面的失败检查和释放动作，不代表 STM32 工程所选 C 库的分配算法、线程安全策略、堆边界、失败诊断或碎片特征。目标工程的这些细节目前均为**待核对**。

#### 这个机制的五个问题

| 问题 | 本课 Host Fake 中的答案 |
| --- | --- |
| 它解决什么问题 | 在运行过程中从有限资源池取得一个当前可用槽，并在不再需要时归还。 |
| 对象或记录在哪里定义 | `PoolSlot` 类型和池接口在源码中声明；三个槽存放在静态对象 `g_pool` 中。 |
| 谁持有它 | 成功申请者持有返回的槽编号；账本同时记录 `owner_id`。 |
| 谁产生或注入它 | `main` 把所有者编号交给 `pool_acquire`；池把槽编号交付给调用者。这里只是参数传递，不引入架构中的依赖注入。 |
| 资源流如何走 | 初始化为空闲 -> 申请成功并记录所有者 -> 所有者使用编号 -> 同一所有者显式释放 -> 再次可用。无空闲槽时走失败分支。 |

#### “所有者”是责任，不是指针本身

本课把所有者（owner）定义为“负责决定资源何时释放的代码实体”。一个变量里保存槽编号，并不自动证明它承担释放责任；责任必须由接口契约和控制流明确约定。

例如，函数把槽编号交给上层后，需明确属于哪一种情况：

- 所有权一并交给上层，由上层最终释放；
- 函数仍保留所有权，上层只能临时借用；
- 失败时没有产生所有权，调用者不得假装持有有效槽。

本课只采用第一种：`main` 成为成功结果的所有者，并在已知路径释放。

### 4.3 为什么嵌入式系统默认偏向确定的存储

这里的“默认优先”不是“永远禁止动态分配”，而是从证据成本出发的工程选择。

静态对象的数量和大小通常能从源码及链接产物追溯；有界调用链的活动深度可结合目标代码、静态分析和运行水位评估。动态分配还要额外证明峰值、失败处理、释放完整性、长期碎片和分配耗时是否满足约束。资源有限且长期运行的系统尤其重视这种可预测性。

因此合理的起点是：

1. 数量固定、贯穿程序的资源，优先考虑静态存储。
2. 生命周期严格局限于一次有界调用的临时状态，优先考虑自动对象，并评估调用深度与单次占用。
3. 确实需要运行期可变数量或跨调用寿命时，再引入受约束的动态策略，同时定义失败、所有权、上限和观测方法。

这仍不是安全证明。静态对象也可能过大，自动对象也可能使调用栈边界不足；“不用堆”不等于“不会耗尽内存”。

## 5. 关键术语与直观模型

| 术语 | 准确定义 | 本课直观模型 | 不应误解为 |
| --- | --- | --- | --- |
| 调用栈（call stack） | 按嵌套调用关系维护活动调用状态的运行时机制 | 尚未返回的调用清单 | C 标准保证每个局部变量都在一段物理栈 RAM |
| 调用帧（stack frame） | 与一次活动函数调用关联的状态模型 | 清单中的一层 | 所有编译器都使用相同字段和布局 |
| 栈指针（stack pointer） | 处理器或 ABI 用来追踪调用栈位置的状态 | 指向当前边界的标记 | 可脱离目标资料猜出的固定地址 |
| 自动存储期（automatic storage duration） | 对象生命周期随相应块进入和离开而开始、结束 | 只在这次进入块期间存在 | 一定分配在物理栈上 |
| 静态存储期（static storage duration） | 对象在整个程序执行期间存在 | 从程序开始一直存在 | 一定放在某个未经核对的 SRAM 地址 |
| 动态存储期（allocated storage duration） | 通过分配取得、直到显式释放才结束的对象存储期 | 领用后必须归还的资源 | 函数返回便自动释放 |
| 所有者（owner） | 对资源最终释放负责的代码实体 | 领用登记人 | 保存地址或编号的任何变量 |
| 栈溢出（stack overflow） | 活动调用所需空间超过可用调用栈边界 | 活动层数和每层需求超过预算 | 本课故意触发的实验现象 |
| 内存碎片（memory fragmentation） | 空闲空间分散，影响连续请求满足能力的现象 | 有空位但形状不适合请求 | 本课固定等大槽可以完整模拟的现象 |
| Host Fake（主机伪实现） | 在主机上用受控状态模拟目标机制的逻辑替身 | 深度计数器和静态资源账本 | 真实 MCU 栈或真实堆分配器 |

## 6. 从输入到结果的完整流程

### 6.1 嵌套调用流程

输入是 `main` 发起的一条固定调用链，结果是深度回到零。

```text
main
  -> call_level_1：定义本次调用的 local_token=11，深度 0 -> 1
       -> call_level_2：定义 local_token=22，深度 1 -> 2
            -> call_level_3：定义 local_token=33，深度 2 -> 3
                 先打印退出信息，再结束 level_3 的对象生命周期
            <- level_3 返回，深度 3 -> 2
            先打印退出信息，再结束 level_2 的对象生命周期
       <- level_2 返回，深度 2 -> 1
       先打印退出信息，再结束 level_1 的对象生命周期
  <- level_1 返回，深度 1 -> 0
main 检查深度必须为 0
```

`local_token` 只在所属函数返回前按值打印。程序既不保存它的地址，也不在其生命周期结束后访问它。深度计数是 Host Fake 自己维护的逻辑记录，不是真实栈指针或字节占用量。

### 6.2 固定池资源流程

输入是一系列所有者编号，结果是账本中每个槽的占用变化。

```text
pool_init
  -> 3 个槽全部空闲

owner 101 acquire -> slot 0
owner 102 acquire -> slot 1
owner 103 acquire -> slot 2
owner 104 acquire -> 失败，因为没有空闲槽

owner 102 release slot 1
owner 104 acquire -> 复用 slot 1

释放 101 和 104，故意暂不释放 103
  -> used 仍为 1，说明函数流程走到这里并不会自动归还槽

owner 103 release slot 2
  -> used 回到 0
```

失败分支没有返回一个可用槽，因此不会产生所有权。释放时同时核对槽编号、占用状态和所有者编号，避免把错误归还悄悄当作成功。

### 6.3 声明、实现、实例化、组装、使用

这五个动作描述代码从规则到运行的不同阶段，不应混为一谈。

| 动作 | 本课位置 | 做了什么 | 生命周期或责任 |
| --- | --- | --- | --- |
| 声明 | `PoolSlot`、常量、函数原型 | 规定数据形状和可调用接口 | 声明本身不申请运行期槽 |
| 实现 | `pool_acquire`、`pool_release`、三个调用函数的函数体 | 写出查找、核对、计数和调用流程 | 实现定义规则，但不等于某次运行已执行 |
| 实例化 | `static PoolSlot g_pool[POOL_SLOT_COUNT]` 和各函数的 `local_token` | 建立具体对象 | `g_pool` 为静态存储期；每个 `local_token` 为该次块进入产生的自动对象 |
| 组装 | `main` 先初始化池，再安排调用与申请/释放顺序 | 把函数和具体对象连成一个可运行场景 | `main` 明确每个成功槽的所有者和清理路径 |
| 使用 | 调用函数、检查返回值、打印和断言结果 | 消费接口产生可观察结果 | 使用者必须遵守对象生命周期和释放契约 |

本课虽然区分这五个动作，但不引入函数指针、依赖注入或组合根；这里只分析一个单文件程序的对象与资源关系。

## 7. 嵌入式系统中的对应位置

### 7.1 可迁移的方法

从主机迁移到 STM32F4、F7、H5 或 H7 时，真正可迁移的是核对方法，而不是某个地址或默认大小：

1. 从源码和目标代码确认实际调用链，而不是只看函数名猜深度。
2. 从实际链接脚本、map/ELF 和启动配置确认构建时预留的 RAM 边界。
3. 从所用编译器、目标 ABI 和优化选项确认帧布局及栈使用报告的含义。
4. 从所选 C 库及工程配置确认是否启用动态分配、堆从哪里取得空间、失败如何报告。
5. 用目标上的水位、故障记录或受控压力测试补充运行证据。

这套方法适用于 F4、F7、H5、H7；系列差异应在具体器件、具体工具链和具体工程出现后再核对，不能先罗列型号特性代替分析。

### 7.2 当前不能声称的内容

本次没有具体 MCU、开发板、目标工具链工程、目标链接脚本、启动文件、STM32 构建日志或上板记录，因此以下内容均为待核对：

- 实际 RAM 区域及地址；
- 栈、堆的预留大小与增长方向；
- 启动文件中边界符号的名称和含义；
- 某个局部对象是否真的占用栈槽；
- 某 C 库的分配算法、线程安全、碎片特征和失败诊断；
- 栈溢出时处理器产生何种具体故障及能否被检测。

### 7.3 与长期 Device Framework 项目的关系

后续 Device Framework（设备框架）会让接口对象、BSP（板级支持包）对象和应用对象具有清晰生命周期。本课只留下一个判断准则：任何跨函数保存的对象或资源，都必须能回答“谁持有、活多久、谁释放”。项目代码等到架构阶段再建立，本课不提前引入。

## 8. 主机实验与硬件迁移边界

### 8.1 本课能验证什么

Host Fake 可以验证：

- 固定三层调用时，逻辑活动深度按 `1 -> 2 -> 3 -> 2 -> 1 -> 0` 变化；
- 自动对象只在所属函数返回前被访问；
- 三个槽占满后第四次申请进入失败分支；
- 释放一个槽后可以再次申请；
- 暂不释放的槽仍在账本中占用；
- 完整清理后占用数回到零。

### 8.2 本课不能验证什么

它不能证明：

- 主机或 STM32 的真实调用帧有多少字节；
- `local_token` 位于某个物理栈地址；
- 真实堆分配器会采用固定槽；
- 真实工程不会栈溢出、内存泄漏或碎片化；
- 仅凭源码和 Host Fake 模型，不能证明代码已经通过某个编译器构建或在开发板运行；本次主机构建结论另有 `host-test.log` 作为证据，仍不代表已上板。

代码已在本次运行中完成主机构建和逻辑验证；这只验证 Host Fake 的预期控制流。硬件迁移内容仍为“通用步骤，待具体器件和资料核对”。

### 8.3 获得硬件后的迁移步骤

1. 记录完整器件型号、开发板、编译器与版本、优化选项。
2. 保存实际链接脚本、map/ELF 和启动文件的版本证据。
3. 按工具链官方方法取得函数栈使用或目标代码证据，人工检查关键调用链。
4. 若工程允许动态分配，记录 C 库、堆配置、最大请求、失败处理和释放责任。
5. 设计不会破坏设备的边界实验，记录构建日志和运行结果。
6. 只有证据完整后，才能把相应结论改为硬件已验证。

## 9. 最小代码示例

下面是一个单文件 C11 示例。它只依赖标准输入输出和固定宽度整数头文件；资源池由静态数组实现，不调用真实动态内存。所有对外形态的参数和返回值都使用固定宽度整数。

```c
#include <stdint.h>
#include <stdio.h>

enum {
    POOL_SLOT_COUNT = 3
};

#define POOL_INVALID_SLOT UINT32_MAX

typedef struct {
    uint32_t owner_id;
    uint8_t in_use;
} PoolSlot;

/* 声明：公开本文件实验要使用的固定宽度接口。 */
static void pool_init(void);
static uint32_t pool_acquire(uint32_t owner_id);
static uint32_t pool_release(uint32_t owner_id, uint32_t slot_id);
static uint32_t pool_used(void);
static void call_level_1(void);

/* 实例化：静态存储期的固定资源账本，不使用动态内存。 */
static PoolSlot g_pool[POOL_SLOT_COUNT];
static uint32_t g_active_depth;
static uint32_t g_failures;

static void check(uint32_t condition, const char *message)
{
    if (condition == 0U) {
        (void)printf("FAIL: %s\n", message);
        g_failures++;
    }
}

/* 实现：把所有槽恢复为空闲。 */
static void pool_init(void)
{
    uint32_t index;

    for (index = 0U; index < (uint32_t)POOL_SLOT_COUNT; ++index) {
        g_pool[index].owner_id = 0U;
        g_pool[index].in_use = 0U;
    }
}

/* 实现：成功时交付槽编号；容量不足时返回无效编号。 */
static uint32_t pool_acquire(uint32_t owner_id)
{
    uint32_t index;

    for (index = 0U; index < (uint32_t)POOL_SLOT_COUNT; ++index) {
        if (g_pool[index].in_use == 0U) {
            g_pool[index].in_use = 1U;
            g_pool[index].owner_id = owner_id;
            return index;
        }
    }

    return POOL_INVALID_SLOT;
}

/* 实现：只有当前登记的所有者可以归还有效槽。 */
static uint32_t pool_release(uint32_t owner_id, uint32_t slot_id)
{
    if (slot_id >= (uint32_t)POOL_SLOT_COUNT) {
        return 0U;
    }
    if (g_pool[slot_id].in_use == 0U) {
        return 0U;
    }
    if (g_pool[slot_id].owner_id != owner_id) {
        return 0U;
    }

    g_pool[slot_id].owner_id = 0U;
    g_pool[slot_id].in_use = 0U;
    return 1U;
}

static uint32_t pool_used(void)
{
    uint32_t index;
    uint32_t used = 0U;

    for (index = 0U; index < (uint32_t)POOL_SLOT_COUNT; ++index) {
        used += (uint32_t)g_pool[index].in_use;
    }
    return used;
}

static void call_level_3(void)
{
    uint32_t local_token = 33U;

    g_active_depth++;
    (void)printf("enter level_3 depth=%u token=%u\n",
                 (unsigned int)g_active_depth,
                 (unsigned int)local_token);
    (void)printf("leave level_3 depth=%u token=%u\n",
                 (unsigned int)g_active_depth,
                 (unsigned int)local_token);
    g_active_depth--;
    /* 返回后 local_token 的生命周期结束；不保存或使用其地址。 */
}

static void call_level_2(void)
{
    uint32_t local_token = 22U;

    g_active_depth++;
    (void)printf("enter level_2 depth=%u token=%u\n",
                 (unsigned int)g_active_depth,
                 (unsigned int)local_token);
    call_level_3();
    (void)printf("leave level_2 depth=%u token=%u\n",
                 (unsigned int)g_active_depth,
                 (unsigned int)local_token);
    g_active_depth--;
}

static void call_level_1(void)
{
    uint32_t local_token = 11U;

    g_active_depth++;
    (void)printf("enter level_1 depth=%u token=%u\n",
                 (unsigned int)g_active_depth,
                 (unsigned int)local_token);
    call_level_2();
    (void)printf("leave level_1 depth=%u token=%u\n",
                 (unsigned int)g_active_depth,
                 (unsigned int)local_token);
    g_active_depth--;
}

int main(void)
{
    uint32_t slot_101;
    uint32_t slot_102;
    uint32_t slot_103;
    uint32_t slot_104;

    /* 组装与使用：先运行固定调用链。 */
    (void)printf("== nested calls ==\n");
    call_level_1();
    (void)printf("after calls depth=%u\n", (unsigned int)g_active_depth);
    check(g_active_depth == 0U, "call depth must return to zero");

    /* 组装与使用：再运行固定资源池的正常和失败路径。 */
    (void)printf("\n== fixed pool ledger ==\n");
    pool_init();

    slot_101 = pool_acquire(101U);
    (void)printf("acquire owner=101 slot=%u used=%u\n",
                 (unsigned int)slot_101, (unsigned int)pool_used());
    slot_102 = pool_acquire(102U);
    (void)printf("acquire owner=102 slot=%u used=%u\n",
                 (unsigned int)slot_102, (unsigned int)pool_used());
    slot_103 = pool_acquire(103U);
    (void)printf("acquire owner=103 slot=%u used=%u\n",
                 (unsigned int)slot_103, (unsigned int)pool_used());

    slot_104 = pool_acquire(104U);
    if (slot_104 == POOL_INVALID_SLOT) {
        (void)printf("acquire owner=104 failed used=%u\n",
                     (unsigned int)pool_used());
    }
    check(slot_104 == POOL_INVALID_SLOT,
          "fourth acquire must fail while all slots are used");

    check(pool_release(102U, slot_102) != 0U,
          "owner 102 must release its slot");
    (void)printf("release owner=102 slot=%u used=%u\n",
                 (unsigned int)slot_102, (unsigned int)pool_used());

    slot_104 = pool_acquire(104U);
    (void)printf("acquire owner=104 slot=%u used=%u\n",
                 (unsigned int)slot_104, (unsigned int)pool_used());
    check(slot_104 == slot_102, "released slot must be reusable");

    check(pool_release(101U, slot_101) != 0U,
          "owner 101 must release its slot");
    check(pool_release(104U, slot_104) != 0U,
          "owner 104 must release its slot");

    /* 安全模拟遗漏释放的后果：先观察占用，再执行最终清理。 */
    (void)printf("leave owner=103 allocated used=%u\n",
                 (unsigned int)pool_used());
    check(pool_used() == 1U,
          "an unreleased slot must remain in the ledger");

    check(pool_release(103U, slot_103) != 0U,
          "owner 103 final cleanup must succeed");
    (void)printf("cleanup complete used=%u\n",
                 (unsigned int)pool_used());
    check(pool_used() == 0U, "all slots must be free after cleanup");

    if (g_failures == 0U) {
        (void)printf("PASS\n");
        return 0;
    }

    (void)printf("FAILURES=%u\n", (unsigned int)g_failures);
    return 1;
}
```

### 9.1 代码属于哪一层

这是主机教学实验层的单文件程序：

```text
实验场景 main
  -> 调用深度记录函数
  -> 固定池接口与静态账本
  -> C11 标准头文件和主机输出
```

依赖从实验场景指向机制实现；机制实现不依赖 STM32 HAL（硬件抽象层）、寄存器或开发板。`g_pool` 和计数器具有静态存储期，各 `local_token` 具有自动存储期。槽的资源责任从 `pool_acquire` 成功返回开始，由 `main` 中对应 owner 承担，直到 `pool_release` 成功。

### 9.2 Windows 主机构建命令

把代码保存为 `stack_heap_fake.c` 后，可使用本机已有的一种 C 编译器。本次运行已从本节代码块直接提取源码，并使用 MSYS2 GCC 16.2.0 以 `-Werror` 编译和运行，编译与程序退出码均为 `0`，最后一行是 `PASS`。证据记录在本次运行目录的 `host-test.log`。复现实验可使用：

```powershell
gcc -std=c11 -Wall -Wextra -Wpedantic stack_heap_fake.c -o stack_heap_fake.exe
./stack_heap_fake.exe
```

或：

```powershell
clang -std=c11 -Wall -Wextra -Wpedantic stack_heap_fake.c -o stack_heap_fake.exe
./stack_heap_fake.exe
```

退出码 `0` 且最后一行是 `PASS`，表示该次主机构建下的逻辑检查通过。它仍不构成硬件验证。

## 10. 常见错误

### 10.1 把自动对象等同于物理栈槽

错误说法：“局部变量一定在栈上。”

改为：“普通局部对象具有自动存储期；在常见实现中，活动调用所需的某些状态可能由调用帧承载。某个对象是否实际占用栈槽，要检查具体目标代码。”

### 10.2 返回局部对象地址后继续访问

函数返回使该次自动对象生命周期结束。旧地址不能恢复对象。正确做法可以是按值返回，或由调用者提供一个在使用期间仍存活的对象；后者只作为已有指针知识的应用，不在本课展开接口架构。

### 10.3 不检查分配失败

“内存通常够”不是证明。真实分配接口和本课 `pool_acquire` 都需要调用者检查失败结果。失败时没有获得有效资源，也不能执行后续使用和释放路径。

### 10.4 只写成功路径，不写释放责任

每次成功取得资源时，应立即能回答：所有者是谁，正常返回谁释放，提前返回谁释放，错误清理谁释放。等代码末尾再猜，容易遗漏分支。

### 10.5 把函数返回误认为资源自动归还

自动对象随块结束；动态取得的资源遵循显式契约。这是两套不同边界。保存资源句柄的局部变量可以消失，但它代表的资源仍可能被占用，从而失去可达的释放路径。

### 10.6 用危险行为演示错误

不要通过解引用悬空指针、越界写、故意触发真实栈溢出或留下真实内存泄漏来“证明”概念。本课用值记录、容量失败和最终清理观察边界，不制造未定义行为。

### 10.7 用 Host Fake 推断真实分配器

固定等大槽没有模拟不同大小块的布局，因此不能证明真实堆不会碎片化，也不能测量分配耗时。真实库行为必须依据所用工具链与库文档核对。

## 11. 调试观察点

### 11.1 不看地址，先看控制流

在 `call_level_1`、`call_level_2`、`call_level_3` 入口和返回前设置断点，观察：

- `g_active_depth` 是否按预期变化；
- 每个 `local_token` 是否只在所属函数活动期间观察；
- 返回顺序是否与进入顺序相反。

不要在函数返回后尝试观察或解引用该函数局部对象地址。

### 11.2 看资源账本的三个字段

在每次 `pool_acquire` 和 `pool_release` 后观察：

- 返回的 `slot_id` 是否有效；
- `g_pool[index].in_use` 是否与预期一致；
- `g_pool[index].owner_id` 是否对应释放者。

重点观察第四次申请的失败分支，以及 owner 102 释放后 owner 104 对同一槽的复用。

### 11.3 记录高水位而不是只看最终值

本例最终 `used=0` 只能说明完成清理，不能告诉你峰值曾是 3。真实工程评估资源边界时，应同时记录峰值或高水位。高水位如何实现会成为调试与验证阶段的内容，本课只提出观察要求，不新增机制。

### 11.4 编译器观察的边界

可选地比较不同优化选项生成的反汇编或调试器变量显示。若 `local_token` 被放入寄存器、常量传播或消除，只能说明该次工具链产物；这恰好支持“生命周期规则不等于固定物理布局”，不能据此推导所有编译器和 STM32 工程。

### 11.5 真实 STM32 的待核对点

拿到具体工程后再记录：编译器版本、ABI、优化选项、链接脚本、栈边界、C 库配置、实际调用链和故障证据。缺少其中任何一项时，不给出具体字节数或安全余量结论。

## 12. 实战实验

### 实验 A：固定调用深度

目标：验证逻辑活动深度完整回到零。

步骤：

1. 用第 9 节代码构建并运行。
2. 把所有 `enter` 行的深度依次记录为一列。
3. 把所有 `leave` 行的深度依次记录为一列。
4. 确认进入深度为 `1, 2, 3`，离开观察为 `3, 2, 1`，最终为 `0`。
5. 说明为什么这些数字不能换算成真实栈字节数。

验收：程序输出 `PASS`；回答中明确区分逻辑深度和物理帧布局。

### 实验 B：容量不足与失败检查

目标：验证容量边界不会被忽略。

步骤：

1. 保持 `POOL_SLOT_COUNT=3`。
2. 连续为 owner 101、102、103、104 申请。
3. 确认前三次成功，第四次返回 `POOL_INVALID_SLOT`。
4. 在纸上写出第四次失败后谁拥有哪几个槽。
5. 解释为什么失败的 owner 104 此时不承担释放责任。

验收：失败没有导致越界访问，也没有把无效编号作为有效槽使用。

### 实验 C：释放后复用

目标：验证释放动作改变资源可用性。

步骤：

1. 在池已满时释放 owner 102 的槽。
2. 再为 owner 104 申请。
3. 确认申请成功，并在当前“从低编号寻找”的 Fake 实现中复用相同槽。
4. 将查找顺序改为从高编号向低编号，再次运行。
5. 区分“释放后存在可用槽”这一契约与“必定返回哪个槽”这一实现细节。

验收：契约判断不依赖某个固定槽编号；若断言依赖查找顺序，应能指出它只是本实现测试。

### 实验 D：安全模拟遗漏释放

目标：观察遗漏释放的可见后果，同时保持实验最终可清理。

步骤：

1. 执行到 owner 101 和 104 已释放、owner 103 尚未释放的位置。
2. 记录 `pool_used()` 为 1。
3. 不访问无效地址，不调用真实动态内存。
4. 执行 owner 103 的最终清理，确认占用回到 0。
5. 写出若这条清理路径永久缺失，重复运行同类流程会怎样影响有限容量。

验收：能够用“账本仍占用”描述后果，而不是用“局部句柄还存在”错误解释资源寿命。

### 实验 E：错误所有者释放

目标：验证所有权检查的失败路径。

步骤：

1. owner 101 成功取得一个槽。
2. 在最终正确释放前，增加一次 `pool_release(999U, slot_101)`。
3. 检查该调用返回 0，且 `pool_used()` 不变。
4. 再由 owner 101 正确释放并确认占用减少。

验收：错误释放不会悄悄改变账本；实验末尾仍全部清理。

## 13. 自检题

1. 普通局部对象的地址被复制到全局指针后，为什么函数返回仍不能通过该指针访问对象？
2. “自动存储期对象通常与调用栈有关”和“自动对象必定在物理栈中”有什么区别？
3. 调用深度从 1 增到 3 能否说明用了 3 个字节或 3 个固定大小帧？为什么？
4. `pool_acquire` 失败时，owner 是否获得了需要释放的槽？
5. 为什么保存槽编号的局部变量消失，不代表槽已被归还？
6. 本课如何安全观察遗漏释放，而没有真的永久泄漏资源？
7. 为什么最终 `used=0` 仍不足以证明运行过程从未接近容量上限？
8. 不使用动态分配是否就能证明系统不会内存不足？

参考要点：

1. 地址不延长对象生命周期；对象离开块后已结束，旧地址不能再用于访问它。
2. 前者是常见实现联系，后者是未经目标代码验证的绝对化断言。
3. 不能；每帧内容与布局依赖 ABI、编译器、优化和具体函数。
4. 没有；失败分支不产生资源所有权。
5. 句柄变量和它代表的资源是不同对象，资源归还由显式契约决定。
6. 先保留 owner 103 的占用并读取账本，再在程序结束前显式清理。
7. 最终值看不到峰值；本例峰值是 3。
8. 不能；静态区可能超出 RAM，调用栈也可能超过边界。

## 14. 面试题

### 14.1 为什么嵌入式系统常限制动态内存

建议答案：不是因为语法不可用，而是系统需要证明容量、最坏失败路径、释放责任、长期碎片和时延是否满足约束。静态或有界调用栈存储通常更容易从构建与运行证据中评估，但也必须检查其边界。

### 14.2 栈和堆最重要的生命周期区别是什么

建议答案：自动对象的生命周期由块进入和离开界定，活动调用状态通常随调用返回撤销；动态分配块则从成功取得开始，直到显式释放才归还。函数返回本身不是动态块的释放动作。

### 14.3 如何审查一个可能泄漏的函数

建议答案：从每个成功取得资源的位置开始，标出所有者；沿正常返回、失败、提前返回的每条路径检查是否恰好释放一次；申请失败路径不得使用或释放不存在的资源。最后用账本、计数或测试记录验证，而不是只看主路径。

### 14.4 map 文件能否直接给出最坏栈深度

建议答案：通常不能。map 主要提供构建期布局和符号证据；最坏栈使用还取决于调用关系、每个目标函数的实际帧、间接调用和运行路径，需要结合工具链报告、目标代码、静态分析与运行证据。

### 14.5 打印两个局部变量地址能证明栈增长方向吗

建议答案：不能把一次主机构建的观察推广为语言或所有目标的规则。对象可能被优化，地址关系受 ABI、编译器和选项影响。目标结论必须查对应 ABI 和实际产物。[1][2]

## 15. 延伸思考

1. 如果固定池的槽代表 UART 接收缓冲区，而不是抽象资源，所有者与释放时机会如何写进接口契约？此处只思考责任，不引入 UART 实现。
2. 若函数有多个提前返回点，怎样让每条路径的资源账本都回到预期状态？
3. 固定等大槽消除了哪类大小变化，又牺牲了什么灵活性？
4. 为什么平均调用深度或平均内存用量不能替代最坏边界分析？
5. 若调试器显示某局部变量“不可用”或被优化掉，这与对象的语言生命周期分别说明什么？
6. 将来设计 Device Framework 对象时，哪些对象适合静态存在，哪些临时状态适合自动存储？需要哪些工程证据才能决定？

## 16. 本节总结

本课建立了两条彼此关联但不能混淆的判断链：

```text
函数调用链：进入调用 -> 活动状态累积 -> 返回 -> 该次调用状态撤销
自动对象：进入相应块 -> 生命周期开始 -> 离开块 -> 生命周期结束

资源申请链：请求 -> 失败，或成功并产生所有权 -> 使用 -> 所有者显式释放
```

调用栈的帧式占用解释嵌套函数如何保留活动状态，但语言生命周期不能简化成“局部变量一定放在栈地址”。堆的显式分配与释放责任让运行期存储更灵活，同时引入申请失败、释放遗漏和碎片风险。

资源受限嵌入式软件默认优先确定的静态或调用栈存储，是为了更容易建立上限和证据，不是绝对禁止动态分配，也不是自动获得安全。真正的工程判断始终要回到具体目标、工具链、构建产物和运行记录。

## 17. 下一步

按课程顺序，下一主题将从本课的“运行期资源边界”继续推进。开始下一课前，应先完成至少一个主机实验，并能不用地址图回答：自动对象何时结束、动态资源由谁释放、Host Fake 能证明什么以及不能证明什么。

生成本课程不会提高掌握度。只有你的自检答案、实验结果或后续复习记录才能作为掌握证据；本次任务不修改 `learning-state.toml` 或 mastery。

## 18. 参考资料

[1] STMicroelectronics, *STM32 Cortex-M4 MCUs and MPUs programming manual*, PM0214 Rev 10, March 2020. 重点阅读：core registers 中的 stack pointer 说明。  
https://www.st.com/resource/en/programming_manual/pm0214-stm32f3-and-stm32f4-series-cortexm4-programming-manual-stmicroelectronics.pdf

[2] GNU Project, *GNU Compiler Collection (GCC) Internals*, GCC 17.0.0, “Basic Stack Layout”. 该页展示栈方向、帧方向、参数和返回地址位置均包含目标相关配置，适合限定“不能由 C 源码猜具体帧布局”的结论。  
https://gcc.gnu.org/onlinedocs/gccint/Frame-Layout.html

[3] GNU Project, *GNU C Language Introduction and Reference Manual*, “Dynamic Memory Allocation”, online manual（该手册说明其内容大致对应 2017 年的 GNU C）。用于核对申请失败检查与 `free` 显式释放；不外推到未核对的 STM32 C 库实现。  
https://www.gnu.org/software/c-intro-and-ref/manual/html_node/Dynamic-Memory-Allocation.html

[4] GNU Project, *GNU C Language Manual: Local Variables*, section 20.5（该手册说明其内容大致对应 2017 年的 GNU C）。用于核对普通局部自动对象从定义到块结束的存储边界；手册同时提醒优化可能改变实际分配形态，因此不用于断言物理栈槽。  
https://www.gnu.org/software/c-intro-and-ref/manual/html_node/Local-Variables.html

[5] GNU Project, *GNU C Language Manual: File-Scope Variables*, section 20.6（该手册说明其内容大致对应 2017 年的 GNU C）。用于核对文件作用域对象的程序期存储边界；不用于推断 STM32 的具体存储地址。  
https://www.gnu.org/software/c-intro-and-ref/manual/html_node/File_002dScope-Variables.html

来源边界说明：Arm AAPCS32 的计划入口在本次访问中返回 403，未用于支撑正文中的具体 ABI 结论；具体 STM32 工程的 ABI、栈/堆大小、库实现和故障行为仍标为待核对。来源访问日期见同目录 `lesson.json`。

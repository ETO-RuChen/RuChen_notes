+++
title = "用构建描述得到可重复的主机构建"
date = "2026-09-27T23:50:12+08:00"
lastmod = "2026-09-27T23:50:12+08:00"
summary = "用最小 CMake 项目理解构建描述如何驱动工具调用，并通过受控源码修改观察依赖关系决定的必要重建范围。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 9
tags = ["embedded-c", "build-system", "cmake", "incremental-build", "c11", "host-fake", "beginner"]
source_ids = ["cmake-4-4-3-buildsystem-7", "cmake-4-4-3-cmake-1", "gnu-make-4-4-1-running", "arm-101754-0617-00"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L009"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 9 课：用构建描述得到可重复的主机构建

手工逐条输入编译命令时，源文件、选项或输出目录很容易漏掉；再次构建时，还得靠人判断哪些步骤需要重做。本课先用一个最小 CMake 项目把这些信息写成可检查的构建描述，再观察源文件变化怎样沿依赖关系传播。

## 1. 本节目标

学习者能在主机上从一个最小 CMake 构建描述配置并构建一个 C11 可执行目标，说明构建描述在哪里定义、CMake 如何将目标和依赖交给生成的构建后端、后端如何调用编译器/链接器，并通过一次受控的源文件修改观察只有受影响目标及其消费者被重建，而不把 CMake 或 Make 的具体命令语法误当成 C 语言规则。预计用时 30 分钟。

本课只引入两个新核心概念：

1. **构建描述驱动工具调用（build description drives tool invocation）**。
2. **目标依赖关系决定重建范围（target dependencies determine rebuild scope）**。

## 2. 它解决什么问题

上一课已经知道编译器能把翻译单元变成目标文件，目标文件随后进入链接步骤。若每次都手工回忆这些调用，命令能否重复取决于人的记忆，源文件改变后也容易做多或做少。

构建系统（build system）读取项目的构建描述，协调编译器、链接器等工具来产生结果。CMake 是构建系统生成工具：配置时读取 `CMakeLists.txt`，为选定的生成器准备构建后端（build backend）文件；`cmake --build` 再调用相应的原生构建工具。[1][2] Make 是一种可执行依赖规则的构建工具，本课只把它视作 CMake 可能选择的后端，不学习 Makefile 语法。[3]

## 3. 必要前置知识

只沿用已经完成的内容：C11 最小程序、固定宽度整数、函数、翻译单元、目标文件，以及编译与后续链接的边界。不假定你会 CMake 语言、Makefile、生成器、交叉编译或工具链文件。

链接器（linker）在这里仅指把编译所得输入组合成可执行文件的工具；内部算法、ELF/Map 和链接脚本都不在本课范围。Arm 编译器官方参考资料也把编译步骤与链接步骤分开描述。[4]

## 4. 核心原理

`CMakeLists.txt` 声明“要得到名为 `host_app` 的可执行目标，它的源文件是 `app.c`”。它不保存编译器执行结果，也不是 C11 源代码。CMake 配置后生成后端所需的规则；构建时，后端依据这些规则调用编译器和链接器。CMake 官方手册把基于 CMake 的构建系统描述为一组高层逻辑目标，目标间依赖用于决定构建顺序以及变化后的重新生成规则。[1]

增量构建（incremental build）是只更新因输入变化而需要更新的结果。若只改 `app.c`，必要链条是重新处理该源文件并更新消费它的 `host_app`。本项目没有第二个用户定义目标，因此不能借它观察“另一个目标保持不动”；也不能把某一生成器日志的逐行形式当作普遍保证。

## 5. 关键术语与直观模型

| 术语 | 直观含义 | 本课位置 |
| --- | --- | --- |
| 构建描述 | 写下目标、输入与约束 | `CMakeLists.txt` |
| 构建目标（build target） | 构建系统中命名的预期结果 | `host_app` |
| 依赖关系（dependency） | 结果更新前必须具备的输入关系 | `host_app` 依赖 `app.c` |
| 配置（configure） | CMake 读取描述并准备构建目录 | `cmake -S . -B build` |
| 生成器（generator） | CMake 用来生成某类后端构建文件的方式 | 由本机 CMake 选择或用户指定 |
| 构建目录 | 保存配置与构建产物的目录 | `build/` |
| Host Fake（主机替身） | 用主机环境验证通用逻辑 | 本课全部实验 |

`-S` 指定源目录，`-B` 指定构建目录；不存在的构建目录可由 CMake 创建。`cmake --build <dir>` 构建已经生成的项目，并抽象了原生构建工具的命令行差异。[2] 这些都是 CMake 行为，不是 C11 语法。

## 6. 从输入到结果的完整流程

```text
CMakeLists.txt + app.c
        |
        | 学习者执行 cmake -S . -B build
        v
CMake 配置并生成后端规则
        |
        | 学习者执行 cmake --build build
        v
生成的后端 -> 编译器 -> 目标文件 -> 链接器 -> 主机可执行文件
```

- 定义在哪里：目标及源文件关系定义于源目录的 `CMakeLists.txt`；C 实现定义于 `app.c`。
- 谁持有：文件系统持有源文件、构建目录、生成的后端文件和最终产物。
- 谁注入：学习者通过配置命令把源目录、构建目录以及可选的生成器选择交给 CMake；这是工具输入，不是“依赖注入”。
- 调用如何流动：CMake 读取描述并生成后端；`cmake --build` 选择并调用后端；后端再调用编译器和链接器。[1][2]
- 声明、实现与使用：`add_executable` 是目标声明，`app.c` 是实现，配置和构建命令使用它们。本例没有运行时对象的实例化、BSP 组装或依赖注入，不能虚构这三个动作。

## 7. 嵌入式系统中的对应位置

迁移到 STM32 时，“描述目标和输入，再由后端调用工具链”的机制仍成立；但编译器选择、启动文件、芯片选项和产物形式必须依据真实工程与官方资料重新核对。本课没有具体开发板，不比较 F4、F7、H5、H7，也不涉及寄存器、HAL/LL、引脚或时钟树。

## 8. 主机实验与硬件迁移边界

Host Fake 能验证：CMake 能否读取描述、后端能否调用主机工具链、输入变化是否触发必要更新、主机程序是否返回预期退出状态。它不能证明 STM32 交叉构建、下载或硬件运行成功。

本次运行目录没有构建、测试或上板记录。以下代码是**示例，待主机执行；迁移后仍待上板验证**，元数据保持 `hardware_verified=false`。

## 9. 最小代码示例

源目录只放两个文件：

```text
cmake-demo/
|-- CMakeLists.txt
`-- app.c
```

`CMakeLists.txt` 属于构建描述层，依赖方向是“构建目标读取源文件路径”；它只在配置/构建期间使用：

```cmake
cmake_minimum_required(VERSION 3.14)
project(host_build_demo LANGUAGES C)

add_executable(host_app app.c)
set_target_properties(host_app PROPERTIES
    C_STANDARD 11
    C_STANDARD_REQUIRED YES
    C_EXTENSIONS NO
)
```

这里把最低版本设为 3.14，是因为后续实验使用统一的 `cmake --build ... --verbose` 选项；若本机版本更低，应先记录版本不满足，而不是把选项错误误判为源码或依赖问题。[2]

`app.c` 属于应用实现层，由目标 `host_app` 使用；程序结束时对象生命周期终止，不使用动态内存：

```c
#include <stdint.h>

static uint32_t add_one(uint32_t value)
{
    return value + 1U;
}

int main(void)
{
    const uint32_t result = add_one(41U);
    return (result == 42U) ? 0 : 1;
}
```

## 10. 常见错误

- 在源码目录内堆放生成物，没有使用独立的 `build/`。
- 把 `project`、`add_executable` 或 `-S/-B` 当成 C11 规则。
- 配置后直接猜后端是 Make；实际生成器依平台、安装和显式选项而定。
- 改动源码后只看“命令成功”，没有保存详细日志或比较产物时间戳。
- 把 CMake 自身的检查步骤误判为所有源文件都重新编译。
- 看到主机程序成功就声称已完成 STM32 构建或上板验证。

## 11. 调试观察点

1. 工具：记录 `cmake --version`，并从配置输出记录实际生成器和编译器。
2. 输入：确认源目录中存在正确的 `CMakeLists.txt` 与 `app.c`。
3. 边界：配置产物应进入 `build/`，源文件保持在源目录。
4. 调用：构建时加 `--verbose`，观察实际编译和链接调用；输出格式依后端而异。
5. 结果：每条命令后立即记录 `$LASTEXITCODE`，并检查可执行文件的路径与时间戳。
6. 重建：修改前先记录产物时间戳并预测更新链条，再比较实际日志。

## 12. 实战实验

在全新的 `cmake-demo` 目录创建第 9 节两个文件，然后执行：

```powershell
cmake --version
cmake -S . -B build
$LASTEXITCODE
cmake --build build --verbose
$LASTEXITCODE
Get-ChildItem .\build -Recurse -Filter host_app.exe |
    Select-Object FullName, Length, LastWriteTime
```

若找到可执行文件，按实际路径运行并紧接着读取 `$LASTEXITCODE`；预期退出状态为 `0`，实际结果以记录为准。

受控变更：把 `app.c` 中的 `41U` 改为 `40U`。先预测 `app.c` 对应的编译工作与消费它的 `host_app` 需要更新，再重复 `cmake --build build --verbose`。新程序的预期退出状态为 `1`。恢复 `41U` 后再次构建，预期回到 `0`。不要用课程文字替代真实日志。

失败排查：

- 找不到 `cmake`：记录 `cmake --version` 的失败信息，检查安装和 `PATH`。
- 配置失败：从第一条错误开始，核对当前目录、两个文件名和 `CMakeLists.txt` 语法。
- 找不到编译器：记录 CMake 识别到的生成器与编译器信息，不要改用手工编译来冒充本实验成功。
- 构建失败：保存详细日志，确认正在构建本次生成的 `build/`。
- 修改后看不到预期调用：确认保存了 `app.c`，检查系统时间和实际输入路径，再比较产物时间戳。
- 产物不能运行：使用日志给出的实际路径；保留退出状态和系统错误，不猜测硬件原因。

## 13. 自检题

1. 构建描述解决了手工命令序列的什么问题？
2. `CMakeLists.txt`、`app.c` 和构建产物分别在哪里，由谁持有？
3. 谁把源目录与构建目录交给 CMake？这为什么不叫运行时依赖注入？
4. 只改 `app.c` 后，哪些必要结果应更新？你要用什么证据判断？
5. 为什么 `cmake --build` 的日志不能证明代码已经上板？

## 14. 面试题

**问：`cmake -S . -B build` 与 `cmake --build build` 的职责有什么不同？**

答题要点：前者读取源目录中的构建描述，为构建目录生成后端构建系统；后者针对已生成的构建目录调用合适的原生构建工具。[2] 两者是构建工具操作，不是 C11 语言阶段。

## 15. 延伸思考

- 若将来增加第二个互不依赖的目标，只改 `app.c` 时你会怎样证明第二个目标没有成为必要重建对象？
- 为什么“日志里出现 CMake 检查”不等于“每个 `.c` 都重新编译”？
- 迁移到 STM32 工程时，哪些输入仍可写进构建描述，哪些信息必须由具体工具链和硬件资料确认？

## 16. 本节总结

构建描述把目标、源文件和约束留在仓库中；CMake 配置生成后端，构建命令再让后端调用编译器和链接器。输入变化沿已声明的依赖关系传播，决定必要更新范围。CMake 与 Make 都是工具，不是 C11 规则。

## 17. 下一步

完成实验并保存版本、命令、退出状态、详细日志和产物时间戳。课程生成本身不会提高掌握度，也不会修改 `completed`；下一主题由后续计划决定。

## 18. 参考资料

1. [CMake, *cmake-buildsystem(7)*](https://cmake.org/cmake/help/latest/manual/cmake-buildsystem.7.html)，CMake 4.4.3；访问日期：2026-09-27。用于核对目标、依赖与变化后的生成规则。[1]
2. [CMake, *cmake(1)*](https://cmake.org/cmake/help/latest/manual/cmake.1.html)，CMake 4.4.3；访问日期：2026-09-27。用于核对 `-S`、`-B` 与 `--build`。[2]
3. [GNU Project, *GNU Make Manual: How to Run make*](https://www.gnu.org/software/make/manual/html_node/Running.html)，GNU make 4.4.1，Edition 0.77；访问日期：2026-09-27。用于核对 Make 更新过期目标的后端边界。[3]
4. [Arm, *Arm Compiler for Embedded Reference Guide*](https://documentation-service.arm.com/static/61718a08ac265639eac5b503)，Document ID `101754_0617_00_en`，Version 6.17，Issue 00；访问日期：2026-09-27。用于核对编译与链接工具阶段的边界。[4]

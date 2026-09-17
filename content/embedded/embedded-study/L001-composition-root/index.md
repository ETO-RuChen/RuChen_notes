+++
title = "从分层图到可替换对象：用组合根完成依赖注入"
date = "2026-09-18T00:38:58+08:00"
lastmod = "2026-09-18T00:38:58+08:00"
summary = "通过静态 Host Fake、ops/ctx 接口和唯一 BSP 组合根，建立从对象声明到 App 调用的最小可替换组装闭环。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 1
tags = ["composition-root", "dependency-injection", "ops-and-ctx", "host-fake", "device-framework"]
source_ids = ["ST-UM1725", "ST-UM1905", "GNU-C-REFERENCE"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L001"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 从分层图到可替换对象：用组合根完成依赖注入

> 本节代码是 C11 Host Fake 教学示例，尚无真实构建记录，也未在开发板上验证。它只能支持代码审查和逻辑验证；`hardware_verified=false`。所有具体 STM32 外设实例、引脚、时钟、寄存器和 HAL/LL API 均留待选定芯片与开发板后核对。

## 1. 本节目标

完成本节后，你应能独立解释并写出一个最小对象组装闭环：

- 用总线接口声明“能做什么”，不绑定 I2C、SPI 或某颗 MCU（Microcontroller Unit，微控制器）。
- 用 Host Fake（主机侧伪实现）提供一个可观察的具体实现。
- 用静态对象承载 Fake、总线接口和 IMU（Inertial Measurement Unit，惯性测量单元）服务，不使用动态内存。
- 在唯一的 BSP（Board Support Package，板级支持包）组合根中完成依赖注入。
- 画出 `App -> IMU Service -> Bus Interface -> Fake` 的调用流，并指出每个对象由谁持有、谁注入、存活多久。

本节只推进一个主要概念：组合根（composition root，集中实例化具体对象并连接依赖的唯一入口）。`ops`/`ctx` 和依赖注入只服务于这个组装目标。

## 2. 它解决什么问题

一张分层图可以告诉我们 App 不应直接依赖 STM32 HAL，却不会自动产生任何 C 对象，也不会回答这些问题：

- `imu_service_t` 到底在哪里定义实例？
- 它需要的 `bus_t` 由谁创建？
- `bus_t` 如何找到 Host Fake 或未来的 STM32 实现？
- 指针指向的对象能活多久？
- 测试时如何换成另一种实现，而不修改 App 和 Service？

如果每一层都自行创建或查找下一层，依赖关系会散落在业务代码里。替换实现时，需要改动许多文件；对象初始化顺序也很难审计。

下文用 App（Application，应用层）表示业务调用者，用 Service（服务层）表示承载用例并依赖总线抽象的对象。这些对象属于 Device Framework（设备框架）长期项目的最小骨架。

组合根把这些决策集中起来：具体对象在哪里、用哪个实现、按什么顺序连接，只在一个边界内决定。业务层只保存抽象依赖，不知道依赖来自 Host Fake、HAL 还是 LL。

先看最小闭环：

```text
main
  | 取得已经组装好的 imu_service_t
  v
App --> IMU Service --> bus_read() --> bus.ops->read(bus.ctx, ...)
                                           |
                                           v
                                      fake_bus_read()
```

## 3. 必要前置知识

- 结构体可以保存数据和函数指针。
- `const bus_t *` 表示调用方不通过该指针修改 `bus_t` 本身。
- 静态存储期（static storage duration）对象在程序整个执行期间存在；本节不展开它在具体链接段中的位置。[GNU-C-REFERENCE]
- 接口声明回答“调用者可以做什么”，函数实现回答“具体怎样做”。
- 本节不要求开发板、STM32CubeMX、FreeRTOS 或真实 IMU。

## 4. 核心原理

### 4.1 `ops` 与 `ctx` 必须成对

`ops` 是 operations table（操作函数表），保存实现函数；`ctx` 是 context（上下文）指针，指出这次调用属于哪个实现实例。

```c
bus->ops->read(bus->ctx, reg, data, length);
```

同一份 `fake_bus_read()` 可以服务多个 Fake 实例，因为不同 `ctx` 可以保存不同的固定返回值和调用计数。C 可以通过函数指针调用函数。[GNU-C-REFERENCE] 只替换 `ops` 而忘记匹配的 `ctx`，函数就会用错误布局解释内存；只替换 `ctx` 而沿用不匹配的 `ops`，问题相同。因此本节让 `bus_init()` 一次接收并校验两者。

### 4.2 依赖注入发生在外部

依赖注入（dependency injection）是指对象不自行寻找或创建具体依赖，而由外部组装者提供依赖。本例中：

```c
imu_service_init(&instances->imu_service,
                 &instances->bus,
                 HOST_FAKE_IDENTITY_REGISTER);
```

`imu_service_t` 只保存 `const bus_t *`。它不知道 `bus_t` 最终路由到 Fake，未来换成 STM32 实现时，Service 和 App 源码不需要改变。

### 4.3 组合根只负责组装

本节把 `bsp_init()` 作为组合根。它可以：

- 取得长期存活的对象实例；
- 按依赖顺序初始化 Fake、Bus、Service；
- 把下层对象地址注入上层对象；
- 向入口层暴露已经组装好的 Service。

它不应该读取 IMU 数据、解释业务状态或实现重试策略。那些是 Service 或 App 的职责。

## 5. 对象、所有权与生命周期

| 对象 | 定义位置 | 持有者 | 注入者 | 被谁使用 | 生命周期 |
| --- | --- | --- | --- | --- | --- |
| `fake_bus_context_t` 实例 | `bsp/device_instances.c` | Device Framework 的实例容器 | `bsp_init()` 将其注入 `bus_t` | `fake_bus_read()` | 静态存储期，贯穿程序执行 |
| `fake_bus_ops` | `platform/host/fake_bus.c` | Host Fake 模块，只读函数表 | `bsp_init()` 将其注入 `bus_t` | `bus_read()` 间接调用 | 静态存储期，贯穿程序执行 |
| `bus_t` 实例 | `bsp/device_instances.c` | Device Framework 的实例容器 | `bsp_init()` 注入 `ops` 和 `ctx` | `imu_service_t` | 静态存储期，贯穿程序执行 |
| `imu_service_t` 实例 | `bsp/device_instances.c` | Device Framework 的实例容器 | `bsp_init()` 注入 `bus_t` | App | 静态存储期，贯穿程序执行 |

“持有”表示谁负责提供对象存储和保证生命周期，不等于谁可以随意修改对象。App 只借用 `const imu_service_t *`；它既不销毁 Service，也不拥有 Bus 或 Fake。

本例没有销毁阶段，因为所有实例均为静态存储期且没有动态资源。未来如果具体实现要管理 DMA（Direct Memory Access，直接存储器访问）、互斥量或电源状态，需要再明确启动与停止协议，不能假设静态对象自动完成硬件资源释放。

## 6. 声明、实现、实例化、组装、使用

架构代码最容易混淆的是把五个动作都叫“写驱动”。本例严格分开：

| 动作 | 回答的问题 | 本例文件 |
| --- | --- | --- |
| 声明 | 上层能调用什么？ | `include/device/bus.h`、`include/service/imu_service.h` |
| 实现 | 调用具体怎样执行？ | `device/bus.c`、`service/imu_service.c`、`platform/host/fake_bus.c` |
| 实例化 | 哪块存储真正承载对象？ | `bsp/device_instances.c` |
| 组装 | 哪个实现连接到哪个使用者？ | `bsp/bsp.c` |
| 使用 | 谁发起业务调用？ | `app/app.c`、`main.c` |

依赖方向如下：

```text
app ---------> service interface ---------> bus interface
                                            ^
host fake ----------------------------------|

bsp composition root ---> 同时知道 service、bus 和所选具体实现
main -------------------> 只负责启动组装并把 service 交给 app
```

只有组合根需要同时看见抽象与具体实现。Bus 接口不能反向包含 Host Fake，Service 不能包含 BSP，App 不能包含 Host Fake。

## 7. STM32 / 寄存器视角

本节没有具体开发板，因此不能选择 I2C/SPI 实例、引脚复用、时钟源、DMA 通道或寄存器地址。

迁移到 STM32 时，组合关系仍然不变：

```text
imu_service_t -> bus_t -> stm32_bus_ops + stm32_bus_context_t
```

变化集中在具体实现和实例配置：`stm32_bus_context_t` 需要承载所选驱动所需的句柄或寄存器基址，具体内容必须按目标系列、芯片、外设实例和所采用的 HAL/LL 路径核对。BSP 负责把由平台初始化流程准备好的具体上下文与 `stm32_bus_ops` 绑定，再注入 Service。

F4 与 F7 的官方手册都说明：HAL（Hardware Abstraction Layer，硬件抽象层）提供较高层、面向功能且更强调可移植性的 API（Application Programming Interface，应用程序编程接口）；LL（Low-Layer，低层）更靠近寄存器级操作、可移植性较低，并要求开发者理解 MCU 与外设细节。[ST-UM1725][ST-UM1905] 这支持“把平台调用封装在具体实现层”的边界，但不意味着 F4 与 F7 的具体初始化代码可直接互换。

F4、F7、H5、H7 的具体句柄、初始化顺序、缓存与 DMA 一致性约束均为后续适配课内容。H5/H7 的本节相关结论尚未查阅对应第一方资料，标记为“待核对”，不在本节展开。

## 8. HAL、LL 与可移植实现

组合根模式不依赖 HAL 或 LL。可以准备两个实现：

- `stm32_hal_bus_ops`：内部调用经目标系列手册核对的 HAL API。
- `stm32_ll_bus_ops`：内部调用经参考手册和 LL 文档核对的 LL API。

两者都实现同一个 `bus_ops_t`，Service 仍只调用 `bus_read()`。选择发生在 BSP 组装根，不发生在 Service 中。

```c
/* 仅表示未来的组装形态，不是可编译实现，也不是已核对 API。 */
bus_init(&instances->bus, &stm32_hal_bus_ops, &instances->stm32_bus_context);
```

不要在 `imu_service.c` 中使用 `#ifdef STM32F4` 分叉到不同 HAL/LL API。那会让可移植业务逻辑知道平台细节，破坏依赖方向。

## 9. 最小代码示例

以下代码按文件展示各层。它是“示例，尚未构建，待 Host 编译验证；待选定硬件后上板验证”。公开接口中的整数均使用固定宽度类型，不使用 `malloc()`/`free()`。

### 9.1 Bus 接口声明：`include/device/bus.h`

层：设备抽象层。依赖：只依赖 C 标准固定宽度类型。生命周期：只声明类型，不创建对象。

```c
#ifndef DEVICE_BUS_H
#define DEVICE_BUS_H

#include <stdint.h>

#define BUS_OK             ((int32_t)0)
#define BUS_ERROR_ARGUMENT ((int32_t)-1)
#define BUS_ERROR_IO       ((int32_t)-2)

typedef int32_t (*bus_read_fn_t)(void *ctx,
                                 uint8_t reg,
                                 uint8_t *data,
                                 uint16_t length);

typedef struct {
    bus_read_fn_t read;
} bus_ops_t;

typedef struct {
    const bus_ops_t *ops;
    void *ctx;
} bus_t;

int32_t bus_init(bus_t *bus, const bus_ops_t *ops, void *ctx);
int32_t bus_read(const bus_t *bus,
                 uint8_t reg,
                 uint8_t *data,
                 uint16_t length);

#endif
```

### 9.2 Bus 调度实现：`device/bus.c`

层：设备抽象层。依赖方向：只调用注入的 `ops`，不知道 Host 或 STM32。生命周期：不持有新资源，只校验并保存借用指针。

```c
#include <stddef.h>

#include "device/bus.h"

int32_t bus_init(bus_t *bus, const bus_ops_t *ops, void *ctx)
{
    if ((bus == NULL) || (ops == NULL) || (ops->read == NULL) || (ctx == NULL)) {
        return BUS_ERROR_ARGUMENT;
    }

    bus->ops = ops;
    bus->ctx = ctx;
    return BUS_OK;
}

int32_t bus_read(const bus_t *bus,
                 uint8_t reg,
                 uint8_t *data,
                 uint16_t length)
{
    if ((bus == NULL) || (bus->ops == NULL) || (bus->ops->read == NULL) ||
        (bus->ctx == NULL) || (data == NULL) || (length == 0U)) {
        return BUS_ERROR_ARGUMENT;
    }

    return bus->ops->read(bus->ctx, reg, data, length);
}
```

### 9.3 IMU Service 声明：`include/service/imu_service.h`

层：服务层接口。依赖方向：Service 依赖抽象 `bus_t`。生命周期：Service 借用 Bus，Bus 必须比 Service 的使用期更长。

```c
#ifndef SERVICE_IMU_SERVICE_H
#define SERVICE_IMU_SERVICE_H

#include <stdint.h>

#include "device/bus.h"

#define IMU_SERVICE_OK             ((int32_t)0)
#define IMU_SERVICE_ERROR_ARGUMENT ((int32_t)-10)

typedef struct {
    const bus_t *bus;
    uint8_t identity_register;
} imu_service_t;

int32_t imu_service_init(imu_service_t *service,
                         const bus_t *bus,
                         uint8_t identity_register);
int32_t imu_service_read_id(const imu_service_t *service, uint8_t *device_id);

#endif
```

### 9.4 IMU Service 实现：`service/imu_service.c`

层：服务层。依赖方向：调用 Bus 抽象，不包含 Fake、BSP 或 STM32 头文件。生命周期：不创建依赖。

```c
#include <stddef.h>

#include "service/imu_service.h"

int32_t imu_service_init(imu_service_t *service,
                         const bus_t *bus,
                         uint8_t identity_register)
{
    if ((service == NULL) || (bus == NULL)) {
        return IMU_SERVICE_ERROR_ARGUMENT;
    }

    service->bus = bus;
    service->identity_register = identity_register;
    return IMU_SERVICE_OK;
}

int32_t imu_service_read_id(const imu_service_t *service, uint8_t *device_id)
{
    if ((service == NULL) || (service->bus == NULL) || (device_id == NULL)) {
        return IMU_SERVICE_ERROR_ARGUMENT;
    }

    return bus_read(service->bus,
                    service->identity_register,
                    device_id,
                    (uint16_t)1U);
}
```

### 9.5 Host Fake 声明：`platform/host/fake_bus.h`

层：Host 平台实现层。依赖方向：实现 Bus 抽象。生命周期：上下文的存储由实例层提供。

```c
#ifndef PLATFORM_HOST_FAKE_BUS_H
#define PLATFORM_HOST_FAKE_BUS_H

#include <stdint.h>

#include "device/bus.h"

typedef struct {
    uint8_t fixed_value;
    uint32_t read_count;
} fake_bus_context_t;

extern const bus_ops_t fake_bus_ops;

void fake_bus_context_init(fake_bus_context_t *ctx, uint8_t fixed_value);

#endif
```

### 9.6 Host Fake 实现：`platform/host/fake_bus.c`

层：Host 平台实现层。依赖方向：由 `bus_ops_t` 适配到 Fake 上下文。生命周期：`fake_bus_ops` 为静态存储期只读对象，不拥有 `ctx`。

```c
#include <stddef.h>

#include "platform/host/fake_bus.h"

static int32_t fake_bus_read(void *ctx,
                             uint8_t reg,
                             uint8_t *data,
                             uint16_t length)
{
    fake_bus_context_t *fake = (fake_bus_context_t *)ctx;

    (void)reg;

    if ((fake == NULL) || (data == NULL) || (length != 1U)) {
        return BUS_ERROR_ARGUMENT;
    }

    fake->read_count += 1U;
    data[0] = fake->fixed_value;
    return BUS_OK;
}

const bus_ops_t fake_bus_ops = {
    .read = fake_bus_read
};

void fake_bus_context_init(fake_bus_context_t *ctx, uint8_t fixed_value)
{
    if (ctx != NULL) {
        ctx->fixed_value = fixed_value;
        ctx->read_count = 0U;
    }
}
```

### 9.7 对象实例声明：`bsp/device_instances.h`

层：BSP 私有实例层。依赖方向：只有 BSP 组合代码应包含此文件。生命周期：声明实例容器的形状。

```c
#ifndef BSP_DEVICE_INSTANCES_H
#define BSP_DEVICE_INSTANCES_H

#include "device/bus.h"
#include "platform/host/fake_bus.h"
#include "service/imu_service.h"

typedef struct {
    fake_bus_context_t fake_bus_context;
    bus_t bus;
    imu_service_t imu_service;
} device_instances_t;

device_instances_t *device_instances_get(void);

#endif
```

### 9.8 静态对象实例化：`bsp/device_instances.c`

层：BSP 私有实例层。依赖方向：只提供对象存储，不决定对象如何连接。生命周期：`g_instances` 具有静态存储期，是所有实例的持有者。

```c
#include "bsp/device_instances.h"

static device_instances_t g_instances;

device_instances_t *device_instances_get(void)
{
    return &g_instances;
}
```

### 9.9 BSP 对外声明：`include/bsp/bsp.h`

层：BSP 边界。依赖方向：入口层通过它启动组装并取得抽象 Service。

```c
#ifndef BSP_BSP_H
#define BSP_BSP_H

#include <stdint.h>

#include "service/imu_service.h"

int32_t bsp_init(void);
const imu_service_t *bsp_imu_service(void);
uint32_t bsp_debug_fake_read_count(void);

#endif
```

`bsp_debug_fake_read_count()` 只为本节 Host 实验暴露观察点，不是产品业务接口。迁移到真实 BSP 时应移入测试专用接口或删除。

### 9.10 唯一组合根：`bsp/bsp.c`

层：BSP 组装层。依赖方向：这是唯一同时知道实例、抽象接口和所选具体实现的地方。生命周期：不拥有额外存储，只连接 `g_instances` 内的长期对象。

```c
#include <stddef.h>

#include "bsp/bsp.h"
#include "bsp/device_instances.h"

#define HOST_FAKE_DEVICE_ID         ((uint8_t)0xA5U)
#define HOST_FAKE_IDENTITY_REGISTER ((uint8_t)0x00U)

static uint8_t g_bsp_initialized;

int32_t bsp_init(void)
{
    device_instances_t *instances = device_instances_get();
    int32_t status;

    fake_bus_context_init(&instances->fake_bus_context, HOST_FAKE_DEVICE_ID);

    status = bus_init(&instances->bus,
                      &fake_bus_ops,
                      &instances->fake_bus_context);
    if (status != BUS_OK) {
        return status;
    }

    status = imu_service_init(&instances->imu_service,
                              &instances->bus,
                              HOST_FAKE_IDENTITY_REGISTER);
    if (status != IMU_SERVICE_OK) {
        return status;
    }

    g_bsp_initialized = 1U;
    return BUS_OK;
}

const imu_service_t *bsp_imu_service(void)
{
    if (g_bsp_initialized == 0U) {
        return NULL;
    }

    return &device_instances_get()->imu_service;
}

uint32_t bsp_debug_fake_read_count(void)
{
    return device_instances_get()->fake_bus_context.read_count;
}
```

`0x00` 在这里只是 Host Fake 协议中的任意测试标记，不代表任何真实 IMU 寄存器。

### 9.11 App 声明与使用：`include/app/app.h`、`app/app.c`

层：应用层。依赖方向：App 只依赖 Service，不包含 BSP、Bus 或 Fake。生命周期：App 借用已经组装好的 Service。

```c
/* include/app/app.h */
#ifndef APP_APP_H
#define APP_APP_H

#include <stdint.h>

#include "service/imu_service.h"

int32_t app_run(const imu_service_t *imu, uint8_t *observed_id);

#endif
```

```c
/* app/app.c */
#include <stddef.h>

#include "app/app.h"

int32_t app_run(const imu_service_t *imu, uint8_t *observed_id)
{
    if ((imu == NULL) || (observed_id == NULL)) {
        return IMU_SERVICE_ERROR_ARGUMENT;
    }

    return imu_service_read_id(imu, observed_id);
}
```

### 9.12 入口层：`main.c`

层：程序入口。依赖方向：启动 BSP 组合根，把抽象 Service 交给 App；只有 Host 验收逻辑读取调试观察点。

```c
#include <stdint.h>

#include "app/app.h"
#include "bsp/bsp.h"

int main(void)
{
    uint8_t observed_id = 0U;
    int32_t status;

    status = bsp_init();
    if (status != BUS_OK) {
        return 1;
    }

    status = app_run(bsp_imu_service(), &observed_id);
    if (status != BUS_OK) {
        return 2;
    }

    if ((observed_id != (uint8_t)0xA5U) ||
        (bsp_debug_fake_read_count() != (uint32_t)1U)) {
        return 3;
    }

    return 0;
}
```

调用与返回过程是：

1. `main()` 调用 `bsp_init()`，组合根按 Fake、Bus、Service 的顺序连接对象。
2. `main()` 把 `bsp_imu_service()` 返回的借用指针传给 `app_run()`。
3. App 调用 `imu_service_read_id()`。
4. Service 调用 `bus_read()`。
5. `bus_read()` 通过 `bus->ops->read` 进入 `fake_bus_read()`，同时传入配对的 `bus->ctx`。
6. Fake 将计数加一，并把 `0xA5` 写入返回缓冲区。
7. 返回值沿原路径回到 `main()`；Host 验收逻辑检查 ID 和调用次数。

## 10. 常见错误

### 10.1 局部上下文逃逸

错误代码把局部 `ctx` 的地址保存进静态 Bus：

```c
static bus_t bus;

const bus_t *build_bad_bus(void)
{
    fake_bus_context_t ctx;

    fake_bus_context_init(&ctx, (uint8_t)0xA5U);
    (void)bus_init(&bus, &fake_bus_ops, &ctx);
    return &bus;
} /* ctx 的生命周期在这里结束，bus.ctx 随即悬空。 */
```

修正方式是让上下文的生命周期不短于 Bus 和所有调用者。这里未带 `static` 的块内局部变量 `ctx` 具有自动存储期，在函数返回后不再有效。[GNU-C-REFERENCE] 本例由静态 `g_instances` 同时持有 Fake 上下文、Bus 和 Service。

### 10.2 空函数表或空函数指针

直接写入 `.ops = NULL`，或提供 `.read = NULL`，都会使间接调用无目标。修正方式是让 `bus_init()` 在组装时失败，并让 `bus_read()` 在调用边界再次防御性检查。不要忽略 `bsp_init()` 的返回值。

### 10.3 `ops` 与 `ctx` 来自不同实现

例如把 `stm32_hal_bus_ops` 与 `fake_bus_context_t` 配对。C 的 `void *` 不会自动发现类型不匹配；具体函数会按错误结构解释地址。修正方式是只允许组合根构造 `bus_t`，并把“实现函数表 + 对应上下文”的组装放在相邻代码中审查。

### 10.4 Service 自己创建具体总线

如果 `imu_service_init()` 内部直接创建 Fake 或调用 STM32 HAL，Service 就无法在不修改源码的情况下替换依赖。修正方式是把 `const bus_t *` 作为初始化参数注入。

### 10.5 BSP 承担业务逻辑

如果 `bsp_init()` 开始判断设备 ID、重试采样或处理业务状态，组合根会变成难以测试的业务模块。BSP 在本节只创建连接关系并暴露对象。

## 11. 调试观察点

无需真实硬件也可以观察以下变量和调用边界：

- 在 `bsp_init()` 返回前观察 `instances->bus.ops == &fake_bus_ops`。
- 观察 `instances->bus.ctx == &instances->fake_bus_context`，确认 `ops`/`ctx` 成对。
- 观察 `instances->imu_service.bus == &instances->bus`，确认注入方向。
- 在 `bus_read()` 处单步，确认下一跳来自 `bus->ops->read`，而不是硬编码函数。
- 在 `fake_bus_read()` 前后观察 `read_count` 从 `0U` 变为 `1U`。
- 返回 `main()` 后观察 `observed_id == 0xA5U`。

若使用支持函数指针显示的调试器，可比较函数地址；若工具无法友好显示函数指针，至少在 `fake_bus_read()` 设置断点并核对调用栈。这里描述的是建议观察方法，不代表已经执行过调试。

## 12. 实战实验

### 实验目标

用 Host Fake 验证一次 App 请求能沿注入链路到达 Fake；替换 Fake 数据时，App 和 Service 源码保持不变。

### 前置

- 可选：任意支持 C11 的主机编译器。
- 无编译器时，可通过逐行追踪对象地址、函数指针和计数变化完成逻辑验证。
- 不需要开发板、调试器或传感器。

### 步骤

1. 按第 9 节的路径建立文件，保持头文件和源文件分层。
2. 先做静态检查：确认只有 `bsp/bsp.c` 同时引用 `fake_bus_ops` 与 `imu_service_init()`。
3. 若有主机编译器，可自行执行类似命令：

   ```text
   cc -std=c11 -Wall -Wextra -Werror -Iinclude -I. device/bus.c service/imu_service.c platform/host/fake_bus.c bsp/device_instances.c bsp/bsp.c app/app.c main.c -o composition_root_demo
   ```

   本仓库没有该命令的运行记录，因此这不是构建成功声明。
4. 运行后记录进程退出码。预期为 `0`；非零值分别对应组装、调用或验收失败。
5. 把 `HOST_FAKE_DEVICE_ID` 从 `0xA5U` 改为另一个测试值，同时修改 `main.c` 中的预期值；不要修改 `app/app.c` 和 `service/imu_service.c`。
6. 再次验证 `read_count == 1U`。

### 预期现象

- `observed_id` 得到 Fake 的固定字节。
- 每调用一次 `app_run()`，`read_count` 增加一次。
- 替换 Fake 数据不要求修改 App 或 Service。
- 这些结果只证明 Host 逻辑链路；不证明任何 STM32 外设通信成立。

### 失败排查

- 编译器报告找不到头文件：检查 `-Iinclude -I.` 和目录是否一致。
- `bsp_init()` 失败：检查 `fake_bus_ops.read` 和 Fake 上下文地址是否为空。
- 退出码为 `2`：沿 `app_run -> imu_service_read_id -> bus_read` 检查返回值。
- 退出码为 `3`：观察固定返回值、`read_count` 和 `length`；Fake 只接受长度 `1U`。
- 修改 Fake 后被迫修改 Service：说明具体实现细节已经泄漏到服务层，重新检查依赖方向。

### 实验记录建议

记录编译器及版本、完整命令、退出码、修改前后固定字节、`read_count` 和失败尝试。只有实际记录存在后，才能声称完成了 Host 构建或测试；Host 成功也不能把 `hardware_verified` 改为 `true`。

## 13. 自检题

1. 分层图为什么不能替代对象实例化和组装？
2. `bus_ops_t` 与 `bus_t.ctx` 分别解决什么问题？为什么必须成对？
3. `fake_bus_context_t`、`bus_t`、`imu_service_t` 的存储分别在哪里？谁持有它们？
4. 哪一行代码完成了 Bus 到 Service 的依赖注入？
5. 从 `app_run()` 到 `fake_bus_read()` 的完整调用路径是什么？
6. 为什么局部 `fake_bus_context_t` 不能注入长期存活的静态 `bus_t`？
7. 把 Fake 换成 STM32 HAL 实现时，哪些文件应该变化，哪些文件不应变化？

判断是否掌握应依据你的答案、实验记录或后续复习结果；课程被生成出来本身不提高掌握度。

## 14. 面试题

**问题 1：什么是组合根？为什么通常希望它唯一？**

参考要点：它是集中实例化具体对象并连接依赖的入口；唯一边界让实现选择、初始化顺序和生命周期关系可审计，避免业务层到处创建依赖。

**问题 2：C 没有接口和构造函数关键字，如何实现运行时可替换依赖？**

参考要点：用函数指针表表达操作集合，用 `void *ctx` 绑定实例状态，用显式初始化函数校验并保存两者，再由组合根注入使用者。

**问题 3：函数指针表方案的主要风险是什么？**

参考要点：空函数指针、`ops`/`ctx` 类型不匹配、对象生命周期不足、初始化顺序错误；通过单点组装、初始化校验、明确所有权和测试观察点降低风险。

**问题 4：为什么 BSP 不应读取设备 ID 后直接执行业务决策？**

参考要点：BSP 的职责是平台初始化和组装；业务决策放入 BSP 会造成职责混合，让 Host 替换、单元测试和跨平台迁移更困难。

## 15. 延伸思考

- 如果系统有两个 IMU，它们可以共享同一个 `bus_ops_t`，但为什么通常需要不同的 `bus_t.ctx` 或不同的设备上下文？
- 如果 Bus 调用改为异步 DMA，哪些对象必须延长生命周期，完成回调应由哪一层拥有？
- 如何让 `device_instances_t` 在 Host 测试中构造两套彼此隔离的对象，而产品固件仍使用静态单例？
- 若初始化进行到 Service 时失败，组合根是否需要逆序清理已经启动的资源？哪些资源才需要显式清理？

## 16. 本节总结

- 接口声明“能做什么”，具体实现回答“怎样做”，实例化提供真实存储，组合根连接依赖，App 使用已组装对象。
- `ops` 路由到实现函数，`ctx` 路由到实现实例；二者必须匹配。
- `device_instances.c` 持有静态对象，`bsp.c` 是唯一注入者；App 和 Service 不创建具体依赖。
- 被注入对象的生命周期必须不短于使用者。本例用同一静态实例容器保证关系。
- Host Fake 只能验证逻辑路径。没有具体板卡、构建日志和上板证据时，不能声称硬件已验证。

## 17. 下一步

下一节可在保持组合根不变的前提下，把抽象扩展为最小 Bus + IMU 组件驱动：明确设备地址或片选、寄存器读事务、错误模型和设备上下文，再分别准备 Host Fake 与经第一方资料核对的 STM32 适配层。届时仍应让 App 只依赖 IMU Service，并在 BSP 选择具体 Bus 实现。

## 18. 参考资料

- [ST-UM1725] STMicroelectronics, *Description of STM32F4 HAL and low-layer drivers*, UM1725 Rev 8, March 2023. <https://www.st.com/resource/en/user_manual/um1725-description-of-stm32f4-hal-and-lowlayer-drivers-stmicroelectronics.pdf>（访问日期：2026-09-18，第一方来源）
- [ST-UM1905] STMicroelectronics, *Description of STM32F7 HAL and low-layer drivers*, UM1905 Rev 5, February 2023. <https://www.st.com/resource/en/user_manual/um1905-description-of-stm32f7-hal-and-lowlayer-drivers-stmicroelectronics.pdf>（访问日期：2026-09-18，第一方来源）
- [GNU-C-REFERENCE] Free Software Foundation, *The GNU C Reference Manual*, online edition generated with GNU Texinfo 5.2. <https://www.gnu.org/software/gnu-c-manual/gnu-c-manual.html>（访问日期：2026-09-18，允许来源，不计入本仓库第一方来源）

说明：计划中将 F7 HAL/LL 手册写为 UM1850；核对 ST 官方现行文档后，本课使用实际对应的 UM1905。两份 ST 手册只用于 HAL/LL 分层边界，不用于证明本节 Host Fake 已构建或任何具体开发板行为。

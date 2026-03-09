---
title: 线性表
date: 2025-11-24      #创建日期
lastmod: 2025-11-25   #最后更新日期
draft: false           #是否打开草稿
featureimage: ""      #封面图
summary: ""           #总结
categories:           #分类
  - 数据结构
series: ["数据结构"]
series_order: 2
tags:                 #标签
  - 数据结构
  - 线性表
  - 数组
  - 顺序表
---
# 复杂度
复杂度是衡量算法效率的指标，主要分为两种：

- 时间复杂度：执行算法所需的时间

- 空间复杂度：执行算法所需的内存空间

我们使用大O表示法来描述复杂度，表示随着数据规模n的增长，算法执行时间或占用空间的增长趋势
#### 常见复杂度等级（从优到劣）
O(1) < O(log n) < O(n) < O(n log n) < O(n²) < O(2ⁿ) < O(n!)
# 数组
数组是一种线性数据结构，存放的数据在逻辑上排成一条线，在物理上也连续存储，存储类型具有相同的数据类型。
![Array](https://pub-c08efc1d6359499ab42938511d27ed34.r2.dev/array_definition.webp)

**数组的索引从0开始**

## 数组插入元素
因为数组在索引和内存上都是连续的，元素之间没有任何空间存放任何变量，若要在数组中间插入元素，则需要将插入元素后的所有元素全部向后一位，之后再给该索引位置幅值
![ArrayInsert](https://pub-c08efc1d6359499ab42938511d27ed34.r2.dev/arrayInsert.png)
``` C
/* 在数组的索引 index 处插入元素 num */
void insert(int *nums, int size, int num, int index) {
    // 把索引 index 以及之后的所有元素向后移动一位
    for (int i = size - 1; i > index; i--) {
        nums[i] = nums[i - 1];
    }
    // 将 num 赋给 index 处的元素
    nums[index] = num;
}
```
## 数组删除元素
> 同样，若要删除索引i处的元素，需要将索引i后的所有元素前移一位
> ![](https://pub-c08efc1d6359499ab42938511d27ed34.r2.dev/deleteelem.png)
``` C
/* 删除索引 index 处的元素 */
// 注意：stdio.h 占用了 remove 关键词
void removeItem(int *nums, int size, int index) {
    // 把索引 index 之后的所有元素向前移动一位
    for (int i = index; i < size - 1; i++) {
        nums[i] = nums[i + 1];
    }
}
```
## 总结
数组具有以下优缺点：

**优点**
- 可以直接访问指定位置的值，时间复杂度为O(1)
- 内存连续，访问起来很快
- 占用空间小，只占据数组本身的空间
**缺点**
- 大小是固定的，而且需要在定义时指定大小
- 插入和删除的效率低，需要从指定位置之后全都移动，时间复杂度为O(n)
- 因为不知道所需内存大小，容易分配过多内存造成空间浪费
# 顺序表
通过数组实现的线性表就是顺序表
## 定义
``` C
// 数据类型
#define ElemType int

#define MAX_SIZE 10 // 定义最大长度
typedef struct {
   ElemType data[MAX_SIZE]; // 用静态的
   int length; // 顺序表的当前长度
} SqList; // 顺序表的类型定义
```
## 初始化
``` C
// 初始化顺序表
void InitList (SqList L) {
    L.length = 0; // 顺序表初始长度为 0
}
```
这个函数的作用是将传入的顺序表L初始化为一个空表，长度为0。
## 在顺序表插入元素
``` C
// 在 L 的位序 i 处插入元素 e
// 注意区分【位序】和【下标】，位序从1开始，下标从0开始
bool ListInsert(SqList &L, int i, int e) {
  // 判断i的范围是否有效
  if (i < 1 || i > L.length + 1)
    return false;
  // 当前存储的元素已达到最大值，不能插入
  if (L.length >= MAX_SIZE)
    return false;
  // 将第i个元素及之后的元素后移
  for (int j = L.length; j >= i; j--) {
    L.data[j] = L.data[j - 1];
  }
  // 在位置 i 处放入 e
  L.data[i - 1] = e;
  // 长度加1
  L.length++;
  return true;
}
```
## 在顺序表中删除元素
``` C
// 删除顺序表 L 的位序 i，并使用 e 返回删除的值
bool ListDelete (SqList &L, int i, int &e) {
  // 判断 i 的范围是否有效
  if (i < 1 || i > L.length)
    return false;
  // 将被删除的元素赋值给 e
  e = L.data[i - 1];
  // 将第 i 个位置后的元素前移
  for (int j = i; j < L.length; j++) {
    L.data[j - 1] = L.data[j];
  }
  L.length--;
  return true;
}
```
>这里有一个点：当删除一个元素后，原先末尾的元素变得无意义了，不用特地修改
**时间复杂度：**
- 平均下来为O(n)
## 查找顺序表的值：遍历
```C
// 按位序查找，返回的为 值
int ListGetElem (SqList L, int i) {
  // 判断 i 的范围是否有效，-999 为约定的失败代表值可以为任意能代表失败的数
  if (i < 1 || i > L.length)
    return -999;
  return L.data[i - 1];
}

// 按值查找，返回的为位序
int ListLocateElem (SqList L, int e) {
  for (int i = 0; i < L.length; i++) {
    if (L.data[i] == e) {
      // 返回的为 位序，所以是 下标 + 1
      return i + 1;
    }
  }
  return -1;
}
```
时间复杂度也为O(n)
## 顺序表数组的优缺点
**优点**
- 随机访问速度快： 由于数组是一段连续的内存空间,通过索引可以直接访问数组中的任何元素,因此随机访问的时间复杂度为 O(1).这使得数组在需要频繁随机访问元素的情况下非常高效.
- 数组不需要额外的指针存储空间,因此在存储上相对紧凑,更节省空间.

**缺点**
- 大小固定：创建之后不能修改大小
- 插入和删除效率很低：插入删除需要移动之后的所有元素，时间复杂度为O(n)
- 不适合存储变长数据：因为大小固定，因为需要存储的元素大小可变，可能导致内存浪费和无法满足要求
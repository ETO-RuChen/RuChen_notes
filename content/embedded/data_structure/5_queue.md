---
title: 队列
date: 2025-11-28      #创建日期
lastmod: 2025-11-28   #最后更新日期
draft: false          #是否打开草稿
featureimage: ""      #封面图
summary: ""           #总结
categories:           #分类
  - 数据结构
series: ["数据结构"]
series_order: 5
tags:                 #标签
  - 数据结构
  - 队列
---
队列是先进先出的数据结构，只允许从一段插入，另一端删除，进制访问除两端以外的一切数据
## 队列实现
```C
typedef struct {
    int data[MAX_SIZE];
    int front;      // 队头指针
    int rear;       // 队尾指针
    int count;      // 元素数量
} ArrayQueue;
```
## 初始化
```C
void initQueue(ArrayQueue *q) {
    q->front = 0;
    q->rear = 0;
    q->count = 0;
}
```
## 入队
```C
// 入队操作
bool enqueue(ArrayQueue *q, int value) {
    if (isFull(q)) {
        printf("队列已满！\n");
        return false;
    }
    
    q->data[q->rear] = value;
    q->rear = (q->rear + 1) % MAX_SIZE;  // 循环队列
    q->count++;
    return true;
}
```
## 出队
```C
// 出队操作
bool dequeue(ArrayQueue *q, int *value) {
    if (isEmpty(q)) {
        printf("队列为空！\n");
        return false;
    }
    
    *value = q->data[q->front];
    q->front = (q->front + 1) % MAX_SIZE;  // 循环队列
    q->count--;
    return true;
}
```
## 获取队头队列
```C
// 获取队头元素
bool front(ArrayQueue *q, int *value) {
    if (isEmpty(q)) {
        return false;
    }
    *value = q->data[q->front];
    return true;
}
```

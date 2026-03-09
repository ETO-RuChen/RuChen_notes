---
title: 栈
date: 2025-11-28      #创建日期
lastmod: 2025-11-28   #最后更新日期
draft: false          #是否打开草稿
featureimage: "https://pub-c08efc1d6359499ab42938511d27ed34.r2.dev/stack.png"      #封面图
summary: ""           #总结
categories:           #分类
  - 数据结构
series: ["数据结构"]
series_order: 4
tags:                 #标签
  - 数据结构
  - 栈
---
栈的特点是先入后出(FILO)
![](https://pub-c08efc1d6359499ab42938511d27ed34.r2.dev/stack.png)
我们把堆叠元素的顶部称为“栈顶”，底部称为“栈底”。将把元素添加到栈顶的操作叫作“入栈”，删除栈顶元素的操作叫作“出栈”。
# 栈的实现
- 用顺序存储方式实现的栈 -- **顺序栈**
- 用链式存储方式实现的栈 -- **链栈**
## 顺序栈的实现
```C
/* 顺序栈的定义 */
#define MaxSize 10              //定义栈中元素的最大个数
typedef struct{
    ElemType data[MaxSize];     //静态数组存放栈中元素
    int top;                    //栈顶指针
}SqStack;
```
我们以常见的 push()、pop()、peek() 作为元素入栈（添加至栈顶）、栈顶元素出栈、访问栈顶元素的函数名称。
### 初始化
```C
/* 初始化顺序栈 */
void InitStack(SqStack *s){
    s->top = -1;             //初始化栈顶指针
}
```
### 入栈
```C
/* 新元素入栈 */
bool Push(SqStack *S,ElemType x){
    if(S.top == MaxSize - 1)        //栈满，报错
        return false;
    S.top = S.top + 1;              //指针先加1
    S.data[S.top] = x;              //新元素入栈
    /*可以将以上两行合并成一行
    S.data[++S.top] = x;
    */
    return true;
}
```
### 出栈
```C
/* 入栈操作 */
bool Pop(SqStack *S,ElemType &x){   //删除的元素需要返回查看，所以x形参传地址
    if(S.top == -1)                 //栈空，报错
        return false;
    x = S.data[S.top];              //先出栈
    S.top = S.top - 1;              //指针再减1
    /*可以将以上两行合并成一行
    x = S.data[S.top--];
    */
    return true;
}
```
### 访问栈顶元素
```C
/* 读栈顶元素 */
bool GetTop(SqStack S,ElemType &x){   
    if(S.top == -1)                 //栈空，报错
        return false;
    x = S.data[S.top];              //x记录栈顶元素
    return true;
}
```

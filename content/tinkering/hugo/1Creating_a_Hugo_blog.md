---
title: hugo博客创建
date: 2025-11-23
lastmod: 2025-11-23 #最后更新日期
draft: false
featureimage: "https://pub-c08efc1d6359499ab42938511d27ed34.r2.dev/hugo.jpg"
series: ["hugo博客开发"]
series_order: 1
tags:
  - hugo
---
之前问AI如何让自己在找工作时更好的吸引到HR的注意力，AI告诉我可以搞一个个人的技术博客然后把二维码放到简历上，于是我就开始搞起了个人博客，也就有了这篇文章。

# 正式开始
## 安装
首先，我对博客这种一窍不通，别人说hugo好用，是静态博客我也就用了。
我也不怎么会命令行，所以去了hugo的github下载了release。这是仓库：
[hugo仓库](https://github.com/gohugoio/hugo)

## Github仓库
我打算让我的笔记能够直接使用我的域名打开，然后我采用的方案是Github的pages+Cloudflare托管DNS的方式。这需要将我的笔记上传到我的Github仓库。
所以，最方便的方法是先创建一个仓库，然后本地clone
## 创建页面
把仓库克隆下来后在命令行输入`hugo new site --force .`创建一个站点

这会在当前目录生成一个空的hugo网站

命令行输入`hugo server -D`

然后命令行会出现一个`http://localhost:1313/`或者`127.0.0.1:1313`的链接，浏览器打开它，你会看到一个404页面，恭喜你，你已经创建好了一个网页，只不过你啥也没写，所以是404。
## 添加主题
hugo只是一个框架，你还需要一个主题，这里我选择了Blowfish主题，挺好看的。官网链接如下：https://blowfish.page/zh-cn/
其实就是git clone，不会导入的可以去官网查看教程[Blowfish安装教程](https://blowfish.page/zh-cn/docs/installation/)

把`Blowfish`导入到`themes/blowfish`文件夹就算正式导入了

hugo的所有页面配置都依赖于它目录里的`config/_default`文件夹，我们把`themes/blowfish/config/_default`下的所有`*toml`文件全都粘贴到那里
之后`config`文件夹的样子是：
``` 
config/_default/
├─ hugo.toml    #总配置，其实底下的*.toml都可以在这个文件进行配置
├─ languages.en.toml #语言配置，同时也可以配置不同语言的params内容比如作者等
├─ markup.toml  #不知道是干嘛的
├─ menus.en.toml  #这个是配置顶部菜单栏的，好像是不同的页面都可以配置，但是我只配置了主页
├─ module.toml # 如果你通过模块安装，不要将此文件直接覆盖
└─ params.toml  #这个是配置页面的各种参数的
```
把`hugo.toml`下的`theme = "blowfish"`注释取消掉，然后
```
hugo server
```
你看到![](https://pub-c08efc1d6359499ab42938511d27ed34.r2.dev/Blowfish_home.png)

恭喜你，你成功创建了一个网站！
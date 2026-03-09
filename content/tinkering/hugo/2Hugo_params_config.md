---
title: hugo博客配置
date: 2025-11-23
lastmod: 2025-11-23 #最后更新日期
draft: false
featureimage: "https://pub-c08efc1d6359499ab42938511d27ed34.r2.dev/nice_Blowfish_home.png"
series: ["hugo博客开发"]
series_order: 2
tags:
  - hugo
---
上期我们已经实现了hugo站点的搭建，现在我们在让我们的hugo页面更加的美观

这里放上Blowfish的文档页面：[Blowfish](https://blowfish.page/zh-cn/docs/)以供参考

Blowfish的配置主要在`hugo.towl`、`languages.zh-cn.toml`、`menus.zh-cn.toml`和`params.toml`四个toml文件上，这里说明一下，Blowfish同样支持**json**格式和**yaml**格式的配置文件，但是**toml**是hugo官方和Blowfish官方推荐的配置文件。

### hugo.toml
首先是theme,这个在Blowfish的入门指南里有写，共有十种不同的配色主题，我这里默认选择`blowfish`

baseURL是链接的网址，用在需要链接域名的时候

defaultContentLanguage用中文，最终代码是这样
``` toml
theme = "blowfish" # UNCOMMENT THIS LINE
baseURL = "https://195481.xyz/" #这是要链接的网址
defaultContentLanguage = "zh-cn"#默认语言
```
### languages.zh-cn.toml
照着抄，稍微改一下就行
``` toml
  displayName = "简体中文"
  isoCode = "zh-cn"
  rtl = false
  dateFormat = "2006 Jan 02"
  # logo = "img/logo.jpg"
  # secondaryLogo = "img/secondary-logo.png"
  # description = "My awesome website"
  copyright = "All Rights Reserved © RuChen 2025"

[params.author]
  name = "你的昵称"
  email = "你的邮箱@qq.com"
  image = "img/你的头像.jpg"
  imageQuality = 96
  headline = "你的头衔"
  # bio = "你的简介"
```
底下的links我就取消注释了一个github，你们随意
# menus.zh-cn.toml
这是我的配置,照着抄就行
``` toml
# 主菜单 - 嵌入式笔记 (作为下拉菜单的父项)
[[main]]
  name = "嵌入式学习📖"
  identifier = "embedded"
  url = "/embedded/"
  weight = 10

# 嵌入式下的子菜单
[[main]]
  identifier = "embedded-c"
  name = "C语言专题"
  url = "/embedded/c-language/"  # 指向子分区
  weight = 11                   
  parent = "embedded"           # 关键！指定父菜单的 identifier

[[main]]
  identifier = "embedded-stm32"
  name = "STM32专题"
  url = "/embedded/stm32/"
  weight = 12
  parent = "embedded"

# 主菜单 - 项目日志 (另一个下拉菜单)
[[main]]
  name = "项目日志📒"
  identifier = "projects"
  url = "/projects/"
  weight = 10

# 捣鼓记 (如果没有子项，就保持原样)
[[main]]
  name = "捣鼓日常🛠️"
  identifier = "tinkering"
  url = "/tinkering/"
  weight = 10

[[main]]
  name = "标签🏷️"
  url = "/tags/"
  weight = 30

#友链相关的菜单项
[[main]]
  name = "友链🔗"
  identifier = "friends"
  weight = 20

[[main]]
  name = "Haley's Blog"
  identifier = "friend-somebody"
  parent = "friends"
  url = "https://your_friend_domain.xyz/"
  weight = 20
```
# params.toml
这个里面需要配置的东西最多，可以分为很多类，分开来说：
## 全局
全局就是最前面的那一堆，我挑几个重点的：
- `colorScheme` 是颜色方案，选择blowfish默认。
- `enableSearch`是否开启网站的搜索功能，设为`true`即为启用。
- `mainSections`指定最近文章中应该展示的模块。 如果没有指定，则使用文章数量最多的板块。
- `defaultBackgroundImage`设置默认背景图用于`background`和`hero`布局下的主页。
- `defaultFeaturedImage`设置默认背景图片用于所有文章的`featured`图片。
- `highlightCurrentMenuArea`当菜单被选择时，标记主菜单中的菜单项。
- `smartTOC`开启智能目录，视图中的项目将会被高亮显示。

## 主页homepage
- `layout`布局参数。合法的参数值有：`page`、`profile`、`hero`、`card`、`background`或`custom`，我选择`background`
- `homepageImage`主页背景
- `showRecent`是否在主页展示最新文章列表。我选true
- `layoutBackgroundBlur`向下滚动主页时，是否模糊背景图。
- `cardView`将列表展示为卡片容器。

## 文章页article
- `showDate`是否显示日期。
- `showDateUpdated`是否展示文章的更新日期。
- `heroStyle`hero图像的展示样式，可选的参数值有：`basic`、`big`、`background`、`thumbAndBackground`
- `showBreadcrumbs`是否在标题栏显示面包屑导航。
- `seriesOpened`是否默认显示打开系列模块
- `showPagination`是否在文章末尾展示上一篇/下一篇的文章链接
- `showTableOfContents`是否展示文章的目录
- `showComments`是否在文章末尾添加[评论部分](https://blowfish.page/zh-cn/docs/partials/#comments)
- `showWordCount`是否显示文章的字数
## 列表页
- `showHero`缩略图是否会在每个页面中作为`hero`图像显示,就是每个文章的图片
- `heroStyle`hero 图像的展示样式，这个可以理解为列表页的那张图的放置方式
- `showBreadcrumbs`是否在标题栏显示面包屑导航
- `layoutBackgroundBlur`向下滚动列表页时，是否模糊背景图
- `groupByYear`是否根据年做聚合
- `cardView`将列表展示为卡片容器
# 最后
其他的我就没怎么搞了
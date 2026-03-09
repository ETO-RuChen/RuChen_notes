---
title: hugo博客评论系统
date: 2025-11-23
lastmod: 2025-11-23 #最后更新日期
draft: false
featureimage: "https://pub-c08efc1d6359499ab42938511d27ed34.r2.dev/Comments_System.png"
series: ["hugo博客开发"]
series_order: 3
tags:
  - hugo
  - 评论系统
---
Blowfish 支持了在每篇文章底部添加一个评论功能。只需要提供一个 layouts/partials/comments.html 文件，并在其中添加显示评论的代码即可。
我是使用Giscus（基于Github的Discussions）
1. 在Github打开Discussions
2. 安装Giscus
访问[giscus.app](https://giscus.app/zh-CN)，按步骤配置：
- 输入你的 GitHub 仓库（格式：用户名/仓库名）
- 选择 "Discussions" 作为评论来源
- 选择主题（推荐 preferred_color_scheme 跟随系统）
- 复制生成的配置代码
3. 在`Blowfish`中配置
在在`hugo.toml`中添加：
``` toml
[giscus]
  enabled = true
  repo = "仓库地址"
  repoID = "R_kgDOJxxxxxxxx"  # 在 giscus.app 获取
  category = "Announcements"
  categoryID = "DIC_kwDOJxxxxxxxx"  # 在 giscus.app 获取
  mapping = "pathname"
  strict = "0"
  reactionsEnabled = "1"
  emitMetadata = "0"
  inputPosition = "top"
  theme = "catppuccin_frappe"
  lang = "zh-CN"
  loading = "lazy"
```
这个是在giscus官网生成的，不要复制我的
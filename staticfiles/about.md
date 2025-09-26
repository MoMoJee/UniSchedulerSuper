
# UniSchedulerSuper 项目结构概述

UniSchedulerSuper 是一个基于 Django 的时间管理和规划系统，主要由以下几个部分组成：

## 核心应用结构

项目采用 Django 框架，分为多个应用（apps）：

1. **core** 核心应用

      - 包含用户认证（登录/注册）
   
      - 用户数据模型（UserData, UserProfile）
   
      - 主页面和基础功能
   
      - 协作事件管理（CollaborativeEventGroup, CollaborativeEvent）

2. **planner** 规划应用

      - AI 辅助规划功能
   
      - 事件创建和管理
   
      - 使用 LLM（大型语言模型）进行智能建议
   
      - 临时事件与主数据合并功能

3. **ai_chatting** AI 聊天应用

      - AI 对话功能

      - 用于测试 AI 和前端交互接口

4. **utils** 工具库

      - 通用工具函数
   
      - 用户偏好 AI 设置等辅助功能

## 技术栈

项目使用的主要技术和依赖包括：

- **Django 5.1.8+** - Web 框架
- **OpenAI API** - AI 功能实现
- **Ollama** - 本地 AI 模型支持
- **SQLite** - 数据库
- **其他依赖**：accelerate, django-cors-headers, pytz, markdown, icalendar, requests

## 数据模型

核心数据模型包括：

- **UserProfile** - 用户个人资料
- **UserData** - 用户数据存储（采用键值对形式存储各种用户数据）
- **CollaborativeEventGroup** - 协作事件组
- **CollaborativeEvent** - 协作事件

## AI 功能

项目集成了多种 AI 功能：

- 智能规划建议
- 基于用户对话的事件创建
- 预设场景匹配和更新
- 语义匹配和工具调用

## 文件组织

- **templates/** - HTML 模板文件
- **static/** - 静态资源（JS, CSS 等）
- **migrations/** - 数据库迁移文件
- **views.py** - 视图函数（处理 HTTP 请求）
- **urls.py** - URL 路由配置
- **models.py** - 数据模型定义
- **LLMFunctions.py** - AI 相关功能实现

## 部署和运行

项目运行需要：

1. Python 3.12 环境
2. 安装依赖：`pip install -r requirements.txt`
3. 启动服务器：`python manage.py runserver 0.0.0.0:8000`

项目支持本地部署和网络访问，可以通过指定 IP 和端口进行配置。

## 总结

UniSchedulerSuper 是一个结合了传统日程管理和 AI 智能规划的综合系统，通过 Django 框架实现了前后端交互，并利用 OpenAI API 提供智能建议和对话功能，帮助用户更高效地管理时间和规划日程。
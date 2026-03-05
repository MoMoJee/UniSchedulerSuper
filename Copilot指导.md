# Copilot 开发指南

## 项目技术栈
- 框架：Django + Django Channels
- 数据库：SQLite
- 特殊依赖：daphne (ASGI 服务器), websocket

## 开发环境启动
```bash
cd /home/momojee/Projects/UniSchedulerSuper
source .venv/bin/activate
python manage.py runserver
```

## 代码修改后的必要步骤
1. 收集静态文件：`python manage.py collectstatic --noinput`
2. 数据库迁移（如有）：`python manage.py migrate`
3. 重启服务：
   ```bash
   pkill -f "daphne\|runserver"
   daphne -b 0.0.0.0 -p 8000 UniSchedulerSuper.asgi:application &
   ```
4. 验证功能

## 注意事项
- 本项目使用 WebSocket (Django Channels)，必须使用 daphne 而非 runserver
- 修改前端 JS 后注意收集静态文件

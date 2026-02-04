from django.apps import AppConfig


class MyappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    
    def ready(self):
        # 启用 SQLite WAL 模式以提高并发性能
        from django.db.backends.signals import connection_created
        
        def enable_wal_mode(sender, connection, **kwargs):
            if connection.vendor == 'sqlite':
                cursor = connection.cursor()
                cursor.execute('PRAGMA journal_mode=WAL;')
                cursor.execute('PRAGMA busy_timeout=30000;')  # 30秒超时
        
        connection_created.connect(enable_wal_mode)

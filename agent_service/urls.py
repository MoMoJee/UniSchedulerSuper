"""
Agent Service URL 配置
"""
from django.urls import path
from . import views_api

app_name = 'agent_service'

urlpatterns = [
    # 健康检查
    path('health/', views_api.health_check, name='health_check'),
    
    # Session 管理
    path('sessions/', views_api.list_sessions, name='list_sessions'),
    path('sessions/create/', views_api.create_session, name='create_session'),
    path('sessions/<str:session_id>/', views_api.delete_session, name='delete_session'),
    path('sessions/<str:session_id>/rename/', views_api.rename_session, name='rename_session'),
    
    # 历史查询
    path('history/', views_api.get_history, name='get_history'),
    
    # 回滚功能
    path('rollback/preview/', views_api.rollback_preview, name='rollback_preview'),
    path('rollback/', views_api.execute_rollback, name='execute_rollback'),
    path('rollback/to-message/', views_api.rollback_to_message, name='rollback_to_message'),
    
    # 专家配置
    path('experts/', views_api.get_available_experts, name='get_experts'),
]

"""
Agent Service URL 配置
"""
from django.urls import path
from . import views_api
from . import views_memory_api

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
    
    # 记忆优化
    path('optimize-memory/', views_api.optimize_memory, name='optimize_memory'),
    
    # 会话 TO DO
    path('session-todos/', views_api.get_session_todos, name='get_session_todos'),
    
    # 工具配置 (新)
    path('tools/', views_api.get_available_tools, name='get_tools'),
    
    # 专家配置 (旧，兼容)
    path('experts/', views_api.get_available_experts, name='get_experts'),
    
    # ==========================================
    # 记忆管理 API
    # ==========================================
    
    # 个人信息
    path('memory/personal-info/', views_memory_api.list_personal_info, name='list_personal_info'),
    path('memory/personal-info/create/', views_memory_api.create_personal_info, name='create_personal_info'),
    path('memory/personal-info/<int:pk>/', views_memory_api.update_personal_info, name='update_personal_info'),
    path('memory/personal-info/<int:pk>/delete/', views_memory_api.delete_personal_info, name='delete_personal_info'),
    
    # 对话风格
    path('memory/dialog-style/', views_memory_api.get_dialog_style, name='get_dialog_style'),
    path('memory/dialog-style/update/', views_memory_api.update_dialog_style, name='update_dialog_style'),
    path('memory/dialog-style/reset/', views_memory_api.reset_dialog_style, name='reset_dialog_style'),
    
    # 工作流规则
    path('memory/workflow-rules/', views_memory_api.list_workflow_rules, name='list_workflow_rules'),
    path('memory/workflow-rules/create/', views_memory_api.create_workflow_rule, name='create_workflow_rule'),
    path('memory/workflow-rules/<int:pk>/', views_memory_api.update_workflow_rule, name='update_workflow_rule'),
    path('memory/workflow-rules/<int:pk>/delete/', views_memory_api.delete_workflow_rule, name='delete_workflow_rule'),
    path('memory/workflow-rules/<int:pk>/toggle/', views_memory_api.toggle_workflow_rule, name='toggle_workflow_rule'),
    
    # 附件系统
    path('attachments/', views_api.get_attachable_items, name='get_attachable_items'),
    path('attachments/format/', views_api.format_attachment_content, name='format_attachment_content'),
]

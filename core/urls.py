from django.urls import path
from . import views
from . import views_events
from . import views_token
from . import views_share_groups
from . import views_rollback
from . import views_import_events
from . import views_calendar_subscription
from . import views_planner_v2
from . import views_planner_legacy
from file_service import views_page as file_views

urlpatterns = [
    path('', views.index, name='index'),
    path('dev-trial/', views.trial, name='dev-trial'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('home/', views.home, name='home'),
    path('home/<path:frontend_path>/', views.home, name='react_home_route'),
    path('user_register/', views.user_register, name='user_register'),
    path('user_login/', views.user_login, name='user_login'),
    path('user_logout/', views.user_logout, name='user_logout'),
    path('password-reset/', views.password_reset_page, name='password_reset_page'),
    path('user_data/', views.user_data, name='user_data'),
    path('user_preferences/', views.user_preferences, name='user_preferences'),
    path('help/', views.help_page, name='help_page'),
    path('files/', file_views.files_page, name='files_page'),

    # ===== Token 认证 API =====
    path('api/auth/login/', views_token.api_login, name='api_login'),
    path('api/auth/logout/', views_token.api_logout, name='api_logout'),
    path('api/auth/token/', views_token.get_token, name='get_token'),
    path('api/auth/token/refresh/', views_token.refresh_token, name='refresh_token'),
    path('api/auth/token/verify/', views_token.verify_token, name='verify_token'),
    path('api/auth/token/delete/', views_token.delete_token, name='delete_token'),
    # path('token-management/', views_token.token_management_page, name='token_management'),
    
    # User account management
    path('api/user/change-username/', views.change_username, name='change_username'),
    path('api/user/change-password/', views.change_password, name='change_password'),
    
    # Email verification
    path('api/email/request-verification/', views.request_email_verification, name='request_email_verification'),
    path('api/email/verify-code/', views.verify_email_code, name='verify_email_code'),
    
    # Password reset
    path('api/password-reset/request/', views.request_password_reset, name='request_password_reset'),
    path('api/password-reset/verify/', views.verify_reset_code, name='verify_reset_code'),
    path('api/password-reset/reset/', views.reset_password, name='reset_password'),
    path('api/password-reset/token/', views.reset_password_with_token, name='reset_password_with_token'),

    path("get_calendar/change_view/", views.change_view, name="change_view"),
    path("get_calendar/user_settings/", views.user_settings, name="user_settings"),
    
    # Events API
    path('get_calendar/events/', views_planner_legacy.retired_planner_v1_api, name='get_events'),
    path('get_calendar/update_events/', views_planner_legacy.retired_planner_v1_api, name='update_events'),
    # path('get_calendar/delete_event/', views.delete_event, name='delete_event'),  # 已弃用
    path('events/create_event/', views_planner_legacy.retired_planner_v1_api, name='create_event'),
    path('api/events/groups/', views_planner_legacy.retired_planner_v1_api, name='get_events_groups'),
    path('get_calendar/create_events_group/', views_planner_legacy.retired_planner_v1_api, name='create_events_group'),
    path('get_calendar/update_events_group/', views_planner_legacy.retired_planner_v1_api, name='update_events_group'),
    path('get_calendar/delete_event_groups/', views_planner_legacy.retired_planner_v1_api, name='delete_event_groups'),
    path('get_calendar/import_events/', views.import_events, name='import_events'),
    path('get_calendar/resources/', views.get_resources, name='get_resources'),
    path("get_calendar/get_outport_calendar/", views.get_outport_calendar, name="get_outport_calendar"),
    path("get_calendar/outport_calendar/", views.outport_calendar, name="outport_calendar"),
    path("get_calendar/check_modified_events", views.check_modified_events, name="check_modified_events"),
    path('api/events/bulk-edit/', views_planner_legacy.retired_planner_v1_api, name='bulk_edit_events'),
    path('api/v2/events/definitions/', views_planner_v2.list_event_definitions_v2, name='v2_event_definitions'),
    path('api/v2/planner/bootstrap/', views_planner_v2.planner_bootstrap_v2, name='v2_planner_bootstrap'),
    path('api/v2/events/occurrences/', views_planner_v2.list_event_occurrences_v2, name='v2_event_occurrences'),
    path('api/v2/events/conflicts/', views_planner_v2.list_event_conflicts_v2, name='v2_event_conflicts'),
    path('api/v2/events/', views_planner_v2.create_event_v2, name='v2_event_create'),
    path('api/v2/events/<str:event_id>/', views_planner_v2.event_command_v2, name='v2_event_command'),
    path('api/v2/search/', views_planner_v2.search_events_v2, name='v2_planner_search'),
    path('api/v2/groups/', views_planner_v2.groups_v2, name='v2_planner_groups'),
    path('api/v2/groups/<str:group_id>/', views_planner_v2.group_command_v2, name='v2_planner_group_command'),
    path('api/v2/todos/', views_planner_v2.todos_v2, name='v2_planner_todos'),
    path('api/v2/todos/<str:todo_id>/', views_planner_v2.todo_command_v2, name='v2_planner_todo_command'),
    path('api/v2/todos/<str:todo_id>/convert/', views_planner_v2.convert_todo_v2, name='v2_planner_todo_convert'),
    path('api/v2/reminders/', views_planner_v2.reminders_v2, name='v2_planner_reminders'),
    path('api/v2/reminders/<str:reminder_id>/', views_planner_v2.reminder_command_v2, name='v2_planner_reminder_command'),
    path('api/v2/reminders/occurrences/action/', views_planner_v2.reminder_occurrence_action_v2, name='v2_planner_reminder_occurrence_action'),
    path('api/v2/share-groups/<str:share_group_id>/occurrences/', views_planner_v2.shared_group_occurrences_v2, name='v2_shared_group_occurrences'),
    
    # ===== 课表导入 API =====
    path('api/import/semesters/', views_import_events.get_semesters, name='get_semesters'),
    path('api/import/fetch/', views_import_events.fetch_courses, name='fetch_courses'),
    path('api/import/confirm/', views_import_events.confirm_import, name='confirm_import'),
    # 兼容旧接口
    path('api/import/fetch-courses/', views_import_events.fetch_and_parse_courses, name='fetch_courses_legacy'),
    path('api/import/confirm-courses/', views_import_events.confirm_import_courses, name='confirm_import_courses_legacy'),
    
    # Agent Rollback API
    path('api/agent/rollback/', views_rollback.rollback_transaction_impl, name='rollback_transaction'),

    # ===== 日历订阅 Feed =====
    path('api/calendar/feed/', views_calendar_subscription.calendar_feed, name='calendar_feed'),

    # Reminders API
    path('api/reminders/', views_planner_legacy.retired_planner_v1_api, name='get_reminders'),
    path('api/reminders/create/', views_planner_legacy.retired_planner_v1_api, name='create_reminder'),
    path('api/reminders/update/', views_planner_legacy.retired_planner_v1_api, name='update_reminder'),
    path('api/reminders/update-status/', views_planner_legacy.retired_planner_v1_api, name='update_reminder_status'),
    path('api/reminders/bulk-edit/', views_planner_legacy.retired_planner_v1_api, name='bulk_edit_reminders'),
    path('api/reminders/convert-to-single/', views_planner_legacy.retired_planner_v1_api, name='convert_recurring_to_single'),
    path('api/reminders/delete/', views_planner_legacy.retired_planner_v1_api, name='delete_reminder'),
    path('api/reminders/snooze/', views_planner_legacy.retired_planner_v1_api, name='snooze_reminder'),
    path('api/reminders/dismiss/', views_planner_legacy.retired_planner_v1_api, name='dismiss_reminder'),
    path('api/reminders/complete/', views_planner_legacy.retired_planner_v1_api, name='complete_reminder'),
    path('api/reminders/pending/', views_planner_legacy.retired_planner_v1_api, name='get_pending_reminders'),
    path('api/reminders/maintain/', views_planner_legacy.retired_planner_v1_api, name='maintain_reminders'),
    path('api/reminders/mark-sent/', views_planner_legacy.retired_planner_v1_api, name='mark_notification_sent'),

    # Todos API
    path('api/todos/', views_planner_legacy.retired_planner_v1_api, name='get_todos'),
    path('api/todos/create/', views_planner_legacy.retired_planner_v1_api, name='create_todo'),
    path('api/todos/update/', views_planner_legacy.retired_planner_v1_api, name='update_todo'),
    path('api/todos/delete/', views_planner_legacy.retired_planner_v1_api, name='delete_todo'),
    path('api/todos/convert/', views_planner_legacy.retired_planner_v1_api, name='convert_todo_to_event'),
    
    # ===== 分享群组 API =====
    path('api/share-groups/create/', views_share_groups.create_share_group, name='create_share_group'),
    path('api/share-groups/my-groups/', views_share_groups.get_my_share_groups, name='get_my_share_groups'),
    path('api/share-groups/join/', views_share_groups.join_share_group, name='join_share_group'),
    path('api/share-groups/<str:share_group_id>/leave/', views_share_groups.leave_share_group, name='leave_share_group'),
    path('api/share-groups/<str:share_group_id>/delete/', views_share_groups.delete_share_group, name='delete_share_group'),
    path('api/share-groups/<str:share_group_id>/update/', views_share_groups.update_share_group, name='update_share_group'),
    path('api/share-groups/<str:share_group_id>/events/', views_planner_legacy.retired_planner_v1_api, name='get_share_group_events'),
    path('api/share-groups/<str:share_group_id>/check-update/', views_share_groups.check_group_update, name='check_group_update'),
    path('api/share-groups/<str:share_group_id>/members/', views_share_groups.get_share_group_members, name='get_share_group_members'),
    path('api/share-groups/<str:share_group_id>/update-member-color/', views_share_groups.update_member_color, name='update_member_color'),
    
    # Other
    path("friendly_link/", views.friendly_link, name="friendly_link"),
    path("me/", views.me, name="me"),
    path("three_body/", views.three_body, name="three_body"),
    path("animation/", views.animation, name="animation"),
]

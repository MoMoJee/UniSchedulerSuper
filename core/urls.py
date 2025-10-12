from django.urls import path
from . import views
from . import views_events

urlpatterns = [
    path('', views.index, name='index'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('home/', views.home, name='home'),
    path('user_register/', views.user_register, name='user_register'),
    path('user_login/', views.user_login, name='user_login'),
    path('user_logout/', views.user_logout, name='user_logout'),
    path('user_data/', views.user_data, name='user_data'),
    path('user_preferences/', views.user_preferences, name='user_preferences'),
    
    # Events API
    path('get_calendar/events/', views.get_events, name='get_events'),
    path('get_calendar/update_events/', views.update_events, name='update_events'),
    path('get_calendar/delete_event/', views.delete_event, name='delete_event'),
    path('events/create_event/', views.create_event, name='create_event'),
    path('get_calendar/create_events_group/', views.create_events_group, name='create_events_group'),
    path('get_calendar/update_events_group/', views.update_event_group, name='update_events_group'),
    path('get_calendar/delete_event_groups/', views.delete_event_groups, name='delete_event_groups'),
    path('get_calendar/import_events/', views.import_events, name='import_events'),
    path('get_calendar/resources/', views.get_resources, name='get_resources'),
    path("get_calendar/get_outport_calendar/", views.get_outport_calendar, name="get_outport_calendar"),
    path("get_calendar/outport_calendar/", views.outport_calendar, name="outport_calendar"),
    path("get_calendar/check_modified_events", views.check_modified_events, name="check_modified_events"),
    path("get_calendar/change_view/", views.change_view, name="change_view"),
    path("get_calendar/user_settings/", views.user_settings, name="user_settings"),
    path('api/events/bulk-edit/', views_events.bulk_edit_events_impl, name='bulk_edit_events'),
    
    # Reminders API
    path('api/reminders/', views.get_reminders, name='get_reminders'),
    path('api/reminders/create/', views.create_reminder, name='create_reminder'),
    path('api/reminders/update/', views.update_reminder, name='update_reminder'),
    path('api/reminders/update-status/', views.update_reminder_status, name='update_reminder_status'),
    path('api/reminders/bulk-edit/', views.bulk_edit_reminders, name='bulk_edit_reminders'),
    path('api/reminders/convert-to-single/', views.convert_recurring_to_single, name='convert_recurring_to_single'),
    path('api/reminders/delete/', views.delete_reminder, name='delete_reminder'),
    path('api/reminders/snooze/', views.snooze_reminder, name='snooze_reminder'),  # TODO 这个 URL 貌似没有用法了
    path('api/reminders/dismiss/', views.dismiss_reminder, name='dismiss_reminder'),  # TODO 这个 URL 貌似没有用法了
    path('api/reminders/complete/', views.complete_reminder, name='complete_reminder'),  # TODO 这个 URL 貌似没有用法了
    path('api/reminders/pending/', views.get_pending_reminders, name='get_pending_reminders'),
    path('api/reminders/maintain/', views.maintain_reminders, name='maintain_reminders'),
    path('api/reminders/mark-sent/', views.mark_notification_sent, name='mark_notification_sent'),

    # Todos API
    path('api/todos/', views.get_todos, name='get_todos'),
    path('api/todos/create/', views.create_todo, name='create_todo'),
    path('api/todos/update/', views.update_todo, name='update_todo'),
    path('api/todos/delete/', views.delete_todo, name='delete_todo'),
    path('api/todos/convert/', views.convert_todo_to_event, name='convert_todo_to_event'),
    
    # Other
    path("friendly_link/", views.friendly_link, name="friendly_link"),
    path("three_body/", views.three_body, name="three_body"),
]

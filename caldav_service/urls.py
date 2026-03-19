from django.urls import path, re_path

from caldav_service.views.principal import ServiceRootView, PrincipalView
from caldav_service.views.calendar_home import CalendarHomeView
from caldav_service.views.calendar import CalendarCollectionView
from caldav_service.views.event import EventObjectView

urlpatterns = [
    # CalDAV 服务根
    path('', ServiceRootView.as_view(), name='caldav_root'),

    # 用户主体（Principal）
    path('principals/<str:username>/', PrincipalView.as_view(), name='caldav_principal'),

    # 日历主目录（Calendar Home Set）
    path('<str:username>/', CalendarHomeView.as_view(), name='caldav_calendar_home'),

    # 日历集合（Calendar Collection）
    path('<str:username>/<str:calendar_id>/', CalendarCollectionView.as_view(), name='caldav_calendar'),

    # 日历对象资源（单个事件 .ics）
    re_path(
        r'^(?P<username>[^/]+)/(?P<calendar_id>[^/]+)/(?P<event_uid>[^/]+)\.ics$',
        EventObjectView.as_view(),
        name='caldav_event',
    ),
]

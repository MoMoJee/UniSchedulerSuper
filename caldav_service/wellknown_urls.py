from django.urls import path
from caldav_service.views.wellknown import wellknown_caldav_view

urlpatterns = [
    path('', wellknown_caldav_view, name='wellknown_caldav'),
]

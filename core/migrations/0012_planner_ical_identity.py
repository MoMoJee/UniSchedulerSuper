import json

from django.db import migrations, models


UID_DOMAIN = 'unischeduler'


def forward_identity(apps, schema_editor):
    CalendarEvent = apps.get_model('core', 'CalendarEvent')
    EventRecurrenceSeries = apps.get_model('core', 'EventRecurrenceSeries')
    UserData = apps.get_model('core', 'UserData')

    legacy = {}
    for row in UserData.objects.filter(key='events').order_by('user_id', 'id'):
        try:
            payload = json.loads(row.value)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, list):
            continue
        for item in payload:
            if isinstance(item, dict) and item.get('id') and item.get('caldav_uid'):
                legacy[(row.user_id, str(item['id']))] = str(item['caldav_uid'])

    for event in CalendarEvent.objects.all().iterator():
        explicit = legacy.get((event.user_id, event.event_id), '')
        event.ical_uid = explicit or f'evt-{event.event_id}@{UID_DOMAIN}'
        event.caldav_resource_name = explicit or event.event_id
        event.save(update_fields={'ical_uid', 'caldav_resource_name'})

    for series in EventRecurrenceSeries.objects.select_related('master_event').all().iterator():
        explicit = legacy.get((series.user_id, series.master_event.event_id), '')
        metadata = dict(series.ical_metadata or {})
        metadata.setdefault('_p5_previous_ical_uid', series.ical_uid)
        series.ical_uid = explicit or f'evt-series-{series.series_id}@{UID_DOMAIN}'
        series.caldav_resource_name = explicit or f'evt-series-{series.series_id}'
        series.ical_metadata = metadata
        series.save(update_fields={'ical_uid', 'caldav_resource_name', 'ical_metadata'})


def reverse_identity(apps, schema_editor):
    EventRecurrenceSeries = apps.get_model('core', 'EventRecurrenceSeries')
    for series in EventRecurrenceSeries.objects.all().iterator():
        metadata = dict(series.ical_metadata or {})
        previous = metadata.pop('_p5_previous_ical_uid', None)
        if previous is not None:
            series.ical_uid = previous
            series.ical_metadata = metadata
            series.save(update_fields={'ical_uid', 'ical_metadata'})


class Migration(migrations.Migration):

    dependencies = [('core', '0011_planner_rollback_snapshot')]

    operations = [
        migrations.AddField(
            model_name='calendarevent',
            name='ical_uid',
            field=models.CharField(blank=True, default='', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='calendarevent',
            name='caldav_resource_name',
            field=models.CharField(blank=True, default='', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='eventrecurrenceseries',
            name='caldav_resource_name',
            field=models.CharField(blank=True, default='', max_length=255),
            preserve_default=False,
        ),
        migrations.RunPython(forward_identity, reverse_identity),
        migrations.AddConstraint(
            model_name='calendarevent',
            constraint=models.UniqueConstraint(fields=('user', 'ical_uid'), name='planner_event_user_ical_uid_uniq'),
        ),
        migrations.AddConstraint(
            model_name='calendarevent',
            constraint=models.UniqueConstraint(
                fields=('user', 'caldav_resource_name'), name='planner_event_user_caldav_resource_uniq'
            ),
        ),
        migrations.AddConstraint(
            model_name='eventrecurrenceseries',
            constraint=models.UniqueConstraint(
                fields=('user', 'caldav_resource_name'), name='planner_event_series_resource_uniq'
            ),
        ),
    ]

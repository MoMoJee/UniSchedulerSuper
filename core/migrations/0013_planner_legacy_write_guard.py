from django.db import migrations, models


PLANNER_KEYS_SQL = "'events','todos','reminders','events_groups','events_rrule_series','rrule_series_storage'"


CREATE_TRIGGERS = f"""
CREATE TRIGGER IF NOT EXISTS p6_userdata_planner_insert_guard
BEFORE INSERT ON core_userdata
WHEN EXISTS (SELECT 1 FROM core_plannerlegacywriteguard WHERE singleton = 1 AND enabled = 1)
 AND NEW.key IN ({PLANNER_KEYS_SQL})
BEGIN SELECT RAISE(ABORT, 'P6_LEGACY_PLANNER_WRITE_FORBIDDEN'); END;

CREATE TRIGGER IF NOT EXISTS p6_userdata_planner_update_guard
BEFORE UPDATE ON core_userdata
WHEN EXISTS (SELECT 1 FROM core_plannerlegacywriteguard WHERE singleton = 1 AND enabled = 1)
 AND (OLD.key IN ({PLANNER_KEYS_SQL}) OR NEW.key IN ({PLANNER_KEYS_SQL}))
BEGIN SELECT RAISE(ABORT, 'P6_LEGACY_PLANNER_WRITE_FORBIDDEN'); END;

CREATE TRIGGER IF NOT EXISTS p6_userdata_planner_delete_guard
BEFORE DELETE ON core_userdata
WHEN EXISTS (SELECT 1 FROM core_plannerlegacywriteguard WHERE singleton = 1 AND enabled = 1)
 AND OLD.key IN ({PLANNER_KEYS_SQL})
BEGIN SELECT RAISE(ABORT, 'P6_LEGACY_PLANNER_WRITE_FORBIDDEN'); END;

CREATE TRIGGER IF NOT EXISTS p6_group_calendar_projection_insert_guard
BEFORE INSERT ON group_calendar_data
WHEN EXISTS (SELECT 1 FROM core_plannerlegacywriteguard WHERE singleton = 1 AND enabled = 1)
 AND NEW.events_data <> '[]'
BEGIN SELECT RAISE(ABORT, 'P6_GROUP_EVENTS_PROJECTION_WRITE_FORBIDDEN'); END;

CREATE TRIGGER IF NOT EXISTS p6_group_calendar_projection_update_guard
BEFORE UPDATE OF events_data ON group_calendar_data
WHEN EXISTS (SELECT 1 FROM core_plannerlegacywriteguard WHERE singleton = 1 AND enabled = 1)
 AND OLD.events_data IS NOT NEW.events_data
BEGIN SELECT RAISE(ABORT, 'P6_GROUP_EVENTS_PROJECTION_WRITE_FORBIDDEN'); END;
"""

DROP_TRIGGERS = """
DROP TRIGGER IF EXISTS p6_userdata_planner_insert_guard;
DROP TRIGGER IF EXISTS p6_userdata_planner_update_guard;
DROP TRIGGER IF EXISTS p6_userdata_planner_delete_guard;
DROP TRIGGER IF EXISTS p6_group_calendar_projection_insert_guard;
DROP TRIGGER IF EXISTS p6_group_calendar_projection_update_guard;
"""


class Migration(migrations.Migration):
    dependencies = [('core', '0012_planner_ical_identity')]

    operations = [
        migrations.CreateModel(
            name='PlannerLegacyWriteGuard',
            fields=[
                ('singleton', models.BooleanField(default=True, editable=False, primary_key=True, serialize=False)),
                ('enabled', models.BooleanField(default=False)),
                ('enabled_at', models.DateTimeField(blank=True, null=True)),
                ('archive_manifest_sha256', models.CharField(blank=True, max_length=64)),
                ('metadata', models.JSONField(blank=True, default=dict)),
            ],
        ),
        migrations.RunSQL(CREATE_TRIGGERS, DROP_TRIGGERS),
    ]

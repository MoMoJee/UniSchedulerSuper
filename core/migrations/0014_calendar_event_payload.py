from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [('core', '0013_planner_legacy_write_guard')]

    operations = [
        migrations.AddField(
            model_name='calendarevent',
            name='payload',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

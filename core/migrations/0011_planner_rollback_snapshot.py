import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('agent_service', '0028_agent_rollback_window'),
        ('core', '0010_planner_cohort_assignment'),
    ]

    operations = [
        migrations.AddField(
            model_name='plannerchangeset', name='affected_refs',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='plannerchangeset', name='after_hash',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='plannerchangeset', name='before_hash',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='plannerchangeset', name='rollback_status',
            field=models.CharField(default='not_reversible', max_length=24),
        ),
        migrations.AddField(
            model_name='plannerchangeset', name='source',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.CreateModel(
            name='PlannerRollbackSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('schema_version', models.PositiveIntegerField(default=1)),
                ('codec', models.CharField(default='zlib-json-v1', max_length=32)),
                ('payload', models.BinaryField()),
                ('payload_sha256', models.CharField(max_length=64)),
                ('uncompressed_size', models.PositiveBigIntegerField()),
                ('expires_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('change_set', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='rollback_snapshot', to='core.plannerchangeset')),
                ('rollback_window', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='planner_snapshots', to='agent_service.agentrollbackwindow')),
            ],
            options={
                'indexes': [models.Index(fields=['rollback_window', 'created_at'], name='planner_snapshot_window_idx')],
            },
        ),
    ]

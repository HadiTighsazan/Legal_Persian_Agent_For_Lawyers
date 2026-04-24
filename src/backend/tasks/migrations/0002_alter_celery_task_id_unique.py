# Generated manually to remove unique=True from celery_task_id
# and replace it with db_index=True (since multiple tasks per document
# may share the same chain ID, and we need to allow that).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='processingtask',
            name='celery_task_id',
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
    ]

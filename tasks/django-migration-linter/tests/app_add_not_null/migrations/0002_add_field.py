from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies = [("app_add_not_null", "0001_initial")]
    operations = [
        migrations.AddField(model_name="A", name="num", field=models.IntegerField(default=0), preserve_default=False),
    ]

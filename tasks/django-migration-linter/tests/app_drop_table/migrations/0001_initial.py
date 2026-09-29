from django.db import migrations, models
class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name="A", fields=[("id", models.AutoField(primary_key=True))]),
        migrations.CreateModel(name="B", fields=[("id", models.AutoField(primary_key=True))]),
    ]

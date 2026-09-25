from django.db import migrations
def forwards(apps, schema_editor):
    A = apps.get_model("app_data_migration", "A")
    A.objects.all().update(name="x")
class Migration(migrations.Migration):
    dependencies = [("app_data_migration", "0001_initial")]
    operations = [migrations.RunPython(forwards)]

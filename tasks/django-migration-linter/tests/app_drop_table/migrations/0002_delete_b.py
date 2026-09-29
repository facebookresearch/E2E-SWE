from django.db import migrations
class Migration(migrations.Migration):
    dependencies = [("app_drop_table", "0001_initial")]
    operations = [migrations.DeleteModel(name="B")]

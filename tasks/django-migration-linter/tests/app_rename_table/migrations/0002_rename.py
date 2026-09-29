from django.db import migrations
class Migration(migrations.Migration):
    dependencies = [("app_rename_table", "0001_initial")]
    operations = [migrations.RenameModel(old_name="A", new_name="C")]

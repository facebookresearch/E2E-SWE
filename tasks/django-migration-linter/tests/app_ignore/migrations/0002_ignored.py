from django.db import migrations
import django_migration_linter as linter
class Migration(migrations.Migration):
    dependencies = [("app_ignore", "0001_initial")]
    operations = [linter.IgnoreMigration(), migrations.DeleteModel(name="B")]

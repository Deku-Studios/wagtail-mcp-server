"""Add the ``TestAuthor`` snippet model used by snippets.* tests.

Hand-written to match 0001_initial's convention. ``TestAuthor`` is
registered as a Wagtail snippet in ``tests/testapp/models.py``; the
table only needs one CharField besides the implicit pk.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wagtail_mcp_server_testapp", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TestAuthor",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100)),
            ],
            options={
                "verbose_name": "Test Author",
            },
        ),
    ]

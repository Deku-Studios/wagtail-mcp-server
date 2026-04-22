"""Initial migration for the testapp models.

Hand-written rather than generated so the test suite is deterministic
across Wagtail versions. The two page tables both inherit from
``wagtailcore.Page`` via the standard one-to-one parent_link pattern.
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models

import wagtail.fields

import tests.testapp.models as testapp_models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        # 0001_initial is the only migration guaranteed across every Wagtail
        # release that has ever existed; the rest of wagtailcore's migrations
        # still run first because they all chain off this one.
        ("wagtailcore", "0001_initial"),
        ("wagtailimages", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TestStreamPage",
            fields=[
                (
                    "page_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="wagtailcore.page",
                    ),
                ),
                (
                    "body",
                    wagtail.fields.StreamField(
                        testapp_models.BODY_BLOCKS,
                        blank=True,
                        use_json_field=True,
                    ),
                ),
            ],
            options={
                "verbose_name": "Test Stream Page",
            },
            bases=("wagtailcore.page",),
        ),
        migrations.CreateModel(
            name="TestRenditionPage",
            fields=[
                (
                    "page_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="wagtailcore.page",
                    ),
                ),
                (
                    "cover",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="wagtailimages.image",
                    ),
                ),
            ],
            options={
                "verbose_name": "Test Rendition Page",
            },
            bases=("wagtailcore.page",),
        ),
    ]

"""
Model <-> schema consistency.

Every model is unmanaged, so nothing stops a model drifting from the real
table. These checks run against the test database built from the live-schema
snapshot plus sql/0*.sql (see abiastream/test_runner.py), and catch the bug
classes that have already bitten this project:

  * a field written on INSERT for a GENERATED column (Video.search_vector)
  * a nullable field with no default mapped to a NOT NULL column, so Django
    sends an explicit NULL that overrides the column default
    (Experiment.created_at)
  * a field whose column does not exist at all
"""
from django.apps import apps
from django.db import connection
from django.db.models import NOT_PROVIDED
from django.test import TestCase

PROJECT_APPS = {
    'accounts', 'profiles', 'videos', 'playback', 'creator_channels',
    'interactions', 'subscriptions', 'notifications', 'verification',
    'comments', 'events', 'recommendations', 'experiments', 'analytics',
    'moderation', 'livestreams',
}


# Known, deliberately-tolerated mismatches.
#   video_tags has a composite key and no id column. VideoTag is never
#   created through the ORM (videos.views.attach_tags uses raw SQL) and the
#   M2M join through it never selects id.
KNOWN_MISSING_COLUMNS = {('VideoTag', 'id')}


def table_columns(table):
    with connection.cursor() as cur:
        cur.execute(
            """
            select column_name, is_nullable = 'YES', column_default is not null,
                   is_generated = 'ALWAYS'
            from information_schema.columns
            where table_schema = 'public' and table_name = %s
            """,
            [table],
        )
        return {name: (nullable, has_default, generated)
                for name, nullable, has_default, generated in cur.fetchall()}


def project_models():
    for model in apps.get_models():
        if model._meta.app_label in PROJECT_APPS and not model._meta.proxy:
            yield model


class ModelSchemaTests(TestCase):

    def test_every_field_has_a_column(self):
        problems = []
        for model in project_models():
            columns = table_columns(model._meta.db_table)
            if not columns:
                problems.append(f'{model.__name__}: table {model._meta.db_table} missing')
                continue
            for field in model._meta.concrete_fields:
                if field.column not in columns and \
                        (model.__name__, field.name) not in KNOWN_MISSING_COLUMNS:
                    problems.append(f'{model.__name__}.{field.name}: no column {field.column}')
        self.assertEqual(problems, [])

    def test_inserts_cannot_violate_column_constraints(self):
        problems = []
        for model in project_models():
            columns = table_columns(model._meta.db_table)
            for field in model._meta.concrete_fields:
                if field.column not in columns:
                    continue
                nullable, has_default, generated = columns[field.column]
                is_django_generated = field.generated

                if generated and not is_django_generated:
                    problems.append(
                        f'{model.__name__}.{field.name}: column is GENERATED; '
                        'use models.GeneratedField')
                    continue

                if (not nullable and field.null and not field.primary_key
                        and field.default is NOT_PROVIDED
                        and not getattr(field, 'auto_now', False)
                        and not getattr(field, 'auto_now_add', False)):
                    problems.append(
                        f'{model.__name__}.{field.name}: NOT NULL column but the '
                        'field is null=True with no default, so a create() without '
                        'it sends NULL')
        self.assertEqual(problems, [])

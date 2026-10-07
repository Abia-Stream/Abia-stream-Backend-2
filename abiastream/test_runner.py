"""
Test runner for a project whose tables are all unmanaged.

Django's default runner creates the test database through migrations, which
create nothing here. This runner instead builds `test_<NAME>` from:

    sql/baseline/supabase_stubs.sql   auth.uid() etc. used by RLS policies
    sql/baseline/000_live_schema.sql  snapshot of the live schema
    sql/0*.sql                        every forward script, in order

Running the forward scripts on top of the live snapshot doubles as a check
that each one applies cleanly (and idempotently) to production.

Refuses to run against anything but a local host.
"""
from pathlib import Path

import psycopg2
from psycopg2 import sql as pgsql
from django.conf import settings
from django.db import connections
from django.test.runner import DiscoverRunner

LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}
SQL_DIR = Path(settings.BASE_DIR) / 'sql'


def schema_files():
    baseline = SQL_DIR / 'baseline'
    return [
        baseline / 'supabase_stubs.sql',
        baseline / '000_live_schema.sql',
        *sorted(SQL_DIR.glob('0*.sql')),
    ]


class NetworkDisabled(RuntimeError):
    pass


def _block_cloudinary_network():
    """
    Belt and braces on top of the fake credentials in test_settings: any
    request the Cloudinary SDK makes raises instead of reaching the network.
    Tests that exercise Cloudinary calls must mock them explicitly.
    """
    import urllib3

    original = urllib3.PoolManager.urlopen

    def guarded(self, method, url, *args, **kwargs):
        if 'cloudinary.com' in url:
            raise NetworkDisabled(f'Cloudinary network call in tests: {method} {url}')
        return original(self, method, url, *args, **kwargs)

    urllib3.PoolManager.urlopen = guarded


class SchemaTestRunner(DiscoverRunner):

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        _block_cloudinary_network()

    def setup_databases(self, **kwargs):
        conn = connections['default']
        params = conn.settings_dict

        if params['HOST'] not in LOCAL_HOSTS:
            raise RuntimeError(
                f'Refusing to build a test database on {params["HOST"]!r}. '
                'Tests only run against a local Postgres (TEST_DB_HOST).'
            )

        old_name = params['NAME']
        test_name = f'test_{old_name}'

        admin = psycopg2.connect(
            dbname='postgres', user=params['USER'], password=params['PASSWORD'],
            host=params['HOST'], port=params['PORT'],
        )
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(pgsql.SQL('drop database if exists {}').format(
                pgsql.Identifier(test_name)))
            cur.execute(pgsql.SQL('create database {}').format(
                pgsql.Identifier(test_name)))
        admin.close()

        db = psycopg2.connect(
            dbname=test_name, user=params['USER'], password=params['PASSWORD'],
            host=params['HOST'], port=params['PORT'],
        )
        db.autocommit = True
        with db.cursor() as cur:
            for path in schema_files():
                if self.verbosity >= 2:
                    print(f'Applying {path.relative_to(settings.BASE_DIR)}')
                try:
                    # pg_dump output clears search_path; the Supabase SQL
                    # editor that runs these scripts in production uses public.
                    cur.execute('set search_path = public')
                    cur.execute(path.read_text(encoding='utf-8'))
                except psycopg2.Error as exc:
                    raise RuntimeError(f'{path.name} failed to apply: {exc}') from exc
        db.close()

        conn.close()
        params['NAME'] = test_name
        return [(conn, old_name, True)]

    def teardown_databases(self, old_config, **kwargs):
        for conn, old_name, destroy in old_config:
            test_name = conn.settings_dict['NAME']
            conn.close()
            conn.settings_dict['NAME'] = old_name
            if destroy and not self.keepdb:
                params = conn.settings_dict
                admin = psycopg2.connect(
                    dbname='postgres', user=params['USER'],
                    password=params['PASSWORD'],
                    host=params['HOST'], port=params['PORT'],
                )
                admin.autocommit = True
                with admin.cursor() as cur:
                    cur.execute(pgsql.SQL('drop database if exists {}').format(
                        pgsql.Identifier(test_name)))
                admin.close()

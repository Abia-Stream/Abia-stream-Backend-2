BLOCKED_APPS = {'admin', 'contenttypes', 'auth', 'sessions'}

class SupabaseRouter:
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in BLOCKED_APPS:
            return False
        return None  # ← None, not True
    

class BlockDjangoInternalTablesRouter:
    """
    Prevents Django's internal apps from creating tables in Supabase.
    We manage auth ourselves via the custom User model with managed=False.
    """
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in BLOCKED_APPS:
            return False
        return None  # let other routers/default decide
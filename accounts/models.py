import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    def get_by_natural_key(self, email):        
        return self.get(email=email)

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)  # hashes into password_hash
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('status', 'active')
        extra_fields.setdefault('is_email_verified', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser):
    class Role(models.TextChoices):
        VIEWER = 'viewer', 'Viewer'
        CREATOR = 'creator', 'Creator'
        ADMIN = 'admin', 'Admin'
        MODERATOR = 'moderator', 'Moderator'
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        SUSPENDED = 'suspended', 'Suspended'
        BANNED = 'banned', 'Banned'
        PENDING_VERIFICATION = 'pending_verification', 'Pending Verification'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255, db_column='password_hash')  # map to password_hash
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VIEWER)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING_VERIFICATION)
    is_email_verified = models.BooleanField(default=False, null=True)
    email_verification_token = models.CharField(max_length=255, null=True, blank=True)
    password_reset_token = models.CharField(max_length=255, null=True, blank=True)
    password_reset_expires = models.DateTimeField(null=True, blank=True)
    last_login = models.DateTimeField(null=True, blank=True)
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    failed_login_attempts = models.IntegerField(default=0, null=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    # Required by AbstractBaseUser
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    
    
    objects = UserManager()

    # Required by PermissionsMixin — but we have no is_staff column,
    # so make it a property
    @property
    def is_staff(self):
        return self.role == self.Role.ADMIN

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    def has_perm(self, perm, obj=None):
        return self.role == self.Role.ADMIN

    def has_module_perms(self, app_label):
        return self.role == self.Role.ADMIN

    class Meta:
        managed = False
        db_table = 'users'

    def __str__(self):
        return self.email
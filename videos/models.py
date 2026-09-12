import uuid
from django.db import models
from django.conf import settings
from django.contrib.postgres.search import SearchVectorField


class Category(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True)
    slug = models.CharField(max_length=255, unique=True)
    description = models.TextField(null=True, blank=True)
    thumbnail_url = models.CharField(max_length=500, null=True, blank=True)
    display_order = models.IntegerField(null=True, blank=True)
    is_active = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        managed = False
        db_table = 'categories'

    def __str__(self):
        return self.name


class Tag(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True)
    slug = models.CharField(max_length=255, unique=True)
    usage_count = models.IntegerField(null=True, blank=True, default=0)
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        managed = False
        db_table = 'tags'

    def __str__(self):
        return self.name


class Video(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PROCESSING = 'processing', 'Processing'
        READY = 'ready', 'Ready'
        FAILED = 'failed', 'Failed'
        PUBLISHED = 'published', 'Published'
        ARCHIVED = 'archived', 'Archived'
        BLOCKED = 'blocked', 'Blocked'

    class Visibility(models.TextChoices):
        PUBLIC = 'public', 'Public'
        UNLISTED = 'unlisted', 'Unlisted'
        PRIVATE = 'private', 'Private'
        SUBSCRIBERS_ONLY = 'subscribers_only', 'Subscribers Only'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_column='creator_id',
        related_name='videos'
    )
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)

    # Cloudinary fields
    cloudinary_public_id = models.CharField(max_length=500, unique=True)
    cloudinary_url = models.CharField(max_length=1000)
    cloudinary_thumbnail_url = models.CharField(max_length=1000, null=True, blank=True)
    cloudinary_resource_type = models.CharField(max_length=50, null=True, blank=True)
    cloudinary_version = models.CharField(max_length=50, null=True, blank=True)

    # Video metadata
    duration_seconds = models.IntegerField(null=True, blank=True)
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    format = models.CharField(max_length=20, null=True, blank=True)
    file_size = models.BigIntegerField(null=True, blank=True)
    bitrate = models.IntegerField(null=True, blank=True)

    # Relations
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        db_column='category_id'
    )
    tags = models.ManyToManyField(Tag, through='VideoTag', blank=True)

    # Stats
    views_count = models.BigIntegerField(null=True, blank=True, default=0)
    likes_count = models.IntegerField(null=True, blank=True, default=0)
    saves_count = models.IntegerField(null=True, blank=True, default=0)
    shares_count = models.IntegerField(null=True, blank=True, default=0)

    # Settings
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        null=True
    )
    visibility = models.CharField(
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
        null=True
    )
    is_monetized = models.BooleanField(null=True, blank=True, default=False)
    revenue_share_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )

    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    # Generated column maintained by Postgres (see sql/002_video_search.sql).
    # Never written from Django.
    search_vector = SearchVectorField(null=True, editable=False)

    class Meta:
        managed = False
        db_table = 'videos'
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class VideoTag(models.Model):
    video = models.ForeignKey(
        Video, on_delete=models.CASCADE, db_column='video_id'
    )
    tag = models.ForeignKey(
        Tag, on_delete=models.CASCADE, db_column='tag_id'
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        managed = False
        db_table = 'video_tags'
        unique_together = ('video', 'tag')

    def save(self, *args, **kwargs):
        # Use get_or_create pattern instead
        VideoTag.objects.get_or_create(
            video=self.video,
            tag=self.tag,
            defaults={'created_at': self.created_at}
        )
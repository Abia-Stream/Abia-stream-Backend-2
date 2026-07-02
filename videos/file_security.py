import os
import uuid
import magic
import hashlib
from django.conf import settings
from rest_framework.exceptions import ValidationError


# ── Allowlists ────────────────────────────────────────────────────────────────

ALLOWED_VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}

ALLOWED_VIDEO_MIME_TYPES = {
    'video/mp4',
    'video/quicktime',
    'video/x-msvideo',
    'video/x-matroska',
    'video/webm',
}

ALLOWED_IMAGE_MIME_TYPES = {
    'image/jpeg',
    'image/png',
    'image/webp',
}

# Magic bytes (file signatures) for allowed types
VIDEO_MAGIC_BYTES = {
    b'\x00\x00\x00\x18ftypmp42',  # MP4
    b'\x00\x00\x00\x1cftyp',      # MP4 variant
    b'\x1aE\xdf\xa3',             # MKV/WebM
    b'RIFF',                       # AVI
    b'\x00\x00\x00\x14ftyp',      # MOV
}

IMAGE_MAGIC_BYTES = {
    b'\xff\xd8\xff',              # JPEG
    b'\x89PNG\r\n\x1a\n',        # PNG
    b'RIFF',                       # WebP (starts with RIFF....WEBP)
}

# Size limits
MAX_VIDEO_SIZE = 500 * 1024 * 1024   # 500MB
MAX_IMAGE_SIZE = 10 * 1024 * 1024    # 10MB


# ── Step 1: Check file size ───────────────────────────────────────────────────

def check_file_size(file, file_type='video'):
    max_size = MAX_VIDEO_SIZE if file_type == 'video' else MAX_IMAGE_SIZE
    if file.size > max_size:
        max_mb = max_size // (1024 * 1024)
        raise ValidationError(
            f'File too large. Maximum size is {max_mb}MB.'
        )


# ── Step 2: Check extension allowlist ────────────────────────────────────────

def check_extension(filename, file_type='video'):
    ext = os.path.splitext(filename.lower())[1]
    allowed = ALLOWED_VIDEO_EXTENSIONS if file_type == 'video' else ALLOWED_IMAGE_EXTENSIONS

    if ext not in allowed:
        raise ValidationError(
            f'File extension not allowed. Allowed: {", ".join(allowed)}'
        )
    return ext


# ── Step 3: Check MIME type ───────────────────────────────────────────────────

def check_mime_type(file, file_type='video'):
    """Check MIME type from Content-Type header."""
    content_type = getattr(file, 'content_type', '').lower()
    allowed = ALLOWED_VIDEO_MIME_TYPES if file_type == 'video' else ALLOWED_IMAGE_MIME_TYPES

    if content_type not in allowed:
        raise ValidationError(
            f'Invalid file type: {content_type}. '
            f'Allowed types: {", ".join(allowed)}'
        )


# ── Step 4: Check magic bytes (file signature) ────────────────────────────────

def check_magic_bytes(file, file_type='video'):
    """
    Read the first bytes of the file to verify it is what it claims to be.
    This prevents attackers from renaming a .php file to .mp4.
    """
    file.seek(0)
    header = file.read(32)
    file.seek(0)  # reset for later reading

    allowed_signatures = VIDEO_MAGIC_BYTES if file_type == 'video' else IMAGE_MAGIC_BYTES

    for signature in allowed_signatures:
        if header.startswith(signature):
            return True


    raise ValidationError(
        'File signature does not match expected format. '
        'File may be corrupted or malicious.'
    )


# ── Step 5: Basic malware scan ────────────────────────────────────────────────

MALICIOUS_PATTERNS = [
    b'<?php',           # PHP code
    b'<script',         # JavaScript
    b'eval(',           # eval injection
    b'exec(',           # exec injection
    b'system(',         # system calls
    b'base64_decode',   # common obfuscation
    b'#!/',             # shell scripts
    b'powershell',      # PowerShell
    b'cmd.exe',         # Windows command
    b'<iframe',         # iframe injection
]

def scan_for_malware(file, file_type='video'):
    """
    Basic pattern scanning for embedded malicious code.
    For production, integrate ClamAV or a cloud scanning service.
    """
    file.seek(0)

    # For video files, only scan the first and last 64KB
    # (malicious code is usually injected at start or end)
    if file_type == 'video':
        header = file.read(65536)  # first 64KB
        file.seek(max(0, file.size - 65536))
        footer = file.read(65536)  # last 64KB
        content_to_scan = header + footer
    else:
        content_to_scan = file.read()

    file.seek(0)  # reset

    content_lower = content_to_scan.lower()
    for pattern in MALICIOUS_PATTERNS:
        if pattern.lower() in content_lower:
            raise ValidationError(
                'File contains potentially malicious content and was rejected.'
            )


# ── Step 6: Generate safe filename ───────────────────────────────────────────

def generate_safe_filename(original_filename, file_type='video'):
    """
    Generate a random UUID-based filename.
    Never use the original filename — it could contain path traversal attacks.
    e.g. ../../etc/passwd.mp4
    """
    ext = os.path.splitext(original_filename.lower())[1]
    safe_name = f'{uuid.uuid4().hex}{ext}'
    return safe_name


# ── Step 7: Compute file hash ─────────────────────────────────────────────────

def compute_file_hash(file):
    """
    Compute SHA-256 hash of the file.
    Useful for detecting duplicate uploads and integrity verification.
    """
    file.seek(0)
    sha256 = hashlib.sha256()
    for chunk in iter(lambda: file.read(8192), b''):
        sha256.update(chunk)
    file.seek(0)
    return sha256.hexdigest()


# ── Main validation pipeline ──────────────────────────────────────────────────

def validate_video_file(file):
    """
    Run all security checks on a video file.
    Call this before any upload to Cloudinary.
    """
    # 1. Check file size
    check_file_size(file, 'video')

    # 2. Check extension
    ext = check_extension(file.name, 'video')

    # 3. Check MIME type
    check_mime_type(file, 'video')

    # 4. Check magic bytes
    check_magic_bytes(file, 'video')

    # 5. Scan for malware patterns
    scan_for_malware(file, 'video')

    # 6. Generate safe filename
    safe_name = generate_safe_filename(file.name, 'video')

    # 7. Compute hash (for deduplication)
    file_hash = compute_file_hash(file)

    return {
        'safe_name': safe_name,
        'extension': ext,
        'file_hash': file_hash,
        'original_name': file.name,
        'size': file.size,
    }


def validate_image_file(file):
    """
    Run all security checks on an image file (thumbnails, banners etc).
    """
    check_file_size(file, 'image')
    ext = check_extension(file.name, 'image')
    check_mime_type(file, 'image')
    check_magic_bytes(file, 'image')
    scan_for_malware(file, 'image')
    safe_name = generate_safe_filename(file.name, 'image')
    file_hash = compute_file_hash(file)

    return {
        'safe_name': safe_name,
        'extension': ext,
        'file_hash': file_hash,
        'original_name': file.name,
        'size': file.size,
    }
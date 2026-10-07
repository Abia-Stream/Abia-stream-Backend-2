"""
Perceptual video fingerprints for re-upload / copy detection.

Six frames are sampled across the video (at fixed percentages, so a
re-encode or resize lands on the same frames) and reduced by Cloudinary to
9x8 grayscale. Each becomes a 64-bit difference hash (dHash): a bit per
adjacent-pixel comparison, robust to compression, scaling and small colour
changes. Two frames "match" when their hashes differ in <= MATCH_BITS bits.

Frames that are almost flat (black screens, solid title cards) carry no
identity and would match unrelated videos; they are dropped.

Verified on 2026-10-07 against real uploads on the Free Cloudinary plan.
"""
import io
import logging
from concurrent.futures import ThreadPoolExecutor

import cloudinary.utils
import requests
from PIL import Image

logger = logging.getLogger(__name__)

SAMPLE_PERCENTS = (10, 25, 40, 55, 70, 85)
FETCH_TIMEOUT_SECONDS = 20
MATCH_BITS = 10              # max differing bits for two frames to match
MIN_INFORMATIVE_FRAMES = 3   # fewer than this and we can't say anything
FLAT_FRAME_BITS = 6          # a hash with <= 6 or >= 58 bits set is near-flat
SAME_VIDEO_SIMILARITY = 0.8  # share of frames that must match
DURATION_TOLERANCE = 0.1     # durations within 10% for "same video"


class FingerprintUnavailable(Exception):
    pass


def frame_url(video, percent):
    options = {
        'resource_type': 'video',
        'format': 'png',
        'transformation': [
            {'start_offset': f'{percent}p'},
            {'width': 9, 'height': 8, 'crop': 'scale'},
            {'effect': 'grayscale'},
        ],
    }
    if video.cloudinary_delivery_type == 'authenticated':
        options.update(type='authenticated', sign_url=True)
    url, _ = cloudinary.utils.cloudinary_url(video.cloudinary_public_id, **options)
    return url


def dhash(image):
    pixels = image.convert('L').resize((9, 8)).tobytes()
    bits = 0
    for row in range(8):
        for col in range(8):
            left = pixels[row * 9 + col]
            right = pixels[row * 9 + col + 1]
            bits = (bits << 1) | (left < right)
    return bits


def to_signed(value):
    """Postgres bigint is signed; store the unsigned 64-bit hash as its two's complement."""
    return value - (1 << 64) if value >= (1 << 63) else value


def to_unsigned(value):
    return value + (1 << 64) if value < 0 else value


def is_informative(hash_value):
    ones = bin(to_unsigned(hash_value)).count('1')
    return FLAT_FRAME_BITS < ones < 64 - FLAT_FRAME_BITS


def _fetch_hash(url):
    response = requests.get(url, timeout=FETCH_TIMEOUT_SECONDS)
    response.raise_for_status()
    return dhash(Image.open(io.BytesIO(response.content)))


def compute(video):
    """Frame hashes for `video` (signed ints). Raises FingerprintUnavailable."""
    urls = [frame_url(video, p) for p in SAMPLE_PERCENTS]
    try:
        with ThreadPoolExecutor(max_workers=len(urls)) as pool:
            hashes = list(pool.map(_fetch_hash, urls))
    except Exception as exc:  # noqa: BLE001 - network, decode, HTTP errors
        raise FingerprintUnavailable(str(exc)) from exc
    return [to_signed(h) for h in hashes]


def hamming(a, b):
    return bin(to_unsigned(a) ^ to_unsigned(b)).count('1')


def similarity(hashes_a, hashes_b):
    """
    Share of A's informative frames that have a matching frame anywhere in B
    (order-free, so a trimmed copy still matches). None when either side has
    too few informative frames to judge.
    """
    a = [h for h in hashes_a if is_informative(h)]
    b = [h for h in hashes_b if is_informative(h)]
    if len(a) < MIN_INFORMATIVE_FRAMES or len(b) < MIN_INFORMATIVE_FRAMES:
        return None
    matched = sum(1 for x in a if min(hamming(x, y) for y in b) <= MATCH_BITS)
    return matched / len(a)


def durations_close(a, b):
    if not a or not b:
        return True  # unknown duration shouldn't veto a strong visual match
    return abs(a - b) <= DURATION_TOLERANCE * max(a, b)


def is_same_video(fp_a, fp_b):
    """fp = (hashes, duration_seconds)."""
    score = similarity(fp_a[0], fp_b[0])
    return score is not None and score >= SAME_VIDEO_SIMILARITY \
        and durations_close(fp_a[1], fp_b[1]), score

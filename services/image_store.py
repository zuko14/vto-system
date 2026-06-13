"""
ZukoLabs VTO — Image Store Service

Manages image storage in Supabase Storage with TTL-based auto-deletion.
  - Selfies: 24-hour TTL (deleted after processing)
  - Outputs: 48-hour TTL
  - Generates signed URLs for WhatsApp delivery
"""

import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.config import get_settings
from core.database import get_db

logger = logging.getLogger(__name__)

# Storage bucket names
SELFIE_BUCKET = "selfies"
OUTPUT_BUCKET = "tryon-outputs"

# TTL durations (in seconds)
SELFIE_TTL = 24 * 60 * 60       # 24 hours
OUTPUT_TTL = 48 * 60 * 60       # 48 hours
SIGNED_URL_EXPIRY = 60 * 60     # 1 hour for signed URLs


async def upload_selfie(
    tenant_id: str,
    customer_id: str,
    image_bytes: bytes,
) -> str:
    """
    Upload a selfie image to temporary storage.
    Auto-expires after 24 hours (DPDP compliance).

    Args:
        tenant_id: Tenant UUID for path scoping.
        customer_id: Customer UUID.
        image_bytes: Raw image bytes.

    Returns:
        Storage path (used for later retrieval/deletion).
    """
    filename = f"{tenant_id}/{customer_id}/selfie_{uuid.uuid4().hex[:8]}.jpg"

    try:
        db = get_db()
        db.storage.from_(SELFIE_BUCKET).upload(
            path=filename,
            file=image_bytes,
            file_options={
                "content-type": "image/jpeg",
                "x-upsert": "true",
            },
        )

        logger.debug("Selfie uploaded: %s", filename)
        return filename

    except Exception as e:
        logger.error("Failed to upload selfie: %s", str(e))
        raise


async def upload_output(
    tenant_id: str,
    job_id: str,
    image_bytes: bytes,
) -> str:
    """
    Upload a try-on output image.
    Auto-expires after 48 hours.

    Args:
        tenant_id: Tenant UUID.
        job_id: Try-on job UUID.
        image_bytes: Generated try-on image bytes.

    Returns:
        Storage path.
    """
    filename = f"{tenant_id}/outputs/{job_id}.jpg"

    try:
        db = get_db()
        db.storage.from_(OUTPUT_BUCKET).upload(
            path=filename,
            file=image_bytes,
            file_options={
                "content-type": "image/jpeg",
                "x-upsert": "true",
            },
        )

        logger.debug("Output uploaded: %s", filename)
        return filename

    except Exception as e:
        logger.error("Failed to upload output: %s", str(e))
        raise


async def get_signed_url(
    bucket: str,
    path: str,
    expires_in: int = SIGNED_URL_EXPIRY,
) -> Optional[str]:
    """
    Generate a signed (temporary) URL for an image.
    Used to send images via WhatsApp.

    Args:
        bucket: Storage bucket name.
        path: File path within the bucket.
        expires_in: URL expiry time in seconds.

    Returns:
        Signed URL string, or None on failure.
    """
    try:
        db = get_db()
        result = db.storage.from_(bucket).create_signed_url(
            path=path,
            expires_in=expires_in,
        )

        if result and "signedURL" in result:
            return result["signedURL"]

        logger.warning("No signed URL returned for %s/%s", bucket, path)
        return None

    except Exception as e:
        logger.error("Failed to generate signed URL: %s", str(e))
        return None


async def delete_file(bucket: str, path: str) -> bool:
    """
    Delete a file from storage.

    Args:
        bucket: Storage bucket name.
        path: File path.

    Returns:
        True if deleted successfully.
    """
    try:
        db = get_db()
        db.storage.from_(bucket).remove([path])
        logger.debug("Deleted file: %s/%s", bucket, path)
        return True

    except Exception as e:
        logger.error("Failed to delete file %s/%s: %s", bucket, path, str(e))
        return False


async def delete_customer_images(
    tenant_id: str,
    customer_id: str,
) -> int:
    """
    Delete all images for a customer (DPDP deletion request).

    Args:
        tenant_id: Tenant UUID.
        customer_id: Customer UUID.

    Returns:
        Number of files deleted.
    """
    deleted_count = 0
    db = get_db()

    try:
        # Delete selfies
        selfie_prefix = f"{tenant_id}/{customer_id}/"
        try:
            selfie_files = db.storage.from_(SELFIE_BUCKET).list(
                path=selfie_prefix,
            )
            if selfie_files:
                paths = [f"{selfie_prefix}{f['name']}" for f in selfie_files]
                db.storage.from_(SELFIE_BUCKET).remove(paths)
                deleted_count += len(paths)
        except Exception:
            pass  # Directory may not exist

        # Delete outputs (by tenant/job pattern)
        output_prefix = f"{tenant_id}/outputs/"
        try:
            output_files = db.storage.from_(OUTPUT_BUCKET).list(
                path=output_prefix,
            )
            if output_files:
                paths = [f"{output_prefix}{f['name']}" for f in output_files]
                db.storage.from_(OUTPUT_BUCKET).remove(paths)
                deleted_count += len(paths)
        except Exception:
            pass

        logger.info(
            "Deleted %d images for customer %s (tenant: %s)",
            deleted_count,
            customer_id,
            tenant_id,
        )

    except Exception as e:
        logger.error(
            "Failed to delete customer images: %s", str(e)
        )

    return deleted_count

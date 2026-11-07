from config.env import env

MINIO_ENDPOINT = env("MINIO_ENDPOINT", default="localhost:9000")
MINIO_ACCESS_KEY = env("MINIO_ACCESS_KEY", default="minioadmin")
MINIO_SECRET_KEY = env("MINIO_SECRET_KEY", default="minioadmin")
MINIO_SECURE = env.bool("MINIO_SECURE", default=False)

# Host/port used when building URLs handed to browsers/apps (presigned video URLs, public cover URLs).
# Defaults to MINIO_ENDPOINT for local dev where everything is on localhost; in docker deployments MINIO_ENDPOINT
# is the internal service name (e.g. "minio:9000") which isn't reachable from outside, so this must be set to
# the server's public host/port instead (e.g. "your-domain.example:9000" or "1.2.3.4:9000").
MINIO_PUBLIC_ENDPOINT = env("MINIO_PUBLIC_ENDPOINT", default=MINIO_ENDPOINT)
MINIO_PUBLIC_SECURE = env.bool("MINIO_PUBLIC_SECURE", default=MINIO_SECURE)
MINIO_VIDEO_BUCKET = env("MINIO_VIDEO_BUCKET", default="encrypted-videos")
MINIO_COURSE_COVER_BUCKET = env("MINIO_COURSE_COVER_BUCKET", default="course-covers")
# Private bucket: course PDFs are only reachable through presigned URLs issued to enrolled users.
MINIO_COURSE_PDF_BUCKET = env("MINIO_COURSE_PDF_BUCKET", default="course-pdfs")
# Long enough that a large video (100-200+ MB) downloading over a slow/mobile connection — especially under
# concurrent load, where per-user throughput drops as more people download at once — doesn't have its presigned
# URL expire mid-download (this was previously 10 minutes and too tight for that scenario; any resumable/range
# request issued after expiry gets rejected by MinIO, which looks like "download failing" partway through).
MINIO_PRESIGNED_URL_TTL_SECONDS = env.int("MINIO_PRESIGNED_URL_TTL_SECONDS", default=60 * 60)


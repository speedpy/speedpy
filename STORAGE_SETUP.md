# Object Storage Setup

SpeedPy stores uploaded media on **local disk by default**. That is deliberate: a
disk (or a platform volume) needs no credentials, no bucket, and no CDN, and it is
the right choice until you actually outgrow it.

When you do outgrow it, flip one flag. Nothing in the codebase is tied to a
specific provider — the provider is chosen entirely by `S3_ENDPOINT_URL`.

## When to move off local disk

Move to object storage when any of these is true:

- You run **more than one web container**, so uploads on one are invisible to the other.
- Your platform's filesystem is **ephemeral** (uploads vanish on redeploy).
- You want a **CDN** in front of user media.
- You need **signed, expiring URLs** for private files.

## Default: local disk

Nothing to configure. Media lands in `MEDIA_ROOT` and is served at `MEDIA_URL`.

On Appliku, attach a volume and set its *environment variable* prefix to `MEDIA`.
The platform then sets **`MEDIA_ROOT`** (container path) and **`MEDIA_URL`** (web
path) for you — those exact names, which is what `project/settings.py` reads.

```yaml
# appliku.yml
volumes:
  media:
    target: "/media/"
    url: "/media/"
    environment_variable: "MEDIA"
```

## Switching to S3-compatible storage

Install the optional dependency — boto3 is large, so it is not in the default
install:

```bash
uv sync --extra s3
```

Then set:

```bash
USE_S3=True
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_BUCKET_NAME=my-bucket
S3_REGION_NAME=...
S3_ENDPOINT_URL=...        # empty for AWS S3
S3_CDN_BASE=...            # optional CDN/custom domain for public files
S3_DEFAULT_ACL=            # see the ACL section below — empty works everywhere
```

`USE_S3=True` without key, secret and bucket **refuses to boot** rather than
failing on the first upload.

Verify against the real bucket:

```bash
python manage.py check_storage
```

It uploads a public probe and fetches it by plain URL, uploads a private probe and
asserts it is **refused** without a signature, then fetches it with one, and cleans
up. The middle check is the one that matters: a bucket left public passes the other
two while quietly serving private files to the world.

## Per-provider settings

| Provider | `S3_ENDPOINT_URL` | `S3_DEFAULT_ACL` | Notes |
|---|---|---|---|
| AWS S3 | *(empty)* | *(empty)* | Buckets created since April 2023 have ACLs **disabled**; grant public read with a bucket policy. |
| DigitalOcean Spaces | `https://<region>.digitaloceanspaces.com` | `public-read` | Supports per-object ACLs. Enable the CDN and set `S3_CDN_BASE`. |
| Cloudflare R2 | `https://<account>.r2.cloudflarestorage.com` | *(empty)* | No ACL support at all. Use a public bucket or a custom domain, and set `S3_CDN_BASE`. |
| Wasabi | `https://s3.<region>.wasabisys.com` | `public-read` | |
| Backblaze B2 | `https://s3.<region>.backblazeb2.com` | *(empty)* | |
| MinIO / self-hosted | `https://minio.example.com` | *(empty)* | Also set `S3_ADDRESSING_STYLE=path`. |

### ACLs are the one genuinely non-portable part

`S3_DEFAULT_ACL` is **empty by default**, which works on every provider.

Sending `public-read` where ACLs are disabled does not degrade quietly — the
provider **rejects the upload**. So only set it where per-object ACLs exist
(DigitalOcean Spaces, Wasabi, older AWS buckets). Everywhere else, make the bucket
or prefix readable with a bucket policy and leave this empty.

## The two backends

`speedpycom/storages.py` defines two, sharing one bucket with disjoint prefixes:

| Backend | Prefix | Access |
|---|---|---|
| `PublicMediaStorage` | `media/` | Plain URLs, through `S3_CDN_BASE` when set. Wired as `STORAGES["default"]`. |
| `PrivateMediaStorage` | `private/` | Signed URLs only, expiring after `S3_SIGNED_URL_EXPIRE` seconds (default 600). |

Credentials are passed to boto3 **explicitly** rather than left to its environment
lookup, so the `AWS_SES_*` variables this project uses for email can never
silently redirect uploads.

## Private files in both modes

Use the `private_storage` callable so a field does not care which mode you are in:

```python
from project.media import private_storage

class Invoice(models.Model):
    pdf = models.FileField(storage=private_storage, upload_to="invoices/")
```

Pass the function, not a call. Django records the reference in migrations, so
flipping `USE_S3` later needs no migration.

- **`USE_S3=True`** — signed, expiring URLs from `field.url`.
- **Local disk** — files land in `PRIVATE_MEDIA_ROOT`, which defaults **outside**
  `MEDIA_ROOT` because everything under `MEDIA_ROOT` is served by the web server.
  `field.url` raises `ValueError` on purpose: serve the file through a view that
  checks permissions and returns `FileResponse(field.open())`.

## Static files do not move

Static stays on WhiteNoise in both modes. Deploys stay atomic, there is no
`collectstatic` round-trip to object storage, and no CDN invalidation step on every
release. Only *uploaded media* moves.

## Migrating existing files

Switching `USE_S3` changes where **new** uploads go; it does not move old ones.
Copy them first, then flip the flag:

```bash
# example: rclone, with a remote configured for your provider
rclone copy /path/to/media remote:my-bucket/media
```

Existing `FileField` values are stored as paths relative to the backend, so they
keep resolving once the objects exist under the same `media/` prefix.

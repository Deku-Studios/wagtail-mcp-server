# `media` — images and documents

Off by default. Manages Wagtail Images and Documents through a
presigned-URL upload flow so bytes never pass through Django.

```python
WAGTAIL_MCP_SERVER = {
    "TOOLSETS": {
        "media": {"enabled": True},
    },
    "LIMITS": {
        "MAX_UPLOAD_MB": 25,  # cap on image and document uploads
    },
}
```

## Storage requirement

`media` requires an S3-compatible `default_storage`. In practice
that means `django-storages`' `S3Storage` pointed at AWS S3,
Cloudflare R2, MinIO, or Backblaze B2.

If `default_storage` is the filesystem backend (or anything else
without `.connection` and `.bucket_name`), `media.images.get_upload_url`
**fails loudly**. There is no silent fallback to writing on the
Django host's disk.

## The upload flow

```
agent → media.images.get_upload_url   (mints presigned PUT + signed token)
agent → S3 PUT bytes directly         (Django not involved)
agent → media.images.finalize         (registers the upload in Wagtail)
```

1. **`get_upload_url`** returns `{put_url, key, token}`. The token
   is a `TimestampSigner`-signed JSON blob bound to the user, key,
   content type, declared max size, and kind (image vs document).
   TTL: 10 minutes.
2. **The agent PUTs bytes** to `put_url` with the `Content-Type` it
   declared in step 1. The presigned URL itself expires in 5 minutes.
3. **`finalize`** validates the token, confirms the object exists in
   the bucket, creates the `wagtailimages.Image` (or `Document`) row
   pointing at the uploaded file, and applies metadata (title, tags,
   collection, alt text).

## Tools

### Image tools

| Tool                            | What it does                                  |
|---------------------------------|-----------------------------------------------|
| `media.images.list`             | Paginated listing, filterable by collection + tag |
| `media.images.get`              | Single image with renditions                  |
| `media.images.get_upload_url`   | Mint presigned PUT + token                    |
| `media.images.finalize`         | Register an uploaded object                   |
| `media.images.update`           | Patch title, tags, collection, default alt    |
| `media.images.focal_point`      | Set focal-point coordinates (new in v0.5)     |

### Document tools

`media.documents.list`, `.get`, `.get_upload_url`, `.finalize`,
`.update` — exact mirrors of the image tools, against
`wagtaildocs.Document` instead.

## Allowed content types

| Kind     | Accepted `Content-Type`s                                              |
|----------|------------------------------------------------------------------------|
| Image    | `image/jpeg`, `image/png`, `image/gif`, `image/webp`, `image/svg+xml`  |
| Document | `application/pdf`, `application/msword`, `application/vnd.openxmlformats-officedocument.*`, `text/csv`, `text/plain`, `text/markdown`, `application/json` |

Anything outside this list is refused at `get_upload_url` time —
before the presigned URL is minted — so a malicious agent cannot
trick an editor into approving a script-in-svg upload.

## Permissions

* Reads: any authenticated caller; collection-level view perms
  apply.
* Uploads: collection-level `add_image` / `add_document`.
* Updates: collection-level `change_image` / `change_document`.
* Focal-point: same as `change_image`.

`media` does **not** ship a delete tool in v0.5. Hard-delete and
collection-move land in a later release; until then, agents that need
to retire an asset should clear it from the relevant pages and let
your existing media-cleanup process handle the underlying file.

## `media.images.focal_point`

Sets the focal-point rectangle Wagtail uses for fill-size renditions.

| Param        | Type | Notes                                              |
|--------------|------|----------------------------------------------------|
| `image_id`   | int  | Required.                                          |
| `x`, `y`     | int  | Centre point in image-pixel coordinates.           |
| `width`, `height` | int | Focal box dimensions.                       |

The toolset validates that the box stays inside the image bounds —
unlike `media.images.update`, which is lenient about partial-state
updates. Returns the post-update image record so the agent can
re-render the rendition URL it cares about.

## Gotchas

* SVG dimensions are best-effort: SVGs without a `viewBox` may report
  `width=None, height=None`. Use `media.images.update` to set them
  explicitly if your downstream code requires them.
* The 10-min token TTL is independent of the 5-min presign TTL. If
  the upload fails, mint a new pair — don't reuse the old token.
* `MAX_UPLOAD_MB` is enforced at `finalize` time as a sanity check;
  the presigned URL itself doesn't enforce it. Misconfigured agents
  can upload larger objects to S3, but `finalize` will reject them
  and you can sweep orphaned keys with a bucket lifecycle rule.

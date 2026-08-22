# Working with video files

SpeedPy ships **without** ffmpeg and without any video pipeline, on purpose: the
binary and its dependencies add hundreds of megabytes to the image and minutes to
every build, and most projects never touch a video file. This document is the
recipe for adding it, written from a production build that does
(withfeedback.com — video testimonials from anonymous visitors).

Read it before designing anything video-shaped. The order of the sections is the
order of the decisions.

---

## 1. You need a custom Dockerfile, and the build moves into it

The default deployment builds from a buildpack and runs asset commands outside
the image. As soon as you need a system binary, that stops working: switch to
building from the repo `Dockerfile`.

Install ffmpeg in the same `apt-get` layer that is already there — a separate
`RUN apt-get install` doubles the layer:

```dockerfile
# ffmpeg (includes ffprobe) powers the video transcode pipeline.
RUN apt-get update \
  && apt-get install -y \
  nano gettext chrpath libssl-dev libxft-dev \
  libfreetype6 libfreetype6-dev libfontconfig1 libfontconfig1-dev \
  ffmpeg \
  && rm -rf /var/lib/apt/lists/*
```

Then **prove it is there at build time**, so a base-image change cannot silently
remove it and leave you finding out from a failed upload weeks later:

```dockerfile
RUN ffmpeg -version && ffprobe -version
```

Two traps that cost real time:

- **Asset builds must move inside the Dockerfile.** A platform's
  `build_command` / `release` asset step typically does **not** run for a
  Dockerfile build. Copy `package.json` + lockfile, `npm ci`, then run the
  Tailwind/bundle/`compilemessages` steps as `RUN` lines. Deploys silently ship
  stale CSS otherwise.
- **`DEBUG=True` for build-time `manage.py` calls.** There is no database and no
  cache while the image builds, so production-only startup guards fire and the
  build fails: `RUN DEBUG=True python manage.py compilemessages`.

On Appliku, the switch is three keys — and `dockerfile_context_path` is
mandatory, not optional:

```yaml
build_settings:
  build_image: dockerfile
  dockerfile_path: Dockerfile
  dockerfile_context_path: .
```

Expect the image to roughly double. That is the price, and it is why this is not
the default.

## 2. Transcoding is a Celery task on its own queue, at concurrency 1

ffmpeg saturates whatever you give it. One video on the default queue starves
every other task in the project — mail, webhooks, the periodic cleanups.

- A **dedicated queue** (`video`) with its own worker process, `-c 1`.
- Route by task name: `app.conf.task_routes = {"video.transcode": {"queue": "video"}}`.
- Keep the *other* video tasks (publish, unpublish, watchdog, reaper) on the
  default queue. They are light I/O, and at concurrency 1 an unpublish queued
  behind a ten-minute transcode would leave a withdrawn video published for that
  whole time.
- `acks_late=True`, `soft_time_limit` below `time_limit` (e.g. 480 / 600). The
  soft limit raises **inside** the task so it can mark the row and re-enqueue;
  the hard limit is the backstop.
- Cap the attempts in your own state machine (3 is a reasonable number), not with
  Celery retries alone — otherwise a file that can never transcode is retried for
  ever.

## 3. Treat every input as hostile

The bytes came from a browser upload. A media decoder is a large C attack
surface, and a "video" is whatever the uploader says it is.

- **`ffprobe` first, and let it reject before a frame is decoded.** Duration,
  dimensions, stream count, codec — all from probe, none from the filename or the
  client's `Content-Type`.
- **Never a shell string.** Build the argument list; `shell=True` with a filename
  from a stranger is a remote shell.
- **Own process group + hard timeout**, and kill the group, not the process. A
  hung decoder that outlives its task keeps a CPU busy for ever.
- **Cap the captured output.** ffprobe JSON and ffmpeg diagnostics are both
  attacker-influenced; buffering them unbounded is a memory DoS.
- **`-map_metadata -1`.** Container metadata routinely carries GPS coordinates
  and device identifiers that the person filming never meant to publish.
- **`-map 0:v:0` / `-map 0:a:0`.** Pin the streams you probed. ffmpeg's automatic
  selection is free to pick a different, larger stream than the one that passed
  validation.
- **Guard the disk before downloading**, at a multiple of the input size (2× is
  enough for a single-output profile). A full disk on the worker breaks every
  task, not just this one.
- Reject absurd dimensions (a decode bomb declares enormous frames) and more than
  a couple of streams per kind — a container can carry thousands of subtitle or
  attachment streams.

## 4. Single MP4, or a chunked playlist?

**Start with a single MP4. In a testimonial-shaped product, finish there too.**

| | Single progressive MP4 | HLS / DASH (chunks + playlist) |
|---|---|---|
| Files per video | 2 (video + poster) | dozens to hundreds, per rendition |
| Player | `<video>`, every browser | hls.js everywhere except Safari |
| Adaptive bitrate | no | yes |
| Seeking | needs `-movflags +faststart` | native |
| CDN cache | one object | many objects, one playlist to invalidate |
| Deleting one video | delete 2 keys | enumerate a prefix, and get it right |
| Live / very long video | poor | the only real answer |

`+faststart` is what makes a single MP4 usable: it moves the `moov` atom to the
front so the browser can start playing before the whole file arrives. Without it
a 40 MB file looks broken on a slow connection.

Choose chunks only when you actually have the problem they solve: videos of many
minutes, wildly varying bandwidth, or live. The cost is not the encode — it is
that **every** later operation (delete, republish, CDN purge, storage accounting)
turns from "two keys" into "a prefix you must enumerate correctly". Deleting a
prefix wrongly is how a published video stays readable after a customer asked for
it to be removed.

A working delivery profile for short user-generated clips, 480p, ~30fps:

```
ffmpeg -nostdin -loglevel error -y -i IN \
  -map 0:v:0 \
  -vf "scale='min(854,iw)':'min(480,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2" \
  -r 30 -c:v libx264 -preset veryfast -crf 26 \
  -map 0:a:0 -c:a aac -b:a 96k -ac 2 \
  -movflags +faststart -map_metadata -1 -t 63 OUT.mp4
```

- `min(...)` with `force_original_aspect_ratio=decrease` **never upscales** — a
  240p phone clip stays 240p instead of being blown up into a bigger file that
  looks worse.
- `force_divisible_by=2` keeps libx264 happy on odd source dimensions.
- `-t` re-applies your duration cap, because the container may have lied to
  probe.
- `-an` instead of the audio maps when there is no audio stream: asking for
  `0:a:0` on a silent file is a hard failure.

Poster frame, one JPEG, taken early but not at zero (frame 0 is often black):

```
ffmpeg -nostdin -y -ss 0.5 -i IN -map 0:v:0 -frames:v 1 -map_metadata -1 -q:v 3 OUT.jpg
```

Use `min(0.5, duration/2)` so a one-second clip still yields a frame.

## 5. Storage layout, and the part people get wrong

Three states, and they must be different prefixes, not one bucket with a flag:

1. **Original** — private. Never served. Keep it only as long as you need to
   re-transcode.
2. **Staging / derivatives** — private, the transcode output before it is
   approved.
3. **Published** — public, behind the CDN, the only prefix a visitor can read.

Publishing is a **copy** into the public prefix; unpublishing deletes those
objects **and purges the CDN**. Do not "publish" by flipping a database column
while the object sits in a public bucket the whole time — that makes moderation a
lie, and a `robots.txt` will not save you.

Deleting a row does not delete an object. Anything that removes a video must go
through the code that removes the objects and purges the edge cache — including
account deletion, team deletion, GDPR erasure, and the reaper.

## 6. What you still need after the encode works

- A **watchdog** for rows stuck in `transcoding` (a worker died, its message is
  gone). Every ~15 minutes: reset or fail them by attempt count.
- A **reaper** for objects with no row, and rows with no object. They will
  happen: a worker that dies between upload and commit leaves one of each.
- **Direct-to-storage uploads** (presigned POST/PUT), not uploads through the web
  process. A 100 MB body through the app server ties up a worker for the whole
  transfer, and your platform's request timeout will cut it off anyway.
- **Idempotent state transitions** guarded by compare-and-swap on the status
  column. Two workers must not both publish; a redelivered message must not
  double-transcode.
- **Limits, enforced twice** — in the presign (max bytes) and after probe
  (duration, dimensions, output size). The client-side limit is a courtesy, not a
  control.

## 7. If you do not need any of this

Do not install ffmpeg. Take an embed URL (YouTube, Vimeo, Loom) and store the
string. It is one field, no queue, no binary, no moderation problem, and no CDN
purge to get wrong. The pipeline above is worth it only when you must hold the
file yourself.

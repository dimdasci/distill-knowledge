# ffmpeg / ffprobe quick reference

Scope: only the invocations used by the `convert` skill. Each section gives one canonical command, what its non-obvious flags do, and when to deviate.

## Installation

Detect first:
```bash
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null && ffmpeg -version | head -1
```

If missing, install per OS:

| OS | Command |
|---|---|
| macOS + Homebrew | `brew install ffmpeg` |
| macOS, no Homebrew | Install Homebrew first: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"` then `brew install ffmpeg` |
| Debian / Ubuntu | `sudo apt-get update && sudo apt-get install -y ffmpeg` |
| Fedora / RHEL | `sudo dnf install -y ffmpeg` |
| Arch | `sudo pacman -S --noconfirm ffmpeg` |
| Windows / other | Manual: https://ffmpeg.org/download.html |

## Probe metadata

```bash
ffprobe -v error -show_entries format=duration,size,format_name \
  -show_entries stream=codec_type,codec_name,width,height,sample_rate \
  -of default=nw=1 inbox/{meeting-folder}/{file}
```

Purpose: gather container, codecs, duration, resolution, sample rate, file size before planning preprocessing.

- `-v error`: silence info/warnings; only real errors hit stderr.
- `-show_entries format=...`: container-level fields (`duration` in seconds, `size` in bytes, `format_name` like `mov,mp4,m4a,3gp,3g2,mj2`).
- `-show_entries stream=...`: per-stream fields. `codec_type` is `video`/`audio`; `width`/`height` are blank for audio streams; `sample_rate` is blank for video.
- `-of default=nw=1`: default key=value output, no section wrappers (`nw` = no wrapper). Easy to scan in chat.
- Deviate when: need JSON for programmatic parsing → `-of json`.

## Extract audio for re-transcription

```bash
ffmpeg -i video.mp4 -vn -acodec libmp3lame -q:a 2 tmp/audio.mp3
```

Purpose: produce an mp3 small enough for the transcribe API, with quality high enough that diarization stays accurate.

- `-vn`: drop the video stream entirely.
- `-acodec libmp3lame`: LAME mp3 encoder. mp3 is in the transcribe API's accepted-formats list.
- `-q:a 2`: VBR quality 2 (~190 kbps). Sweet spot for speech: clearly audible, much smaller than the source.
- Transcribe ceiling: the API rejects files over 25 MB. At `-q:a 2` ~190 kbps that's roughly 17 minutes of audio per MB headroom. For longer meetings drop to `-q:a 4` (~165 kbps) or `-q:a 6` (~115 kbps); transcribe accuracy degrades slowly until ~64 kbps.
- Deviate when: meeting still over 25 MB at `-q:a 6` → re-encode to mono and lower sample rate: add `-ac 1 -ar 16000`.

## Convert / re-encode video container

```bash
ffmpeg -i input.mov -c:v libx264 -crf 20 -c:a aac -b:a 160k tmp/video.mp4
```

Purpose: normalize unreadable containers/codecs into something the rest of the pipeline (and human review) can open.

- `-c:v libx264`: H.264 video. Universal playback, good ffmpeg seek behavior.
- `-crf 20`: constant rate factor, visually lossless for screen content / talking heads. Lower = bigger + sharper, higher = smaller + softer. Range 18–28 is usable.
- `-c:a aac -b:a 160k`: AAC audio at 160 kbps CBR. Plenty for speech; mp4 + aac is the safest container/codec combo.
- Deviate when: source is already h264/aac in a usable container → use `-c copy` to remux without re-encoding (instant, lossless). Need smaller file for archive → `-crf 23` or `-crf 26`. Need faster encode → add `-preset fast` (default is `medium`).

## Capture single frame for screenshot

```bash
ffmpeg -i video.mp4 -ss {seconds} -frames:v 1 -q:v 2 outbox/{slug}/screenshots/{nn}.jpg
```

Purpose: pull one readable still at a given timestamp, e.g. the Step 3 probe frame or a screen-share moment.

- `-ss {seconds}` placed **after** `-i`: accurate seek — ffmpeg decodes from the nearest keyframe up to the requested time, so the frame matches the timestamp exactly. Slower but correct.
- `-ss` placed **before** `-i`: fast seek — jumps to the nearest keyframe; cheap but the frame can land seconds off. Convert skill uses post-`-i` because screenshot accuracy matters more than speed.
- `-frames:v 1`: stop after one video frame.
- `-q:v 2`: JPEG quality 2 on a 2–31 scale (lower = better). Screenshots must stay readable when the reader zooms in on UI text.
- Offset trick: SKILL.md adds `seconds + 2` to the VTT timestamp because speakers usually say "this" or "look here" before the content fully renders on screen.
- Deviate when: frame must be exact at sub-second granularity → use `-ss 00:14:32.500` form. Need a smaller thumbnail → add `-vf scale=1280:-1`.

## Capture multiple frames at intervals

```bash
ffmpeg -i video.mp4 -ss {start} -t {duration} -vf fps=1/{N} -q:v 2 \
  outbox/{slug}/screenshots/{nn}-%02d.jpg
```

Purpose: sample a window where content scrolls or a multi-page doc is being walked through (Step 5 of SKILL.md).

- `-ss {start} -t {duration}`: limit capture to a window starting at `{start}`, lasting `{duration}` seconds.
- `-vf fps=1/{N}`: emit one frame every `N` seconds. `fps=1/5` → one frame every 5 s; `fps=1/2` → every 2 s.
- `%02d` in the output path: ffmpeg substitutes a zero-padded frame counter, so the command produces `{nn}-01.jpg`, `{nn}-02.jpg`, …
- `-q:v 2`: same readability rationale as the single-frame case.
- Deviate when: only 2–3 specific moments are interesting → run the single-frame command 2–3 times with explicit `-ss` values instead of an interval sweep (cleaner output filenames, no off-by-one frames).

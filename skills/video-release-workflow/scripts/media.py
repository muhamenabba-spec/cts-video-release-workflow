#!/usr/bin/env python3
"""Local, non-network media helpers. Requires FFmpeg/FFprobe, never overwrites."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def tool(name, override=None):
    found = override or shutil.which(name)
    if not found:
        raise ValueError(f"Missing {name}; install/locate it with user approval first.")
    return str(found)


def run(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, encoding="utf-8",
                            errors="replace", check=False)
    if result.returncode:
        raise ValueError(f"Media tool failed ({result.returncode}): {result.stderr[-5000:]}")
    return result.stdout


def existing(path):
    result = Path(path).resolve()
    if not result.is_file():
        raise ValueError(f"File not found: {result}")
    return result


def fresh(path, inputs=()):
    result = Path(path).resolve()
    if result in [Path(p).resolve() for p in inputs]:
        raise ValueError("Output cannot be the source file.")
    if result.exists():
        raise ValueError(f"Refusing to overwrite: {result}")
    result.parent.mkdir(parents=True, exist_ok=True)
    return result


def number(value, label):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite.")
    return value


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(path, ffprobe=None):
    path = existing(path)
    data = json.loads(run([tool("ffprobe", ffprobe), "-v", "error", "-show_streams",
                           "-show_format", "-of", "json", str(path)]))
    videos = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    audios = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path),
            "duration": float(data.get("format", {}).get("duration", 0)),
            "video": [{k: s.get(k) for k in ("codec_name", "width", "height",
                       "avg_frame_rate", "sample_aspect_ratio", "side_data_list")}
                      for s in videos],
            "audio": [{k: s.get(k) for k in ("codec_name", "sample_rate", "channels")}
                      for s in audios]}


def ffmpeg(args):
    return [tool("ffmpeg", args.ffmpeg), "-hide_banner", "-loglevel", "error", "-n"]


def video_info(args):
    source = existing(args.source)
    data = probe(source, args.ffprobe)
    if not data["video"] or data["duration"] <= 0:
        raise ValueError("A non-empty video stream is required.")
    return source, data


def frame(args):
    source, data = video_info(args)
    at = number(args.at, "at")
    if not 0 <= at < data["duration"]:
        raise ValueError("Frame time is outside the source video.")
    output = fresh(args.output, [source])
    run(ffmpeg(args) + ["-ss", str(at), "-i", str(source), "-frames:v", "1", str(output)])
    return {"output": str(output), "source_sha256": data["sha256"], "source_time": at}


def cut(args):
    source, data = video_info(args)
    segments = read_json(args.plan).get("segments", [])
    if not 1 <= len(segments) <= 100:
        raise ValueError("Plan needs 1 to 100 explicit source segments.")
    graph, mapping, labels = [], [], []
    elapsed = 0.0
    for index, segment in enumerate(segments):
        start, end = number(segment["start"], "start"), number(segment["end"], "end")
        if not 0 <= start < end <= data["duration"] + 0.001:
            raise ValueError(f"Invalid source range at segment {index}.")
        graph.append(f"[0:v:0]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{index}]")
        labels.append(f"[v{index}]")
        if data["audio"]:
            graph.append(f"[0:a:0]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]")
            labels.append(f"[a{index}]")
        mapping.append({"source_start": start, "source_end": end,
                        "output_start": elapsed, "output_end": elapsed + end - start,
                        "reason": str(segment.get("reason", "unspecified"))})
        elapsed += end - start
    audio = 1 if data["audio"] else 0
    graph.append("".join(labels) + f"concat=n={len(segments)}:v=1:a={audio}[v]" + ("[a]" if audio else ""))
    output = fresh(args.output, [source])
    sidecar = fresh(str(output) + ".map.json", [source])
    command = ffmpeg(args) + ["-i", str(source), "-filter_complex", ";".join(graph), "-map", "[v]"]
    if audio:
        command += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    if args.fps:
        if not 1 <= number(args.fps, "fps") <= 120:
            raise ValueError("fps must be between 1 and 120.")
        command += ["-r", str(args.fps)]
    run(command + ["-c:v", "libx264", "-crf", "18", "-preset", "medium",
                   "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)])
    result = {"source": str(source), "source_sha256": data["sha256"],
              "output": str(output), "planned_duration": elapsed, "mapping": mapping,
              "actual_media": probe(output, args.ffprobe)}
    sidecar.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def ass_time(seconds):
    centiseconds = round(seconds * 100)
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    seconds, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def plain_ass(text):
    if any(c in text for c in ("\n", "\r", "\\", "{", "}")):
        raise ValueError("Use plain single-line text, without ASS markup/control characters.")
    return text


def ass_header(width, height, font, size):
    if any(c in font for c in (",", "\r", "\n")):
        raise ValueError("Invalid font name.")
    return (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")


def filter_path(path):
    # FFmpeg filter option escaping, independently of subprocess (no shell involved).
    return str(Path(path).resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")


def captions(args):
    source, data = video_info(args)
    x, y = number(args.x, "x"), number(args.y, "y")
    size = number(args.size, "size")
    if not 0 < x < 1 or not 0 < y < 1 or size <= 0 or args.max_chars < 1:
        raise ValueError("Caption position must be inside canvas; size and max_chars must be positive.")
    cues = read_json(args.cues)
    if not isinstance(cues, list) or not cues:
        raise ValueError("Caption cues must be a non-empty JSON list.")
    width, height = data["video"][0]["width"], data["video"][0]["height"]
    content = ass_header(width, height, args.font_name, size)
    previous = 0.0
    for cue in cues:
        start, end = number(cue["start"], "start"), number(cue["end"], "end")
        text = plain_ass(str(cue["text"]))
        if not text.strip() or len(text) > args.max_chars:
            raise ValueError("Empty/long caption: split into meaningful consecutive cues first.")
        if not previous <= start < end <= data["duration"] + 0.001:
            raise ValueError("Caption cues overlap, are out of order or exceed video duration.")
        if round(end * 100) <= round(start * 100):
            raise ValueError("Caption is shorter than ASS time precision.")
        previous = end
        content += (f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,"
                    f"{{\\pos({round(width*x)},{round(height*y)})}}{text}\n")
    output = fresh(args.output, [source])
    ass = fresh(str(output) + ".ass", [source])
    ass.write_text(content, encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="caption-render-", dir=output.parent) as temp:
        local = Path(temp) / "captions.ass"
        local.write_text(content, encoding="utf-8")
        # ASCII relative filename avoids colon, Unicode and space path ambiguity on Windows.
        vf = "subtitles=filename=captions.ass"
        if args.font_dir:
            font_dir = Path(args.font_dir).resolve()
            if not font_dir.is_dir():
                raise ValueError("font-dir does not exist.")
            vf += f":fontsdir='{filter_path(font_dir)}'"
        run(ffmpeg(args) + ["-i", str(source), "-vf", vf, "-c:v", "libx264", "-crf", "18",
                           "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(output)], cwd=temp)
    return {"output": str(output), "ass": str(ass), "cue_count": len(cues),
            "visual_review": "required", "actual_media": probe(output, args.ffprobe)}


def mix(args):
    source, data = video_info(args)
    plan_path = existing(args.plan)
    events = read_json(plan_path).get("events", [])
    if not 1 <= len(events) <= 50:
        raise ValueError("Use 1 to 50 explicitly selected sound events.")
    command = ffmpeg(args) + ["-i", str(source)]
    graph = (["[0:a:0]aresample=48000,aformat=channel_layouts=stereo[base]"] if data["audio"] else
             [f"anullsrc=r=48000:cl=stereo,atrim=duration={data['duration']}[base]"])
    labels = ["[base]"]
    for index, event in enumerate(events, 1):
        if event.get("authorized") is not True or not str(event.get("source", "")).strip():
            raise ValueError("Each sound needs a truthful authorized=true and source/permission note.")
        at, gain = number(event["at"], "at"), number(event.get("gain_db", -14), "gain_db")
        if not 0 <= at < data["duration"] or not -60 <= gain <= 0:
            raise ValueError("Sound time or gain is outside supported range.")
        sound = existing(plan_path.parent / event["file"])
        if not probe(sound, args.ffprobe)["audio"]:
            raise ValueError("Sound file has no audio stream.")
        command += ["-i", str(sound)]
        delay = round(at * 1000)
        graph.append(f"[{index}:a:0]aresample=48000,aformat=channel_layouts=stereo,"
                     f"asetpts=PTS-STARTPTS,volume={gain}dB,adelay={delay}|{delay}[s{index}]")
        labels.append(f"[s{index}]")
    graph.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,"
                 "alimiter=limit=0.95:level=false:latency=true[a]")
    output = fresh(args.output, [source])
    run(command + ["-filter_complex", ";".join(graph), "-map", "0:v:0", "-map", "[a]",
                   "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", str(data["duration"]),
                   "-movflags", "+faststart", str(output)])
    return {"output": str(output), "events": len(events), "listening_review": "required",
            "actual_media": probe(output, args.ffprobe)}


def cover(args):
    source, font = existing(args.source), existing(args.font_file)
    lines = Path(args.text_file).read_text(encoding="utf-8-sig").strip().splitlines()
    if not 1 <= len(lines) <= 2 or any(not line.strip() for line in lines):
        raise ValueError("Cover needs one or two non-empty text lines.")
    width, height = args.width, args.height
    if min(width, height) < 64 or width % 2 or height % 2:
        raise ValueError("Use even cover dimensions >=64.")
    size = args.size or max(24, round(width / 12))
    # Reserve a separate title area; fit the whole real frame rather than fake cutouts.
    panel = round(height * 0.28)
    image_height = height - panel
    output = fresh(args.output, [source, font])
    if output.suffix.lower() != ".png":
        raise ValueError("Cover output must be PNG.")
    graph = (f"scale={width}:{image_height}:force_original_aspect_ratio=decrease,"
             f"pad={width}:{height}:(ow-iw)/2:0:color=black,setsar=1")
    with tempfile.TemporaryDirectory(prefix="cover-render-", dir=output.parent) as temp:
        copied_font = Path(temp) / ("font" + font.suffix.lower())
        shutil.copyfile(font, copied_font)
        for index, line in enumerate(lines):
            text_file = Path(temp) / f"line{index}.txt"
            text_file.write_text(line, encoding="utf-8")
            top = image_height + panel * (0.36 if len(lines) == 1 else (0.17 + index * 0.42))
            color = "0xFFDA63" if index == 0 else "white"
            graph += (f",drawtext=fontfile={copied_font.name}:textfile={text_file.name}:expansion=none:"
                      f"fontcolor={color}:fontsize={size}:x=(w-text_w)/2:y={round(top)}:"
                      "borderw=1:bordercolor=black")
        run(ffmpeg(args) + ["-i", str(source), "-vf", graph, "-frames:v", "1", str(output)], cwd=temp)
    return {"output": str(output), "width": width, "height": height,
            "source_sha256": sha256(source), "person_redrawn": False,
            "visual_review": "required"}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--ffmpeg", help="Approved local FFmpeg executable")
    result.add_argument("--ffprobe", help="Approved local FFprobe executable")
    commands = result.add_subparsers(dest="command", required=True)
    p = commands.add_parser("probe"); p.add_argument("source")
    p = commands.add_parser("frame"); p.add_argument("source"); p.add_argument("--at", type=float, required=True); p.add_argument("--output", required=True)
    p = commands.add_parser("cut"); p.add_argument("source"); p.add_argument("--plan", required=True); p.add_argument("--output", required=True); p.add_argument("--fps", type=float)
    p = commands.add_parser("captions"); p.add_argument("source"); p.add_argument("--cues", required=True); p.add_argument("--output", required=True)
    p.add_argument("--font-name", required=True); p.add_argument("--font-dir"); p.add_argument("--size", type=float, default=42)
    p.add_argument("--x", type=float, default=0.5); p.add_argument("--y", type=float, default=0.75); p.add_argument("--max-chars", type=int, default=12)
    p = commands.add_parser("mix"); p.add_argument("source"); p.add_argument("--plan", required=True); p.add_argument("--output", required=True)
    p = commands.add_parser("cover"); p.add_argument("source"); p.add_argument("--text-file", required=True); p.add_argument("--font-file", required=True)
    p.add_argument("--output", required=True); p.add_argument("--width", type=int, required=True); p.add_argument("--height", type=int, required=True); p.add_argument("--size", type=int)
    return result


def main():
    args = parser().parse_args()
    try:
        value = probe(args.source, args.ffprobe) if args.command == "probe" else globals()[args.command](args)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

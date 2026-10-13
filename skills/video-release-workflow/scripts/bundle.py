#!/usr/bin/env python3
"""Build/check a local release bundle; this script never uploads or publishes."""
from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from media import existing, probe, sha256


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, data):
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def new_directory(path):
    root = Path(path).resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError(f"Target must be a new or empty directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    return root


def init(args):
    root = new_directory(args.project)
    work_id = str(uuid.uuid4())
    project = {"schema_version": 1, "work_id": work_id, "name": args.name,
               "stage": "draft", "created_at": utc_now(), "current": {},
               "confirmations": [], "platforms": {}, "unknowns": []}
    write(root / "VIDEO_PROJECT.json", project)
    with (root / "PROGRESS.md").open("x", encoding="utf-8") as stream:
        stream.write(f"# {args.name}\n\nwork_id: {work_id}\n\n当前：draft\n尚未拍摄、渲染、上传或发布。\n")
    return {"project": str(root), "work_id": work_id, "stage": "draft"}


def png_size(path):
    with Path(path).open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError("Cover must be an actual PNG image.")
    return list(struct.unpack(">II", header[16:24]))


def pack(args):
    spec_path = existing(args.spec)
    spec = read(spec_path)
    work_id, title = spec.get("work_id"), spec.get("title")
    tags = spec.get("tags", [])
    if not isinstance(work_id, str) or not work_id.strip():
        raise ValueError("A stable work_id is required; do not guess the last project.")
    if not isinstance(title, str) or not title.strip() or "\n" in title or "\r" in title:
        raise ValueError("A real, single-line title is required.")
    if not isinstance(tags, list) or any(not isinstance(t, str) or not t.strip() or any(c.isspace() for c in t) for t in tags):
        raise ValueError("tags must be a list of non-empty, whitespace-free topic strings.")
    tags = list(dict.fromkeys("#" + t.lstrip("#") for t in tags))
    if any(t == "#" for t in tags):
        raise ValueError("A topic cannot be an empty #.")
    def source(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Required asset is missing from release spec.")
        return existing(spec_path.parent / value)
    video = source(spec.get("video"))
    if video.suffix.lower() != ".mp4":
        raise ValueError("Current release video must be MP4.")
    media = probe(video, args.ffprobe)
    if not media["video"] or media["duration"] <= 0:
        raise ValueError("Current release video is not playable video media.")
    covers = spec.get("covers", {})
    portrait, landscape = source(covers.get("portrait")), source(covers.get("landscape"))
    portrait_size, landscape_size = png_size(portrait), png_size(landscape)
    if portrait_size[0] >= portrait_size[1] or landscape_size[0] <= landscape_size[1]:
        raise ValueError("Portrait and landscape covers must be separately oriented correctly.")
    checks = source(spec.get("checks_file"))
    sources = [("video", video, "01_video.mp4"), ("cover_portrait", portrait, "02_cover_portrait.png"),
               ("cover_landscape", landscape, "03_cover_landscape.png"), ("checks", checks, "05_checks.md")]
    if checks.suffix.lower() != ".md":
        raise ValueError("checks_file must be the actual Markdown review record.")
    for field, stem in (("subtitles", "04_subtitles"), ("script", "07_script")):
        if spec.get(field):
            path = source(spec[field])
            allowed = {".srt", ".ass", ".json"} if field == "subtitles" else {".md", ".txt"}
            if path.suffix.lower() not in allowed:
                raise ValueError(f"Unsupported {field} format.")
            sources.append((field, path, stem + path.suffix.lower()))
    requested = spec.get("requested_platforms", [])
    supported = {"douyin", "channels", "bilibili", "xiaohongshu"}
    if not isinstance(requested, list) or any(p not in supported for p in requested):
        raise ValueError("requested_platforms must use douyin/channels/bilibili/xiaohongshu.")
    if not isinstance(spec.get("packaging_confirmed", False), bool):
        raise ValueError("packaging_confirmed must be a factual boolean.")
    # Validate all inputs before creating/copying any output.
    root = new_directory(args.output)
    artifacts = []
    for role, src, filename in sources:
        before = sha256(src)
        dest = root / filename
        shutil.copyfile(src, dest)
        after = sha256(dest)
        if before != after:
            raise ValueError(f"Asset changed while packaging: {role}; keep source and inspect partial bundle.")
        artifacts.append({"role": role, "path": filename, "sha256": after, "bytes": dest.stat().st_size})
    copyline = title.strip() + (" " + " ".join(tags) if tags else "")
    copyfile = root / "title-and-tags.txt"
    with copyfile.open("x", encoding="utf-8") as stream:
        stream.write(copyline + "\n")
    artifacts.append({"role": "copyline", "path": copyfile.name, "sha256": sha256(copyfile), "bytes": copyfile.stat().st_size})
    media.pop("path", None)
    manifest = {"schema_version": 1, "work_id": work_id, "created_at": utc_now(),
                "title": title.strip(), "tags": tags, "copyline": copyline,
                "packaging_confirmed": spec.get("packaging_confirmed", False),
                "artifacts": artifacts, "video_probe": media,
                "cover_sizes": {"portrait": portrait_size, "landscape": landscape_size},
                "technical_integrity": "hashed",
                "review_evidence": "05_checks.md (read it; hashes do not prove visual/audio/rights approval)",
                "final_publication_confirmation": None,
                "platforms": {p: {"account_verified": False, "status": "not_started",
                                   "submitted_at": None, "public_url": None, "evidence": []}
                              for p in dict.fromkeys(requested)},
                "published": False}
    write(root / "manifest.json", manifest)
    return {"bundle": str(root), "work_id": work_id, "copyline": copyline,
            "packaging_confirmed": manifest["packaging_confirmed"], "uploaded": False, "published": False,
            "check": check_root(root)}


def check_root(root):
    root = Path(root).resolve()
    manifest = read(root / "manifest.json")
    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("Bundle has no artifact manifest.")
    seen_paths, seen_roles = set(), set()
    for item in artifacts:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Artifact path must stay inside the release bundle.")
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Artifact resolves outside bundle.")
        if str(relative) in seen_paths or item["role"] in seen_roles:
            raise ValueError("Duplicate artifact path or role.")
        seen_paths.add(str(relative)); seen_roles.add(item["role"])
        existing(path)
        if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise ValueError(f"Asset differs from manifest: {relative}")
    required = {"video", "cover_portrait", "cover_landscape", "checks", "copyline"}
    if not required.issubset(seen_roles):
        raise ValueError("Required video/cover/check/copyline roles are missing.")
    return {"integrity": "passed", "checked_artifacts": len(artifacts),
            "visual_audio_rights_review": "not_proven_by_this_check",
            "web_publication": "not_performed_by_this_script"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("init"); p.add_argument("--project", required=True); p.add_argument("--name", required=True)
    p = commands.add_parser("pack"); p.add_argument("--spec", required=True); p.add_argument("--output", required=True); p.add_argument("--ffprobe")
    p = commands.add_parser("check"); p.add_argument("bundle")
    args = parser.parse_args()
    try:
        result = check_root(args.bundle) if args.command == "check" else globals()[args.command](args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

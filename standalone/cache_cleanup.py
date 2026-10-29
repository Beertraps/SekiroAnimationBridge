"""Size and cleanup of the bridge's asset cache (work/asset-cache).

A scan unpacks animation members into archives/ and writes its catalog into
catalogs/; the skeleton preview keeps its results in previews/. A catalog is in
use while a source or the settings name it, and an archive folder while a
catalog in use lists its files. The rest is left over from removed or rescanned
sources and from mod archives that changed. Previews are kept up to a size
limit, the least recently shown going first.

Files changed in the last few minutes are never removed: they may belong to a
scan that is running, or that has finished before the UI saved its source.
"""
from __future__ import annotations
import os
import re
import shutil
import time
from contextlib import nullcontext
from pathlib import Path

PREVIEW_LIMIT = 256 * 1024 * 1024
# Aggressive preview caching decodes whole clip lists ahead, and keeps more of them.
AGGRESSIVE_LIMIT = 2 * 1024 * 1024 * 1024
RECENT = 600
ARCHIVE = re.compile(r'archives[\\/]+([0-9a-f]{24})[\\/]')


def size(path):
    """Bytes and file count below a folder."""
    total = count = 0
    try:
        entries = list(os.scandir(path))
    except OSError:
        return 0, 0
    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False):
                more, files = size(entry.path)
                total, count = total + more, count + files
            else:
                total, count = total + entry.stat(follow_symlinks=False).st_size, count + 1
        except OSError:
            pass
    return total, count


def newest(path):
    """The latest modification time of a file or of anything below a folder."""
    latest = os.stat(path).st_mtime
    if os.path.isdir(path):
        for entry in os.scandir(path):
            try:
                latest = max(latest, newest(entry.path) if entry.is_dir(follow_symlinks=False) else entry.stat().st_mtime)
            except OSError:
                pass
    return latest


def catalogs_in_use(settings):
    """File names of the catalogs that the saved sources, the current selection and the donor name."""
    names = [source.get('catalog') for source in settings.get('sources') or [] if isinstance(source, dict)]
    names += [settings.get('assetCatalog'), (settings.get('donor') or {}).get('assetCatalog')]
    return {Path(name).name.lower() for name in names if name}


def preview_limit(settings):
    return AGGRESSIVE_LIMIT if settings.get('previewCache') == 'aggressive' else PREVIEW_LIMIT


def unused(cache, settings, now=None):
    """The catalogs, archive folders and previews that cleanup would remove."""
    cache, now = Path(cache), time.time() if now is None else now
    old = lambda path: now - newest(path) > RECENT
    keep, listed, catalogs = catalogs_in_use(settings), set(), []
    for path in sorted((cache / 'catalogs').glob('*.json')):
        if path.name.lower() in keep or not old(path):
            listed.update(ARCHIVE.findall(path.read_text(encoding='utf-8', errors='replace')))
        else:
            catalogs.append(path)
    folders = sorted(p for p in (cache / 'archives').glob('*') if p.is_dir()) if (cache / 'archives').is_dir() else []
    archives = [p for p in folders if p.name not in listed and old(p)]
    previews, kept, limit = [], 0, preview_limit(settings)
    stored = sorted((p for p in (cache / 'previews').glob('*') if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True) \
        if (cache / 'previews').is_dir() else []
    for path in stored:
        # Previews of an older bridge (.json) are never read again, nor is a staging file left by a crash.
        current = path.name.endswith('.json.gz')
        kept += path.stat().st_size if current else 0
        if (kept > limit or not current) and old(path):
            previews.append(path)
    return dict(catalogs=catalogs, archives=archives, previews=previews)


def usage(cache, settings):
    """Bytes used by each part of the cache, and how many of them cleanup would free."""
    cache = Path(cache)
    parts = {name: size(cache / name)[0] for name in ('archives', 'catalogs', 'previews')}
    found = unused(cache, settings)
    free = sum(size(p)[0] for p in found['archives']) + sum(p.stat().st_size for p in found['catalogs'] + found['previews'])
    return dict(parts, total=sum(parts.values()), unused=free, folder=str(cache))


def clean(cache, settings, lock=None, allowed=lambda: True):
    """Remove what unused() finds and return the bytes freed.

    Each item is removed under lock and only while allowed() holds, so a caller
    can stop the cleanup before it starts a scan or an import.
    """
    freed = 0
    found = unused(cache, settings)
    # Catalogs first: an archive folder is only removed once no catalog lists it.
    for path in found['catalogs'] + found['previews'] + found['archives']:
        with lock or nullcontext():
            if not allowed():
                break
            try:
                bytes_ = size(path)[0] if path.is_dir() else path.stat().st_size
                shutil.rmtree(path) if path.is_dir() else path.unlink()
                freed += bytes_
            except OSError:
                pass
    return freed

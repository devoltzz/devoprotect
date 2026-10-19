# Re-encodes a sound as a smaller MP3 (mono, 22 kHz, constant rate) through ffmpeg.
import os
import shutil
import subprocess
import sys
import tempfile


FFMPEG_DEFAULT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'terceiros',
                                               'ffmpeg', 'bin', 'ffmpeg.exe'))


def executable(ffmpeg=None):
    if ffmpeg or os.environ.get('FFMPEG'):
        return ffmpeg or os.environ.get('FFMPEG')
    if os.path.isfile(FFMPEG_DEFAULT):
        return FFMPEG_DEFAULT
    return shutil.which('ffmpeg') or FFMPEG_DEFAULT


def find_ffmpeg(ffmpeg=None):
    if sys.platform == 'emscripten':
        return None
    exe = executable(ffmpeg)
    if not os.path.isfile(exe):
        exe = shutil.which(exe)
    return exe if exe and os.path.isfile(exe) else None


def reencode(data_bytes, ext, kbps=32, channels=1, rate=22050, ffmpeg=None):
    exe = find_ffmpeg(ffmpeg)
    if not exe:
        raise RuntimeError('ffmpeg not found: %s (FFMPEG= or ffmpeg=)' % executable(ffmpeg))
    tmp = tempfile.mkdtemp(prefix='audio_shrink_')
    try:
        ent = os.path.join(tmp, 'entry' + (ext if ext.startswith('.') else '.' + ext))
        out_path = os.path.join(tmp, 'out.mp3')
        open(ent, 'wb').write(data_bytes)
        cmd = [exe, '-v', 'error', '-nostdin', '-y', '-i', ent, '-map', '0:a:0', '-map_metadata', '-1',
               '-id3v2_version', '0', '-write_id3v1', '0', '-ac', str(channels), '-ar', str(rate),
               '-codec:a', 'libmp3lame', '-b:a', '%dk' % kbps, out_path]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0 or not os.path.isfile(out_path):
            raise RuntimeError('ffmpeg failed (%d): %s' % (r.returncode, r.stderr.decode('utf-8', 'replace')[-400:]))
        return open(out_path, 'rb').read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def shrink_bytes(data_bytes, ext, kbps=32, channels=1, rate=22050, ffmpeg=None):
    new = reencode(data_bytes, ext, kbps=kbps, channels=channels, rate=rate, ffmpeg=ffmpeg)
    if len(new) < len(data_bytes):
        return new, {'before': len(data_bytes), 'after_diag': len(new), 'shrunk': True}
    return data_bytes, {'before': len(data_bytes), 'after_diag': len(data_bytes), 'shrunk': False}

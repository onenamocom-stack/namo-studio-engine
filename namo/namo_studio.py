#!/usr/bin/env python3
"""
namo_studio.py - the CPU studio: voice + sfx stems (namo_audio.py), then mix + assembly. Never renders pictures.
usage: python namo/namo_studio.py <ep> [OUT_DIR]          OUT_DIR default: <repo>/out/<ep>/
Specs  : show/episodes.json (beats: shot, kind, dur ... - the picture timeline, shots back to back)
         + namo/plans/<ep>_audio.json (voice, subs, sfx, music, mix; written by namo_audio.py if missing)
Inputs : OUT/shots/<shot>.mp4 (768x1344 24fps, native ambience), OUT/music/<theme>_s<seed>.wav (optional)
Outputs: OUT/final.mp4 (each clip trimmed to its dur, centre-crop 756x1344 -> 1080x1920 h264 24fps, AAC 48k stereo,
         -16 LUFS, TP <= -1.5 dBTP, Hindi-track subs burned), OUT/final.hi.srt, OUT/final.en.srt
Refuses to assemble if any shot is missing, undecodable, wrong size, shorter than its beat, or black
(YAVG max <= 17). A film is never published half-made: final.mp4 is moved into place only when complete.
"""
import glob, json, os, re, shutil, sys, tempfile

from namo_audio import SR, build_sfx, build_voice, duration, episode, plan_path, sh, timeline, write_plan

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FPS, W, H = 24, 1080, 1920
SRC_W, SRC_H = 768, 1344      # H3 render size (17k+5 frame grid)
TP = -2.0                     # limiter ceiling 0.5 dB under the -1.5 dBTP contract: AAC overshoots a little
AMBIENCE_DB = -12
XFADE = 0.25
MUSIC_FADE = 1.5              # at cue edges
GAP_FADE = 0.5                # music out/in around silence beats
BLACK_YAVG = 17
FMT = "aformat=sample_rates=%d:channel_layouts=stereo" % SR
FONTS = [("C:/Windows/Fonts/NotoSansDevanagari*.tt?", "Noto Sans Devanagari"),
         ("/usr/share/fonts/**/NotoSansDevanagari*.tt?", "Noto Sans Devanagari"),
         ("C:/Windows/Fonts/Nirmala*.tt?", "Nirmala UI")]


def log(*a):
    print("[studio]", *a, flush=True)


def frame(t):
    return round(t * FPS)


# ---------- acceptance: the CPU refuses to assemble a broken shot ----------
def check_shots(out, beats):
    """beats carry t0/t1. A 'fade' cut keeps the outgoing clip XFADE longer to dissolve under the next one."""
    shots, errs = [], []
    for i, b in enumerate(beats):
        p = os.path.join(out, "shots", b["shot"] + ".mp4")
        fade_out = "fade" in (b.get("cut") or "").lower() and i < len(beats) - 1
        frames = frame(b["t1"]) - frame(b["t0"])
        need = frames + (frame(XFADE) if fade_out else 0)
        if not os.path.exists(p):
            errs.append("missing " + p)
            continue
        try:
            d = json.loads(sh(["ffprobe", "-v", "error", "-of", "json", "-show_format", "-show_streams", p]).stdout)
            v = next(s for s in d["streams"] if s["codec_type"] == "video")
        except (RuntimeError, StopIteration):
            errs.append("undecodable / no video " + p)
            continue
        if (v["width"], v["height"]) != (SRC_W, SRC_H):
            errs.append("%s wrong size %sx%s (want %sx%s)" % (p, v["width"], v["height"], SRC_W, SRC_H))
        dur = float(d["format"]["duration"])
        if dur * FPS < need - 0.5:
            errs.append("%s too short: %.1f frames < %d needed" % (p, dur * FPS, need))
        yavg = re.findall(r"YAVG=([\d.]+)", sh(["ffmpeg", "-i", p, "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                                                "-f", "null", "-"]).stderr)
        ymax = max(map(float, yavg), default=0.0)
        if ymax <= BLACK_YAVG:
            errs.append("%s black/broken: YAVG max %.1f <= %d" % (p, ymax, BLACK_YAVG))
        has_audio = any(s["codec_type"] == "audio" for s in d["streams"])
        if not has_audio:
            log("WARN %s has no native audio track: no ambience under %s" % (p, b["shot"]))
        shots.append({"path": p, "t0": b["t0"], "frames": frames, "dur": dur, "audio": has_audio, "fade_out": fade_out,
                      "fade_in": i > 0 and "fade" in (beats[i - 1].get("cut") or "").lower()})
    if errs:
        raise SystemExit("REFUSING TO ASSEMBLE %d broken shot(s):\n  %s" % (len(errs), "\n  ".join(errs)))
    return shots


def pick_music(out, cues):
    """one seed per theme, locked: first seed in plan order whose stem exists."""
    picked, missing = [], set()
    for c in cues:
        hit = next((f for f in (os.path.join(out, "music", "%s_s%s.wav" % (c["theme"], s)) for s in c["seeds"])
                    if os.path.exists(f)), None)
        if hit:
            picked.append({"path": hit, "t0": c["t0"], "t1": c["t1"]})
        else:
            missing.add(c["theme"])
    if missing:
        bar = "!" * 72
        log("\n%s\nWARNING: NO MUSIC STEM for %s in %s\n         film is mixed WITHOUT that music.\n%s"
            % (bar, ", ".join(sorted(missing)), os.path.join(out, "music"), bar))
    for c in picked:
        log("music %s @ %.1f-%.1f" % (os.path.basename(c["path"]), c["t0"], c["t1"]))
    return picked


def music_pieces(cue, silent):
    """cue span minus silence beats -> [(t0, t1, fade_in, fade_out)]."""
    t0, t1 = cue["t0"], cue["t1"]
    cuts = sorted((max(s0, t0), min(s1, t1)) for s0, s1 in silent if s0 < t1 and s1 > t0)
    pieces, a = [], t0
    for s0, s1 in cuts + [(t1, t1)]:
        if s0 - a > 0.3:
            pieces.append((a, s0, MUSIC_FADE if a == t0 else GAP_FADE, MUSIC_FADE if s0 == t1 else GAP_FADE))
        a = s1
    return pieces


# ---------- audio: buses -> ducked mix -> gain + true-peak limit to -16 LUFS ----------
def mix_audio(shots, voices, voice_db, sfx, music, mixcfg, total, dst):
    ins, fl = [], []

    def inp(path):
        ins.extend(["-i", path])
        return len(ins) // 2 - 1

    def at(t):
        return "adelay=%d:all=1" % round(t * 1000)

    def amix(labels, out):
        fl.append("%samix=inputs=%d:normalize=0:duration=longest%s" % ("".join(labels), len(labels), out))

    amb = []
    for i, s in enumerate(shots):   # native ambience; crossfade XFADE where the cut says fade, else 10 ms de-click
        if not s["audio"]:
            continue
        L = min(s["frames"] / FPS + (XFADE if s["fade_out"] else 0), s["dur"])
        fi, fo = (XFADE if s["fade_in"] else 0.01), (XFADE if s["fade_out"] else 0.01)
        fl.append("[%d:a]%s,atrim=0:%.4f,asetpts=PTS-STARTPTS,afade=t=in:d=%.2f,afade=t=out:st=%.4f:d=%.2f,%s[amb%d]"
                  % (inp(s["path"]), FMT, L, fi, L - fo, fo, at(s["t0"]), i))
        amb.append("[amb%d]" % i)
    bed = []
    if amb:
        amix(amb, ",volume=%ddB[amb]" % AMBIENCE_DB)
        bed.append("[amb]")
    for m in music:   # stem time follows the cue; silence beats cut out of it
        for a, b, fi, fo in music_pieces(m, mixcfg.get("silent_spans", [])):
            L = b - a
            fi, fo = min(fi, L / 2), min(fo, L / 2)
            fl.append("[%d:a]%s,apad,atrim=%.3f:%.3f,asetpts=PTS-STARTPTS,afade=t=in:d=%.2f,afade=t=out:st=%.3f:d=%.2f,volume=%.3f,%s[mu%d]"
                      % (inp(m["path"]), FMT, a - m["t0"], b - m["t0"], fi, L - fo, fo, mixcfg["music_bed"], at(a), len(bed)))
            bed.append("[mu%d]" % len(bed))
    for j, v in enumerate(voices):
        fl.append("[%d:a]%s,%s[vo%d]" % (inp(v["path"]), FMT, at(v["t0"]), j))
    amix(["[vo%d]" % j for j in range(len(voices))], ",asplit=2[voice][key]")
    # sidechain: reduction ~ (level - threshold) * (1 - 1/ratio); threshold put so speech at its measured
    # mean level ducks the bed by duck_under_voice_db.  ponytail: one mean level for all lines, per-line if they differ a lot
    ratio = 20
    thr_db = voice_db + mixcfg["duck_under_voice_db"] / (1 - 1 / ratio)
    log("duck: speech %.1f dBFS -> threshold %.1f dBFS, ratio %d (~%d dB)" % (voice_db, thr_db, ratio, mixcfg["duck_under_voice_db"]))
    if bed:
        amix(bed, "[bed]")
        fl.append("[bed][key]sidechaincompress=threshold=%.5f:ratio=%d:attack=20:release=400:knee=2[ducked]" % (10 ** (thr_db / 20), ratio))
        final = ["[ducked]", "[voice]"]
    else:
        fl.append("[key]anullsink")
        final = ["[voice]"]
    for j, s in enumerate(sfx):
        fl.append("[%d:a]%s,%s[sx%d]" % (inp(s["path"]), FMT, at(s["t0"]), j))
        final.append("[sx%d]" % j)
    amix(final, ",apad=whole_dur=%.3f,atrim=0:%.3f[mix]" % (total, total))
    raw = dst + ".raw.wav"
    sh(["ffmpeg", "-y"] + ins + ["-filter_complex", ";".join(fl), "-map", "[mix]", "-c:a", "pcm_f32le", raw])

    normalize(raw, dst, mixcfg["lufs"])
    os.remove(raw)


def loudness(path):
    m = json.loads(re.search(r'\{\s*"input_i".*?\}', sh(["ffmpeg", "-i", path, "-af", "loudnorm=print_format=json",
                                                          "-f", "null", "-"]).stderr, re.S).group())
    return float(m["input_i"]), float(m["input_tp"]), float(m["input_lra"])


def normalize(src, dst, lufs):
    """linear gain to `lufs` + 4x-oversampled limiter at TP. Not loudnorm: with LRA or peaks over target it silently
    drops to dynamic mode and misses I by ~0.5 LU. Two passes: measure, then re-measure and correct what the limiter took."""
    i0, tp0, lra = loudness(src)
    log("pre-normalize: I=%.2f LUFS TP=%.2f dBTP LRA=%.1f" % (i0, tp0, lra))
    gain = lufs - i0
    for _ in range(3):
        sh(["ffmpeg", "-y", "-i", src, "-af", "volume=%.3fdB,aresample=%d,alimiter=limit=%.5f:level=false:attack=1:release=60,"
            "aresample=%d" % (gain, SR * 4, 10 ** (TP / 20), SR), "-c:a", "pcm_f32le", dst])
        i, tp, _ = loudness(dst)
        if abs(i - lufs) < 0.05:
            break
        gain += lufs - i
    log("normalized: gain %+.2f dB -> I=%.2f LUFS TP=%.2f dBTP" % (gain, i, tp))


# ---------- subtitles ----------
def ts(t, sep=","):
    ms = round(t * 1000)
    return "%02d:%02d:%02d%s%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, sep, ms % 1000)


def write_srt(lines, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, l in enumerate(lines, 1):
            f.write("%d\n%s --> %s\n%s\n\n" % (i, ts(l["t0"]), ts(l["t1"]), l["text"]))


def write_ass(lines, font, path):
    cs = lambda t: "%d:%02d:%05.2f" % (t // 3600, t // 60 % 60, t % 60)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
                "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Default,%s,54,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,1,2,70,70,240,1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" % (W, H, font))
        for l in lines:
            f.write("Dialogue: 0,%s,%s,Default,,0,0,0,,%s\n" % (cs(l["t0"]), cs(l["t1"]), l["text"].replace("\n", "\\N")))


def find_font():
    for pat, family in FONTS:
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            return hits[0], family
    raise SystemExit("no Devanagari font found (looked for %s)" % ", ".join(p for p, _ in FONTS))


# ---------- picture + mux ----------
def assemble(shots, mix, total, ass, work, dst):
    """trim each clip to its beat (+XFADE on 'fade' cuts, dissolved over the next clip's head), centre-crop to 9:16, scale."""
    ins, fl = [], []
    for i, s in enumerate(shots):
        ins += ["-i", s["path"]]
        n = s["frames"] + (frame(XFADE) if s["fade_out"] else 0)
        fl.append("[%d:v]trim=end_frame=%d,setpts=PTS-STARTPTS,fps=%d,settb=1/%d,setsar=1[v%d]" % (i, n, FPS, FPS, i))
    acc, length = "[v0]", shots[0]["frames"]
    for i in range(1, len(shots)):
        nxt = "[c%d]" % i
        if shots[i - 1]["fade_out"]:
            fl.append("%s[v%d]xfade=transition=fade:duration=%.3f:offset=%.4f%s" % (acc, i, XFADE, length / FPS, nxt))
        else:
            fl.append("%s[v%d]concat=n=2:v=1:a=0,settb=1/%d%s" % (acc, i, FPS, nxt))   # xfade needs equal timebases
        acc, length = nxt, length + shots[i]["frames"]
    fl.append("%scrop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=%d:%d:flags=lanczos,fps=%d,format=yuv420p,ass=%s:fontsdir=fonts[v]"
              % (acc, W, H, FPS, ass))
    sh(["ffmpeg", "-y"] + ins + ["-i", mix, "-filter_complex", ";".join(fl), "-map", "[v]", "-map", "%d:a" % len(shots),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-ac", "2", "-t", "%.3f" % total, "-movflags", "+faststart", dst],
       cwd=work)   # relative ass/fonts paths: no Windows drive-colon escaping inside the filtergraph


def main():
    ep = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("EP", "ep01")
    out = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "out", ep))
    src = episode(ep)["beats"]
    beats = [dict(b, t0=t0, t1=t1) for b, (t0, t1) in zip(src, timeline(src))]
    plan = json.load(open(plan_path(ep), encoding="utf-8")) if os.path.exists(plan_path(ep)) else write_plan(ep)
    total = beats[-1]["t1"]
    log("%s: %d shots, %.2fs, OUT=%s" % (ep, len(beats), total, out))
    shots = check_shots(out, beats)   # before spending any TTS calls
    font, family = find_font()

    voices, voice_db = build_voice(out, plan["voice"])
    sfx = build_sfx(out, plan["sfx"], {b["shot"]: (b["t0"], b["t1"]) for b in beats})
    music = pick_music(out, plan["music"])

    subs = plan["subs"]
    if not subs.get("en"):
        log("WARN plan has no English subs: final.en.srt is empty")
    write_srt(subs["hi"], os.path.join(out, "final.hi.srt"))
    write_srt(subs.get("en", []), os.path.join(out, "final.en.srt"))

    work = tempfile.mkdtemp(prefix="_work_", dir=out)
    os.makedirs(os.path.join(work, "fonts"))
    shutil.copy(font, os.path.join(work, "fonts"))
    write_ass(subs["hi"], family, os.path.join(work, "hi.ass"))
    mix = os.path.join(work, "mix.wav")
    mix_audio(shots, voices, voice_db, sfx, music, plan["mix"], total, mix)
    film = os.path.join(work, "final.mp4")
    assemble(shots, mix, total, "hi.ass", work, film)
    final = os.path.join(out, "final.mp4")
    os.replace(film, final)
    shutil.rmtree(work)
    log("FINAL %s %.3fs %d bytes (subs font: %s)" % (final, duration(final), os.path.getsize(final), family))


if __name__ == "__main__":
    main()

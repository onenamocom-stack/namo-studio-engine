#!/usr/bin/env python3
"""
namo_gpu.py - the GPU half of the factory. Runs on a RunPod pod that has the weight volume.
Reads  : show/<ep>/gpu_shot_manifest.json, show/<ep>/keyframes/*, cast/*.png
Writes : render/<ep>/shots/<SHOT>.mp4  +  shots/<SHOT>.json  +  SHA256SUMS
         render/<ep>/music/<THEME>_s<SEED>.wav
It never mixes, never narrates, never concatenates, never burns text.
"""
import hashlib, json, os, sys, time, copy, requests, boto3

C = "http://127.0.0.1:8188"
OUT = os.environ.get("OUT", "/workspace/out")

def s3():
    return boto3.client("s3", endpoint_url=os.environ["R2_EP"],
                        aws_access_key_id=os.environ["R2_AK"],
                        aws_secret_access_key=os.environ["R2_SK"], region_name="auto")

def load(ep):
    s = s3(); B = "namo-media"
    man = json.loads(s.get_object(Bucket=B, Key="show/%s/gpu_shot_manifest.json" % ep)["Body"].read())
    graphs = json.loads(s.get_object(Bucket=B, Key="config/render/graphs.json")["Body"].read())
    return man, graphs

def submit(graph):
    r = requests.post(C + "/prompt", json={"prompt": graph}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError("rejected: " + r.text[:600])
    pid = r.json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 2400:
        time.sleep(4)
        h = requests.get(C + "/history/" + pid, timeout=30).json()
        if pid in h:
            res = h[pid]
            if res.get("status", {}).get("status_str") != "success":
                raise RuntimeError("comfy failed: " + str(res.get("status"))[:400])
            return res["outputs"]
    raise RuntimeError("timeout on prompt " + pid)

def fetch_view(v, dst):
    with requests.get(C + "/view", params={"filename": v["filename"], "subfolder": v.get("subfolder", ""),
                                           "type": "output"}, stream=True, timeout=(20, 180)) as q:
        q.raise_for_status()
        with open(dst, "wb") as f:
            for b in q.iter_content(1 << 20):
                f.write(b)

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

def main():
    ep = os.environ.get("EP", "ep01")
    man, graphs = load(ep)
    s = s3()
    shot_dir = os.path.join(OUT, ep, "shots"); music_dir = os.path.join(OUT, ep, "music")
    os.makedirs(shot_dir, exist_ok=True); os.makedirs(music_dir, exist_ok=True)
    sums = []

    for sh in man["shots"]:
        gname = "J2_ref2va" if sh.get("ref2va") else man["graph_default"]
        g = copy.deepcopy(graphs[gname]["graph"])
        # keyframe into comfy input
        kf = os.path.basename(sh["keyframe"])
        requests.post(C + "/upload/image", files={"image": (kf, s.get_object(
            Bucket="namo-media", Key=sh["keyframe"])["Body"].read(), "image/png")}, timeout=180)
        for nid, node in g.items():
            if node["class_type"] == "MiniMaxH3ImageToVideo":
                node["inputs"]["image"] = kf
                node["inputs"]["length"] = sh["frames"]
                node["inputs"]["width"] = man["w"]; node["inputs"]["height"] = man["h"]
            if node["class_type"] == "RandomNoise":
                node["inputs"]["noise_seed"] = sh["seed"]
            if node["class_type"] == "MiniMaxH3ReferenceToVideo":
                node["inputs"]["length"] = sh["frames"]
                node["inputs"]["width"] = man["w"]; node["inputs"]["height"] = man["h"]
        t0 = time.time()
        outs = submit(g)
        # find the video output node
        vid = None
        for k, v in outs.items():
            cand = v.get("images") or v.get("videos") or []
            if cand:
                vid = cand[0]; break
        if not vid:
            raise RuntimeError("no video output for " + sh["shot"])
        dst = os.path.join(shot_dir, sh["shot"] + ".mp4")
        fetch_view(vid, dst)
        meta = {"shot": sh["shot"], "frames": sh["frames"], "fps": man["fps"],
                "seconds": sh["frames"] / man["fps"], "seed": sh["seed"], "graph": gname,
                "ref2va": sh.get("ref2va", False), "sec": round(time.time() - t0, 1)}
        json.dump(meta, open(os.path.join(shot_dir, sh["shot"] + ".json"), "w"), indent=1)
        sums.append(sha(dst) + "  " + sh["shot"] + ".mp4")
        print("SHOT", sh["shot"], meta["sec"], "s", os.path.getsize(dst), "B", flush=True)
        s.upload_file(dst, "namo-media", "render/%s/shots/%s.mp4" % (ep, sh["shot"]))   # ship as we go

    # music stems: several seeds per theme, CPU picks later
    music = json.loads(s.get_object(Bucket="namo-media", Key="show/%s/music.json" % ep)["Body"].read())
    mg = json.loads(s.get_object(Bucket="namo-media", Key="config/render/music_graph.json")["Body"].read())["graph"]
    for c in music["cues"]:
        if not c.get("gen"):
            continue
        for seed in c.get("seeds", [11, 22, 33]):
            g = copy.deepcopy(mg)
            for nid, node in g.items():
                if node["class_type"] == "RandomNoise":
                    node["inputs"]["noise_seed"] = seed
                if "TextEncode" in node["class_type"]:
                    node["inputs"]["text"] = c["intent"] + ", " + c["theme"]
            outs = submit(g)
            audio = None
            for k, v in outs.items():
                if v.get("audio"):
                    audio = v["audio"][0]; break
            if not audio:
                continue
            name = "%s_s%d.wav" % (c["theme"], seed)
            dst = os.path.join(music_dir, name)
            fetch_view(audio, dst)
            sums.append(sha(dst) + "  " + name)
            s.upload_file(dst, "namo-media", "render/%s/music/%s" % (ep, name))
            print("MUSIC", name, os.path.getsize(dst), "B", flush=True)

    open(os.path.join(OUT, ep, "SHA256SUMS"), "w").write("\n".join(sums) + "\n")
    s.upload_file(os.path.join(OUT, ep, "SHA256SUMS"), "namo-media", "render/%s/SHA256SUMS" % ep)
    print("GPU_DONE", len(sums), "artifacts")

if __name__ == "__main__":
    main()

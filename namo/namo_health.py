"""namo_health.py - one call that says whether the factory is alive. No opinions, only probes."""
import json, os, socket, sys, time
import requests

def port(host, p, timeout=3):
    try:
        s = socket.create_connection((host, p), timeout=timeout); s.close(); return True
    except Exception:
        return False

def http(url, key=None, timeout=6):
    try:
        h = {"Authorization": "Bearer " + key} if key else {}
        return requests.get(url, headers=h, timeout=timeout).status_code
    except Exception as e:
        return str(e)[:60]

def run(cfg_dir="/data/user/0/com.niki914.zafiro/files/.config"):
    def read(n):
        try: return open(os.path.join(cfg_dir, n)).read().strip()
        except Exception: return None
    key = None
    try:
        key = open("/data/user/0/com.niki914.zafiro/files/tool_output/_pkey").read().strip()
    except Exception: pass
    rp = read("runpod.key")
    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "probes": {}}
    out["probes"]["proxy_8322"] = http("http://127.0.0.1:8322/v1/models", key) if key else "no-key"
    out["probes"]["laya_8331"] = http("http://127.0.0.1:8331/health")
    for name, p in (("proxy_port", 8322), ("laya_port", 8331)):
        out["probes"][name] = port("127.0.0.1", p)
    if rp:
        try:
            hh = {"Authorization": "Bearer " + rp.strip()}
            vols = requests.get("https://rest.runpod.io/v1/networkvolumes", headers=hh, timeout=20).json()
            out["volumes"] = [{"id": v["id"], "size": v["size"], "dc": v["dataCenterId"]} for v in vols]
            pods = requests.get("https://rest.runpod.io/v1/pods", headers=hh, timeout=20).json()
            out["pods"] = [{"id": x["id"], "name": x.get("name"), "status": x.get("desiredStatus")} for x in pods]
        except Exception as e:
            out["runpod_error"] = str(e)[:80]
    # factory assets on disk
    base = "/data/user/0/com.niki914.zafiro/files/manufacture"
    kf = base + "/keyframes"
    out["keyframes"] = len([f for f in os.listdir(kf) if f.endswith(".png") and "_v" not in f]) if os.path.isdir(kf) else 0
    cast = base + "/cast"
    out["cast_sheets"] = len([f for f in os.listdir(cast) if f.endswith(".png")]) if os.path.isdir(cast) else 0
    out["ok"] = (out["probes"]["proxy_8322"] == 200 and out["probes"]["laya_8331"] == 200)
    return out

if __name__ == "__main__":
    print(json.dumps(run(), indent=1))

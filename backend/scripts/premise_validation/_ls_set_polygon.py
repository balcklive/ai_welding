"""临时：把 LS 项目4 的 label_config 改为 PolygonLabels(单类熔池)，回读验证。

服务器宿主运行（python3 + urllib，访问 127.0.0.1:8224）；key 从 .env 读，refresh→Bearer。
不回显 token。
"""

import json
import subprocess
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8224"
ENV = "/home/wwwroot/code/ai_welding/.env"

key = subprocess.check_output(
    "grep '^LABEL_STUDIO_API_KEY=' %s | cut -d= -f2-" % ENV, shell=True, text=True
).strip()
print("key_len:", len(key))

XML = (
    '<View><Image name="image" value="$image"/>'
    '<PolygonLabels name="label" toName="image">'
    '<Label value="熔池" background="#f032e6"/></PolygonLabels></View>'
)


def req(method, path, body=None, token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:  # noqa: BLE001
            return e.code, None


code, r = req("POST", "/api/token/refresh/", {"refresh": key})
access = r.get("access") if isinstance(r, dict) else None
print("refresh:", code, "| access_len:", len(access or ""))
if not access:
    raise SystemExit(1)

# 优先 label-config 端点，回退 project PATCH
attempts = [("PATCH", "/api/projects/4/label-config/", {"label_config": XML}),
            ("PATCH", "/api/projects/4/", {"label_config": XML})]
done = False
for method, path, body in attempts:
    code, r = req(method, path, body, access)
    print("%s %s -> %s %s" % (method, path, code, (r if isinstance(r, dict) else r)))
    if code in (200, 201):
        done = True
        break

if not done:
    print("PATCH failed on both paths; abort"); raise SystemExit(1)

code, r = req("GET", "/api/projects/4/", token=access)
lc = (r or {}).get("label_config", "") if isinstance(r, dict) else ""
print("verify PolygonLabels:", "<PolygonLabels" in lc)
print("verify BrushLabels removed:", "<BrushLabels" not in lc)
print("verify sample:", lc[:200])

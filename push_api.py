import os, sys, base64, json, time, urllib.request, urllib.error

TOKEN = open("/tmp/qf_worktok.txt").read().strip()
API = "https://api.github.com"
REPO = "/repos/sunxufeng/QuantFlow"
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
if PROXY:
    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.ProxyHandler({"https": PROXY, "http": PROXY}))
    )

REPO_ROOT = "/Users/sunxufeng/WorkBuddy/2026-08-12-14-19-17/quantflow"
BASE = "18fbbe8"
MESSAGE = "feat(v2.9): 因子研究增强——相关性矩阵热力图 + IC/IR 分析（前端因子库新增「研究」tab） (2.14.0)"


def api(method, path, data=None, retries=6):
    url = API + path
    body = json.dumps(data).encode() if data is not None else None
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=body, method=method)
            req.add_header("Authorization", "Bearer " + TOKEN)
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=60) as r:
                txt = r.read().decode()
                return json.loads(txt) if txt else {}
        except urllib.error.HTTPError as e:
            last = e.read().decode() if e.fp else str(e)
            if e.code in (409, 422):
                print("HTTP", e.code, last); raise
        except Exception as e:
            last = str(e)
        print(f"  retry {i+1} ({method} {path}): {last}")
        time.sleep(3)
    raise RuntimeError(f"api failed {method} {path}: {last}")


# 1) base ref
ref = api("GET", f"{REPO}/git/refs/heads/main")
base_sha = ref["object"]["sha"]
print("base_sha", base_sha)

# 2) base commit -> tree
base_commit = api("GET", f"{REPO}/git/commits/{base_sha}")
base_tree = base_commit["tree"]["sha"]

# 3) changed files (passed as args)
changed = sys.argv[1:]
print("changed files:", len(changed))

# 4) blobs
tree_items = []
for rel in changed:
    local = os.path.join(REPO_ROOT, rel)
    with open(local, "rb") as f:
        content = f.read()
    b = api("POST", f"{REPO}/git/blobs",
            {"content": base64.b64encode(content).decode(), "encoding": "base64"})
    tree_items.append({"path": rel, "mode": "100644", "type": "blob", "sha": b["sha"]})
    print("blob", rel, b["sha"][:8])

# 5) new tree (preserve other files via base_tree)
tree = api("POST", f"{REPO}/git/trees", {"base_tree": base_tree, "tree": tree_items})
print("tree", tree["sha"][:8])

# 6) commit
commit = api("POST", f"{REPO}/git/commits",
             {"message": MESSAGE, "tree": tree["sha"], "parents": [base_sha]})
print("commit", commit["sha"][:8])

# 7) PATCH ref
api("PATCH", f"{REPO}/git/refs/heads/main", {"sha": commit["sha"]})
print("PUSHED", commit["sha"])

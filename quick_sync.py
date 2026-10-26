import os, sys, json, base64, requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

token = os.environ.get("GITHUB_TOKEN", "")
if not token and sys.platform == "win32":
    try:
        import ctypes
        from ctypes import wintypes
        class CREDENTIAL(ctypes.Structure):
            _fields_ = [
                ('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
                ('Comment', wintypes.LPWSTR), ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                ('CredentialBlob', ctypes.POINTER(ctypes.c_char)), ('Persist', wintypes.DWORD),
                ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)
            ]
        advapi32 = ctypes.windll.advapi32
        cred_pointer = ctypes.POINTER(CREDENTIAL)()
        advapi32.CredReadW('git:https://github.com', 1, 0, ctypes.byref(cred_pointer))
        cred = cred_pointer.contents
        raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        try: token = raw.decode('utf-16le').strip('\x00')
        except Exception: token = raw.decode('utf-8').strip('\x00')
        if not token.startswith('gh'): token = raw.decode('utf-8', errors='ignore').strip('\x00')
    except Exception as e:
        print(f"Credential load warning: {e}")
        token = ""

REPO = "hironish100-gif/boatrace-ai"
PAGES_REPO = "hironish100-gif/boatrace-live"

headers = {
    "Authorization": f"token {token}",
    "Accept": "application/vnd.github.v3+json"
}

def get_file_sha(path_in_repo, target_repo=REPO):
    url = f"https://api.github.com/repos/{target_repo}/contents/{path_in_repo}"
    r = requests.get(url, headers=headers, timeout=10)
    if r.status_code == 200:
        return r.json().get("sha")
    return None

def git_sha1(content_bytes):
    import hashlib
    s = hashlib.sha1()
    s.update(f"blob {len(content_bytes)}\0".encode("utf-8"))
    s.update(content_bytes)
    return s.hexdigest()

def upload_file(local_path, repo_path, target_repo=REPO):
    if not os.path.exists(local_path):
        print(f"Skipping (not found): {local_path}")
        return False

    with open(local_path, "rb") as f:
        content_bytes = f.read()

    sha = get_file_sha(repo_path, target_repo=target_repo)
    if sha and git_sha1(content_bytes) == sha:
        return True

    b64_content = base64.b64encode(content_bytes).decode('utf-8')

    url = f"https://api.github.com/repos/{target_repo}/contents/{repo_path}"
    payload = {
        "message": f"Sync {repo_path} live data",
        "content": b64_content,
        "branch": "main"
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=headers, json=payload, timeout=30)
    if r.status_code in [200, 201]:
        print(f"[SUCCESS] Uploaded {repo_path} to {target_repo}")
        return True
    else:
        print(f"[ERROR] Failed to upload {repo_path} to {target_repo}: {r.status_code}")
        return False

def main():
    import glob

    # 1. all_days_data.json の生成（GitHub Pages での超高速API代用）
    try:
        from build_multiday_dashboard import build_multiday_json
        j_str = build_multiday_json()
        j_path = os.path.join(BASE_DIR, "all_days_data.json")
        with open(j_path, "w", encoding="utf-8") as fp:
            fp.write(j_str)
    except Exception as e_j:
        print(f"Error generating all_days_data.json: {e_j}")

    # 2. GitHub Pages 公開リポジトリへの配信 (Render不要の永久無料・スリープなし環境)
    print(">>> Syncing to GitHub Pages (boatrace-live)...")
    upload_file(os.path.join(BASE_DIR, "index.html"), "index.html", target_repo=PAGES_REPO)
    upload_file(os.path.join(BASE_DIR, "all_days_data.json"), "all_days_data.json", target_repo=PAGES_REPO)
    upload_file(os.path.join(BASE_DIR, "manifest.json"), "manifest.json", target_repo=PAGES_REPO)
    upload_file(os.path.join(BASE_DIR, "icon.svg"), "icon.svg", target_repo=PAGES_REPO)
    upload_file(os.path.join(BASE_DIR, "sw.js"), "sw.js", target_repo=PAGES_REPO)

    # 3. メインリポジトリ (boatrace-ai) への同期
    print(">>> Syncing to main repository (boatrace-ai)...")
    files = [
        "app.py",
        "index.html",
        "boatrace_dashboard.html",
        "all_days_data.json",
        ".github/workflows/boatrace_monitor.yml",
        "cloud_cron_runner.py",
        "build_multiday_dashboard.py",
        "build_dark_high_contrast_dashboard.py",
        "accumulated_learning_engine.py",
        "generate_edogawa_dynamic.py",
        "pipeline_edogawa_live.py",
        "universal_oriten_engine.py",
        "test_inject_results.py",
        "quick_sync.py",
        "send_live_wakamatsu_email.py",
        "gmail_error_watcher.py",
        "data/accumulated_learned_stats.json",
        "data/official_racer_course_stats.json",
        "data/racer_master_intelligence.json",
        "data/edogawa_20261012_data.json",
    ]
    for fp in sorted(glob.glob(os.path.join(BASE_DIR, "data", "*_2026101[3-9]_data.json")) + glob.glob(os.path.join(BASE_DIR, "data", "*_202610[23]*_data.json"))):
        rel_p = "data/" + os.path.basename(fp)
        if rel_p not in files:
            files.append(rel_p)
    for f in files:
        local_path = os.path.join(BASE_DIR, f)
        upload_file(local_path, f, target_repo=REPO)
    print("GitHub sync completed!")

if __name__ == "__main__":
    main()

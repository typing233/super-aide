"""GitHub：设备码登录、令牌保存、REST 和 Git Data API（社区共建用）。全程只用 api.github.com，不需要 git。

- 登录：OAuth 设备码（device flow）。超级助手显示一个 8 位码，你在浏览器打开 github.com/login/device 输入；
  只需要 client_id（公开的），不需要密钥。权限 public_repo（fork 主仓库、在你的 fork 上建分支、开 PR）。
- 令牌存在 Windows 凭据管理器里（当前用户才读得到）。装了 gh 并登录过的，直接用 gh auth token。
- 请求自动带上系统代理（urllib 在 Windows 上会读系统的代理设置）。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .. import __version__

log = logging.getLogger(__name__)

#: 维护者注册的 OAuth App "Super Aide"（打开了 Device Flow）。client_id 是公开的，可以放进开源代码
CLIENT_ID = "Ov23li0J2caMVSX6GTzM"
SCOPE = "public_repo"
API = "https://api.github.com"
DEVICE_CODE = "https://github.com/login/device/code"
ACCESS_TOKEN = "https://github.com/login/oauth/access_token"
CREDENTIAL = "SuperAide/github"
TIMEOUT = 30
NO_WINDOW = 0x08000000


class GitHubError(Exception):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


# ---------- 令牌 ----------

def saved_token() -> str:
    try:
        import win32cred

        cred = win32cred.CredRead(CREDENTIAL, win32cred.CRED_TYPE_GENERIC)
        blob = cred.get("CredentialBlob") or b""
        return blob.decode("utf-16-le") if isinstance(blob, bytes) else str(blob)
    except Exception:  # noqa: BLE001 - 没存过
        return ""


def save_token(token: str, login: str = "") -> None:
    import win32cred

    win32cred.CredWrite({"Type": win32cred.CRED_TYPE_GENERIC, "TargetName": CREDENTIAL, "UserName": login or "github",
                         "CredentialBlob": token, "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                         "Comment": "Super Aide community contributions"}, 0)


def forget_token() -> None:
    try:
        import win32cred

        win32cred.CredDelete(CREDENTIAL, win32cred.CRED_TYPE_GENERIC, 0)
    except Exception:  # noqa: BLE001
        pass


def gh_token() -> str:
    """装了 GitHub CLI 并登录过：直接用它的令牌（PATH 上的，或者便携版的默认位置）。"""
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    for exe in (shutil.which("gh"), local / "Programs" / "gh" / "bin" / "gh.exe"):
        if exe and Path(exe).exists():
            try:
                out = subprocess.run([str(exe), "auth", "token"], capture_output=True, text=True, timeout=15,
                                     creationflags=NO_WINDOW)
            except (OSError, subprocess.SubprocessError):
                continue
            token = out.stdout.strip()
            if out.returncode == 0 and token:
                return token
    return ""


def token() -> tuple[str, str]:
    """(令牌, 来源)：先用你在超级助手里登录的，再用 gh 的。都没有返回空。"""
    saved = saved_token()
    if saved:
        return saved, "app"
    from_gh = gh_token()
    return (from_gh, "gh") if from_gh else ("", "")


# ---------- 设备码登录 ----------

@dataclass
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    interval: int
    expires_at: float


def _form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode("ascii")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Accept": "application/json", "User-Agent": f"super-aide/{__version__}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def device_start() -> DeviceCode:
    data = _form(DEVICE_CODE, {"client_id": CLIENT_ID, "scope": SCOPE})
    if "device_code" not in data:
        raise GitHubError(data.get("error_description") or data.get("error") or "GitHub 没给设备码")
    return DeviceCode(data["device_code"], data["user_code"], data.get("verification_uri", "https://github.com/login/device"),
                      int(data.get("interval", 5)), time.time() + int(data.get("expires_in", 900)))


def device_poll(code: DeviceCode, sleep=time.sleep, cancelled=lambda: False) -> str:
    """等你在浏览器里输入设备码，返回令牌。过期、被拒绝、取消都抛 GitHubError。"""
    interval = code.interval
    while time.time() < code.expires_at:
        sleep(interval)
        if cancelled():
            raise GitHubError("已取消")
        data = _form(ACCESS_TOKEN, {"client_id": CLIENT_ID, "device_code": code.device_code,
                                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if data.get("access_token"):
            return data["access_token"]
        error = data.get("error", "")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval = int(data.get("interval", interval + 5))
            continue
        raise GitHubError(data.get("error_description") or error or "登录失败")
    raise GitHubError("设备码过期了，请重新登录")


# ---------- REST ----------

class GitHub:
    def __init__(self, token: str) -> None:
        self.token = token

    def request(self, method: str, path: str, data: dict | None = None, accept: str = "application/vnd.github+json",
                raw: bool = False):
        url = path if path.startswith("https://") else API + path
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Accept": accept, "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"super-aide/{__version__}", **({"Content-Type": "application/json"} if body else {})})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    content = resp.read()
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                if e.code >= 500 and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise GitHubError(f"GitHub {e.code}: {detail}", e.code) from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == 2:
                    raise GitHubError(f"连不上 GitHub：{getattr(e, 'reason', e)}") from e
                time.sleep(2 * (attempt + 1))
        if raw:
            return content.decode("utf-8", "replace")
        return json.loads(content) if content else {}

    def me(self) -> dict:
        return self.request("GET", "/user")

    def repo(self, repo: str) -> dict:
        return self.request("GET", f"/repos/{repo}")

    def can_push(self, repo: str) -> bool:
        return bool(self.repo(repo).get("permissions", {}).get("push"))

    def fork(self, repo: str, login: str) -> str:
        """fork 主仓库到你的账号（已经 fork 过就用那个），同步 main，返回 fork 的全名。"""
        name = repo.split("/", 1)[1]
        mine = f"{login}/{name}"
        try:
            info = self.repo(mine)
            if not info.get("fork"):
                raise GitHubError(f"你的账号下已经有一个叫 {name} 的仓库，但不是 {repo} 的 fork")
        except GitHubError as e:
            if e.status != 404:
                raise
            self.request("POST", f"/repos/{repo}/forks", {"default_branch_only": True})
            for _ in range(30):  # fork 是异步建的
                time.sleep(2)
                try:
                    self.repo(mine)
                    break
                except GitHubError as e2:
                    if e2.status != 404:
                        raise
        try:
            self.request("POST", f"/repos/{mine}/merge-upstream", {"branch": "main"})
        except GitHubError as e:
            log.info("同步 fork 失败（不影响提交，PR 基于主仓库的 main）：%s", e)
        return mine

    def head(self, repo: str, branch: str = "main") -> str:
        return self.request("GET", f"/repos/{repo}/git/ref/heads/{branch}")["object"]["sha"]

    def file_at(self, repo: str, path: str, ref: str) -> str | None:
        """主版本某个提交里的文件内容（文本）；不存在返回 None。"""
        try:
            data = self.request("GET", f"/repos/{repo}/contents/{urllib.parse.quote(path)}?ref={ref}")
        except GitHubError as e:
            if e.status == 404:
                return None
            raise
        if data.get("encoding") == "base64":
            return base64.b64decode(data.get("content", "")).decode("utf-8")
        return self.request("GET", data["download_url"], raw=True) if data.get("download_url") else None

    def commit_files(self, repo: str, base: str, files: dict[str, str | None], message: str, branch: str) -> str:
        """在 repo 上基于 base 建一个提交（files：路径 → 新内容，None 是删除），再建分支 branch 指向它。"""
        tree_base = self.request("GET", f"/repos/{repo}/git/commits/{base}")["tree"]["sha"]
        entries = []
        for path, content in sorted(files.items()):
            if content is None:
                entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
                continue
            blob = self.request("POST", f"/repos/{repo}/git/blobs",
                                {"content": base64.b64encode(content.encode("utf-8")).decode("ascii"), "encoding": "base64"})
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        tree = self.request("POST", f"/repos/{repo}/git/trees", {"base_tree": tree_base, "tree": entries})
        commit = self.request("POST", f"/repos/{repo}/git/commits", {"message": message, "tree": tree["sha"],
                                                                     "parents": [base]})
        self.request("POST", f"/repos/{repo}/git/refs", {"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
        return commit["sha"]

    def open_pr(self, repo: str, head: str, title: str, body: str) -> dict:
        return self.request("POST", f"/repos/{repo}/pulls", {"title": title, "head": head, "base": "main", "body": body,
                                                             "maintainer_can_modify": True})

    def find_pr(self, repo: str, marker: str) -> dict | None:
        """开着的 PR 里，说明中带这个标记（问题指纹）的那一个。"""
        q = urllib.parse.quote(f'repo:{repo} is:pr is:open "{marker}" in:body')
        items = self.request("GET", f"/search/issues?q={q}&per_page=5").get("items", [])
        return items[0] if items else None

    def plus_one(self, repo: str, number: int) -> None:
        self.request("POST", f"/repos/{repo}/issues/{number}/reactions", {"content": "+1"})

    def open_prs(self, repo: str) -> list[dict]:
        return self.request("GET", f"/repos/{repo}/pulls?state=open&per_page=50")

    def pr_diff(self, repo: str, number: int) -> str:
        return self.request("GET", f"/repos/{repo}/pulls/{number}", accept="application/vnd.github.diff", raw=True)

    def checks(self, repo: str, sha: str) -> str:
        """CI 的结果：passed / failed / pending / none。"""
        runs = self.request("GET", f"/repos/{repo}/commits/{sha}/check-runs?per_page=50").get("check_runs", [])
        if not runs:
            return "none"
        if any(r.get("status") != "completed" for r in runs):
            return "pending"
        bad = {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}
        return "failed" if any(r.get("conclusion") in bad for r in runs) else "passed"

    def merge(self, repo: str, number: int, title: str) -> None:
        self.request("PUT", f"/repos/{repo}/pulls/{number}/merge", {"merge_method": "squash", "commit_title": title})

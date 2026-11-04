"""
GitHub Automated Synchronization and Repository Management Module.
Automatically initializes Git, applies .gitignore filters for large ROMs,
creates remote GitHub repositories using the GitHub CLI (gh), and pushes updates.
"""

import os
import subprocess
import shutil
from pathlib import Path
from typing import Tuple, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_GITIGNORE = """# Custom ROM Flasher Agent Git Ignore
# Ignore large binary downloads, flashable images, and system platform-tools
downloads/
tools/platform-tools/
*.zip
*.img
*.bin
*.tar
*.md5
*.iso

# Logs and runtime caches
logs/
*.log
__pycache__/
*.py[cod]
*$py.class
.venv/
env/
.env

# OS metadata
.DS_Store
Thumbs.db
"""


class GitHubSync:
    """Manages Git and GitHub CLI automation for Custom ROM Agent."""

    def __init__(self, repo_dir: Optional[Path] = None):
        self.repo_dir = repo_dir or BASE_DIR
        self.git_bin = shutil.which("git") or "/usr/bin/git"
        self.gh_bin = shutil.which("gh") or "/home/alpesh/.local/bin/gh"

    def _run_cmd(self, cmd: list, timeout: int = 60) -> Tuple[int, str, str]:
        """Execute command inside repo directory."""
        try:
            res = subprocess.run(
                cmd,
                cwd=str(self.repo_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except Exception as e:
            return -1, "", str(e)

    def check_gh_auth(self) -> Dict[str, Any]:
        """Check if user is authenticated with GitHub CLI."""
        code, out, err = self._run_cmd([self.gh_bin, "auth", "status"])
        combined = f"{out} {err}"
        is_authenticated = "Logged in to github.com" in combined or code == 0
        username = "Unknown"
        for line in combined.splitlines():
            if "account" in line:
                parts = line.split("account")[-1].strip().split()
                if parts:
                    username = parts[0]
                    break

        return {
            "authenticated": is_authenticated,
            "username": username,
            "details": combined
        }

    def ensure_gitignore(self):
        """Ensure .gitignore exists to prevent committing huge ROM archives."""
        gitignore_path = self.repo_dir / ".gitignore"
        if not gitignore_path.exists():
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write(DEFAULT_GITIGNORE)

    def auto_sync_to_github(
        self,
        repo_name: str = "Android-Custom-ROM-Flasher-Agent",
        commit_message: str = "feat: initial commit for custom rom flasher agent",
        is_private: bool = False
    ) -> Tuple[bool, str]:
        """
        Full automated pipeline:
        1. Initialize git if needed
        2. Ensure .gitignore
        3. Stage & Commit
        4. Create GitHub repo if needed via gh
        5. Push to GitHub
        """
        # Step 1: Ensure .gitignore
        self.ensure_gitignore()

        # Step 2: Check / Init git
        git_dir = self.repo_dir / ".git"
        if not git_dir.exists():
            code, out, err = self._run_cmd([self.git_bin, "init", "-b", "main"])
            if code != 0:
                return False, f"Failed to initialize git repository: {err}"

        # Step 3: Check auth
        auth_info = self.check_gh_auth()
        if not auth_info["authenticated"]:
            return False, "GitHub CLI (gh) is not authenticated. Please run 'gh auth login' or connect account."

        # Step 4: Stage files
        self._run_cmd([self.git_bin, "add", "."])

        # Step 5: Commit if there are changes
        code_diff, _, _ = self._run_cmd([self.git_bin, "diff", "--staged", "--quiet"])
        if code_diff != 0:
            # Staged changes exist
            code_c, out_c, err_c = self._run_cmd([self.git_bin, "commit", "-m", commit_message])
            if code_c != 0 and "nothing to commit" not in err_c:
                return False, f"Failed to commit changes: {err_c}"

        # Step 6: Check remote origin
        code_rem, out_rem, _ = self._run_cmd([self.git_bin, "remote", "get-url", "origin"])

        if code_rem != 0:
            # Remote does not exist: create repository using GitHub CLI
            visibility_flag = "--private" if is_private else "--public"
            code_gh, out_gh, err_gh = self._run_cmd([
                self.gh_bin, "repo", "create", repo_name,
                visibility_flag,
                "--source=.",
                "--remote=origin",
                "--push"
            ], timeout=90)

            if code_gh == 0:
                return True, f"GitHub repository '{repo_name}' created and code pushed successfully! URL: https://github.com/{auth_info['username']}/{repo_name}"
            else:
                # If repository already exists on GitHub under user account, attach it
                if "already exists" in f"{out_gh} {err_gh}".lower():
                    repo_url = f"https://github.com/{auth_info['username']}/{repo_name}.git"
                    self._run_cmd([self.git_bin, "remote", "add", "origin", repo_url])
                    code_push, _, err_push = self._run_cmd([self.git_bin, "push", "-u", "origin", "main"])
                    if code_push == 0:
                        return True, f"Existing GitHub repo connected and updated! URL: https://github.com/{auth_info['username']}/{repo_name}"
                    return False, f"Remote created but push failed: {err_push}"

                return False, f"GitHub repo creation failed: {err_gh or out_gh}"
        else:
            # Remote origin exists: simply push updates
            code_p, out_p, err_p = self._run_cmd([self.git_bin, "push", "-u", "origin", "main"])
            if code_p == 0:
                return True, f"Code successfully synchronized and pushed to GitHub ({out_rem})!"
            return False, f"Git push failed: {err_p}"

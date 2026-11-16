import tarfile
from pathlib import Path

ROOT = Path("/home/user/.doubao/agent_mode/workspace/.sessions/38452724256755714/agents/m_0cweEuPu7Xj/work_src")
OUT = Path("/home/user/.doubao/agent_mode/workspace/.sessions/38452724256755714/agents/m_0cweEuPu7Xj/deploy_rectify.tgz")

EXCLUDE_DIR_PARTS = {"__pycache__", ".git", "certs", "toolout"}
EXCLUDE_PREFIX = [
    "ai_new/modules/agent_common/config/data/config.json",
    "ai_new/modules/agent_common/config/data/config.yaml",
    "ai_new/modules/agent/auth/data/sessions/",
    "ai_new/modules/agent/sessions/data/sessions/",
    "ai_new/modules/agent/tickets/data/tickets/",
    "ai_new/modules/agent/projects/data/",
    "ai_new/modules/agent/artifacts/data/",
    "ai_new/modules/agent/channel/data/channels/",
    "ai_new/modules/agent_common/ops/data/",
    "ai_new/modules/agent/knowledge/data/",
]

def excluded(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    if rel.endswith(".pyc") or rel.endswith(".log"):
        return True
    parts = rel.split("/")
    if any(p in EXCLUDE_DIR_PARTS for p in parts):
        return True
    for pre in EXCLUDE_PREFIX:
        if rel == pre.rstrip("/") or rel.startswith(pre):
            return True
    return False

members = []
for f in ROOT.rglob("*"):
    if not f.is_file():
        continue
    rel = str(f.relative_to(ROOT))
    if excluded(rel):
        continue
    members.append((f, rel))

with tarfile.open(OUT, "w:gz") as tar:
    for f, rel in members:
        tar.add(f, arcname=rel)

print("packed", len(members), "files ->", OUT.name)
for _, rel in sorted(members):
    print(" ", rel)

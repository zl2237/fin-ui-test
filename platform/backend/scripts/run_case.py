"""执行用例并轮询结果（平台 API 版调试入口，参数=用例 ID 列表）。"""
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")
os.environ.setdefault("DB_PASSWORD", "x")

BASE = "http://127.0.0.1:8000"


def get_token() -> str:
    from app.database import SessionLocal
    from app import models
    from app.auth import create_token

    db = SessionLocal()
    u = db.query(models.User).filter(models.User.id == 1).first()
    tok = create_token(u.id, u.username, u.role)
    db.close()
    return tok


def main() -> None:
    token = get_token()
    h = {"Authorization": "Bearer " + token}
    for cid in [int(x) for x in sys.argv[1:]]:
        r = requests.post(f"{BASE}/api/testcases/{cid}/execute",
                          json={"case_id": cid}, headers=h, timeout=30)
        r.raise_for_status()
        eid = r.json().get("id")
        print(f"case {cid} execution={eid} started", flush=True)
        for _ in range(150):
            time.sleep(5)
            d = requests.get(f"{BASE}/api/executions/{eid}", headers=h).json()
            if d.get("status") in ("success", "failed", "error"):
                print(f"case {cid} => {d['status']} summary={d.get('summary')}", flush=True)
                break
        else:
            print(f"case {cid} => TIMEOUT", flush=True)


if __name__ == "__main__":
    main()

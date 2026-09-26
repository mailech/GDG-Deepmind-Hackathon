"""Print what Nova currently remembers. Run it on camera to prove persistence.

uv run python src/show_memory.py
"""

import asyncio
import json
import os
import re
import sys

import asyncpg
from dotenv import load_dotenv

load_dotenv(".env.local")


async def main() -> None:
    dsn = re.sub(r"[?&](sslmode|channel_binding)=[^&]*", "", os.environ["DATABASE_URL"])
    conn = await asyncpg.connect(dsn, ssl="require")
    rows = await conn.fetch(
        "SELECT user_id, name, language_preference, facts, last_interaction "
        "FROM students ORDER BY last_interaction DESC"
    )
    await conn.close()

    host = os.environ["DATABASE_URL"].split("@")[-1].split("/")[0]
    print()
    print("=" * 62)
    print("  NOVA'S MEMORY  ·  Neon Postgres")
    print(f"  {host}")
    print("=" * 62)

    if not rows:
        print("\n  (empty — nobody stored yet)\n")
        return

    for r in rows:
        facts = r["facts"]
        facts = json.loads(facts) if isinstance(facts, str) else dict(facts or {})
        print(f"\n  NAME         {r['name']}")
        print(f"  user_id      {r['user_id']}")
        print(f"  language     {r['language_preference'] or '-'}")
        print(f"  last seen    {r['last_interaction']:%Y-%m-%d %H:%M:%S} UTC")
        print("  ---- what Nova remembers " + "-" * 30)
        if not facts:
            print("    (nothing yet)")
        for key, value in facts.items():
            if isinstance(value, list):
                print(f"    {key}:")
                for item in value:
                    print(f"        - {item}")
            else:
                print(f"    {key}: {value}")

    print(f"\n{'=' * 62}")
    print(f"  {len(rows)} student(s) stored\n")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())

"""
诊断脚本：直接检查 Chroma 数据库中实际存储的记忆内容。
"""
import os
os.environ["ANONYMIZED_TELEMETRY"] = "false"
os.environ["CHROMA_TELEMETRY_DISABLED"] = "true"

import chromadb
from chromadb.config import Settings

# posthog 7.x 与 chromadb 0.6.x 接口不兼容，禁用遥测
import chromadb.telemetry.product.posthog as _posthog_module
_posthog_module.posthog.capture = lambda *args, **kwargs: None

CHROMA_DATA_DIR = "./data/chroma"
SESSION_ID = "cfe32fea-8c30-449c-8486-f26149ecfb82"

client = chromadb.PersistentClient(
    path=CHROMA_DATA_DIR,
    settings=Settings(anonymized_telemetry=False, allow_reset=True),
)

# 列出所有 collection
print("=== Collections ===")
for name in client.list_collections():
    print(f"  - {name}")

# 检查 gitintel_memory collection
print(f"\n=== gitintel_memory 内容 (session={SESSION_ID}) ===")
try:
    col = client.get_collection("gitintel_memory")
    all_docs = col.get(limit=1000)

    if not all_docs or not all_docs.get("ids"):
        print("  (collection 为空)")
    else:
        print(f"  总文档数: {len(all_docs['ids'])}")
        print()
        for i in range(len(all_docs["ids"])):
            metadata = all_docs["metadatas"][i] or {}
            sid = metadata.get("session_id", "N/A")
            doc_type = metadata.get("doc_type", "N/A")
            user_msg = metadata.get("user_message", "")
            assistant_msg = metadata.get("assistant_message", "")
            timestamp = metadata.get("timestamp", 0)
            content = all_docs.get("documents", [None] * len(all_docs["ids"]))[i]

            print(f"  [{i+1}] id={all_docs['ids'][i]}")
            print(f"      session_id={sid}, doc_type={doc_type}, timestamp={timestamp}")
            print(f"      user_message={repr(user_msg[:80])}")
            print(f"      assistant_message={repr(assistant_msg[:80])}")
            print(f"      content={repr((content or '')[:100])}")
            print()
except Exception as e:
    print(f"  错误: {e}")

# 检查 gitintel_knowledge collection
print("\n=== gitintel_knowledge 内容 (前3条) ===")
try:
    col = client.get_collection("gitintel_knowledge")
    all_docs = col.get(limit=1000)
    if not all_docs or not all_docs.get("ids"):
        print("  (collection 为空)")
    else:
        print(f"  总文档数: {len(all_docs['ids'])}")
        for i in range(min(3, len(all_docs["ids"]))):
            metadata = all_docs["metadatas"][i] or {}
            content = all_docs.get("documents", [None] * len(all_docs["ids"]))[i]
            print(f"  [{i+1}] title={metadata.get('title','')}, category={metadata.get('category','')}")
            print(f"      content={repr((content or '')[:100])}")
except Exception as e:
    print(f"  错误: {e}")

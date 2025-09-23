import chromadb
from chromadb.config import Settings
from pprint import pprint

persist_dir = r"C:\Users\impark-eray\Desktop\impark\dijidemi-chatbot\chroma_db"
client = chromadb.PersistentClient(path=persist_dir, settings=Settings())

collections = client.list_collections()
for coll in collections:
    print(f"\n=== Collection: {coll.name} ===")
    try:
        collection = client.get_collection(coll.name)
    except Exception as exc:
        print(f"  Unable to open collection: {exc}")
        continue

    peek = collection.peek(limit=3)  # küçük bir örnek
    metadatas = peek.get("metadatas", [])
    ids = peek.get("ids", [])

    if not metadatas:
        print("  (no documents or metadata found)")
        continue

    for idx, metadata in zip(ids, metadatas):
        print(f"  id={idx}")
        pprint(metadata)

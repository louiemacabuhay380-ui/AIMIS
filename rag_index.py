"""Rebuild the chatbot knowledge base for every scored interview.
Run once after setting up Ollama, or after changing OLLAMA_EMBED_MODEL:
    python rag_index.py
(New interviews are added automatically after they are scored.)"""
from app import get_db, load_report
import rag

status = rag.ollama_status()
if not status["running"]:
    print("Ollama is not running, so chunks will be saved without embeddings (keyword search only).")
elif not status.get("has_embed_model"):
    print(f"The embedding model is missing. Run:  ollama pull {status['embed_model']}")

conn = get_db()
cursor = conn.cursor(dictionary=True)
cursor.execute("""SELECT i.interview_id FROM interviews i
                  JOIN evaluations e ON e.interview_id = i.interview_id ORDER BY i.interview_id""")
ids = [row["interview_id"] for row in cursor.fetchall()]
total = 0
for n, interview_id in enumerate(ids, start=1):
    total += rag.index_interview(conn, interview_id, load_report)
    print(f"{n}/{len(ids)} interviews indexed", end="\r")
conn.close()
print(f"\nDone: {total} chunks from {len(ids)} interviews.")

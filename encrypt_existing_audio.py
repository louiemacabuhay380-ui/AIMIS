"""One-time script: encrypts old .wav recordings and updates their paths in the database."""
import os
from dotenv import load_dotenv
import db
from cryptography.fernet import Fernet

load_dotenv()
fernet = Fernet(os.getenv("AUDIO_ENCRYPTION_KEY").encode())
audio_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads", "audio")

conn = db.get_db()
cursor = conn.cursor()

for name in os.listdir(audio_dir):
    if not name.endswith(".wav"):
        continue
    path = os.path.join(audio_dir, name)
    with open(path, "rb") as f:
        data = f.read()
    with open(path + ".enc", "wb") as f:
        f.write(fernet.encrypt(data))
    cursor.execute("UPDATE responses SET audio_path = %s WHERE audio_path = %s",
                   (f"uploads/audio/{name}.enc", f"uploads/audio/{name}"))
    conn.commit()
    os.remove(path)
    print("Encrypted", name)

conn.close()
print("Done.")
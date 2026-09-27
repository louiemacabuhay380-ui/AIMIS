"""One-time script: encrypts old .wav recordings and updates their paths in the database."""
import os
from dotenv import load_dotenv
import mysql.connector
from cryptography.fernet import Fernet

load_dotenv()
fernet = Fernet(os.getenv("AUDIO_ENCRYPTION_KEY").encode())
audio_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads", "audio")

conn = mysql.connector.connect(
    host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME"))
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
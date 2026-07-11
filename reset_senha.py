"""Redefine a senha do admin diretamente no banco.

Uso (na VPS, com o volume de dados montado):

    ADMIN_PASSWORD="nova-senha" python reset_senha.py

Lê DATA_DIR/royal.db e atualiza o hash da senha na tabela users.
"""
import os
import sqlite3
import sys

from werkzeug.security import generate_password_hash

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "royal.db")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

if not ADMIN_PASSWORD:
    print("Erro: defina ADMIN_PASSWORD antes de rodar este script.")
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)
try:
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (generate_password_hash(ADMIN_PASSWORD), ADMIN_USERNAME),
    )
    conn.commit()
finally:
    conn.close()

print(DB_PATH)
print("Senha atualizada com sucesso.")

"""Configuração inicial da loja — roda no boot, antes do gunicorn.

Sincroniza as variáveis de ambiente para o `site_config` e garante a senha do
admin. Pensado para o primeiro deploy de uma loja nova: com as env vars
setadas, a loja já sobe 100% configurada, sem precisar rodar comandos manuais
no console.

Importante (para NÃO sobrescrever o que o dono edita pelo painel):
  - As env vars só são aplicadas UMA vez, no primeiríssimo boot da loja
    (banco novo). Depois disso, uma flag `env_config_seeded` fica gravada no
    banco e este script não toca mais em nenhuma configuração — mesmo que as
    env vars continuem setadas em cada redeploy.
  - Motivo: em hosts que refazem o boot a cada commit (ex: Vapor/Heroku), este
    script rodava de novo a cada deploy e reescrevia valores como o telefone
    do WhatsApp por cima das edições feitas no painel. A flag corta isso: o
    banco passa a ser a fonte da verdade assim que a loja é semeada.
  - A senha do admin também só é (re)definida via ADMIN_PASSWORD nesse primeiro
    boot. Para trocar a senha depois, use o painel ou o `reset_senha.py`.

Importar o `app` aqui é proposital: isso dispara o init_db() dele, garantindo
que o schema exista mesmo num volume de dados vazio (primeiro boot), e faz com
que usemos exatamente o mesmo caminho de banco (DB_PATH) que a aplicação usa.
"""
import os
import sqlite3

import app as royal_app
from werkzeug.security import generate_password_hash

DB_PATH = royal_app.DB_PATH
ADMIN_USERNAME = royal_app.ADMIN_USERNAME

# Cada chave do site_config e a env var que a alimenta.
CONFIG_ENV_MAP = {
    "store_name": "STORE_NAME",
    "store_city": "STORE_CITY",
    "theme_primary_color": "THEME_PRIMARY_COLOR",
    "whatsapp_phone": "WHATSAPP_PHONE",
    "instagram_url": "INSTAGRAM_URL",
    "favicon_url": "FAVICON_URL",
    "meta_description": "META_DESCRIPTION",
    "meta_keywords": "META_KEYWORDS",
}


def main():
    conn = sqlite3.connect(DB_PATH)
    applied = []
    skipped = []
    admin_password_set = False
    try:
        # Só semeia a partir das env vars UMA vez (primeiro boot da loja). Depois
        # disso o banco é a fonte da verdade: em hosts que refazem o boot a cada
        # commit (Vapor/Heroku), rodar isto de novo reescreveria valores editados
        # no painel (ex: o telefone do WhatsApp) por cima. A flag corta isso.
        already_seeded = conn.execute(
            "SELECT 1 FROM site_config WHERE key = 'env_config_seeded'"
        ).fetchone() is not None

        if already_seeded:
            print("=== setup_loja: configuracao inicial ===")
            print(f"Banco: {DB_PATH}")
            print(
                "Loja ja semeada anteriormente (flag 'env_config_seeded' presente): "
                "env vars ignoradas, valores do banco/painel preservados."
            )
            print("Loja pronta.")
            return

        for key, env_name in CONFIG_ENV_MAP.items():
            raw = os.environ.get(env_name)
            if raw is None or raw.strip() == "":
                # Env var ausente/vazia -> preserva o valor atual do banco.
                skipped.append(key)
                continue
            value = raw.strip()
            if key == "whatsapp_phone":
                # O link wa.me só aceita dígitos (país + DDD + número).
                value = "".join(ch for ch in value if ch.isdigit())
            # Mesmo padrão de upsert usado pela aplicação (app.py).
            conn.execute(
                "INSERT INTO site_config (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            applied.append((key, value))

        # Senha do admin: só redefine se ADMIN_PASSWORD estiver setada (não
        # derruba o boot se estiver ausente — o init_db já criou o admin).
        admin_password = os.environ.get("ADMIN_PASSWORD", "").strip()
        admin_password_set = bool(admin_password)
        if admin_password_set:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (generate_password_hash(admin_password), ADMIN_USERNAME),
            )

        # Marca a loja como semeada: os próximos boots/deploys não mexem mais
        # em nada e o painel passa a mandar sozinho.
        conn.execute(
            "INSERT OR IGNORE INTO site_config (key, value) VALUES ('env_config_seeded', '1')"
        )

        conn.commit()
    finally:
        conn.close()

    print("=== setup_loja: configuracao inicial (primeiro boot) ===")
    print(f"Banco: {DB_PATH}")
    if applied:
        print("Configuracoes aplicadas a partir das env vars:")
        for key, value in applied:
            shown = value if len(value) <= 60 else value[:57] + "..."
            print(f"  - {key} = {shown}")
    else:
        print("Nenhuma env var de configuracao definida (valores atuais preservados).")
    if skipped:
        print("Preservados (env var ausente/vazia): " + ", ".join(skipped))
    print(
        "Senha do admin: "
        + (
            f"redefinida via ADMIN_PASSWORD (usuario '{ADMIN_USERNAME}')."
            if admin_password_set
            else "mantida (ADMIN_PASSWORD nao definida)."
        )
    )
    print("Loja pronta.")


if __name__ == "__main__":
    main()

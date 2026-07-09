#!/bin/bash
# Backup diário do banco (royal.db) e das imagens enviadas pelo admin
# (uploads/). Rodado automaticamente pelo timer royal-backup.timer
# (via royal-backup.service) — ver instruções em GUIA_DEPLOY_VPS.md.
#
# Sem isso, uma exclusão em massa pelo painel admin (ex: apagar uma marca,
# que apaga em cascata todos os modelos/sabores dela) ou uma alteração
# maliciosa não têm como ser desfeitas.
set -euo pipefail

APP_DIR="/var/www/royal"
BACKUP_DIR="/var/backups/royal"
RETENTION_DAYS=14
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_DIR/$STAMP"

mkdir -p "$DEST"
cp "$APP_DIR/royal.db" "$DEST/royal.db"
tar -czf "$DEST/uploads.tar.gz" -C "$APP_DIR" uploads

# Apaga backups mais velhos que RETENTION_DAYS dias.
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -mtime "+$RETENTION_DAYS" -exec rm -rf {} \;

echo "Backup salvo em $DEST"

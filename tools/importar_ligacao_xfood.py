"""Importa a ligação sabor do site <-> código do xFood para o banco de UMA loja.

Cada loja (Royal, Vapor, Pods Ilha) tem o próprio banco e ids de sabor
próprios, então rode uma vez por banco, com o CSV daquela loja:

    python tools/importar_ligacao_xfood.py /dados/royal.db tools/ligacao_aprovada_vapor.csv
    python tools/importar_ligacao_xfood.py /dados/royal.db tools/ligacao_aprovada_vapor.csv --aplicar

Sem --aplicar só SIMULA e mostra o que faria. Com --aplicar:
  - faz backup do .db (royal.db.bak-xfood-AAAAMMDD-HHMMSS) antes de gravar;
  - grava tudo numa transação só.

Pode rodar várias vezes: par que já existe é ignorado. Recusa (e lista):
  - sabor_id que não existe no banco;
  - código já ligado a OUTRO sabor (no banco ou repetido no próprio CSV).

Trava de segurança: se o nome do CSV for ligacao_aprovada_<loja>.csv e o
banco for de outra loja (site_config.store_name), recusa — a não ser com
--ignorar-loja. Os ids de sabor são diferentes em cada banco.

Não importa nada do app Flask: usa só sqlite3. A tabela é criada aqui com o
mesmo DDL do init_db do app.py, caso o app ainda não tenha subido com ela.
"""

import argparse
import csv
import os
import re
import sqlite3
import sys
from datetime import datetime

DDL = """
CREATE TABLE IF NOT EXISTS product_xfood_codes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id   INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    xfood_codigo TEXT NOT NULL UNIQUE,
    criado_em    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pxc_product ON product_xfood_codes(product_id);
"""

# loja do nome do CSV -> trecho esperado em site_config.store_name
LOJA_NOME = {"vapor": "VAPOR", "royal": "ROYAL", "podsilha": "PODS ILHA"}


def ler_csv(caminho):
    pares, erros = [], []
    with open(caminho, encoding="utf-8-sig") as f:
        for n, r in enumerate(csv.DictReader(f, delimiter=";"), start=2):
            sid = (r.get("site_sabor_id") or "").strip()
            cod = (r.get("xfood_codigo") or "").strip()
            if not sid.isdigit() or not cod:
                erros.append(f"linha {n}: inválida ({sid!r}; {cod!r})")
                continue
            pares.append((int(sid), cod))
    return pares, erros


def checar_loja(db, caminho_csv, ignorar):
    nome = (db.execute("SELECT value FROM site_config WHERE key = 'store_name'").fetchone() or [""])[0] or ""
    m = re.match(r"ligacao_aprovada_(\w+)\.csv$", os.path.basename(caminho_csv), re.I)
    print(f"Banco da loja: {nome or '(sem store_name)'}")
    if m and m.group(1).lower() in LOJA_NOME:
        esperado = LOJA_NOME[m.group(1).lower()]
        if esperado not in nome.upper():
            msg = f"O CSV é da loja '{m.group(1)}', mas o banco é de '{nome}'."
            if not ignorar:
                sys.exit(msg + " Nada foi feito. (Use --ignorar-loja se tiver certeza.)")
            print("AVISO: " + msg)


def tabela_existe(db):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='product_xfood_codes'"
    ).fetchone() is not None


def sabores_ativos_sem_codigo(db, ligados):
    """Sabores de modelos ativos (e com o modelo principal ativo, no caso de
    versão) que não têm nenhum código. `ligados` = product_ids com código."""
    rows = db.execute(
        """
        SELECT p.id, p.name, m.name AS modelo
        FROM products p
        JOIN vape_models m ON m.id = p.model_id
        LEFT JOIN vape_models pai ON pai.id = m.parent_id
        WHERE m.active = 1 AND COALESCE(pai.active, 1) = 1
        ORDER BY m.name, p.id
        """
    ).fetchall()
    return [r for r in rows if r[0] not in ligados]


def backup(caminho_db):
    destino = f"{caminho_db}.bak-xfood-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    origem = sqlite3.connect(caminho_db)
    copia = sqlite3.connect(destino)
    with copia:
        origem.backup(copia)   # cópia consistente mesmo com o app rodando
    copia.close()
    origem.close()
    return destino


def main():
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("banco", help="caminho do royal.db da loja")
    ap.add_argument("csv", help="ligacao_aprovada_<loja>.csv (site_sabor_id;xfood_codigo)")
    ap.add_argument("--aplicar", action="store_true", help="grava de verdade (sem isto só simula)")
    ap.add_argument("--ignorar-loja", action="store_true", help="não confere se o CSV é desta loja")
    args = ap.parse_args()

    if not os.path.isfile(args.banco):
        sys.exit(f"Banco não encontrado: {args.banco}")

    pares, invalidas = ler_csv(args.csv)
    db = sqlite3.connect(args.banco)
    db.execute("PRAGMA foreign_keys = ON")
    checar_loja(db, args.csv, args.ignorar_loja)

    sabores = {r[0]: (r[1], r[2]) for r in db.execute(
        "SELECT p.id, p.name, m.name FROM products p JOIN vape_models m ON m.id = p.model_id")}
    dono = {}   # código -> product_id já gravado
    if tabela_existe(db):
        dono = dict(db.execute("SELECT xfood_codigo, product_id FROM product_xfood_codes"))

    novos, ja_existiam, sem_sabor, conflito = [], [], [], []
    planejado = dict(dono)
    for sid, cod in pares:
        if sid not in sabores:
            sem_sabor.append((sid, cod))
        elif cod in planejado and planejado[cod] != sid:
            outro = planejado[cod]
            conflito.append((sid, cod, outro))
        elif cod in planejado:
            ja_existiam.append((sid, cod))
        else:
            planejado[cod] = sid
            novos.append((sid, cod))

    def nome(sid):
        s = sabores.get(sid)
        return f"[{s[1]}] {s[0]}" if s else "(não existe)"

    modo = "APLICANDO" if args.aplicar else "SIMULAÇÃO (nada gravado; use --aplicar)"
    print(f"\n{modo}\nBanco: {args.banco}\nCSV:   {args.csv} ({len(pares)} pares)\n")
    print(f"  novos a gravar         : {len(novos)}")
    print(f"  já existiam (ignorados): {len(ja_existiam)}")
    print(f"  RECUSADOS sabor_id inexistente : {len(sem_sabor)}")
    print(f"  RECUSADOS código de outro sabor: {len(conflito)}")
    print(f"  linhas inválidas no CSV        : {len(invalidas)}")
    for linha in invalidas:
        print(f"    {linha}")
    for sid, cod in sem_sabor:
        print(f"    sabor_id {sid} não existe (código {cod})")
    for sid, cod, outro in conflito:
        print(f"    código {cod} pedido para {sid} {nome(sid)}, mas já é de {outro} {nome(outro)}")

    por_sabor = {}
    for cod, sid in planejado.items():
        por_sabor.setdefault(sid, []).append(cod)
    print(f"\nDepois da importação: {len(por_sabor)} sabores ligados, {len(planejado)} códigos")
    multi = {s: c for s, c in por_sabor.items() if len(c) > 1}
    for sid, cods in sorted(multi.items()):
        print(f"  {sid} {nome(sid)}: {', '.join(sorted(cods))}")
    faltando = sabores_ativos_sem_codigo(db, set(por_sabor))
    print(f"Sabores ATIVOS sem código xFood: {len(faltando)}")
    for sid, sabor, modelo in faltando[:50]:
        print(f"  {sid} [{modelo}] {sabor}")
    if len(faltando) > 50:
        print(f"  ... e mais {len(faltando) - 50}")

    if not args.aplicar:
        return
    if not novos:
        print("\nNada novo para gravar.")
        return
    destino = backup(args.banco)
    print(f"\nBackup: {destino}")
    with db:
        db.executescript(DDL)
        db.executemany(
            "INSERT INTO product_xfood_codes (product_id, xfood_codigo) VALUES (?, ?)", novos
        )
    print(f"Gravados {len(novos)} códigos.")


if __name__ == "__main__":
    main()

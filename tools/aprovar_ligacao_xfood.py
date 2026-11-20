"""Gera ligacao_aprovada_<loja>.csv a partir das sugestões de cada loja.

Lê <pasta>/<loja>/ligacao_sugerida.csv (saída do sugerir_ligacao_xfood.py,
uma subpasta por loja) e aplica as decisões do dono:

  - aprova todos os pares, inclusive a faixa 60–89;
  - nos sabores duplicados no xFood, liga OS DOIS códigos ao mesmo sabor;
  - em lojas que não são a de referência (Vapor), um sabor com confiança < 90
    que NÃO existe na Vapor fica de fora e vai para a lista de pendências.

"Existe na Vapor" = a Vapor tem um sabor com o mesmo nome (normalizado) ligado
ao mesmo código do xFood. Não dá para comparar por id: cada loja tem o próprio
banco e os ids são independentes.

Uso:
    python tools/aprovar_ligacao_xfood.py "C:\\...\\saida" --destino tools
"""

import argparse
import csv
import os
import re
import sys
import unicodedata

LOJAS = ["vapor", "royal", "podsilha"]
REFERENCIA = "vapor"
APROVA_SEM_REFERENCIA = 90

# Mesmo sabor cadastrado com dois códigos no xFood: os dois vão para o sabor.
DUPLOS = [{"49166", "0570"}, {"0500", "0602"}]

# Decisões do dono sobre os pendentes (confiança < 90 e grafia diferente da
# Vapor). (loja, site_sabor_id) -> código aprovado. Só vale se a sugestão do
# script continuar sendo esse código; se mudar, volta a ser pendente.
APROVADOS_MANUAIS = {
    ("royal", "67"): "6932570104182",     # TE30K Bubballo Grape
    ("royal", "65"): "6932570104199",     # TE30K Bubbaloo tutti fruit
    ("podsilha", "64"): "6932570104199",  # TE30K Bubballo tutti fruit
}
# Ficam SEM código de propósito (o dono resolve no admin).
RECUSADOS_MANUAIS = {
    ("podsilha", "246"),                  # Elfbar Duke 35K Mango Peach (xFood só tem Mango Magic)
}


def chave(texto):
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).upper()
    return re.sub(r"[^A-Z0-9]", "", t)


def ler(pasta, loja):
    caminho = os.path.join(pasta, loja, "ligacao_sugerida.csv")
    with open(caminho, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pasta", help="pasta com as subpastas vapor/, royal/, podsilha/")
    ap.add_argument("--destino", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()

    dados = {loja: ler(args.pasta, loja) for loja in LOJAS}
    ref = {(chave(r["sabor_site"]), r["xfood_codigo"]) for r in dados[REFERENCIA]}

    # ---- comparação entre lojas
    print("SABORES POR LOJA")
    for loja in LOJAS:
        print(f"  {loja:<9} {len(dados[loja])}")
    por_id = {loja: {r["site_sabor_id"]: r for r in dados[loja]} for loja in LOJAS}
    ids = [set(por_id[l]) for l in LOJAS]
    print(f"\nIDS: iguais nas 3 = {ids[0] == ids[1] == ids[2]}; em comum nas 3 = {len(ids[0] & ids[1] & ids[2])}")
    mesmo_sabor = sum(
        1 for i in ids[0] & ids[1] & ids[2]
        if len({(chave(por_id[l][i]["sabor_site"]), por_id[l][i]["xfood_codigo"]) for l in LOJAS}) == 1
    )
    print(f"     ids em comum que apontam para o MESMO sabor nas 3 = {mesmo_sabor}")

    conj = {loja: {(chave(r["sabor_site"]), r["xfood_codigo"]): r for r in dados[loja]} for loja in LOJAS}
    print("\nSABOR (nome + código xFood) QUE EXISTE NUMA LOJA E NÃO EM OUTRA")
    algum = False
    for loja in LOJAS:
        outras = [l for l in LOJAS if l != loja]
        for k, r in sorted(conj[loja].items(), key=lambda kv: (kv[1]["modelo_site"], kv[1]["sabor_site"])):
            faltam = [l for l in outras if k not in conj[l]]
            if faltam:
                algum = True
                print(f"  só em {loja:<9} (falta em {', '.join(faltam)}): [{r['modelo_site']}] {r['sabor_site']}"
                      f" -> {r['xfood_codigo']} {r['xfood_descricao']} (conf {r['confianca']})")
    if not algum:
        print("  nenhum")

    # ---- aprovação
    print("\nAPROVAÇÃO")
    pendentes, recusados = [], []
    for loja in LOJAS:
        pares = []
        for r in dados[loja]:
            conf = int(r["confianca"])
            existe_ref = (chave(r["sabor_site"]), r["xfood_codigo"]) in ref
            k = (loja, r["site_sabor_id"])
            if k in RECUSADOS_MANUAIS:
                recusados.append((loja, r))
                continue
            aprovado_dono = APROVADOS_MANUAIS.get(k) == r["xfood_codigo"]
            if loja != REFERENCIA and conf < APROVA_SEM_REFERENCIA and not existe_ref and not aprovado_dono:
                pendentes.append((loja, r))
                continue
            sid = int(r["site_sabor_id"])
            pares.append((sid, r["xfood_codigo"]))
            for d in DUPLOS:
                if {r["xfood_codigo"], r["candidato2_codigo"]} == d:
                    pares.append((sid, r["candidato2_codigo"]))
        pares.sort()
        destino = os.path.join(args.destino, f"ligacao_aprovada_{loja}.csv")
        with open(destino, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["site_sabor_id", "xfood_codigo"])
            w.writerows(pares)
        duplos = sorted({s for s, _ in pares if sum(1 for x, _ in pares if x == s) > 1})
        print(f"  {loja:<9} {len({s for s, _ in pares})} sabores, {len(pares)} códigos"
              f" (sabores com 2 códigos: {duplos}) -> {destino}")

    print("\nPENDENTES (confiança < 90 e não existe na Vapor) — NÃO aprovados")
    for loja, r in pendentes:
        print(f"  {loja:<9} id {r['site_sabor_id']:<4} [{r['modelo_site']}] {r['sabor_site']}"
              f" -> sugerido {r['xfood_codigo']} {r['xfood_descricao']} (conf {r['confianca']});"
              f" 2º {r['candidato2_codigo']} {r['candidato2_descricao']}")
    if not pendentes:
        print("  nenhum")

    print("\nSEM CÓDIGO POR DECISÃO DO DONO (resolver no admin)")
    for loja, r in recusados:
        print(f"  {loja:<9} id {r['site_sabor_id']:<4} [{r['modelo_site']}] {r['sabor_site']}"
              f" (sugestão recusada: {r['xfood_codigo']} {r['xfood_descricao']})")
    if not recusados:
        print("  nenhum")


if __name__ == "__main__":
    main()

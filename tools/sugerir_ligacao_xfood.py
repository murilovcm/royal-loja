"""Sugere a ligação entre cada sabor do site e um produto (código) do xFood.

Só LÊ: o catálogo público de produção (o JSON embutido na home, em
<script id="catalogData">) e o estoque_atual.json exportado do xFood. Não
importa nada do app Flask nem toca no banco.

Uso:
    python tools/sugerir_ligacao_xfood.py "C:\\...\\estoque_atual.json"
    python tools/sugerir_ligacao_xfood.py estoque.json --catalogo-html home.html --saida pasta

Estratégia ("grupo primeiro"):
  1. Cada modelo do site é ligado a um grupo_id do xFood (≈ uma linha de
     produto) pela sobreposição de sabores + tokens do nome (50K, V400, MIX...).
     Corrija na mão em GRUPO_FORCADO quando errar.
  2. Cada sabor é comparado só com os itens daquele grupo. Grupo fraco (< 50)
     => busca em todos os itens e a confiança fica limitada a 59.

Saídas (separador ;, UTF-8 com BOM):
  ligacao_sugerida.csv, sem_par_no_xfood.csv, xfood_sem_par_no_site.csv
"""

import argparse
import csv
import difflib
import json
import os
import re
import sys
import unicodedata
import urllib.request
from collections import defaultdict

# {nome do modelo no site (como aparece em modelo_site): grupo_id do xFood}
# Ex.: {"ICE KING": "3268fdef-5acd-4eb0-9c31-45f2b5388173"}
GRUPO_FORCADO = {}

URL_PADRAO = "https://vaporstoreslz.com/"
NOTA_GRUPO_MIN = 50          # abaixo disso o grupo não é confiável
LIMITE_SEM_GRUPO = 59        # teto de confiança quando o grupo é fraco
SEM_PAR_ABAIXO = 40          # confiança < isto => "sem candidato razoável"
LIGADO_A_PARTIR = 60         # item do xFood conta como "casado" a partir disto

# Tokens que descrevem o aparelho, não o sabor.
RE_MODELO = re.compile(r"^(V\d+|\d+K|\d+|\d+MG|MG|K)$")


# ---------------------------------------------------------------- normalização

def limpar_visivel(texto):
    """Tira emoji/símbolos mas mantém a grafia (para mostrar no CSV)."""
    out = []
    for ch in texto or "":
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "N", "Z") or ch in "|/-_(),.&'+":
            out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def normalizar(texto):
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.upper()
    t = re.sub(r"[|/\-_(),.&+]", " ", t)
    t = re.sub(r"[^A-Z0-9 ]", " ", t)
    # "DOJO40K", "TE30K", "BC15K" -> "DOJO 40K"; "V400" (uma letra) fica junto.
    t = re.sub(r"\b([A-Z]{2,})(\d+K)\b", r"\1 \2", t)
    return re.sub(r"\s+", " ", t).strip()


def tokens(texto):
    return normalizar(texto).split()


def token_modelo(tok):
    """Padroniza números do aparelho: 10000 -> 10K, 46 -> 46K."""
    if tok.isdigit():
        n = int(tok)
        if n >= 1000 and n % 1000 == 0:
            return f"{n // 1000}K"
        if 5 <= n < 100:
            return f"{n}K"
    return tok


def puffs_para_token(puff_count):
    digitos = re.sub(r"\D", "", puff_count or "")
    if digitos and int(digitos) >= 1000:
        return f"{int(digitos) // 1000}K"
    return None


# ------------------------------------------------------------------- entrada

def carregar_catalogo(url, html_local):
    if html_local:
        with open(html_local, encoding="utf-8") as f:
            html = f.read()
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ligacao-xfood)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            html = r.read().decode("utf-8")
    m = re.search(r'<script id="catalogData" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        sys.exit("Não achei <script id=\"catalogData\"> na página do catálogo.")
    return json.loads(m.group(1))


def carregar_xfood(caminho):
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    itens = []
    for i in dados["itens"]:
        bruto = i.get("descricao") or ""
        try:
            saldo = float(i.get("saldo") or 0)
        except (TypeError, ValueError):
            saldo = 0.0
        itens.append({
            "codigo": str(i.get("codigo") or ""),
            "descricao": bruto.strip(),
            "grupo_id": i.get("grupo_id") or "",
            "saldo": int(saldo) if saldo == int(saldo) else saldo,
            "_bruto": bruto,
        })
    separar_prefixo(itens)
    return itens


def separar_prefixo(itens):
    """Separa os tokens do aparelho (prefixo) dos tokens do sabor.

    Quando há | ou /, o prefixo é o que vem antes do primeiro separador. Sem
    separador ("ELFBAR 15K ICY MINT"), tiro do começo os tokens que o grupo
    usa como prefixo nos outros itens ou que têm cara de modelo (50K, V250).
    """
    por_grupo = defaultdict(list)
    for it in itens:
        por_grupo[it["grupo_id"]].append(it)

    for grupo in por_grupo.values():
        pref_grupo = set()
        for it in grupo:
            m = re.match(r"^([^|/]*)[|/](.*)$", it["_bruto"])
            if m and tokens(m.group(1)):
                pref_grupo.update(tokens(m.group(1)))
        if not pref_grupo:  # nenhum item com separador: usa os tokens iniciais frequentes
            cont = defaultdict(int)
            for it in grupo:
                for t in set(tokens(it["_bruto"])[:3]):
                    cont[t] += 1
            pref_grupo = {t for t, c in cont.items() if c >= max(2, len(grupo) / 2)}

        for it in grupo:
            m = re.match(r"^([^|/]*)[|/](.*)$", it["_bruto"])
            if m and tokens(m.group(1)):
                pref, sab = tokens(m.group(1)), tokens(m.group(2))
            else:
                toks = tokens(it["_bruto"])
                k = 0
                while k < len(toks) - 1 and (toks[k] in pref_grupo or RE_MODELO.match(toks[k])):
                    k += 1
                pref, sab = toks[:k], toks[k:]
            it["prefixo"] = [token_modelo(t) for t in pref]
            it["sabor"] = sab


# ---------------------------------------------------------------- similaridade

_cache_tok = {}


# Parecidos mas não iguais: "ICE MINT" x "ICY MINT" vai para revisão, não some.
QUASE = {frozenset(("ICE", "ICY")): 0.7}


def sim_token(a, b):
    if a == b:
        return 1.0
    if frozenset((a, b)) in QUASE:
        return QUASE[frozenset((a, b))]
    chave = (a, b)
    if chave not in _cache_tok:
        r = 0.0
        if len(a) >= 4 and len(b) >= 4:
            r = difflib.SequenceMatcher(None, a, b).ratio()
            r = r if r >= 0.85 else 0.0
        _cache_tok[chave] = r
    return _cache_tok[chave]


def cobertura(a, b):
    if not a:
        return 0.0
    return sum(max((sim_token(x, y) for y in b), default=0.0) for x in a) / len(a)


_cache_sab = {}


def nota_sabor(a, b):
    """0..1 entre duas listas de tokens de sabor."""
    chave = (tuple(a), tuple(b))
    if chave in _cache_sab:
        return _cache_sab[chave]
    if not a or not b:
        _cache_sab[chave] = 0.0
        return 0.0
    if "".join(a) == "".join(b):          # DRAGONFRUIT x DRAGON FRUIT
        _cache_sab[chave] = 1.0
        return 1.0
    ca, cb = cobertura(a, b), cobertura(b, a)
    f1 = 0.0 if ca + cb == 0 else 2 * ca * cb / (ca + cb)
    # Pega junções/quebras: "PINEAPPLEICE" x "PINEAPPLE ICE".
    junto = difflib.SequenceMatcher(None, "".join(sorted(a)), "".join(sorted(b))).ratio()
    nota = 0.75 * f1 + 0.25 * junto
    # "Grape" e "Grape Ice" são produtos diferentes.
    frio = {"ICE", "ICY"}
    if bool(frio & set(a)) != bool(frio & set(b)):
        nota *= 0.85
    _cache_sab[chave] = nota
    return nota


# --------------------------------------------------------------------- casamento

def sabores_do_site(catalogo):
    linhas = []
    for m in catalogo:
        for f in m["flavors"]:
            nome_modelo = (f.get("version_name") or m["name"]).strip()
            rotulo = (f.get("version_label") or "").strip()
            modelo_site = f"{nome_modelo} ({rotulo})" if rotulo else nome_modelo
            puff = puffs_para_token(f.get("version_puffs") or m.get("puff_count"))
            tok_modelo = {token_modelo(t) for t in tokens(nome_modelo)}
            if puff:
                tok_modelo.add(puff)
            linhas.append({
                "id": f["id"],
                "modelo_site": modelo_site,
                "marca": m.get("brand_name") or "",
                "sabor_site": limpar_visivel(f["name"]),
                "tok_sabor": tokens(f["name"]),
                "tok_modelo": tok_modelo,
                "em_estoque": bool(f.get("is_in_stock")),
            })
    return linhas


def nota_nome(tok_modelo, prefixo_grupo):
    """Fração dos tokens do prefixo do grupo que aparecem no nome do modelo."""
    if not prefixo_grupo:
        return 0.0
    achou = sum(1 for p in prefixo_grupo if any(sim_token(p, t) >= 0.85 for t in tok_modelo))
    return achou / len(prefixo_grupo)


def escolher_grupos(sabores, itens):
    por_grupo = defaultdict(list)
    for it in itens:
        por_grupo[it["grupo_id"]].append(it)

    # Prefixo "típico" do grupo = tokens presentes em >= 40% dos prefixos.
    pref_grupo = {}
    for g, lst in por_grupo.items():
        cont = defaultdict(int)
        for it in lst:
            for t in set(it["prefixo"]):
                cont[t] += 1
        pref_grupo[g] = {t for t, c in cont.items() if c >= 0.4 * len(lst)}

    por_modelo = defaultdict(list)
    for s in sabores:
        por_modelo[s["modelo_site"]].append(s)

    escolha = {}
    for modelo, lst in por_modelo.items():
        tok_modelo = lst[0]["tok_modelo"]
        notas = []
        for g, its in por_grupo.items():
            encaixe = sum(max(nota_sabor(s["tok_sabor"], it["sabor"]) for it in its) for s in lst) / len(lst)
            nome = nota_nome(tok_modelo, pref_grupo[g])
            ativo = 2 if any(isinstance(it["saldo"], (int, float)) and it["saldo"] > 0 for it in its) else 0
            notas.append((min(100, round(100 * (0.7 * encaixe + 0.3 * nome)) + ativo), g))
        notas.sort(reverse=True)
        forcado = GRUPO_FORCADO.get(modelo)
        if forcado:
            escolha[modelo] = {"grupo": forcado, "nota": 100, "forcado": True,
                               "segundo": notas[0], "pref": pref_grupo.get(forcado, set())}
        else:
            escolha[modelo] = {"grupo": notas[0][1], "nota": notas[0][0], "forcado": False,
                               "segundo": notas[1] if len(notas) > 1 else (0, ""),
                               "pref": pref_grupo[notas[0][1]]}
    return escolha, por_grupo


def casar(sabores, itens, escolha, por_grupo):
    resultado = []
    for s in sabores:
        info = escolha[s["modelo_site"]]
        forte = info["forcado"] or info["nota"] >= NOTA_GRUPO_MIN
        universo = por_grupo.get(info["grupo"], []) if forte else itens

        cands = []
        for it in universo:
            n = nota_sabor(s["tok_sabor"], it["sabor"])
            # Bônus pequeno quando o prefixo do item bate com o nome do modelo
            # (separa "V400 MIX" de "V400 MIX SLIM" dentro do mesmo grupo).
            n += 0.03 * nota_nome(s["tok_modelo"], it["prefixo"])
            if not forte:
                n *= 0.5 + 0.5 * nota_nome(s["tok_modelo"], it["prefixo"])
            tem_saldo = 1 if isinstance(it["saldo"], (int, float)) and it["saldo"] > 0 else 0
            cands.append((n, tem_saldo, it))
        cands.sort(key=lambda c: (c[0], c[1]), reverse=True)

        c1 = cands[0] if cands else None
        c2 = cands[1] if len(cands) > 1 else None
        conf = 0
        if c1:
            conf = 100 * min(c1[0], 1.0)
            if c2:
                margem = c1[0] - c2[0]
                if margem < 0.05:
                    conf -= (0.05 - margem) * 200      # até -10 quando empatam
            if not forte:
                conf = min(conf, LIMITE_SEM_GRUPO)
        resultado.append({
            **s,
            "conf": max(0, min(100, round(conf))),
            "c1": c1[2] if c1 else None,
            "c2": c2[2] if c2 else None,
        })
    return resultado


# ---------------------------------------------------------------------- saídas

def escrever_csv(caminho, cabecalho, linhas):
    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cabecalho)
        w.writerows(linhas)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("estoque_json")
    ap.add_argument("--url", default=URL_PADRAO)
    ap.add_argument("--catalogo-html", help="HTML da home salvo localmente (em vez de baixar)")
    ap.add_argument("--saida", help="pasta dos CSVs (padrão: a pasta do estoque_json)")
    ap.add_argument("--exemplos", type=int, default=10)
    args = ap.parse_args()

    saida = args.saida or os.path.dirname(os.path.abspath(args.estoque_json))
    os.makedirs(saida, exist_ok=True)

    catalogo = carregar_catalogo(args.url, args.catalogo_html)
    itens = carregar_xfood(args.estoque_json)
    sabores = sabores_do_site(catalogo)
    escolha, por_grupo = escolher_grupos(sabores, itens)
    res = casar(sabores, itens, escolha, por_grupo)
    res.sort(key=lambda r: (r["conf"], r["modelo_site"], r["sabor_site"]))

    # ligacao_sugerida.csv
    escrever_csv(
        os.path.join(saida, "ligacao_sugerida.csv"),
        ["site_sabor_id", "modelo_site", "sabor_site", "xfood_codigo", "xfood_descricao",
         "saldo_xfood", "confianca", "candidato2_codigo", "candidato2_descricao"],
        [[r["id"], r["modelo_site"], r["sabor_site"],
          r["c1"]["codigo"] if r["c1"] else "", r["c1"]["descricao"] if r["c1"] else "",
          r["c1"]["saldo"] if r["c1"] else "", r["conf"],
          r["c2"]["codigo"] if r["c2"] else "", r["c2"]["descricao"] if r["c2"] else ""]
         for r in res],
    )

    # sem_par_no_xfood.csv
    sem_par = [r for r in res if r["conf"] < SEM_PAR_ABAIXO]
    escrever_csv(
        os.path.join(saida, "sem_par_no_xfood.csv"),
        ["site_sabor_id", "modelo_site", "sabor_site", "em_estoque_site",
         "melhor_tentativa_codigo", "melhor_tentativa_descricao", "confianca"],
        [[r["id"], r["modelo_site"], r["sabor_site"], "sim" if r["em_estoque"] else "não",
          r["c1"]["codigo"] if r["c1"] else "", r["c1"]["descricao"] if r["c1"] else "", r["conf"]]
         for r in sem_par],
    )

    # xfood_sem_par_no_site.csv
    casados = {r["c1"]["codigo"] for r in res if r["c1"] and r["conf"] >= LIGADO_A_PARTIR}
    modelo_do_grupo = defaultdict(list)
    for modelo, info in escolha.items():
        if info["forcado"] or info["nota"] >= NOTA_GRUPO_MIN:
            modelo_do_grupo[info["grupo"]].append(modelo)
    sobra = [it for it in itens
             if isinstance(it["saldo"], (int, float)) and it["saldo"] > 0 and it["codigo"] not in casados]
    sobra.sort(key=lambda it: (", ".join(modelo_do_grupo.get(it["grupo_id"], [])) == "", it["descricao"]))
    escrever_csv(
        os.path.join(saida, "xfood_sem_par_no_site.csv"),
        ["xfood_codigo", "xfood_descricao", "saldo_xfood", "grupo_id", "modelo_site_do_grupo"],
        [[it["codigo"], it["descricao"], it["saldo"], it["grupo_id"],
          ", ".join(modelo_do_grupo.get(it["grupo_id"], []))] for it in sobra],
    )

    # ----- resumo no terminal
    print("MODELO DO SITE -> GRUPO DO xFOOD (nota; 2º grupo)")
    for modelo, info in sorted(escolha.items(), key=lambda kv: kv[1]["nota"]):
        ex = next((it["descricao"] for it in por_grupo.get(info["grupo"], [])), "?")
        ex2 = next((it["descricao"] for it in por_grupo.get(info["segundo"][1], [])), "?")
        marca = " [forçado]" if info["forcado"] else ("" if info["nota"] >= NOTA_GRUPO_MIN else " [FRACO]")
        print(f"  {info['nota']:>3}{marca}  {modelo:<32} -> {ex:<40} | 2º {info['segundo'][0]:>3} {ex2}")

    alta = [r for r in res if r["conf"] >= 90]
    media = [r for r in res if 60 <= r["conf"] < 90]
    baixa = [r for r in res if r["conf"] < 60]
    print()
    print(f"Sabores no site: {len(res)}")
    print(f"  confiança >= 90 : {len(alta)}")
    print(f"  60 a 89         : {len(media)}")
    print(f"  abaixo de 60    : {len(baixa)}")
    print(f"  sem par (< {SEM_PAR_ABAIXO})  : {len(sem_par)}")
    print(f"  xFood com saldo > 0 sem par no site: {len(sobra)}")

    def mostra(titulo, lst):
        print(f"\n{titulo}")
        passo = max(1, len(lst) // args.exemplos) if lst else 1
        for r in lst[::passo][: args.exemplos]:
            c1 = f"{r['c1']['codigo']} {r['c1']['descricao']}" if r["c1"] else "-"
            print(f"  {r['conf']:>3}  [{r['modelo_site']}] {r['sabor_site']}  ->  {c1}")

    mostra(">= 90", alta)
    mostra("60 a 89", media)
    mostra("< 60", baixa)
    print(f"\nCSVs gravados em: {saida}")


if __name__ == "__main__":
    main()

# 👑 Royal — Loja de Vapes Premium

Loja virtual single-page com estética dark premium (preto + amarelo vibrante + roxo),
checkout via WhatsApp, painel admin e live editor visual.

## Stack
- Backend: Python + Flask
- Banco: SQLite3 puro (sem ORM)
- Frontend: Jinja2 + CSS puro (variáveis) + Vanilla JS

## Como rodar
```bash
pip install -r requirements.txt
python app.py
```
Acesse http://localhost:5000

O banco `royal.db` é criado automaticamente com dados de exemplo (Ignite, Elfbar, Lost Mary).

## Rotas
- `/`               — Loja (visão do cliente)
- `/admin`          — Painel administrativo (marcas → modelos → sabores)
- `/admin/editor`   — Live Editor visual (textos editáveis, color picker, drag&drop de fotos)

## Configuração
Edite `WHATSAPP_PHONE` no topo de `app.py` com o telefone do dono da loja
(formato internacional só dígitos, ex: `5598999999999`).

## Estrutura do negócio
Hierarquia centrada no modelo: **Marca → Modelo (a foto/caixa) → Sabores (produtos)**.
- Card exibe a foto do MODELO, puffs, 2 sabores + "mais X", e menor preço.
- Modal: escolha do sabor (só em estoque), seletor de qtd, botão bloqueado até selecionar.
- Carrinho: localStorage → sidebar deslizante → checkout WhatsApp formatado.

## Admin
- Painel: toggle ⭐ (best seller) no modelo; toggle de estoque + edição rápida de preço/nome
  no sabor (salva via fetch no onchange).
- Live Editor: textos `contenteditable` salvam no blur; color picker injeta `--primary-yellow`;
  arraste uma imagem sobre um card para trocar a foto do modelo.

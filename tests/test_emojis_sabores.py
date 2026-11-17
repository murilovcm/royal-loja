"""Emojis automáticos dos sabores (static/js/emojis-sabores.js).

A regra mora em JS (roda no admin), então o teste chama o Node. Sem Node na
máquina, pula: o resto da suíte não depende dele.
"""
import json
import os
import shutil
import subprocess

import pytest

JS = os.path.join(os.path.dirname(__file__), "..", "static", "js", "emojis-sabores.js")
NODE = shutil.which("node")

# Os 10 sabores do print do dono, com os emojis que ele já punha à mão.
CASOS = {
    "Watermelon Ice": "🍉 ❄️ Watermelon Ice",
    "Sour Watermelon Peach": "🍉 🍑 Sour Watermelon Peach",
    "Menthol": "🌿 Menthol",
    "Kiwi Strawberry Ice": "🥝 🍓 ❄️ Kiwi Strawberry Ice",
    "Fanta Strawberry": "🍊 🍓 Fanta Strawberry",
    "Sakura Grape": "🍇 Sakura Grape",
    "Pineapple Ice": "🍍 ❄️ Pineapple Ice",
    "Icy Mint": "🌿 ❄️ Icy Mint",
    "Green Apple Ice": "🍏 ❄️ Green Apple Ice",
    # Frase de duas palavras não conta a fruta de novo; português também vale.
    "Apple / Green Apple": "🍎 🍏 Apple / Green Apple",
    "Morango com Menta Gelado": "🍓 🌿 ❄️ Morango com Menta Gelado",
    # Já tem emoji: não mexe. Palavra desconhecida: não inventa.
    "🍓 Strawberry Ice": "🍓 Strawberry Ice",
    "Lush": "Lush",
    "": "",
}


@pytest.mark.skipif(not NODE, reason="Node não instalado")
def test_emojis_pelo_nome_do_sabor():
    codigo = (
        "const E = require(%s);"
        "const casos = %s;"
        "process.stdout.write(JSON.stringify(Object.keys(casos).map(n => [n, E.comEmojis(n)])));"
    ) % (json.dumps(os.path.abspath(JS)), json.dumps(CASOS))
    saida = subprocess.run([NODE, "-e", codigo], capture_output=True, check=True).stdout
    resultado = dict(json.loads(saida.decode("utf-8")))
    assert resultado == CASOS

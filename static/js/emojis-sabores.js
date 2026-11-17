/* Emojis automáticos nos nomes dos sabores (painel admin).
 *
 * Lê o nome do sabor e devolve os emojis na ORDEM das palavras
 * ("Kiwi Strawberry Ice" -> "🥝 🍓 ❄️ Kiwi Strawberry Ice"). O gelo vai sempre
 * por último, como já era feito à mão. Regras:
 *   - nome que já começa com emoji não é tocado (quem ajustou à mão manda);
 *   - palavra desconhecida não ganha nada (melhor sem emoji que com o errado);
 *   - no máximo 4 emojis, sem repetir.
 * A COR do sabor (a bolinha na loja) sai do primeiro emoji: o que já está no
 * nome, ou o que a regra acima sugeriria. Quem decide QUANDO pintar é o admin
 * (só sabor ainda com o roxo padrão — cor escolhida à mão não muda).
 * Para ensinar uma fruta nova, é só pôr a palavra no dicionário abaixo.
 * tests/test_emojis_sabores.py roda estes exemplos no Node.
 */
(function (global) {
  "use strict";

  // Frases de duas palavras vêm antes: "green apple" é 🍏, não 🍎.
  var FRASES = [
    ["green apple", "🍏"], ["maçã verde", "🍏"], ["blue razz", "🫐"], ["cotton candy", "🍬"],
    ["bubble gum", "🍬"], ["passion fruit", "🥭"], ["dragon fruit", "🐉"], ["red bull", "⚡"],
  ];
  var PALAVRAS = {
    watermelon: "🍉", melancia: "🍉", strawberry: "🍓", morango: "🍓", grape: "🍇", uva: "🍇",
    kiwi: "🥝", peach: "🍑", "pêssego": "🍑", pessego: "🍑", mango: "🥭", manga: "🥭",
    pineapple: "🍍", abacaxi: "🍍", banana: "🍌", cherry: "🍒", cereja: "🍒",
    blueberry: "🫐", mirtilo: "🫐", berry: "🫐", berries: "🫐", blackberry: "🫐", raspberry: "🫐",
    apple: "🍎", "maçã": "🍎", lemon: "🍋", lime: "🍋", "limão": "🍋", lemonade: "🍋",
    orange: "🍊", laranja: "🍊", fanta: "🍊", tangerine: "🍊", coconut: "🥥", coco: "🥥",
    melon: "🍈", honeydew: "🍈", pear: "🍐", passion: "🥭", guava: "🍈",
    mint: "🌿", menthol: "🌿", menta: "🌿", "hortelã": "🌿", mojito: "🌿",
    cola: "🥤", coke: "🥤", coffee: "☕", "café": "☕", vanilla: "🍦", baunilha: "🍦",
    cream: "🍦", candy: "🍬", gum: "🍬", chocolate: "🍫", tea: "🍵", energy: "⚡",
  };
  // Cor de cada emoji (fruta mais "de cara": melancia vermelha, não verde).
  var CORES = {
    "🍉": "#ff3b4e", "🍓": "#ff2d55", "🍇": "#8b3dff", "🥝": "#8bc34a", "🍑": "#ffa26b",
    "🥭": "#ffb020", "🍍": "#f5c518", "🍌": "#ffe135", "🍒": "#c8102e", "🫐": "#4f6bed",
    "🍏": "#4caf50", "🍎": "#e53935", "🍋": "#f7e04b", "🍊": "#ff8c1a", "🥥": "#d9c7a7",
    "🍈": "#b5e07a", "🍐": "#c5d86d", "🌿": "#22b07d", "🥤": "#8b4513", "☕": "#6f4e37",
    "🍦": "#f3e5ab", "🍬": "#ff7eb6", "🍫": "#5d3a1a", "🍵": "#7cb342", "⚡": "#2196f3",
    "🐉": "#e91e63", "❄️": "#7dd3fc",
  };
  var GELO = /^(ice|icy|iced|cool|frozen|gelo|gelado|gelada)$/;
  var JA_TEM = /^\s*\p{Extended_Pictographic}/u;

  function sugerir(nome) {
    if (!nome || JA_TEM.test(nome)) return "";
    return pelasPalavras(nome).join(" ");
  }

  // Lista de emojis que o nome pede, na ordem (sem olhar se já tem emoji).
  function pelasPalavras(nome) {
    var txt = " " + nome.toLowerCase().replace(/[\/()+,&.-]/g, " ").replace(/\s+/g, " ") + " ";
    var achados = [];  // [posição no nome, emoji]
    FRASES.forEach(function (fe) {
      var alvo = " " + fe[0] + " ", i = txt.indexOf(alvo);
      if (i >= 0) {
        achados.push([i, fe[1]]);
        // Apaga a frase (mesmo tamanho) para "apple" não contar de novo.
        txt = txt.replace(alvo, " " + "_".repeat(fe[0].length) + " ");
      }
    });
    var gelo = false, pos = 0;
    txt.split(" ").forEach(function (p) {
      if (Object.prototype.hasOwnProperty.call(PALAVRAS, p)) achados.push([pos, PALAVRAS[p]]);
      if (GELO.test(p)) gelo = true;
      pos += p.length + 1;
    });
    var lista = [];
    achados.sort(function (a, b) { return a[0] - b[0]; }).forEach(function (a) {
      if (lista.indexOf(a[1]) < 0) lista.push(a[1]);
    });
    if (gelo) lista.push("❄️");
    return lista.slice(0, 4);
  }

  // Cor pelo primeiro emoji do nome (o que já está lá manda); "" se não souber.
  function cor(nome) {
    var m = (nome || "").match(/^\s*(\p{Extended_Pictographic})/u);
    var e = m ? m[1] : pelasPalavras(nome || "")[0];
    if (!e) return "";
    // ❄ às vezes vem sem o ️ (o seletor de emoji); vale das duas formas.
    return CORES[e] || CORES[e + "️"] || "";
  }

  function comEmojis(nome) {
    var s = sugerir(nome);
    return s ? s + " " + nome.trim() : nome;
  }

  var api = { sugerir: sugerir, comEmojis: comEmojis, cor: cor };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else global.EmojisSabores = api;
})(this);

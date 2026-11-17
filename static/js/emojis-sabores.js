/* Emojis automáticos nos nomes dos sabores (painel admin).
 *
 * Lê o nome do sabor e devolve os emojis na ORDEM das palavras
 * ("Kiwi Strawberry Ice" -> "🥝 🍓 ❄️ Kiwi Strawberry Ice"). O gelo vai sempre
 * por último, como já era feito à mão. Regras:
 *   - nome que já começa com emoji não é tocado (quem ajustou à mão manda);
 *   - palavra desconhecida não ganha nada (melhor sem emoji que com o errado);
 *   - no máximo 4 emojis, sem repetir.
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
  var GELO = /^(ice|icy|iced|cool|frozen|gelo|gelado|gelada)$/;
  var JA_TEM = /^\s*\p{Extended_Pictographic}/u;

  function sugerir(nome) {
    if (!nome || JA_TEM.test(nome)) return "";
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
    return lista.slice(0, 4).join(" ");
  }

  function comEmojis(nome) {
    var s = sugerir(nome);
    return s ? s + " " + nome.trim() : nome;
  }

  var api = { sugerir: sugerir, comEmojis: comEmojis };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else global.EmojisSabores = api;
})(this);

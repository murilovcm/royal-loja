/* Roda dentro do WhatsApp Web. Faz UMA coisa: lê o nome no topo da conversa
   aberta e avisa o painel quando ele muda (para o painel abrir o pedido
   daquela conversa com o nome do cliente já preenchido).

   Não lê mensagens, não clica, não digita e não envia nada. Se o WhatsApp
   mudar a tela e o nome deixar de ser achado, o painel só para de preencher
   sozinho; todo o resto continua igual. */
(function () {
  "use strict";

  // Textos que aparecem no cabeçalho mas não são o nome do contato.
  var NAO_E_NOME = /^(online|digitando|gravando|visto por último|clique para|toque para|click here|typing|last seen)/i;

  function nomeDaConversa() {
    var cab = document.querySelector("#main header");
    if (!cab) return "";
    var spans = cab.querySelectorAll('span[dir="auto"]');
    for (var i = 0; i < spans.length; i++) {
      var t = (spans[i].getAttribute("title") || spans[i].textContent || "").trim();
      if (t && !NAO_E_NOME.test(t)) return t.slice(0, 60);
    }
    return "";
  }

  var ultimo = null;
  function avisar(forcar) {
    var nome = nomeDaConversa();
    if (!nome || (nome === ultimo && !forcar)) return;
    ultimo = nome;
    try { chrome.runtime.sendMessage({ tipo: "atd-conversa", nome: nome }).catch(function () {}); }
    catch (e) { /* extensão recarregada: este script antigo para aqui */ }
  }

  // Conferir a cada 0,7 s é leve e não depende de como o WhatsApp monta a tela.
  setInterval(avisar, 700);

  // O painel acabou de abrir e pergunta qual é a conversa de agora.
  chrome.runtime.onMessage.addListener(function (msg, _quem, responder) {
    if (msg && msg.tipo === "atd-qual-conversa") {
      responder({ nome: nomeDaConversa() });
    }
  });
})();

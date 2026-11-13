/* Métricas de visita da loja (aba Métricas do painel).

   Três sinais, todos sem cookie e sem corpo — o servidor identifica o
   visitante por um hash diário de IP + navegador e descarta robôs e quem está
   logado no painel (ver "Métricas de visita" no app.py):
     hit  -> ao abrir a página (visitante único + página vista)
     ping -> a cada 30 s enquanto a aba está VISÍVEL ("online agora")
     wa   -> quando o pedido é enviado para o WhatsApp (app.js chama
             window.royalMetrics.wa())
   Falha de rede aqui nunca pode atrapalhar a compra: tudo é fire-and-forget. */
(function () {
  "use strict";
  var PING_MS = 30000;

  function send(path) {
    try {
      if (navigator.sendBeacon && navigator.sendBeacon(path)) return;
      fetch(path, { method: "POST", keepalive: true, credentials: "same-origin" }).catch(function () {});
    } catch (_) { /* métrica nunca quebra a loja */ }
  }

  var timer = null;
  function startPing() {
    if (timer) return;
    timer = setInterval(function () { send("/api/m/ping"); }, PING_MS);
  }
  function stopPing() {
    clearInterval(timer);
    timer = null;
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      send("/api/m/ping");
      startPing();
    } else {
      stopPing();
    }
  });

  send("/api/m/hit");
  if (document.visibilityState === "visible") startPing();

  window.royalMetrics = { wa: function () { send("/api/m/wa"); } };
})();

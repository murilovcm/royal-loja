/* Métricas de visita da loja (aba Métricas do painel).

   Sinais sem cookie e sem corpo — o servidor identifica o visitante por um
   hash diário de IP + navegador e descarta robôs e quem está logado no painel
   (ver "Métricas de visita" no app.py):
     hit  -> ao abrir a página (visitante único + página vista)
     ping -> a cada 30 s enquanto a aba está VISÍVEL ("online agora")
     step -> passos do funil, chamados pelo app.js via
             window.royalMetrics.step(...): "product" (abriu um produto),
             "cart" (adicionou ao carrinho), "checkout" (abriu o checkout) e
             "order" (enviou o pedido no WhatsApp); e "hero", o toque no
             "Ver Catálogo" do topo (contador à parte). Cada um só é mandado
             uma vez por página aberta; o servidor deduplica por dia.
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

  var sent = {};
  window.royalMetrics = {
    step: function (name) {
      if (sent[name]) return;
      sent[name] = true;
      send("/api/m/step/" + name);
    },
  };
})();

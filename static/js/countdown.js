/* ===================================================================
   COUNTDOWN DAS PROMOÇÕES

   Carregado sempre, com ou sem o tema Black Friday: o desconto com hora
   marcada é do produto, não do tema. Sem nenhuma promoção na página este
   arquivo não faz nada (o intervalo nem chega a ser ligado).

   Contrato com o HTML:
     [data-promo-fim="2026-11-27T02:59:00Z"]  escopo de uma promoção (ISO, UTC)
     [data-cd]            dentro do escopo: recebe "2 dias" (mais de 24h, parado)
                          ou "04:12:09" (últimas 24h, contando)
     data-promo-heat      escrito aqui no escopo: "dias" | "horas" | "urgente"
                          (urgente = menos de 1h; é o gancho do estilo de urgência)

   Ao zerar, conforme data-promo-expire do escopo:
     "revert" (padrão)  o card volta ao normal: some o que tem [data-promo-only]
                        e cada [data-promo-price] recebe o preço cheio que
                        carrega no próprio atributo
     "remove"           o elemento sai do DOM (card da seção de ofertas,
                        destaque do topo)
     "none"             nada aqui; quem desenhou cuida (modal e carrinho, no app.js)

   RELÂMPAGO: com data-promo-depois="<ISO>" no escopo, ao zerar ele NÃO
   expira: passa para a oferta normal, que vale até aquela data. O escopo
   recebe o novo data-promo-fim, perde .is-relampago, e dentro dele
     [data-depois-text]  recebe o texto do atributo (preço, selo, rótulo)
     [data-depois-href]  vira o novo href do <use> (raio -> relógio)
     data-depois-aria    (no escopo) vira o aria-label
   O evento "promo:expired" dispara do mesmo jeito (o app.js troca os preços).

   [data-promo-group] é removido inteiro quando não sobra nenhuma promoção
   dentro dele, então a seção de ofertas e o destaque somem sem deixar buraco.
   Com data-promo-group="first", o próximo item escondido passa a aparecer:
   é assim que o destaque troca sozinho para a próxima oferta.

   Depois de qualquer expiração dispara o evento "promo:expired" no document.
   =================================================================== */
(function () {
  "use strict";

  var CFG = window.ROYAL || {};
  var HORA = 3600e3;
  var DIA = 86400e3;

  // Relógio do cliente pode estar errado (ou adiantado de propósito). O
  // servidor manda a hora dele na página e trabalhamos com a diferença.
  var desvio = typeof CFG.serverNow === "number" ? CFG.serverNow - Date.now() : 0;
  function agora() { return Date.now() + desvio; }
  function acertar(serverMs) {
    if (typeof serverMs === "number" && isFinite(serverMs)) desvio = serverMs - Date.now();
  }

  function fimDe(el) { return Date.parse(el.getAttribute("data-promo-fim")); }
  function ativa(fimIso) {
    var fim = Date.parse(fimIso);
    return fim > agora(); // NaN > x é false: data inválida = sem promoção
  }

  function dois(n) { return n < 10 ? "0" + n : String(n); }
  function partes(ms) {
    var s = Math.max(Math.floor(ms / 1000), 0);
    return {
      d: Math.floor(s / 86400),
      h: Math.floor((s % 86400) / 3600),
      m: Math.floor((s % 3600) / 60),
      s: s % 60
    };
  }
  /** Com mais de 24h o texto fica PARADO em dias inteiros ("1 dia", "2 dias");
      a contagem regressiva só começa nas últimas 24 horas ("04:12:09").
      Os dias são arredondados para baixo: faltando 2 dias e 21 horas aparece
      "2 dias". Assim o número nunca promete mais tempo do que existe, e a
      passagem de "1 dia" para "23:59:59" acontece sem salto. */
  function texto(ms) {
    var t = partes(ms);
    if (t.d > 0) return t.d + (t.d === 1 ? " dia" : " dias");
    return dois(t.h) + ":" + dois(t.m) + ":" + dois(t.s);
  }

  function pintar(scope, resta) {
    var calor = resta < HORA ? "urgente" : resta < DIA ? "horas" : "dias";
    if (scope.getAttribute("data-promo-heat") !== calor) scope.setAttribute("data-promo-heat", calor);
    var txt = texto(resta);
    var alvos = scope.querySelectorAll("[data-cd]");
    for (var i = 0; i < alvos.length; i++) {
      var el = alvos[i];
      // Um escopo pode conter outro (linha do carrinho dentro de nada, mas o
      // modal dentro do overlay): cada [data-cd] obedece ao escopo mais próximo.
      if (el.closest("[data-promo-fim]") !== scope) continue;
      if (el.textContent !== txt) el.textContent = txt;
    }
  }

  // Só os timers na tela (ou perto dela) são repintados. A EXPIRAÇÃO é
  // conferida em todos, visíveis ou não.
  var visto = typeof WeakSet === "function" ? new WeakSet() : null;
  var visivel = typeof WeakMap === "function" ? new WeakMap() : null;
  var io = null;
  if (visto && visivel && "IntersectionObserver" in window) {
    io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { visivel.set(e.target, e.isIntersecting); });
    }, { rootMargin: "300px" });
  }

  // Relâmpago zerou: o escopo continua em oferta, agora com o preço e o
  // relógio da oferta normal.
  function rebaixar(el, depois) {
    el.setAttribute("data-promo-fim", depois);
    el.removeAttribute("data-promo-depois");
    el.removeAttribute("data-promo-heat");
    el.classList.remove("is-relampago");
    Array.prototype.forEach.call(el.querySelectorAll("[data-depois-text]"), function (n) {
      n.textContent = n.getAttribute("data-depois-text");
      n.removeAttribute("data-depois-text");
    });
    Array.prototype.forEach.call(el.querySelectorAll("[data-depois-href]"), function (n) {
      n.setAttribute("href", n.getAttribute("data-depois-href"));
      n.removeAttribute("data-depois-href");
    });
    var aria = el.getAttribute("data-depois-aria");
    if (aria) { el.setAttribute("aria-label", aria); el.removeAttribute("data-depois-aria"); }
    pintar(el, fimDe(el) - agora());
  }

  function expirar(lista) {
    lista.forEach(function (el) {
      var depois = el.getAttribute("data-promo-depois");
      if (depois && ativa(depois)) { rebaixar(el, depois); return; }
      var modo = el.getAttribute("data-promo-expire") || "revert";
      el.removeAttribute("data-promo-fim");
      el.removeAttribute("data-promo-heat");
      if (io) io.unobserve(el);
      if (modo === "remove") {
        if (el.parentNode) el.parentNode.removeChild(el);
        return;
      }
      if (modo !== "revert") return;
      el.classList.remove("is-promo");
      Array.prototype.forEach.call(el.querySelectorAll("[data-promo-only]"), function (n) {
        n.parentNode.removeChild(n);
      });
      Array.prototype.forEach.call(el.querySelectorAll("[data-promo-price]"), function (n) {
        n.textContent = n.getAttribute("data-promo-price");
      });
      var aria = el.getAttribute("data-promo-aria");
      if (aria) el.setAttribute("aria-label", aria);
    });

    Array.prototype.forEach.call(document.querySelectorAll("[data-promo-group]"), function (g) {
      var restam = g.querySelectorAll("[data-promo-fim]");
      if (!restam.length) {
        if (g.parentNode) g.parentNode.removeChild(g);
        return;
      }
      if (g.getAttribute("data-promo-group") === "first" && restam[0].hidden) {
        restam[0].hidden = false;
        pintar(restam[0], fimDe(restam[0]) - agora());
      }
    });

    document.dispatchEvent(new CustomEvent("promo:expired"));
  }

  var timer = null;

  function tick() {
    var t = agora();
    var escopos = document.querySelectorAll("[data-promo-fim]");
    if (!escopos.length) { parar(); return; }
    var vencidos = [];
    for (var i = 0; i < escopos.length; i++) {
      var el = escopos[i];
      var resta = fimDe(el) - t;
      if (!(resta > 0)) { vencidos.push(el); continue; }
      if (io) {
        if (!visto.has(el)) { visto.add(el); io.observe(el); }
        else if (visivel.get(el) === false) continue;
      }
      pintar(el, resta);
    }
    if (vencidos.length) expirar(vencidos);
  }

  // UM intervalo para a página inteira, e só enquanto existir promoção nela.
  function ligar() {
    if (timer === null && !document.hidden) timer = setInterval(tick, 1000);
  }
  function parar() {
    if (timer !== null) { clearInterval(timer); timer = null; }
  }
  /** Chamado por quem acabou de desenhar um escopo novo (modal, carrinho). */
  function refresh() {
    tick();
    if (document.querySelector("[data-promo-fim]")) ligar();
  }

  // Aba oculta: para. Ao voltar, um tick imediato põe tudo em dia (inclusive
  // o que expirou enquanto ela estava em segundo plano).
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) parar();
    else refresh();
  });
  // Página restaurada do cache de voltar/avançar: o tempo passou sem o
  // intervalo rodar.
  window.addEventListener("pageshow", function (e) { if (e.persisted) refresh(); });

  window.PROMO = { now: agora, ativa: ativa, texto: texto, refresh: refresh, acertar: acertar };

  refresh();
})();

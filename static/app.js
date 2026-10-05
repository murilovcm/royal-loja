/* ===================================================================
   ROYAL — Frontend logic
   =================================================================== */
(function () {
  "use strict";

  const CATALOG = JSON.parse(document.getElementById("catalogData").textContent);
  const CFG = window.ROYAL;
  const PALETTE = ["#a855f7","#22d3ee","#f97316","#ec4899","#4ade80","#eab308","#60a5fa","#f43f5e"];
  const byId = (id) => document.getElementById(id);
  const brl = (n) => "R$ " + n.toFixed(2).replace(".", ",");

  // ---------------------------------------------------------------
  // Altura real da tela (--app-vvh)
  // ---------------------------------------------------------------
  // Carrinho e checkout ocupam a tela cheia no mobile (position: fixed +
  // altura via esta variável). Usar só 100dvh não basta: no iOS/Android,
  // quando o teclado abre para digitar endereço/telefone, o viewport de
  // *layout* não encolhe, então um painel com altura fixa em 100% empurra
  // o botão "Finalizar Pedido" pra baixo da tela, atrás do teclado — o
  // cliente não consegue mais confirmar o pedido. window.visualViewport
  // reflete a área realmente visível (já descontando o teclado), então
  // recalculamos essa variável nele para o painel encolher junto.
  // Além da altura, o iOS pode "panorâmicar" o viewport visual (offsetTop)
  // pra tentar mostrar o campo focado, sem o viewport de layout (onde o
  // position:fixed se ancora) se mexer — sem repassar esse deslocamento,
  // o painel fica ancorado no topo errado e some por trás do teclado.
  let lastVvh = -1, lastVvTop = -1;
  // O painel só deve SEGUIR o visualViewport enquanto um campo dele está focado
  // (teclado/seletor aberto). Com o teclado FECHADO, o iOS Safari às vezes deixa
  // o visualViewport "preso" com a altura e o offsetTop do teclado — se
  // continuássemos lendo dele, o painel ficaria encolhido e deslocado pra baixo
  // mesmo sem teclado (o bug do vídeo). Então, sem campo focado, ignoramos o
  // visualViewport e usamos a viewport de layout cheia (window.innerHeight,
  // top 0), que é sempre confiável quando não há teclado.
  function panelFieldFocused() {
    const ae = document.activeElement;
    return !!(ae && ae.closest && ae.closest(".cart-sidebar, .checkout-panel") &&
              /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName));
  }
  function setAppVvh() {
    const vv = window.visualViewport;
    let h, top;
    if (vv && panelFieldFocused()) {
      // Campo focado: teclado provavelmente aberto -> acompanha a área visível.
      h = Math.round(vv.height);
      top = Math.round(vv.offsetTop);
    } else {
      // Nada focado (teclado fechado): viewport cheia, sem deslocamento.
      h = Math.round(window.innerHeight);
      top = 0;
    }
    // Só escreve nas CSS vars se algo mudou de fato: escrever força recálculo
    // de layout, e o evento "scroll" do visualViewport dispara a cada frame
    // enquanto o cliente rola/digita — sem esse guard, era um dos travamentos.
    if (h === lastVvh && top === lastVvTop) return;
    lastVvh = h; lastVvTop = top;
    document.documentElement.style.setProperty("--app-vvh", h + "px");
    document.documentElement.style.setProperty("--app-vv-top", top + "px");
  }
  // Throttle por requestAnimationFrame: no máximo um recálculo por frame,
  // em vez de um por evento (o visualViewport emite vários por frame).
  let vvRaf = 0;
  function scheduleVvh() {
    if (vvRaf) return;
    vvRaf = requestAnimationFrame(() => { vvRaf = 0; setAppVvh(); });
  }
  setAppVvh();
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", scheduleVvh, { passive: true });
    window.visualViewport.addEventListener("scroll", scheduleVvh, { passive: true });
  } else {
    window.addEventListener("resize", scheduleVvh, { passive: true });
  }
  // Reforço: em algumas versões de iOS o evento "resize"/"scroll" do
  // visualViewport não dispara a tempo (ou não dispara) quando o teclado
  // abre/fecha ao focar um campo dentro do carrinho/checkout — sem esse
  // reforço, --app-vvh/--app-vv-top ficam com o valor de antes do teclado
  // abrir, e o painel fixo é desenhado fora do lugar. Recalcula de novo no
  // focus/blur de qualquer campo, imediatamente e de novo depois que a
  // animação do teclado termina (~350ms).
  document.addEventListener("focusin", (e) => {
    const field = e.target.closest(".cart-sidebar, .checkout-panel");
    if (field) {
      setAppVvh();
      setTimeout(setAppVvh, 350);
      setTimeout(setAppVvh, 700);
      // Depois que o teclado assenta e o painel encolheu (--app-vvh já
      // atualizado), revela o campo focado com o MENOR scroll possível dentro
      // do corpo rolável (.checkout-body/.cart-items — o body está travado).
      // Antes usávamos block:"center" + behavior:"smooth", mas num campo alto
      // (o de endereço, que embute o cartão de GPS + botão) isso empurrava
      // nome/telefone pra fora da tela; e o scroll suave, disparado enquanto o
      // teclado ainda anima, às vezes "capturava" o toque e o formulário
      // parecia travado. "nearest" + instantâneo revela o campo sem esse efeito.
      const control = e.target.closest("input, select, textarea");
      if (control && control.scrollIntoView) {
        setTimeout(() => {
          try { control.scrollIntoView({ block: "nearest", behavior: "auto" }); }
          catch (_) { control.scrollIntoView(); }
        }, 380);
      }
    }
  });
  document.addEventListener("focusout", (e) => {
    if (e.target.closest(".cart-sidebar, .checkout-panel")) {
      // Ao sair do campo / fechar o teclado, força a restauração da altura.
      // Zera o cache (lastVvh/lastVvTop) antes de recalcular para reescrever as
      // CSS vars MESMO se algum "resize" do visualViewport tiver sido perdido no
      // fechamento do teclado — era isso que deixava o painel "encolhido e
      // travado" com o teclado já fechado (bug do vídeo).
      // NÃO recalculamos de forma síncrona aqui: durante o focusout o
      // document.activeElement pode já ser o <body> mesmo quando o foco está
      // apenas migrando para OUTRO campo (o teclado continua aberto). Recalcular
      // agora encheria o painel por 1 frame e ele encolheria de novo (piscada).
      // Nos timers abaixo, se outro campo foi focado, setAppVvh mantém encolhido;
      // se não, restaura a altura cheia. setAppVvh agora usa window.innerHeight
      // quando nenhum campo está focado, então independe de valores presos do iOS.
      const restore = () => { lastVvh = -1; lastVvTop = -1; setAppVvh(); };
      setTimeout(restore, 60);
      setTimeout(restore, 350);
      setTimeout(restore, 700);
    }
  });

  // ---------------------------------------------------------------
  // Trava de rolagem do body (carrinho/checkout abertos)
  // ---------------------------------------------------------------
  // overflow:hidden sozinho não impede o Safari/iOS de rolar a página POR
  // BAIXO do painel fixo quando um campo de texto ganha foco — o navegador
  // tenta "subir" a página pra revelar o campo mesmo com overflow:hidden,
  // e é exatamente isso que faz o carrinho/checkout parecer esmagado ao
  // digitar. Travar o body em position:fixed (em vez de só overflow)
  // impede essa rolagem nativa por completo. Contador em vez de booleano
  // porque abrir o checkout fecha o carrinho primeiro (destrava e trava
  // de novo em sequência).
  let lockedScrollY = 0;
  let lockCount = 0;
  function lockBodyScroll() {
    if (lockCount === 0) {
      lockedScrollY = window.scrollY;
      document.body.style.position = "fixed";
      document.body.style.top = `-${lockedScrollY}px`;
      document.body.style.left = "0";
      document.body.style.right = "0";
      document.body.style.overflow = "hidden";
    }
    lockCount++;
  }
  function unlockBodyScroll() {
    lockCount = Math.max(0, lockCount - 1);
    if (lockCount === 0) {
      document.body.style.position = "";
      document.body.style.top = "";
      document.body.style.left = "";
      document.body.style.right = "";
      document.body.style.overflow = "";
      window.scrollTo(0, lockedScrollY);
      // Painel fechado: garante que --app-vvh volte à altura cheia. Se o painel
      // foi fechado com o teclado ainda aberto (ex: toque no ✕), o focusout
      // pode não recalcular a tempo; aqui zeramos o cache e reescrevemos assim
      // que o teclado fecha, evitando deixar valores "encolhidos" para a
      // próxima abertura.
      if (typeof setAppVvh === "function") {
        lastVvh = -1; lastVvTop = -1;
        setAppVvh();
        setTimeout(() => { lastVvh = -1; lastVvTop = -1; setAppVvh(); }, 350);
      }
    }
  }

  // ---------------------------------------------------------------
  // AGE GATE
  // ---------------------------------------------------------------
  (function () {
    const KEY = "royal_age_verified";
    const DURATION_MS = 30 * 24 * 60 * 60 * 1000; // 30 dias
    const gate = byId("ageGate");
    if (!gate) return;

    function isVerified() {
      try {
        const data = JSON.parse(localStorage.getItem(KEY));
        return !!(data && data.expires && Date.now() < data.expires);
      } catch (e) { return false; }
    }

    // O gate é o último elemento do <body> e o conteúdo continua pintado atrás
    // dele (ver a nota no style.css: esconder o conteúdo faria o Googlebot
    // indexar a loja como uma tela de verificação de idade). Como o conteúdo
    // está visível, ele também continuaria alcançável pelo Tab — daí o `inert`
    // no resto do body enquanto a idade não é confirmada.
    //
    // `inert` tira interação, foco e leitura por leitor de tela SEM esconder
    // nada visualmente, então não recria o problema de indexação. Em navegador
    // antigo que não o suporta, a degradação é só a ordem de tabulação passar
    // por trás do vidro — o overlay continua bloqueando clique e rolagem.
    function setPageInert(on) {
      Array.prototype.forEach.call(document.body.children, (el) => {
        if (el === gate) return;
        if (on) el.setAttribute("inert", "");
        else el.removeAttribute("inert");
      });
    }

    if (isVerified()) {
      document.documentElement.classList.add("age-ok");
    } else {
      document.body.style.overflow = "hidden";
      setPageInert(true);
      const yesBtn = byId("ageGateYes");
      if (yesBtn) setTimeout(() => yesBtn.focus(), 50);
    }

    byId("ageGateYes").addEventListener("click", () => {
      try {
        localStorage.setItem(KEY, JSON.stringify({ expires: Date.now() + DURATION_MS }));
      } catch (e) {}
      gate.classList.add("age-gate-hide");
      document.documentElement.classList.add("age-ok");
      document.body.style.overflow = "";
      setPageInert(false);
    });

    byId("ageGateNo").addEventListener("click", () => {
      gate.classList.add("denied");
    });
  })();

  // ---------------------------------------------------------------
  // PROMO POP-UP — sutil, dispensável, aparece uma vez por versão de conteúdo.
  // Só entra em cena depois que o age gate foi liberado.
  // ---------------------------------------------------------------
  (function () {
    const pop = byId("promoPop");
    if (!pop || (CFG && CFG.editor)) return;

    const SEEN_KEY = "royal_promo_seen";
    const COOLDOWN_MS = 12 * 60 * 60 * 1000; // não repetir a mesma promo por 12h
    const DELAY_MS = 1300;

    // Assinatura do conteúdo: se o painel mudar título/cupom/mensagem, o pop-up
    // volta a aparecer mesmo pra quem já tinha visto a promo anterior.
    const sig = (() => {
      const t = (byId("promoPopTitle") ? byId("promoPopTitle").textContent : "") + "|" +
                (byId("promoPopCode") ? byId("promoPopCode").textContent : "") + "|" +
                (pop.querySelector(".promo-pop-msg") ? pop.querySelector(".promo-pop-msg").textContent : "");
      let h = 0;
      for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) | 0;
      return String(h);
    })();

    function alreadySeen() {
      try {
        const raw = JSON.parse(localStorage.getItem(SEEN_KEY) || "null");
        return !!(raw && raw.sig === sig && (Date.now() - raw.ts) < COOLDOWN_MS);
      } catch (e) { return false; }
    }
    function markSeen() {
      try { localStorage.setItem(SEEN_KEY, JSON.stringify({ sig: sig, ts: Date.now() })); } catch (e) {}
    }

    let shown = false, closed = false;
    function open() {
      if (shown || closed || alreadySeen()) return;
      shown = true;
      pop.hidden = false;
      requestAnimationFrame(() => pop.classList.add("show"));
      markSeen();
    }
    function close() {
      if (closed) return;
      closed = true;
      pop.classList.remove("show");
      setTimeout(() => { pop.hidden = true; }, 340);
    }

    pop.querySelectorAll("[data-promo-close]").forEach((el) => el.addEventListener("click", close));
    const cta = pop.querySelector("[data-promo-cta]");
    if (cta) cta.addEventListener("click", close);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && shown && !closed) close(); });

    const copyBtn = byId("promoPopCopy");
    if (copyBtn) {
      copyBtn.addEventListener("click", () => {
        const codeEl = byId("promoPopCode");
        const code = codeEl ? codeEl.textContent.trim() : "";
        const done = () => {
          const orig = copyBtn.dataset.label || copyBtn.textContent;
          copyBtn.dataset.label = orig;
          copyBtn.textContent = "Copiado ✓";
          copyBtn.classList.add("copied");
          setTimeout(() => { copyBtn.textContent = orig; copyBtn.classList.remove("copied"); }, 1600);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(code).then(done).catch(done);
        } else {
          done();
        }
      });
    }

    // Espera o age gate liberar antes de mostrar (não competir com o modal 18+).
    if (document.documentElement.classList.contains("age-ok")) {
      setTimeout(open, DELAY_MS);
    } else {
      const yes = byId("ageGateYes");
      if (yes) yes.addEventListener("click", () => setTimeout(open, DELAY_MS + 300), { once: true });
    }
  })();

  // ---------------------------------------------------------------
  // SUBLINHA ROTATIVA DE AVISOS (faixa do topo)
  // ---------------------------------------------------------------
  // As mensagens vêm do painel (site_config.announce_messages, uma por linha)
  // e já chegam renderizadas empilhadas na mesma célula de grid. Aqui só
  // trocamos qual está com a classe .is-on; a transição é 100% CSS.
  // --header-h alimenta o `top` da faixa grudada. Medido, não fixo: a altura
  // do header muda com o breakpoint e com o tamanho do logo que cada loja
  // configura, então um valor cravado no CSS dessincronizaria em alguma das
  // três lojas e a faixa ficaria flutuando ou escondida atrás do header.
  (function trackHeaderHeight() {
    const header = document.querySelector("header.site-header");
    if (!header) return;
    const apply = () => {
      document.documentElement.style.setProperty(
        "--header-h", Math.round(header.getBoundingClientRect().height) + "px"
      );
    };
    apply();
    if ("ResizeObserver" in window) new ResizeObserver(apply).observe(header);
    else window.addEventListener("resize", apply, { passive: true });
  })();

  (function initAnnounce() {
    const bar = byId("announceBar");
    if (!bar) return;
    const msgs = Array.from(bar.querySelectorAll(".announce-msg"));
    // Uma mensagem só não gira: ficaria piscando sem motivo.
    if (msgs.length < 2) return;
    // Quem pede menos movimento TAMBÉM vê todas as mensagens: o CSS troca o
    // rolo por um fade simples dentro do prefers-reduced-motion. Parar aqui
    // escondia o frete grátis e as formas de pagamento dessas pessoas.
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const segs = Array.from(bar.querySelectorAll(".announce-segs i"));

    const HOLD_MS = 4800;
    // Casa com a saída de .announce-msg.is-off no CSS (220ms), com folga.
    const EXIT_MS = 300;
    // Dedo parado mais que isso deixa de ser toque e vira "segurar": pausa.
    const PRESS_MS = 220;
    // Deslocamento lateral mínimo para o gesto contar como deslize.
    const SWIPE_PX = 30;
    const HINT_KEY = "announceHintSeen";

    let i = 0;
    let timer = null;
    let startedAt = 0;
    let remaining = HOLD_MS;
    let held = false;
    let rotations = 0;

    // Os traços usam a MESMA duração da rotação; um valor só, aqui.
    segs.forEach((s) => s.style.setProperty("--seg-dur", HOLD_MS + "ms"));

    // A seta de pista aparece até o primeiro toque. Depois some pelo resto da
    // sessão: quem já descobriu o gesto não precisa ser lembrado a cada página.
    let hintSeen = false;
    try { hintSeen = sessionStorage.getItem(HINT_KEY) === "1"; } catch (e) {}
    if (hintSeen) bar.classList.add("touched");
    function markTouched() {
      bar.classList.add("touched");
      bar.classList.remove("hint-go");
      if (hintSeen) return;
      hintSeen = true;
      try { sessionStorage.setItem(HINT_KEY, "1"); } catch (e) {}
    }

    // Traço da mensagem atual recomeça do zero; os anteriores ficam cheios.
    function paintSegs() {
      segs.forEach((s, k) => {
        s.classList.toggle("done", k < i);
        s.classList.remove("run");
      });
      if (!segs[i]) return;
      void segs[i].offsetWidth; // reinicia a animação do traço
      segs[i].classList.add("run");
    }

    function show(n, dir) {
      if (n === i) return;
      const prev = msgs[i];
      const nx = msgs[n];
      // A direção muda onde as mensagens em repouso esperam (embaixo ao
      // avançar, em cima ao voltar). O reflow aplica esse repouso ANTES da
      // entrada, senão a anterior entraria pelo lado errado.
      bar.dataset.dir = dir;
      nx.classList.remove("is-off");
      void nx.offsetWidth;
      prev.classList.remove("is-on");
      prev.classList.add("is-off");
      // Terminada a saída, volta ao repouso num salto invisível. A checagem
      // cobre o toque rápido que traz a mesma mensagem de volta nesse meio-tempo.
      setTimeout(() => {
        if (!prev.classList.contains("is-on")) prev.classList.remove("is-off");
      }, EXIT_MS);
      nx.classList.add("is-on");
      i = n;
      paintSegs();
      rotations++;
      if (rotations === 1 && !hintSeen && !reduceMotion) bar.classList.add("hint-go");
    }

    // Só gira quando alguém pode ver e ninguém está segurando: aba em segundo
    // plano (bateria, e sem a fila de trocas acumuladas ao voltar), faixa
    // recolhida porque o cliente abriu um produto (.is-done) ou dedo apoiado.
    const canRun = () => !document.hidden && !bar.classList.contains("is-done") && !held;

    function schedule(ms = HOLD_MS) {
      clearTimeout(timer);
      timer = null;
      if (!canRun()) {
        bar.classList.add("is-paused");
        return;
      }
      bar.classList.remove("is-paused");
      remaining = ms;
      startedAt = performance.now();
      timer = setTimeout(() => {
        show((i + 1) % msgs.length, "fwd");
        schedule();
      }, ms);
    }

    // Segurar: guarda quanto faltava para o traço congelado continuar de onde
    // parou quando o dedo sair.
    function pause() {
      if (!timer) return;
      clearTimeout(timer);
      timer = null;
      remaining = Math.max(remaining - (performance.now() - startedAt), 250);
      bar.classList.add("is-paused");
    }

    function go(step) {
      show((i + step + msgs.length) % msgs.length, step > 0 ? "fwd" : "back");
      schedule();
    }

    // Ao reaparecer (aba de volta, produto fechado), a mensagem em tela ganha
    // o tempo inteiro de novo, em vez de trocar logo depois de voltar.
    function sync() {
      if (canRun()) {
        paintSegs();
        schedule();
      } else {
        clearTimeout(timer);
        timer = null;
        bar.classList.add("is-paused");
      }
    }
    document.addEventListener("visibilitychange", sync);
    // .is-done é ligado e desligado por openModal/closeModal. Observar a classe
    // aqui mantém a regra da rotação num lugar só. Filtra só a virada de
    // .is-done: esta mesma função mexe em is-paused/hint-go/touched na faixa, e
    // reagir a elas reiniciaria o traço a cada pausa.
    let wasDone = bar.classList.contains("is-done");
    new MutationObserver(() => {
      const isDone = bar.classList.contains("is-done");
      if (isDone === wasDone) return;
      wasDone = isDone;
      sync();
    }).observe(bar, { attributes: true, attributeFilter: ["class"] });

    // ---- Toque: tocar avança, segurar pausa, deslizar navega ----
    let down = false;
    let x0 = 0;
    let y0 = 0;
    let pressTimer = null;
    bar.addEventListener("pointerdown", (e) => {
      if (e.button > 0) return;
      down = true;
      x0 = e.clientX;
      y0 = e.clientY;
      markTouched();
      // Captura: o pointerup chega mesmo se o dedo sair da faixa no deslize.
      try { bar.setPointerCapture(e.pointerId); } catch (err) {}
      pressTimer = setTimeout(() => {
        held = true;
        pause();
      }, PRESS_MS);
    });
    bar.addEventListener("pointerup", (e) => {
      if (!down) return;
      down = false;
      clearTimeout(pressTimer);
      const wasHeld = held;
      held = false;
      const dx = e.clientX - x0;
      const dy = e.clientY - y0;
      if (Math.abs(dx) >= SWIPE_PX && Math.abs(dx) > Math.abs(dy)) go(dx < 0 ? 1 : -1);
      else if (wasHeld) schedule(remaining);
      else go(1);
    });
    // O navegador assumiu o gesto (rolagem vertical da página): solta a pausa.
    bar.addEventListener("pointercancel", () => {
      if (!down) return;
      down = false;
      clearTimeout(pressTimer);
      if (held) {
        held = false;
        schedule(remaining);
      }
    });
    // Teclado: a faixa é focável (tabindex no template).
    bar.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        markTouched();
        go(1);
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        markTouched();
        go(-1);
      }
    });

    sync();
  })();

  // ---------------------------------------------------------------
  // STORE STATUS (aberta/fechada) — todos os dias, 10h às 23h (Brasília)
  // ---------------------------------------------------------------
  (function () {
    const el = byId("storeStatus");
    if (!el) return;
    const textEl = el.querySelector(".store-status-text");
    const OPEN_HOUR = 10;
    const CLOSE_HOUR = 23;

    function update() {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/Sao_Paulo",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).formatToParts(new Date());
      const hour = Number(parts.find((p) => p.type === "hour").value);
      const minute = Number(parts.find((p) => p.type === "minute").value);
      const totalMin = hour * 60 + minute;
      const isOpen = totalMin >= OPEN_HOUR * 60 && totalMin < CLOSE_HOUR * 60;

      el.classList.toggle("open", isOpen);
      el.classList.toggle("closed", !isOpen);
      textEl.textContent = isOpen ? "Loja aberta agora" : "Loja fechada no momento";
    }

    update();
    setInterval(update, 60000);
  })();

  // ---- Cart state (apenas em memória — zera a cada recarregamento da página) ----
  let cart = [];
  try { localStorage.removeItem("royal_cart"); } catch (e) {}
  const saveCart = () => {};

  // ---- Acessório: cabo USB-C ----
  // Produto ÚNICO vindo do painel (site_config -> get_cable() no app.py). No
  // carrinho ele usa um flavor_id RESERVADO, em string: os sabores têm id
  // numérico, então "cable" nunca colide com eles — e, de quebra, um cupom
  // restrito a modelos já o ignora sozinho, porque a lista de ids permitidos
  // que vem de /api/coupon/apply só contém números.
  const CABLE = CFG.cable || { enabled: false, name: "", price: 0, image: "" };
  const CABLE_ID = "cable";
  const cableIndex = () => cart.findIndex((it) => it.flavor_id === CABLE_ID);
  const cableInCart = () => cableIndex() !== -1;
  function cableSubtotal() {
    const i = cableIndex();
    return i === -1 ? 0 : cart[i].price * cart[i].qty;
  }
  // Rótulo de um item para os toasts. O cabo não tem sabor, e "Cabo USB-C • "
  // com o bullet solto no fim parece texto quebrado.
  const itemLabel = (it) =>
    it.flavor_name ? `${it.model_name} • ${it.flavor_name}` : it.model_name;

  // ---------------------------------------------------------------
  // TOAST
  // ---------------------------------------------------------------
  let toastTimer;
  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }
  function toast(title, subtitle, variant) {
    const t = byId("toast");
    t.innerHTML = subtitle
      ? `<span class="toast-icon">${variant === "success" ? "✓" : "•"}</span>
         <span class="toast-body"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(subtitle)}</span></span>`
      : `<span class="toast-body"><strong>${escapeHtml(title)}</strong></span>`;
    t.classList.toggle("toast-success", variant === "success");
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2000);
  }

  // ---------------------------------------------------------------
  // CATALOG FILTER + SEARCH
  // ---------------------------------------------------------------
  const grid = byId("catalogGrid");
  const cards = Array.from(grid.querySelectorAll(".model-card"));
  let activeFilter = "all";

  function applyFilter() {
    const q = (byId("searchInput").value || "").toLowerCase().trim();
    let visible = 0;
    cards.forEach((c) => {
      const matchSearch = !q ||
        c.dataset.name.includes(q) || c.dataset.brandname.includes(q);
      let matchFilter = true;
      if (activeFilter === "best") matchFilter = c.dataset.best === "1";
      else if (activeFilter.startsWith("brand-")) matchFilter = c.dataset.brand === activeFilter.split("-")[1];
      const show = matchSearch && matchFilter;
      c.style.display = show ? "" : "none";
      if (show) visible++;
    });
    byId("catalogCount").textContent = visible + " modelo" + (visible !== 1 ? "s" : "");

    // Estado vazio: diz O QUE não foi achado e dá a saída. Antes era um
    // "Nenhum modelo encontrado 🔍" genérico, que deixava o cliente sem saber
    // se errou a busca ou se o filtro estava atrapalhando.
    let empty = grid.querySelector(".empty-msg");
    if (visible === 0) {
      if (!empty) {
        empty = document.createElement("div");
        empty.className = "empty-msg";
        grid.appendChild(empty);
      }
      const termo = (byId("searchInput").value || "").trim();
      const filtrando = activeFilter !== "all";
      empty.innerHTML = "";

      const titulo = document.createElement("p");
      titulo.className = "empty-msg-title";
      if (termo) {
        // Nome do produto entra como nó de texto, nunca via innerHTML.
        titulo.append("Nenhum produto encontrado para ");
        const forte = document.createElement("strong");
        forte.textContent = "“" + termo + "”";
        titulo.append(forte);
      } else {
        titulo.textContent = "Nenhum produto nesta categoria";
      }
      empty.appendChild(titulo);

      const dica = document.createElement("p");
      dica.className = "empty-msg-hint";
      dica.textContent = filtrando && termo
        ? "Talvez o produto esteja em outra marca. Toque abaixo para buscar no catálogo inteiro."
        : filtrando
          ? "Esta marca está sem produtos no momento."
          : "Confira a grafia ou tente pelo nome da marca.";
      empty.appendChild(dica);

      if (filtrando || termo) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "empty-msg-reset";
        btn.textContent = "Ver todos os produtos";
        btn.addEventListener("click", () => {
          byId("searchInput").value = "";
          const todos = byId("filterBar").querySelector('.pill[data-filter="all"]');
          if (todos) todos.click();
          else applyFilter();
        });
        empty.appendChild(btn);
      }
    } else if (empty) empty.remove();
  }

  byId("filterBar").addEventListener("click", (e) => {
    const pill = e.target.closest(".pill");
    if (!pill) return;
    byId("filterBar").querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
    pill.classList.add("active");
    activeFilter = pill.dataset.filter;
    applyFilter();
  });
  byId("searchInput").addEventListener("input", applyFilter);
  applyFilter();

  // Hero chips -> reusa o filtro do catálogo e rola até ele
  const heroChips = byId("heroChips");
  if (heroChips) {
    heroChips.addEventListener("click", (e) => {
      const chip = e.target.closest(".hero-chip");
      if (!chip) return;
      const pill = byId("filterBar").querySelector(`.pill[data-filter="${chip.dataset.filter}"]`);
      if (pill) pill.click();
      byId("catalogo").scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  // ---------------------------------------------------------------
  // MODAL
  // ---------------------------------------------------------------
  const overlay = byId("modalOverlay");
  let modalState = { model: null, flavor: null, qty: 1 };

  function imgHTML(model, phSize) {
    // alt descritivo: marca + modelo, igual ao card. Antes era só o modelo.
    if (model.image_url) {
      return `<img src="${model.image_url}" alt="${escapeHtml(model.brand_name)} ${escapeHtml(model.name)}" decoding="async">`;
    }
    return `<span class="ph">${escapeHtml(model.name[0])}</span>`;
  }

  // Foto/puffs/título do modal seguem a VERSÃO do sabor escolhido. Sem sabor
  // escolhido, mostram o modelo principal. É o que deixa claro que "Lush Ice"
  // vem no aparelho Slim, e não no que o cliente clicou na grade.
  function applyFlavorContext(model, flavor) {
    const alt = flavor && flavor.version_label;
    // Versão sem foto própria cai na foto do principal: melhor mostrar o produto
    // certo com a foto da geração anterior do que o placeholder de letra.
    byId("modalImg").innerHTML = imgHTML(
      alt
        ? { ...model, name: flavor.version_name, image_url: flavor.version_image || model.image_url }
        : model
    );
    byId("modalName").textContent = alt ? flavor.version_name : model.name;

    const puffsEl = byId("modalPuffs");
    puffsEl.innerHTML = '<i class="ico-bolt"></i> ';
    puffsEl.append(alt ? flavor.version_puffs : model.puff_count);

    // Texto do aviso montado com nós de texto, nunca innerHTML com dado do
    // painel — mesma regra do badge de puffs logo acima.
    //
    // São DOIS avisos independentes, empilhados: o de versão (fato sobre o
    // aparelho) e o do próprio sabor. Um sabor de versão com aviso próprio
    // mostra os dois, nessa ordem — o de versão nunca é engolido, porque é ele
    // que diz qual aparelho o cliente vai receber.
    const disc = byId("modalDisclaimer");
    disc.textContent = "";
    disc.hidden = !alt;
    if (alt) {
      const txt = document.createElement("span");
      txt.append("Este sabor é da versão ");
      const b = document.createElement("b");
      b.textContent = flavor.version_label;
      txt.append(b);
      // O lojista digita a nota sem se preocupar com pontuação, então fecha-se a
      // frase aqui — senão sai "mesma bateria 8.000 puffs." tudo emendado.
      if (flavor.version_note) {
        txt.append(` — ${fecharFrase(flavor.version_note)}`);
      } else {
        txt.append(".");
      }
      if (flavor.version_puffs) txt.append(` ${flavor.version_puffs}.`);
      disc.append(iconeAviso(), txt);
    }

    const fnote = byId("modalFlavorNote");
    const note = flavor ? (flavor.note || "").trim() : "";
    fnote.textContent = "";
    fnote.hidden = !note;
    if (note) {
      const txt = document.createElement("span");
      txt.textContent = fecharFrase(note);
      fnote.append(iconeAviso(), txt);
    }
  }

  function iconeAviso() {
    const ic = document.createElement("span");
    ic.className = "fd-ic";
    ic.setAttribute("aria-hidden", "true");
    ic.textContent = "ⓘ";
    return ic;
  }

  // Fecha a frase que o lojista digitou solta, sem duplicar pontuação que ele
  // já tenha posto.
  function fecharFrase(txt) {
    const t = txt.trim();
    return `${t}${/[.!?…]$/.test(t) ? "" : "."}`;
  }

  function openModal(model) {
    // O cliente abriu um produto: a faixa de avisos sai de cena para não roubar
    // espaço de quem está decidindo. Volta quando ele fecha o produto e retoma a
    // navegação (ver closeModal) — some enquanto decide, reaparece ao continuar.
    const announceBar = byId("announceBar");
    if (announceBar) announceBar.classList.add("is-done");

    modalState = { model, flavor: null, qty: 1 };
    byId("modalBrand").textContent = model.brand_name;
    // Sem sabor escolhido ainda, o contexto é o do modelo principal (foto,
    // puffs e título), e o aviso de versão fica escondido.
    applyFlavorContext(model, null);
    byId("qtyVal").textContent = "1";

    const inStock = model.flavors.filter((f) => f.is_in_stock);
    const fg = byId("modalFlavors");
    if (inStock.length === 0) {
      fg.innerHTML = `<span style="color:var(--text-dim);font-size:.85rem">Sem sabores em estoque no momento.</span>`;
    } else {
      // A etiqueta da versão vai DENTRO do pill: o mesmo sabor pode existir em
      // duas versões com preços diferentes ("Grape Ice" no padrão e no antigo),
      // então ela precisa viajar colada ao nome para o cliente saber qual é qual.
      fg.innerHTML = inStock.map((f, i) =>
        `<button class="flavor-pill" data-fid="${f.id}">
           <span class="dot" style="background:${f.color || PALETTE[i % PALETTE.length]}"></span>${escapeHtml(f.name)}${
             f.version_label ? `<span class="vtag">${escapeHtml(f.version_label)}</span>` : ""
           }
         </button>`).join("");
    }
    updateModalTotal();
    overlay.classList.add("open");
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    overlay.classList.remove("open");
    document.body.style.overflow = "";
    // O cliente saiu do produto — seja para ver outro, seja depois de adicionar
    // ao carrinho (que também passa por aqui). Voltou a navegar, então a faixa
    // de avisos volta com ele. Reaparece com a própria transição de slide.
    const announceBar = byId("announceBar");
    if (announceBar) announceBar.classList.remove("is-done");
  }

  function updateModalTotal() {
    const addBtn = byId("addBtn");
    if (!modalState.flavor) {
      byId("modalTotal").textContent = brl(0);
      addBtn.disabled = true;
      addBtn.textContent = "Selecione um sabor";
      return;
    }
    const total = modalState.flavor.price * modalState.qty;
    byId("modalTotal").textContent = brl(total);
    addBtn.disabled = false;
    addBtn.textContent = "Adicionar ao Carrinho";
  }

  byId("modalFlavors").addEventListener("click", (e) => {
    const pill = e.target.closest(".flavor-pill");
    if (!pill) return;
    const fid = Number(pill.dataset.fid);
    // Resolve o sabor no catálogo em vez de ler nome/preço de volta do DOM:
    // assim o objeto vem completo (inclusive os campos de versão) e nenhum dado
    // do painel precisa transitar por atributo HTML.
    const flavor = modalState.model.flavors.find((f) => f.id === fid);
    if (!flavor) return;
    byId("modalFlavors").querySelectorAll(".flavor-pill").forEach((p) => p.classList.remove("selected"));
    pill.classList.add("selected");
    modalState.flavor = flavor;
    // Trocou para um sabor de outra versão: foto, puffs, título e aviso acompanham.
    applyFlavorContext(modalState.model, flavor);
    updateModalTotal();
  });

  byId("qtyMinus").addEventListener("click", () => {
    if (modalState.qty > 1) { modalState.qty--; byId("qtyVal").textContent = modalState.qty; updateModalTotal(); }
  });
  byId("qtyPlus").addEventListener("click", () => {
    modalState.qty++; byId("qtyVal").textContent = modalState.qty; updateModalTotal();
  });

  byId("addBtn").addEventListener("click", () => {
    if (!modalState.flavor) return;
    const m = modalState.model;
    const f = modalState.flavor;
    // Nome e foto vêm da VERSÃO do sabor, não do card que o cliente clicou:
    // o pedido precisa dizer "V150 Slim" para o lojista separar o aparelho certo.
    const versionName = f.version_name || m.name;
    const existing = cart.find((it) => it.flavor_id === f.id);
    if (existing) existing.qty += modalState.qty;
    else cart.push({
      flavor_id: f.id,
      model_name: versionName,
      brand_name: m.brand_name,
      flavor_name: f.name,
      price: f.price,
      qty: modalState.qty,
      image_url: f.version_image || m.image_url || "",
    });
    saveCart();
    renderCart();
    closeModal();
    openCart();
    toast("Adicionado ao carrinho", `${versionName} • ${f.name}`, "success");
  });

  byId("modalClose").addEventListener("click", closeModal);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeModal(); closeCart(); closeNav(); } });

  // Card -> abre o modal de sabores. Comportamento IDÊNTICO ao de antes: o
  // alvo é o card inteiro, um toque só, e o botão do canto inferior direito
  // continua sendo afordância visual (não tem handler próprio, então não há
  // como disparar duas vezes).
  //
  // O que entrou: teclado. O card agora é role="button" tabindex="0" no
  // template, então Enter e Espaço precisam abrir o modal como o clique. Antes
  // a grade inteira era inalcançável sem mouse ou toque.
  function openCardModal(card) {
    if (CFG.editor) return;
    const id = Number(card.dataset.id);
    const model = CATALOG.find((m) => m.id === id);
    if (model) openModal(model);
  }
  document.querySelectorAll(".model-card").forEach((card) => {
    card.addEventListener("click", () => openCardModal(card));
    card.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
      // Espaço rola a página por padrão; num controle isso é comportamento errado.
      e.preventDefault();
      openCardModal(card);
    });
  });

  // ---------------------------------------------------------------
  // CART SIDEBAR
  // ---------------------------------------------------------------
  const cartSidebar = byId("cartSidebar");
  const cartOverlay = byId("cartOverlay");

  function openCart() { cartSidebar.classList.add("open"); cartOverlay.classList.add("open"); lockBodyScroll(); }
  function closeCart() { cartSidebar.classList.remove("open"); cartOverlay.classList.remove("open"); unlockBodyScroll(); }

  byId("cartClose").addEventListener("click", closeCart);
  cartOverlay.addEventListener("click", closeCart);

  // Voltar ao catálogo sem perder o carrinho: quem quer um segundo modelo não
  // precisa fechar tudo e rolar a página do topo de novo.
  byId("cartAddMoreBtn").addEventListener("click", () => {
    closeCart();
    byId("catalogo").scrollIntoView({ behavior: "smooth", block: "start" });
  });

  const cartFab = byId("cartFab");
  cartFab.addEventListener("click", openCart);

  // ---------------------------------------------------------------
  // NAV SIDEBAR (menu 3 pontinhos)
  // ---------------------------------------------------------------
  const navSidebar = byId("navSidebar");
  const navOverlay = byId("navOverlay");
  const navToggle = byId("navToggle");
  function openNav() {
    navSidebar.classList.add("open"); navOverlay.classList.add("open");
    navSidebar.setAttribute("aria-hidden", "false");
    if (navToggle) navToggle.setAttribute("aria-expanded", "true");
    lockBodyScroll();
  }
  function closeNav() {
    navSidebar.classList.remove("open"); navOverlay.classList.remove("open");
    navSidebar.setAttribute("aria-hidden", "true");
    if (navToggle) navToggle.setAttribute("aria-expanded", "false");
    unlockBodyScroll();
  }
  if (navToggle) navToggle.addEventListener("click", openNav);
  byId("navClose").addEventListener("click", closeNav);
  navOverlay.addEventListener("click", closeNav);
  // Categorias -> reusa o filtro do catálogo, rola até ele e fecha o menu
  navSidebar.querySelectorAll(".nav-side-cat").forEach((btn) => {
    btn.addEventListener("click", () => {
      const pill = byId("filterBar").querySelector(`.pill[data-filter="${btn.dataset.filter}"]`);
      if (pill) pill.click();
      closeNav();
      byId("catalogo").scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  function renderCart() {
    const box = byId("cartItems");
    const totalCount = cart.reduce((s, it) => s + it.qty, 0);
    byId("cartFabBadge").textContent = totalCount;
    cartFab.classList.toggle("show", totalCount > 0);

    if (cart.length === 0) {
      box.innerHTML = `<div class="cart-empty"><svg class="ico big" aria-hidden="true"><use href="#i-cart"></use></svg>Seu carrinho está vazio.</div>`;
      resetCoupon();
      byId("whatsappBtn").disabled = true;
      return;
    }

    // A linha de oferta do cabo fica colada no ÚLTIMO produto da lista, e uma
    // só: o cabo é do pedido inteiro, não daquele sabor, então repeti-la sob
    // cada item seria ruído sem oferecer nada a mais.
    let lastProduct = -1;
    for (let i = cart.length - 1; i >= 0; i--) {
      if (!cart[i].is_cable) { lastProduct = i; break; }
    }
    const showOffer = CABLE.enabled && !cableInCart() && lastProduct !== -1;

    box.innerHTML = cart.map((it, idx) => {
      const img = it.image_url
        ? `<img src="${it.image_url}" alt="" decoding="async">`
        : `<span class="ph">${escapeHtml(it.model_name[0])}</span>`;
      // O cabo é um item de pedido como os outros, mas sem sabor e sem
      // controle de quantidade: a decisão dele é binária (ver addCable).
      const row = it.is_cable
        ? `<div class="cart-item is-cable">
             <div class="ci-img">${img}</div>
             <div class="ci-info">
               <div class="m">${escapeHtml(it.model_name)}</div>
               <div class="f accessory">Acessório</div>
               <div class="p">${brl(it.price)}</div>
             </div>
             <div class="ci-right">
               <button class="rm" data-idx="${idx}" title="Remover" aria-label="Remover ${escapeHtml(it.model_name)} do carrinho"><svg class="ico" aria-hidden="true"><use href="#i-trash"></use></svg></button>
             </div>
           </div>`
        : `<div class="cart-item">
             <div class="ci-img">${img}</div>
             <div class="ci-info">
               <div class="m">${it.model_name}</div>
               <div class="f">${it.flavor_name}</div>
               <div class="p">${brl(it.price)}</div>
             </div>
             <div class="ci-right">
               <button class="rm" data-idx="${idx}" title="Remover" aria-label="Remover ${escapeHtml(it.model_name)} do carrinho"><svg class="ico" aria-hidden="true"><use href="#i-trash"></use></svg></button>
               <div class="ci-qty">
                 <button data-act="dec" data-idx="${idx}">−</button>
                 <span>${it.qty}</span>
                 <button data-act="inc" data-idx="${idx}">+</button>
               </div>
             </div>
           </div>`;
      return row + (showOffer && idx === lastProduct ? cableOfferHtml() : "");
    }).join("");

    updateTotals();
    byId("whatsappBtn").disabled = false;
  }

  // ---- Coupon (aplicado no carrinho, vale para o checkout também) ----
  let appliedCoupon = null; // { code, type: 'percent'|'fixed', value }

  // Acréscimo para pagamento com cartão de crédito (5% sobre o total já com
  // desconto e frete). Só incide quando a forma de pagamento é "Crédito".
  const CREDIT_SURCHARGE_RATE = 0.05;
  function creditSurcharge(base) {
    const paymentEl = byId("custPayment");
    return paymentEl && paymentEl.value === "Crédito" ? base * CREDIT_SURCHARGE_RATE : 0;
  }

  function cartTotal() {
    return cart.reduce((s, it) => s + it.price * it.qty, 0);
  }

  // Subtotal sobre o qual o cupom incide. Cupom sem restrição (productIds nulo)
  // vale para o carrinho inteiro; cupom restrito só conta os itens cujos sabores
  // pertencem aos modelos permitidos (productIds vem da rota /api/coupon/apply).
  function couponBase(coupon) {
    if (!coupon) return 0;
    // O cabo fica FORA de qualquer cupom: é acessório de margem fina, e o papel
    // dele é cruzar o limiar do frete, não ser descontado. No cupom restrito
    // isso já aconteceria sozinho (o id dele não é numérico, então nunca está
    // na lista de permitidos), mas o caso geral precisa ser explícito — senão
    // as duas regras divergem e só uma delas protege o acessório.
    if (!coupon.productIds) return cartTotal() - cableSubtotal();
    const allowed = new Set(coupon.productIds);
    return cart.reduce((s, it) => (allowed.has(it.flavor_id) ? s + it.price * it.qty : s), 0);
  }

  function computeDiscount(coupon) {
    if (!coupon) return 0;
    const base = couponBase(coupon);
    if (coupon.type === "percent") return base * (coupon.value / 100);
    return Math.min(coupon.value, base);
  }

  // Fonte única de verdade do dinheiro do pedido. É consumida tanto pelo resumo
  // na tela (updateTotals) quanto pela mensagem do WhatsApp — antes cada um
  // refazia a conta por conta própria, então toda regra nova precisava ser
  // escrita duas vezes e bastava esquecer uma para a tela e a mensagem enviada
  // ao cliente discordarem sobre quanto ele vai pagar.
  function computeOrderTotals() {
    const total = cartTotal();
    const discount = computeDiscount(appliedCoupon);
    const discountedTotal = Math.max(total - discount, 0);

    const fs = CFG.freeShip || {};
    const freeShipEnabled = !!fs.enabled && fs.min > 0;
    // O mínimo é medido sobre o valor DEPOIS do cupom: é o que o cliente
    // realmente paga pelos produtos, então cupom e frete grátis não se somam
    // em cima de um ticket que não chegou ao valor exigido.
    const qualifiesByValue = freeShipEnabled && discountedTotal >= fs.min;

    // Frete: só existe depois que o cliente usa a geolocalização no checkout (e não pediu retirada).
    const pickup = pickupCheckbox.checked;
    const hasNumericShipping = !pickup && !!(shippingInfo && shippingInfo.ok && typeof shippingInfo.price === "number");
    // Bolsão ("a combinar", price null) e endereço fora da área nunca entram:
    // não têm preço numérico, então não há o que zerar.
    const zoneEligible = hasNumericShipping && shippingInfo.price <= fs.maxZone;
    const freeShipping = qualifiesByValue && zoneEligible;

    const shippingFull = hasNumericShipping ? shippingInfo.price : 0;
    const shippingPrice = freeShipping ? 0 : shippingFull;

    const surchargeBase = discountedTotal + shippingPrice;
    const surcharge = creditSurcharge(surchargeBase);

    // Frete barato demais para virar argumento: nas zonas mais próximas dizer
    // "economia de R$ 8,00" diminui o benefício em vez de reforçá-lo. Nesses
    // casos o cliente vê só que ganhou o frete, sem o valor em reais.
    const showSaving = freeShipping && shippingFull >= (fs.minSaving || 0);

    return {
      total, discount, discountedTotal, pickup, hasNumericShipping,
      freeShipping, showSaving, shippingFull, shippingPrice, surcharge,
      finalTotal: surchargeBase + surcharge,
      // Progresso da barra do carrinho. Não depende da zona: ali o site ainda
      // não sabe onde o cliente mora (a zona só sai do GPS, no checkout).
      freeShipEnabled,
      freeShipMin: fs.min,
      remaining: freeShipEnabled ? Math.max(fs.min - discountedTotal, 0) : 0,
      pct: freeShipEnabled ? Math.min(discountedTotal / fs.min, 1) : 0,
      // Quanto faltaria para o frete grátis SEM o cabo no carrinho. É sobre
      // ESTE número que a oferta "alavanca" decide se aparece. Medida com o
      // cabo já dentro, a condição viraria falsa no instante em que ele entra
      // e a oferta se apagaria justo na hora de confirmar o sucesso.
      // A subtração é exata porque o cabo nunca entra no desconto do cupom
      // (ver couponBase), então ele não deixa resíduo em discountedTotal.
      cableGap: freeShipEnabled
        ? Math.max(fs.min - (discountedTotal - cableSubtotal()), 0)
        : 0
    };
  }

  // A oferta "alavanca" só aparece quando o cabo REALMENTE fecha o frete:
  // 0 < falta <= preço do cabo. Fora disso o cliente vê só a linha discreta
  // na lista. A regra é de VALOR e não de quantidade de itens justamente por
  // isso: dois vapes baratos ainda deixam faltar mais do que o cabo cobre, e
  // prometer "o cabo fecha o frete" ali seria mentira.
  function shouldShowLever(t) {
    if (!CABLE.enabled || !t.freeShipEnabled) return false;
    return t.cableGap > 0 && t.cableGap <= CABLE.price;
  }

  function addCable() {
    if (!CABLE.enabled || cableInCart()) return;
    // Sempre UM cabo. A oferta aparece em até dois lugares (a linha na lista e
    // a alavanca na barra) e tocar os dois não pode somar dois cabos.
    cart.push({
      flavor_id: CABLE_ID,
      is_cable: true,
      model_name: CABLE.name,
      brand_name: "Acessório",
      flavor_name: "",
      price: CABLE.price,
      qty: 1,
      image_url: CABLE.image || ""
    });
    saveCart();
    renderCart();
    toast("Adicionado ao carrinho", CABLE.name, "success");
  }

  function removeCable() {
    const i = cableIndex();
    if (i === -1) return;
    const name = cart[i].model_name;
    cart.splice(i, 1);
    saveCart();
    renderCart();
    toast("Removido do carrinho", name);
  }

  // A linha discreta, colada no último produto da lista. Deliberadamente NÃO
  // fala de frete grátis: essa promessa é exclusiva da alavanca, que só surge
  // quando ela é verdadeira. Aqui a linha aparece em todo carrinho, inclusive
  // nos que ainda precisam de R$ 150 — prometer o frete seria mentir.
  // A linha inteira é o botão: alvo de toque grande e um único rótulo no
  // leitor de tela, em vez de um "+" solto sem contexto.
  function cableOfferHtml() {
    return `<button type="button" class="cable-offer" data-cable="add"
      aria-label="Adicionar ${escapeHtml(CABLE.name)} ao pedido por ${brl(CABLE.price)}">
      <span class="co-ico"><svg class="ico" aria-hidden="true"><use href="#i-cable"></use></svg></span>
      <span class="co-txt">Levar um <strong>${escapeHtml(CABLE.name)}</strong> para carregar</span>
      <span class="co-price">${brl(CABLE.price)}</span>
      <span class="co-plus" aria-hidden="true">+</span>
    </button>`;
  }

  // A oferta "alavanca" vive DENTRO da barra de frete porque é a barra que ela
  // completa: a listra tracejada marca exatamente o pedaço que o cabo cobre.
  function renderCableLever(t, done, ico) {
    const lever = byId("cableLever");
    const ghost = byId("freeShipGhost");
    const on = shouldShowLever(t);

    // A listra só existe enquanto falta algo: depois de fechado não há pedaço
    // a completar, e deixá-la ali sugeriria que ainda falta.
    const showGhost = on && !done;
    ghost.hidden = !showGhost;
    if (showGhost) ghost.style.left = (t.pct * 100).toFixed(1) + "%";

    if (!on) {
      lever.hidden = true;
      lever.innerHTML = "";
      return;
    }
    lever.hidden = false;
    lever.innerHTML = cableInCart()
      ? `<div class="fu-done">
           <span class="fu-ok">${ico("i-check")} O cabo fechou o frete</span>
           <button type="button" class="fu-rm" data-cable="remove">Remover</button>
         </div>`
      : `<div class="fu-offer">
           <span class="fu-bolt">${ico("i-bolt")}</span>
           <span class="fu-txt">
             <strong>Um ${escapeHtml(CABLE.name)} <em>fecha o frete</em></strong>
             <span class="fu-sub">${brl(CABLE.price)} · a listra acima é o que falta</span>
           </span>
           <button type="button" class="fu-add" data-cable="add">Adicionar</button>
         </div>`;
  }

  // Barra "faltam R$ X para o frete grátis", no rodapé do carrinho.
  function renderFreeShipBar(t) {
    const bar = byId("freeShipBar");
    if (!t.freeShipEnabled || cart.length === 0) {
      bar.style.display = "none";
      return;
    }
    bar.style.display = "block";

    const done = t.remaining <= 0;
    bar.classList.toggle("done", done);
    byId("freeShipFill").style.width = (t.pct * 100).toFixed(1) + "%";

    const ico = (name) => `<svg class="ico" aria-hidden="true"><use href="#${name}"></use></svg>`;
    if (done) {
      byId("freeShipMsg").innerHTML = ico("i-check") + " <strong>Frete grátis liberado!</strong>";
      // Ressalva deliberada: o carrinho promete o frete grátis sem saber a zona
      // do cliente. Quem cair em bolsão ("a combinar") não recebe o benefício,
      // e descobrir isso só no checkout parece propaganda enganosa.
      byId("freeShipNote").textContent = "válido para as zonas de entrega";
    } else {
      byId("freeShipMsg").innerHTML =
        ico("i-truck") + ` Faltam <strong>${brl(t.remaining)}</strong> para o frete grátis`;
      byId("freeShipNote").textContent = "";
    }
    renderCableLever(t, done, ico);
  }

  function updateTotals() {
    const t = computeOrderTotals();
    const showDiscount = !!(appliedCoupon && t.discount > 0);

    const cartDiscountRow = byId("cartDiscountRow");
    cartDiscountRow.style.display = showDiscount ? "flex" : "none";
    if (showDiscount) {
      byId("cartDiscountCode").textContent = `(${appliedCoupon.code})`;
      byId("cartDiscountValue").textContent = "-" + brl(t.discount);
    }
    byId("cartTotal").textContent = brl(t.discountedTotal);

    const checkoutDiscountRow = byId("checkoutDiscountRow");
    checkoutDiscountRow.style.display = showDiscount ? "flex" : "none";
    if (showDiscount) {
      byId("checkoutDiscountCode").textContent = `(${appliedCoupon.code})`;
      byId("checkoutDiscountValue").textContent = "-" + brl(t.discount);
    }

    renderFreeShipBar(t);

    const checkoutShippingRow = byId("checkoutShippingRow");
    const checkoutShippingWas = byId("checkoutShippingWas");
    checkoutShippingRow.style.display = t.hasNumericShipping ? "flex" : "none";
    checkoutShippingRow.classList.toggle("free", t.freeShipping);
    if (t.hasNumericShipping) {
      byId("checkoutShippingZone").textContent = `(${shippingInfo.zone_label})`;
      if (t.freeShipping) {
        // Mostra o valor que seria cobrado, riscado: a economia fica concreta
        // em vez de virar só a palavra "grátis". Só que abaixo do minSaving o
        // riscado sai de cena — ali o número trabalha contra a oferta.
        checkoutShippingWas.style.display = t.showSaving ? "" : "none";
        if (t.showSaving) checkoutShippingWas.textContent = brl(t.shippingFull);
        byId("checkoutShippingValue").textContent = "GRÁTIS";
      } else {
        checkoutShippingWas.style.display = "none";
        byId("checkoutShippingValue").textContent = brl(t.shippingFull);
      }
    } else {
      checkoutShippingWas.style.display = "none";
    }

    const freeShipBanner = byId("checkoutFreeShipBanner");
    freeShipBanner.style.display = t.freeShipping ? "flex" : "none";
    if (t.freeShipping) {
      byId("checkoutFreeShipSaved").textContent =
        t.showSaving ? `Economia de ${brl(t.shippingFull)}` : "Entrega por nossa conta";
    }

    const checkoutShippingNote = byId("checkoutShippingNote");
    if (t.pickup) {
      checkoutShippingNote.textContent = "🏪 Retirada no local, sem frete";
      checkoutShippingNote.className = "geo-status show ok";
    } else if (shippingInfo && !t.hasNumericShipping) {
      checkoutShippingNote.textContent = shippingInfo.message || "";
      checkoutShippingNote.className = "geo-status show " + (shippingInfo.ok ? "warn" : "danger");
    } else {
      checkoutShippingNote.textContent = "";
      checkoutShippingNote.className = "geo-status";
    }

    const checkoutSurchargeRow = byId("checkoutSurchargeRow");
    checkoutSurchargeRow.style.display = t.surcharge > 0 ? "flex" : "none";
    if (t.surcharge > 0) {
      byId("checkoutSurchargeValue").textContent = "+" + brl(t.surcharge);
    }

    byId("checkoutTotal").textContent = brl(t.finalTotal);
  }

  function setCouponFeedback(msg, variant) {
    const el = byId("couponFeedback");
    el.textContent = msg;
    el.className = "coupon-feedback show " + variant;
  }

  function resetCoupon() {
    appliedCoupon = null;
    const input = byId("couponInput");
    input.value = "";
    input.disabled = false;
    byId("couponApplyBtn").textContent = "Aplicar";
    const fb = byId("couponFeedback");
    fb.textContent = "";
    fb.className = "coupon-feedback";
    updateTotals();
  }

  byId("couponApplyBtn").addEventListener("click", async () => {
    const btn = byId("couponApplyBtn");
    if (appliedCoupon) { resetCoupon(); return; }

    const input = byId("couponInput");
    const code = input.value.trim().toUpperCase();
    if (!code) { setCouponFeedback("Digite um cupom", "error"); return; }

    btn.disabled = true;
    try {
      const r = await fetch("/api/coupon/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code,
          total: cartTotal(),
          items: cart.map((it) => ({ flavor_id: it.flavor_id, price: it.price, qty: it.qty })),
        }),
      });
      const data = await r.json();
      if (data.ok) {
        appliedCoupon = { code: data.code, type: data.type, value: data.value, productIds: data.product_ids || null };
        const discount = computeDiscount(appliedCoupon);
        setCouponFeedback(
          appliedCoupon.type === "percent"
            ? `Cupom aplicado! -${appliedCoupon.value}%`
            : `Cupom aplicado! -${brl(discount)}`,
          "success"
        );
        input.disabled = true;
        btn.textContent = "Remover";
      } else {
        appliedCoupon = null;
        setCouponFeedback(data.error || "Cupom inválido ou inativo", "error");
      }
    } catch (e) {
      setCouponFeedback("Erro ao validar cupom. Tente novamente.", "error");
    }
    btn.disabled = false;
    updateTotals();
  });

  byId("couponInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); byId("couponApplyBtn").click(); }
  });

  // Oferta do cabo. Vem ANTES das demais checagens: a linha é um <button> que
  // não carrega data-idx, então cairia no ramo de quantidade com idx NaN.
  function handleCableClick(e) {
    const btn = e.target.closest("[data-cable]");
    if (!btn) return false;
    e.preventDefault();
    if (btn.dataset.cable === "add") addCable();
    else removeCable();
    return true;
  }

  byId("cartItems").addEventListener("click", (e) => {
    if (handleCableClick(e)) return;
    const rm = e.target.closest(".rm");
    if (rm) {
      const idx = Number(rm.dataset.idx);
      const item = cart[idx];
      const row = rm.closest(".cart-item");
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reduced || !row) {
        cart.splice(idx, 1); saveCart(); renderCart();
        if (item) toast("Removido do carrinho", itemLabel(item));
        return;
      }
      row.style.maxHeight = row.offsetHeight + "px";
      row.classList.add("removing");
      void row.offsetHeight;
      row.style.maxHeight = "0px";
      setTimeout(() => { cart.splice(idx, 1); saveCart(); renderCart(); }, 320);
      if (item) toast("Removido do carrinho", itemLabel(item));
      return;
    }
    const qb = e.target.closest("[data-act]");
    if (qb) {
      const idx = Number(qb.dataset.idx);
      const item = cart[idx];
      if (!item) return;
      if (qb.dataset.act === "inc") {
        cart[idx].qty++;
        toast("Adicionado ao carrinho", `${item.model_name} • ${item.flavor_name}`, "success");
      } else {
        cart[idx].qty--;
        if (cart[idx].qty < 1) cart.splice(idx, 1);
        toast("Removido do carrinho", `${item.model_name} • ${item.flavor_name}`);
      }
      saveCart(); renderCart();
    }
  });

  // A alavanca vive dentro da barra de frete, no rodapé do carrinho — fora do
  // #cartItems, então precisa do seu próprio ponto de escuta.
  byId("freeShipBar").addEventListener("click", handleCableClick);

  // ---------------------------------------------------------------
  // CHECKOUT PANEL
  // ---------------------------------------------------------------
  const checkoutPanel = byId("checkoutPanel");
  const checkoutOverlay = byId("checkoutOverlay");
  let geoCoords = null;

  function openCheckout() {
    if (cart.length === 0) return;
    renderCheckoutSummary();
    updateCheckoutBtnState(); // começa desabilitado se os campos estiverem vazios
    closeCart();
    checkoutPanel.classList.add("open");
    checkoutOverlay.classList.add("open");
    lockBodyScroll();
  }
  function closeCheckout() {
    checkoutPanel.classList.remove("open");
    checkoutOverlay.classList.remove("open");
    unlockBodyScroll();
  }

  byId("whatsappBtn").addEventListener("click", openCheckout);
  byId("checkoutClose").addEventListener("click", closeCheckout);
  checkoutOverlay.addEventListener("click", closeCheckout);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeCheckout(); });

  function renderCheckoutSummary() {
    const box = byId("checkoutItems");
    box.innerHTML = cart.map((it) => {
      const sub = it.price * it.qty;
      return `<div class="checkout-item">
        <span class="qty">${it.qty}x</span>
        <div class="ci-info">
          <div class="m">${it.model_name}</div>
          <div class="f${it.is_cable ? " accessory" : ""}">${it.is_cable ? "Acessório" : it.flavor_name}</div>
        </div>
        <span class="p">${brl(sub)}</span>
      </div>`;
    }).join("");
    updateTotals();
  }

  // ---- Phone mask (Brazilian) ----
  function maskPhoneBR(value) {
    let v = value.replace(/\D/g, "").slice(0, 11);
    if (v.length > 10) v = v.replace(/^(\d{2})(\d{5})(\d{0,4}).*/, "($1) $2-$3");
    else if (v.length > 6) v = v.replace(/^(\d{2})(\d{4})(\d{0,4}).*/, "($1) $2-$3");
    else if (v.length > 2) v = v.replace(/^(\d{2})(\d{0,5})/, "($1) $2");
    else if (v.length > 0) v = v.replace(/^(\d{0,2})/, "($1");
    return v;
  }
  byId("custPhone").addEventListener("input", (e) => {
    e.target.value = maskPhoneBR(e.target.value);
    updateCheckoutBtnState();
  });

  // ---- Geolocation ----
  const geoBtn = byId("geoBtn");
  const geoBtnDefaultText = geoBtn.textContent;
  let geoAccuracy = null;
  // Cliente é OBRIGADO a pressionar o botão de localização antes de finalizar
  // (só para entrega). Basta a TENTATIVA: se der qualquer problema (permissão
  // negada, timeout, sem suporte), geoAttempted já fica true e o pedido segue.
  let geoAttempted = false;
  let shippingInfo = null; // resultado de /api/shipping/calc: { ok, special, zone_label, price, message }

  // ---- Retirada no local ----
  const pickupCheckbox = byId("custPickup");
  const addressField = byId("addressField");
  function isPickup() { return pickupCheckbox.checked; }
  pickupCheckbox.addEventListener("change", () => {
    addressField.style.display = isPickup() ? "none" : "";
    updateTotals();
    updateCheckoutBtnState();
  });

  function setGeoStatus(text, level) {
    const statusEl = byId("geoStatus");
    statusEl.textContent = text;
    statusEl.className = `geo-status show${level ? " " + level : ""}`;
  }

  function setGeoLoading(loading) {
    geoBtn.disabled = loading;
    geoBtn.textContent = loading ? "📡 Buscando localização..." : geoBtnDefaultText;
  }

  async function fetchShipping() {
    if (!geoCoords) { shippingInfo = null; updateTotals(); return; }
    try {
      const r = await fetch("/api/shipping/calc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lat: geoCoords.lat, lng: geoCoords.lng }),
      });
      shippingInfo = await r.json();
    } catch (e) {
      shippingInfo = { ok: false, price: null, zone_label: null, message: "Não foi possível calcular o frete agora. Tente novamente." };
    }
    updateTotals();
  }

  geoBtn.addEventListener("click", () => {
    geoBtn.classList.add("geo-used");
    // Marca a tentativa: a partir daqui o pedido pode ser finalizado mesmo que
    // a localização falhe (permissão negada, timeout, sem suporte).
    geoAttempted = true;
    geoBtn.classList.remove("geo-required");
    if (!navigator.geolocation) {
      geoCoords = null;
      geoAccuracy = null;
      shippingInfo = null;
      updateTotals();
      setGeoStatus("⚠️ Geolocalização não suportada neste navegador. Preencha o endereço manualmente.", "warn");
      return;
    }
    setGeoLoading(true);
    setGeoStatus("📡 Obtendo localização...", "");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        geoCoords = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        geoAccuracy = pos.coords.accuracy;
        setGeoLoading(false);
        const acc = Math.round(geoAccuracy);
        if (acc <= 50) {
          setGeoStatus("✓ Localização precisa capturada", "ok");
        } else if (acc <= 500) {
          setGeoStatus(`⚠ Localização aproximada (~${acc} metros). Confirme o endereço acima para garantir a entrega`, "warn");
        } else {
          setGeoStatus("⚠ Localização imprecisa. Por favor confirme bem o endereço digitado", "danger");
        }
        fetchShipping();
      },
      (err) => {
        geoCoords = null;
        geoAccuracy = null;
        shippingInfo = null;
        updateTotals();
        setGeoLoading(false);
        let msg;
        switch (err.code) {
          case err.PERMISSION_DENIED:
            msg = "Você não permitiu o acesso à localização. Sem problema, preencha o endereço acima que o entregador chega até você.";
            break;
          case err.POSITION_UNAVAILABLE:
            msg = "Não foi possível obter sua localização agora. Confirme o endereço no campo acima.";
            break;
          case err.TIMEOUT:
            msg = "A localização demorou demais. Confirme o endereço no campo acima.";
            break;
          default:
            msg = "Não foi possível obter sua localização. Confirme o endereço no campo acima.";
        }
        setGeoStatus(msg, "warn");
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );
  });

  // ---- Validation + send ----
  function setFieldError(inputEl, errEl, hasError) {
    inputEl.classList.toggle("invalid", hasError);
    if (errEl) errEl.classList.toggle("show", hasError);
    return hasError;
  }

  // Habilita "Confirmar e Enviar no WhatsApp" só quando os campos obrigatórios
  // de contato estão preenchidos — mesmo padrão do modal de produto ("Selecione
  // um sabor" + botão desabilitado). Telefone usa o mesmo limite da validação
  // (>=10 dígitos). Pagamento continua validado no clique (mostra erro no campo).
  // Endereço é opcional: na entrega o botão de localização já é obrigatório.
  function updateCheckoutBtnState() {
    const nameOk = byId("custName").value.trim().length > 0;
    const phoneOk = byId("custPhone").value.replace(/\D/g, "").length >= 10;
    byId("checkoutConfirmBtn").disabled = !(nameOk && phoneOk);
  }
  byId("custName").addEventListener("input", updateCheckoutBtnState);
  // Recalcula o total ao trocar a forma de pagamento (acréscimo do crédito).
  byId("custPayment").addEventListener("change", () => {
    setFieldError(byId("custPayment"), byId("errPayment"), false);
    updateTotals();
  });

  byId("checkoutConfirmBtn").addEventListener("click", () => {
    if (cart.length === 0) return;

    const nameEl = byId("custName");
    const phoneEl = byId("custPhone");
    const addressEl = byId("custAddress");
    const paymentEl = byId("custPayment");
    const notesEl = byId("custNotes");

    const pickup = pickupCheckbox.checked;
    const nameVal = nameEl.value.trim();
    const phoneDigits = phoneEl.value.replace(/\D/g, "");
    const addressVal = addressEl.value.trim();
    const paymentVal = paymentEl.value;

    let hasError = false;
    if (setFieldError(nameEl, byId("errName"), nameVal.length === 0)) hasError = true;
    if (setFieldError(phoneEl, byId("errPhone"), phoneDigits.length < 10)) hasError = true;
    if (setFieldError(paymentEl, byId("errPayment"), paymentVal.length === 0)) hasError = true;

    if (hasError) {
      const firstInvalid = checkoutPanel.querySelector(".invalid");
      if (firstInvalid) firstInvalid.focus({ preventScroll: false });
      toast("Preencha os campos obrigatórios");
      return;
    }

    // Obrigatório PRESSIONAR o botão de localização antes de finalizar (entrega).
    // Se a localização deu qualquer problema, geoAttempted já é true (o cliente
    // tentou), então o pedido pode seguir mesmo sem coordenadas.
    if (!pickup && !geoAttempted) {
      geoBtn.classList.add("geo-required");
      setGeoStatus("👆 Toque em \"Usar minha localização atual\" e permita o acesso à localização para confirmar seu endereço e finalizar o pedido.", "warn");
      try { geoBtn.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (_) {}
      toast("Confirme sua localização para finalizar");
      return;
    }

    // Marcador neutro: a coroa era o símbolo do Royal e ia junto nos pedidos
    // enviados pelas outras lojas servidas por este mesmo código.
    let msg = `🛒 *PEDIDO ${CFG.storeName.toUpperCase()}*\n`;
    msg += `━━━━━━━━━━━━━━━\n\n`;
    let total = 0;
    cart.forEach((it, i) => {
      const sub = it.price * it.qty;
      total += sub;
      msg += `*${i + 1}. ${it.model_name}*\n`;
      // O cabo não tem sabor. Mandar "Sabor:" vazio faria quem separa o pedido
      // procurar um sabor que não existe.
      msg += it.is_cable ? `   🔌 Acessório\n` : `   🍬 Sabor: ${it.flavor_name}\n`;
      msg += `   📦 Qtd: ${it.qty}x  •  ${brl(it.price)}\n`;
      msg += `   💰 Subtotal: ${brl(sub)}\n\n`;
    });
    msg += `━━━━━━━━━━━━━━━\n`;
    const t = computeOrderTotals();
    const discount = t.discount;
    if (appliedCoupon) {
      // Cupom restrito: o "-X%" sozinho engana (incide só sobre parte do carrinho),
      // então mostramos também o valor real descontado.
      const pct = "-" + appliedCoupon.value + "%";
      const discountLabel = appliedCoupon.type === "percent"
        ? (appliedCoupon.productIds ? `${pct} (${brl(discount)})` : pct)
        : "-" + brl(discount);
      msg += `🏷️ *Cupom aplicado:* ${appliedCoupon.code}\n`;
      msg += `💸 *Desconto:* ${discountLabel}\n`;
    }

    if (pickup) {
      msg += `🏪 *Retirada no local* (sem frete)\n`;
    } else if (shippingInfo) {
      if (t.freeShipping) {
        // Explicita que o frete foi zerado POR REGRA — senão a equipe não sabe
        // se foi promoção ou esquecimento. O valor isento só entra acima do
        // minSaving: o cliente lê esta mensagem antes de enviar, e nas zonas
        // baratas ver "isento de R$ 8,00" desvaloriza o que ele acabou de
        // ganhar. A zona vai junto de qualquer jeito, então a equipe consegue
        // recuperar o valor pela tabela.
        msg += `🚚 *Frete:* GRÁTIS (${shippingInfo.zone_label}) — pedido acima de ${brl(t.freeShipMin)}`;
        msg += t.showSaving ? `, isento de ${brl(t.shippingFull)}\n` : `\n`;
      } else if (t.hasNumericShipping) {
        msg += `🚚 *Frete:* ${brl(t.shippingFull)} (${shippingInfo.zone_label})\n`;
      } else {
        msg += `🚚 *Frete:* ${shippingInfo.message}\n`;
      }
    }

    const surcharge = t.surcharge;
    if (surcharge > 0) {
      msg += `💳 *Acréscimo cartão de crédito (5%):* +${brl(surcharge)}\n`;
    }
    if (t.hasNumericShipping || surcharge > 0) {
      msg += `💰 *TOTAL FINAL: ${brl(t.finalTotal)}*\n\n`;
    } else if (appliedCoupon) {
      msg += `💰 *Total com desconto: ${brl(t.finalTotal)}*\n\n`;
    } else {
      msg += `*TOTAL: ${brl(total)}*\n\n`;
    }
    msg += `👤 *Cliente:* ${nameVal}\n`;
    msg += `📱 *Telefone:* ${phoneEl.value}\n`;
    if (pickup) msg += `🏪 *Retirada:* no local\n`;
    else if (addressVal) msg += `📍 *Endereço:* ${addressVal}\n`;
    else msg += `📍 *Endereço:* não informado\n`;
    msg += `💳 *Pagamento:* ${paymentVal}\n`;
    if (byId("custLoyalty").checked) msg += `🎁 *Cartão fidelidade:* sim, quero receber\n`;
    if (notesEl.value.trim()) msg += `📝 *Obs:* ${notesEl.value.trim()}\n`;
    if (!pickup && geoCoords) {
      let mapNote = "";
      if (geoAccuracy != null && geoAccuracy > 500) {
        mapNote = ` (localização aproximada, ~${Math.round(geoAccuracy)} metros, confira o endereço)`;
      }
      msg += `🗺️ *Localização:* https://maps.google.com/?q=${geoCoords.lat},${geoCoords.lng}${mapNote}\n`;
    } else if (!pickup) {
      // Entrega sem coordenadas: o cliente apertou o botão mas a localização não
      // veio (permissão negada, timeout, sem suporte). Sinaliza para a equipe
      // calcular o frete na mão pelo endereço, já que não dá para calcular sozinho.
      // Sem endereço também, só resta combinar com o cliente.
      msg += addressVal
        ? `⚠️ *Localização não capturada, calcular o frete manualmente pelo endereço acima.*\n`
        : `⚠️ *Localização e endereço não informados, confirmar com o cliente.*\n`;
    }
    msg += `\nOlá! Gostaria de finalizar este pedido. 🚀`;

    const url = `https://wa.me/${CFG.whatsapp}?text=${encodeURIComponent(msg)}`;
    window.open(url, "_blank");
    closeCheckout();
    toast("Pedido enviado ✓");
  });

  renderCart();

  // ---------------------------------------------------------------
  // SKELETON DA FOTO DO PRODUTO
  // ---------------------------------------------------------------
  // A caixa da foto mostra um brilho varrendo enquanto a imagem baixa (CSS).
  // Aqui só marcamos quando cada uma terminou, para ela aparecer com um fade
  // e o brilho parar. Imagem que veio do cache já chega com .complete = true,
  // então nesse caso a marcação é imediata e não há piscada.
  (function initImageSkeleton() {
    document.querySelectorAll(".model-card .card-img img").forEach((img) => {
      if (img.complete && img.naturalWidth > 0) {
        img.classList.add("is-loaded");
        return;
      }
      img.addEventListener("load", () => img.classList.add("is-loaded"), { once: true });
      // Falha de rede (comum em 4G ruim): revela mesmo assim, senão a caixa
      // fica brilhando para sempre num produto que nunca vai pintar.
      img.addEventListener("error", () => img.classList.add("is-loaded"), { once: true });
    });
  })();

  // ---------------------------------------------------------------
  // SCROLL REVEAL (fade + deslize sutil ao entrar na viewport)
  // ---------------------------------------------------------------
  (function initScrollReveal() {
    const targets = Array.from(document.querySelectorAll(".hero, .section:not([data-hidden]), .model-card"));
    if (!targets.length) return;

    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReducedMotion || !("IntersectionObserver" in window)) {
      targets.forEach((el) => el.classList.add("reveal-visible"));
      return;
    }

    const STAGGER_MS = 55;
    const MAX_STAGGER_STEPS = 4; // além disso, mesmo atraso (evita cascata longa demais)

    const reveal = (el, delay) => {
      if (delay) setTimeout(() => el.classList.add("reveal-visible"), delay);
      else el.classList.add("reveal-visible");
    };

    const observer = new IntersectionObserver(
      (entries, obs) => {
        let batchIndex = 0;
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const el = entry.target;
          obs.unobserve(el);
          reveal(el, Math.min(batchIndex, MAX_STAGGER_STEPS) * STAGGER_MS);
          batchIndex++;
        });
      },
      // limiar baixo + margem inferior: o elemento começa a surgir assim que
      // entra pela base da tela, em vez de "pipocar" já visível.
      { threshold: 0.08, rootMargin: "0px 0px -8% 0px" }
    );

    // Passe inicial: o que JÁ está na primeira tela é revelado na hora.
    // O threshold de 0.08 é calculado sobre a altura TOTAL do elemento, então
    // uma seção alta que aparece só pela borda inferior não atinge o limiar e
    // ficava invisível até a rede de segurança de 3s. Isso não incomodava
    // enquanto o hero era grande e empurrava tudo para fora da tela; com o
    // hero mais curto, a seção "Mais Vendidos" caiu exatamente nessa faixa e
    // o cliente via um vazio ao abrir a loja.
    let initialIndex = 0;
    const vh = window.innerHeight;
    targets.forEach((el) => {
      if (el.getBoundingClientRect().top < vh) {
        reveal(el, Math.min(initialIndex, MAX_STAGGER_STEPS) * STAGGER_MS);
        initialIndex++;
      } else {
        observer.observe(el);
      }
    });

    // Rede de segurança (acessibilidade): se algo não for observado/revelado em
    // até 3s, garante que nada fique invisível.
    setTimeout(() => {
      targets.forEach((el) => {
        if (!el.classList.contains("reveal-visible")) {
          const r = el.getBoundingClientRect();
          if (r.top < window.innerHeight) el.classList.add("reveal-visible");
        }
      });
    }, 3000);
  })();

  // ---------------------------------------------------------------
  // LIVE EDITOR
  // ---------------------------------------------------------------
  if (CFG.editor) {
    // contenteditable -> save on blur
    document.querySelectorAll("[data-cfg][contenteditable=true]").forEach((el) => {
      el.addEventListener("blur", () => {
        const key = el.dataset.cfg;
        const value = el.textContent.trim();
        fetch("/api/update_config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key, value }),
        }).then((r) => r.json()).then(() => toast("Salvo ✓")).catch(() => toast("Erro ao salvar"));
      });
      // prevent enter from adding newlines
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); el.blur(); } });
    });

    // Color picker -> inject --primary-yellow
    const picker = byId("colorPicker");
    if (picker) {
      picker.addEventListener("input", (e) => {
        document.documentElement.style.setProperty("--primary-yellow", e.target.value);
      });
      picker.addEventListener("change", (e) => {
        fetch("/api/update_config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: "theme_primary_color", value: e.target.value }),
        }).then(() => toast("Cor salva ✓"));
      });
    }

    // Drag & drop image onto model cards
    document.querySelectorAll(".model-card").forEach((card) => {
      card.addEventListener("dragover", (e) => { e.preventDefault(); card.classList.add("drag-over"); });
      card.addEventListener("dragleave", () => card.classList.remove("drag-over"));
      card.addEventListener("drop", (e) => {
        e.preventDefault();
        card.classList.remove("drag-over");
        const file = e.dataTransfer.files[0];
        if (!file || !file.type.startsWith("image/")) { toast("Solte um arquivo de imagem"); return; }
        const fd = new FormData();
        fd.append("file", file);
        fd.append("model_id", card.dataset.id);
        toast("Enviando imagem...");
        fetch("/api/upload_image", { method: "POST", body: fd })
          .then((r) => r.json())
          .then((data) => {
            if (data.ok) {
              const box = card.querySelector(".card-img");
              box.innerHTML = `<img src="${data.image_url}" alt="" decoding="async">`;
              // update in-memory catalog too
              const m = CATALOG.find((x) => x.id === Number(card.dataset.id));
              if (m) m.image_url = data.image_url;
              toast("Foto atualizada ✓");
            } else toast("Erro no upload");
          })
          .catch(() => toast("Erro no upload"));
      });
    });
  }
})();

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

  // ---- Promoção com hora marcada ----
  // O relógio (já corrigido pela hora do servidor) vem do countdown.js. O
  // fallback existe só para o app.js não quebrar se aquele arquivo falhar ao
  // carregar: sem ele, nenhuma promoção é considerada ativa no navegador e
  // quem decide o preço é a cotação do servidor.
  const PROMO = window.PROMO || { now: () => Date.now(), ativa: () => false, refresh() {}, acertar() {} };
  // Vale para um sabor, um modelo ou um item do carrinho: todos carregam promo_fim.
  const promoOn = (x) => !!(x && x.promo_fim && PROMO.ativa(x.promo_fim));
  // Texto do selo: "R$ 20" quando o desconto é redondo, "R$ 15,50" quando não.
  const descontoCurto = (v) => "R$ " + (Number.isInteger(v) ? String(v) : v.toFixed(2).replace(".", ","));

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
  // STORE STATUS (aberta/fechada) — grade por dia do painel (Brasília)
  // ---------------------------------------------------------------
  (function () {
    const el = byId("storeStatus");
    if (!el) return;
    const textEl = el.querySelector(".store-status-text");
    // CFG.hours: 7 itens indexados como getDay() (0 = domingo), vindos de
    // get_store_hours() no app.py. Sem dado, assume o antigo 10h–23h.
    const HOURS = Array.isArray(CFG.hours) && CFG.hours.length === 7
      ? CFG.hours
      : Array.from({ length: 7 }, () => ({ closed: false, open: "10:00", close: "23:00" }));
    const WEEKDAY = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
    const toMin = (hhmm) => {
      const [h, m] = String(hhmm).split(":").map(Number);
      return h * 60 + m;
    };
    // Janela de um dia em minutos. Fechar às 00:00 (ou no mesmo horário da
    // abertura) vale como 24:00; fechar antes da abertura vira a noite.
    function windowOf(d) {
      if (!d || d.closed) return null;
      const o = toMin(d.open);
      let c = toMin(d.close);
      if (c === 0 || c === o) c = 1440;
      return c > o ? { o, c, overnight: 0 } : { o, c: 1440, overnight: c };
    }

    function update() {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/Sao_Paulo",
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).formatToParts(new Date());
      const get = (t) => parts.find((p) => p.type === t).value;
      const day = WEEKDAY[get("weekday")];
      const totalMin = Number(get("hour")) * 60 + Number(get("minute"));
      const today = windowOf(HOURS[day]);
      const yesterday = windowOf(HOURS[(day + 6) % 7]);
      const isOpen = !!(
        (today && totalMin >= today.o && totalMin < today.c) ||
        (yesterday && totalMin < yesterday.overnight));

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
  // Três camadas, todas combinadas (E entre elas):
  //   1. busca       texto livre: modelo, marca ou SABOR em estoque
  //   2. fileira     Todos / Mais Vendidos / uma marca
  //   3. filtros     painel "Filtros": puffs, sabor, preço, só em oferta, ordem
  // Dentro de um mesmo grupo do painel as opções se SOMAM (25-40 mil OU 40 mil+);
  // entre grupos elas se CRUZAM (esses puffs E gelado E até R$ 140).
  //
  // Nada disso depende de cadastro: tudo sai do catálogo que a página já
  // recebe (puffs do modelo, nomes dos sabores em estoque, preço que vale agora).
  const grid = byId("catalogGrid");
  const cards = Array.from(grid.querySelectorAll(".model-card"));
  let activeFilter = "all";

  // "Açaí" e "acai", "MENTHOL" e "menthol" têm que casar.
  const semAcento = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  // "15.500 Puffs" -> 15500, "50K puffs" -> 50000. Texto que não fala de puffs
  // (ex.: "20mg" de um spray) devolve null: o modelo fica fora das faixas em
  // vez de cair, errado, em "até 10 mil".
  function puffsDe(model) {
    const t = semAcento(model.puff_count);
    if (!t.includes("puff")) return null;
    const mil = t.match(/(\d+(?:[.,]\d+)?)\s*k\b/);
    const n = mil ? Math.round(parseFloat(mil[1].replace(",", ".")) * 1000) : parseInt(t.replace(/\D/g, ""), 10);
    return n >= 1000 ? n : null;
  }

  const FAIXAS_PUFFS = [
    { id: "p10", label: "Até 10 mil", curto: "Até 10 mil puffs", ok: (n) => n <= 10000 },
    { id: "p25", label: "10 a 25 mil", curto: "10 a 25 mil puffs", ok: (n) => n > 10000 && n <= 25000 },
    { id: "p40", label: "25 a 40 mil", curto: "25 a 40 mil puffs", ok: (n) => n > 25000 && n <= 40000 },
    { id: "p40mais", label: "Mais de 40 mil", curto: "Mais de 40 mil puffs", ok: (n) => n > 40000 },
  ];
  const FAIXAS_PRECO = [
    { id: "r100", label: "Até R$ 100", ok: (p) => p <= 100 },
    { id: "r140", label: "R$ 100 a R$ 140", ok: (p) => p > 100 && p <= 140 },
    { id: "r140mais", label: "Acima de R$ 140", ok: (p) => p > 140 },
  ];
  // Famílias de sabor, reconhecidas pelo nome que o lojista já cadastra (em
  // inglês ou português). \b evita que "grape" case com "grapefruit" e afins.
  const SABORES = [
    { id: "gelado", label: "Gelado", re: /\b(ice|icy|iced|frozen|gelad[oa]|gelo)\b|🧊|❄/ },
    { id: "mentolado", label: "Mentolado", re: /\b(mint|minty|menthol|mentol|menta|hortela)\b/ },
    { id: "morango", label: "Morango", re: /\b(strawberry|morango)\b/ },
    { id: "uva", label: "Uva", re: /\b(grape|uva)\b/ },
    { id: "melancia", label: "Melancia", re: /\b(watermelon|melancia)\b/ },
    { id: "maca", label: "Maçã", re: /\b(apple|maca)\b/ },
    { id: "tropical", label: "Tropicais", re: /\b(mango|manga|pineapple|abacaxi|passion|maracuja|guava|goiaba|kiwi|banana|coconut|coco|tropical)\b/ },
  ];
  const ORDENS = [
    { id: "padrao", label: "Padrão da loja" },
    { id: "menor", label: "Menor preço" },
    { id: "maior", label: "Maior preço" },
  ];

  // Ficha de cada card, calculada uma vez. O preço e a oferta NÃO entram aqui:
  // mudam quando uma oferta zera, então são lidos na hora de filtrar.
  const fichas = new Map();
  cards.forEach((card, ordem) => {
    const model = CATALOG.find((m) => m.id === Number(card.dataset.id));
    const sabores = model ? model.flavors.filter((f) => f.is_in_stock).map((f) => semAcento(f.name)) : [];
    fichas.set(card, {
      model,
      ordem,
      puffs: model ? puffsDe(model) : null,
      busca: semAcento([card.dataset.name, card.dataset.brandname].concat(sabores).join(" | ")),
      sabores: new Set(SABORES.filter((s) => sabores.some((nome) => s.re.test(nome))).map((s) => s.id)),
    });
  });
  // Preço que vale agora (já com oferta): o do sabor mais barato à venda.
  function precoDe(model) {
    if (!model) return 0;
    const venda = model.flavors.filter((f) => f.is_in_stock);
    const lista = (venda.length ? venda : model.flavors).map((f) => f.price);
    return lista.length ? Math.min(...lista) : 0;
  }
  const emOferta = (model) => !!model && model.flavors.some((f) => f.is_in_stock && promoOn(f));

  const filtros = { ordem: "padrao", puffs: new Set(), sabor: new Set(), preco: new Set(), oferta: false };
  const totalFiltros = () => filtros.puffs.size + filtros.sabor.size + filtros.preco.size + (filtros.oferta ? 1 : 0) + (filtros.ordem !== "padrao" ? 1 : 0);

  function passaNosFiltros(ficha) {
    if (filtros.puffs.size && !(ficha.puffs !== null && FAIXAS_PUFFS.some((f) => filtros.puffs.has(f.id) && f.ok(ficha.puffs)))) return false;
    if (filtros.sabor.size && ![...filtros.sabor].some((id) => ficha.sabores.has(id))) return false;
    if (filtros.preco.size) {
      const p = precoDe(ficha.model);
      if (!FAIXAS_PRECO.some((f) => filtros.preco.has(f.id) && f.ok(p))) return false;
    }
    if (filtros.oferta && !emOferta(ficha.model)) return false;
    return true;
  }

  function applyFilter() {
    const q = semAcento(byId("searchInput").value).trim();
    let visible = 0;
    cards.forEach((c) => {
      const ficha = fichas.get(c);
      const matchSearch = !q || ficha.busca.includes(q);
      let matchFilter = true;
      if (activeFilter === "best") matchFilter = c.dataset.best === "1";
      else if (activeFilter.startsWith("brand-")) matchFilter = c.dataset.brand === activeFilter.split("-")[1];
      const show = matchSearch && matchFilter && passaNosFiltros(ficha);
      c.style.display = show ? "" : "none";
      if (show) visible++;
    });

    // Ordem: reposiciona os cards na grade. "Padrão" devolve a ordem que o
    // lojista definiu no painel.
    const ordenados = cards.slice().sort((a, b) => {
      const fa = fichas.get(a), fb = fichas.get(b);
      if (filtros.ordem === "menor") return precoDe(fa.model) - precoDe(fb.model) || fa.ordem - fb.ordem;
      if (filtros.ordem === "maior") return precoDe(fb.model) - precoDe(fa.model) || fa.ordem - fb.ordem;
      return fa.ordem - fb.ordem;
    });
    if (ordenados.some((c, i) => grid.children[i] !== c)) ordenados.forEach((c) => grid.appendChild(c));

    byId("catalogCount").textContent = visible + " modelo" + (visible !== 1 ? "s" : "");
    paintFilterState(visible);

    // Estado vazio: diz O QUE não foi achado e dá a saída. Antes era um
    // "Nenhum modelo encontrado 🔍" genérico, que deixava o cliente sem saber
    // se errou a busca ou se o filtro estava atrapalhando.
    let empty = grid.querySelector(".empty-msg");
    if (visible === 0) {
      if (!empty) {
        empty = document.createElement("div");
        empty.className = "empty-msg";
      }
      grid.appendChild(empty); // sempre por último, depois dos cards reordenados
      const termo = (byId("searchInput").value || "").trim();
      const filtrando = activeFilter !== "all";
      const comPainel = totalFiltros() - (filtros.ordem !== "padrao" ? 1 : 0) > 0;
      empty.innerHTML = "";

      const titulo = document.createElement("p");
      titulo.className = "empty-msg-title";
      if (termo) {
        // Nome do produto entra como nó de texto, nunca via innerHTML.
        titulo.append("Nenhum produto encontrado para ");
        const forte = document.createElement("strong");
        forte.textContent = "“" + termo + "”";
        titulo.append(forte);
      } else if (comPainel) {
        titulo.textContent = "Nenhum produto com esses filtros";
      } else {
        titulo.textContent = "Nenhum produto nesta categoria";
      }
      empty.appendChild(titulo);

      const dica = document.createElement("p");
      dica.className = "empty-msg-hint";
      dica.textContent = comPainel
        ? "Tire um dos filtros para ver mais opções, ou veja o catálogo inteiro."
        : filtrando && termo
          ? "Talvez o produto esteja em outra marca. Toque abaixo para buscar no catálogo inteiro."
          : filtrando
            ? "Esta marca está sem produtos no momento."
            : "Confira a grafia ou tente pelo nome da marca ou do sabor.";
      empty.appendChild(dica);

      if (filtrando || termo || comPainel) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "empty-msg-reset";
        btn.textContent = "Ver todos os produtos";
        btn.addEventListener("click", () => {
          byId("searchInput").value = "";
          limparFiltros(false);
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

  // ---- Painel "Filtros" ----
  const filterPanel = byId("filterPanel");
  const filterOverlay = byId("filterOverlay");
  const filterOpenBtn = byId("filterOpen");

  // Um botão de opção. Texto por textContent: rótulos são fixos daqui, mas a
  // regra da casa é não montar HTML com string.
  function opcao(grupo, id, label, ligado) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "filter-opt";
    b.dataset.grupo = grupo;
    b.dataset.id = id;
    b.setAttribute("aria-pressed", String(ligado));
    b.textContent = label;
    return b;
  }
  function grupo(titulo, botoes) {
    const g = document.createElement("div");
    g.className = "filter-group";
    g.setAttribute("role", "group");
    g.setAttribute("aria-label", titulo);
    const h = document.createElement("h4");
    h.textContent = titulo;
    const linha = document.createElement("div");
    linha.className = "filter-opts";
    botoes.forEach((b) => linha.appendChild(b));
    g.append(h, linha);
    return g;
  }

  // Monta os grupos a cada abertura: só entram opções que existem no catálogo
  // de agora (uma família de sabor sem nenhum modelo, ou "só em oferta" sem
  // oferta ativa, seriam botões que sempre dão zero resultados).
  function renderFilterPanel() {
    const body = byId("filterBody");
    body.textContent = "";
    const todas = [...fichas.values()];
    body.appendChild(grupo("Ordenar por", ORDENS.map((o) => opcao("ordem", o.id, o.label, filtros.ordem === o.id))));
    const faixasPuffs = FAIXAS_PUFFS.filter((f) => todas.some((x) => x.puffs !== null && f.ok(x.puffs)));
    if (faixasPuffs.length) body.appendChild(grupo("Puffs", faixasPuffs.map((f) => opcao("puffs", f.id, f.label, filtros.puffs.has(f.id)))));
    const familias = SABORES.filter((s) => todas.some((x) => x.sabores.has(s.id)));
    if (familias.length) body.appendChild(grupo("Sabor", familias.map((s) => opcao("sabor", s.id, s.label, filtros.sabor.has(s.id)))));
    const faixasPreco = FAIXAS_PRECO.filter((f) => todas.some((x) => f.ok(precoDe(x.model))));
    if (faixasPreco.length) body.appendChild(grupo("Preço", faixasPreco.map((f) => opcao("preco", f.id, f.label, filtros.preco.has(f.id)))));
    if (todas.some((x) => emOferta(x.model)) || filtros.oferta) {
      body.appendChild(grupo("Ofertas", [opcao("oferta", "sim", "Só em oferta", filtros.oferta)]));
    }
  }

  byId("filterBody").addEventListener("click", (e) => {
    const b = e.target.closest(".filter-opt");
    if (!b) return;
    const g = b.dataset.grupo, id = b.dataset.id;
    if (g === "ordem") filtros.ordem = id;
    else if (g === "oferta") filtros.oferta = !filtros.oferta;
    else if (filtros[g].has(id)) filtros[g].delete(id);
    else filtros[g].add(id);
    renderFilterPanel();
    applyFilter();
    // O grupo foi redesenhado: devolve o foco ao botão que a pessoa acabou de usar.
    const de_novo = byId("filterBody").querySelector(`.filter-opt[data-grupo="${g}"][data-id="${id}"]`);
    if (de_novo) de_novo.focus();
  });

  function limparFiltros(aplicar) {
    filtros.ordem = "padrao";
    filtros.puffs.clear(); filtros.sabor.clear(); filtros.preco.clear();
    filtros.oferta = false;
    if (filterPanel.classList.contains("open")) renderFilterPanel();
    if (aplicar !== false) applyFilter();
  }

  // Tudo o que mostra o estado dos filtros FORA do painel: o número no botão,
  // as etiquetas removíveis acima da grade e o texto do botão "Ver N modelos".
  function paintFilterState(visible) {
    const n = totalFiltros();
    const badge = byId("filterCount");
    badge.hidden = n === 0;
    badge.textContent = n;
    filterOpenBtn.classList.toggle("is-on", n > 0);
    filterOpenBtn.setAttribute("aria-label", n ? `Filtros (${n} ativo${n > 1 ? "s" : ""})` : "Filtros");
    byId("filterApply").textContent = visible === 0 ? "Nenhum modelo" : `Ver ${visible} modelo${visible !== 1 ? "s" : ""}`;
    byId("filterClear").disabled = n === 0;

    const box = byId("filterActive");
    box.textContent = "";
    box.hidden = n === 0;
    if (!n) return;
    const etiqueta = (texto, tirar) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "filter-chip";
      b.setAttribute("aria-label", `Tirar o filtro ${texto}`);
      const t = document.createElement("span");
      t.textContent = texto;
      const x = document.createElement("span");
      x.className = "filter-chip-x";
      x.setAttribute("aria-hidden", "true");
      x.textContent = "✕";
      b.append(t, x);
      b.addEventListener("click", () => { tirar(); applyFilter(); });
      box.appendChild(b);
    };
    if (filtros.ordem !== "padrao") etiqueta(ORDENS.find((o) => o.id === filtros.ordem).label, () => { filtros.ordem = "padrao"; });
    FAIXAS_PUFFS.forEach((f) => { if (filtros.puffs.has(f.id)) etiqueta(f.curto, () => filtros.puffs.delete(f.id)); });
    SABORES.forEach((s) => { if (filtros.sabor.has(s.id)) etiqueta(s.label, () => filtros.sabor.delete(s.id)); });
    FAIXAS_PRECO.forEach((f) => { if (filtros.preco.has(f.id)) etiqueta(f.label, () => filtros.preco.delete(f.id)); });
    if (filtros.oferta) etiqueta("Só em oferta", () => { filtros.oferta = false; });
    const limpar = document.createElement("button");
    limpar.type = "button";
    limpar.className = "filter-clear-link";
    limpar.textContent = "Limpar";
    limpar.addEventListener("click", () => limparFiltros());
    box.appendChild(limpar);
  }

  function openFilter() {
    renderFilterPanel();
    filterPanel.classList.add("open");
    filterOverlay.classList.add("open");
    filterPanel.setAttribute("aria-hidden", "false");
    filterOpenBtn.setAttribute("aria-expanded", "true");
    lockBodyScroll();
    byId("filterClose").focus();
  }
  function closeFilter() {
    if (!filterPanel.classList.contains("open")) return;
    filterPanel.classList.remove("open");
    filterOverlay.classList.remove("open");
    filterPanel.setAttribute("aria-hidden", "true");
    filterOpenBtn.setAttribute("aria-expanded", "false");
    unlockBodyScroll();
    filterOpenBtn.focus({ preventScroll: true });
  }
  filterOpenBtn.addEventListener("click", openFilter);
  byId("filterClose").addEventListener("click", closeFilter);
  filterOverlay.addEventListener("click", closeFilter);
  byId("filterClear").addEventListener("click", () => limparFiltros());
  // "Ver N modelos": fecha e leva o cliente para o começo da grade filtrada.
  byId("filterApply").addEventListener("click", () => {
    closeFilter();
    const reduzido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    byId("catalogo").scrollIntoView({ behavior: reduzido ? "auto" : "smooth", block: "start" });
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeFilter(); });
  // Uma oferta zerou: preço e "só em oferta" mudaram. Espera o app.js devolver
  // os preços cheios (outro ouvinte do mesmo evento) e refaz o filtro.
  document.addEventListener("promo:expired", () => setTimeout(() => {
    if (filterPanel.classList.contains("open")) renderFilterPanel();
    applyFilter();
  }, 0));

  applyFilter();

  // ---------------------------------------------------------------
  // AVALIAÇÕES DO GOOGLE (carrossel antes das perguntas frequentes)
  // ---------------------------------------------------------------
  // A fileira é scroll-snap nativo: no celular o dedo arrasta sem nada daqui.
  // Este bloco só acrescenta pontos, setas, teclado, arrasto com mouse e a
  // marcação do card em foco. Não há troca automática (ver abaixo).
  (function initReviewsCarousel() {
    const row = byId("reviewsRow");
    if (!row) return;
    const wrap = byId("reviewsCarousel");
    const cards = Array.from(row.children);
    const dots = Array.from(wrap.querySelectorAll(".reviews-dots button"));
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const n = cards.length;

    const base = () => cards[0].offsetLeft;
    const current = () => {
      let best = 0, bestDist = Infinity;
      cards.forEach((c, i) => {
        const d = Math.abs(c.offsetLeft - base() - row.scrollLeft);
        if (d < bestDist) { bestDist = d; best = i; }
      });
      return best;
    };
    const goTo = (i) => row.scrollTo({ left: cards[i].offsetLeft - base(), behavior: reduced ? "auto" : "smooth" });
    const step = (dir) => {
      const atEnd = row.scrollLeft >= row.scrollWidth - row.clientWidth - 2;
      let i = current() + dir;
      if (dir > 0 && atEnd) i = 0;          // no fim, volta ao começo
      if (i < 0) i = n - 1;
      goTo(Math.min(i, n - 1));
    };
    // Marca também o card em foco (.is-active): é o que dispara o destaque
    // animado no CSS (sobe, brilho atravessando a foto, zoom lento). Só troca
    // quando o foco muda, para a animação não reiniciar a cada pixel rolado.
    let lastActive = -1;
    const markDots = () => {
      const a = current();
      dots.forEach((d, k) => {
        d.classList.toggle("on", k === a);
        if (k === a) d.setAttribute("aria-current", "true"); else d.removeAttribute("aria-current");
      });
      if (a !== lastActive) {
        cards.forEach((c, k) => c.classList.toggle("is-active", k === a));
        lastActive = a;
      }
    };
    let raf = 0;
    row.addEventListener("scroll", () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(markDots);
    }, { passive: true });
    markDots();
    if (n < 2) return;

    // SEM auto-avanço, de propósito: o carrossel só se move quando o cliente
    // arrasta, toca numa seta ou num ponto. Com troca automática, quem chegava
    // pela linha da nota no hero às vezes já encontrava a fileira no fim.
    dots.forEach((d, i) => d.addEventListener("click", () => goTo(i)));
    wrap.querySelectorAll(".reviews-arrow").forEach((b) =>
      b.addEventListener("click", () => step(Number(b.dataset.dir)))
    );
    row.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight") { step(1); e.preventDefault(); }
      if (e.key === "ArrowLeft") { step(-1); e.preventDefault(); }
    });

    // Arrasto com mouse (no toque, o scroll nativo já resolve)
    let x0 = null, s0 = 0, i0 = 0, moved = false;
    row.addEventListener("pointerdown", (e) => {
      if (e.pointerType !== "mouse" || e.button !== 0) return;
      x0 = e.clientX; s0 = row.scrollLeft; i0 = current(); moved = false;
      row.classList.add("is-dragging");
      row.setPointerCapture(e.pointerId);
    });
    row.addEventListener("pointermove", (e) => {
      if (x0 === null) return;
      const dx = e.clientX - x0;
      if (Math.abs(dx) > 3) moved = true;
      row.scrollLeft = s0 - dx;
    });
    const endDrag = () => {
      if (x0 === null) return;
      const dx = row.scrollLeft - s0;
      x0 = null;
      row.classList.remove("is-dragging");
      let i = current();
      if (Math.abs(dx) > 40 && i === i0) i = Math.max(0, Math.min(n - 1, i0 + Math.sign(dx)));
      goTo(i);
    };
    row.addEventListener("pointerup", endDrag);
    row.addEventListener("pointercancel", endDrag);
    // Um arrasto não pode virar clique (ex.: abrir a foto no futuro).
    row.addEventListener("click", (e) => { if (moved) { e.preventDefault(); e.stopPropagation(); moved = false; } }, true);

  })();

  // Linha da nota no hero -> desce até as avaliações e acende os cards por
  // um instante, para o olho achar onde chegou.
  (function initHeroRating() {
    const link = byId("heroRating");
    const section = byId("avaliacoes");
    if (!link || !section) return;
    link.addEventListener("click", (e) => {
      e.preventDefault();
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      section.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
      const row = byId("reviewsRow");
      if (!row || reduced) return;
      setTimeout(() => {
        row.classList.remove("is-flash");
        void row.offsetWidth;
        row.classList.add("is-flash");
      }, 650);
    });
  })();

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
    paintModalPromo();
    updateModalTotal();
    overlay.classList.add("open");
    document.body.style.overflow = "hidden";
  }

  // Selo e relógio da promoção do modelo aberto. O bloco nasce `hidden` no
  // template; só aparece com promoção ativa e volta a sumir quando ela zera
  // (ver o listener de "promo:expired").
  function paintModalPromo() {
    const box = byId("modalPromo");
    const m = modalState.model;
    const on = promoOn(m);
    box.hidden = !on;
    if (!on) { box.removeAttribute("data-promo-fim"); return; }
    box.setAttribute("data-promo-fim", m.promo_fim);
    byId("modalPromoOff").textContent = "-" + descontoCurto(m.promo_desconto);
    // Relâmpago: raio + "Relâmpago" no lugar de "acaba em".
    const rel = !!m.promo_relampago;
    box.classList.toggle("is-relampago", rel);
    byId("modalPromoBolt").hidden = !rel;
    byId("modalPromoLbl").textContent = rel ? "Relâmpago · em cada sabor · acaba em" : "em cada sabor · acaba em";
    PROMO.refresh();
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
    const was = byId("modalWas");
    if (!modalState.flavor) {
      byId("modalTotal").textContent = brl(0);
      was.hidden = true;
      addBtn.disabled = true;
      addBtn.textContent = "Selecione um sabor";
      return;
    }
    const total = modalState.flavor.price * modalState.qty;
    byId("modalTotal").textContent = brl(total);
    // De/por: o valor cheio riscado só aparece com a promoção do sabor ativa.
    const emPromo = promoOn(modalState.flavor);
    was.hidden = !emPromo;
    if (emPromo) was.textContent = brl(modalState.flavor.price_original * modalState.qty);
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
      // Promoção viaja com o item: é o que permite mostrar o de/por no
      // carrinho e voltar ao preço cheio quando o relógio zerar.
      price_original: f.price_original != null ? f.price_original : f.price,
      promo_fim: promoOn(f) ? f.promo_fim : null,
      promo_relampago: promoOn(f) && !!f.promo_relampago,
      promo_depois: promoOn(f) ? (f.promo_depois || null) : null,
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
  // Destaque "próxima oferta" (hero) -> abre direto o produto em oferta.
  document.addEventListener("click", (e) => {
    const link = e.target.closest("[data-open-model]");
    if (!link || CFG.editor) return;
    const model = CATALOG.find((m) => m.id === Number(link.dataset.openModel));
    if (!model) return;
    e.preventDefault();
    openModal(model);
  });

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
               ${promoOn(it)
                 ? `<div class="p"><s class="ci-was">${brl(it.price_original)}</s> ${brl(it.price)}</div>
                    <div class="ci-promo" data-promo-fim="${escapeHtml(it.promo_fim)}" data-promo-expire="none">Oferta por mais <b data-cd></b></div>`
                 : `<div class="p">${brl(it.price)}</div>`}
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
    // As linhas em oferta acabaram de ser redesenhadas: religa os relógios.
    PROMO.refresh();
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

  // Quanto as ofertas com hora marcada tiraram do carrinho (antes do cupom).
  function promoSavings() {
    return cart.reduce((s, it) => (promoOn(it) ? s + (it.price_original - it.price) * it.qty : s), 0);
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
      // Economia das ofertas com hora marcada. `total` já vem com ela
      // descontada (it.price é o preço que vale agora); o número aqui é só
      // para MOSTRAR ao cliente e à equipe quanto saiu.
      promoSavings: promoSavings(),
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

    // Economia: só entra em cena com oferta ativa no carrinho. No carrinho o
    // número soma o cupom ("você economiza" é o total que deixou de pagar);
    // no resumo do checkout o cupom já tem a linha dele, então ali vai só a
    // parte das ofertas.
    const showSavings = t.promoSavings > 0.004;
    byId("cartSavingsRow").style.display = showSavings ? "flex" : "none";
    byId("checkoutSavingsRow").style.display = showSavings ? "flex" : "none";
    if (showSavings) {
      byId("cartSavingsValue").textContent = brl(t.promoSavings + t.discount);
      byId("checkoutSavingsValue").textContent = "-" + brl(t.promoSavings);
    }

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
    showPriceNotice([]);      // aviso de uma abertura anterior não vale mais
    renderCheckoutSummary();
    refreshQuote();           // confere os preços no servidor já na abertura
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
        <span class="p">${promoOn(it) ? `<s class="ci-was">${brl(it.price_original * it.qty)}</s> ` : ""}${brl(sub)}</span>
      </div>`;
    }).join("");
    updateTotals();
  }

  // ---------------------------------------------------------------
  // PREÇO QUE VALE AGORA (ofertas com hora marcada)
  // ---------------------------------------------------------------
  // Dois mecanismos, um de cada lado:
  //   1. No navegador, o relógio (corrigido pela hora do servidor) zera e o
  //      evento "promo:expired" devolve catálogo e carrinho ao preço cheio.
  //   2. No servidor, /api/cart/quote diz quanto cada sabor custa AGORA. É a
  //      revalidação do pedido: como o pedido desta loja é uma mensagem de
  //      WhatsApp montada aqui, é esta cotação que impede uma oferta vencida
  //      de chegar ao atendente.

  // Aviso dentro do resumo do checkout. Texto montado com nós, nunca innerHTML
  // com nome de produto.
  function showPriceNotice(mudancas) {
    const box = byId("checkoutPriceNotice");
    box.textContent = "";
    if (!mudancas.length) { box.hidden = true; return; }
    const titulo = document.createElement("strong");
    titulo.textContent = mudancas.length === 1 ? "O preço de um item mudou" : "O preço de alguns itens mudou";
    box.append(titulo);
    mudancas.forEach((m) => {
      const p = document.createElement("p");
      p.textContent = m;
      box.append(p);
    });
    const fim = document.createElement("p");
    fim.className = "price-notice-end";
    fim.textContent = "O total já foi recalculado. Confira e envie o pedido.";
    box.append(fim);
    box.hidden = false;
  }

  function fraseMudanca(it, antes) {
    const nome = itemLabel(it);
    return it.price > antes
      ? `A oferta de ${nome} acabou: voltou de ${brl(antes)} para ${brl(it.price)}.`
      : `${nome} baixou de ${brl(antes)} para ${brl(it.price)}.`;
  }

  // O relógio de `x` (modelo, sabor ou item do carrinho) zerou. Com
  // relâmpago, passa a valer a oferta normal (`promo_depois`) e ela é
  // devolvida; sem, a promoção acaba e volta null.
  function proximaPromo(x) {
    const d = x.promo_depois;
    x.promo_relampago = false;
    x.promo_depois = null;
    if (d && PROMO.ativa(d.promo_fim)) {
      x.promo_fim = d.promo_fim;
      x.promo_desconto = d.promo_desconto;
      return d;
    }
    x.promo_fim = null;
    x.promo_desconto = 0;
    return null;
  }
  const venceu = (x) => !!(x.promo_fim && !PROMO.ativa(x.promo_fim));

  // Relógio zerou: catálogo e carrinho vão para o próximo preço (oferta
  // normal depois do relâmpago, ou preço cheio). Devolve as frases de aviso
  // dos itens do carrinho que mudaram.
  function syncPromoPrices() {
    CATALOG.forEach((m) => {
      if (venceu(m)) proximaPromo(m);
      m.flavors.forEach((f) => {
        if (venceu(f)) {
          const d = proximaPromo(f);
          f.price = d ? d.price : f.price_original;
        }
      });
    });
    const mudancas = [];
    cart.forEach((it) => {
      if (venceu(it)) {
        const antes = it.price;
        const eraRelampago = !!it.promo_relampago;
        const d = proximaPromo(it);
        it.price = d ? d.price : it.price_original;
        if (it.price === antes) return;
        mudancas.push(eraRelampago && d
          ? `O relâmpago de ${itemLabel(it)} acabou: passou de ${brl(antes)} para ${brl(it.price)}, ainda com o desconto da oferta.`
          : fraseMudanca(it, antes));
      }
    });
    return mudancas;
  }

  // Um cupom já aplicado foi validado com os preços de antes. Se o carrinho
  // mudou de preço, o desconto é recalculado sozinho (computeDiscount lê
  // it.price), então basta redesenhar.
  function aposMudancaDePreco(mudancas) {
    renderCart();
    if (checkoutPanel.classList.contains("open")) renderCheckoutSummary();
    if (mudancas.length) {
      showPriceNotice(mudancas);
      toast("Uma oferta acabou", "O total do pedido foi atualizado");
    }
  }

  document.addEventListener("promo:expired", () => {
    const mudancas = syncPromoPrices();
    if (overlay.classList.contains("open") && modalState.model) {
      paintModalPromo();
      updateModalTotal();
    }
    if (cart.length) aposMudancaDePreco(mudancas);
  });

  // Cotação no servidor. Devolve:
  //   null   -> não foi possível cotar (rede/servidor): segue com o preço local
  //   []     -> cotado, nada mudou
  //   [...]  -> frases dos itens cujo preço mudou (carrinho já corrigido)
  let lastQuoteAt = 0;       // quando a última cotação BEM-SUCEDIDA terminou
  let quoteInFlight = null;
  const QUOTE_FRESH_MS = 30000;

  function quoteCart() {
    if (quoteInFlight) return quoteInFlight;
    const ids = cart.filter((it) => !it.is_cable).map((it) => ({ flavor_id: it.flavor_id }));
    if (!ids.length) { lastQuoteAt = Date.now(); return Promise.resolve([]); }
    const ctrl = typeof AbortController === "function" ? new AbortController() : null;
    const timer = ctrl ? setTimeout(() => ctrl.abort(), 6000) : null;
    quoteInFlight = fetch("/api/cart/quote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: ids }),
      signal: ctrl ? ctrl.signal : undefined,
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("quote " + r.status))))
      .then((data) => {
        if (!data || !data.ok) throw new Error("quote inválida");
        PROMO.acertar(data.now_ms);
        const oficiais = new Map(data.items.map((q) => [q.flavor_id, q]));
        const mudancas = [];
        for (let i = cart.length - 1; i >= 0; i--) {
          const it = cart[i];
          if (it.is_cable) continue;
          const q = oficiais.get(it.flavor_id);
          if (!q) continue;
          if (!q.found) {
            // O sabor foi excluído do catálogo depois de entrar no carrinho.
            mudancas.unshift(`${itemLabel(it)} não está mais disponível e saiu do pedido.`);
            cart.splice(i, 1);
            continue;
          }
          const antes = it.price;
          it.price = q.price;
          it.price_original = q.price_original;
          it.promo_fim = q.promo_fim || null;
          it.promo_relampago = !!q.promo_relampago;
          it.promo_depois = q.promo_depois || null;
          if (Math.round(antes * 100) !== Math.round(q.price * 100)) mudancas.unshift(fraseMudanca(it, antes));
        }
        lastQuoteAt = Date.now();
        return mudancas;
      })
      .catch(() => null)
      .finally(() => { if (timer) clearTimeout(timer); quoteInFlight = null; });
    return quoteInFlight;
  }

  // Cota e, se algo mudou, redesenha e avisa. Usada ao abrir o checkout e de
  // tempos em tempos enquanto ele está aberto, para o clique em "Enviar"
  // encontrar uma cotação recente e não precisar esperar a rede.
  function refreshQuote() {
    return quoteCart().then((mudancas) => {
      if (mudancas && mudancas.length) aposMudancaDePreco(mudancas);
      return mudancas;
    });
  }
  setInterval(() => {
    if (!document.hidden && cart.length && checkoutPanel.classList.contains("open")) refreshQuote();
  }, 15000);

  // Chamada no clique de "Confirmar e Enviar". true = pode enviar agora.
  //
  // O envio abre o WhatsApp com window.open, e navegador de celular só deixa
  // abrir janela DENTRO do toque do usuário. Por isso o caminho feliz é
  // síncrono: a cotação já foi feita ao abrir o checkout e é refeita a cada
  // 15s, então quase sempre existe uma recente e o pedido sai neste toque.
  // Quando não existe, cotamos agora e pedimos um segundo toque, em vez de
  // tentar abrir a janela depois da espera e o navegador bloquear em silêncio.
  let lastQuoteFailAt = 0;
  function precosConferidos() {
    // 1. O relógio local já sabe de alguma oferta vencida?
    const locais = syncPromoPrices();
    if (locais.length) { aposMudancaDePreco(locais); return false; }
    // 2. Cotação recente do servidor: nada a fazer.
    if (Date.now() - lastQuoteAt <= QUOTE_FRESH_MS) return true;
    // 3. A última tentativa falhou há pouco (sem rede, servidor fora): o
    //    pedido segue com o preço do relógio corrigido, que acabou de ser
    //    conferido no passo 1. Travar a venda por causa da cotação seria pior.
    if (Date.now() - lastQuoteFailAt <= QUOTE_FRESH_MS) return true;
    // 4. Sem cotação recente: cota agora e pede o segundo toque.
    const btn = byId("checkoutConfirmBtn");
    btn.disabled = true;
    btn.classList.add("is-checking");
    refreshQuote().then((mudancas) => {
      btn.classList.remove("is-checking");
      updateCheckoutBtnState();
      if (mudancas === null) {
        lastQuoteFailAt = Date.now();
        toast("Não deu para conferir os preços", "Toque de novo para enviar o pedido");
      } else if (!mudancas.length) {
        toast("Preços conferidos", "Toque de novo para enviar o pedido", "success");
      }
    });
    return false;
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

    // Revalidação de preço NO MOMENTO DO PEDIDO. Se uma oferta acabou com o
    // item no carrinho, o total é recalculado, o cliente é avisado e este
    // clique não envia nada: ele confere e toca de novo.
    if (!precosConferidos()) return;

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
      if (promoOn(it)) {
        // De/por e o desconto por unidade: o atendente vê que o preço menor é
        // uma oferta do site, e não erro de digitação. ~texto~ é o riscado do
        // WhatsApp.
        msg += `   📦 Qtd: ${it.qty}x  •  ~${brl(it.price_original)}~ ${brl(it.price)}\n`;
        msg += `   🔥 Oferta: -${brl(it.price_original - it.price)} por unidade\n`;
      } else {
        msg += `   📦 Qtd: ${it.qty}x  •  ${brl(it.price)}\n`;
      }
      msg += `   💰 Subtotal: ${brl(sub)}\n\n`;
    });
    msg += `━━━━━━━━━━━━━━━\n`;
    const t = computeOrderTotals();
    const discount = t.discount;
    if (t.promoSavings > 0.004) {
      msg += `🔥 *Economia nas ofertas:* ${brl(t.promoSavings)}\n`;
    }
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
  // ASSINATURA DO LETREIRO DE BLACK FRIDAY (encaixe)
  // A assinatura (nome da loja ou texto do painel) fica entre dois fios
  // dourados e a linha inteira mede a largura do FRIDAY. As letras nunca
  // quebram (CSS); aqui garantimos que também nunca vazem: se o nome não
  // cabe com os dois fios no tamanho mínimo, a fonte da assinatura diminui na
  // proporção exata. Letras, espaços entre elas e o vão até os fios são em
  // em, então escalam juntos; só a largura mínima dos fios é fixa em px.
  // Sem Black Friday (ou sem assinatura) não há .bf-sign e nada roda.
  // ---------------------------------------------------------------
  (function initBfSignFit() {
    const sign = document.querySelector(".bf-sign");
    const txt = sign && sign.querySelector(".bf-sign-txt");
    if (!txt) return;

    const fit = () => {
      sign.style.fontSize = "";
      sign.style.removeProperty("--bf-sign-track");
      const cs = getComputedStyle(sign);
      const width = sign.clientWidth;
      const gap = parseFloat(cs.columnGap) || 0;
      const ruleMin = parseFloat(cs.getPropertyValue("--bf-sign-rule-min")) || 0;
      const fits = () => txt.scrollWidth + 2 * (gap + ruleMin) <= width;
      if (!width || fits()) return;
      // 1º passo: aproxima as letras. 2º, se ainda não couber: fonte menor.
      sign.style.setProperty("--bf-sign-track", ".22em");
      if (fits()) return;
      const need = txt.scrollWidth;
      const scale = (width - 2 * ruleMin) / (need + 2 * gap);
      // 0,98: um respiro para arredondamento de subpixel.
      sign.style.fontSize = (parseFloat(cs.fontSize) * scale * 0.98).toFixed(2) + "px";
    };

    fit();
    // A largura muda quando a Archivo chega (display=swap) e ao girar a tela.
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);
    let raf = 0;
    window.addEventListener("resize", () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(fit);
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

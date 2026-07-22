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
  function setAppVvh() {
    const vv = window.visualViewport;
    const h = Math.round(vv ? vv.height : window.innerHeight);
    const top = Math.round(vv ? vv.offsetTop : 0);
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
      // atualizado), traz o campo focado pro meio do corpo rolável. Assim o
      // cliente vê os campos de cima e de baixo — mantém a "visão geral" em
      // vez de o campo ficar colado no teclado. "center" só afeta o scroller
      // interno (.checkout-body/.cart-items), o body está travado.
      const control = e.target.closest("input, select, textarea");
      if (control && control.scrollIntoView) {
        // Depois que o teclado assenta e o painel encolheu (--app-vvh já
        // atualizado), traz o campo focado pro meio do corpo rolável com
        // scroll suave. Assim o cliente vê os campos de cima e de baixo —
        // mantém a "visão geral". "center" só afeta o scroller interno
        // (.checkout-body/.cart-items), o body está travado.
        setTimeout(() => {
          try { control.scrollIntoView({ block: "center", behavior: "smooth" }); }
          catch (_) { control.scrollIntoView(); }
        }, 380);
      }
    }
  });
  document.addEventListener("focusout", (e) => {
    if (e.target.closest(".cart-sidebar, .checkout-panel")) {
      setTimeout(setAppVvh, 350);
      setTimeout(setAppVvh, 700);
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

    if (isVerified()) {
      document.documentElement.classList.add("age-ok");
    } else {
      document.body.style.overflow = "hidden";
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
    let empty = grid.querySelector(".empty-msg");
    if (visible === 0) {
      if (!empty) {
        empty = document.createElement("div");
        empty.className = "empty-msg";
        empty.textContent = "Nenhum modelo encontrado 🔍";
        grid.appendChild(empty);
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
    if (model.image_url) return `<img src="${model.image_url}" alt="${model.name}">`;
    return `<span class="ph">${model.name[0]}</span>`;
  }

  function openModal(model) {
    modalState = { model, flavor: null, qty: 1 };
    byId("modalImg").innerHTML = imgHTML(model);
    byId("modalBrand").textContent = model.brand_name;
    byId("modalName").textContent = model.name;
    // Ícone de raio temável (segue currentColor) + texto como nó de texto
    // (nunca innerHTML com dado do produto — evita injeção de HTML).
    const puffsEl = byId("modalPuffs");
    puffsEl.innerHTML = '<i class="ico-bolt"></i> ';
    puffsEl.append(model.puff_count);
    byId("qtyVal").textContent = "1";

    const inStock = model.flavors.filter((f) => f.is_in_stock);
    const fg = byId("modalFlavors");
    if (inStock.length === 0) {
      fg.innerHTML = `<span style="color:var(--text-dim);font-size:.85rem">Sem sabores em estoque no momento.</span>`;
    } else {
      fg.innerHTML = inStock.map((f, i) =>
        `<button class="flavor-pill" data-fid="${f.id}" data-price="${f.price}" data-name="${f.name}">
           <span class="dot" style="background:${f.color || PALETTE[i % PALETTE.length]}"></span>${f.name}
         </button>`).join("");
    }
    updateModalTotal();
    overlay.classList.add("open");
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    overlay.classList.remove("open");
    document.body.style.overflow = "";
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
    byId("modalFlavors").querySelectorAll(".flavor-pill").forEach((p) => p.classList.remove("selected"));
    pill.classList.add("selected");
    modalState.flavor = {
      id: Number(pill.dataset.fid),
      name: pill.dataset.name,
      price: parseFloat(pill.dataset.price),
    };
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
    const existing = cart.find((it) => it.flavor_id === f.id);
    if (existing) existing.qty += modalState.qty;
    else cart.push({
      flavor_id: f.id,
      model_name: m.name,
      brand_name: m.brand_name,
      flavor_name: f.name,
      price: f.price,
      qty: modalState.qty,
      image_url: m.image_url || "",
    });
    saveCart();
    renderCart();
    closeModal();
    openCart();
    toast("Adicionado ao carrinho", `${m.name} • ${f.name}`, "success");
  });

  byId("modalClose").addEventListener("click", closeModal);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeModal(); closeCart(); closeNav(); } });

  // Card click -> open modal (disabled in editor mode)
  grid.parentElement.parentElement.addEventListener("click", () => {}); // noop guard
  document.querySelectorAll(".model-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (CFG.editor) return;
      const id = Number(card.dataset.id);
      const model = CATALOG.find((m) => m.id === id);
      if (model) openModal(model);
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
      box.innerHTML = `<div class="cart-empty"><div class="big">🛒</div>Seu carrinho está vazio.</div>`;
      resetCoupon();
      byId("whatsappBtn").disabled = true;
      return;
    }

    box.innerHTML = cart.map((it, idx) => {
      const img = it.image_url
        ? `<img src="${it.image_url}" alt="">`
        : `<span class="ph">${it.model_name[0]}</span>`;
      return `<div class="cart-item">
        <div class="ci-img">${img}</div>
        <div class="ci-info">
          <div class="m">${it.model_name}</div>
          <div class="f">${it.flavor_name}</div>
          <div class="p">${brl(it.price)}</div>
        </div>
        <div class="ci-right">
          <button class="rm" data-idx="${idx}" title="Remover">🗑</button>
          <div class="ci-qty">
            <button data-act="dec" data-idx="${idx}">−</button>
            <span>${it.qty}</span>
            <button data-act="inc" data-idx="${idx}">+</button>
          </div>
        </div>
      </div>`;
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
    if (!coupon.productIds) return cartTotal();
    const allowed = new Set(coupon.productIds);
    return cart.reduce((s, it) => (allowed.has(it.flavor_id) ? s + it.price * it.qty : s), 0);
  }

  function computeDiscount(coupon) {
    if (!coupon) return 0;
    const base = couponBase(coupon);
    if (coupon.type === "percent") return base * (coupon.value / 100);
    return Math.min(coupon.value, base);
  }

  function updateTotals() {
    const total = cartTotal();
    const discount = computeDiscount(appliedCoupon);
    const discountedTotal = Math.max(total - discount, 0);
    const showDiscount = !!(appliedCoupon && discount > 0);

    const cartDiscountRow = byId("cartDiscountRow");
    cartDiscountRow.style.display = showDiscount ? "flex" : "none";
    if (showDiscount) {
      byId("cartDiscountCode").textContent = `(${appliedCoupon.code})`;
      byId("cartDiscountValue").textContent = "-" + brl(discount);
    }
    byId("cartTotal").textContent = brl(discountedTotal);

    const checkoutDiscountRow = byId("checkoutDiscountRow");
    checkoutDiscountRow.style.display = showDiscount ? "flex" : "none";
    if (showDiscount) {
      byId("checkoutDiscountCode").textContent = `(${appliedCoupon.code})`;
      byId("checkoutDiscountValue").textContent = "-" + brl(discount);
    }

    // Frete: só existe depois que o cliente usa a geolocalização no checkout (e não pediu retirada).
    const pickup = pickupCheckbox.checked;
    const hasNumericShipping = !pickup && !!(shippingInfo && shippingInfo.ok && typeof shippingInfo.price === "number");
    const shippingPrice = hasNumericShipping ? shippingInfo.price : 0;

    const checkoutShippingRow = byId("checkoutShippingRow");
    checkoutShippingRow.style.display = hasNumericShipping ? "flex" : "none";
    if (hasNumericShipping) {
      byId("checkoutShippingZone").textContent = `(${shippingInfo.zone_label})`;
      byId("checkoutShippingValue").textContent = brl(shippingInfo.price);
    }

    const checkoutShippingNote = byId("checkoutShippingNote");
    if (pickup) {
      checkoutShippingNote.textContent = "🏪 Retirada no local — sem frete";
      checkoutShippingNote.className = "geo-status show ok";
    } else if (shippingInfo && !hasNumericShipping) {
      checkoutShippingNote.textContent = shippingInfo.message || "";
      checkoutShippingNote.className = "geo-status show " + (shippingInfo.ok ? "warn" : "danger");
    } else {
      checkoutShippingNote.textContent = "";
      checkoutShippingNote.className = "geo-status";
    }

    const surchargeBase = discountedTotal + shippingPrice;
    const surcharge = creditSurcharge(surchargeBase);
    const checkoutSurchargeRow = byId("checkoutSurchargeRow");
    checkoutSurchargeRow.style.display = surcharge > 0 ? "flex" : "none";
    if (surcharge > 0) {
      byId("checkoutSurchargeValue").textContent = "+" + brl(surcharge);
    }

    byId("checkoutTotal").textContent = brl(surchargeBase + surcharge);
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

  byId("cartItems").addEventListener("click", (e) => {
    const rm = e.target.closest(".rm");
    if (rm) {
      const idx = Number(rm.dataset.idx);
      const item = cart[idx];
      const row = rm.closest(".cart-item");
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reduced || !row) {
        cart.splice(idx, 1); saveCart(); renderCart();
        if (item) toast("Removido do carrinho", `${item.model_name} • ${item.flavor_name}`);
        return;
      }
      row.style.maxHeight = row.offsetHeight + "px";
      row.classList.add("removing");
      void row.offsetHeight;
      row.style.maxHeight = "0px";
      setTimeout(() => { cart.splice(idx, 1); saveCart(); renderCart(); }, 320);
      if (item) toast("Removido do carrinho", `${item.model_name} • ${item.flavor_name}`);
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
          <div class="f">${it.flavor_name}</div>
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
    if (isPickup()) setFieldError(byId("custAddress"), byId("errAddress"), false);
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
          setGeoStatus(`⚠ Localização aproximada (~${acc} metros) — confirme o endereço acima para garantir a entrega`, "warn");
        } else {
          setGeoStatus("⚠ Localização imprecisa — por favor confirme bem o endereço digitado", "danger");
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
            msg = "Você não permitiu o acesso à localização. Sem problema — preencha o endereço acima que o entregador chega até você.";
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
  function updateCheckoutBtnState() {
    const nameOk = byId("custName").value.trim().length > 0;
    const phoneOk = byId("custPhone").value.replace(/\D/g, "").length >= 10;
    const addressOk = isPickup() || byId("custAddress").value.trim().length > 0;
    byId("checkoutConfirmBtn").disabled = !(nameOk && phoneOk && addressOk);
  }
  byId("custName").addEventListener("input", updateCheckoutBtnState);
  byId("custAddress").addEventListener("input", updateCheckoutBtnState);
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
    if (!pickup && setFieldError(addressEl, byId("errAddress"), addressVal.length === 0)) hasError = true;
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

    let msg = `👑 *PEDIDO ${CFG.storeName.toUpperCase()}*\n`;
    msg += `━━━━━━━━━━━━━━━\n\n`;
    let total = 0;
    cart.forEach((it, i) => {
      const sub = it.price * it.qty;
      total += sub;
      msg += `*${i + 1}. ${it.model_name}*\n`;
      msg += `   🍬 Sabor: ${it.flavor_name}\n`;
      msg += `   📦 Qtd: ${it.qty}x  •  ${brl(it.price)}\n`;
      msg += `   💰 Subtotal: ${brl(sub)}\n\n`;
    });
    msg += `━━━━━━━━━━━━━━━\n`;
    const discount = appliedCoupon ? computeDiscount(appliedCoupon) : 0;
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

    const hasNumericShipping = !pickup && !!(shippingInfo && shippingInfo.ok && typeof shippingInfo.price === "number");
    const shippingPrice = hasNumericShipping ? shippingInfo.price : 0;
    if (pickup) {
      msg += `🏪 *Retirada no local* (sem frete)\n`;
    } else if (shippingInfo) {
      if (hasNumericShipping) {
        msg += `🚚 *Frete:* ${brl(shippingInfo.price)} (${shippingInfo.zone_label})\n`;
      } else {
        msg += `🚚 *Frete:* ${shippingInfo.message}\n`;
      }
    }

    const baseTotal = Math.max(total - discount, 0) + shippingPrice;
    const surcharge = creditSurcharge(baseTotal);
    if (surcharge > 0) {
      msg += `💳 *Acréscimo cartão de crédito (5%):* +${brl(surcharge)}\n`;
    }
    const finalTotal = baseTotal + surcharge;
    if (hasNumericShipping || surcharge > 0) {
      msg += `💰 *TOTAL FINAL: ${brl(finalTotal)}*\n\n`;
    } else if (appliedCoupon) {
      msg += `💰 *Total com desconto: ${brl(finalTotal)}*\n\n`;
    } else {
      msg += `*TOTAL: ${brl(total)}*\n\n`;
    }
    msg += `👤 *Cliente:* ${nameVal}\n`;
    msg += `📱 *Telefone:* ${phoneEl.value}\n`;
    if (pickup) msg += `🏪 *Retirada:* no local\n`;
    else msg += `📍 *Endereço:* ${addressVal}\n`;
    msg += `💳 *Pagamento:* ${paymentVal}\n`;
    if (byId("custLoyalty").checked) msg += `🎁 *Cartão fidelidade:* sim, quero receber\n`;
    if (notesEl.value.trim()) msg += `📝 *Obs:* ${notesEl.value.trim()}\n`;
    if (!pickup && geoCoords) {
      let mapNote = "";
      if (geoAccuracy != null && geoAccuracy > 500) {
        mapNote = ` (localização aproximada, ~${Math.round(geoAccuracy)} metros — confira o endereço)`;
      }
      msg += `🗺️ *Localização:* https://maps.google.com/?q=${geoCoords.lat},${geoCoords.lng}${mapNote}\n`;
    }
    msg += `\nOlá! Gostaria de finalizar este pedido. 🚀`;

    const url = `https://wa.me/${CFG.whatsapp}?text=${encodeURIComponent(msg)}`;
    window.open(url, "_blank");
    closeCheckout();
    toast("Pedido enviado ✓");
  });

  renderCart();

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

    targets.forEach((el) => observer.observe(el));

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
              box.innerHTML = `<img src="${data.image_url}" alt="">`;
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

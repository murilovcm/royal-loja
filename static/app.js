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

  // ---- Cart state (localStorage) ----
  let cart = [];
  try { cart = JSON.parse(localStorage.getItem("royal_cart")) || []; } catch (e) { cart = []; }
  const saveCart = () => localStorage.setItem("royal_cart", JSON.stringify(cart));

  // ---------------------------------------------------------------
  // TOAST
  // ---------------------------------------------------------------
  let toastTimer;
  function toast(msg) {
    const t = byId("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
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
    byId("modalPuffs").textContent = "⚡ " + model.puff_count;
    byId("qtyVal").textContent = "1";

    const inStock = model.flavors.filter((f) => f.is_in_stock);
    const fg = byId("modalFlavors");
    if (inStock.length === 0) {
      fg.innerHTML = `<span style="color:var(--text-dim);font-size:.85rem">Sem sabores em estoque no momento.</span>`;
    } else {
      fg.innerHTML = inStock.map((f, i) =>
        `<button class="flavor-pill" data-fid="${f.id}" data-price="${f.price}" data-name="${f.name}">
           <span class="dot" style="background:${PALETTE[i % PALETTE.length]}"></span>${f.name}
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
    toast("Adicionado ao carrinho ✓");
  });

  byId("modalClose").addEventListener("click", closeModal);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeModal(); closeCart(); } });

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

  function openCart() { cartSidebar.classList.add("open"); cartOverlay.classList.add("open"); document.body.style.overflow = "hidden"; }
  function closeCart() { cartSidebar.classList.remove("open"); cartOverlay.classList.remove("open"); document.body.style.overflow = ""; }

  byId("cartToggle").addEventListener("click", openCart);
  byId("cartClose").addEventListener("click", closeCart);
  cartOverlay.addEventListener("click", closeCart);

  function renderCart() {
    const box = byId("cartItems");
    const badge = byId("cartBadge");
    const totalCount = cart.reduce((s, it) => s + it.qty, 0);
    badge.textContent = totalCount;
    badge.classList.toggle("show", totalCount > 0);

    if (cart.length === 0) {
      box.innerHTML = `<div class="cart-empty"><div class="big">🛒</div>Seu carrinho está vazio.</div>`;
      byId("cartTotal").textContent = brl(0);
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

    const total = cart.reduce((s, it) => s + it.price * it.qty, 0);
    byId("cartTotal").textContent = brl(total);
    byId("whatsappBtn").disabled = false;
  }

  byId("cartItems").addEventListener("click", (e) => {
    const rm = e.target.closest(".rm");
    if (rm) { cart.splice(Number(rm.dataset.idx), 1); saveCart(); renderCart(); return; }
    const qb = e.target.closest("[data-act]");
    if (qb) {
      const idx = Number(qb.dataset.idx);
      if (qb.dataset.act === "inc") cart[idx].qty++;
      else { cart[idx].qty--; if (cart[idx].qty < 1) cart.splice(idx, 1); }
      saveCart(); renderCart();
    }
  });

  // ---------------------------------------------------------------
  // WHATSAPP CHECKOUT
  // ---------------------------------------------------------------
  byId("whatsappBtn").addEventListener("click", () => {
    if (cart.length === 0) return;
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
    msg += `*TOTAL: ${brl(total)}*\n\n`;
    msg += `Olá! Gostaria de finalizar este pedido. 🚀`;

    const url = `https://wa.me/${CFG.whatsapp}?text=${encodeURIComponent(msg)}`;
    window.open(url, "_blank");
  });

  renderCart();

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

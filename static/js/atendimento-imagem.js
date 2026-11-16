/* ===================================================================
   PAINEL DE ATENDIMENTO — imagem dos sabores (Etapa 5)

   Desenha, na hora, o "cartão com foto" de um modelo para colar no WhatsApp
   no lugar do print do site: foto do cadastro, nome, puffs, preço (com o
   "de" riscado na promoção), SÓ os sabores em estoque e o rodapé
   "Preços de dd/mm/aaaa" (uma imagem velha reenviada mostra o dia dela).

   Tudo é da loja onde o painel está aberto: o logo é o mesmo do cabeçalho do
   site dela (config.loja.logo) e o amarelo é a cor principal do tema dela.
   Royal sai com logo da Royal, Vapor com o da Vapor, e assim por diante.

   gerar(modelo, loja) devolve uma Promise<Blob> PNG. O painel entrega essa
   promessa direto ao ClipboardItem, ainda dentro do clique.
   =================================================================== */
(function () {
  "use strict";

  var W = 1080;
  var FONTE = '"Geist", system-ui, -apple-system, "Segoe UI", sans-serif';
  // Fundo escuro da identidade da loja; o destaque vem do tema (abaixo).
  var COR = { fundo: "#0f0e13", linha: "#2a2731", texto: "#f5f5f7", fraco: "#a3a1ab", foto: "#ffffff" };

  function destaque() {
    var v = getComputedStyle(document.documentElement).getPropertyValue("--primary-yellow").trim();
    return v || "#FFD60A";
  }
  function brl(n) {
    return Number(n || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }).replace(/ /g, " ");
  }
  function puffs(m) { return String(m.puffs || "").replace(/\s*puffs?/i, "").trim(); }
  function nomeSabor(s) { return s.nome + (s.versao ? " (" + s.versao + ")" : ""); }

  // Fotos e logo são carregados uma vez. crossOrigin evita "sujar" o canvas;
  // se a imagem não carregar (link quebrado, outro site sem permissão), a
  // imagem sai sem ela em vez de falhar.
  var cache = {};
  function carregar(src) {
    if (!src) return Promise.resolve(null);
    if (!cache[src]) {
      cache[src] = new Promise(function (ok) {
        var i = new Image();
        i.crossOrigin = "anonymous";
        i.onload = function () { ok(i.naturalWidth ? i : null); };
        i.onerror = function () { ok(null); };
        i.src = src;
      });
    }
    return cache[src];
  }
  function fontes() {
    if (!document.fonts || !document.fonts.load) return Promise.resolve();
    return Promise.all([document.fonts.load("800 40px Geist"), document.fonts.load("600 40px Geist"),
                        document.fonts.load("500 40px Geist")]).catch(function () {});
  }

  function cortar(ctx, t, max) {
    if (ctx.measureText(t).width <= max) return t;
    while (t.length > 1 && ctx.measureText(t + "…").width > max) t = t.slice(0, -1);
    return t + "…";
  }
  function quebrar(ctx, t, max, linhas) {
    var out = [], cur = "";
    t.split(" ").forEach(function (p) {
      var tent = cur ? cur + " " + p : p;
      if (ctx.measureText(tent).width <= max || !cur) cur = tent;
      else { out.push(cur); cur = p; }
    });
    if (cur) out.push(cur);
    if (out.length > linhas) { out = out.slice(0, linhas); out[linhas - 1] = cortar(ctx, out[linhas - 1] + "…", max); }
    return out;
  }
  function caixa(ctx, x, y, w, h, r) {
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
    else ctx.rect(x, y, w, h);
  }

  // Cabeçalho: logo da loja. Logo largo (com o nome escrito) vai sozinho;
  // logo quadrado (só o ícone) vai com o nome da loja ao lado.
  function cabecalho(ctx, logo, nomeLoja) {
    ctx.textBaseline = "middle";
    var x = 64;
    if (logo) {
      var h = 64, w = logo.naturalWidth * h / logo.naturalHeight;
      if (w > 440) { w = 440; h = logo.naturalHeight * w / logo.naturalWidth; }
      ctx.drawImage(logo, x, 60 - h / 2, w, h);
      x += w + 16;
      if (w / h > 1.4) nomeLoja = "";
    }
    if (nomeLoja) {
      ctx.fillStyle = COR.texto;
      ctx.font = "700 40px " + FONTE;
      ctx.fillText(cortar(ctx, nomeLoja, 560 - x), x, 62);
    }
    ctx.fillStyle = COR.fraco;
    ctx.font = "500 30px " + FONTE;
    ctx.textAlign = "right";
    ctx.fillText("Sabores disponíveis", W - 64, 62);
    ctx.textAlign = "left";
  }

  function desenhar(m, loja, foto, logo) {
    var sab = m.sabores.filter(function (s) { return s.em_estoque; });
    var amarelo = destaque();
    var linhas = Math.ceil(sab.length / 2);
    var heroH = foto ? 420 : 330, listaH = linhas * 84 + 40;
    var H = 120 + heroH + listaH + 112;
    var cv = document.createElement("canvas");
    cv.width = W;
    cv.height = H;
    var ctx = cv.getContext("2d");
    ctx.fillStyle = COR.fundo;
    ctx.fillRect(0, 0, W, H);
    cabecalho(ctx, logo, loja.nome);

    // Foto (fundo branco, como no site) e, ao lado, nome, puffs e preço.
    var y0 = 120, tx = 64;
    if (foto) {
      ctx.save();
      caixa(ctx, 64, y0 + 20, 360, 360, 32);
      ctx.fillStyle = COR.foto;
      ctx.fill();
      ctx.clip();
      var e = Math.min(336 / foto.naturalWidth, 336 / foto.naturalHeight);
      var iw = foto.naturalWidth * e, ih = foto.naturalHeight * e;
      ctx.drawImage(foto, 64 + (360 - iw) / 2, y0 + 20 + (360 - ih) / 2, iw, ih);
      ctx.restore();
      tx = 64 + 360 + 48;
    }
    var mw = W - 64 - tx, ty = y0 + (foto ? 70 : 50);
    ctx.textBaseline = "alphabetic";
    ctx.font = "650 30px " + FONTE;
    ctx.fillStyle = COR.fraco;
    ctx.fillText(cortar(ctx, m.marca.toUpperCase(), mw), tx, ty);
    ctx.font = "800 78px " + FONTE;
    ctx.fillStyle = COR.texto;
    var nomes = quebrar(ctx, m.modelo, mw, 2);
    nomes.forEach(function (l, i) { ctx.fillText(l, tx, ty + 82 + i * 80); });
    var yp = ty + 82 + (nomes.length - 1) * 80;
    if (puffs(m)) {
      ctx.font = "500 34px " + FONTE;
      ctx.fillStyle = COR.fraco;
      ctx.fillText(puffs(m) + " puffs", tx, yp + 54);
    }
    var yPreco = y0 + heroH - 30;
    if (m.preco_original > m.preco) {
      ctx.font = "500 32px " + FONTE;
      ctx.fillStyle = COR.fraco;
      var de = "de " + brl(m.preco_original), w0 = ctx.measureText("de ").width;
      ctx.fillText(de, tx, yPreco - 70);
      ctx.fillRect(tx + w0, yPreco - 81, ctx.measureText(de).width - w0, 3);
    }
    ctx.font = "800 72px " + FONTE;
    ctx.fillStyle = amarelo;
    ctx.fillText(brl(m.preco), tx, yPreco);

    // Sabores em estoque, duas colunas. Bolinha na cor do cadastro do sabor.
    var ly = y0 + heroH;
    ctx.fillStyle = COR.linha;
    ctx.fillRect(64, ly, W - 128, 2);
    var colW = (W - 128 - 40) / 2;
    ctx.textBaseline = "middle";
    sab.forEach(function (s, i) {
      var cx = 64 + (i % 2) * (colW + 40), cy = ly + 82 + Math.floor(i / 2) * 84;
      ctx.beginPath();
      ctx.arc(cx + 12, cy, 11, 0, Math.PI * 2);
      ctx.fillStyle = s.cor || amarelo;
      ctx.fill();
      ctx.font = "600 40px " + FONTE;
      var t = nomeSabor(s);
      if (ctx.measureText(t).width > colW - 44) ctx.font = "600 34px " + FONTE;
      ctx.fillStyle = COR.texto;
      ctx.fillText(cortar(ctx, t, colW - 44), cx + 40, cy);
    });

    // Rodapé: a data dos preços e o site da loja.
    var fy = ly + listaH;
    ctx.fillStyle = COR.linha;
    ctx.fillRect(64, fy, W - 128, 2);
    ctx.font = "500 30px " + FONTE;
    ctx.fillStyle = COR.fraco;
    ctx.fillText("Preços de " + new Date().toLocaleDateString("pt-BR") + " · " + sab.length + (sab.length > 1 ? " sabores" : " sabor"), 64, fy + 56);
    if (loja.site) {
      ctx.textAlign = "right";
      ctx.font = "650 30px " + FONTE;
      ctx.fillStyle = amarelo;
      ctx.fillText(cortar(ctx, loja.site, 420), W - 64, fy + 56);
      ctx.textAlign = "left";
    }
    return cv;
  }

  function paraBlob(cv) {
    return new Promise(function (ok, falha) {
      try {
        cv.toBlob(function (b) { b ? ok(b) : falha(new Error("não consegui gerar a imagem")); }, "image/png");
      } catch (e) { falha(e); }
    });
  }

  window.ATD_IMAGEM = {
    gerar: function (m, loja) {
      return Promise.all([carregar(m.foto), carregar(loja.logo), fontes()]).then(function (r) {
        return paraBlob(desenhar(m, loja, r[0], r[1])).catch(function () {
          // Canvas "sujo" por uma imagem de outro site: refaz sem foto/logo.
          return paraBlob(desenhar(m, loja, null, null));
        });
      });
    }
  };
})();

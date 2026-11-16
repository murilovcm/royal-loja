/* ===================================================================
   PAINEL DE ATENDIMENTO — abas Catálogo, Pedido e Mensagens

   Catálogo (Etapa 2): lista sanfona; o toque abre os sabores ali mesmo,
   com o botão de copiar. Na Etapa 3 cada sabor virou botão: tocar no sabor
   que o cliente escolheu coloca ele no pedido aberto.

   Pedido (Etapa 3): um pedido ATIVO por vez, com o nome do cliente no topo.
   "Guardar" põe o pedido na lista "Em espera" (até 20) e abre outro; tocar
   num guardado reabre. Dentro da extensão do Chrome, cada conversa do
   WhatsApp tem o próprio pedido: trocar de conversa guarda e reabre sozinho
   (ver trocarConversa). Tudo fica salvo neste navegador (localStorage), então
   atualizar a página não perde nada.

   A CONTA É DO SERVIDOR: o painel manda só ids, quantidades, local e forma
   de pagamento para /api/atendimento/cotacao e mostra o que voltar. Preço,
   frete, frete grátis, acréscimo do crédito e total nunca são calculados nem
   digitados aqui. Uma mensagem com total só é copiada quando a cotação
   bate com o pedido que está na tela.

   A atendente copia e cola no WhatsApp Web (Ctrl+V): o painel nunca lê nem
   envia mensagem.
   =================================================================== */
(function () {
  "use strict";

  var CFG = window.ATD || {};
  var $ = function (id) { return document.getElementById(id); };
  var painel = $("painel");
  var lista = $("lista");
  var busca = $("busca");
  var chips = $("marcas");

  var MODELOS = [];
  var CONFIG = null;
  var SABOR = {};            // id do sabor -> {m: modelo, s: sabor}
  var st = { q: "", marca: "", aberto: null, aba: "cat" };
  var atualizadoEm = null;

  var LIMITE_ESPERA = 20;   // com um pedido por conversa, a espera enche mais rápido
  var QTD_MAX = 50;
  var CHAVE_LOCAL = "atd_pedidos_v1";
  var PAGAMENTOS = { pix: "Pix", dinheiro: "Dinheiro", debito: "Débito", credito: "Crédito" };

  // ---------------------------------------------------------------- utilidades
  function icon(id) { return '<svg class="ico" aria-hidden="true"><use href="#i-' + id + '"></use></svg>'; }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  // "R$ 159,99" com espaço comum: o espaço inseparável do toLocaleString
  // aparece estranho em alguns WhatsApps.
  function brl(n) {
    return Number(n || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }).replace(/ /g, " ");
  }
  function norm(s) { return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  function puffs(p) { return String(p || "").replace(/\s*puffs?/i, "").trim(); }
  function emPromo(m) { return m.preco_original > m.preco; }
  function modeloPorId(id) { return MODELOS.find(function (m) { return String(m.id) === String(id); }); }
  function hora(ts) { return new Date(ts).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }); }
  function marcas() {
    var v = [];
    MODELOS.forEach(function (m) { if (v.indexOf(m.marca) < 0) v.push(m.marca); });
    return v;
  }
  // Negrito/itálico/riscado do WhatsApp, só para a prévia da mensagem.
  function waHtml(t) {
    return esc(t).replace(/\*([^*\n]+)\*/g, "<b>$1</b>")
      .replace(/(^|[\s>])_([^_\n]+)_/g, "$1<i>$2</i>")
      .replace(/~([^~\n]+)~/g, "<s>$1</s>");
  }

  // ---------------------------------------------------------------- textos
  // Preenche as {variaveis} do texto. Uma linha cujas variáveis vieram TODAS
  // vazias é removida (ex.: "🌐 {site}" quando a loja não cadastrou site, ou
  // "💳 Crédito (+5%): {acrescimo}" num pedido no Pix), para a mensagem não
  // sair com um ícone solto.
  function preencher(tpl, vars) {
    return String(tpl || "").split("\n").map(function (linha) {
      var nomes = linha.match(/\{(\w+)\}/g) || [];
      var vazias = nomes.filter(function (n) {
        var v = vars[n.slice(1, -1)];
        return v == null || v === "";
      });
      if (nomes.length && vazias.length === nomes.length) return null;
      return linha.replace(/\{(\w+)\}/g, function (_, k) { return vars[k] == null ? "" : vars[k]; }).replace(/^\s+/, "");
    }).filter(function (l) { return l !== null; }).join("\n");
  }

  function textoSabores(m) {
    var sabores = m.sabores
      .filter(function (s) { return s.em_estoque; })
      .map(function (s) { return "• " + s.nome + (s.versao ? " (" + s.versao + ")" : ""); })
      .join("\n");
    return preencher(CONFIG.textos.sabores, {
      loja: CONFIG.loja.nome,
      marca: m.marca,
      modelo: m.modelo,
      puffs: puffs(m.puffs),
      sabores: sabores,
      // ~texto~ é riscado no WhatsApp: o "de" da promoção.
      preco_de: emPromo(m) ? "~" + brl(m.preco_original) + "~" : "",
      preco: brl(m.preco)
    });
  }

  function textoCatalogo() {
    var blocos = marcas().map(function (marca) {
      var linhas = MODELOS
        .filter(function (m) { return m.marca === marca && m.em_estoque > 0; })
        .map(function (m) {
          return "• " + m.modelo + " · " + puffs(m.puffs) + " puffs – " + brl(m.preco) + (emPromo(m) ? " 🔥" : "");
        });
      return linhas.length ? "*" + marca.toUpperCase() + "*\n" + linhas.join("\n") : "";
    }).filter(Boolean);
    return preencher(CONFIG.textos.catalogo, {
      loja: CONFIG.loja.nome,
      catalogo_por_marca: blocos.join("\n\n"),
      horario: CONFIG.loja.horario,
      site: CONFIG.loja.site
    });
  }

  // ---------------------------------------------------------------- copiar
  // writeText precisa rodar dentro do clique. Se o navegador recusar (página
  // sem foco, permissão), cai para a seleção de texto + execCommand.
  // `depois` roda só quando a cópia deu certo.
  function copiar(texto, rotulo, depois) {
    // "Copiado: X" em vez de "X copiado": serve para "Mensagem padrão" e
    // para "Catálogo" sem errar a concordância.
    function ok() {
      aviso("Copiado: " + rotulo + ". Cole no WhatsApp com Ctrl+V.");
      if (depois) depois();
    }
    function alternativo() {
      var ta = document.createElement("textarea");
      ta.value = texto;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      var feito = false;
      try { feito = document.execCommand("copy"); } catch (e) { /* segue para o aviso */ }
      document.body.removeChild(ta);
      if (feito) ok();
      else aviso("O navegador bloqueou a cópia. Tente de novo com o painel em foco.", true);
    }
    try { navigator.clipboard.writeText(texto).then(ok, alternativo); } catch (e) { alternativo(); }
  }

  // Imagem dos sabores (atendimento-imagem.js). A PROMESSA da imagem vai
  // direto para o ClipboardItem, ainda dentro do clique: o Chrome só deixa
  // escrever na área de transferência durante o gesto. Se ele recusar, a
  // imagem aparece na tela para copiar com o botão direito.
  function copiarImagem(m) {
    if (!window.ATD_IMAGEM) return;
    var blob = window.ATD_IMAGEM.gerar(m, CONFIG.loja);
    function mostrar() {
      // data: e não blob:, porque a CSP da loja só libera img-src 'self' data:.
      blob.then(function (b) {
        var leitor = new FileReader();
        leitor.onload = function () {
          $("imgPrevia").src = leitor.result;
          $("imgFundo").hidden = false;
        };
        leitor.readAsDataURL(b);
      }, function () { aviso("Não consegui gerar a imagem. Tente de novo.", true); });
    }
    try {
      navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]).then(function () {
        aviso("Copiado: Imagem do " + m.modelo + ". Cole no WhatsApp com Ctrl+V.");
      }, mostrar);
    } catch (e) { mostrar(); }
  }

  var avisoTimer = null;
  function aviso(msg, erro) {
    var t = $("toast");
    t.className = "pn-toast" + (erro ? " erro" : "");
    t.innerHTML = icon(erro ? "x" : "check") + "<span>" + esc(msg) + "</span>";
    t.hidden = false;
    clearTimeout(avisoTimer);
    avisoTimer = setTimeout(function () { t.hidden = true; }, erro ? 4000 : 2400);
  }

  // ================================================================ PEDIDO
  function pedidoVazio() {
    return { cliente: "", itens: [], retirada: false, loc: "", pag: "pix", moto: null, copiados: {} };
  }
  // Lê o que ficou salvo neste navegador. Qualquer coisa estranha (outro
  // formato, storage bloqueado) vira um pedido em branco: nunca trava o painel.
  function lerSalvo() {
    try {
      var d = JSON.parse(localStorage.getItem(CHAVE_LOCAL) || "null");
      if (d && d.ativo && Array.isArray(d.ativo.itens) && Array.isArray(d.espera)) {
        d.espera = d.espera.filter(function (e) { return e && e.p && Array.isArray(e.p.itens); }).slice(0, LIMITE_ESPERA);
        [d.ativo].concat(d.espera.map(function (e) { return e.p; })).forEach(function (p) {
          if (!p.copiados || typeof p.copiados !== "object") p.copiados = {};
          if (!PAGAMENTOS[p.pag]) p.pag = "pix";
          p.loc = String(p.loc || "");
          p.cliente = String(p.cliente || "");
          p.itens = p.itens.filter(function (i) { return i && i.fid > 0 && i.qty > 0; });
        });
        return d;
      }
    } catch (e) { /* storage indisponível ou dado quebrado */ }
    return { ativo: pedidoVazio(), espera: [] };
  }
  var ped = lerSalvo();
  function salvar() {
    try { localStorage.setItem(CHAVE_LOCAL, JSON.stringify(ped)); } catch (e) { /* segue só na memória */ }
  }
  function P() { return ped.ativo; }
  function qtdItens(p) { return p.itens.reduce(function (a, i) { return a + i.qty; }, 0); }

  // ---------------------------------------------------------------- cotação
  // Cada mudança no pedido pede a conta de novo. `cot.chave` guarda para qual
  // pedido aquela resposta vale; se o pedido mudou depois, a resposta velha
  // não serve para copiar nada.
  var cot = { chave: "", dados: null, erro: "", carregando: false };
  var cotSeq = 0;
  var cotTimer = null;

  function pedidoParaServidor(p) {
    return {
      itens: p.itens.map(function (i) { return { flavor_id: i.fid, qty: i.qty }; }),
      retirada: !!p.retirada,
      localizacao: p.retirada ? "" : p.loc.trim(),
      pagamento: p.pag
    };
  }
  function chaveDe(p) { return JSON.stringify(pedidoParaServidor(p)); }
  function cotacaoValida() { return !!cot.dados && !cot.carregando && cot.chave === chaveDe(P()); }
  function contaFechada() { return cotacaoValida() && cot.dados.status === "ok"; }

  function cotar(espera) {
    clearTimeout(cotTimer);
    cotSeq++;
    if (!P().itens.length) {
      cot = { chave: chaveDe(P()), dados: null, erro: "", carregando: false };
      desenharPedido();
      return;
    }
    cot.carregando = true;
    desenharPedido();
    var seq = cotSeq;
    cotTimer = setTimeout(function () {
      var chave = chaveDe(P());
      api("/api/atendimento/cotacao", JSON.parse(chave)).then(function (d) {
        if (seq !== cotSeq) return;
        cot = { chave: chave, dados: d, erro: "", carregando: false };
        guardarNomes(d.itens);
        desenharPedido();
      }, function (e) {
        if (seq !== cotSeq) return;
        cot = { chave: chave, dados: null, erro: e.message, carregando: false };
        desenharPedido();
      });
    }, espera || 0);
  }
  // O nome de cada item fica salvo junto: se o sabor sair do catálogo, o
  // pedido guardado ainda mostra o que era.
  function guardarNomes(itens) {
    var mudou = false;
    (itens || []).forEach(function (it) {
      var meu = P().itens.find(function (i) { return i.fid === it.flavor_id; });
      var nome = it.modelo + " · " + it.sabor;
      if (meu && meu.nome !== nome) { meu.nome = nome; meu.marca = it.marca; mudou = true; }
    });
    if (mudou) salvar();
  }

  function motivoSemTotal() {
    if (cot.erro) return cot.erro;
    var d = cot.dados;
    if (!d) return "";
    if (d.status === "sem_localizacao") return "Falta a localização";
    if (d.status === "a_combinar") return (d.zona || "Zona especial") + ": frete a combinar";
    if (d.status === "fora_da_area") return "Fora da área de entrega";
    return "";
  }

  // ---------------------------------------------------------------- ações
  function mudou(espera) {
    salvar();
    cotar(espera);
  }
  function adicionar(fid) {
    var x = SABOR[fid];
    if (!x || !x.s.em_estoque) return;
    var it = P().itens.find(function (i) { return i.fid === fid; });
    if (it) {
      if (it.qty >= QTD_MAX) { aviso("No máximo " + QTD_MAX + " unidades por sabor.", true); return; }
      it.qty++;
    } else {
      P().itens.push({ fid: fid, qty: 1, nome: x.m.modelo + " · " + x.s.nome, marca: x.m.marca });
    }
    aviso("No pedido: " + x.m.modelo + " " + x.s.nome + (it ? " (" + it.qty + ")" : ""));
    desenharLista();
    mudou();
  }
  function guardar() {
    var p = P();
    if (!p.itens.length) { aviso("Pedido vazio: nada para guardar.", true); return; }
    if (ped.espera.length >= LIMITE_ESPERA) {
      aviso("Já há " + LIMITE_ESPERA + " pedidos em espera. Reabra ou apague um.", true);
      return;
    }
    if (!p.cliente.trim()) p.cliente = "Sem nome";
    p.ultimoTotal = contaFechada() ? cot.dados.total : null;
    ped.espera.unshift({ ts: Date.now(), p: p });
    ped.ativo = pedidoVazio();
    aviso("Guardado: " + p.cliente + ". Pedido novo aberto.");
    trocouPedido();
  }
  function reabrir(i) {
    var e = ped.espera.splice(i, 1)[0];
    if (!e) return;
    // O pedido que estava aberto vai para a espera no lugar dele.
    if (P().itens.length) {
      if (!P().cliente.trim()) P().cliente = "Sem nome";
      P().ultimoTotal = contaFechada() ? cot.dados.total : null;
      ped.espera.unshift({ ts: Date.now(), p: P() });
    }
    ped.ativo = e.p;
    fecharEspera();
    aviso("Reaberto: " + e.p.cliente);
    trocouPedido();
    abrirAba("ped");
  }
  // ---------------------------------------------------------------- um pedido por conversa
  // A extensão avisa quando a atendente abre outra conversa no WhatsApp Web
  // (só o nome do contato). O pedido de cada conversa fica guardado sozinho:
  // abrir a conversa do João mostra um pedido limpo com "João" no topo, e
  // voltar para a Maria reabre o dela do jeito que estava.
  function trocarConversa(nome) {
    var p = P();
    if (p.conversa === nome) return;
    // Pedido sem conversa (montado antes de a extensão avisar) e sem outro
    // cliente digitado: passa a ser desta conversa.
    if (!p.conversa && (!p.cliente.trim() || p.cliente.trim() === nome)) {
      p.conversa = nome;
      if (!p.cliente.trim()) p.cliente = nome;
      salvar();
      preencherCampos();
      desenharPedido();
      return;
    }
    var msg;
    if (p.itens.length) {
      if (!p.cliente.trim()) p.cliente = p.conversa || "Sem nome";
      p.ultimoTotal = contaFechada() ? cot.dados.total : null;
      ped.espera.unshift({ ts: Date.now(), p: p });
      // Espera cheia: sai o pedido guardado há mais tempo.
      if (ped.espera.length > LIMITE_ESPERA) {
        var velho = ped.espera.pop();
        msg = "A espera estava cheia: saiu o pedido de " + velho.p.cliente + ".";
      }
    }
    var i = ped.espera.findIndex(function (e) { return e.p.conversa === nome; });
    if (i >= 0) {
      ped.ativo = ped.espera.splice(i, 1)[0].p;
      aviso(msg || "Pedido de " + ped.ativo.cliente + " reaberto.", !!msg);
    } else {
      ped.ativo = pedidoVazio();
      ped.ativo.cliente = nome;
      ped.ativo.conversa = nome;
      if (msg) aviso(msg, true);
    }
    desarmarNovo();
    trocouPedido();
  }
  window.addEventListener("message", function (e) {
    // Só a nossa extensão, e só o quadro que contém o painel.
    if (!CFG.extensao || e.origin !== CFG.extensao || e.source !== window.parent) return;
    var d = e.data;
    if (!d || d.fonte !== "atd-extensao" || d.tipo !== "conversa") return;
    var nome = String(d.nome || "").trim().slice(0, 60);
    if (nome) trocarConversa(nome);
  });

  function apagarGuardado(i) {
    var e = ped.espera.splice(i, 1)[0];
    salvar();
    desenharEspera();
    desenharContadores();
    if (e) aviso("Apagado: " + e.p.cliente);
  }
  // "Novo" com itens pede um segundo toque: não se perde um pedido sem querer.
  var novoArmado = null;
  function novo() {
    var b = $("btnNovo");
    if (P().itens.length && !novoArmado) {
      b.classList.add("armado");
      b.querySelector("span").textContent = "Apagar?";
      novoArmado = setTimeout(desarmarNovo, 3000);
      return;
    }
    desarmarNovo();
    // Na mesma conversa do WhatsApp, o pedido novo continua sendo daquele cliente.
    var conversa = P().conversa;
    ped.ativo = pedidoVazio();
    if (conversa) { ped.ativo.conversa = conversa; ped.ativo.cliente = conversa; }
    aviso("Pedido novo aberto.");
    trocouPedido();
    $("cliente").focus();
  }
  function desarmarNovo() {
    clearTimeout(novoArmado);
    novoArmado = null;
    $("btnNovo").classList.remove("armado");
    $("btnNovo").querySelector("span").textContent = "Novo";
  }
  function trocouPedido(semSalvar) {
    if (!semSalvar) salvar();
    cot = { chave: "", dados: null, erro: "", carregando: false };
    preencherCampos();
    if (CONFIG) desenharLista();
    if (CONFIG) cotar(); else desenharPedido();
  }

  // ---------------------------------------------------------------- desenho do pedido
  // Campos que a atendente digita (nome, local) não são redesenhados a cada
  // tecla, para não perder o cursor: só são preenchidos ao trocar de pedido.
  function preencherCampos() {
    $("cliente").value = P().cliente;
    $("local").value = P().loc;
    desenharEscolhas();
  }
  function desenharEscolhas() {
    var p = P();
    $("segEntrega").querySelectorAll("[data-ret]").forEach(function (b) {
      b.setAttribute("aria-pressed", String((b.dataset.ret === "1") === !!p.retirada));
    });
    $("segPag").querySelectorAll("[data-pag]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.pag === p.pag));
    });
    $("blocoLocal").hidden = !!p.retirada;
    $("dicaRetirada").hidden = !p.retirada;
  }

  function desenharItens() {
    var p = P();
    var porId = {};
    if (cotacaoValida()) cot.dados.itens.forEach(function (it) { porId[it.flavor_id] = it; });
    $("pedItens").innerHTML = p.itens.length ? p.itens.map(function (i) {
      var x = SABOR[i.fid], srv = porId[i.fid];
      var nome = x ? x.m.modelo + " · " + x.s.nome : (i.nome || "Sabor fora do catálogo");
      var marca = x ? x.m.marca : (i.marca || "");
      return '<div class="pd-it"><div class="pd-it-main"><b>' + esc(nome) + "</b><span>" + esc(marca) +
          (srv ? " · " + brl(srv.preco) : "") + "</span></div>" +
        '<span class="pd-qty"><button type="button" data-menos="' + i.fid + '" aria-label="' + (i.qty > 1 ? "Tirar um" : "Remover") + '">' +
          (i.qty > 1 ? "−" : "×") + "</button><span>" + i.qty + "</span>" +
          '<button type="button" data-mais="' + i.fid + '" aria-label="Mais um">+</button></span>' +
        '<span class="pd-it-tot">' + (srv ? brl(srv.total) : "…") + "</span></div>";
    }).join("") : '<div class="pd-hint">Abra um modelo no Catálogo e toque no sabor que o cliente escolheu.</div>';
  }

  function desenharZona() {
    var z = $("zona"), d = cotacaoValida() ? cot.dados : null;
    z.className = "pd-zona";
    z.innerHTML = "";
    if (P().retirada || !P().itens.length || cot.carregando) return;
    if (cot.erro && /localiza/i.test(cot.erro)) {
      z.className = "pd-zona erro";
      z.innerHTML = icon("x") + esc(cot.erro);
    } else if (d && d.status === "ok") {
      z.className = "pd-zona ok";
      z.innerHTML = icon("check") + esc(d.zona) + " · " +
        (d.frete_gratis ? "frete grátis <span>(" + brl(d.frete_cheio) + ")</span>" : brl(d.frete));
    } else if (d && (d.status === "a_combinar" || d.status === "fora_da_area")) {
      z.className = "pd-zona erro";
      z.innerHTML = icon("x") + esc(motivoSemTotal()) + ". O total não fecha.";
    }
  }

  function desenharConta() {
    var p = P(), d = cotacaoValida() ? cot.dados : null;
    var linhas = "";
    if (d) {
      linhas = "<div><span>Itens (" + qtdItens(p) + ")</span><span>" + brl(d.subtotal) + "</span></div>";
      if (!d.retirada && d.status === "ok") {
        linhas += "<div><span>Frete · " + esc(d.zona) + "</span>" + (d.frete_gratis
          ? '<span class="gr"><s>' + brl(d.frete_cheio) + "</s>grátis</span>"
          : "<span>" + brl(d.frete) + "</span>") + "</div>";
      }
      if (d.acrescimo) linhas += "<div><span>Crédito +" + d.credito_pct + "%</span><span>" + brl(d.acrescimo) + "</span></div>";
    }
    var tot;
    if (!p.itens.length) tot = '<b class="calc">Sem itens</b>';
    else if (contaFechada()) tot = "<b>" + brl(d.total) + "</b>";
    else if (cot.carregando || (!d && !cot.erro)) tot = '<b class="calc">Calculando…</b>';
    else tot = '<b class="pend">' + esc(motivoSemTotal()) + "</b>";
    $("conta").innerHTML = (linhas ? '<div class="pd-conta">' + linhas + "</div>" : "") +
      '<div class="pd-tot"><span>' + icon("shield") + "Total calculado pelo sistema</span>" + tot + "</div>";
    $("btnResumo").disabled = !contaFechada();
  }

  function desenharContadores() {
    var n = qtdItens(P());
    $("tabPedN").hidden = !n;
    $("tabPedN").textContent = n;
    var e = ped.espera.length;
    $("esperaN").hidden = !e;
    $("esperaN").textContent = e;
    var barra = $("barraPedido");
    barra.hidden = !n;
    if (n) {
      barra.innerHTML = icon("cart") + "<span><b>" + esc(P().cliente || "Pedido") + "</b> · " + n + (n > 1 ? " itens" : " item") +
        (contaFechada() ? " · <b>" + brl(cot.dados.total) + "</b>" : "") + "</span>Ver pedido" + icon("chevron-right");
    }
  }

  function desenharPedido() {
    desenharItens();
    desenharZona();
    desenharConta();
    desenharContadores();
    desenharMensagens();
  }

  // ---------------------------------------------------------------- mensagens
  // Os textos na ordem do atendimento. No Pix: padrão, resumo, dados do Pix,
  // agradecimento (depois do comprovante). Dinheiro e cartão: padrão, resumo,
  // confirmação, agradecimento.
  function motoboys() { return (CONFIG.motoboys || []).filter(function (m) { return m.ativo; }); }

  function passos() {
    var p = P(), d = contaFechada() ? cot.dados : null;
    var bloqueio = "";
    if (!p.itens.length) bloqueio = "Adicione um sabor ao pedido";
    else if (!d) bloqueio = motivoSemTotal() || "Calculando o total…";

    var resumo = "";
    if (d) {
      var itens = d.itens.map(function (it) {
        return "• " + it.qty + "x " + it.marca + " " + it.modelo + " – " + it.sabor + " – " + brl(it.total);
      }).join("\n");
      resumo = preencher(CONFIG.textos.resumo, {
        itens: itens,
        // Retirada: as linhas de frete somem da mensagem.
        zona: d.retirada ? "" : d.zona,
        frete: d.retirada ? "" : (d.frete_gratis ? "grátis" : brl(d.frete)),
        acrescimo: d.acrescimo ? brl(d.acrescimo) : "",
        total: brl(d.total)
      });
    }
    var lista = [
      { k: "padrao", t: "Mensagem padrão", d: "Pede sabor, local e pagamento", txt: CONFIG.textos.padrao, bloq: "" },
      { k: "resumo", t: "Resumo do pedido", d: "Para o cliente confirmar", txt: resumo, bloq: bloqueio }
    ];
    if (p.pag === "pix") {
      lista.push({
        k: "pix", t: "Dados do Pix", d: "Depois do \"pode confirmar\"",
        txt: d ? preencher(CONFIG.textos.pix, {
          loja: CONFIG.loja.nome, pix_tipo: CONFIG.loja.pix_tipo, pix_chave: CONFIG.loja.pix_chave,
          pix_titular: CONFIG.loja.pix_titular, total: brl(d.total)
        }) : "",
        bloq: bloqueio || (CONFIG.loja.pix_chave ? "" : "Chave Pix não cadastrada. O dono cadastra em Ajustes.")
      });
    } else {
      lista.push({
        k: "conf", t: "Confirmação", d: PAGAMENTOS[p.pag] + " na entrega",
        txt: d ? preencher(CONFIG.textos.confirmacao, { total: brl(d.total), pagamento: PAGAMENTOS[p.pag] }) : "",
        bloq: bloqueio
      });
    }
    var motos = motoboys();
    var moto = p.retirada ? null : motos.find(function (m) { return m.id === p.moto; });
    lista.push({
      k: "agr", t: "Agradecimento", d: p.pag === "pix" ? "Quando chegar o comprovante" : "Com o motoboy que vai levar",
      moto: true,
      txt: preencher(CONFIG.textos.agradecimento, {
        prazo: CONFIG.loja.prazo, motoboy: moto ? moto.nome : "", motoboy_tel: moto ? moto.telefone : ""
      }),
      // Sem motoboy cadastrado ainda (ou retirada), sai sem a linha dele.
      bloq: motos.length && !moto && !p.retirada ? "Escolha o motoboy" : ""
    });
    return lista;
  }

  var previewAberto = {};
  function desenharMensagens() {
    if (!CONFIG) return;
    var p = P(), d = contaFechada() ? cot.dados : null;
    $("msgCliente").textContent = p.cliente || "Sem nome";
    $("msgSub").textContent = d
      ? brl(d.total) + " · " + PAGAMENTOS[p.pag] + (d.retirada ? " · retirada" : " · " + d.zona)
      : (p.itens.length ? (motivoSemTotal() || "Calculando o total…") : "Pedido sem itens");
    var ps = passos();
    var chave = chaveDe(p);
    // Uma cópia vale para o pedido daquele momento. Se o pedido mudou depois
    // (ex.: copiou o resumo e o cliente pediu mais um), o passo volta a pedir
    // cópia, para o cliente não ficar com um total velho.
    function copiado(k) {
      var c = p.copiados[k];
      if (!c) return null;
      if (k === "padrao" || k === "agr") return c;
      // Mesmo pedido E mesmo total: se o preço mudou no admin depois da
      // cópia, o cliente ficou com um total velho e o passo pede de novo.
      return c.chave === chave && (c.total == null || (d && d.total === c.total)) ? c : null;
    }
    var prox = ps.findIndex(function (x) { return !copiado(x.k) && !x.bloq; });
    var motos = motoboys();
    $("msgLista").innerHTML = ps.map(function (x, i) {
      var feito = copiado(x.k), velho = p.copiados[x.k] && !feito;
      var escolha = x.moto && motos.length && !p.retirada ? '<div class="ms-moto">Motoboy:' + motos.map(function (m) {
        return '<button type="button" data-moto="' + m.id + '" aria-pressed="' + (p.moto === m.id) + '">' + icon("motorbike") + esc(m.nome) + "</button>";
      }).join("") + "</div>" : "";
      return '<div class="ms' + (i === prox ? " prox" : "") + (x.bloq && !x.moto ? " off" : "") + '">' +
        '<div class="ms-top"><span class="ms-n">' + (feito ? icon("check") : i + 1) + "</span>" +
          '<span class="ms-t"><b>' + esc(x.t) + "</b><span>" +
            (feito ? "Copiada às " + hora(feito.ts) : velho ? "O pedido mudou: copie de novo" : esc(x.d)) + "</span></span>" +
          '<button type="button" class="btn' + (i === prox ? " btn-pri" : "") + '" data-msg="' + x.k + '"' + (x.bloq ? " disabled" : "") + ">" +
            icon("message") + "Copiar</button></div>" +
        escolha +
        (x.bloq ? '<div class="ms-aviso">' + esc(x.bloq) + "</div>" : "") +
        (x.txt ? '<button type="button" class="ms-prev" data-prev="' + x.k + '" aria-expanded="' + !!previewAberto[x.k] + '" title="Ver a mensagem inteira">' +
          '<div class="wa-bubble">' + waHtml(x.txt) + "</div></button>" : "") +
        "</div>";
    }).join("");
  }
  function copiarMensagem(k) {
    if (!CONFIG) return;
    var x = passos().find(function (y) { return y.k === k; });
    if (!x || x.bloq || !x.txt) return;
    var chave = chaveDe(P());
    copiar(x.txt, x.t, function () {
      P().copiados[k] = { ts: Date.now(), chave: chave, total: contaFechada() ? cot.dados.total : null };
      salvar();
      desenharMensagens();
    });
  }

  // ---------------------------------------------------------------- em espera
  function desenharEspera() {
    $("esperaConta").textContent = ped.espera.length + " de " + LIMITE_ESPERA;
    $("esperaLista").innerHTML = ped.espera.length ? ped.espera.map(function (e, i) {
      var n = qtdItens(e.p);
      return '<div class="es-row"><button type="button" class="es-abrir" data-reabrir="' + i + '"><b>' + esc(e.p.cliente) + "</b><span>" +
        n + (n > 1 ? " itens" : " item") + (e.p.ultimoTotal != null ? " · " + brl(e.p.ultimoTotal) : "") +
        " · " + PAGAMENTOS[e.p.pag] + " · guardado às " + hora(e.ts) + "</span></button>" +
        '<button type="button" class="pd-ib" data-apagar="' + i + '" aria-label="Apagar o pedido de ' + esc(e.p.cliente) + '">' + icon("trash") + "</button></div>";
    }).join("") : '<div class="es-vazio">Nenhum pedido guardado. Use "Guardar" para pausar um cliente e atender outro.</div>';
  }
  function abrirEspera() {
    desenharEspera();
    $("espera").hidden = false;
    $("btnFecharEspera").focus();
  }
  function fecharEspera() { $("espera").hidden = true; }

  // ---------------------------------------------------------------- abas
  // Cada botão de aba aponta (aria-controls) para a seção dele. Ajustes só
  // existe na página do dono.
  function abrirAba(aba) {
    var achou = false;
    painel.querySelectorAll(".pn-tabs [data-aba]").forEach(function (b) {
      var on = b.dataset.aba === aba;
      achou = achou || on;
      b.setAttribute("aria-selected", String(on));
      $(b.getAttribute("aria-controls")).hidden = !on;
    });
    if (!achou) { abrirAba("cat"); return; }
    st.aba = aba;
    try { sessionStorage.setItem("atd_aba", aba); } catch (e) { /* só conveniência */ }
  }

  // ================================================================ CATÁLOGO
  // Acha por marca, modelo (com ou sem espaço: "pulse x" e "pulsex"), nome
  // das versões e sabor ("mint").
  function filtrar() {
    var q = norm(st.q).trim();
    var qJunto = q.replace(/\s/g, "");
    return MODELOS.filter(function (m) {
      if (st.marca && m.marca !== st.marca) return false;
      if (!q) return true;
      var alvo = norm([m.marca, m.modelo, m.busca].join(" "));
      if (alvo.indexOf(q) >= 0 || alvo.replace(/\s/g, "").indexOf(qJunto) >= 0) return true;
      return m.sabores.some(function (s) { return norm(s.nome).indexOf(q) >= 0; });
    });
  }
  function bateSabor(s) {
    var q = norm(st.q).trim();
    return q && norm(s.nome).indexOf(q) >= 0;
  }

  function precoHtml(m) {
    return '<span class="price">' + (emPromo(m) ? "<s>" + brl(m.preco_original) + "</s>" : "") +
      "<b>" + brl(m.preco) + "</b></span>";
  }

  function desenharMarcas() {
    chips.innerHTML = ['<button type="button" data-marca="" aria-pressed="' + (st.marca === "") + '">Todas</button>']
      .concat(marcas().map(function (b) {
        return '<button type="button" data-marca="' + esc(b) + '" aria-pressed="' + (st.marca === b) + '">' + esc(b) + "</button>";
      })).join("");
  }

  function desenharLista() {
    if (!CONFIG) return;
    var itens = filtrar();
    // Um resultado só (ex.: digitou "v400"): já abre, poupa um toque.
    var aberto = itens.length === 1 ? itens[0].id : st.aberto;
    if (!itens.length) {
      lista.innerHTML = '<div class="pn-empty">Nada encontrado. Tente o nome do modelo (v400) ou um sabor (mint).</div>';
      return;
    }
    lista.innerHTML = itens.map(function (m) {
      var on = m.id === aberto;
      var semEstoque = m.em_estoque === 0;
      return '<div class="a-item' + (semEstoque ? " sem-estoque" : "") + '">' +
        '<button type="button" class="a-row" data-id="' + m.id + '" aria-expanded="' + on + '">' +
          '<span class="a-main"><span class="a-name">' + esc(m.modelo) + '</span>' +
            '<span class="a-sub">' + esc(m.marca) + (m.puffs ? " · " + esc(m.puffs) : "") + "</span></span>" +
          '<span class="a-right">' + precoHtml(m) +
            '<span class="a-count">' + (semEstoque ? "esgotado" : m.em_estoque + " de " + m.sabores.length + " sabores") + "</span></span>" +
          icon("chevron-down") +
        "</button>" +
        (on ? corpo(m) : "") +
      "</div>";
    }).join("") + (atualizadoEm ? '<div class="pn-stamp">Catálogo atualizado às ' + atualizadoEm + "</div>" : "");
  }

  // Sabores do modelo aberto. Cada um é um botão: o toque soma 1 no pedido.
  // Esgotado fica riscado e desligado; o que já está no pedido mostra a
  // quantidade.
  function corpo(m) {
    var qtd = {};
    P().itens.forEach(function (i) { qtd[i.fid] = i.qty; });
    return '<div class="a-body">' +
      (m.em_estoque ? '<span class="flv-dica">Toque no sabor que o cliente escolheu para pôr no pedido</span>' : "") +
      '<div class="flv">' + m.sabores.map(function (s) {
        var cls = [qtd[s.id] ? "no" : "", s.em_estoque && bateSabor(s) ? "hit" : ""].join(" ").trim();
        return '<button type="button" data-add="' + s.id + '"' + (cls ? ' class="' + cls + '"' : "") +
          (s.em_estoque ? ' title="Pôr no pedido"' : ' disabled title="Esgotado"') + ">" +
          esc(s.nome) + (s.versao ? '<span class="flv-ver">' + esc(s.versao) + "</span>" : "") +
          (qtd[s.id] ? "<i>" + qtd[s.id] + "</i>" : "") + "</button>";
      }).join("") + "</div>" +
      '<div class="a-actions">' +
        '<button type="button" class="btn btn-pri" data-copiar="' + m.id + '"' + (m.em_estoque ? "" : " disabled") + ">" +
          icon("message") + "Copiar sabores</button>" +
        '<button type="button" class="btn" data-imagem="' + m.id + '"' + (m.em_estoque ? "" : " disabled") +
          ' title="Copiar a imagem dos sabores (substitui o print do site)">' + icon("device-mobile") + "Imagem</button>" +
      "</div></div>";
  }

  // ---------------------------------------------------------------- dados
  // Sem `corpoJson`, GET; com ele, POST em JSON. O token CSRF vai sempre.
  function api(url, corpoJson) {
    var op = { headers: { "X-Admin-Token": CFG.csrf }, credentials: "same-origin" };
    if (corpoJson !== undefined) {
      op.method = "POST";
      op.headers["Content-Type"] = "application/json";
      op.body = JSON.stringify(corpoJson);
    }
    return fetch(url, op).then(function (r) {
      if (r.status === 401) { window.location.href = CFG.login; throw new Error("sessão expirada"); }
      return r.json().then(function (d) {
        if (!r.ok || !d.ok) throw new Error(d.error || "erro " + r.status);
        return d;
      });
    });
  }

  // `auto`: busca automática (a cada 2 min / ao voltar ao painel). Não gira o
  // botão nem mostra erro: se falhar, tenta de novo na próxima vez.
  var carregando = null;
  var ultimaCarga = 0;
  function carregar(auto) {
    if (carregando) return carregando;
    var btn = $("btnAtualizar");
    if (auto !== true) {
      btn.classList.add("girando");
      btn.disabled = true;
    }
    carregando = Promise.all([api("/api/atendimento/catalogo"), api("/api/atendimento/config")])
      .then(function (res) {
        ultimaCarga = Date.now();
        MODELOS = res[0].modelos;
        CONFIG = res[1];
        SABOR = {};
        MODELOS.forEach(function (m) { m.sabores.forEach(function (s) { SABOR[s.id] = { m: m, s: s }; }); });
        $("lojaNome").textContent = CONFIG.loja.nome;
        atualizadoEm = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
        if (st.marca && marcas().indexOf(st.marca) < 0) st.marca = "";
        $("btnCatalogo").disabled = false;
        $("btnPadrao").disabled = false;
        desenharMarcas();
        desenharLista();
        // Preço ou estoque podem ter mudado: refaz a conta do pedido aberto.
        cotar();
        aoCarregar.forEach(function (fn) { fn(); });
      })
      .catch(function (e) {
        if (!MODELOS.length) {
          lista.innerHTML = '<div class="pn-empty">Não consegui carregar o catálogo (' + esc(e.message) + ').<br>' +
            '<button type="button" class="btn" data-recarregar>' + icon("refresh") + "Tentar de novo</button></div>";
        } else if (auto !== true) {
          aviso("Não consegui atualizar o catálogo: " + e.message, true);
        }
      })
      .then(function () {
        carregando = null;
        btn.classList.remove("girando");
        btn.disabled = false;
      });
    return carregando;
  }

  // O painel acompanha o admin sozinho: preço, promoção e estoque novos chegam
  // em no máximo 2 minutos, e na hora em que a atendente volta para o painel
  // (vindo do WhatsApp) se a última busca tiver mais de 1 minuto.
  var AUTO_INTERVALO = 2 * 60 * 1000;
  var AUTO_AO_VOLTAR = 60 * 1000;
  setInterval(function () {
    if (!document.hidden && Date.now() - ultimaCarga >= AUTO_INTERVALO - 1000) carregar(true);
  }, 15 * 1000);
  function aoVoltar() {
    if (!document.hidden && ultimaCarga && Date.now() - ultimaCarga >= AUTO_AO_VOLTAR) carregar(true);
  }
  window.addEventListener("focus", aoVoltar);
  document.addEventListener("visibilitychange", aoVoltar);

  // ---------------------------------------------------------------- eventos
  // Catálogo
  lista.addEventListener("click", function (e) {
    if (e.target.closest("[data-recarregar]")) { carregar(); return; }
    var add = e.target.closest("[data-add]");
    if (add) { adicionar(Number(add.dataset.add)); return; }
    var cp = e.target.closest("[data-copiar]");
    if (cp) {
      var m = modeloPorId(cp.dataset.copiar);
      if (m) copiar(textoSabores(m), "Sabores do " + m.modelo);
      return;
    }
    var im = e.target.closest("[data-imagem]");
    if (im) {
      var mi = modeloPorId(im.dataset.imagem);
      if (mi) copiarImagem(mi);
      return;
    }
    var row = e.target.closest(".a-row");
    if (!row) return;
    st.aberto = row.getAttribute("aria-expanded") === "true" ? null : Number(row.dataset.id);
    desenharLista();
  });

  busca.addEventListener("input", function () { st.q = busca.value; desenharLista(); lista.scrollTop = 0; });
  // Esc limpa a busca: a atendente volta rápido para a lista inteira.
  busca.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && busca.value) { busca.value = ""; st.q = ""; desenharLista(); }
  });

  chips.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) return;
    st.marca = b.dataset.marca;
    desenharMarcas();
    desenharLista();
    lista.scrollTop = 0;
  });

  $("btnCatalogo").addEventListener("click", function () { copiar(textoCatalogo(), "Catálogo"); });
  $("btnPadrao").addEventListener("click", function () { copiar(CONFIG.textos.padrao, "Mensagem padrão"); });
  $("btnAtualizar").addEventListener("click", function () { carregar(); });
  $("barraPedido").addEventListener("click", function () { abrirAba("ped"); });

  painel.querySelector(".pn-tabs").addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.aba) { abrirAba(b.dataset.aba); return; }
  });

  // Pedido
  $("cliente").addEventListener("input", function () {
    P().cliente = this.value;
    salvar();
    desenharContadores();
    $("msgCliente").textContent = P().cliente || "Sem nome";
  });
  // A cotação espera a atendente parar de colar/digitar o local.
  $("local").addEventListener("input", function () { P().loc = this.value; mudou(500); });
  $("segEntrega").addEventListener("click", function (e) {
    var b = e.target.closest("[data-ret]");
    if (!b) return;
    P().retirada = b.dataset.ret === "1";
    desenharEscolhas();
    mudou();
  });
  $("segPag").addEventListener("click", function (e) {
    var b = e.target.closest("[data-pag]");
    if (!b) return;
    P().pag = b.dataset.pag;
    desenharEscolhas();
    mudou();
  });
  $("pedItens").addEventListener("click", function (e) {
    var b = e.target.closest("[data-mais],[data-menos]");
    if (!b) return;
    var fid = Number(b.dataset.mais || b.dataset.menos);
    var i = P().itens.findIndex(function (x) { return x.fid === fid; });
    if (i < 0) return;
    if (b.dataset.mais) {
      if (P().itens[i].qty >= QTD_MAX) { aviso("No máximo " + QTD_MAX + " unidades por sabor.", true); return; }
      P().itens[i].qty++;
    } else if (P().itens[i].qty > 1) {
      P().itens[i].qty--;
    } else {
      P().itens.splice(i, 1);
    }
    desenharLista();
    mudou();
  });
  $("btnGuardar").addEventListener("click", guardar);
  $("btnNovo").addEventListener("click", novo);
  $("btnEspera").addEventListener("click", abrirEspera);
  $("btnResumo").addEventListener("click", function () { copiarMensagem("resumo"); });

  // Em espera
  $("espera").addEventListener("click", function (e) {
    if (e.target === this) { fecharEspera(); return; }
    var r = e.target.closest("[data-reabrir]");
    if (r) { reabrir(Number(r.dataset.reabrir)); return; }
    var a = e.target.closest("[data-apagar]");
    if (a) apagarGuardado(Number(a.dataset.apagar));
  });
  $("btnFecharEspera").addEventListener("click", fecharEspera);
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (!$("espera").hidden) fecharEspera();
    $("imgFundo").hidden = true;
  });

  // Imagem que o navegador não deixou copiar: fica na tela para o botão direito.
  $("imgFundo").addEventListener("click", function (e) {
    if (e.target === this || e.target.closest("#btnFecharImg")) this.hidden = true;
  });

  // Mensagens
  $("msgLista").addEventListener("click", function (e) {
    var b = e.target.closest("[data-msg],[data-moto],[data-prev]");
    if (!b) return;
    if (b.dataset.msg) { copiarMensagem(b.dataset.msg); return; }
    if (b.dataset.moto) {
      P().moto = Number(b.dataset.moto);
      salvar();
      desenharMensagens();
      return;
    }
    previewAberto[b.dataset.prev] = !previewAberto[b.dataset.prev];
    desenharMensagens();
  });

  // Outra aba do navegador mexeu no pedido (dois painéis abertos): segue o
  // que foi salvo por último, em vez de um sobrescrever o outro.
  window.addEventListener("storage", function (e) {
    if (e.key !== CHAVE_LOCAL) return;
    ped = lerSalvo();
    trocouPedido(true);  // não grava de volta: as duas abas ficariam se respondendo
  });

  // O que a aba Ajustes (atendimento-ajustes.js, só na página do dono) usa
  // daqui. Depois de salvar, ela chama recarregar(): o painel inteiro passa a
  // usar o texto/motoboy novo na hora.
  var aoCarregar = [];
  window.ATD_PAINEL = {
    api: api,
    aviso: aviso,
    copiar: copiar,
    preencher: preencher,
    waHtml: waHtml,
    brl: brl,
    esc: esc,
    icon: icon,
    hora: hora,
    recarregar: carregar,
    config: function () { return CONFIG; },
    modelos: function () { return MODELOS; },
    atualizadoEm: function () { return atualizadoEm; },
    aoCarregar: function (fn) { aoCarregar.push(fn); if (CONFIG) fn(); }
  };

  var abaSalva = null;
  try { abaSalva = sessionStorage.getItem("atd_aba"); } catch (e) { /* só conveniência */ }
  if (abaSalva && abaSalva !== "cat") abrirAba(abaSalva);
  preencherCampos();
  desenharPedido();
  carregar();
})();

/* ===================================================================
   PAINEL DE ATENDIMENTO — aba Ajustes (Etapa 4, só o dono)

   Menu de ajustes com um resumo em cada linha; tocar abre a tela daquele
   ajuste, com o "Salvar" fixo embaixo. Só é carregado na página do dono, e
   todas as rotas de escrita também são só do dono (o servidor confere).

   - Loja e entrega, Textos: salvam direto (POST /api/atendimento/config).
   - Pix: mostra "de -> para" e pede a SENHA do dono; o servidor confere a
     senha antes de gravar (o painel pode ter ficado aberto na conta dele).
   - Motoboys: cada ação grava na hora.
   - Copiar para outra loja: cada loja tem o próprio banco; o código leva
     prazo, horário, textos e motoboys, nunca Pix, nome, site ou local da retirada.
   Toda mudança vai para o histórico com o valor anterior. Depois de salvar,
   o painel recarrega a config: as atendentes já usam o novo na próxima
   atualização do painel delas.
   =================================================================== */
(function () {
  "use strict";

  var A = window.ATD_PAINEL;
  var $ = function (id) { return document.getElementById(id); };
  if (!A || !$("abaAj")) return;
  var esc = A.esc, icon = A.icon, brl = A.brl;

  // Textos e as variáveis que cada um entende (as mesmas que o painel preenche).
  var TEXTOS = [
    ["sabores", "Sabores", ["loja", "marca", "modelo", "puffs", "sabores", "preco_de", "preco"]],
    ["catalogo", "Catálogo", ["loja", "catalogo_por_marca", "horario", "site"]],
    ["padrao", "Padrão", []],
    ["resumo", "Resumo", ["itens", "zona", "frete", "acrescimo", "total"]],
    ["pix", "Pix", ["loja", "pix_tipo", "pix_chave", "pix_titular", "total"]],
    ["confirmacao", "Confirmação", ["total", "pagamento"]],
    ["agradecimento", "Agradecimento", ["prazo", "motoboy", "motoboy_tel"]],
    ["retirada", "Retirada", ["loja", "local", "mapa", "horario"]]
  ];
  var CAMPOS = {
    loja: ["atd_nome", "atd_site", "atd_grupo_vip", "atd_prazo", "atd_horario"],
    pix: ["atd_pix_tipo", "atd_pix_chave", "atd_pix_titular"],
    retirada: ["atd_retirada_local", "atd_retirada_mapa"],
    textos: TEXTOS.map(function (t) { return "atd_tpl_" + t[0]; })
  };
  var ROTULO = {
    atd_nome: "Nome nas mensagens", atd_site: "Site", atd_grupo_vip: "Grupo VIP",
    atd_prazo: "Prazo de entrega", atd_horario: "Horário",
    atd_pix_tipo: "Tipo da chave Pix", atd_pix_chave: "Chave Pix", atd_pix_titular: "Titular do Pix",
    atd_retirada_local: "Local da retirada", atd_retirada_mapa: "Mapa da retirada"
  };
  TEXTOS.forEach(function (t) { ROTULO["atd_tpl_" + t[0]] = "Texto: " + t[1]; });
  var TIPOS_PIX = ["Celular", "CPF", "CNPJ", "E-mail", "Aleatória"];

  var st = {
    tela: null, texto: "resumo", salvo: null, rasc: null,
    motoEdit: null, hist: null, histErro: "", sairArmado: null
  };
  function cfg() { return A.config(); }
  function copia(o) { return JSON.parse(JSON.stringify(o)); }
  function difs(sec) {
    return (CAMPOS[sec] || []).filter(function (k) { return (st.rasc[k] || "") !== (st.salvo[k] || ""); });
  }
  function nomeLoja() { return st.salvo.atd_nome || cfg().ajustes.nome_da_loja || "Loja"; }

  // Config nova do servidor (abriu o painel, salvou, atualizou). O que a pessoa
  // está editando e ainda não salvou continua no rascunho.
  A.aoCarregar(function () {
    var novo = cfg().ajustes && cfg().ajustes.valores;
    if (!novo) return;
    var antigo = st.salvo;
    st.salvo = copia(novo);
    if (!st.rasc) st.rasc = copia(novo);
    else Object.keys(novo).forEach(function (k) { if (!antigo || st.rasc[k] === antigo[k]) st.rasc[k] = novo[k]; });
    desenharMenu();
    if (st.tela && !$("abaAj").contains(document.activeElement)) desenharTela();
    else if (st.tela) atualizarRodape();
  });

  // ================================================================ menu
  var SECOES = [
    { k: "loja", t: "Loja e entrega", ic: "home", g: "Loja",
      res: function () { return nomeLoja() + " · " + (st.salvo.atd_prazo || "sem prazo") + " · " + (st.salvo.atd_horario || "sem horário"); } },
    { k: "pix", t: "Pix", ic: "shield", g: "Loja",
      res: function () { return st.salvo.atd_pix_chave ? (st.salvo.atd_pix_tipo || "Chave") + " · " + st.salvo.atd_pix_chave : null; },
      falta: "Não cadastrado: o passo do Pix fica travado" },
    { k: "retirada", t: "Local da retirada", ic: "map-pin", g: "Loja",
      res: function () { return st.salvo.atd_retirada_local || null; },
      falta: "Não cadastrado: o botão Retirada avisa que falta" },
    { k: "motoboys", t: "Motoboys", ic: "motorbike", g: "Atendimento",
      res: function () {
        var a = cfg().motoboys.filter(function (m) { return m.ativo; });
        return a.length ? a.length + (a.length > 1 ? " ativos · " : " ativo · ") + a.map(function (m) { return m.nome; }).join(", ") : null;
      },
      falta: "Nenhum: o agradecimento sai sem motoboy" },
    { k: "textos", t: "Textos das mensagens", ic: "message", g: "Atendimento",
      res: function () {
        var pad = cfg().ajustes.textos_padrao;
        var n = TEXTOS.filter(function (t) { return st.salvo["atd_tpl_" + t[0]] !== pad[t[0]]; }).length;
        return n ? n + " de " + TEXTOS.length + " personalizados" : TEXTOS.length + " textos, todos no original";
      } },
    { k: "copiar", t: "Copiar para outra loja", ic: "refresh", g: "Ferramentas", res: function () { return "Motoboys e textos, sem o Pix"; } },
    { k: "diag", t: "Testar frete e catálogo", ic: "truck", g: "Ferramentas", res: function () { return "Cole um local e veja a zona"; } },
    { k: "hist", t: "Histórico", ic: "clock", g: "Ferramentas", res: function () { return "Quem mudou o quê, com o valor anterior"; } }
  ];
  function secao(k) { return SECOES.find(function (s) { return s.k === k; }); }

  function desenharMenu() {
    var grupo = "";
    $("ajMenu").innerHTML = '<div class="mn">' + SECOES.map(function (s) {
      var h = s.g !== grupo ? '<div class="mn-grp">' + s.g + "</div>" : "";
      grupo = s.g;
      var r = s.res();
      return h + '<button type="button" class="mn-row" data-tela="' + s.k + '"><span class="mn-ic">' + icon(s.ic) + "</span>" +
        '<span class="mn-t"><b>' + s.t + "</b><span" + (r == null ? ' class="falta"' : "") + ">" + esc(r == null ? s.falta : r) + "</span></span>" +
        icon("chevron-right") + "</button>";
    }).join("") + "</div>";
  }

  // ================================================================ telas
  function campo(k, rotulo, ph, tipo) {
    return '<label class="aj-f"><span>' + rotulo + '</span><input class="aj-in" data-k="' + k + '" value="' + esc(st.rasc[k]) + '"' +
      ' placeholder="' + esc(ph || "") + '" maxlength="200" autocomplete="off"' + (tipo ? ' inputmode="' + tipo + '"' : "") + "></label>";
  }

  function telaLoja() {
    var c = cfg(), r = c.regras;
    return '<div class="aj-sec"><div class="aj-h">' + icon("home") + "Nas mensagens</div>" +
      campo("atd_nome", "Nome nas mensagens", c.ajustes.nome_da_loja) +
      '<div class="aj-dica">Vazio usa o nome da loja do admin (' + esc(c.ajustes.nome_da_loja) + ").</div>" +
      campo("atd_site", "Site", "royalpodsslz.com", "url") +
      campo("atd_grupo_vip", "Link do grupo VIP", "https://chat.whatsapp.com/…", "url") +
      '<div class="aj-row2">' + campo("atd_prazo", "Prazo de entrega", "até 60 minutos") + campo("atd_horario", "Horário", "10h às 23h") + "</div></div>" +
      '<div class="aj-sec"><div class="aj-h">' + icon("eye") + "Vem do site (muda no admin)</div>" +
      '<div class="aj-ro">' +
        "<div><span>WhatsApp</span><b>" + esc(c.loja.whatsapp || "—") + "</b></div>" +
        "<div><span>Instagram</span><b>" + esc(String(c.loja.instagram || "—").replace(/^https?:\/\/(www\.)?/, "")) + "</b></div>" +
        "<div><span>Frete grátis</span><b>" + (r.frete_gratis_ativo ? "a partir de " + brl(r.frete_gratis_min) + " (zonas até " + brl(r.frete_gratis_max_zona) + ")" : "desligado") + "</b></div>" +
        "<div><span>Crédito</span><b>+" + r.credito_pct + "% fixo, igual ao site</b></div>" +
      '</div><a class="aj-link" href="/admin" target="_blank" rel="noopener">' + icon("arrow-right") + "Abrir o admin</a></div>";
  }

  function exemplo() {
    var v = st.rasc;
    var modelos = A.modelos().filter(function (m) { return m.em_estoque > 0; });
    var m = modelos[0];
    var moto = cfg().motoboys.find(function (x) { return x.ativo; });
    return {
      loja: v.atd_nome || cfg().ajustes.nome_da_loja, site: v.atd_site, horario: v.atd_horario, prazo: v.atd_prazo,
      marca: m ? m.marca : "Sex Addict", modelo: m ? m.modelo : "S200", puffs: m ? String(m.puffs || "").replace(/\s*puffs?/i, "") : "20.000",
      sabores: m ? m.sabores.filter(function (s) { return s.em_estoque; }).slice(0, 3).map(function (s) { return "• " + s.nome; }).join("\n") : "• Icy Mint",
      preco_de: "", preco: m ? brl(m.preco) : "R$ 119,99",
      catalogo_por_marca: modelos.slice(0, 2).map(function (x) { return "*" + x.marca.toUpperCase() + "*\n• " + x.modelo + " – " + brl(x.preco); }).join("\n\n"),
      // Pedido de exemplo do planejamento (S200 + Zona 1 + crédito). Só para a prévia.
      itens: "• 1x Sex Addict S200 – Icy Mint – R$ 119,99", zona: "Zona 1", frete: "R$ 8,00", acrescimo: "R$ 6,40", total: "R$ 134,39",
      pagamento: "Crédito", pix_tipo: v.atd_pix_tipo, pix_chave: v.atd_pix_chave, pix_titular: v.atd_pix_titular,
      motoboy: moto ? moto.nome : "", motoboy_tel: moto ? moto.telefone : "",
      local: v.atd_retirada_local || "Prédio da loja – ponto de referência", mapa: v.atd_retirada_mapa
    };
  }
  function previaPix() {
    return A.waHtml(A.preencher(st.rasc.atd_tpl_pix, Object.assign(exemplo(), { total: "R$ 127,99" })));
  }
  function telaPix() {
    return '<div class="aj-sec"><div class="aj-lock">' + icon("shield") +
      "<span>Só você vê e muda o Pix. Ao salvar, o painel pede a <b>sua senha</b>, e a troca fica no histórico com a chave anterior.</span></div>" +
      '<div class="aj-f"><span>Tipo da chave</span></div><div class="aj-chips" role="group" aria-label="Tipo da chave">' + TIPOS_PIX.map(function (t) {
        return '<button type="button" data-tipo="' + t + '" aria-pressed="' + (st.rasc.atd_pix_tipo === t) + '">' + t + "</button>";
      }).join("") + "</div>" +
      campo("atd_pix_chave", "Chave Pix", "98 98888-0000") +
      campo("atd_pix_titular", "Nome do titular", "Como aparece no banco") +
      '<div class="aj-h">' + icon("message") + "Como a mensagem sai (exemplo de R$ 127,99)</div>" +
      '<div class="aj-prev"><div class="wa-bubble" id="ajPrevPix">' + previaPix() + "</div></div></div>";
  }

  // Local da retirada: o que o cliente reconhece + o link do Google Maps, com a
  // prévia da mensagem do botão "Retirada" (texto editável em Textos).
  function previaRetirada() { return A.waHtml(A.preencher(st.rasc.atd_tpl_retirada, exemplo())); }
  function telaRetirada() {
    return '<div class="aj-sec">' +
      campo("atd_retirada_local", "Onde fica (como o cliente reconhece)", "Prédio cinza – ao lado da farmácia") +
      campo("atd_retirada_mapa", "Link do Google Maps", "https://maps.google.com/…", "url") +
      '<div class="aj-dica">No WhatsApp Web, abra a localização da loja, copie o link do Google Maps e cole aqui. Cada loja tem o seu: este local não vai no "Copiar para outra loja".</div></div>' +
      '<div class="aj-sec"><div class="aj-h">' + icon("message") + "Como o cliente recebe</div>" +
      '<div class="aj-prev"><div class="wa-bubble" id="ajPrevRet">' + previaRetirada() + "</div></div></div>";
  }

  function telaMotoboys() {
    var lista = cfg().motoboys.slice().sort(function (a, b) { return (b.ativo - a.ativo) || a.nome.localeCompare(b.nome, "pt-BR"); });
    return '<div class="aj-sec"><div class="aj-dica">As atendentes escolhem o motoboy no agradecimento. Desativar tira da lista delas sem apagar o histórico.</div>' +
      (lista.length ? lista.map(function (m) {
        if (st.motoEdit === m.id) {
          return '<div class="mb"><div class="mb-edit">' +
            '<input class="aj-in" id="ajMotoNome" value="' + esc(m.nome) + '" aria-label="Nome" maxlength="60">' +
            '<input class="aj-in" id="ajMotoTel" value="' + esc(m.telefone) + '" aria-label="Telefone" maxlength="30" inputmode="tel">' +
            '<div class="aj-row2"><button type="button" class="btn" data-mcancelar>Cancelar</button>' +
            '<button type="button" class="btn btn-pri" data-msalvar="' + m.id + '">Salvar</button></div></div></div>';
        }
        return '<div class="mb' + (m.ativo ? "" : " off") + '"><span class="mn-ic">' + icon("motorbike") + "</span>" +
          '<div class="mb-main"><b>' + esc(m.nome) + (m.ativo ? "" : " <em>· desativado</em>") + "</b><span>" + esc(m.telefone) + "</span></div>" +
          (m.ativo ? '<button type="button" class="mini" data-meditar="' + m.id + '">Editar</button>' +
                     '<button type="button" class="mini" data-mativo="' + m.id + '" data-v="0">Desativar</button>'
                   : '<button type="button" class="mini" data-mativo="' + m.id + '" data-v="1">Reativar</button>') + "</div>";
      }).join("") : '<div class="aj-dica">Nenhum motoboy cadastrado ainda.</div>') +
      '<div class="aj-h">' + icon("bag-plus") + "Adicionar motoboy</div>" +
      '<div class="aj-row2"><input class="aj-in" id="ajNovoNome" placeholder="Nome" maxlength="60" aria-label="Nome do motoboy">' +
      '<input class="aj-in" id="ajNovoTel" placeholder="98 9…" maxlength="30" inputmode="tel" aria-label="Telefone do motoboy"></div>' +
      '<button type="button" class="btn" data-madd>' + icon("bag-plus") + "Adicionar</button></div>";
  }

  function previaTexto() { return A.waHtml(A.preencher(st.rasc["atd_tpl_" + st.texto], exemplo())); }
  function telaTextos() {
    var t = TEXTOS.find(function (x) { return x[0] === st.texto; });
    var k = "atd_tpl_" + t[0];
    var original = cfg().ajustes.textos_padrao[t[0]];
    return '<div class="aj-sec"><div class="aj-chips" role="group" aria-label="Qual texto">' + TEXTOS.map(function (x) {
        var mudou = st.rasc["atd_tpl_" + x[0]] !== st.salvo["atd_tpl_" + x[0]];
        return '<button type="button" data-texto="' + x[0] + '" aria-pressed="' + (st.texto === x[0]) + '">' + x[1] + (mudou ? " •" : "") + "</button>";
      }).join("") + "</div>" +
      '<textarea class="aj-in aj-tpl" data-k="' + k + '" id="ajTexto" rows="8" maxlength="2000" aria-label="Texto ' + t[1] + '">' + esc(st.rasc[k]) + "</textarea>" +
      (t[2].length ? '<div class="aj-dica">Toque para pôr no texto onde está o cursor. Uma linha cujas variáveis ficarem vazias some sozinha (ex.: o crédito num pedido no Pix).</div>' +
        '<div class="aj-vars">' + t[2].map(function (v) { return '<button type="button" data-var="' + v + '">{' + v + "}</button>"; }).join("") + "</div>" : "") +
      '<div class="aj-h">' + icon("eye") + "Prévia com um pedido de exemplo</div>" +
      '<div class="aj-prev"><div class="wa-bubble" id="ajPrevTexto">' + previaTexto() + "</div></div>" +
      (st.rasc[k] !== original ? '<button type="button" class="aj-link" data-original>' + icon("refresh") + "Voltar ao texto original</button>" : "") + "</div>";
  }

  function telaCopiar() {
    return '<div class="aj-sec"><div class="aj-dica">Cada loja tem o próprio banco. Para repetir aqui o que você fez em outra loja: lá, toque em <b>Copiar configuração</b>; aqui, cole o código. ' +
      "Vão juntos motoboys, textos, prazo e horário. <b>Pix, nome, site e local da retirada nunca vão no código.</b></div>" +
      '<button type="button" class="btn" data-exportar>' + icon("message") + "Copiar configuração desta loja</button>" +
      '<label class="aj-f"><span>Colar código de outra loja</span><textarea class="aj-in" id="ajCodigo" rows="3" placeholder="ATD1:…"></textarea></label>' +
      '<div id="ajImport" aria-live="polite"></div></div>';
  }

  function telaDiag() {
    var modelos = A.modelos(), sabores = 0;
    modelos.forEach(function (m) { sabores += m.em_estoque; });
    return '<div class="aj-sec"><div class="aj-h">' + icon("truck") + "Testar frete</div>" +
      '<textarea class="aj-in" id="ajFreteTexto" rows="2" placeholder="Cole um link do Maps ou -2.53, -44.30"></textarea>' +
      '<div id="ajFrete" aria-live="polite"></div></div>' +
      '<div class="aj-sec"><div class="aj-h">' + icon("grid") + "Catálogo no painel</div>" +
      '<div class="aj-ro"><div><span>Atualizado</span><b>às ' + esc(A.atualizadoEm() || "—") + "</b></div>" +
      "<div><span>Modelos</span><b>" + modelos.length + " modelos · " + sabores + " sabores em estoque</b></div></div>" +
      '<div class="aj-dica">Sabor esgotado se marca no admin, como sempre: o painel lê o mesmo cadastro.</div></div>';
  }

  // Histórico: rótulo amigável de cada chave e dos motoboys (gravados em JSON).
  function motoTexto(v) {
    try { var m = JSON.parse(v); return m.nome + " · " + m.telefone + (m.ativo ? "" : " · desativado"); } catch (e) { return v; }
  }
  function curto(v) { v = String(v == null ? "" : v); return v.length > 70 ? v.slice(0, 70) + "…" : v; }
  function telaHist() {
    if (st.histErro) return '<div class="aj-sec"><div class="md-erro">' + esc(st.histErro) + "</div></div>";
    if (!st.hist) return '<div class="aj-sec"><div class="aj-dica">Carregando…</div></div>';
    if (!st.hist.length) return '<div class="aj-sec"><div class="aj-dica">Nenhuma mudança ainda.</div></div>';
    return '<div class="aj-sec">' + st.hist.map(function (h) {
      var moto = /^motoboy:/.test(h.chave);
      var de = moto ? (h.valor_anterior ? motoTexto(h.valor_anterior) : "") : curto(h.valor_anterior);
      var para = moto ? motoTexto(h.valor_novo) : curto(h.valor_novo);
      var titulo = moto ? (h.valor_anterior ? "Motoboy alterado" : "Motoboy adicionado") : (ROTULO[h.chave] || h.chave);
      var d = new Date(h.ts * 1000);
      return '<div class="hs"><div class="hs-top"><span>' + d.toLocaleDateString("pt-BR") + " " + A.hora(d) + "</span><span>" + esc(h.username) + "</span></div>" +
        "<b>" + esc(titulo) + "</b><span>" + (de ? "<s>" + esc(de) + "</s> → " : "") + esc(para || "(vazio)") + "</span></div>";
    }).join("") + "</div>";
  }

  var TELAS = { loja: telaLoja, pix: telaPix, retirada: telaRetirada, motoboys: telaMotoboys, textos: telaTextos, copiar: telaCopiar, diag: telaDiag, hist: telaHist };

  function desenharTela() {
    var s = secao(st.tela);
    $("ajTitulo").textContent = s.t;
    $("ajCorpo").innerHTML = TELAS[st.tela]();
    $("ajRodape").hidden = !CAMPOS[st.tela];
    atualizarRodape();
  }
  function atualizarRodape() {
    if (!CAMPOS[st.tela]) return;
    var n = difs(st.tela).length, b = $("ajSalvar");
    b.disabled = !n;
    b.innerHTML = icon(st.tela === "pix" ? "shield" : "check") + (n ? "Salvar (" + n + ")" : "Nada para salvar");
  }
  function abrirTela(k) {
    st.tela = k;
    st.motoEdit = null;
    desarmarSaida();
    $("ajMenu").hidden = !!k;
    $("ajTela").hidden = !k;
    if (!k) { desenharMenu(); return; }
    if (k === "hist") carregarHist();
    desenharTela();
    $("ajCorpo").scrollTop = 0;
  }

  // Voltar com alteração não salva pede um segundo toque.
  function desarmarSaida() { clearTimeout(st.sairArmado); st.sairArmado = null; }
  function voltar() {
    var n = CAMPOS[st.tela] ? difs(st.tela).length : 0;
    if (n && !st.sairArmado) {
      A.aviso("Há alterações não salvas. Toque em voltar de novo para descartar.", true);
      st.sairArmado = setTimeout(desarmarSaida, 3500);
      return;
    }
    if (n) CAMPOS[st.tela].forEach(function (k) { st.rasc[k] = st.salvo[k]; });
    abrirTela(null);
  }

  // ================================================================ salvar
  function valoresMudados(sec) {
    var v = {};
    difs(sec).forEach(function (k) { v[k] = st.rasc[k] || ""; });
    return v;
  }
  function salvar() {
    var sec = st.tela;
    if (!difs(sec).length) return;
    if (sec === "pix") { abrirSenha(); return; }
    enviar({ valores: valoresMudados(sec) }).then(function () {
      A.aviso("Salvo. As atendentes veem na próxima atualização do painel.");
    }, function (e) { A.aviso(e.message, true); });
  }
  function enviar(corpo) {
    $("ajSalvar").disabled = true;
    return A.api("/api/atendimento/config", corpo).then(function (d) {
      st.hist = null;
      return A.recarregar().then(function () { return d; });
    }).finally(atualizarRodape);
  }

  function abrirSenha() {
    $("ajSenhaLista").innerHTML = difs("pix").map(function (k) {
      return '<div class="md-de"><span>' + esc(ROTULO[k]) + "</span><div>" + (st.salvo[k] ? "<s>" + esc(st.salvo[k]) + "</s> → " : "") +
        "<b>" + esc(st.rasc[k] || "(vazio)") + "</b></div></div>";
    }).join("");
    $("ajSenhaErro").hidden = true;
    $("ajSenhaCampo").value = "";
    $("ajSenha").hidden = false;
    $("ajSenhaCampo").focus();
  }
  function fecharSenha() { $("ajSenha").hidden = true; $("ajSenhaCampo").value = ""; }
  $("ajSenhaForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var senha = $("ajSenhaCampo").value;
    if (!senha) return;
    $("ajSenhaOk").disabled = true;
    enviar({ valores: valoresMudados("pix"), senha: senha }).then(function () {
      fecharSenha();
      desenharTela();
      A.aviso("Pix salvo. As atendentes veem na próxima atualização do painel.");
    }, function (err) {
      $("ajSenhaErro").textContent = err.message;
      $("ajSenhaErro").hidden = false;
      $("ajSenhaCampo").value = "";
      $("ajSenhaCampo").focus();
    }).finally(function () { $("ajSenhaOk").disabled = false; });
  });
  $("ajSenhaCancelar").addEventListener("click", fecharSenha);
  $("ajSenha").addEventListener("click", function (e) { if (e.target === this) fecharSenha(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !$("ajSenha").hidden) fecharSenha(); });

  // ================================================================ motoboys
  function motoboy(url, corpo, msg) {
    return A.api(url, corpo).then(function () {
      st.motoEdit = null;
      st.hist = null;
      return A.recarregar();
    }).then(function () {
      if (st.tela === "motoboys") desenharTela();
      A.aviso(msg);
    }, function (e) { A.aviso(e.message, true); });
  }

  // ================================================================ histórico
  function carregarHist() {
    if (st.hist) return;
    st.histErro = "";
    A.api("/api/atendimento/historico").then(function (d) {
      st.hist = d.itens;
      if (st.tela === "hist") desenharTela();
    }, function (e) {
      st.histErro = "Não consegui carregar o histórico (" + e.message + ").";
      if (st.tela === "hist") desenharTela();
    });
  }

  // ================================================================ copiar / frete
  // Esperam a pessoa parar de colar/digitar antes de perguntar ao servidor.
  var importTimer = null, freteTimer = null, importSeq = 0, freteSeq = 0;
  function previaImport() {
    var codigo = $("ajCodigo").value.trim(), out = $("ajImport"), seq = ++importSeq;
    if (!codigo) { out.innerHTML = ""; return; }
    A.api("/api/atendimento/importar", { codigo: codigo }).then(function (d) {
      if (seq !== importSeq) return;
      var partes = [];
      if (d.config.length) partes.push(d.config.map(function (k) { return ROTULO[k] || k; }).join(", "));
      if (d.motoboys_novos.length) partes.push("motoboys novos: " + d.motoboys_novos.join(", "));
      if (d.motoboys_atualizados.length) partes.push("motoboys atualizados: " + d.motoboys_atualizados.join(", "));
      out.innerHTML = partes.length
        ? '<div class="aj-lock">' + icon("check") + "<span>Vai mudar nesta loja: " + esc(partes.join("; ")) + ". <b>O Pix, o nome e o site desta loja não mudam.</b></span></div>" +
          '<button type="button" class="btn btn-pri" data-aplicar>' + icon("check") + "Aplicar nesta loja</button>"
        : '<div class="aj-dica">Esta loja já está igual ao código. Nada para mudar.</div>';
    }, function (e) {
      if (seq !== importSeq) return;
      out.innerHTML = '<div class="md-erro">' + esc(e.message) + "</div>";
    });
  }
  function testarFrete() {
    var texto = $("ajFreteTexto").value.trim(), out = $("ajFrete"), seq = ++freteSeq;
    if (!texto) { out.innerHTML = ""; return; }
    A.api("/api/atendimento/frete", { texto: texto }).then(function (d) {
      if (seq !== freteSeq) return;
      var onde = " <span>(" + d.lat.toFixed(5) + ", " + d.lng.toFixed(5) + ")</span>";
      out.innerHTML = !d.dentro_da_area ? '<div class="pd-zona erro">' + icon("x") + "Fora da área de entrega." + onde + "</div>"
        : d.preco == null ? '<div class="pd-zona erro">' + icon("x") + esc(d.zona) + ": frete a combinar." + onde + "</div>"
        : '<div class="pd-zona ok">' + icon("check") + esc(d.zona) + " · " + brl(d.preco) + onde + "</div>";
    }, function (e) {
      if (seq !== freteSeq) return;
      out.innerHTML = '<div class="pd-zona erro">' + icon("x") + esc(e.message) + "</div>";
    });
  }

  // ================================================================ eventos
  $("ajMenu").addEventListener("click", function (e) {
    var b = e.target.closest("[data-tela]");
    if (b) abrirTela(b.dataset.tela);
  });
  $("ajVoltar").addEventListener("click", voltar);
  $("ajSalvar").addEventListener("click", salvar);

  $("ajCorpo").addEventListener("input", function (e) {
    var el = e.target;
    if (el.dataset.k) {
      st.rasc[el.dataset.k] = el.value;
      // Só a prévia e o botão mudam enquanto digita (o cursor não pula).
      if ($("ajPrevPix")) $("ajPrevPix").innerHTML = previaPix();
      if ($("ajPrevTexto")) $("ajPrevTexto").innerHTML = previaTexto();
      if ($("ajPrevRet")) $("ajPrevRet").innerHTML = previaRetirada();
      atualizarRodape();
      return;
    }
    if (el.id === "ajCodigo") { clearTimeout(importTimer); importTimer = setTimeout(previaImport, 400); return; }
    if (el.id === "ajFreteTexto") { clearTimeout(freteTimer); freteTimer = setTimeout(testarFrete, 400); }
  });

  $("ajCorpo").addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) return;
    var d = b.dataset;
    if (d.tipo) { st.rasc.atd_pix_tipo = d.tipo; desenharTela(); return; }
    if (d.texto) { st.texto = d.texto; desenharTela(); return; }
    if (d.var) {
      var ta = $("ajTexto"), ini = ta.selectionStart, fim = ta.selectionEnd, v = "{" + d.var + "}";
      ta.value = ta.value.slice(0, ini) + v + ta.value.slice(fim);
      ta.focus();
      ta.setSelectionRange(ini + v.length, ini + v.length);
      ta.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    if (d.original !== undefined) {
      st.rasc["atd_tpl_" + st.texto] = cfg().ajustes.textos_padrao[st.texto];
      desenharTela();
      return;
    }
    if (d.meditar) { st.motoEdit = Number(d.meditar); desenharTela(); $("ajMotoNome").focus(); return; }
    if (d.mcancelar !== undefined) { st.motoEdit = null; desenharTela(); return; }
    if (d.msalvar) {
      motoboy("/api/atendimento/motoboy/" + d.msalvar, { nome: $("ajMotoNome").value, telefone: $("ajMotoTel").value }, "Motoboy salvo.");
      return;
    }
    if (d.mativo) {
      var on = d.v === "1";
      motoboy("/api/atendimento/motoboy/" + d.mativo, { ativo: on }, on ? "Motoboy de volta na lista das atendentes." : "Motoboy saiu da lista das atendentes.");
      return;
    }
    if (d.madd !== undefined) {
      var nome = $("ajNovoNome").value, tel = $("ajNovoTel").value;
      motoboy("/api/atendimento/motoboy", { nome: nome, telefone: tel }, "Motoboy adicionado: " + nome.trim() + ".");
      return;
    }
    if (d.exportar !== undefined) {
      A.api("/api/atendimento/exportar").then(function (r) {
        A.copiar(r.codigo, "código", function () {
          A.aviso("Código copiado. Cole no Ajustes da outra loja (Copiar para outra loja).");
        });
      }, function (err) { A.aviso(err.message, true); });
      return;
    }
    if (d.aplicar !== undefined) {
      b.disabled = true;
      A.api("/api/atendimento/importar", { codigo: $("ajCodigo").value.trim(), aplicar: true }).then(function () {
        st.hist = null;
        $("ajCodigo").value = "";
        $("ajImport").innerHTML = "";
        return A.recarregar();
      }).then(function () { A.aviso("Configuração aplicada nesta loja."); }, function (err) { b.disabled = false; A.aviso(err.message, true); });
    }
  });
})();

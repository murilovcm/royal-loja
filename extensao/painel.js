/* Casca da extensão do painel de atendimento.

   A extensão não tem tela própria de atendimento: ela só abre o /atendimento
   da loja escolhida num quadro, no painel lateral do Chrome. Qualquer deploy
   no servidor já chega a todos os PCs sem reinstalar nada.

   Cada perfil do Chrome (um por número de WhatsApp) fica preso a uma loja,
   guardada em chrome.storage.local. No primeiro uso a atendente escolhe;
   depois, trocar exige a senha do dono, conferida no servidor da loja atual,
   para ninguém mandar o Pix da loja errada. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var atual = null;      // loja deste perfil
  var escolhida = null;  // na tela de troca

  function lojaPorId(id) { return LOJAS.find(function (l) { return l.id === id; }) || null; }
  function dominio(l) { return l.url.replace(/^https?:\/\//, ""); }

  function mostrar(tela) {
    ["telaEscolha", "telaTroca", "telaPainel"].forEach(function (t) { $(t).hidden = t !== tela; });
  }

  function listaLojas(el, marcada, desligada) {
    el.innerHTML = "";
    LOJAS.forEach(function (l) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "loja";
      b.dataset.id = l.id;
      b.setAttribute("aria-pressed", String(marcada === l));
      b.disabled = desligada === l;
      var bola = document.createElement("i");
      bola.style.background = l.cor;
      var nome = document.createElement("b");
      nome.textContent = l.nome;
      var dom = document.createElement("span");
      dom.textContent = desligada === l ? "loja atual" : dominio(l);
      b.append(bola, nome, dom);
      el.appendChild(b);
    });
  }

  // ---------------------------------------------------------------- painel
  function abrirPainel(l) {
    atual = l;
    document.documentElement.style.setProperty("--loja", l.cor);
    document.documentElement.style.setProperty("--loja-texto", l.texto);
    $("faixaNome").textContent = l.nome;
    document.title = "Atendimento · " + l.nome;
    var destino = l.url + "/atendimento";
    if ($("quadro").getAttribute("src") !== destino) $("quadro").setAttribute("src", destino);
    mostrar("telaPainel");
  }

  // ---------------------------------------------------------------- primeiro uso
  function abrirEscolha() {
    listaLojas($("listaEscolha"), null, null);
    mostrar("telaEscolha");
  }
  $("listaEscolha").addEventListener("click", function (e) {
    var b = e.target.closest(".loja");
    if (!b) return;
    var l = lojaPorId(b.dataset.id);
    chrome.storage.local.set({ loja: l.id }, function () { abrirPainel(l); });
  });

  // ---------------------------------------------------------------- troca (com senha)
  function abrirTroca() {
    escolhida = null;
    $("trocaAtual").textContent = atual.nome;
    listaLojas($("listaTroca"), null, atual);
    $("senha").value = "";
    erro("");
    mostrar("telaTroca");
  }
  function erro(msg) { $("erroTroca").textContent = msg; $("erroTroca").hidden = !msg; }

  $("btnTroca").addEventListener("click", abrirTroca);
  $("btnCancelar").addEventListener("click", function () { abrirPainel(atual); });
  $("listaTroca").addEventListener("click", function (e) {
    var b = e.target.closest(".loja");
    if (!b || b.disabled) return;
    escolhida = lojaPorId(b.dataset.id);
    listaLojas($("listaTroca"), escolhida, atual);
    $("senha").focus();
  });

  // A senha é conferida no servidor da loja ATUAL (a que está saindo). Se ele
  // não responder, confere no da loja nova, para o dono não ficar travado.
  function conferir(loja, senha) {
    return fetch(loja.url + "/api/atendimento/confere-dono", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ senha: senha }),
      credentials: "omit"
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (r.ok && d.ok) return true;
        // Só 403 (senha errada) e 429 (bloqueio) são resposta de verdade. Um
        // 404/500 (loja fora do ar ou sem esta versão) conta como falha de
        // conexão: tenta a outra loja em vez de dizer "senha incorreta".
        if (r.status === 403 || r.status === 429) {
          throw Object.assign(new Error(d.error || "Senha incorreta."), { resposta: true });
        }
        throw new Error("loja respondeu " + r.status);
      });
    });
  }
  $("formTroca").addEventListener("submit", function (e) {
    e.preventDefault();
    var senha = $("senha").value;
    if (!escolhida) { erro("Escolha a nova loja."); return; }
    if (!senha) { erro("Digite a senha do dono."); $("senha").focus(); return; }
    $("btnTrocar").disabled = true;
    erro("");
    conferir(atual, senha).catch(function (err) {
      if (err.resposta) throw err;
      return conferir(escolhida, senha);
    }).then(function () {
      chrome.storage.local.set({ loja: escolhida.id }, function () { abrirPainel(escolhida); });
    }, function (err) {
      erro(err.resposta ? err.message : "Não consegui falar com a loja. Confira a internet e tente de novo.");
      $("senha").value = "";
      $("senha").focus();
    }).finally(function () { $("btnTrocar").disabled = false; });
  });

  // ---------------------------------------------------------------- início
  chrome.storage.local.get("loja", function (d) {
    var l = lojaPorId(d && d.loja);
    if (l) abrirPainel(l); else abrirEscolha();
  });
})();

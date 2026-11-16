# Extensão do Painel de Atendimento

Abre o painel de atendimento (`/atendimento`) da loja no painel lateral do
Chrome, ao lado do WhatsApp Web. Uma extensão só para as três lojas.

A extensão não tem tela própria: ela mostra a página do servidor. Um deploy no
EasyPanel já atualiza todos os PCs sem reinstalar nada. Só é preciso
reinstalar se algum arquivo **desta pasta** mudar.

## Instalar (em cada perfil do Chrome, um por número de WhatsApp)

1. Copie a pasta `extensao` para o PC (ex.: `C:\painel-atendimento`).
2. No Chrome, abra `chrome://extensions`.
3. Ligue **Modo do desenvolvedor** (canto superior direito).
4. Clique em **Carregar sem compactação** e escolha a pasta.
5. Fixe o ícone (quebra-cabeça → alfinete) e clique nele: o painel abre ao lado.
6. Escolha a loja daquele perfil e entre com a conta da atendente.

O ID da extensão é sempre `iffmpahjhfdbbmfipmpepnjpmenldkfk` (vem da `key` do
`manifest.json`). O servidor só deixa o painel abrir dentro desta extensão; se o
ID mudar, o painel aparece em branco. Para trocar o ID, mude também a variável
`ATD_EXTENSAO_ID` no servidor.

## Um pedido por conversa

O `whatsapp.js` lê **só o nome no topo da conversa aberta** no WhatsApp Web
(nunca as mensagens; não clica, não digita, não envia). Ao trocar de conversa,
o painel guarda o pedido que estava aberto e abre o daquela conversa, com o
nome do cliente já preenchido. Voltar para uma conversa reabre o pedido dela.
Se o WhatsApp mudar a tela e o nome não for achado, o painel só deixa de
preencher sozinho.

## Atualizar a extensão

Quando algum arquivo **desta pasta** mudar: em `chrome://extensions`, clique na
seta de recarregar da extensão e depois recarregue a aba do WhatsApp Web (F5).

## Trocar a loja de um perfil

Botão de troca na faixa colorida → escolha a loja → **senha do dono**. A senha
é conferida no servidor da loja atual (5 erros bloqueiam por 5 minutos, igual
ao login).

## Arquivos

- `manifest.json` — permissões: painel lateral, guardar a loja do perfil e
  acesso só aos três domínios das lojas.
- `lojas.js` — nome, endereço e cor de cada loja. Mudou um domínio? Troque
  aqui **e** em `host_permissions` no `manifest.json`.
- `painel.html`, `painel.css`, `painel.js` — a faixa da loja, a escolha no
  primeiro uso e a troca com senha.
- `background.js` — o clique no ícone abre o painel lateral.
- `whatsapp.js` — lê o nome da conversa aberta e avisa o painel.

// As três lojas. Cada uma tem o próprio servidor e banco; a extensão só abre
// o painel (/atendimento) da loja escolhida para este perfil do Chrome.
// Mudou um domínio? Troque aqui E em "host_permissions" no manifest.json.
var LOJAS = [
  { id: "royal", nome: "Royal", url: "https://royalpodsslz.com", cor: "#f5b400", texto: "#1a1300" },
  { id: "vapor", nome: "Vapor", url: "https://vaporstoreslz.com", cor: "#3b82f6", texto: "#ffffff" },
  { id: "podsilha", nome: "Pods Ilha", url: "https://podsaoluis.com", cor: "#10b981", texto: "#03140d" }
];

# 🚀 Guia de Deploy — Royal na sua VPS (Ubuntu)

Este guia coloca a loja no ar no seu domínio, com HTTPS.
Faça uma FASE de cada vez. Se travar, copie a mensagem de erro.

Substitua nos comandos:
- `SEU_USUARIO_GIT/royal` → seu repositório no GitHub
- `seudominio.com.br` → seu domínio real
- `seu@email.com` → seu e-mail (para o certificado HTTPS)

---

## FASE 1 — Apontar o domínio (no painel do domínio)

Crie dois registros DNS do tipo A apontando para o IP da sua VPS:

| Tipo | Nome | Valor          |
|------|------|----------------|
| A    | @    | IP_DA_SUA_VPS  |
| A    | www  | IP_DA_SUA_VPS  |

Aguarde a propagação (minutos a algumas horas).
Teste com:  `ping seudominio.com.br`  (deve responder o IP da VPS).

---

## FASE 2 — Preparar a VPS (via SSH)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv nginx git -y
```

---

## FASE 3 — Baixar o código e configurar o ambiente

```bash
# Cria a pasta e baixa o projeto do GitHub
sudo mkdir -p /var/www
sudo chown -R $USER:$USER /var/www
cd /var/www
git clone https://github.com/SEU_USUARIO_GIT/royal.git
cd royal

# Cria ambiente virtual e instala dependências
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Testa rapidamente (Ctrl+C para parar depois de ver "Running")
gunicorn --bind 0.0.0.0:5000 app:app
```

Se aparecer "Listening at ...", está funcionando. Aperte `Ctrl+C`.

```bash
# Ajusta permissões para o Nginx conseguir ler os arquivos
deactivate
sudo chown -R www-data:www-data /var/www/royal
```

---

## FASE 4 — Rodar como serviço (liga sozinho, reinicia sozinho)

```bash
# Copia o arquivo de serviço já pronto
sudo cp /var/www/royal/deploy/royal.service /etc/systemd/system/royal.service

# Liga o serviço
sudo systemctl daemon-reload
sudo systemctl start royal
sudo systemctl enable royal

# Confere se está ativo (deve aparecer "active (running)")
sudo systemctl status royal
```

---

## FASE 5 — Configurar o Nginx (o "porteiro" do site)

```bash
# Copia a config
sudo cp /var/www/royal/deploy/nginx-royal.conf /etc/nginx/sites-available/royal

# IMPORTANTE: edite e troque "seudominio.com.br" pelo seu domínio
sudo nano /etc/nginx/sites-available/royal
#   (troque nas duas linhas server_name, salve com Ctrl+O Enter, saia com Ctrl+X)

# Ativa o site
sudo ln -s /etc/nginx/sites-available/royal /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default   # remove a página padrão do Nginx

# Testa e reinicia
sudo nginx -t
sudo systemctl restart nginx
```

Agora abra `http://seudominio.com.br` no navegador. A loja deve aparecer! 🎉

---

## FASE 6 — HTTPS grátis (cadeado de segurança)

Sem isso o navegador mostra "site não seguro". É grátis e automático:

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d seudominio.com.br -d www.seudominio.com.br
```

Responda o e-mail quando pedir e escolha "redirect" (opção 2) para forçar HTTPS.
O certificado renova sozinho.

Pronto: `https://seudominio.com.br` no ar com cadeado. 🔒

---

## COMO ATUALIZAR O SITE DEPOIS

Quando você mudar algo e subir pro GitHub, na VPS basta:

```bash
cd /var/www/royal
git pull
sudo chown -R www-data:www-data /var/www/royal
sudo systemctl restart royal
```

---

## ⚠️ IMPORTANTE — Senha do /admin na VPS

O painel já está protegido por senha. Para definir a senha na VPS
SEM deixá-la no código, edite o arquivo de serviço e adicione as
variáveis de ambiente. Rode:

```bash
sudo nano /etc/systemd/system/royal.service
```

Na seção [Service], adicione estas duas linhas (troque pelos seus valores):

```
Environment="ADMIN_PASSWORD=suaSenhaForteAqui"
Environment="SECRET_KEY=um-texto-longo-e-aleatorio-qualquer"
```

Salve (Ctrl+O, Enter, Ctrl+X) e recarregue:

```bash
sudo systemctl daemon-reload
sudo systemctl restart royal
```

DICA: use uma senha forte (12+ caracteres, com letras, números e símbolos).
A senha de teste "386121" é fraca — troque antes de divulgar a loja.
Para gerar uma SECRET_KEY aleatória, rode:  `openssl rand -hex 32`

## Comandos úteis para problemas

```bash
sudo systemctl status royal      # ver se a loja está rodando
sudo journalctl -u royal -n 50   # ver os últimos erros da loja
sudo nginx -t                    # testar config do Nginx
sudo systemctl restart royal     # reiniciar a loja
```

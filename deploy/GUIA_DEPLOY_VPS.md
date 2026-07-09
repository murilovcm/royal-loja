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

⚠️ Esta fase não é só estética — sem HTTPS, o cookie de login do painel
`/admin` pode trafegar sem criptografia e ser interceptado na rede. Faça
esta fase ANTES de divulgar a loja, não deixe para depois.

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d seudominio.com.br -d www.seudominio.com.br --redirect --hsts
```

As flags `--redirect` e `--hsts` já forçam o HTTP a virar HTTPS automaticamente
(sem precisar escolher nada na hora) e ligam o header HSTS, que impede o
navegador de tentar HTTP de novo depois da primeira visita. Responda o
e-mail quando pedir. O certificado renova sozinho.

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

## ⚠️ IMPORTANTE — Conta do dono e chave de sessão na VPS

O arquivo `deploy/royal.service` já vem com três linhas de placeholder que
você PRECISA trocar antes de ligar o serviço pela primeira vez. Se você já
copiou o arquivo (Fase 4), edite a cópia instalada:

```bash
sudo nano /etc/systemd/system/royal.service
```

Troque os valores destas três linhas (já estão lá, só falta preencher):

```
Environment="ADMIN_USERNAME=TROQUE_ESTE_USUARIO"
Environment="ADMIN_PASSWORD=TROQUE_ESTA_SENHA"
Environment="SECRET_KEY=TROQUE_ESTA_CHAVE"
```

Salve (Ctrl+O, Enter, Ctrl+X) e recarregue:

```bash
sudo systemctl daemon-reload
sudo systemctl restart royal
```

DICA: use uma senha forte (12+ caracteres, com letras, números e símbolos).
Para gerar uma SECRET_KEY aleatória, rode:  `openssl rand -hex 32`

**Como isso funciona:** `ADMIN_USERNAME`/`ADMIN_PASSWORD` só são lidos na
primeiríssima vez que a loja liga (quando ainda não existe nenhuma conta no
banco) — nesse momento, eles criam a conta "dono" com acesso completo. A
partir daí a senha real já está guardada (com hash) dentro do `royal.db`, e
essas duas variáveis não têm mais nenhum efeito — trocar a senha do dono
depois disso é feito pelo próprio painel (aba Funcionários não se aplica ao
dono; por enquanto, trocar a senha do dono exige acesso direto ao banco ou
recriar o `royal.db`). Já `SECRET_KEY` é usada em toda requisição para
assinar o cookie de login, então sempre importa — nunca deixe no padrão.

Depois que a loja estiver no ar, entre em `/admin` com o usuário e senha
que você definiu, abra a aba **👥 Funcionários** e crie um login para cada
pessoa da sua equipe. Por padrão, cada funcionário criado já pode mexer no
Catálogo e em Cupons — você pode desligar qualquer um desses poderes a
qualquer momento na mesma aba. Identidade Visual e Frete nunca aparecem
liberados para funcionários, é reservado só para a conta do dono.

Se você esquecer de trocar, o serviço aparece nos logs
(`sudo journalctl -u royal -n 50`) com um aviso enorme "ATENCAO: ADMIN_PASSWORD
e/ou SECRET_KEY nao foram definidos" — é o app avisando que ainda está com os
valores padrão.

---

## FASE 7 — Backup automático (recomendado fortemente)

O painel admin consegue apagar marcas inteiras (e todos os modelos/sabores
dela junto) e alterar qualquer configuração do site. Sem backup, um clique
errado, uma senha vazada ou uma sessão roubada não têm volta. Configure isto
antes de divulgar a loja:

```bash
# Cria a pasta onde os backups ficam guardados
sudo mkdir -p /var/backups/royal

# Copia os arquivos de timer/serviço já prontos
sudo cp /var/www/royal/deploy/royal-backup.service /etc/systemd/system/
sudo cp /var/www/royal/deploy/royal-backup.timer /etc/systemd/system/

# Liga o timer (roda todo dia às 03:30)
sudo systemctl daemon-reload
sudo systemctl enable --now royal-backup.timer

# Testa rodando um backup na hora, para conferir que funciona
sudo systemctl start royal-backup.service
ls -la /var/backups/royal
```

Cada execução cria uma pasta com data/hora dentro de `/var/backups/royal`
contendo `royal.db` e `uploads.tar.gz`. Backups com mais de 14 dias são
apagados automaticamente. **Recomendado:** de tempos em tempos, copie
`/var/backups/royal` para fora da VPS (outro servidor, um bucket S3, o seu
computador via `scp`) — um backup que mora no mesmo disco da loja não te
protege se a VPS inteira for perdida.

### Como restaurar um backup

```bash
sudo systemctl stop royal
sudo cp /var/backups/royal/<DATA-ESCOLHIDA>/royal.db /var/www/royal/royal.db
sudo tar -xzf /var/backups/royal/<DATA-ESCOLHIDA>/uploads.tar.gz -C /var/www/royal
sudo chown -R www-data:www-data /var/www/royal
sudo systemctl start royal
```

---

## Se você suspeitar de um ataque ao painel admin

Sinais de alerta: produtos/preços/cupons alterados sem você ter feito,
marcas/modelos que sumiram, um logo ou cor estranha aplicada, ou você não
consegue mais entrar com sua senha de sempre.

1. **Troque a senha e a chave imediatamente** — edite
   `/etc/systemd/system/royal.service` (mesmo passo da seção acima), coloque
   valores novos em `ADMIN_PASSWORD` e `SECRET_KEY`, e reinicie
   (`sudo systemctl daemon-reload && sudo systemctl restart royal`). Isso
   invalida IMEDIATAMENTE qualquer sessão de admin já aberta — inclusive a de
   quem invadiu — porque o cookie de sessão é assinado com a chave antiga.
2. **Restaure o banco a partir do último backup limpo** (ver "Como
   restaurar um backup" acima) se algo foi apagado ou alterado
   indevidamente.
3. **Confira a pasta de uploads** (`/var/www/royal/uploads`) por arquivos
   que você não reconhece, principalmente `.svg` — apague qualquer um que
   não tenha sido enviado por você.
4. **Veja o registro de ações do painel** — toda ação administrativa
   (login, logout, tentativas de senha erradas, criação/edição/exclusão de
   dados) fica gravada na tabela `audit_log` dentro do `royal.db`. Para
   consultar:
   ```bash
   sqlite3 /var/www/royal/royal.db \
     "SELECT datetime(ts,'unixepoch','localtime'), ip, action, detail FROM audit_log ORDER BY id DESC LIMIT 100;"
   ```
   Isso mostra quem (por IP) fez o quê e quando — use para descobrir a
   janela de tempo do ataque e decidir de qual backup restaurar.

## Comandos úteis para problemas

```bash
sudo systemctl status royal      # ver se a loja está rodando
sudo journalctl -u royal -n 50   # ver os últimos erros da loja
sudo nginx -t                    # testar config do Nginx
sudo systemctl restart royal     # reiniciar a loja
```

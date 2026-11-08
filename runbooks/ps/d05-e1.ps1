# d05-e1.ps1 — testes de fora com a chave (notebook ou máquina virtual)
# Gerado de runbooks/acesso-aplicacoes-d05.md (D-05). Rode como arquivo, sem colar no terminal:
#   pwsh -ExecutionPolicy Bypass -File C:\www\vllm-master\runbooks\ps\d05-e1.ps1
# (Windows PowerShell 5.1 também serve: powershell -ExecutionPolicy Bypass -File ...)
# Colar blocos longos corrompeu o texto três vezes em 2026-11-07 (§9 do estudo).

$u = Read-Host "Usuário com que você entra no sabdiia01"
$d = "$env:USERPROFILE\.vllm-estudo"; New-Item -ItemType Directory -Force $d | Out-Null
$k = Read-Host "Consumidor desta máquina (wsantos ou estacao)"
if ($k -notin @("wsantos", "estacao")) { "ABORTA: consumidor inválido: $k"; return }
$S = "${u}@192.168.50.151:/home/utec/vllm-estudo"
scp "$S/d05-chave-$k.env" "$S/d05-chave-dev-1.env" "$d\"
if (-not (Test-Path "$d\d05-chave-$k.env")) { "ABORTA: chave de $k não copiada"; return }
$c = Get-Content "$d\d05-chave-$k.env" -Raw | ConvertFrom-StringData
$ip = $c.KONG_IP; $URL = "$($c.BASE_URL)/chat/completions"
[IO.File]::WriteAllText("$d\h-ambas.txt", "apikey: $($c.CHAVE_KONG)`nAuthorization: Bearer $($c.CHAVE_VLLM)`n")
[IO.File]::WriteAllText("$d\h-kong.txt", "apikey: $($c.CHAVE_KONG)`n")
[IO.File]::WriteAllText("$d\h-vllm.txt", "Authorization: Bearer $($c.CHAVE_VLLM)`n")
if (Test-Path "$d\d05-chave-dev-1.env") {
  $p = Get-Content "$d\d05-chave-dev-1.env" -Raw | ConvertFrom-StringData
  [IO.File]::WriteAllText("$d\h-pendente.txt", "apikey: $($p.CHAVE_KONG)`nAuthorization: Bearer $($p.CHAVE_VLLM)`n")
}
[IO.File]::WriteAllText("$d\corpo.json", '{"model":"mistralai/Mistral-Nemo-Instruct-2407","messages":[{"role":"user","content":"Qual é a capital do Brasil? Responda com uma palavra."}],"max_tokens":10,"temperature":0}')
[IO.File]::WriteAllText("$d\corpo-sse.json", '{"model":"mistralai/Mistral-Nemo-Instruct-2407","messages":[{"role":"user","content":"Explique em cinco frases o que é inflação."}],"max_tokens":200,"temperature":0,"stream":true}')
[IO.File]::WriteAllText("$d\vazio.json", '{}')
$r = "C:\www\vllm-master"
$dir = if (Test-Path "$r\logs-analysis") { "$r\logs-analysis" } else { [Environment]::GetFolderPath('Desktop') }
$log = Join-Path $dir "d05-e1-estacao-$($env:COMPUTERNAME.ToLower())-$(Get-Date -Format yyyy-MM-dd-HHmm).log"
& {
  "== $env:COMPUTERNAME  $(Get-Date -Format o)  D-05 E1: testes de fora, Kong em $ip, consumidor $($c.CONSUMIDOR)"
  function k($nome, [string[]]$a) {
    Remove-Item "$d\resp.txt" -ErrorAction SilentlyContinue
    $r = & curl.exe -sk -m 60 -o "$d\resp.txt" -w "HTTP %{http_code}" @a
    $b = "$(Get-Content "$d\resp.txt" -Raw -ErrorAction SilentlyContinue)" -replace '\s+', ' '
    "{0,-48} -> {1} | {2}" -f $nome, $r, $b.Substring(0, [Math]::Min(170, $b.Length))
  }
  $J = @("-H", "Content-Type: application/json")
  "### 1. chaves"
  k "sem chave (401 do Kong)"            (@("-X", "POST") + $J + @("--data-binary", "@$d\corpo.json", $URL))
  k "só a chave do Kong (401 do vLLM)"   (@("-X", "POST", "-H", "@$d\h-kong.txt") + $J + @("--data-binary", "@$d\corpo.json", $URL))
  k "só a chave do vLLM (401 do Kong)"   (@("-X", "POST", "-H", "@$d\h-vllm.txt") + $J + @("--data-binary", "@$d\corpo.json", $URL))
  k "as duas (200, Brasília)"            (@("-X", "POST", "-H", "@$d\h-ambas.txt") + $J + @("--data-binary", "@$d\corpo.json", $URL))
  if (Test-Path "$d\h-pendente.txt") {
    k "chave de dev-1, IP fora da lista (403)" (@("-X", "POST", "-H", "@$d\h-pendente.txt") + $J + @("--data-binary", "@$d\corpo.json", $URL))
  } else { "chave de dev-1 não copiada: teste de IP fora da lista pulado" }
  "### 2. streaming (SSE): o primeiro byte chega antes do fim?"
  $t = & curl.exe -sk -N -m 120 -o "$d\sse.txt" -w "primeiro byte %{time_starttransfer} s, total %{time_total} s, HTTP %{http_code}" -X POST -H "@$d\h-ambas.txt" -H "Content-Type: application/json" --data-binary "@$d\corpo-sse.json" $URL
  $t
  $l = Get-Content "$d\sse.txt" | Where-Object { $_ -like 'data:*' }
  "linhas 'data:': $($l.Count); primeira e últimas:"
  @($l | Select-Object -First 1) + @($l | Select-Object -Last 2) | ForEach-Object { $_.Substring(0, [Math]::Min(200, $_.Length)) }
  "### 3. caminhos e métodos fora da rota (404 do Kong)"
  k "GET na rota"                        (@("-H", "@$d\h-ambas.txt", $URL))
  k "/vllm/v1/models"              (@("-H", "@$d\h-ambas.txt", "https://$ip/vllm/v1/models"))
  k "/vllm/metrics"                (@("-H", "@$d\h-ambas.txt", "https://$ip/vllm/metrics"))
  k "POST /invocations"                  (@("-X", "POST", "-H", "@$d\h-ambas.txt") + $J + @("--data-binary", "@$d\corpo.json", "https://$ip/invocations"))
  "### 4. HTTP sem TLS (não pode dar 200)"
  k "http://, as duas chaves"            (@("-X", "POST", "-H", "@$d\h-ambas.txt") + $J + @("--data-binary", "@$d\corpo.json", "http://$ip/vllm/v1/chat/completions"))
  "### 5. certificado apresentado pelo Kong"
  try {
    $tcp = [Net.Sockets.TcpClient]::new($ip, 443)
    $ssl = [Net.Security.SslStream]::new($tcp.GetStream(), $false, { $true })
    $ssl.AuthenticateAsClient($ip)
    $x = [Security.Cryptography.X509Certificates.X509Certificate2]$ssl.RemoteCertificate
    "sujeito: $($x.Subject) | emissor: $($x.Issuer) | válido até: $($x.NotAfter) | autoassinado: $($x.Subject -eq $x.Issuer)"
    $ssl.Dispose(); $tcp.Dispose()
  } catch { "falhou: $($_.Exception.Message)" }
  "### 6. limite: 125 requisições inválidas em seguida (o vLLM recusa '{}' com 400, sem usar a GPU)"
  $cods = 1..125 | ForEach-Object { & curl.exe -sk -m 10 -o NUL -w "%{http_code}" -X POST -H "@$d\h-ambas.txt" -H "Content-Type: application/json" --data-binary "@$d\vazio.json" $URL }
  $cods | Group-Object | Sort-Object Name | ForEach-Object { "HTTP $($_.Name): $($_.Count)" }
  "== fim $(Get-Date -Format o)"
} *>&1 | Tee-Object -FilePath $log
Remove-Item "$d\d05-chave-$k.env", "$d\d05-chave-dev-1.env", "$d\h-*.txt", "$d\*.json", "$d\resp.txt", "$d\sse.txt" -ErrorAction SilentlyContinue
"chaves e arquivos de teste apagados de $d; log em $log"

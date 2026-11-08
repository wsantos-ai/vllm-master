# d05-d2.ps1 — teste do ator com o arquivo de chave recebido (máquina de cada ator)
# Gerado de runbooks/acesso-aplicacoes-d05.md (D-05). Rode como arquivo, sem colar no terminal:
#   pwsh -ExecutionPolicy Bypass -File .\d05-d2.ps1
# (Windows PowerShell 5.1 também serve: powershell -ExecutionPolicy Bypass -File ...)
# Colar blocos longos corrompeu o texto três vezes em 2026-11-07 (§9 do estudo).

$arq = Read-Host "Caminho completo do arquivo .env de chave recebido"
if (-not (Test-Path $arq)) { "ABORTA: arquivo não encontrado: $arq"; return }
$c = Get-Content $arq -Raw | ConvertFrom-StringData
$URL = "$($c.BASE_URL)/chat/completions"
$h = Join-Path $env:TEMP "d05-h.txt"; $b = Join-Path $env:TEMP "d05-b.json"; $s = Join-Path $env:TEMP "d05-s.json"; $r = Join-Path $env:TEMP "d05-r.txt"
[IO.File]::WriteAllText($h, "apikey: $($c.CHAVE_KONG)`nAuthorization: Bearer $($c.CHAVE_VLLM)`n")
[IO.File]::WriteAllText($b, "{`"model`":`"$($c.MODELO)`",`"messages`":[{`"role`":`"user`",`"content`":`"Qual é a capital do Brasil? Responda com uma palavra.`"}],`"max_tokens`":10,`"temperature`":0}")
[IO.File]::WriteAllText($s, "{`"model`":`"$($c.MODELO)`",`"messages`":[{`"role`":`"user`",`"content`":`"Explique em cinco frases o que é inflação.`"}],`"max_tokens`":200,`"temperature`":0,`"stream`":true}")
$log = Join-Path ([Environment]::GetFolderPath('Desktop')) "d05-d2-$($c.CONSUMIDOR)-$($env:COMPUTERNAME.ToLower())-$(Get-Date -Format yyyy-MM-dd-HHmm).log"
& {
  "== $env:COMPUTERNAME  $(Get-Date -Format o)  D-05 D2: consumidor $($c.CONSUMIDOR), Kong $($c.KONG_IP)"
  $t = Test-NetConnection $c.KONG_IP -Port 443 -WarningAction SilentlyContinue
  "443: origem $($t.SourceAddress.IPAddress)  alcançou=$($t.TcpTestSucceeded)"
  "### 1. uma pergunta (200 e Brasília; 403 = IP de saída fora da lista; 401 = chave)"
  Remove-Item $r -ErrorAction SilentlyContinue
  $code = & curl.exe -sk -m 60 -o $r -w "HTTP %{http_code}" -X POST -H "@$h" -H "Content-Type: application/json" --data-binary "@$b" $URL
  "$code | $((Get-Content $r -Raw -ErrorAction SilentlyContinue) -replace '\s+', ' ')"
  "### 2. streaming: primeiro byte antes do fim?"
  & curl.exe -sk -N -m 120 -o $r -w "primeiro byte %{time_starttransfer} s, total %{time_total} s, HTTP %{http_code}" -X POST -H "@$h" -H "Content-Type: application/json" --data-binary "@$s" $URL
  ""
  "linhas 'data:': $((Get-Content $r | Where-Object { $_ -like 'data:*' }).Count)"
  "== fim $(Get-Date -Format o)"
} *>&1 | Tee-Object -FilePath $log
Remove-Item $h, $b, $s, $r -ErrorAction SilentlyContinue
"log em ${log}: envie a quem coordena os testes (o log não contém as chaves)"

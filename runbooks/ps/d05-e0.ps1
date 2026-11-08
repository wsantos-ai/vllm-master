# d05-e0.ps1 — rede até o Kong (notebook ou máquina virtual)
# Gerado de runbooks/acesso-aplicacoes-d05.md (D-05). Rode como arquivo, sem colar no terminal:
#   pwsh -ExecutionPolicy Bypass -File C:\www\vllm-master\runbooks\ps\d05-e0.ps1
# (Windows PowerShell 5.1 também serve: powershell -ExecutionPolicy Bypass -File ...)
# Colar blocos longos corrompeu o texto três vezes em 2026-11-07 (§9 do estudo).

$ip = Read-Host "IP do proxy do Kong (seção 2 do K0)"
if ($ip -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { "ABORTA: IP inválido: $ip"; return }
$r = "C:\www\vllm-master"
$dir = if (Test-Path "$r\logs-analysis") { "$r\logs-analysis" } else { [Environment]::GetFolderPath('Desktop') }
$log = Join-Path $dir "d05-e0-rede-$($env:COMPUTERNAME.ToLower())-$(Get-Date -Format yyyy-MM-dd-HHmm).log"
& {
  "== $env:COMPUTERNAME  $(Get-Date -Format o)  D-05 E0: esta máquina alcança o Kong em ${ip}?"
  "### 1. IPv4 desta máquina (172.16.30.6 na máquina virtual; 172.16.254.x na VPN do notebook)"
  Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object IPAddress, PrefixLength, InterfaceAlias, PrefixOrigin | Format-Table | Out-String
  "### 2. portas do Kong e, como controle, o ssh de 01"
  foreach ($d in @(@($ip, 443), @($ip, 80), @('192.168.50.151', 22))) {
    $t = Test-NetConnection $d[0] -Port $d[1] -WarningAction SilentlyContinue
    "{0}:{1}  origem {2}  alcançou={3}" -f $d[0], $d[1], $t.SourceAddress.IPAddress, $t.TcpTestSucceeded
  }
  "### 3. caminho até o Kong"
  tracert -d -h 8 -w 500 $ip
  "### 4. o Kong responde HTTPS? (sem rota ainda: 404 é resposta)"
  curl.exe -sk -m 10 -o NUL -w "https://$ip/vllm/v1/chat/completions  HTTP %{http_code}`n" "https://$ip/vllm/v1/chat/completions"
  "== fim $(Get-Date -Format o)"
} *>&1 | Tee-Object -FilePath $log

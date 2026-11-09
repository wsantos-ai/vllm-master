# d05-d1.ps1 — rede do ator até o Kong, sem chave (máquina de cada ator)
# Gerado de runbooks/acesso-aplicacoes-d05.md (D-05). Rode como arquivo, sem colar no terminal:
#   pwsh -ExecutionPolicy Bypass -File .\d05-d1.ps1
# (Windows PowerShell 5.1 também serve: powershell -ExecutionPolicy Bypass -File ...)
# Colar blocos longos corrompeu o texto três vezes em 2026-11-07 (§9 do estudo).

$padrao = "192.168.50.161"  # IP do Kong (proxy, MetalLB); não é o gateway da rede
$ip = Read-Host "IP do Kong [Enter = $padrao]"
if ([string]::IsNullOrWhiteSpace($ip)) { $ip = $padrao }
$ip = $ip.Trim()
if ($ip -ne $padrao) { "AVISO: $ip não é o IP do Kong conhecido ($padrao). Confira com quem coordena os testes." }
if ($ip -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { "ABORTA: IP inválido: $ip"; return }
$log = Join-Path ([Environment]::GetFolderPath('Desktop')) "d05-d1-rede-$($env:COMPUTERNAME.ToLower())-$(Get-Date -Format yyyy-MM-dd-HHmm).log"
& {
  "== $env:COMPUTERNAME  $(Get-Date -Format o)  D-05 D1: rede do ator até o Kong $ip"
  "### 1. IPv4 desta máquina (DHCP ou fixo)"
  Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -ne '127.0.0.1' } | Select-Object IPAddress, PrefixLength, InterfaceAlias, PrefixOrigin | Format-Table | Out-String
  "### 2. alcança a porta 443 do Kong? com que IP de origem?"
  $t = Test-NetConnection $ip -Port 443 -WarningAction SilentlyContinue
  "{0}:443  origem {1}  alcançou={2}" -f $ip, $t.SourceAddress.IPAddress, $t.TcpTestSucceeded
  "### 3. caminho"
  tracert -d -h 8 -w 500 $ip
  "== fim $(Get-Date -Format o)"
} *>&1 | Tee-Object -FilePath $log
"log em ${log}: envie a quem coordena os testes"

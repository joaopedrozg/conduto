<#
.SYNOPSIS
    Baixa e instala o Microsoft ODBC Driver for SQL Server no Windows.

.DESCRIPTION
    Automatiza o download (e instalacao) do ODBC Driver for SQL Server.
    Preferencias de instalacao:
      1. winget (quando disponivel)
      2. Download direto do MSI oficial + instalacao silenciosa via msiexec

    Use -DownloadOnly para apenas baixar o instalador (ex.: instalacao offline).

.PARAMETER Version
    Versao do driver: 18 (padrao) ou 17.

.PARAMETER DownloadOnly
    Apenas baixa o MSI, sem instalar.

.PARAMETER OutFile
    Caminho de saida do MSI baixado. Padrao: msodbcsql<versao>.msi no diretorio atual
    (ou %TEMP% quando instalando).

.PARAMETER Force
    Baixa/instala mesmo se o driver ja estiver presente.

.PARAMETER NoWinget
    Ignora o winget e usa o download direto do MSI.

.EXAMPLE
    .\scripts\install-sqlserver-odbc.ps1
    Baixa (se preciso) e instala o ODBC Driver 18 for SQL Server.

.EXAMPLE
    .\scripts\install-sqlserver-odbc.ps1 -Version 17 -DownloadOnly -OutFile .\msodbcsql17.msi
    Apenas baixa o instalador da versao 17.

.LINK
    https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server
#>
[CmdletBinding()]
param(
    [ValidateSet("17", "18")]
    [string]$Version = "18",
    [switch]$DownloadOnly,
    [string]$OutFile = "",
    [switch]$Force,
    [switch]$NoWinget
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$links = @{
    "17" = "https://go.microsoft.com/fwlink/?linkid=2361646"
    "18" = "https://go.microsoft.com/fwlink/?linkid=2249006"
}
$wingetIds = @{
    "17" = "Microsoft.msodbcsql.17"
    "18" = "Microsoft.msodbcsql.18"
}
$driverNames = @{
    "17" = "ODBC Driver 17 for SQL Server"
    "18" = "ODBC Driver 18 for SQL Server"
}

function Test-OdbcDriverInstalado {
    param([Parameter(Mandatory)][string]$Nome)
    $chaves = @(
        "HKLM:\SOFTWARE\ODBC\ODBCINST.INI\ODBC Drivers",
        "HKLM:\SOFTWARE\WOW6432Node\ODBC\ODBCINST.INI\ODBC Drivers"
    )
    foreach ($chave in $chaves) {
        if (Test-Path -LiteralPath $chave) {
            $propriedades = Get-ItemProperty -LiteralPath $chave
            if ($propriedades.PSObject.Properties.Name -contains $Nome) {
                return $true
            }
        }
    }
    return $false
}

function Test-RebootPendente {
    $chaves = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
    )
    foreach ($chave in $chaves) {
        if (Test-Path -LiteralPath $chave) { return $true }
    }
    $sm = Get-ItemProperty -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager" -ErrorAction SilentlyContinue
    if ($sm.PendingFileRenameOperations) { return $true }
    return $false
}

function Invoke-BaixarDriver {
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$Destino
    )
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = "SilentlyContinue"
    Write-Host "Baixando $Url ..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $Url -OutFile $Destino -UseBasicParsing
    if (-not (Test-Path -LiteralPath $Destino)) {
        throw "Download falhou: o arquivo nao foi criado em $Destino"
    }
    $tamanho = (Get-Item -LiteralPath $Destino).Length
    Write-Host ("Download concluido: {0} ({1:N1} MB)" -f $Destino, ($tamanho / 1MB)) -ForegroundColor Green
}

function Invoke-InstalarMsi {
    param([Parameter(Mandatory)][string]$Msi)
    $ehAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent())
        .IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $ehAdmin) {
        throw "A instalacao via MSI exige administrador. Abra o PowerShell como administrador e rode: msiexec /i `"$Msi`" /quiet /norestart"
    }
    Write-Host "Instalando via MSI (pode levar alguns minutos)..." -ForegroundColor Cyan
    $processo = Start-Process -FilePath "msiexec" -ArgumentList @("/i", "`"$Msi`"", "/quiet", "/norestart", "IACCEPTMSODBCSQLLICENSETERMS=YES") -Wait -PassThru -WindowStyle Hidden
    if ($processo.ExitCode -notin 0, 3010) {
        throw "msiexec falhou com codigo $($processo.ExitCode)."
    }
}

$driverName = $driverNames[$Version]

try {
    $driverJaInstalado = Test-OdbcDriverInstalado -Nome $driverName
    if ($driverJaInstalado -and -not $Force) {
        Write-Host "$driverName ja esta instalado. Use -Force para reinstalar." -ForegroundColor Green
        exit 0
    }

    if ($DownloadOnly) {
        if (-not $OutFile) {
            $OutFile = Join-Path (Get-Location) "msodbcsql$Version.msi"
        }
        Invoke-BaixarDriver -Url $links[$Version] -Destino $OutFile
        Write-Host "Apenas download. Para instalar depois: msiexec /i `"$OutFile`" /quiet /norestart" -ForegroundColor Yellow
        exit 0
    }

    if (Test-RebootPendente) {
        Write-Host "ERRO: ha um reinicio pendente no Windows que bloqueia a instalacao do driver. Reinicie o computador e tente novamente." -ForegroundColor Red
        exit 1
    }

    if (-not $NoWinget -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        $pacote = $wingetIds[$Version]
        Write-Host "Instalando $driverName via winget ($pacote)..." -ForegroundColor Cyan
        & winget install --id $pacote --silent --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -eq 0) {
            Write-Host "$driverName instalado via winget." -ForegroundColor Green
            exit 0
        }
        Write-Host "winget falhou (codigo $LASTEXITCODE); tentando download direto do MSI." -ForegroundColor Yellow
    }

    if (-not $OutFile) {
        $OutFile = Join-Path $env:TEMP "msodbcsql$Version.msi"
    }
    Invoke-BaixarDriver -Url $links[$Version] -Destino $OutFile
    Invoke-InstalarMsi -Msi $OutFile
    Write-Host "$driverName instalado com sucesso." -ForegroundColor Green
    exit 0
}
catch {
    Write-Host "ERRO: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

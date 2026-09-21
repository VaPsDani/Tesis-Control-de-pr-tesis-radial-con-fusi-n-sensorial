# mantener_despierto.ps1
# Pide a Windows que no se suspenda por inactividad MIENTRAS corra en WSL un
# proceso cuya linea de comandos contenga -Patron, y retira la peticion sola
# al terminar. No cambia ninguna configuracion de energia: es la misma
# peticion temporal que hace un reproductor de video. La pantalla si puede
# apagarse. No evita una suspension manual ni un reinicio de Windows Update.
#
# Uso: powershell -File mantener_despierto.ps1 -Patron tanda_a_b.sh
param([string]$Patron = "rehacer_capitulo.sh")

$firma = @"
using System;
using System.Runtime.InteropServices;
public static class Energia {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@
Add-Type -TypeDefinition $firma

$ES_CONTINUOUS      = [uint32]2147483648
$ES_SYSTEM_REQUIRED = [uint32]1
$activo = [uint32]($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED)
$log = Join-Path $env:TEMP "mantener_despierto.log"

function Registrar($texto) { "$(Get-Date -Format s)  $texto" | Out-File -FilePath $log -Append -Encoding utf8 }

[Energia]::SetThreadExecutionState($activo) | Out-Null
Registrar "peticion de no suspender ACTIVA (vigilando '$Patron')"

$visto = $false
$inicio = Get-Date
while ($true) {
    $vivo = [bool](wsl.exe -d Ubuntu pgrep -f $Patron)
    if ($vivo -and -not $visto) { Registrar "proceso '$Patron' detectado"; $visto = $true }
    # Termina cuando el proceso, ya visto, desaparece; o si nunca aparecio
    # en 10 minutos (el lanzamiento fallo).
    if (-not $vivo -and ($visto -or ((Get-Date) - $inicio).TotalMinutes -gt 10)) { break }
    [Energia]::SetThreadExecutionState($activo) | Out-Null
    Start-Sleep -Seconds 60
}

[Energia]::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null
Registrar "proceso '$Patron' terminado: peticion RETIRADA"

# Texto de una imagen con el OCR integrado de Windows (Windows.Media.Ocr), sin instalar nada.
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File ocr_windows.ps1 -Path imagen.png [-Language es-MX]
# Escribe el texto en UTF-8, una línea por renglón reconocido. Sale con 2 si no hay reconocedor del idioma.
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [string]$Language = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]

# Las operaciones de WinRT son asíncronas: se esperan con AsTask.
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq "IAsyncOperation``1"
} | Select-Object -First 1

function Await($operation, [Type]$resultType) {
    $task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($operation))
    $task.Wait() | Out-Null
    return $task.Result
}

if ($Language) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($Language))
} else {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}

if ($null -eq $engine) {
    [Console]::Error.WriteLine("No hay reconocedor de OCR para el idioma.")
    exit 2
}

try {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path $Path).Path)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
} catch {
    # Un archivo que no es una imagen válida: un mensaje corto, sin la traza de PowerShell.
    [Console]::Error.WriteLine("no es una imagen que Windows pueda abrir")
    exit 1
}

foreach ($line in $result.Lines) {
    [Console]::Out.WriteLine($line.Text)
}

$stream.Dispose()

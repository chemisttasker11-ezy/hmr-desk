param([string]$List, [string]$Out)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$ext = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 }
$opM = $ext | Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$actM = $ext | Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1
function Await($op, [type]$t) { $task = $opM.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(); $task.Result }
$ocr = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$results = @{}
foreach ($path in Get-Content $List) {
  $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
  $doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
  $txt = @()
  for ($p = 0; $p -lt $doc.PageCount; $p++) {
    $page = $doc.GetPage($p)
    $opt = New-Object Windows.Data.Pdf.PdfPageRenderOptions; $opt.DestinationWidth = 2000
    $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    $actM.Invoke($null, @($page.RenderToStreamAsync($stream, $opt))).Wait()
    $bmp = Await ((Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])).GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $txt += ,(((Await ($ocr.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])).Lines | ForEach-Object Text) -join "`n")
  }
  $results[$path] = @($txt)
}

$results | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $Out "ocr.json") -Encoding UTF8

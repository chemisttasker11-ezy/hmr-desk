# word2pdf.ps1 <docx> <pdf> : render with Microsoft Word (read-only open, no changes saved)
param([string]$Docx, [string]$Pdf)
$w = New-Object -ComObject Word.Application
$w.Visible = $false
$w.DisplayAlerts = 0
try {
    $doc = $w.Documents.Open($Docx, $false, $true)
    $doc.ExportAsFixedFormat($Pdf, 17)
    $doc.Close(0)
} finally { $w.Quit() }

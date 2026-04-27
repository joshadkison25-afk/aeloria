param([string]$Path, [string]$OutPath)
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($Path)
try {
  $entry = $zip.Entries | Where-Object { $_.FullName -eq 'word/document.xml' }
  if (-not $entry) { Write-Error "no document.xml in $Path"; return }
  $sr = New-Object System.IO.StreamReader($entry.Open())
  $xmlStr = $sr.ReadToEnd()
  $sr.Close()
} finally {
  $zip.Dispose()
}

[xml]$xml = $xmlStr
$nsmgr = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
$nsmgr.AddNamespace('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')

$sb = New-Object System.Text.StringBuilder
foreach ($p in $xml.SelectNodes('//w:p', $nsmgr)) {
  $line = New-Object System.Text.StringBuilder
  foreach ($t in $p.SelectNodes('.//w:t', $nsmgr)) {
    [void]$line.Append($t.InnerText)
  }
  [void]$sb.AppendLine($line.ToString())
}

if ($OutPath) {
  Set-Content -Path $OutPath -Value $sb.ToString() -Encoding UTF8
  Write-Output ("WROTE " + $OutPath + " (" + $sb.Length + " chars)")
} else {
  Write-Output $sb.ToString()
}

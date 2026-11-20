Add-Type -AssemblyName System.Drawing
$projectRoot = Split-Path -Parent $PSScriptRoot
$iconDirectory = Join-Path $projectRoot 'src-tauri/icons'
New-Item -ItemType Directory -Path $iconDirectory -Force | Out-Null
$bitmap = [System.Drawing.Bitmap]::new(256, 256)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.Clear([System.Drawing.ColorTranslator]::FromHtml('#257d61'))
$pen = [System.Drawing.Pen]::new([System.Drawing.Color]::White, 9)
$pen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
$graphics.DrawLines($pen, [System.Drawing.Point[]]@([System.Drawing.Point]::new(54,65),[System.Drawing.Point]::new(112,77),[System.Drawing.Point]::new(128,90),[System.Drawing.Point]::new(144,77),[System.Drawing.Point]::new(202,65),[System.Drawing.Point]::new(202,183),[System.Drawing.Point]::new(144,195),[System.Drawing.Point]::new(128,208),[System.Drawing.Point]::new(112,195),[System.Drawing.Point]::new(54,183),[System.Drawing.Point]::new(54,65)))
$graphics.DrawLine($pen,128,90,128,208)
$pngStream = [System.IO.MemoryStream]::new()
$bitmap.Save($pngStream, [System.Drawing.Imaging.ImageFormat]::Png)
$png = $pngStream.ToArray()
$iconStream = [System.IO.MemoryStream]::new()
$writer = [System.IO.BinaryWriter]::new($iconStream)
$writer.Write([uint16]0); $writer.Write([uint16]1); $writer.Write([uint16]1)
$writer.Write([byte]0); $writer.Write([byte]0); $writer.Write([byte]0); $writer.Write([byte]0)
$writer.Write([uint16]1); $writer.Write([uint16]32); $writer.Write([uint32]$png.Length); $writer.Write([uint32]22)
$writer.Write($png)
[System.IO.File]::WriteAllBytes((Join-Path $iconDirectory 'icon.ico'), $iconStream.ToArray())
$writer.Dispose(); $iconStream.Dispose(); $pngStream.Dispose(); $pen.Dispose(); $graphics.Dispose(); $bitmap.Dispose()
Write-Output 'Generated src-tauri/icons/icon.ico'

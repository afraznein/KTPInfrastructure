param(
    [Parameter(Mandatory = $true)] [string]$AtlasJson,
    [Parameter(Mandatory = $true)] [string]$OverviewBmp,
    [Parameter(Mandatory = $true)] [string]$OutputDirectory,
    [string]$MapConfig = (Join-Path (Split-Path -Parent $PSScriptRoot) 'config\analytics\spatial_maps\dod_anzio.json')
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$atlas = Get-Content -LiteralPath $AtlasJson -Raw | ConvertFrom-Json
$spatialConfig = Get-Content -LiteralPath $MapConfig -Raw | ConvertFrom-Json
$mapDisplayName = if ($spatialConfig.display_name) {
    [string]$spatialConfig.display_name
} else {
    [string]$spatialConfig.map_name
}
$overview = @{
    OriginX = [double]$spatialConfig.overview.origin_x
    OriginY = [double]$spatialConfig.overview.origin_y
    Zoom = [double]$spatialConfig.overview.zoom
    Rotated = [bool]$spatialConfig.overview.rotated
}
$gridSize = [double]$atlas.grid_size
$mapWidth = [int]$spatialConfig.overview.width
$mapHeight = [int]$spatialConfig.overview.height
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

function Convert-WorldToPixel {
    param([double]$WorldX, [double]$WorldY, [int]$Width, [int]$Height)
    $aspect = 4.0 / 3.0
    if ($overview.Rotated) {
        $halfX = 4096.0 / $overview.Zoom
        $halfY = 4096.0 / ($overview.Zoom * $aspect)
        $pixelX = ($WorldX - ($overview.OriginX - $halfX)) / (2.0 * $halfX) * $Width
        $pixelY = (($overview.OriginY + $halfY) - $WorldY) / (2.0 * $halfY) * $Height
    } else {
        $halfX = 4096.0 / ($overview.Zoom * $aspect)
        $halfY = 4096.0 / $overview.Zoom
        $pixelX = (($overview.OriginY + $halfY) - $WorldY) / (2.0 * $halfY) * $Width
        $pixelY = (($overview.OriginX + $halfX) - $WorldX) / (2.0 * $halfX) * $Height
    }
    [System.Drawing.PointF]::new([single]$pixelX, [single]$pixelY)
}

function Get-CellRectangle {
    param([string]$Key, [int]$Width, [int]$Height)
    $parts = $Key.Split(',')
    $cellX = [double]$parts[0]
    $cellY = [double]$parts[1]
    $worldX0 = $cellX * $gridSize
    $worldX1 = ($cellX + 1) * $gridSize
    $worldY0 = $cellY * $gridSize
    $worldY1 = ($cellY + 1) * $gridSize
    $corners = @(
        (Convert-WorldToPixel $worldX0 $worldY0 $Width $Height),
        (Convert-WorldToPixel $worldX0 $worldY1 $Width $Height),
        (Convert-WorldToPixel $worldX1 $worldY0 $Width $Height),
        (Convert-WorldToPixel $worldX1 $worldY1 $Width $Height)
    )
    $left = [single](($corners | Measure-Object -Property X -Minimum).Minimum)
    $right = [single](($corners | Measure-Object -Property X -Maximum).Maximum)
    $top = [single](($corners | Measure-Object -Property Y -Minimum).Minimum)
    $bottom = [single](($corners | Measure-Object -Property Y -Maximum).Maximum)
    [System.Drawing.RectangleF]::new($left, $top, $right - $left, $bottom - $top)
}

function Get-PaletteColor {
    param([string]$Name)
    switch ($Name) {
        'blue'   { [System.Drawing.Color]::FromArgb(54, 154, 255) }
        'cyan'   { [System.Drawing.Color]::FromArgb(43, 219, 225) }
        'gold'   { [System.Drawing.Color]::FromArgb(255, 196, 45) }
        'green'  { [System.Drawing.Color]::FromArgb(68, 220, 120) }
        'orange' { [System.Drawing.Color]::FromArgb(255, 126, 36) }
        'purple' { [System.Drawing.Color]::FromArgb(190, 92, 255) }
        'red'    { [System.Drawing.Color]::FromArgb(255, 66, 72) }
        default  { [System.Drawing.Color]::FromArgb(255, 196, 45) }
    }
}

function New-MapCanvas {
    $source = [System.Drawing.Bitmap]::FromFile($OverviewBmp)
    $corner = $source.GetPixel(0, 0)
    if ($corner.G -ge 200 -and $corner.R -le 32 -and $corner.B -le 32) {
        # Older DoD overview bitmaps use a bright-green corner color as a
        # transparency key. Preserve normal artwork; remove only that exact key.
        $source.MakeTransparent($corner)
    }
    $canvas = [System.Drawing.Bitmap]::new($mapWidth, $mapHeight)
    $graphics = [System.Drawing.Graphics]::FromImage($canvas)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.DrawImage($source, 0, 0, $mapWidth, $mapHeight)
    $dim = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(68, 0, 0, 0))
    $graphics.FillRectangle($dim, 0, 0, $mapWidth, $mapHeight)
    $dim.Dispose(); $source.Dispose()
    [pscustomobject]@{ Canvas = $canvas; Graphics = $graphics }
}

function Draw-Header {
    param([System.Drawing.Graphics]$Graphics, [string]$Title, [string]$Detail, [int]$Width)
    $titleFont = [System.Drawing.Font]::new('Segoe UI', 19, [System.Drawing.FontStyle]::Bold)
    $detailFont = [System.Drawing.Font]::new('Segoe UI', 9.5)
    $white = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
    $muted = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(225, 215, 225, 235))
    $back = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(225, 8, 11, 18))
    $format = [System.Drawing.StringFormat]::new()
    $format.Trimming = [System.Drawing.StringTrimming]::EllipsisCharacter
    $format.FormatFlags = [System.Drawing.StringFormatFlags]::NoWrap
    try {
        $Graphics.FillRectangle($back, 14, 16, $Width - 28, 75)
        $Graphics.DrawString($Title, $titleFont, $white, [System.Drawing.RectangleF]::new(28, 22, $Width - 56, 33), $format)
        $Graphics.DrawString($Detail, $detailFont, $muted, [System.Drawing.RectangleF]::new(30, 58, $Width - 60, 24), $format)
    } finally {
        $titleFont.Dispose(); $detailFont.Dispose(); $white.Dispose(); $muted.Dispose(); $back.Dispose(); $format.Dispose()
    }
}

function Draw-Flags {
    param([System.Drawing.Graphics]$Graphics, [int]$Width, [int]$Height)
    $font = [System.Drawing.Font]::new('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
    $outline = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(245, 8, 8, 8), 3)
    $fill = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(245, 255, 255, 255))
    $text = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
    $back = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(205, 0, 0, 0))
    try {
        foreach ($flag in $atlas.flags) {
            $point = Convert-WorldToPixel ([double]$flag.x) ([double]$flag.y) $Width $Height
            $Graphics.FillEllipse($fill, $point.X - 5, $point.Y - 5, 10, 10)
            $Graphics.DrawEllipse($outline, $point.X - 5, $point.Y - 5, 10, 10)
            $size = $Graphics.MeasureString([string]$flag.name, $font)
            $x = $point.X + 8; $y = $point.Y - ($size.Height / 2)
            $Graphics.FillRectangle($back, $x - 2, $y - 1, $size.Width + 4, $size.Height + 2)
            $Graphics.DrawString([string]$flag.name, $font, $text, $x, $y)
        }
    } finally {
        $font.Dispose(); $outline.Dispose(); $fill.Dispose(); $text.Dispose(); $back.Dispose()
    }
}

function Draw-Legend {
    param([System.Drawing.Graphics]$Graphics, [string]$Text, [System.Drawing.Color]$Color, [int]$Width, [int]$Height)
    $font = [System.Drawing.Font]::new('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
    $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(218, 8, 11, 18))
    $colorBrush = [System.Drawing.SolidBrush]::new($Color)
    $white = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
    try {
        $size = $Graphics.MeasureString($Text, $font)
        $x = $Width - $size.Width - 61; $y = $Height - 50
        $Graphics.FillRectangle($brush, $x - 12, $y - 8, $size.Width + 55, 36)
        $Graphics.FillRectangle($colorBrush, $x, $y, 22, 18)
        $Graphics.DrawString($Text, $font, $white, $x + 29, $y)
    } finally {
        $font.Dispose(); $brush.Dispose(); $colorBrush.Dispose(); $white.Dispose()
    }
}

function Save-Canvas {
    param($Map, [string]$Name)
    $path = Join-Path $OutputDirectory $Name
    $Map.Canvas.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $Map.Graphics.Dispose(); $Map.Canvas.Dispose()
    $path
}

function Render-Heatmap {
    param($Panel)
    if (@($Panel.cells).Count -eq 0) {
        return Render-Placeholder $Panel 'No qualifying cells were available for this layer.'
    }
    $map = New-MapCanvas
    $max = [double](($Panel.cells | Measure-Object -Property value -Maximum).Maximum)
    if ($max -le 0) { $max = 1 }
    $base = Get-PaletteColor ([string]$Panel.palette)
    foreach ($cell in $Panel.cells) {
        $level = [Math]::Sqrt([Math]::Max(0, [double]$cell.value) / $max)
        $alpha = [int](35 + 205 * $level)
        $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb($alpha, $base.R, $base.G, $base.B))
        $rect = Get-CellRectangle ([string]$cell.key) $mapWidth $mapHeight
        $map.Graphics.FillRectangle($brush, $rect); $brush.Dispose()
    }
    Draw-Flags $map.Graphics $mapWidth $mapHeight
    Draw-Header $map.Graphics ([string]$Panel.title) ([string]$Panel.detail) $mapWidth
    Draw-Legend $map.Graphics 'higher aggregate intensity' $base $mapWidth $mapHeight
    Save-Canvas $map ([string]$Panel.name)
}

function Render-Signed {
    param($Panel)
    if (@($Panel.cells).Count -eq 0) {
        return Render-Placeholder $Panel 'No cells met both comparison thresholds for this layer.'
    }
    $map = New-MapCanvas
    $maxAbs = 0.0
    foreach ($cell in $Panel.cells) { $maxAbs = [Math]::Max($maxAbs, [Math]::Abs([double]$cell.value)) }
    if ($maxAbs -le 0) { $maxAbs = 1 }
    $positive = if ([string]$Panel.palette -eq 'blue') { Get-PaletteColor 'blue' } else { Get-PaletteColor 'gold' }
    $negative = Get-PaletteColor 'red'
    foreach ($cell in $Panel.cells) {
        $value = [double]$cell.value
        $base = if ($value -ge 0) { $positive } else { $negative }
        $level = [Math]::Sqrt([Math]::Abs($value) / $maxAbs)
        $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb([int](38 + 202 * $level), $base.R, $base.G, $base.B))
        $map.Graphics.FillRectangle($brush, (Get-CellRectangle ([string]$cell.key) $mapWidth $mapHeight)); $brush.Dispose()
    }
    Draw-Flags $map.Graphics $mapWidth $mapHeight
    Draw-Header $map.Graphics ([string]$Panel.title) ([string]$Panel.detail) $mapWidth
    $legend = if ([string]$Panel.palette -eq 'blue') { 'blue positive | red negative' } else { 'gold positive | red negative' }
    Draw-Legend $map.Graphics $legend $positive $mapWidth $mapHeight
    Save-Canvas $map ([string]$Panel.name)
}

function Render-Balance {
    param($Panel)
    if (@($Panel.cells).Count -eq 0) {
        return Render-Placeholder $Panel 'No coordinate-bearing combat events were available for this layer.'
    }
    $map = New-MapCanvas
    $maxTotal = 1.0
    foreach ($cell in $Panel.cells) { $maxTotal = [Math]::Max($maxTotal, [double]$cell.kills + [double]$cell.deaths) }
    $gold = Get-PaletteColor 'gold'; $red = Get-PaletteColor 'red'
    foreach ($cell in $Panel.cells) {
        $kills = [double]$cell.kills; $deaths = [double]$cell.deaths; $total = $kills + $deaths
        if ($total -le 0) { continue }
        $killShare = $kills / $total
        $r = [int]($red.R + (($gold.R - $red.R) * $killShare))
        $g = [int]($red.G + (($gold.G - $red.G) * $killShare))
        $b = [int]($red.B + (($gold.B - $red.B) * $killShare))
        $alpha = [int](42 + 198 * [Math]::Sqrt($total / $maxTotal))
        $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb($alpha, $r, $g, $b))
        $map.Graphics.FillRectangle($brush, (Get-CellRectangle ([string]$cell.key) $mapWidth $mapHeight)); $brush.Dispose()
    }
    Draw-Flags $map.Graphics $mapWidth $mapHeight
    Draw-Header $map.Graphics ([string]$Panel.title) ([string]$Panel.detail) $mapWidth
    Draw-Legend $map.Graphics 'gold kills | red deaths' $gold $mapWidth $mapHeight
    Save-Canvas $map ([string]$Panel.name)
}

function Render-Vectors {
    param($Panel)
    if (@($Panel.vectors).Count -eq 0) {
        return Render-Placeholder $Panel 'No qualifying combat vectors were available for this layer.'
    }
    $map = New-MapCanvas
    $max = [double](($Panel.vectors | Measure-Object -Property count -Maximum).Maximum)
    if ($max -le 0) { $max = 1 }
    foreach ($vector in $Panel.vectors) {
        $start = Convert-WorldToPixel ([double]$vector.x1) ([double]$vector.y1) $mapWidth $mapHeight
        $end = Convert-WorldToPixel ([double]$vector.x2) ([double]$vector.y2) $mapWidth $mapHeight
        $level = [Math]::Sqrt([double]$vector.count / $max)
        $hs = [double]$vector.headshot_rate
        $color = [System.Drawing.Color]::FromArgb([int](70 + 170 * $level), 255, [int](166 + 70 * $hs), 40)
        $pen = [System.Drawing.Pen]::new($color, [single](1.2 + 5.0 * $level))
        $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::RoundAnchor
        $map.Graphics.DrawLine($pen, $start, $end); $pen.Dispose()
        if ([int]$vector.count -gt 1) {
            $victim = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(170, 255, 68, 76))
            $radius = [single](1.5 + 2.5 * $level)
            $map.Graphics.FillEllipse($victim, $end.X - $radius, $end.Y - $radius, $radius * 2, $radius * 2); $victim.Dispose()
        }
    }
    Draw-Flags $map.Graphics $mapWidth $mapHeight
    Draw-Header $map.Graphics ([string]$Panel.title) ([string]$Panel.detail) $mapWidth
    Draw-Legend $map.Graphics 'line width = recurrence' (Get-PaletteColor 'gold') $mapWidth $mapHeight
    Save-Canvas $map ([string]$Panel.name)
}

function Render-Table {
    param($Panel)
    $width = 1600; $height = 900
    $canvas = [System.Drawing.Bitmap]::new($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($canvas)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.Clear([System.Drawing.Color]::FromArgb(15, 19, 28))
    $accent = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(36, 46, 65))
    $headerBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(50, 67, 91))
    $alternate = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(23, 29, 41))
    $line = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(70, 90, 116), 1)
    $white = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
    $muted = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(205, 215, 225))
    $titleFont = [System.Drawing.Font]::new('Segoe UI', 28, [System.Drawing.FontStyle]::Bold)
    $detailFont = [System.Drawing.Font]::new('Segoe UI', 13)
    $headFont = [System.Drawing.Font]::new('Segoe UI', 12, [System.Drawing.FontStyle]::Bold)
    $cellFont = [System.Drawing.Font]::new('Segoe UI', 11)
    $format = [System.Drawing.StringFormat]::new()
    $format.LineAlignment = [System.Drawing.StringAlignment]::Center
    $format.Trimming = [System.Drawing.StringTrimming]::EllipsisCharacter
    $format.FormatFlags = [System.Drawing.StringFormatFlags]::NoWrap
    try {
        $graphics.FillRectangle($accent, 0, 0, $width, 125)
        $graphics.DrawString([string]$Panel.title, $titleFont, $white, 55, 30)
        $graphics.DrawString([string]$Panel.detail, $detailFont, $muted, 58, 80)
        $columns = @($Panel.columns); $rows = @($Panel.rows)
        $left = 55; $top = 165; $tableWidth = $width - 110
        $rowHeight = [Math]::Min(72, [Math]::Max(46, [Math]::Floor(($height - $top - 70) / ([Math]::Max(1, $rows.Count) + 1))))
        $columnWidth = $tableWidth / $columns.Count
        $graphics.FillRectangle($headerBrush, $left, $top, $tableWidth, $rowHeight)
        for ($columnIndex = 0; $columnIndex -lt $columns.Count; $columnIndex++) {
            $rect = [System.Drawing.RectangleF]::new([single]($left + $columnIndex * $columnWidth + 10), [single]$top, [single]($columnWidth - 20), [single]$rowHeight)
            $graphics.DrawString([string]$columns[$columnIndex], $headFont, $white, $rect, $format)
        }
        for ($rowIndex = 0; $rowIndex -lt $rows.Count; $rowIndex++) {
            $y = $top + ($rowIndex + 1) * $rowHeight
            if ($rowIndex % 2 -eq 1) { $graphics.FillRectangle($alternate, $left, $y, $tableWidth, $rowHeight) }
            for ($columnIndex = 0; $columnIndex -lt $columns.Count; $columnIndex++) {
                $column = [string]$columns[$columnIndex]
                $value = [string]$rows[$rowIndex].$column
                $rect = [System.Drawing.RectangleF]::new([single]($left + $columnIndex * $columnWidth + 10), [single]$y, [single]($columnWidth - 20), [single]$rowHeight)
                $graphics.DrawString($value, $cellFont, $muted, $rect, $format)
            }
            $graphics.DrawLine($line, $left, $y + $rowHeight, $left + $tableWidth, $y + $rowHeight)
        }
        for ($columnIndex = 0; $columnIndex -le $columns.Count; $columnIndex++) {
            $x = $left + $columnIndex * $columnWidth
            $graphics.DrawLine($line, $x, $top, $x, $top + ($rows.Count + 1) * $rowHeight)
        }
        $privacyFont = [System.Drawing.Font]::new('Segoe UI', 10, [System.Drawing.FontStyle]::Italic)
        try { $graphics.DrawString('Aggregate-only output - no player identities, individual heatmaps, or routes', $privacyFont, $muted, 57, $height - 43) } finally { $privacyFont.Dispose() }
        $path = Join-Path $OutputDirectory ([string]$Panel.name)
        $canvas.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
        $path
    } finally {
        $graphics.Dispose(); $canvas.Dispose(); $accent.Dispose(); $headerBrush.Dispose(); $alternate.Dispose(); $line.Dispose()
        $white.Dispose(); $muted.Dispose(); $titleFont.Dispose(); $detailFont.Dispose(); $headFont.Dispose(); $cellFont.Dispose(); $format.Dispose()
    }
}

function Render-Placeholder {
    param($Panel, [string]$Message)
    $placeholder = [pscustomobject]@{
        name = [string]$Panel.name; title = [string]$Panel.title; detail = [string]$Panel.detail
        columns = @('Status', 'Explanation'); rows = @([pscustomobject]@{ Status = 'No data'; Explanation = $Message })
    }
    Render-Table $placeholder
}

$rendered = [System.Collections.Generic.List[string]]::new()
foreach ($panel in $atlas.panels) {
    $path = switch ([string]$panel.type) {
        'heatmap'    { Render-Heatmap $panel; break }
        'signed'     { Render-Signed $panel; break }
        'balance'    { Render-Balance $panel; break }
        'vectors'    { Render-Vectors $panel; break }
        'table'      { Render-Table $panel; break }
        'placeholder'{ Render-Placeholder $panel ([string]$panel.message); break }
        default      { throw "Unknown panel type '$($panel.type)'" }
    }
    $rendered.Add([string]$path)
}

function New-ContactSheet {
    param([string[]]$ImagePaths, [string]$OutputPath)
    $columns = 5; $cellWidth = 310; $cellHeight = 225; $margin = 20; $headerHeight = 92
    $rows = [Math]::Ceiling($ImagePaths.Count / [double]$columns)
    $width = ($columns * $cellWidth) + ($margin * 2)
    $height = $headerHeight + ($rows * $cellHeight) + $margin
    $canvas = [System.Drawing.Bitmap]::new($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($canvas)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.Clear([System.Drawing.Color]::FromArgb(12, 16, 24))
    $titleFont = [System.Drawing.Font]::new('Segoe UI', 24, [System.Drawing.FontStyle]::Bold)
    $labelFont = [System.Drawing.Font]::new('Segoe UI', 8.5)
    $white = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
    $muted = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(205, 215, 225))
    $border = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(65, 82, 108), 1)
    $format = [System.Drawing.StringFormat]::new()
    $format.Trimming = [System.Drawing.StringTrimming]::EllipsisCharacter
    $format.FormatFlags = [System.Drawing.StringFormatFlags]::NoWrap
    try {
        $graphics.DrawString("$mapDisplayName spatial analytics atlas", $titleFont, $white, $margin, 18)
        $graphics.DrawString("$($ImagePaths.Count) aggregate-only analytical panels", $labelFont, $muted, $margin + 2, 61)
        for ($index = 0; $index -lt $ImagePaths.Count; $index++) {
            $column = $index % $columns; $row = [Math]::Floor($index / $columns)
            $x = $margin + ($column * $cellWidth); $y = $headerHeight + ($row * $cellHeight)
            $source = [System.Drawing.Bitmap]::FromFile($ImagePaths[$index])
            try {
                $availableWidth = $cellWidth - 14; $availableHeight = $cellHeight - 36
                $scale = [Math]::Min($availableWidth / $source.Width, $availableHeight / $source.Height)
                $drawWidth = [int]($source.Width * $scale); $drawHeight = [int]($source.Height * $scale)
                $drawX = $x + [int](($availableWidth - $drawWidth) / 2)
                $drawY = $y + 2 + [int](($availableHeight - $drawHeight) / 2)
                $graphics.DrawImage($source, $drawX, $drawY, $drawWidth, $drawHeight)
                $graphics.DrawRectangle($border, $drawX, $drawY, $drawWidth, $drawHeight)
                $labelRect = [System.Drawing.RectangleF]::new([single]($x + 4), [single]($y + $availableHeight + 7), [single]($cellWidth - 18), 22)
                $graphics.DrawString([System.IO.Path]::GetFileName($ImagePaths[$index]), $labelFont, $muted, $labelRect, $format)
            } finally { $source.Dispose() }
        }
        $canvas.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $graphics.Dispose(); $canvas.Dispose(); $titleFont.Dispose(); $labelFont.Dispose()
        $white.Dispose(); $muted.Dispose(); $border.Dispose(); $format.Dispose()
    }
}

$contactSheet = Join-Path $OutputDirectory '99-atlas-contact-sheet.png'
New-ContactSheet @($rendered) $contactSheet
$rendered.Add($contactSheet)

$metadata = [ordered]@{
    schema_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    map = [string]$atlas.map
    target_match_id = [string]$atlas.target_match_id
    grid_size = [double]$atlas.grid_size
    privacy = [string]$atlas.privacy
    summary = $atlas.summary
    contact_sheet = '99-atlas-contact-sheet.png'
    images = @($atlas.panels | ForEach-Object { [ordered]@{ file = [string]$_.name; category = [string]$_.category; title = [string]$_.title; detail = [string]$_.detail; type = [string]$_.type } })
}
$metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'atlas-metadata.json') -Encoding UTF8

$readme = [System.Collections.Generic.List[string]]::new()
$readme.Add("# $mapDisplayName spatial analytics atlas")
$readme.Add('')
$readme.Add("This folder contains one aggregate-only image set built from $($atlas.summary.matches) local Lane B bot matches. It exposes no player names, identifiers, individual heatmaps, or routes. The current baseline is synthetic and is not yet a competitive-match norm.")
$readme.Add('')
$readme.Add('[Open the full contact sheet](99-atlas-contact-sheet.png)')
$readme.Add('')
$readme.Add('## Images')
$readme.Add('')
foreach ($panel in $atlas.panels) {
    $readme.Add("- [$($panel.name)]($($panel.name)) - **$($panel.category):** $($panel.detail)")
}
$readme.Add('')
$readme.Add('## Definitions and cautions')
$readme.Add('')
$analysis = $spatialConfig.analysis
$readme.Add("- Occupancy is reconstructed from $($analysis.sample_seconds)-second periodic position samples; one sample contributes $($analysis.sample_seconds) seconds.")
$readme.Add("- Normalized target rates require at least $($analysis.target_cell_minimum_seconds) seconds of cell occupancy; corpus rates require at least $($analysis.corpus_cell_minimum_seconds) aggregate seconds.")
$readme.Add("- Trade kill: a teammate kills the prior killer within $($analysis.trade_seconds) seconds. Fast multikill: consecutive personal kills within $($analysis.multikill_seconds) seconds.")
$readme.Add("- Isolated death: no teammate has a position sample within $($analysis.nearest_sample_seconds) seconds and $($analysis.isolation_radius_units) world units of the death.")
$readme.Add("- Damage positions are approximate: capped damage is assigned to the attacker's nearest periodic sample within $($analysis.nearest_sample_seconds) seconds.")
$readme.Add("- Pre-event maps contain aggregate samples or combat from the $($analysis.event_window_seconds) seconds before capture, cap-break, or reconstructed capout events.")
$readme.Add('- Target-vs-baseline panels use the other four bot matches, avoiding self-comparison. Real matches are needed before calling this a competitive baseline.')
$readme.Add('- Grenade explosion/damage heatmaps remain deferred until exact explosion events are persisted; inferred grenade locations are intentionally not shown.')
$readme.Add('')
$readme.Add('See `atlas-metadata.json` for machine-readable counts and the image manifest.')
$readme | Set-Content -LiteralPath (Join-Path $OutputDirectory 'README.md') -Encoding UTF8

[pscustomobject]@{
    OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
    ImageCount = $rendered.Count
    Metadata = Join-Path $OutputDirectory 'atlas-metadata.json'
    Readme = Join-Path $OutputDirectory 'README.md'
}

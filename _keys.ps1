$j = Get-Content 'C:/Users/Josh/Desktop/aeloria/world_state.json' -Raw | ConvertFrom-Json
$out = @()
foreach ($p in $j.PSObject.Properties) {
  $v = $p.Value
  $kind = 'scalar'
  $count = ''
  if ($null -eq $v) { $kind = 'null' }
  elseif ($v -is [System.Array] -or $v -is [System.Collections.IEnumerable] -and -not ($v -is [string])) {
    $kind = 'list'; try { $count = ($v | Measure-Object).Count } catch {}
  } elseif ($v -is [System.Management.Automation.PSCustomObject]) {
    $kind = 'obj'; $count = ($v.PSObject.Properties | Measure-Object).Count
  }
  $out += [pscustomobject]@{ key=$p.Name; kind=$kind; count=$count }
}
$out | Sort-Object key | Format-Table -AutoSize | Out-String -Width 200

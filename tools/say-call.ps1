# say-call.ps1 -- thin wrapper around ec20_uac_call.py --say  (ASCII on purpose)
param([Parameter(Mandatory=$true)][string]$Text,
      [Parameter(Mandatory=$true)][string]$Port,
      [Parameter(Mandatory=$true)][string]$Number,
      [string]$Voice = "", [switch]$Keep)
$args2 = @("..\ec20_uac_call.py","--say",$Text,"--port",$Port,"--dial",$Number)
if ($Voice) { $args2 += @("--voice", $Voice) }
if ($Keep)  { $args2 += "--keep" }
& python @args2

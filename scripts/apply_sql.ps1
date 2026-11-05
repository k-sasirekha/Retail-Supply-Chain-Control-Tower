# Apply every SQL file in order: schema, then seeds, then views.
# Safe to re-run: each file uses IF NOT EXISTS, CREATE OR REPLACE or ON CONFLICT DO NOTHING.
param(
    [string]$Database = "warehouse",
    [string]$User = "ct_admin",
    [string]$Container = "ct_postgres"
)

$folders = @("sql\schema", "sql\seeds", "sql\views")
foreach ($folder in $folders) {
    $files = Get-ChildItem (Join-Path $PSScriptRoot "..\$folder\*.sql") | Sort-Object Name
    foreach ($file in $files) {
        Write-Host "Applying $folder\$($file.Name)"
        Get-Content $file.FullName | docker exec -i -e PGOPTIONS="-c client_min_messages=warning" $Container psql -U $User -d $Database -v ON_ERROR_STOP=1 -q
        if ($LASTEXITCODE -ne 0) {
            Write-Host "FAILED: $($file.Name)" -ForegroundColor Red
            exit 1
        }
    }
}
Write-Host "Done: all SQL applied to database '$Database'."
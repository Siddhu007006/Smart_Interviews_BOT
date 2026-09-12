#Requires -Version 5.0
<#
.SYNOPSIS
Switch to a different Hive account by clearing cached browser profile

.DESCRIPTION
When you deliberately change HIVE_USERNAME/HIVE_PASSWORD in .env and want to 
switch to a different account, the old persistent browser profile still contains
cached session data (cookies, localStorage, etc) from the previous account.

This script clears the profile so the next run forces a fresh login with the 
NEW credentials from .env.

WARNING: This deletes the entire profile cache. Only use when deliberately switching accounts.
For normal operation with the same account, just run the bot - it reuses the persistent session.

.EXAMPLE
.\switch_account.ps1

Then run:
  python run.py

The bot will create a fresh profile and login with new credentials from .env
#>

param(
    [string]$ProfilePath = "$env:USERPROFILE\.hive_bot_profile"
)

Write-Host ""
Write-Host "════════════════════════════════════════════════════════════════"
Write-Host "                   ACCOUNT SWITCH UTILITY"
Write-Host "════════════════════════════════════════════════════════════════"
Write-Host ""
Write-Host "⚠️  This utility clears the ENTIRE browser profile cache."
Write-Host ""
Write-Host "Use this ONLY when you:"
Write-Host "  1. Changed HIVE_USERNAME and/or HIVE_PASSWORD in .env"
Write-Host "  2. Want to switch to a DIFFERENT account"
Write-Host "  3. Need to clear cached session from the old account"
Write-Host ""
Write-Host "For NORMAL operation with the SAME account:"
Write-Host "  Just run: python run.py"
Write-Host "  The bot will reuse the persistent session (no need to clear)"
Write-Host ""

# Check if profile exists
if (Test-Path $ProfilePath) {
    Write-Host "Found browser profile at:"
    Write-Host "  $ProfilePath"
    Write-Host ""
    Write-Host "Profile contents:"
    $size = (Get-ChildItem $ProfilePath -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Host "  Size: $([math]::Round($size, 2)) MB"
    Get-ChildItem $ProfilePath -Directory | ForEach-Object {
        Write-Host "  📁 $($_.Name)"
    }
    Write-Host ""
    
    Write-Host "🔴 CONFIRM: Are you switching to a DIFFERENT account? (yes/no)"
    $confirm = Read-Host "Type 'yes' to clear profile and switch accounts"
    
    if ($confirm -eq "yes") {
        try {
            Write-Host ""
            Write-Host "🔄 Clearing profile..."
            Remove-Item -Recurse -Force $ProfilePath -ErrorAction Stop
            Write-Host "✅ Profile cleared successfully"
            Write-Host ""
            Write-Host "Next steps:"
            Write-Host "  1. Verify HIVE_USERNAME and HIVE_PASSWORD are updated in .env"
            Write-Host "  2. Run: python run.py"
            Write-Host "  3. Bot will:"
            Write-Host "     • Create fresh browser profile"
            Write-Host "     • Login with NEW credentials from .env"
            Write-Host "     • Start solving problems with new account"
            Write-Host ""
        } catch {
            Write-Host "❌ Failed to clear profile: $_"
            exit 1
        }
    } else {
        Write-Host "❌ Cancelled - profile not cleared"
        Write-Host ""
        Write-Host "If you meant to just run the bot with the same account:"
        Write-Host "  python run.py"
        exit 0
    }
} else {
    Write-Host "Profile does not exist at:"
    Write-Host "  $ProfilePath"
    Write-Host ""
    Write-Host "The bot will create a fresh profile on next run."
    Write-Host "✅ Ready to login"
    Write-Host ""
}

Write-Host "════════════════════════════════════════════════════════════════"
Write-Host ""

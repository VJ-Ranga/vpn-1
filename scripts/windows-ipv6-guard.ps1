param(
    [ValidateSet('Enable', 'Disable', 'Status')]
    [string]$Action = 'Status'
)

# A fixed, app-owned rule only. Never disable adapter IPv6 bindings or alter
# unrelated firewall rules. Persistent so a helper crash cannot reopen IPv6.
$ErrorActionPreference = 'Stop'
$name = 'NorthstarVPN-Block-IPv6'
$group = 'Northstar VPN IPv6 guard'

function Get-GuardStatus {
    $profiles = @(Get-NetFirewallProfile -PolicyStore ActiveStore)
    $firewallReady = $profiles.Count -eq 3 -and
        @($profiles | Where-Object { $_.Enabled -ne 'True' -or $_.AllowLocalFirewallRules -eq 'False' }).Count -eq 0
    $rules = @(Get-NetFirewallRule -PolicyStore ActiveStore -Name $name -ErrorAction SilentlyContinue)
    $valid = $false
    if ($rules.Count -eq 1) {
        $rule = $rules[0]
        $addresses = @($rule | Get-NetFirewallAddressFilter)
        $ports = @($rule | Get-NetFirewallPortFilter)
        $apps = @($rule | Get-NetFirewallApplicationFilter)
        $services = @($rule | Get-NetFirewallServiceFilter)
        $interfaces = @($rule | Get-NetFirewallInterfaceFilter)
        $valid = $rule.Group -eq $group -and $rule.Enabled -eq 'True' -and
            $rule.Direction -eq 'Outbound' -and $rule.Action -eq 'Block' -and
            $rule.Profile -eq 'Any' -and
            $addresses.Count -eq 1 -and @($addresses[0].RemoteAddress).Count -eq 2 -and
            $addresses[0].RemoteAddress -contains '::/1' -and $addresses[0].RemoteAddress -contains '8000::/1' -and
            $addresses[0].LocalAddress -eq 'Any' -and
            $ports.Count -eq 1 -and $ports[0].Protocol -eq 'Any' -and
            $apps.Count -eq 1 -and $apps[0].Program -eq 'Any' -and
            $services.Count -eq 1 -and $services[0].Service -eq 'Any' -and
            $interfaces.Count -eq 1 -and $interfaces[0].InterfaceAlias -eq 'Any'
    }
    return @{ blocked = [bool]($firewallReady -and $valid); rule_present = ($rules.Count -gt 0); firewall_ready = [bool]$firewallReady }
}

if ($Action -eq 'Enable') {
    $status = Get-GuardStatus
    if (-not $status.firewall_ready) {
        throw 'IPv6 guard requires Windows Firewall enabled on all profiles and local firewall rules allowed.'
    }
    if (-not $status.blocked) {
        if ($status.rule_present) {
            throw 'The existing Northstar IPv6 rule does not match the required policy. Refusing to connect.'
        }
        New-NetFirewallRule -Name $name -DisplayName 'Northstar VPN - block IPv6 bypass' `
            -Group $group -Direction Outbound -Action Block -Enabled True `
            -Profile Any -Protocol Any -RemoteAddress '::/1','8000::/1' `
            -PolicyStore PersistentStore | Out-Null
    }
    $status = Get-GuardStatus
    if (-not $status.blocked) { throw 'IPv6 block could not be verified in the active firewall policy.' }
} elseif ($Action -eq 'Disable') {
    $rules = @(Get-NetFirewallRule -PolicyStore PersistentStore -Name $name -ErrorAction SilentlyContinue)
    foreach ($rule in $rules) {
        if ($rule.Group -ne $group) { throw 'Refusing to remove a rule not owned by Northstar VPN.' }
        $rule | Remove-NetFirewallRule
    }
    $status = Get-GuardStatus
    if ($status.rule_present) { throw 'The IPv6 guard rule could not be removed.' }
} else {
    $status = Get-GuardStatus
}
$status | ConvertTo-Json -Compress

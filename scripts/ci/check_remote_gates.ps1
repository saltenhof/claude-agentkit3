<#
.SYNOPSIS
    Report the remote quality gates (SonarQube + Jenkins) for this repository.

.DESCRIPTION
    Credentials come from the sources CLAUDE.md declares as the ones that carry:

      * SonarQube -- `.env` in the repo root (`SONAR_HOST_URL`, `SONAR_USER`,
        `SONAR_PASSWORD`). The file is gitignored and is NOT auto-loaded by the
        shell, so this script loads it itself.
      * Jenkins   -- user `admin` plus the API token in
        `var/jenkins-api-token.txt`.

    An already-exported environment variable always wins over the file, so CI
    can override without editing anything.

    Until AG3-218 the script read `$env:SONAR_URL` (a key `.env` does not
    define) and `$env:JENKINS_USER` / `$env:JENKINS_API_TOKEN` sourced from
    `T:\seu\agentkit3-secrets.cmd` -- a machine-local file outside the
    repository. With a clean shell it aborted with "credentials missing"; with a
    stale one Jenkins answered 401. Either way the script failed at
    AUTHENTICATION rather than at the gate, so a red result said nothing about
    the gate at all.

    Jenkins answers an unauthenticated request with 403, not 401. Clients that
    only attach Basic credentials after a 401 challenge -- among them
    `Invoke-RestMethod -Credential` -- therefore never send them. The
    Authorization header below is set preemptively for that reason.
#>
param(
    [string]$SonarUrl,
    [string]$SonarProjectKey,
    [string]$SonarUser,
    [string]$SonarPassword,
    [string]$JenkinsUrl,
    [string]$JenkinsUser,
    [string]$JenkinsPassword
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Get-DotEnvValue([string]$Name) {
    $envPath = Join-Path $repoRoot ".env"
    if (-not (Test-Path -LiteralPath $envPath)) {
        return $null
    }
    foreach ($line in Get-Content -LiteralPath $envPath -Encoding utf8) {
        if ($line -notmatch '^\s*[A-Za-z_]') { continue }
        $parts = $line -split '=', 2
        if ($parts.Count -eq 2 -and $parts[0].Trim() -eq $Name) {
            return $parts[1].Trim()
        }
    }
    return $null
}

function Get-JenkinsToken {
    $tokenPath = Join-Path $repoRoot "var\jenkins-api-token.txt"
    if (-not (Test-Path -LiteralPath $tokenPath)) {
        return $null
    }
    $token = (Get-Content -LiteralPath $tokenPath -Raw -Encoding utf8).Trim()
    if (-not $token) { return $null }
    return $token
}

function Resolve-Setting([string]$Explicit, [string[]]$EnvNames, [scriptblock]$Fallback) {
    if ($Explicit) { return $Explicit }
    foreach ($name in $EnvNames) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value) { return $value }
    }
    if ($Fallback) { return (& $Fallback) }
    return $null
}

$SonarUrl = Resolve-Setting $SonarUrl @("SONAR_HOST_URL") { Get-DotEnvValue "SONAR_HOST_URL" }
if (-not $SonarUrl) { $SonarUrl = "http://localhost:9901" }
if (-not $SonarProjectKey) { $SonarProjectKey = "claude-agentkit3" }
$SonarUser = Resolve-Setting $SonarUser @("SONAR_USER") { Get-DotEnvValue "SONAR_USER" }
$SonarPassword = Resolve-Setting $SonarPassword @("SONAR_PASSWORD") { Get-DotEnvValue "SONAR_PASSWORD" }

if (-not $JenkinsUrl) { $JenkinsUrl = "http://localhost:9900/job/claude-agentkit3/" }
$JenkinsUser = Resolve-Setting $JenkinsUser @("JENKINS_USER") { "admin" }
$JenkinsPassword = Resolve-Setting `
    $JenkinsPassword `
    @("JENKINS_API_TOKEN", "JENKINS_PASSWORD") `
    { Get-JenkinsToken }

function New-BasicAuthHeader([string]$User, [string]$Secret, [string]$Name, [string]$Source) {
    if (-not $User -or -not $Secret) {
        throw "$Name credentials missing. Expected them in $Source."
    }

    $bytes = [Text.Encoding]::UTF8.GetBytes("${User}:${Secret}")
    @{ Authorization = "Basic " + [Convert]::ToBase64String($bytes) }
}

function Invoke-Json([string]$Uri, [hashtable]$Header) {
    # Preemptive header, never -Credential: see the 403-not-401 note above.
    Invoke-RestMethod -Uri $Uri -Headers $Header -TimeoutSec 30
}

$sonarHeader = New-BasicAuthHeader `
    $SonarUser $SonarPassword "Sonar" "SONAR_USER / SONAR_PASSWORD (environment or .env in the repo root)"
$jenkinsHeader = New-BasicAuthHeader `
    $JenkinsUser $JenkinsPassword "Jenkins" "JENKINS_USER / JENKINS_API_TOKEN, or var/jenkins-api-token.txt with user 'admin'"

$sonarBase = $SonarUrl.TrimEnd("/")
$qualityGate = Invoke-Json `
    "$sonarBase/api/qualitygates/project_status?projectKey=$SonarProjectKey" `
    $sonarHeader

$metrics = Invoke-Json `
    "$sonarBase/api/measures/component?component=$SonarProjectKey&metricKeys=violations,critical_violations,security_hotspots" `
    $sonarHeader

$measureMap = @{}
foreach ($measure in $metrics.component.measures) {
    $measureMap[$measure.metric] = [int]$measure.value
}

$jenkinsBase = $JenkinsUrl.TrimEnd("/")
$jenkins = Invoke-Json `
    "$jenkinsBase/api/json?tree=color,lastBuild[number,result,building,url],lastCompletedBuild[number,result,url]" `
    $jenkinsHeader

$jenkinsOk = (
    $jenkins.lastCompletedBuild -and
    $jenkins.lastCompletedBuild.result -eq "SUCCESS" -and
    -not ($jenkins.lastBuild -and $jenkins.lastBuild.building)
)

$summary = [ordered]@{
    sonar_quality_gate = $qualityGate.projectStatus.status
    sonar_violations = $measureMap["violations"]
    sonar_critical_violations = $measureMap["critical_violations"]
    sonar_security_hotspots = $measureMap["security_hotspots"]
    jenkins_color = $jenkins.color
    jenkins_last_build = $jenkins.lastBuild
    jenkins_last_completed_build = $jenkins.lastCompletedBuild
}

$summary | ConvertTo-Json -Depth 8

if ($qualityGate.projectStatus.status -ne "OK") {
    throw "Sonar Quality Gate is $($qualityGate.projectStatus.status)."
}
if ($measureMap["violations"] -ne 0 -or $measureMap["critical_violations"] -ne 0 -or $measureMap["security_hotspots"] -ne 0) {
    throw "Sonar strict metrics are not zero."
}
if (-not $jenkinsOk) {
    throw "Jenkins is not green."
}

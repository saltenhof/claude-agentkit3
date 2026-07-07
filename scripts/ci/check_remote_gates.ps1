param(
    [string]$SonarUrl = $env:SONAR_URL,
    [string]$SonarProjectKey = $env:SONAR_PROJECT_KEY,
    [string]$SonarUser = $env:SONAR_USER,
    [string]$SonarPassword = $env:SONAR_PASSWORD,
    [string]$JenkinsUrl = $env:JENKINS_URL,
    [string]$JenkinsUser = $env:JENKINS_USER,
    [string]$JenkinsPassword = $(if ($env:JENKINS_API_TOKEN) { $env:JENKINS_API_TOKEN } else { $env:JENKINS_PASSWORD })
)

$ErrorActionPreference = "Stop"

if (-not $SonarUrl) { $SonarUrl = "http://localhost:9901" }
if (-not $SonarProjectKey) { $SonarProjectKey = "claude-agentkit3" }
if (-not $JenkinsUrl) { $JenkinsUrl = "http://localhost:9900/job/claude-agentkit3/" }

function New-BasicCredential([string]$User, [string]$Password, [string]$Name) {
    if (-not $User -or -not $Password) {
        throw "$Name credentials missing. Load T:\seu\agentkit3-secrets.cmd or set environment variables."
    }

    $securePassword = ConvertTo-SecureString $Password -AsPlainText -Force
    [pscredential]::new($User, $securePassword)
}

function Invoke-Json([string]$Uri, [pscredential]$Credential) {
    Invoke-RestMethod `
        -Uri $Uri `
        -Credential $Credential `
        -Authentication Basic `
        -AllowUnencryptedAuthentication `
        -TimeoutSec 30
}

$sonarCredential = New-BasicCredential $SonarUser $SonarPassword "Sonar"
$jenkinsCredential = New-BasicCredential $JenkinsUser $JenkinsPassword "Jenkins"

$sonarBase = $SonarUrl.TrimEnd("/")
$qualityGate = Invoke-Json `
    "$sonarBase/api/qualitygates/project_status?projectKey=$SonarProjectKey" `
    $sonarCredential

$metrics = Invoke-Json `
    "$sonarBase/api/measures/component?component=$SonarProjectKey&metricKeys=violations,critical_violations,security_hotspots" `
    $sonarCredential

$measureMap = @{}
foreach ($measure in $metrics.component.measures) {
    $measureMap[$measure.metric] = [int]$measure.value
}

$jenkinsBase = $JenkinsUrl.TrimEnd("/")
$jenkins = Invoke-Json `
    "$jenkinsBase/api/json?tree=color,lastBuild[number,result,building,url],lastCompletedBuild[number,result,url]" `
    $jenkinsCredential

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

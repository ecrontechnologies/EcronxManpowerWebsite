# Ecronx Django integration - end-to-end API test.
# Run:  powershell -File tests\test-django-api.ps1
# Assumes the Django server is running on http://127.0.0.1:8000

$Base = "http://127.0.0.1:8000"
$AdminUser = "admin"
$AdminPass = "EcronxAdmin2026secure"

$script:pass = 0
$script:fail = 0

function Call($method, $path, $body, $token) {
  $headers = @{}
  if ($token) { $headers['Authorization'] = "Bearer $token" }
  try {
    $params = @{
      Uri = "$Base$path"; Method = $method; UseBasicParsing = $true
      TimeoutSec = 15; Headers = $headers
    }
    if ($body) {
      $params['ContentType'] = 'application/json'
      $params['Body'] = ($body | ConvertTo-Json -Compress)
    }
    $r = Invoke-WebRequest @params
    return @{ code = $r.StatusCode; body = $r.Content }
  } catch {
    # Windows PowerShell 5.1 exposes the raw error body on ErrorDetails;
    # the .Response stream is unreliable across PowerShell versions.
    $resp = $_.Exception.Response
    $code = 0
    $text = ''
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
      $text = $_.ErrorDetails.Message
    }
    if ($resp) {
      try { $code = [int]$resp.StatusCode } catch { $code = 0 }
      if (-not $code) {
        try { $code = [int]$resp.StatusCode.value__ } catch { $code = 0 }
      }
      if (-not $text) {
        try {
          if ($resp.PSObject.Methods.Name -contains 'GetResponseStream') {
            $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
            $text = $sr.ReadToEnd()
          } elseif ($resp.Content) {
            $text = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
          }
        } catch { $text = '' }
      }
    }
    if (-not $text) { $text = $_.Exception.Message }
    return @{ code = $code; body = $text }
  }
}

function Assert($label, $condition, $detail) {
  if ($condition) {
    $script:pass++
    Write-Host ("  PASS  " + $label) -ForegroundColor Green
  } else {
    $script:fail++
    Write-Host ("  FAIL  " + $label + "  -> " + $detail) -ForegroundColor Red
  }
}

Write-Host "`n=== 1. Public endpoints ===" -ForegroundColor Cyan
$health = Call GET '/api/health' $null $null
Assert "GET /api/health -> 200" ($health.code -eq 200) "code=$($health.code)"
$content = Call GET '/api/content' $null $null
Assert "GET /api/content -> 200" ($content.code -eq 200) "code=$($content.code)"
$cj = $content.body | ConvertFrom-Json
Assert "content has company name" ([bool]$cj.settings.companyName) "missing"
Assert "content has services" ($cj.services.Count -ge 1) "count=$($cj.services.Count)"

Write-Host "`n=== 2. Authentication & RBAC ===" -ForegroundColor Cyan
$bad = Call POST '/api/admin/login' @{ username = $AdminUser; password = 'definitely-wrong' } $null
Assert "admin login with wrong password -> 401" ($bad.code -eq 401) "code=$($bad.code)"

$empOnAdmin = Call POST '/api/admin/login' @{ username = 'ecx-100'; password = 'whatever' } $null
Assert "employee blocked from admin login -> 401" ($empOnAdmin.code -eq 401) "code=$($empOnAdmin.code)"

$login = Call POST '/api/admin/login' @{ username = $AdminUser; password = $AdminPass } $null
Assert "admin login -> 200" ($login.code -eq 200) "code=$($login.code)"
$token = ($login.body | ConvertFrom-Json).token
Assert "admin token issued" ([bool]$token) "no token"

$noAuth = Call GET '/api/attendance/admin/dashboard' $null $null
Assert "dashboard without token -> 401" ($noAuth.code -eq 401) "code=$($noAuth.code)"

$badToken = Call GET '/api/attendance/admin/dashboard' $null 'not-a-real-token'
Assert "dashboard with invalid token -> 401" ($badToken.code -eq 401) "code=$($badToken.code)"

Write-Host "`n=== 3. Admin dashboard ===" -ForegroundColor Cyan
$dash = Call GET '/api/attendance/admin/dashboard' $null $token
Assert "dashboard with token -> 200" ($dash.code -eq 200) "code=$($dash.code) body=$($dash.body)"
$dj = $dash.body | ConvertFrom-Json
Assert "dashboard returns counts" ($null -ne $dj.counts.employees) "no counts"
Assert "dashboard returns date" ([bool]$dj.date) "no date"

Write-Host "`n=== 4. Employee account management ===" -ForegroundColor Cyan
$uname = "emp-" + (Get-Random -Minimum 1000 -Maximum 9999)
$newEmp = Call POST '/api/attendance/admin/employees' @{
  name = 'Automated Test Employee'; username = $uname
  password = 'StrongPassw0rd!2026'; email = 'auto.test@example.com'
} $token
Assert "create employee -> 201" ($newEmp.code -eq 201) "code=$($newEmp.code) body=$($newEmp.body)"
$emp = $newEmp.body | ConvertFrom-Json
$empId = $emp.employee.id
Assert "employee has uuid" ([bool]$empId) "no id"

$dupe = Call POST '/api/attendance/admin/employees' @{
  name = 'Duplicate'; username = $uname; password = 'StrongPassw0rd!2026'
} $token
Assert "duplicate username -> 409" ($dupe.code -eq 409) "code=$($dupe.code)"

$weak = Call POST '/api/attendance/admin/employees' @{ name = 'Weak'; password = 'short' } $token
Assert "weak password rejected -> 400" ($weak.code -eq 400) "code=$($weak.code)"

Write-Host "`n=== 5. Employee login with new credentials ===" -ForegroundColor Cyan
$empLogin = Call POST '/api/attendance/employee/login' @{ username = $uname; password = 'StrongPassw0rd!2026' } $null
Assert "employee login -> 200" ($empLogin.code -eq 200) "code=$($empLogin.code) body=$($empLogin.body)"
$empToken = ($empLogin.body | ConvertFrom-Json).token
$me = Call GET '/api/attendance/me' $null $empToken
Assert "employee GET /me -> 200" ($me.code -eq 200) "code=$($me.code)"

$empOnAdminApi = Call GET '/api/attendance/admin/dashboard' $null $empToken
Assert "employee blocked from admin API -> 403" ($empOnAdminApi.code -eq 403) "code=$($empOnAdminApi.code)"

Write-Host "`n=== 6. Password change ===" -ForegroundColor Cyan
$chgWrong = Call POST '/api/password/change' @{
  currentPassword = 'wrong-current'; newPassword = 'AnotherPass!2026'; confirmPassword = 'AnotherPass!2026'
} $empToken
Assert "change with wrong current -> 400" ($chgWrong.code -eq 400) "code=$($chgWrong.code)"

$chgOk = Call POST '/api/password/change' @{
  currentPassword = 'StrongPassw0rd!2026'; newPassword = 'AnotherPass!2026'; confirmPassword = 'AnotherPass!2026'
} $empToken
Assert "change password -> 200" ($chgOk.code -eq 200) "code=$($chgOk.code) body=$($chgOk.body)"

$oldLogin = Call POST '/api/attendance/employee/login' @{ username = $uname; password = 'StrongPassw0rd!2026' } $null
Assert "old password no longer works -> 401" ($oldLogin.code -eq 401) "code=$($oldLogin.code)"
$newLogin = Call POST '/api/attendance/employee/login' @{ username = $uname; password = 'AnotherPass!2026' } $null
Assert "new password works -> 200" ($newLogin.code -eq 200) "code=$($newLogin.code)"
$empToken = ($newLogin.body | ConvertFrom-Json).token

$mismatch = Call POST '/api/password/change' @{
  currentPassword = 'AnotherPass!2026'; newPassword = 'XyzPass!2026999'; confirmPassword = 'Different!2026999'
} $empToken
Assert "mismatched confirm rejected -> 400" ($mismatch.code -eq 400) "code=$($mismatch.code)"

Write-Host "`n=== 7. Attendance check-in / check-out ===" -ForegroundColor Cyan
$empToken = ((Call POST '/api/attendance/employee/login' @{ username = $uname; password = 'AnotherPass!2026' } $null).body | ConvertFrom-Json).token
$badLoc = Call POST '/api/attendance/check-in' @{ location = @{ latitude = 999; longitude = 80; accuracy = 10 } } $empToken
Assert "invalid GPS rejected -> 400" ($badLoc.code -eq 400) "code=$($badLoc.code)"

$ci = Call POST '/api/attendance/check-in' @{ location = @{ latitude = 12.8078; longitude = 80.0751; accuracy = 12.5 } } $empToken
Assert "check-in -> 201" ($ci.code -eq 201) "code=$($ci.code) body=$($ci.body)"

$ciDup = Call POST '/api/attendance/check-in' @{ location = @{ latitude = 12.8078; longitude = 80.0751; accuracy = 12.5 } } $empToken
Assert "duplicate check-in -> 409" ($ciDup.code -eq 409) "code=$($ciDup.code)"

$co = Call POST '/api/attendance/check-out' @{ location = @{ latitude = 12.8073; longitude = 80.0749; accuracy = 9.1 } } $empToken
Assert "check-out -> 200" ($co.code -eq 200) "code=$($co.code) body=$($co.body)"

$coDup = Call POST '/api/attendance/check-out' @{ location = @{ latitude = 12.8073; longitude = 80.0749; accuracy = 9.1 } } $empToken
Assert "duplicate check-out -> 409" ($coDup.code -eq 409) "code=$($coDup.code)"

Write-Host "`n=== 8. Correction request + approval ===" -ForegroundColor Cyan
# The API dates records in ATTENDANCE_TIME_ZONE (default Asia/Kolkata), not in the
# server's local time zone. Compute "today" and the timestamps in that same zone,
# otherwise a correction can land on a different date than the one requested.
$tz = [System.TimeZoneInfo]::FindSystemTimeZoneById('India Standard Time')
$nowIst = [System.TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $tz)
$today = $nowIst.ToString('yyyy-MM-dd')
$offset = $tz.GetUtcOffset($nowIst).ToString('hh\:mm')
$checkInIst = "${today}T09:00:00+$offset"
$corr = Call POST '/api/attendance/corrections' @{
  date = $today; checkIn = $checkInIst; note = 'I forgot to check in on time.'
} $empToken
Assert "submit correction -> 201" ($corr.code -eq 201) "code=$($corr.code) body=$($corr.body)"
$corrId = ($corr.body | ConvertFrom-Json).request.id

$noNote = Call POST '/api/attendance/corrections' @{ date = $today } $empToken
Assert "correction without times/note -> 400" ($noNote.code -eq 400) "code=$($noNote.code)"

$review = Call POST "/api/attendance/admin/corrections/$corrId" @{ decision = 'approve' } $token
Assert "admin approves correction -> 200" ($review.code -eq 200) "code=$($review.code) body=$($review.body)"

$reviewAgain = Call POST "/api/attendance/admin/corrections/$corrId" @{ decision = 'reject' } $token
Assert "re-review blocked -> 409" ($reviewAgain.code -eq 409) "code=$($reviewAgain.code)"

Write-Host "`n=== 9. Sites and leave ===" -ForegroundColor Cyan
$site = Call POST '/api/attendance/admin/sites' @{ client = 'Test Client'; name = 'Test Site'; address = '1 Test Road' } $token
Assert "create site -> 201" ($site.code -eq 201) "code=$($site.code)"

$badLeave = Call POST '/api/attendance/admin/leave' @{ employeeId = 'not-a-uuid'; date = $today } $token
Assert "leave with malformed employee id -> 400" ($badLeave.code -eq 400) "code=$($badLeave.code)"

$missingLeave = Call POST '/api/attendance/admin/leave' @{ employeeId = '00000000-0000-4000-8000-000000000000'; date = $today } $token
Assert "leave with unknown employee -> 404" ($missingLeave.code -eq 404) "code=$($missingLeave.code)"

$leaveEmp = Call POST '/api/attendance/admin/employees' @{
  name = 'Leave Test'; username = "leave-$uname"; password = 'StrongPassw0rd!2026'
} $token
$leaveEmpId = ($leaveEmp.body | ConvertFrom-Json).employee.id
$leave = Call POST '/api/attendance/admin/leave' @{ employeeId = $leaveEmpId; date = $today; note = 'Approved sick leave' } $token
Assert "mark leave -> 200" ($leave.code -eq 200) "code=$($leave.code) body=$($leave.body)"

Write-Host "`n=== 10. Reports / backups ===" -ForegroundColor Cyan
foreach ($fmt in @('json', 'csv', 'pdf')) {
  $from = [System.TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow.AddDays(-30), $tz).ToString('yyyy-MM-dd')
  $to = [System.TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $tz).ToString('yyyy-MM-dd')
  $rep = Call GET "/api/attendance/admin/backup?from=$from&to=$to&format=$fmt" $null $token
  Assert "backup $fmt -> 200" ($rep.code -eq 200) "code=$($rep.code)"
  Assert "backup $fmt has content" ([bool]$rep.body) "empty"
}
$badRange = Call GET "/api/attendance/admin/backup?from=2026-01-01&to=2025-01-01&format=json" $null $token
Assert "backup with reversed range -> 400" ($badRange.code -eq 400) "code=$($badRange.code)"

Write-Host "`n=== 11. Password recovery flow (admin) ===" -ForegroundColor Cyan
$req = Call POST '/api/password/reset/request' @{ username = 'admin'; role = 'admin' } $null
Assert "reset request -> 200" ($req.code -eq 200) "code=$($req.code) body=$($req.body)"

$unknown = Call POST '/api/password/reset/request' @{ username = 'no-such-user-xyz'; role = 'admin' } $null
Assert "unknown user reset -> 200 (no enumeration)" ($unknown.code -eq 200) "code=$($unknown.code)"

$badCode = Call POST '/api/password/reset/verify' @{ username = 'admin'; code = '000000' } $null
Assert "wrong code rejected -> 400" ($badCode.code -eq 400) "code=$($badCode.code)"

$noTicket = Call POST '/api/password/reset/confirm' @{
  username = 'admin'; code = '000000'; ticket = 'fake'; newPassword = 'NewAdminPass!2026'; confirmPassword = 'NewAdminPass!2026'
} $null
Assert "confirm without valid ticket -> 400" ($noTicket.code -eq 400) "code=$($noTicket.code)"

Write-Host "`n=== 12. Admin employee management (update / reset / delete) ===" -ForegroundColor Cyan
$upd = Call PATCH "/api/attendance/admin/employees/$empId" @{ name = 'Renamed Employee' } $token
Assert "update employee name -> 200" ($upd.code -eq 200) "code=$($upd.code)"

$deact = Call PATCH "/api/attendance/admin/employees/$empId" @{ active = $false } $token
Assert "deactivate employee -> 200" ($deact.code -eq 200) "code=$($deact.code)"
$deactLogin = Call POST '/api/attendance/employee/login' @{ username = $uname; password = 'AnotherPass!2026' } $null
Assert "deactivated employee cannot log in -> 401" ($deactLogin.code -eq 401) "code=$($deactLogin.code)"

$react = Call PATCH "/api/attendance/admin/employees/$empId" @{ active = $true } $token
Assert "reactivate employee -> 200" ($react.code -eq 200) "code=$($react.code)"

$resetPw = Call POST "/api/attendance/admin/employees/$empId/password" @{ newPassword = 'AdminSetPass!2026' } $token
Assert "admin resets employee password -> 200" ($resetPw.code -eq 200) "code=$($resetPw.code) body=$($resetPw.body)"
$afterReset = Call POST '/api/attendance/employee/login' @{ username = $uname; password = 'AdminSetPass!2026' } $null
Assert "employee logs in with admin-set password -> 200" ($afterReset.code -eq 200) "code=$($afterReset.code)"

$del = Call DELETE "/api/attendance/admin/employees/$empId" $null $token
Assert "delete employee -> 200" ($del.code -eq 200) "code=$($del.code)"
$delLogin = Call POST '/api/attendance/employee/login' @{ username = $uname; password = 'AdminSetPass!2026' } $null
Assert "deleted employee cannot log in -> 401" ($delLogin.code -eq 401) "code=$($delLogin.code)"

Write-Host "`n=== 13. Logout ===" -ForegroundColor Cyan
$empForLogout = Call POST '/api/attendance/employee/login' @{ username = "leave-$uname"; password = 'StrongPassw0rd!2026' } $null
$eTok = ($empForLogout.body | ConvertFrom-Json).token
$out = Call POST '/api/attendance/employee/logout' $null $eTok
Assert "employee logout -> 200" ($out.code -eq 200) "code=$($out.code)"
$afterOut = Call GET '/api/attendance/me' $null $eTok
Assert "token invalid after logout -> 401" ($afterOut.code -eq 401) "code=$($afterOut.code)"

Write-Host "`n=============================" -ForegroundColor Cyan
Write-Host ("RESULT: " + $script:pass + " passed, " + $script:fail + " failed") -ForegroundColor $(if ($script:fail -eq 0) { 'Green' } else { 'Red' })
Write-Host "=============================`n" -ForegroundColor Cyan
if ($script:fail -gt 0) { exit 1 }
